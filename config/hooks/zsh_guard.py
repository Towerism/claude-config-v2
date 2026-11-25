"""PreToolUse hook for Bash: deny two zsh patterns that leak secrets.

1. An unbraced `$VAR` followed by `:` and a modifier letter (`"$TOKEN:token"`, `$HOST:user`).
   zsh reads `:t`, `:h` and the like as a modifier, applies it and drops the colon. It does this
   in double quotes and unquoted, not in single quotes. Fix: `${VAR}:`.
2. `2>&1` and a stdout file redirect in the same command before a `|` (`cmd 2>&1 >/dev/null | grep x`).
   With MULTIOS on (zsh's default), stdout still goes down the pipe. Fix: `2>file`, `| wc -c`
   or `setopt nomultios`.

The scan is a plain text pass that skips quoted and backslash-escaped text. It does not parse
`$(...)`, heredocs or `|&`; a miss lets the command through. Prints only one of two fixed reasons
and always exits 0, so a bad payload never blocks a tool call. The zsh spikes behind each rule
are in tests/test_zsh_guard.py.
"""

from __future__ import annotations

import contextlib
import json
import re
import sys

# `$NAME` or `$1`, then `:` and a modifier zsh applies: h t r e l u q Q a A c P &, g + one of
# those, or s/ and gs/ (a bare `:s` is a "bad substitution" error, so it needs no rule).
MODIFIER = re.compile(r"\$(?:[A-Za-z_]\w*|\d):(?:g?[hrtelquQaAcP&]|g?s/)")
SEGMENT_END = re.compile(r"(\|\||&&|;|\n|\|)")
STDERR_TO_STDOUT = re.compile(r"(?<![\w>&])2>&1(?!\d)")
STDOUT_TO_FILE = re.compile(r"(?<![\w&])(?:1>>?|>>?|&>>?)(?!&)")

MODIFIER_REASON = (
    "zsh reads an unbraced $VAR followed by a colon and a letter such as t, h, e or u as a modifier "
    "and drops the colon, which can leak a secret into a URL or header. Write ${VAR}: instead."
)
MULTIOS_REASON = (
    "With zsh's MULTIOS, `2>&1` plus another stdout redirect before a pipe still sends stdout down "
    "the pipe, so a secret on stdout leaks. Write `2>file`, end the pipe with `| wc -c`, or run "
    "`setopt nomultios` first."
)


def mask(command: str, keep_double: bool) -> str:
    """`command` with single-quoted text, backslash pairs and (unless `keep_double`) double-quoted text blanked."""
    out: list[str] = []
    quote = ""
    i = 0
    while i < len(command):
        c = command[i]
        if c == "\\" and quote != "'":
            out.append("  ")
            i += 2
            continue
        if quote:
            if c == quote:
                quote = ""
            out.append(c if quote == '"' and keep_double else " ")
        elif c in "'\"":
            quote = c
            out.append(" ")
        else:
            out.append(c)
        i += 1
    return "".join(out)


def verdict(command: str) -> str | None:
    if MODIFIER.search(mask(command, True)):
        return MODIFIER_REASON
    parts = SEGMENT_END.split(mask(command, False))
    for i in range(0, len(parts) - 2, 2):
        segment = parts[i]
        if parts[i + 1] == "|" and STDERR_TO_STDOUT.search(segment) and STDOUT_TO_FILE.search(segment):
            return MULTIOS_REASON
    return None


def main() -> None:
    reason = None
    with contextlib.suppress(Exception):  # hook contract: exit 0, fixed code
        payload = json.loads(sys.stdin.buffer.read().decode("utf-8"))
        tool_input = payload.get("tool_input")
        command = tool_input.get("command") if isinstance(tool_input, dict) else None
        if payload.get("tool_name") == "Bash" and isinstance(command, str):
            reason = verdict(command)
    if reason:
        print(json.dumps({"hookSpecificOutput": {
            "hookEventName": "PreToolUse", "permissionDecision": "deny", "permissionDecisionReason": reason,
        }}))


if __name__ == "__main__":
    try:
        main()
    finally:
        sys.exit(0)
