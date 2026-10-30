"""cfg: install claude-config v2 into a Claude home, per machine.

    cfg.py plan     [--host NAME]   show what a deploy would change
    cfg.py deploy   [--host NAME] [--yes] [--force]
    cfg.py status                   compare the live config with the last deploy
    cfg.py rollback                 undo the last deploy

A deploy copies the host's skills and hooks into the Claude home, merges the
hook entries, plugins and marketplaces into settings.json, and keeps the global
rules in a marked block of CLAUDE.md (OMC keeps its own block in the same file).
Everything it owns is listed, with hashes, in <home>/claude-config/state.json.
Without --yes, deploy only prints the plan.

A deploy with --yes also keeps the sync clone: a clone of this repo's main, made once in
$XDG_DATA_HOME/claude-config (default ~/.local/share/claude-config) from this checkout, with
origin set to this checkout's origin, and recorded as syncClone in state.json. The auto_sync
hook fetches main into it at each new session and deploys it from there (ADR-0007). Without an
origin the deploy still runs, with a warning, and auto sync stays off. status also shows the
last line of <home>/claude-config/sync.log, where the hook logs a failed sync.

The Claude home is --target, else $CLAUDE_CONFIG_DIR, else ~/.claude.
Standard library only: it runs on a machine with nothing installed but Python.
"""

import argparse
import copy
import hashlib
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
START = "<!-- CLAUDE-CONFIG:START -->"
END = "<!-- CLAUDE-CONFIG:END -->"
KEEP_BACKUPS = 5
NAME = re.compile(r"[a-z0-9][a-z0-9_.-]{0,63}")
MANAGED = ("settings.json", "CLAUDE.md", "claude-config/state.json")


class CfgError(Exception):
    """A problem the user can fix; main() prints it and exits 2."""


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def read_json(path: Path) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    except ValueError as err:
        raise CfgError(f"{path} is not valid JSON: {err}") from err
    if not isinstance(data, dict):
        raise CfgError(f"{path} must hold a JSON object")
    return data


def write_atomic(path: Path, data: bytes, follow: bool = False) -> None:
    """Replace `path` in one step through an unpredictable temp file, keeping its mode.

    A symlink at `path` is replaced by the new file, unless `follow` is set (settings.json and
    CLAUDE.md, which a dotfiles manager may link): then the file it points at is replaced.
    """
    if follow and path.is_symlink():
        path = path.resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".cfg-tmp")
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        if path.exists() and not path.is_symlink():
            os.chmod(name, path.stat().st_mode & 0o7777)
        os.replace(name, path)
    except BaseException:
        Path(name).unlink(missing_ok=True)
        raise


def safe_rel(home: Path, rel: object) -> str:
    """`rel` if it names a file cfg may touch inside `home`; CfgError otherwise.

    state.json and the backups' created.json sit in a directory other tools can write, so their
    paths are checked before cfg deletes or overwrites anything.
    """
    if not isinstance(rel, str) or not rel:
        raise CfgError(f"refusing path {rel!r}")
    path = Path(rel)
    inside = rel in MANAGED or (path.parts[0] in ("skills", "hooks") and len(path.parts) > 1)
    if path.is_absolute() or ".." in path.parts or not inside:
        raise CfgError(f"refusing path outside cfg's files: {rel!r}")
    if not (home / path).resolve().is_relative_to(home.resolve()):
        raise CfgError(f"refusing path that escapes the Claude home through a link: {rel!r}")
    return rel


def dump(obj: dict) -> bytes:
    return (json.dumps(obj, indent=2, ensure_ascii=False) + "\n").encode()


def claude_home(arg: str | None) -> Path:
    return Path(arg or os.environ.get("CLAUDE_CONFIG_DIR") or Path.home() / ".claude")


# --- the host profile and what it selects -------------------------------------


