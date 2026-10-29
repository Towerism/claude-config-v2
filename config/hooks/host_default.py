"""SessionStart and SubagentStart hook: tell the model which machine this is.

The global rules name no tracker. They say to start with the tracker the
repo's CLAUDE.md names, else the host default stated at session start. This
hook states that default, on SessionStart for the main session and on
SubagentStart for each subagent (a subagent doesn't inherit SessionStart
context).

The default comes from, in order:
1. `defaultTracker` in the machine-local file $XDG_CONFIG_HOME/claude-config/local.json
   (or ~/.config/claude-config/local.json), which `cfg` never writes;
2. `defaultTracker` in <claude home>/claude-config/state.json, written by `cfg deploy`
   from the host profile.

The Claude home is two levels above this file (<home>/hooks/host_default.py).
Reads only those two files, prints only checked names (the host, the tracker and its
skill), always exits 0 and writes nothing to stderr.
"""

import contextlib
import json
import os
import re
import sys
from pathlib import Path

NAME = re.compile(r"[a-z0-9][a-z0-9-]{0,63}")
# Each tracker has its own lifecycle skill.
TRACKERS = {
    "github": "github-issue-lifecycle",
    "gitea": "gitea-issue-lifecycle",
    "jira": "jira-ticket-lifecycle",
}
CAP = 64 * 1024


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


def message(home: Path, config_home: Path) -> str | None:
    """The context line for this machine, or None when nothing usable is configured."""
    state = read_json(home / "claude-config" / "state.json")
    local = read_json(config_home / "claude-config" / "local.json")
    tracker = tracker_name(local.get("defaultTracker")) or tracker_name(state.get("defaultTracker"))
    if tracker is None:
        return None
    host = checked(state.get("host"))
    where = f"Host profile: {host}. " if host else ""
    return (
        f"{where}Default issue tracker: {tracker}. Use the {TRACKERS[tracker]} skill "
        "unless the repo's CLAUDE.md names another tracker; the repo's choice wins."
    )


# A session whose first prompt starts with a skill or holds an OMC keyword runs unguarded (#12, #36).
BYPASS_PROMPT = re.compile(
    r"(?i)\s*(?:<command-message>[^<]*</command-message>\s*)?(?:<command-name>)?/(?P<skill>\w[\w.-]*(?::\w[\w.-]*)?)(?=\s|:|<|$)"
)
BYPASS_WORD = re.compile(
    r"(?i)(?<![\w./-])(?:autopilot|ralph|ralplan|deep[\s-]+interview|deslop|anti-slop|deep-analyze|tdd|deepsearch|ultrathink|cancelomc)(?![\w'\u2019/-]|\.\w)"
)
# Claude Code's own commands (as of October 2026): a first prompt starting with one of these is not a skill.
BUILTIN_COMMANDS = frozenset({
    "add-dir", "agents", "artifacts", "bashes", "branch", "btw", "bug", "checkpoint", "chrome", "clear",
    "compact", "config", "context", "continue", "copy", "cost", "desktop", "diff", "doctor", "effort", "exit",
    "export", "extra-usage", "fast", "feedback", "fork", "goal", "help", "hooks", "ide", "init", "insights",
    "install-github-app", "install-slack-app", "keybindings", "login", "logout", "mcp", "memory", "mobile",
    "model", "new", "output-style", "permissions", "plan", "plugin", "pr-comments", "privacy-settings", "quit",
    "release-notes", "reload-plugins", "remote-control", "remote-env", "rename", "reset", "resume", "review",
    "rewind", "sandbox", "settings", "skills", "stats", "status", "statusline", "tasks", "terminal-setup",
    "theme", "todos", "upgrade", "usage", "vim", "voice", "web-setup",
})


def session_bypassed(payload: dict) -> bool:
    """Whether the session's first user prompt starts with a skill or holds an OMC keyword. Reads the first
    256 KB of the transcript; anything unreadable means no."""
    with contextlib.suppress(Exception):  # hook contract: exit 0, fixed code
        path = payload["transcript_path"]
        if not isinstance(path, str) or not os.path.isfile(path):
            return False
        with open(path, "rb") as f:
            lines = f.read(256 * 1024).splitlines()
        for line in lines:
            try:
                entry = json.loads(line)
                content = entry["message"]["content"]
                if entry["type"] != "user" or entry.get("isMeta") or entry.get("isSidechain"):
                    continue
            except (ValueError, KeyError, TypeError):
                continue
            if isinstance(content, list):
                # Only what the user typed: skip blocks the IDE or harness injected.
                content = "\n".join(
                    b.get("text", "")
                    for b in content
                    if isinstance(b, dict) and b.get("type") == "text" and not b.get("text", "").lstrip().startswith(("<ide_", "<system-reminder"))
                )
            if isinstance(content, str) and content.strip():
                start = BYPASS_PROMPT.match(content)
                if start and start.group("skill").lower() not in BUILTIN_COMMANDS:
                    return True
                return BYPASS_WORD.search(content) is not None
    return False


def main() -> None:
    parsed = False
    with contextlib.suppress(Exception):  # hook contract: exit 0, fixed code
        payload = json.loads(sys.stdin.buffer.read().decode("utf-8"))
        event = payload.get("hook_event_name")
        parsed = True
    if not parsed:
        return
    if event not in ("SessionStart", "SubagentStart") or session_bypassed(payload):
        return
    home = Path(__file__).resolve().parent.parent
    xdg = os.environ.get("XDG_CONFIG_HOME")
    config_home = Path(xdg) if xdg else Path.home() / ".config"
    text = message(home, config_home)
    if text:
        print(
            json.dumps(
                {"hookSpecificOutput": {"hookEventName": event, "additionalContext": text}}
            )
        )


if __name__ == "__main__":
    try:
        main()
    finally:
        sys.exit(0)
