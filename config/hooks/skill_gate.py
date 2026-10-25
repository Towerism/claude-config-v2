"""Skill gate: review context from git facts, and an ask before the model starts autopilot.

Events: PreToolUse (tool_name Skill, name in tool_input.skill) and UserPromptExpansion
(name in command_name). On `review` it prints agent context naming code-simplifier (diff over
300 lines), git-master (fixup or WIP commits) and security-reviewer (a category hit), using
integers and fixed names only. On PreToolUse only, `autopilot` prints an "ask"; the user-typed
/autopilot arrives as UserPromptExpansion and passes. Always exits 0.

Git runs hardened: no repo config that executes code, no external diff or textconv, no GIT_*
variables, git found once by absolute path, output capped at 64 KiB, one 5-second deadline.
"""

import json
import os
import re
import select
import shutil
import subprocess
import sys
import time

DEADLINE_SECONDS = 5
CAP = 64 * 1024
LARGE_DIFF = 300
SAFE_PATH = "/usr/local/bin:/usr/bin:/bin"

NAME = re.compile(r"[a-z0-9-]+(:[a-z0-9-]+)?")
REVIEW = {"review", "omc-review", "oh-my-claudecode:review", "oh-my-claudecode:omc-review"}
AUTOPILOT = {"autopilot", "oh-my-claudecode:autopilot"}
AUTOPILOT_REASON = "Autopilot runs only when you ask for it (global rule: do not use autopilot unless the user asks)"

FIXUP = re.compile(r"(fixup|squash|amend)!")
WIP = re.compile(r"(?i)wip\b")
CATEGORIES = {
    "auth": re.compile(r"(?i)(auth|login|session|passw(or)?d|credential|oauth|jwt)"),
    "input": re.compile(r"\b(json\.loads|yaml\.load|pickle\.loads?|eval\(|exec\()"),
    "secrets": re.compile(r"(?i)(secret|api[_-]?key|private[_ ]key|bearer)"),
    "shell": re.compile(r"\b(subprocess|os\.system|shell=True|child_process)"),
    "network": re.compile(r"\b(requests\.|urllib|http\.client|socket\.|fetch\()"),
    "deserialization": re.compile(r"\b(pickle|marshal|yaml\.load|ObjectInputStream)"),
}

GIT_FLAGS = [
    "--no-optional-locks", "-c", "core.fsmonitor=false", "-c", "core.hooksPath=/dev/null", "-c", "diff.external=",
]
DIFF_FLAGS = ["--no-ext-diff", "--no-textconv"]


class Git:
    """Runs git in one directory under one deadline; `run` returns the capped stdout or None."""

    def __init__(self, cwd: str) -> None:
        self.cwd = cwd
        self.deadline = time.monotonic() + DEADLINE_SECONDS
        self.exe = shutil.which("git", path=SAFE_PATH)
        self.env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
        self.env["PATH"] = SAFE_PATH

    def run(self, *args: str) -> str | None:
        if self.exe is None:
            return None
        proc = subprocess.Popen(
            [self.exe, *GIT_FLAGS, *args],
            cwd=self.cwd, env=self.env, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
        )
        chunks: list[bytes] = []
        size = 0
        try:
            while size < CAP:
                left = self.deadline - time.monotonic()
                if left <= 0:
                    return None
                if not select.select([proc.stdout], [], [], left)[0]:
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


def default_ref(git: Git) -> str | None:
    head = git.run("symbolic-ref", "--short", "refs/remotes/origin/HEAD")
    if head and head.strip().startswith("origin/"):
        return head.strip()
    for name in ("main", "master"):
        if git.run("rev-parse", "--verify", "--quiet", f"refs/heads/{name}") is not None:
            return name
    return None


def changed_lines(numstat: str) -> int:
    total = 0
    for row in numstat.splitlines():
        added, _, rest = row.partition("\t")
        deleted = rest.partition("\t")[0]
        if added.isdigit() and deleted.isdigit():  # binary files show "-"
            total += int(added) + int(deleted)
    return total


def security_hits(paths: str, diff: str) -> list[str]:
    added = [line[1:] for line in diff.splitlines() if line.startswith("+") and not line.startswith("+++")]
    haystack = paths.splitlines() + added
    return [name for name, pattern in CATEGORIES.items() if any(pattern.search(text) for text in haystack)]


def review_context(cwd: str) -> str | None:
    git = Git(cwd)
    ref = default_ref(git)
    if ref is None:
        return None
    base = git.run("merge-base", ref, "HEAD")
    if not base or not base.strip():
        return None
    base = base.strip()
    parts = []
    numstat = git.run("diff", "--numstat", *DIFF_FLAGS, base) or ""
    lines = changed_lines(numstat)
    if lines > LARGE_DIFF:
        parts.append(f"the diff is {lines} changed lines (over {LARGE_DIFF}): run oh-my-claudecode:code-simplifier first")
    subjects = git.run("log", "--format=%s", f"{base}..HEAD") or ""
    if any(FIXUP.match(s) or WIP.match(s) for s in subjects.splitlines()):
        parts.append("the branch has fixup or WIP commits: run oh-my-claudecode:git-master to clean the history first")
    paths = git.run("diff", "--name-only", *DIFF_FLAGS, base) or ""
    patch = git.run("diff", "-U0", *DIFF_FLAGS, base) or ""
    hits = security_hits(paths, patch)
    if hits:
        parts.append(f"the changes touch {', '.join(hits)}: run oh-my-claudecode:security-reviewer")
    if not parts:
        return None
    return "Review pre-check: " + "; ".join(parts) + "."


def emit(event: str, **fields: str) -> None:
    print(json.dumps({"hookSpecificOutput": {"hookEventName": event, **fields}}))


def main() -> None:
    try:
        payload = json.loads(sys.stdin.buffer.read().decode("utf-8"))
        event = payload["hook_event_name"]
        if event == "PreToolUse":
            if payload["tool_name"] != "Skill":
                return
            name = payload["tool_input"]["skill"]
        elif event == "UserPromptExpansion":
            name = payload["command_name"]
        else:
            return
        cwd = payload.get("cwd")
        if not isinstance(name, str) or not NAME.fullmatch(name):
            return
    except Exception:
        return
    try:
        if name in AUTOPILOT and event == "PreToolUse":
            emit(event, permissionDecision="ask", permissionDecisionReason=AUTOPILOT_REASON)
        elif name in REVIEW and isinstance(cwd, str) and "\0" not in cwd:
            text = review_context(cwd)
            if text:
                emit(event, additionalContext=text)
    except Exception:
        sys.stderr.write("skill_gate: error\n")


if __name__ == "__main__":
    try:
        main()
    finally:
        sys.exit(0)