def load_host(name: str) -> dict:
    if not NAME.fullmatch(name):
        raise CfgError(f"invalid host name {name!r}")
    path = ROOT / "hosts" / f"{name}.json"
    if not path.is_file():
        known = ", ".join(sorted(p.stem for p in (ROOT / "hosts").glob("*.json")))
        raise CfgError(f"no host profile '{name}' (have: {known})")
    host = read_json(path)
    if host.get("name") != name:
        raise CfgError(f"{path}: 'name' must be '{name}'")
    for item in [*host.get("skills", []), *host.get("hooks", [])]:
        if not isinstance(item, str) or not NAME.fullmatch(item) or item in (".", ".."):
            raise CfgError(f"{path}: invalid skill or hook name {item!r}")
    for skill in host.get("skills", []):
        if not (ROOT / "config" / "skills" / skill / "SKILL.md").is_file():
            raise CfgError(f"{path}: skill '{skill}' has no config/skills/{skill}/SKILL.md")
    for hook in host.get("hooks", []):
        if not (ROOT / "config" / "hooks" / hook).is_file():
            raise CfgError(f"{path}: hook '{hook}' is not in config/hooks/")
    return host


# Path parts that never ship: bytecode caches and OMC runtime state.
SKIP_PARTS = frozenset({"__pycache__", ".omc"})


def desired_files(host: dict) -> dict[str, bytes]:
    """Relative path under the Claude home -> content, for every copied file."""
    files: dict[str, bytes] = {}
    for skill in host.get("skills", []):
        base = ROOT / "config" / "skills" / skill
        for path in sorted(p for p in base.rglob("*") if p.is_file() and SKIP_PARTS.isdisjoint(p.relative_to(base).parts)):
            files[f"skills/{skill}/{path.relative_to(base).as_posix()}"] = path.read_bytes()
    for hook in host.get("hooks", []):
        files[f"hooks/{hook}"] = (ROOT / "config" / "hooks" / hook).read_bytes()
    return files


def merge_settings(old: dict, host: dict, home: Path, previous: list[str]) -> tuple[dict, list[str]]:
    """The settings with our hook entries replaced, plus the commands we own now."""
    fragment = json.loads((ROOT / "config" / "settings.fragment.json").read_text(encoding="utf-8"))
    new = copy.deepcopy(old)
    hooks = new.setdefault("hooks", {})
    if not isinstance(hooks, dict) or not all(isinstance(v, list) for v in hooks.values()):
        raise CfgError("settings.json: 'hooks' must map event names to lists")
    quoted = shlex.quote(str(home))
    wanted = set(host.get("hooks", []))
    plan: list[tuple[str, dict, list[dict]]] = []
    commands: list[str] = []
    for event, groups in fragment["hooks"].items():
        for group in groups:
            entries = []
            for entry in group["hooks"]:
                if Path(entry["command"].split()[-1]).name in wanted:
                    command = entry["command"].replace("{claude_home}", quoted)
                    entries.append({**entry, "command": command})
                    if command not in commands:
                        commands.append(command)
            if entries:
                plan.append((event, group, entries))
    ours = {*previous, *commands}  # also drops copies left by a deploy that failed part-way
    for event in list(hooks):
        groups = []
        for group in hooks[event]:
            kept = [h for h in group.get("hooks", []) if h.get("command") not in ours]
            if kept:
                groups.append({**group, "hooks": kept})
        if groups:
            hooks[event] = groups
        else:
            del hooks[event]
    for event, group, entries in plan:
        hooks.setdefault(event, []).append({**group, "hooks": entries})
    if not hooks:
        del new["hooks"]
    for plugin in host.get("plugins", []):
        new.setdefault("enabledPlugins", {})[plugin] = True
    for name, market in host.get("marketplaces", {}).items():
        new.setdefault("extraKnownMarketplaces", {}).setdefault(name, market)
    return new, commands


def find_block(text: str) -> tuple[int, int] | None:
    """Offsets of our block (START line through END line), None if absent; CfgError if damaged."""
    lines = text.split("\n")
    starts = [i for i, line in enumerate(lines) if line.strip() == START]
    ends = [i for i, line in enumerate(lines) if line.strip() == END]
    if not starts and not ends:
        return None
    if len(starts) != 1 or len(ends) != 1 or starts[0] > ends[0]:
        raise CfgError(
            f"CLAUDE.md: expected one {START} line followed by one {END} line; fix or remove them"
        )
    begin = sum(len(line) + 1 for line in lines[: starts[0]])
    finish = sum(len(line) + 1 for line in lines[: ends[0] + 1]) - 1
    return begin, finish


def merge_claude_md(old: str) -> str:
    body = (ROOT / "config" / "CLAUDE.global.md").read_text(encoding="utf-8").strip()
    block = f"{START}\n{body}\n{END}"
    found = find_block(old)
    if found:
        return old[: found[0]] + block + old[found[1] :]
    return (old.rstrip("\n") + "\n\n" if old.strip() else "") + block + "\n"


