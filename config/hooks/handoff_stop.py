"""Stop hook: hand the session off to a fresh context (ADR-0019).

When the session has written its handoff note (`.omc/handoffs/<session id>.md`, per the
session-handoff skill), type `/clear` and then a prompt naming the note into the session's tmux
pane, once per note. Claude Code has no hook output that clears a session, so the keys are typed;
a detached sender waits for the turn to end first. A background job (`claude --bg`: `CLAUDE_JOB_DIR`
set, no pane) has nothing to type into, so it gets a new background job with that prompt instead.
Without a note, block one stop per session once context use passes the handoff limit, telling the
model to load the skill.

Acts only in an interactive session (`CLAUDE_CODE_ENTRYPOINT=cli`; a nested `claude -p` reports
`sdk-cli`) inside a tmux pane with tmux on PATH, or in a background job with `claude` on PATH. Knows
nothing about OMC stages or modes: the skill decides when to hand off. Prints only that block
decision and always exits 0.
"""

from __future__ import annotations

import contextlib
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

CLEAR_DELAY = 2  # seconds before /clear, so the turn has ended and the input box is ready
PROMPT_DELAY = 3  # seconds between /clear and the prompt, so the fresh session has started
PANE = re.compile(r"%\d+")
SESSION = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,127}")
# $1 tmux, $2 pane, $3 prompt, $4 and $5 the delays. Fixed text: nothing from the note reaches a shell.
SENDER = (
    'sleep "$4"; "$1" send-keys -t "$2" /clear Enter; '
    'sleep "$5"; "$1" send-keys -t "$2" -l "$3"; "$1" send-keys -t "$2" Enter'
)
PROMPT = (
    "Read {note} first, then run its next skill with its arguments now. "
    "Do not re-ask the decisions it lists as settled."
)
LIMIT_PERCENT = 60  # of the context window, capped at LIMIT_TOKENS
LIMIT_TOKENS = 300_000
CACHE = "hud-stdin-cache.json"  # OMC's HUD copy of the statusline input, per session
REASON = "Context is past the handoff limit. Load the session-handoff skill now and follow it."


def number(value: object) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def past_limit(project: Path, session: str, env: dict) -> bool:
    """Whether this session's context use is at or past min(LIMIT_PERCENT of the window, LIMIT_TOKENS).
    Reads OMC's HUD cache: in the project's .omc, else under $OMC_STATE_DIR/<project id>/ (the id
    is OMC's own hash, so a glob on the unique session id finds it). No cache means no."""
    candidates = [project / ".omc" / "state" / "sessions" / session / CACHE]
    if env.get("OMC_STATE_DIR"):
        candidates += sorted(Path(env["OMC_STATE_DIR"]).glob(f"*/state/sessions/{session}/{CACHE}"))
    found = next((path for path in candidates if path.is_file()), None)
    if found is None:
        return False
    context = json.loads(found.read_text())["context_window"]
    window, usage = context["context_window_size"], context.get("current_usage")
    if usage is not None:
        parts = [usage["input_tokens"], usage["cache_creation_input_tokens"], usage["cache_read_input_tokens"]]
        used = sum(parts) if all(map(number, parts)) else None
    else:
        percent = context["used_percentage"]
        used = percent * window / 100 if number(percent) and number(window) else None
    return number(window) and used is not None and used >= min(window * LIMIT_PERCENT / 100, LIMIT_TOKENS)


def act(payload: dict, env: dict) -> dict | None:
    """Send the handoff keys, or return the block decision to print, or do nothing."""
    if not isinstance(payload, dict) or payload.get("hook_event_name") != "Stop":
        return None
    session = payload.get("session_id")
    pane = env.get("TMUX_PANE", "")
    tmux = PANE.fullmatch(pane) and shutil.which("tmux", path=env.get("PATH"))
    claude = not tmux and env.get("CLAUDE_JOB_DIR") and shutil.which("claude", path=env.get("PATH"))
    if env.get("CLAUDE_CODE_ENTRYPOINT") != "cli" or not (tmux or claude):
        return None
    if not isinstance(session, str) or not SESSION.fullmatch(session):
        return None
    project = Path(env.get("CLAUDE_PROJECT_DIR") or payload.get("cwd") or "")
    if not project.is_absolute():
        return None
    handoffs = project / ".omc" / "handoffs"
    note = handoffs / f"{session}.md"
    if note.is_file():
        # Not gated on stop_hook_active: after our own limit block, the stop that follows the
        # note always carries it.
        open(handoffs / f"{session}.sent", "x").close()  # raises once sent: one send per note
        prompt = PROMPT.format(note=note)
        subprocess.Popen(
            ["sh", "-c", SENDER, "sh", tmux, pane, prompt, str(CLEAR_DELAY), str(PROMPT_DELAY)] if tmux
            else [claude, "--bg", prompt],
            cwd=project, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
        return None
    # A block on a re-entrant stop trips Claude Code's override for repeatedly blocked Stop hooks,
    # so OMC never does it either (persistent-mode.mjs).
    if payload.get("stop_hook_active") is True or not past_limit(project, session, env):
        return None
    handoffs.mkdir(parents=True, exist_ok=True)
    open(handoffs / f"{session}.limit", "x").close()  # raises once blocked: one block per session
    return {"decision": "block", "reason": REASON}


def main() -> None:
    decision = None
    with contextlib.suppress(Exception):  # hook contract: exit 0, fixed code
        decision = act(json.loads(sys.stdin.buffer.read().decode("utf-8")), dict(os.environ))
    if decision:
        print(json.dumps(decision))


if __name__ == "__main__":
    try:
        main()
    finally:
        sys.exit(0)
