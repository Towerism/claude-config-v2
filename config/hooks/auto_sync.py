"""SessionStart hook (matcher startup): bring the deployed config up to date with main on origin.

`cfg.py deploy --yes` keeps a dedicated clone of claude-config and records it as `syncClone` in
<claude home>/claude-config/state.json (ADR-0007). At each new session this hook fetches main
into that clone, fast-forwards it, removes untracked files from it, and runs the clone's
`cfg.py deploy --yes --force` for the recorded host. A file edited by hand in the Claude home is
overwritten and backed up first; `cfg.py rollback` restores it.

It does nothing, and runs no git, when $XDG_CONFIG_HOME/claude-config/local.json (or
~/.config/claude-config/local.json) sets "autoSync": false, or when no clone is recorded. It
skips quietly while another run holds <home>/claude-config/sync.lock; the deploy inherits the
lock, so it stays held until the deploy ends even if this hook is killed. The fetch has
FETCH_SECONDS and each local git step LOCAL_SECONDS; a deploy that has started always runs to
the end, in its own session. The clone, its tools/ and tools/cfg.py must belong to this user and
not be group- or world-writable, or nothing is run.

On success it prints nothing, or only reloadSkills when the deploy changed something, so nothing
enters the model's context. On failure a line with the UTC time and a fixed reason goes to
<home>/claude-config/sync.log (the last LOG_LINES are kept), and the user sees a fixed one-line
systemMessage. Before the deploy writes anything, the current config stays. A deploy that fails
after its backup is rolled back with the clone's `cfg.py rollback`; if that fails too, the
message says the config may be partly updated.

The Claude home is two levels above this file (<home>/hooks/auto_sync.py). git runs by absolute
path from a fixed PATH with a fixed argv and environment: no GIT_* variables from the session,
no SSH_ASKPASS, GIT_TERMINAL_PROMPT=0, ssh in BatchMode (GIT_SSH_COMMAND, which overrides
core.sshCommand), and GIT_ATTR_NOSYSTEM=1. These settings are overridden on the command line:
core.fsmonitor, core.hooksPath, core.gitProxy, core.askPass, core.attributesFile,
protocol.ext.allow, remote.origin.uploadpack, submodule.recurse, fetch.recurseSubmodules, gc.auto
and maintenance.auto. The user's ssh-agent and credential helper still work if they are found on
that PATH. Filters named by the repo's own .gitattributes are not overridden; claude-config has
none. Prints only fixed words, always exits 0 and writes nothing to stderr.
"""

import contextlib
import fcntl
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import time
from pathlib import Path

FETCH_SECONDS = 15
LOCAL_SECONDS = 10  # each local git step, so a stuck clone cannot hold the session start
LOG_LINES = 200
CAP = 64 * 1024
SAFE_PATH = "/usr/local/bin:/usr/bin:/bin"  # git is looked up here, never on the caller's PATH
NAME = re.compile(r"[a-z0-9][a-z0-9_.-]{0,63}")  # a host name, as cfg.py checks it
GIT_FLAGS = [
    "--no-optional-locks",
    "-c", "core.fsmonitor=false", "-c", "core.hooksPath=/dev/null", "-c", "core.gitProxy=",
    "-c", "core.askPass=", "-c", "core.attributesFile=/dev/null", "-c", "protocol.ext.allow=never",
    "-c", "remote.origin.uploadpack=git-upload-pack", "-c", "submodule.recurse=false",
    "-c", "fetch.recurseSubmodules=false", "-c", "gc.auto=0", "-c", "maintenance.auto=false",
]
MAIN = "+refs/heads/main:refs/remotes/origin/main"
RELOAD = {"hookSpecificOutput": {"hookEventName": "SessionStart", "reloadSkills": True}}
LOGGED = " The reason is logged in claude-config/sync.log in the Claude home."
STAYS = "claude-config auto sync failed ({reason}); the current config stays." + LOGGED
MESSAGES = {
    "diverged": STAYS + " To repair the sync clone, run make deploy YES=1 in a claude-config checkout.",
    "deploy-rolled-back": "claude-config auto sync failed during the deploy ({reason}); the deploy was rolled back." + LOGGED,
    "deploy-failed-partial": (
        "claude-config auto sync failed during the deploy ({reason}) and could not roll it back; the config "
        "may be partly updated. Run make rollback in a claude-config checkout." + LOGGED
    ),
}


class Failure(Exception):
    """A sync that stopped; args[0] is one of the fixed reason words."""


def read_json(path: Path) -> dict:
    """The JSON object in `path`; {} when it is missing, too big or not an object."""
    try:
        if not path.is_file() or path.stat().st_size > CAP:
            return {}
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def environment() -> dict:
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_") and k != "SSH_ASKPASS"}
    env.update(
        PATH=SAFE_PATH, GIT_TERMINAL_PROMPT="0", GIT_SSH_COMMAND="ssh -o BatchMode=yes", GIT_ATTR_NOSYSTEM="1"
    )
    return env