def remove_block(text: str) -> str:
    found = find_block(text)
    if not found:
        return text
    return (text[: found[0]].rstrip("\n") + "\n" + text[found[1] :].lstrip("\n")).lstrip("\n")


# --- plan, deploy, status, rollback ------------------------------------------


class Plan:
    def __init__(self, home: Path, host: dict):
        self.home, self.host = home, host
        self.state_dir = home / "claude-config"
        self.state = read_json(self.state_dir / "state.json")
        self.recorded: dict[str, str] = {
            safe_rel(home, rel): digest for rel, digest in self.state.get("files", {}).items()
        }
        self.want = desired_files(host)
        for rel in self.want:
            safe_rel(home, rel)
        self.add, self.update, self.remove, self.conflicts = [], [], [], []
        for rel, data in self.want.items():
            live = home / rel
            if not live.exists():
                self.add.append(rel)
            elif live.read_bytes() != data:
                self.update.append(rel)
                if self.recorded.get(rel) != sha(live.read_bytes()):
                    self.conflicts.append(rel)
        for rel in self.recorded:
            if rel not in self.want and (home / rel).exists():
                self.remove.append(rel)
                if sha((home / rel).read_bytes()) != self.recorded[rel]:
                    self.conflicts.append(rel)
        settings, self.commands = merge_settings(
            read_json(home / "settings.json"), host, home, self.state.get("hookCommands", [])
        )
        self.settings = dump(settings)
        old_md = read_text(home / "CLAUDE.md") if (home / "CLAUDE.md").exists() else ""
        self.claude_md = merge_claude_md(old_md).encode()
        self.clone = self.state.get("syncClone")  # main() sets it before a deploy
        self.settings_changed = self.settings != _read(home / "settings.json")
        self.claude_md_changed = self.claude_md != _read(home / "CLAUDE.md")

    def lines(self) -> list[str]:
        out = [f"host {self.host['name']} -> {self.home}"]
        for label, rels in (("add", self.add), ("update", self.update), ("remove", self.remove)):
            out += [f"  {label:7}{rel}" + ("   CONFLICT (live file changed since last deploy)" if rel in self.conflicts else "") for rel in rels]
        out += [f"  merge  {name}" for name, changed in (("settings.json", self.settings_changed), ("CLAUDE.md", self.claude_md_changed)) if changed]
        if self.state and (self.host["name"], self.host.get("defaultTracker")) != (
            self.state.get("host"), self.state.get("defaultTracker")
        ):
            out.append("  record  host and default tracker in state.json")
        if len(out) == 1:
            out.append("  nothing to change")
        return out

    def changes(self) -> bool:
        identity = (self.host["name"], self.host.get("defaultTracker"))
        if identity != (self.state.get("host"), self.state.get("defaultTracker")):
            return True  # same files, different machine role: state.json must still be rewritten
        if self.clone != self.state.get("syncClone"):
            return True  # a new sync clone must still be recorded
        return bool(self.add or self.update or self.remove or self.settings_changed or self.claude_md_changed)


def read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except UnicodeDecodeError as err:
        raise CfgError(f"{path} is not UTF-8 text") from err


def _read(path: Path) -> bytes:
    return path.read_bytes() if path.exists() else b""


def new_backup_dir(state_dir: Path) -> Path:
    """backups/<UTC time>-<counter>: names sort in creation order, whatever the local clock does."""
    stamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    root = state_dir / "backups"
    n = 1
    while (root / f"{stamp}-{n:03d}").exists():
        n += 1
    return root / f"{stamp}-{n:03d}"


