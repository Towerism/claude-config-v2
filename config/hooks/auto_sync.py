"""SessionStart hook (matcher startup): bring the deployed config up to date with main on origin.

`cfg.py deploy --yes` keeps a dedicated clone of claude-config and records it as `syncClone` in
<claude home>/claude-config/state.json (ADR-0007). At each new session this hook fetches main
into that clone, fast-forwards it, and runs the clone's `cfg.py deploy --yes --force` for the
recorded host. A file edited by hand in the Claude home is overwritten and backed up first;
`cfg.py rollback` restores it.

It does nothing, and runs no git, when $XDG_CONFIG_HOME/claude-config/local.json (or
~/.config/claude-config/local.json) sets "autoSync": false, or when no clone is recorded. It
skips quietly while another run holds <home>/claude-config/sync.lock. The fetch has
FETCH_SECONDS; a deploy that has started always runs to the end, in its own session.

On success it prints nothing, or only reloadSkills when the deploy changed something, so nothing
enters the model's context. On failure the config stays as it was, a line with the UTC time and
a fixed reason goes to <home>/claude-config/sync.log (the last LOG_LINES are kept), and the user
sees a fixed one-line systemMessage.

The Claude home is two levels above this file (<home>/hooks/auto_sync.py). git runs by absolute
path from a fixed PATH with a fixed argv, with no GIT_* variables and no repo config that runs
programs (fsmonitor, hooks, a custom upload-pack, the ext transport). It never prompts
(GIT_TERMINAL_PROMPT=0, ssh in BatchMode) but can still use the user's ssh-agent or credential
helper. Prints only fixed words, always exits 0 and writes nothing to stderr.
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
LOCAL_SECONDS = 30  # each local git step, so a stuck clone cannot hold the session start
LOG_LINES = 200
CAP = 64 * 1024
SAFE_PATH = "/usr/local/bin:/usr/bin:/bin"  # git is looked up here, never on the caller's PATH
NAME = re.compile(r"[a-z0-9][a-z0-9_.-]{0,63}")  # a host name, as cfg.py checks it
GIT_FLAGS = [
    "-c", "core.fsmonitor=false", "-c", "core.hooksPath=/dev/null", "-c", "protocol.ext.allow=never",
    "-c", "remote.origin.uploadpack=git-upload-pack",
]
MAIN = "+refs/heads/main:refs/remotes/origin/main"
RELOAD = {"hookSpecificOutput": {"hookEventName": "SessionStart", "reloadSkills": True}}
WARNING = (
    "claude-config auto sync failed ({reason}); the current config stays. "
    "The reason is logged in claude-config/sync.log in the Claude home."
)


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
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    env.update(PATH=SAFE_PATH, GIT_TERMINAL_PROMPT="0", GIT_SSH_COMMAND="ssh -o BatchMode=yes")
    return env


def run(argv: list[str], cwd: str, seconds: float | None) -> int | None:
    """The exit code of `argv`, or None once `seconds` pass; its output is discarded.

    It runs in its own session: past the deadline the whole group (git and its ssh) is killed,
    and a kill aimed at this hook's group never reaches a deploy under way.
    """
    proc = subprocess.Popen(
        argv, cwd=cwd, env=environment(), stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL, start_new_session=True,
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
        before = state_file.read_bytes()
        cfg = os.path.join(clone, "tools", "cfg.py")
        argv = [sys.executable, "-I", cfg, "deploy", "--host", host, "--yes", "--force", "--target", str(home)]
        if run(argv, clone, None) != 0:  # no deadline: a started deploy always finishes
            raise Failure("deploy-failed")
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
            print(json.dumps({"systemMessage": WARNING.format(reason=reason)}))
            return
        if changed:
            print(json.dumps(RELOAD))


if __name__ == "__main__":
    try:
        main()
    finally:
        sys.exit(0)