def run(argv: list[str], cwd: str, seconds: float | None, keep: tuple[int, ...] = ()) -> int | None:
    """The exit code of `argv`, or None once `seconds` pass; its output is discarded.

    It runs in its own session: past the deadline the whole group (git and its ssh) is killed,
    and a kill aimed at this hook's group never reaches a deploy under way. `keep` are file
    descriptors it inherits (the lock). Files it writes are not group- or world-writable.
    """
    proc = subprocess.Popen(
        argv, cwd=cwd, env=environment(), stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL, start_new_session=True, pass_fds=keep, umask=0o022,
    )
    try:
        return proc.wait(timeout=seconds)
    except subprocess.TimeoutExpired:
        with contextlib.suppress(OSError):
            os.killpg(proc.pid, signal.SIGKILL)
        proc.wait()
        return None


def git(clone: str, args: list[str], seconds: float, reason: str) -> int:
    exe = shutil.which("git", path=SAFE_PATH)
    if exe is None:
        raise Failure("no-git")
    code = run([exe, *GIT_FLAGS, *args], clone, seconds)
    if code is None:
        raise Failure("timeout")
    if code != 0 and reason:
        raise Failure(reason)
    return code


def safe(path: str) -> bool:
    """Whether `path` belongs to this user and no one else can write to it."""
    info = os.stat(path)
    return info.st_uid == os.getuid() and not info.st_mode & 0o022


def backups(home: Path) -> set[str]:
    root = home / "claude-config" / "backups"
    return {p.name for p in root.iterdir() if p.is_dir() and not p.name.endswith(".partial")} if root.is_dir() else set()


def sync(home: Path, config_home: Path) -> bool:
    """Whether a deploy changed the Claude home; Failure when the sync stopped."""
    if read_json(config_home / "claude-config" / "local.json").get("autoSync") is False:
        return False
    state_file = home / "claude-config" / "state.json"
    state = read_json(state_file)
    clone, host = state.get("syncClone"), state.get("host")
    if not isinstance(clone, str) or not os.path.isabs(clone) or not os.path.isdir(os.path.join(clone, ".git")):
        return False
    if not isinstance(host, str) or not NAME.fullmatch(host):
        return False
    with open(home / "claude-config" / "sync.lock", "a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            return False  # another session start is syncing
        git(clone, ["fetch", "--quiet", "--no-tags", "origin", MAIN], FETCH_SECONDS, "fetch-failed")
        # Fast-forward only: main must be an ancestor of what origin has now.
        ahead = git(clone, ["merge-base", "--is-ancestor", "refs/heads/main", "refs/remotes/origin/main"], LOCAL_SECONDS, "")
        if ahead == 1:
            raise Failure("diverged")
        if ahead != 0:
            raise Failure("git-failed")
        git(clone, ["checkout", "--quiet", "--force", "-B", "main", "refs/remotes/origin/main"], LOCAL_SECONDS, "git-failed")
        # cfg.py collects files by walking the disk, so nothing untracked may ship.
        git(clone, ["clean", "-ffdxq"], LOCAL_SECONDS, "git-failed")
        tools = os.path.join(clone, "tools")
        cfg = os.path.join(tools, "cfg.py")
        if not all(safe(path) for path in (clone, tools, cfg)):
            raise Failure("unsafe-clone")
        before, saved = state_file.read_bytes(), backups(home)
        keep = (lock.fileno(),)
        deploy = [sys.executable, "-I", cfg, "deploy", "--host", host, "--yes", "--force", "--target", str(home)]
        if run(deploy, clone, None, keep) != 0:  # no deadline: a started deploy always finishes
            if backups(home) == saved:
                raise Failure("deploy-failed")  # it stopped before its backup, so before any write
            undo = [sys.executable, "-I", cfg, "rollback", "--target", str(home)]
            raise Failure("deploy-rolled-back" if run(undo, clone, None, keep) == 0 else "deploy-failed-partial")
        return state_file.read_bytes() != before


def log(home: Path, reason: str) -> None:
    path = home / "claude-config" / "sync.log"
    lines = []
    if path.is_file() and path.stat().st_size <= CAP * 4:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()[-(LOG_LINES - 1):]
    lines.append(f"{time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())} {reason}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    parsed = False
    with contextlib.suppress(Exception):  # hook contract: exit 0, fixed code
        payload = json.loads(sys.stdin.buffer.read().decode("utf-8"))
        startup = payload.get("hook_event_name") == "SessionStart" and payload.get("source") == "startup"
        parsed = True
    if not parsed or not startup:
        return
    with contextlib.suppress(Exception):  # hook contract: exit 0, fixed code
        home = Path(__file__).resolve().parent.parent
        xdg = os.environ.get("XDG_CONFIG_HOME")
        config_home = Path(xdg) if xdg else Path.home() / ".config"
        try:
            changed = sync(home, config_home)
        except Failure as failure:
            reason = failure.args[0]
            with contextlib.suppress(Exception):  # hook contract: exit 0, fixed code
                log(home, reason)
            print(json.dumps({"systemMessage": MESSAGES.get(reason, STAYS).format(reason=reason)}))
            return
        if changed:
            print(json.dumps(RELOAD))


if __name__ == "__main__":
    try:
        main()
    finally:
        sys.exit(0)