def deploy(plan: Plan) -> None:
    home = plan.home
    managed = ["settings.json", "CLAUDE.md", "claude-config/state.json"]
    touched = [*plan.update, *plan.remove, *managed]
    created = [rel for rel in [*plan.add, *managed] if not (home / rel).exists()]
    final = new_backup_dir(plan.state_dir)
    work = final.with_name(final.name + ".partial")
    (work / "files").mkdir(parents=True)
    (work / "created.json").write_text(json.dumps(created))
    for rel in touched:
        if (home / rel).exists():
            dest = work / "files" / rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(home / rel, dest)
    work.rename(final)  # a backup either exists whole or not at all
    for rel in plan.remove:
        (home / rel).unlink()
        _prune_dirs((home / rel).parent, home)
    for rel in [*plan.add, *plan.update]:
        write_atomic(home / rel, plan.want[rel])
        if rel.startswith("hooks/"):
            (home / rel).chmod(0o755)
    write_atomic(home / "settings.json", plan.settings, follow=True)
    write_atomic(home / "CLAUDE.md", plan.claude_md, follow=True)
    state = {
        "host": plan.host["name"],
        "defaultTracker": plan.host.get("defaultTracker"),
        "files": {rel: sha(data) for rel, data in plan.want.items()},
        "hookCommands": plan.commands,
        "settingsSha": sha(plan.settings),
        "claudeMdSha": sha(plan.claude_md),
        "deployedAt": final.name,
        **({"syncClone": plan.clone} if plan.clone else {}),
    }
    write_atomic(plan.state_dir / "state.json", dump(state))
    old = sorted(p for p in (plan.state_dir / "backups").iterdir() if p.is_dir())
    for stale in old[:-KEEP_BACKUPS]:
        shutil.rmtree(stale)


def _prune_dirs(path: Path, stop: Path) -> None:
    while path != stop and path.is_dir() and not any(path.iterdir()):
        path.rmdir()
        path = path.parent


def rollback(home: Path) -> list[str]:
    """Undo the last deploy. Returns notes for the user.

    settings.json and CLAUDE.md are restored whole only if nothing else has changed them since the
    deploy (other tools write to both). Otherwise only our own hook entries and our CLAUDE.md block
    are removed, and everything else in the files stays.
    """
    backups = home / "claude-config" / "backups"
    found = sorted(p for p in backups.iterdir() if p.is_dir() and not p.name.endswith(".partial")) if backups.is_dir() else []
    if not found:
        raise CfgError("no backup to roll back to")
    latest = found[-1]
    if not (latest / "created.json").is_file():
        raise CfgError(f"backup {latest.name} is incomplete; delete it to roll back to the one before")
    state = read_json(home / "claude-config" / "state.json")
    try:
        created = {safe_rel(home, rel) for rel in json.loads((latest / "created.json").read_text())}
    except (ValueError, TypeError) as err:
        raise CfgError(f"backup {latest.name} is damaged: {err}") from err
    notes: list[str] = []
    shared = {
        "settings.json": (state.get("settingsSha"), lambda text: unmerge_settings(text, state)),
        "CLAUDE.md": (state.get("claudeMdSha"), remove_block),
    }
    for rel, (digest, strip) in shared.items():
        live = home / rel
        if live.exists() and digest and sha(live.read_bytes()) != digest:
            write_atomic(live, strip(read_text(live)).encode(), follow=True)
            created.discard(rel)
            (latest / "files" / rel).unlink(missing_ok=True)
            notes.append(f"{rel} changed after the deploy: removed only claude-config's part")
    for rel in sorted(created):
        (home / rel).unlink(missing_ok=True)
        _prune_dirs((home / rel).parent, home)
    files = latest / "files"
    for path in sorted(p for p in files.rglob("*") if p.is_file()):
        dest = home / path.relative_to(files)
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, dest)
    shutil.rmtree(latest)
    return [latest.name, *notes]


def unmerge_settings(text: str, state: dict) -> str:
    """The settings text without the hook entries the last deploy added."""
    try:
        data = json.loads(text) if text.strip() else {}
    except ValueError as err:
        raise CfgError(f"settings.json is not valid JSON: {err}") from err
    if not isinstance(data, dict) or not isinstance(data.get("hooks", {}), dict):
        raise CfgError("settings.json must hold an object with an object under 'hooks'")
    ours = set(state.get("hookCommands", []))
    hooks = data.get("hooks", {})
    for event in list(hooks):
        groups = []
        for group in hooks[event]:
            kept = [h for h in group.get("hooks", []) if h.get("command") not in ours]
            if kept:
                groups.append({**group, "hooks": kept})
        if groups:
            hooks[event] = groups
        else:
            del hooks[event]
    if not hooks:
        data.pop("hooks", None)
    return dump(data).decode()


