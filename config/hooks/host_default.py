"""SessionStart and SubagentStart hook: state the issue tracker for the current repo.

A subagent doesn't inherit SessionStart context, so SubagentStart gets the same line. The
tracker comes from the first of these that names one:

1. the Jira project key `jira.project` in the machine-local file
   $XDG_CONFIG_HOME/claude-config/local.json (or ~/.config/claude-config/local.json) appearing in
   the repo's local history: the last 200 commit subjects of HEAD and the newest 500 branch names
   hold at least two distinct KEY-N tokens, or one in a conventional form (" (KEY-N)" ending a
   subject, "KEY-N:" starting one, "/KEY-N-" in a branch name); this gives jira;
2. the `origin` remote: github.com gives github; a host listed by `tea logins list` gives gitea
   (tea runs only when a tea config file exists);
3. `defaultTracker` in <claude home>/claude-config/state.json, written by `cfg deploy` from the
   host profile.

The repo is the payload's absolute `cwd`. The top-level `defaultTracker` in local.json is
ignored. With none of these, nothing is printed. The repo's own CLAUDE.md wins over all of
them, and the line says so.

The Claude home is two levels above this file (<home>/hooks/host_default.py). git runs by
absolute path from a fixed PATH with a fixed argv, with no repo config that runs programs
(fsmonitor, hooks, external diff, signature checks), no GIT_* variables and no lazy fetch, output
capped at 64 KiB; one 5-second deadline covers the hook. Prints only checked names (the host, the
tracker and its skill) and fixed words, always exits 0 and writes nothing to stderr.
"""

import contextlib
import csv
import json
import os
import re
import select
import shutil
import signal
import subprocess
import sys
import time
from pathlib import Path
from urllib.parse import urlsplit

NAME = re.compile(r"[a-z0-9][a-z0-9-]{0,63}")
# Each tracker has its own lifecycle skill.
TRACKERS = {
    "github": "github-issue-lifecycle",
    "gitea": "gitea-issue-lifecycle",
    "jira": "jira-ticket-lifecycle",
}
CAP = 64 * 1024
DEADLINE_SECONDS = 5
TEA_SECONDS = 2
SAFE_PATH = "/usr/local/bin:/usr/bin:/bin"  # git and tea are looked up here, never on the caller's PATH
# Override repo config that would run programs.
GIT_FLAGS = [
    "--no-optional-locks", "-c", "core.fsmonitor=false", "-c", "core.hooksPath=/dev/null", "-c", "diff.external=",
    "-c", "log.showSignature=false",
]
JIRA_KEY = re.compile(r"[A-Z][A-Z0-9_]{1,9}")
HOST = re.compile(r"[a-z0-9.-]{1,253}")
SCP_URL = re.compile(r"(?:[^@/:]+@)?([^/:]+):")


class Timeout(Exception):
    pass


def on_deadline(signum, frame):
    raise Timeout


def read_json(path: Path) -> dict:
    """The JSON object in `path`; {} when it is missing, too big or not an object."""
    try:
        if not path.is_file() or path.stat().st_size > CAP:
            return {}
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def checked(value: object) -> str | None:
    """`value` if it is a plain lowercase name, else None."""
    return value if isinstance(value, str) and NAME.fullmatch(value) else None


def tracker_name(value: object) -> str | None:
    name = checked(value)
    return name if name in TRACKERS else None


def run_tool(name: str, args: list[str], env: dict, deadline: float, cwd: str | None = None) -> str | None:
    """stdout of `name` (found on SAFE_PATH) capped at CAP, or None on failure or past the deadline.

    Tests replace this function to answer for tea.
    """
    exe = shutil.which(name, path=SAFE_PATH)
    if exe is None:
        return None
    try:
        proc = subprocess.Popen(
            [exe, *args],
            cwd=cwd, env=env, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
        )
    except (OSError, ValueError):
        return None
    chunks: list[bytes] = []
    size = 0
    try:
        while size < CAP:
            left = deadline - time.monotonic()
            if left <= 0 or not select.select([proc.stdout], [], [], left)[0]:
                return None
            chunk = os.read(proc.stdout.fileno(), CAP - size)
            if not chunk:
                break
            chunks.append(chunk)
            size += len(chunk)
    finally:
        proc.kill()
        proc.wait()
        proc.stdout.close()
    if size < CAP and proc.returncode not in (0, -9):
        return None
    return b"".join(chunks).decode("utf-8", errors="replace")


def run_git(cwd: str, args: list[str], deadline: float) -> str | None:
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    env["PATH"] = SAFE_PATH
    env["GIT_NO_LAZY_FETCH"] = "1"
    return run_tool("git", [*GIT_FLAGS, *args], env, deadline, cwd)


def names_jira(key: str, subjects: list[str], branches: list[str]) -> bool:
    """Whether `key` shows up as two distinct KEY-N tokens, or as one in a conventional form."""
    token = re.compile(rf"(?<![A-Za-z0-9_]){re.escape(key)}-(\d+)(?![A-Za-z0-9_])")
    numbers = {m.group(1) for text in (*subjects, *branches) for m in token.finditer(text)}
    if len(numbers) >= 2:
        return True
    key_ref = rf"{re.escape(key)}-\d+"
    return any(re.search(rf" \({key_ref}\)$", s) or re.match(rf"{key_ref}:", s) for s in subjects) or any(
        re.search(rf"/{key_ref}-", b) for b in branches
    )


