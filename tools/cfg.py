#!/usr/bin/env python3
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

The Claude home is --target, else $CLAUDE_CONFIG_DIR, else ~/.claude.
Standard library only: it runs on a machine with nothing installed but Python.
"""

import argparse
import copy
import hashlib
import json
import os
import shlex
import shutil
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
START = "<!-- CLAUDE-CONFIG:START -->"
END = "<!-- CLAUDE-CONFIG:END -->"
KEEP_BACKUPS = 5


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


def write_atomic(path: Path, data: bytes) -> None:
    """Replace `path` (or the file a symlink points at) in one step, keeping its mode."""
    path = path.resolve() if path.is_symlink() else path
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".cfg-tmp")
    tmp.write_bytes(data)
    if path.exists():
        tmp.chmod(path.stat().st_mode & 0o7777)
    os.replace(tmp, path)


def dump(obj: dict) -> bytes:
    return (json.dumps(obj, indent=2, ensure_ascii=False) + "\n").encode()


def claude_home(arg: str | None) -> Path:
    return Path(arg or os.environ.get("CLAUDE_CONFIG_DIR") or Path.home() / ".claude")


# --- the host profile and what it selects -------------------------------------


def load_host(name: str) -> dict:
    path = ROOT / "hosts" / f"{name}.json"
    if not path.is_file():
        known = ", ".join(sorted(p.stem for p in (ROOT / "hosts").glob("*.json")))
        raise CfgError(f"no host profile '{name}' (have: {known})")
    host = read_json(path)
    if host.get("name") != name:
        raise CfgError(f"{path}: 'name' must be '{name}'")
    for skill in host.get("skills", []):
        if not (ROOT / "config" / "skills" / skill / "SKILL.md").is_file():
            raise CfgError(f"{path}: skill '{skill}' has no config/skills/{skill}/SKILL.md")
    for hook in host.get("hooks", []):
        if not (ROOT / "config" / "hooks" / hook).is_file():
            raise CfgError(f"{path}: hook '{hook}' is not in config/hooks/")
    return host


def desired_files(host: dict) -> dict[str, bytes]:
    """Relative path under the Claude home -> content, for every copied file."""
    files: dict[str, bytes] = {}
    for skill in host.get("skills", []):
        base = ROOT / "config" / "skills" / skill
        for path in sorted(p for p in base.rglob("*") if p.is_file() and "__pycache__" not in p.parts):
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
        self.recorded: dict[str, str] = self.state.get("files", {})
        self.want = desired_files(host)
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
        old_md = (home / "CLAUDE.md").read_text(encoding="utf-8") if (home / "CLAUDE.md").exists() else ""
        self.claude_md = merge_claude_md(old_md).encode()
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
        return bool(self.add or self.update or self.remove or self.settings_changed or self.claude_md_changed)


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
    write_atomic(home / "settings.json", plan.settings)
    write_atomic(home / "CLAUDE.md", plan.claude_md)
    state = {
        "host": plan.host["name"],
        "defaultTracker": plan.host.get("defaultTracker"),
        "files": {rel: sha(data) for rel, data in plan.want.items()},
        "hookCommands": plan.commands,
        "settingsSha": sha(plan.settings),
        "claudeMdSha": sha(plan.claude_md),
        "deployedAt": final.name,
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
    created = set(json.loads((latest / "created.json").read_text()))
    notes: list[str] = []
    shared = {
        "settings.json": (state.get("settingsSha"), lambda text: unmerge_settings(text, state)),
        "CLAUDE.md": (state.get("claudeMdSha"), remove_block),
    }
    for rel, (digest, strip) in shared.items():
        live = home / rel
        if live.exists() and digest and sha(live.read_bytes()) != digest:
            write_atomic(live, strip(live.read_text(encoding="utf-8")).encode())
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
    data = json.loads(text) if text.strip() else {}
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
    return out


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
