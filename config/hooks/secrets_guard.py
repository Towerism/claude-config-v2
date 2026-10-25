"""Secrets guard: Read, Grep and Glob never touch secret files; Bash asks first.

Why: .env files hold credentials, and deny-terms holds the user's private terms. Neither may
reach the model's context or its output.

Secret file: the names `deny-terms`, `.env`, and `.env.<suffix>` except the suffixes `example`,
`sample` and `template`. `.envrc` is not one. The same definition lives in bash_guard.py; a test
keeps them equal.

Read, Grep, Glob look only at path-like fields (`file_path`, `path`, `glob`, and Glob's `pattern`);
a Grep regex `pattern` is never scanned. A path denies when its basename, or its os.path.realpath
(~ expanded), names a secret file, or it resolves to ~/.config/claude-config/deny-terms or the
directory holding it (that directory only, so a search over the home directory is not denied). A
path that cannot be expanded or resolved (a lone surrogate, say) denies. A glob denies when its
basename names a secret file, or fnmatch matches one of `.env`, `.env.local`, `.env.production` or
`deny-terms`. A glob whose basename opens with a wildcard (`*`, `?`, `[`) never denies: it is
ordinary listing. Each `{a,b}` alternative is checked on its own; a glob with more than 16
alternatives or brace groups denies. Bash asks when a command token holds a secret name at its
start or right after `/`, a quote or `=`, or a glob word there that opens with a literal character
and matches one of the same four names (`.en?`, `.e*`).

Nothing named by the input is opened, only resolved. The Bash scan is linear in the command
length. Nothing from the input is printed. Always exits 0; one 5-second deadline; every error is
one fixed code on stderr.
"""

import contextlib
import fnmatch
import json
import os
import re
import signal
import sys
from pathlib import Path

DEADLINE_SECONDS = 5
# Suffixes that mark a template, not a secret: .env.example is committed on purpose.
SAFE_SUFFIXES = {"example", "sample", "template"}
# Literal names a non-wildcard glob is matched against (see glob_denied).
GLOB_NAMES = (".env", ".env.local", ".env.production", "deny-terms")
# The input fields that hold a path. Grep's regex `pattern` is not one.
PATH_FIELDS = {"Read": ("file_path",), "Grep": ("path", "glob"), "Glob": ("path", "pattern")}
# Fields whose value is a glob, not a plain path.
GLOB_FIELDS = {"glob", "pattern"}
# A `{a,b}` group in a glob; each alternative is checked. Past these bounds the glob is denied.
BRACE_GROUP = re.compile(r"\{([^{}]*)\}")
MAX_ALTERNATIVES = 16
MAX_BRACE_GROUPS = 16

DENY_REASON = "Secret files (.env, deny-terms) are off limits: do not read, search or list them."
ASK_REASON = "This command names a secret file (.env or deny-terms). Confirm you want it touched."

# Shell operators become spaces, so each token is one command word or argument.
OPERATORS = str.maketrans({c: " " for c in ";&|<>()`"})
# A word starts at a token start or after / ' " =, and ends before the next of those or a glob
# character. Words never overlap, so the scan is linear in the command length.
WORD = re.compile(r"(?:^|(?<=[/'\"=]))([^/'\"=*?\[\]]*)([*?\[]?)")
# The same word starts, for the glob match: a token splits into pieces at / ' " =.
PIECE_BREAK = re.compile(r"[/'\"=]")
GLOB_CHARS = re.compile(r"[*?\[]")


def names_secret(name: str) -> bool:
    """Whether a bare file name is a secret file."""
    if name == "deny-terms" or name == ".env":
        return True
    return name.startswith(".env.") and name[5:] not in SAFE_SUFFIXES


def path_denied(value: str, deny_file: str | None) -> bool:
    try:
        expanded = os.path.expanduser(value)
    except (ValueError, UnicodeError, OSError):
        return True
    if names_secret(os.path.basename(expanded)):
        return True
    try:
        resolved = os.path.realpath(expanded)
    except (ValueError, UnicodeError, OSError):
        return True  # a path that cannot be resolved could name anything: deny
    if names_secret(os.path.basename(resolved)):
        return True
    # The deny-terms directory counts, its parents do not: a search over $HOME is not a deny.
    return deny_file is not None and resolved in (deny_file, os.path.dirname(deny_file))