def status(home: Path) -> list[str]:
    state = read_json(home / "claude-config" / "state.json")
    if not state:
        return [f"{home}: no deploy recorded"]
    out = [f"{home}: host {state.get('host')}, deployed {state.get('deployedAt')}"]
    for rel, digest in sorted(state.get("files", {}).items()):
        live = home / rel
        if not live.exists():
            out.append(f"  missing   {rel}")
        elif sha(live.read_bytes()) != digest:
            out.append(f"  modified  {rel}")
    host = load_host(state.get("host", ""))
    pending = Plan(home, host)
    out += [f"  pending   {line.strip()}" for line in pending.lines()[1:] if "nothing to change" not in line]
    if len(out) == 1:
        out.append("  in sync")
    log = home / "claude-config" / "sync.log"
    lines = read_text(log).splitlines() if log.is_file() else []
    if lines:
        out.append(f"  last sync failure: {lines[-1]}")
    return out


def sync_clone() -> str | None:
    """The path of the clone auto sync deploys from, made from this checkout on first use.

    None, after a warning, when it can't be made: the deploy goes on without auto sync.
    """
    data = os.environ.get("XDG_DATA_HOME")
    base = Path(data) if data and os.path.isabs(data) else Path.home() / ".local" / "share"
    clone = base / "claude-config"
    if ROOT.resolve() == clone.resolve() or (clone / ".git").is_dir():
        return str(clone)
    warning = "warning: auto sync stays off on this machine:"
    if clone.exists():
        print(f"{warning} {clone} exists and is not a git clone")
        return None
    if not (ROOT / ".git").exists():
        print(f"{warning} {ROOT} is not a git checkout")
        return None
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    env["GIT_TERMINAL_PROMPT"] = "0"

    def git(*args: str) -> subprocess.CompletedProcess:
        return subprocess.run(["git", *args], env=env, capture_output=True, text=True, check=False)

    url = git("-C", str(ROOT), "remote", "get-url", "origin").stdout.strip()
    if not url:
        print(f"{warning} this checkout has no origin remote")
        return None
    clone.parent.mkdir(parents=True, exist_ok=True)
    work = Path(tempfile.mkdtemp(dir=clone.parent, prefix=".claude-config."))
    try:
        made = (
            git("clone", "--quiet", "--branch", "main", "--", str(ROOT), str(work)).returncode == 0
            and git("-C", str(work), "remote", "set-url", "origin", url).returncode == 0
        )
        if made:
            work.rename(clone)  # the clone appears whole or not at all
    finally:
        if work.exists():
            shutil.rmtree(work)
    if not made:
        print(f"{warning} could not clone this checkout's main branch to {clone}")
        return None
    print(f"sync clone: {clone}")
    return str(clone)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="cfg", description=__doc__.split("\n\n")[0])
    parser.add_argument("command", choices=["plan", "deploy", "status", "rollback"])
    parser.add_argument("--host", help="host profile name (default: the one last deployed)")
    parser.add_argument("--target", help="Claude home (default: $CLAUDE_CONFIG_DIR or ~/.claude)")
    parser.add_argument("--yes", action="store_true", help="deploy: apply the plan")
    parser.add_argument("--force", action="store_true", help="deploy: overwrite conflicting files (backed up)")
    args = parser.parse_args(argv)
    home = claude_home(args.target)
    try:
        if args.command == "status":
            print("\n".join(status(home)))
            return 0
        if args.command == "rollback":
            name, *notes = rollback(home)
            print("\n".join([f"rolled back {name}", *notes]))
            return 0
        name = args.host or read_json(home / "claude-config" / "state.json").get("host")
        if not name:
            raise CfgError("first deploy on this machine needs --host NAME")
        plan = Plan(home, load_host(name))
        print("\n".join(plan.lines()))
        if args.command == "plan" or not args.yes:
            if args.command == "deploy":
                print("dry run: add --yes to apply")
            return 1 if plan.conflicts else 0
        if plan.conflicts and not args.force:
            print("stopped: conflicts above; pass --force to overwrite them (they are backed up)")
            return 1
        plan.clone = sync_clone()
        if not plan.changes():
            return 0  # no backup for a deploy that changes nothing
        deploy(plan)
        print("deployed; undo with: cfg.py rollback")
        return 0
    except CfgError as err:
        print(f"cfg: {err}", file=sys.stderr)
        return 2
    except OSError as err:
        print(f"cfg: {err}; if a deploy stopped part-way, run: cfg.py rollback", file=sys.stderr)
        return 3


if __name__ == "__main__":
    sys.exit(main())
