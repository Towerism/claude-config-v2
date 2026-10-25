"""Secrets guard: Read, Grep and Glob never touch secret files; Bash asks first.

Secret file: the names `deny-terms`, `.env`, and `.env.<suffix>` except the suffixes `example`,
`sample` and `template`. `.envrc` is not one. The same definition lives in bash_guard.py; a test
keeps them equal.

Read, Grep, Glob look only at path-like fields (`file_path`, `path`, `glob`, and Glob's `pattern`);
a Grep regex `pattern` is never scanned. A path denies when its basename, or its os.path.realpath
(~ expanded), names a secret file, or it resolves to ~/.config/claude-config/deny-terms or the
directory holding it (that directory only, so a search over the home directory is not denied). A
glob denies when its basename matches `.env`, `.env.local`, `.env.production` or `deny-terms`,
unless it opens with a wildcard (`*`, `?`, `[`): that is ordinary listing, not a secret probe.
Bash asks when a command token holds a secret name at its start or right after `/`, a quote or `=`.

Nothing named by the input is opened, only resolved. Scanning is linear. Nothing from the input is
printed. Always exits 0; one 5-second deadline; every error is one fixed code on stderr.
"""

import fnmatch
import json
import os
import re
import signal
import sys
from pathlib import Path

DEADLINE_SECONDS = 5
SAFE_SUFFIXES = {"example", "sample", "template"}
GLOB_NAMES = (".env", ".env.local", ".env.production", "deny-terms")
PATH_FIELDS = {"Read": ("file_path",), "Grep": ("path", "glob"), "Glob": ("path", "pattern")}
GLOB_FIELDS = {"glob", "pattern"}

DENY_REASON = "Secret files (.env, deny-terms) are off limits: do not read, search or list them."
ASK_REASON = "This command names a secret file (.env or deny-terms). Confirm you want it touched."

OPERATORS = str.maketrans({c: " " for c in ";&|<>()`"})
# A word starts at a token start or right after / ' " =, and ends at the next of those, a glob
# character, or the token end. Words never overlap, so a scan is linear.
WORD = re.compile(r"(?:^|(?<=[/'\"=]))([^/'\"=*?\[\]]*)([*?\[]?)")


def names_secret(name: str) -> bool:
    if name == "deny-terms" or name == ".env":
        return True
    return name.startswith(".env.") and name[5:] not in SAFE_SUFFIXES


def path_denied(value: str, deny_file: str | None) -> bool:
    expanded = os.path.expanduser(value)
    resolved = os.path.realpath(expanded)
    if names_secret(os.path.basename(expanded)) or names_secret(os.path.basename(resolved)):
        return True
    return deny_file is not None and resolved in (deny_file, os.path.dirname(deny_file))


def glob_denied(value: str) -> bool:
    base = os.path.basename(value)
    if names_secret(base):
        return True
    # A basename opening with a wildcard (`*`, `[a-z]*`) is ordinary listing, not a secret probe.
    return base[:1] not in ("", "*", "?", "[") and any(fnmatch.fnmatchcase(name, base) for name in GLOB_NAMES)


def deny_terms_file() -> str | None:
    try:
        return os.path.realpath(Path.home() / ".config" / "claude-config" / "deny-terms")
    except Exception:
        return None


def command_names_secret(command: str) -> bool:
    for token in command.translate(OPERATORS).split():
        for match in WORD.finditer(token):
            word, glob = match.groups()
            if glob:
                if word.startswith(".env") or word.startswith("deny-terms"):
                    return True
            elif names_secret(word):
                return True
    return False


def emit(**fields: str) -> None:
    print(json.dumps({"hookSpecificOutput": {"hookEventName": "PreToolUse", **fields}}))


def on_deadline(signum, frame) -> None:
    raise TimeoutError


def main() -> None:
    try:
        payload = json.loads(sys.stdin.buffer.read().decode("utf-8"))
        name = payload["tool_name"]
        fields = payload["tool_input"]
        if not isinstance(name, str) or not isinstance(fields, dict):
            return
    except Exception:
        return
    try:
        signal.signal(signal.SIGALRM, on_deadline)
        signal.alarm(DEADLINE_SECONDS)
        if name == "Bash":
            command = fields.get("command")
            if isinstance(command, str) and "\0" not in command and command_names_secret(command):
                emit(permissionDecision="ask", permissionDecisionReason=ASK_REASON)
        elif name in PATH_FIELDS:
            deny_file = deny_terms_file()
            for field in PATH_FIELDS[name]:
                value = fields.get(field)
                if not isinstance(value, str) or "\0" in value:
                    continue
                if glob_denied(value) if field in GLOB_FIELDS else path_denied(value, deny_file):
                    emit(permissionDecision="deny", permissionDecisionReason=DENY_REASON)
                    return
    except Exception:
        sys.stderr.write("secrets_guard: error\n")


if __name__ == "__main__":
    try:
        main()
    finally:
        sys.exit(0)