def jira_in_history(key: str, cwd: str, deadline: float) -> bool:
    log = run_git(cwd, ["log", "-n", "200", "--format=%s", "HEAD", "--"], deadline) or ""
    refs = run_git(
        cwd,
        ["for-each-ref", "--sort=-committerdate", "--count=500", "--format=%(refname:short)", "refs/heads", "refs/remotes"],
        deadline,
    ) or ""
    return names_jira(key, log.splitlines(), refs.splitlines())


def url_host(url: str) -> str | None:
    """The lowercase host of an https, ssh or scp-style URL, if it passes HOST."""
    url = url.strip()
    if "://" in url:
        try:
            host = urlsplit(url).hostname
        except ValueError:
            return None
    else:
        match = SCP_URL.match(url)
        host = match.group(1) if match else None
    host = host.lower() if host else None
    return host if host and HOST.fullmatch(host) else None


def tea_hosts(config_home: Path, deadline: float) -> set[str]:
    """Hosts of the tea logins (URL and SSHHost columns); tea runs only when its config exists."""
    if not any(p.is_file() for p in (config_home / "tea" / "config.yml", Path.home() / ".config" / "tea" / "config.yml")):
        return set()
    env = {"PATH": SAFE_PATH, **{k: os.environ[k] for k in ("HOME", "XDG_CONFIG_HOME") if k in os.environ}}
    out = run_tool("tea", ["logins", "list", "-o", "csv"], env, min(deadline, time.monotonic() + TEA_SECONDS))
    hosts = set()
    for row in csv.DictReader((out or "").splitlines()):
        for key, value in row.items():
            if isinstance(key, str) and key.lower() in ("url", "sshhost") and isinstance(value, str) and value:
                host = url_host(value) if "://" in value else url_host(value + ":")
                if host:
                    hosts.add(host)
    return hosts


def origin_tracker(cwd: str, config_home: Path, deadline: float) -> str | None:
    host = url_host(run_git(cwd, ["remote", "get-url", "origin"], deadline) or "")
    if host is None:
        return None
    if host == "github.com":
        return "github"
    return "gitea" if host in tea_hosts(config_home, deadline) else None


def repo_tracker(cwd: object, local: dict, config_home: Path) -> tuple[str, str] | None:
    """(tracker, source) from the repo's own signals, or None."""
    if not isinstance(cwd, str) or "\0" in cwd or not os.path.isabs(cwd) or not os.path.isdir(cwd):
        return None
    deadline = time.monotonic() + DEADLINE_SECONDS
    jira = local.get("jira")
    key = jira.get("project") if isinstance(jira, dict) else None
    if isinstance(key, str) and JIRA_KEY.fullmatch(key) and jira_in_history(key, cwd, deadline):
        return "jira", "jira key in history"
    tracker = origin_tracker(cwd, config_home, deadline)
    return (tracker, "origin") if tracker else None


def message(home: Path, config_home: Path, cwd: object = None) -> str | None:
    """The context line for this repo and machine, or None when nothing names a tracker."""
    state = read_json(home / "claude-config" / "state.json")
    local = read_json(config_home / "claude-config" / "local.json")
    profile = tracker_name(state.get("defaultTracker"))
    found = repo_tracker(cwd, local, config_home)
    tracker, source = found or (profile, "host profile")
    if tracker is None:
        return None
    host = checked(state.get("host"))
    where = f"Host profile: {host}. " if host else ""
    text = (
        f"{where}Default issue tracker: {tracker}. Use the {TRACKERS[tracker]} skill "
        f"unless the repo's CLAUDE.md names another tracker; the repo's choice wins. Source: {source}."
    )
    if found and profile and profile != tracker:
        text += f" Host profile default: {profile}."
    return text


def main() -> None:
    parsed = False
    with contextlib.suppress(Exception):  # hook contract: exit 0, fixed code
        payload = json.loads(sys.stdin.buffer.read().decode("utf-8"))
        event = payload.get("hook_event_name")
        parsed = True
    if not parsed:
        return
    if event not in ("SessionStart", "SubagentStart"):
        return
    # Past the deadline, or on any error, nothing is printed.
    with contextlib.suppress(Exception):  # hook contract: exit 0, fixed code
        signal.signal(signal.SIGALRM, on_deadline)
        signal.alarm(DEADLINE_SECONDS)
        home = Path(__file__).resolve().parent.parent
        xdg = os.environ.get("XDG_CONFIG_HOME")
        config_home = Path(xdg) if xdg else Path.home() / ".config"
        text = message(home, config_home, payload.get("cwd"))
        signal.alarm(0)  # disarm first, so the alarm cannot fire during the print
        if text:
            print(json.dumps({"hookSpecificOutput": {"hookEventName": event, "additionalContext": text}}))
    signal.alarm(0)


if __name__ == "__main__":
    try:
        main()
    finally:
        sys.exit(0)