def glob_matches_secret(base: str) -> bool:
    """Whether a glob basename that opens with a literal character matches one of GLOB_NAMES."""
    # A basename opening with a wildcard is ordinary listing: `Glob **/*` must pass.
    return base[:1] not in ("", "*", "?", "[") and any(fnmatch.fnmatchcase(name, base) for name in GLOB_NAMES)


def brace_alternatives(value: str) -> list[str] | None:
    """The globs a `{a,b}` pattern stands for; None past MAX_ALTERNATIVES or MAX_BRACE_GROUPS."""
    values = [value]
    for _ in range(MAX_BRACE_GROUPS):
        expanded = []
        for v in values:
            group = BRACE_GROUP.search(v)
            if group is None:
                expanded.append(v)
            else:
                head, tail = v[:group.start()], v[group.end():]
                expanded += [head + alt + tail for alt in group.group(1).split(",")]
            if len(expanded) > MAX_ALTERNATIVES:
                return None
        if expanded == values:
            return values
        values = expanded
    return None if any(BRACE_GROUP.search(v) for v in values) else values


def glob_denied(value: str) -> bool:
    alternatives = brace_alternatives(value)
    if alternatives is None:
        return True  # too many alternatives to check: deny
    for alt in alternatives:
        base = os.path.basename(alt)
        if names_secret(base) or glob_matches_secret(base):
            return True
    return False


def deny_terms_file() -> str | None:
    """The real path of deny-terms, or None when the home directory cannot be found."""
    try:
        return os.path.realpath(Path.home() / ".config" / "claude-config" / "deny-terms")
    except Exception:
        return None


def command_names_secret(command: str) -> bool:
    for token in command.translate(OPERATORS).split():
        for match in WORD.finditer(token):
            word, glob = match.groups()
            if glob:
                # A glob word asks when its literal start is .env or deny-terms.
                if word.startswith(".env") or word.startswith("deny-terms"):
                    return True
            elif names_secret(word):
                return True
        # A glob word with a literal start, such as `.en?` or `.e*`, asks when it matches a
        # secret name, as the Glob rule does.
        for piece in PIECE_BREAK.split(token):
            if GLOB_CHARS.search(piece) and glob_matches_secret(piece):
                return True
    return False


def emit(**fields: str) -> None:
    print(json.dumps({"hookSpecificOutput": {"hookEventName": "PreToolUse", **fields}}))


def on_deadline(signum, frame) -> None:
    raise TimeoutError


# A session whose first prompt starts ralph or autopilot runs unguarded (#12).
BYPASS_PROMPT = re.compile(
    r"(?i)\s*(?:<command-message>[^<]*</command-message>\s*)?(?:<command-name>)?/?(?:oh-my-claudecode:)?(?:ralph|autopilot)(?=\s|:|<|$)"
)


def session_bypassed(payload: dict) -> bool:
    """Whether the session's first user prompt starts ralph or autopilot. Reads the first 256 KB of the
    transcript; anything unreadable means no."""
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
                content = "".join(b.get("text", "") for b in content if isinstance(b, dict) and b.get("type") == "text")
            if isinstance(content, str) and content.strip():
                return BYPASS_PROMPT.match(content) is not None
    return False


def main() -> None:
    try:
        payload = json.loads(sys.stdin.buffer.read().decode("utf-8"))
        if session_bypassed(payload):
            return
        name = payload["tool_name"]
        fields = payload["tool_input"]
        if not isinstance(name, str) or not isinstance(fields, dict):
            return
    except Exception:
        return
    try:
        signal.signal(signal.SIGALRM, on_deadline)
        signal.alarm(DEADLINE_SECONDS)  # one deadline for the whole hook
        if name == "Bash":
            command = fields.get("command")
            if isinstance(command, str) and "\0" not in command and command_names_secret(command):
                signal.alarm(0)  # disarm before printing, so the alarm cannot fire mid-output
                emit(permissionDecision="ask", permissionDecisionReason=ASK_REASON)
        elif name in PATH_FIELDS:
            deny_file = deny_terms_file()
            for field in PATH_FIELDS[name]:
                value = fields.get(field)
                if not isinstance(value, str) or "\0" in value:
                    continue
                if glob_denied(value) if field in GLOB_FIELDS else path_denied(value, deny_file):
                    signal.alarm(0)
                    emit(permissionDecision="deny", permissionDecisionReason=DENY_REASON)
                    return
    except Exception:
        sys.stderr.write("secrets_guard: error\n")  # the only output on error: a fixed code


if __name__ == "__main__":
    try:
        main()
    finally:
        sys.exit(0)
