"""Skill gate: review pre-check from git facts, and an ask before the model starts autopilot.

Events: PreToolUse (tool_name Skill, name in tool_input.skill) and UserPromptExpansion
(name in command_name). On a review skill it prints context naming the agent to run first:
code-simplifier (diff over 300 changed lines), git-master (fixup or WIP commits) and
security-reviewer (a secret-prone category in the diff). It uses integers and fixed names only.
On PreToolUse, `autopilot` prints an "ask": the model must not start autopilot unprompted. A
typed /autopilot arrives as UserPromptExpansion and passes. Always exits 0.

Git runs hardened. A diff in a repo with core.fsmonitor, diff.external or a filter.<name>
program set runs those programs, and so does `git log` with log.showSignature and gpg.program
(spikes left marker files). The flags override that config; each filter name in the config is
listed first and its programs emptied on every diff, and a name that cannot be overridden skips
the diff. GIT_* variables are dropped, git is found once on a fixed PATH, output is capped at
64 KiB, and one 5-second deadline covers every git call. bash_guard.py holds the same hardening;
a test keeps the two equal.
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
SAFE_PATH = "/usr/local/bin:/usr/bin:/bin"  # git is looked up here, never on the caller's PATH

# Skill names are short tokens; anything else is ignored before git runs.
NAME = re.compile(r"[a-z0-9-]+(:[a-z0-9-]+)?")
REVIEW = {"review", "omc-review", "oh-my-claudecode:review", "oh-my-claudecode:omc-review"}
AUTOPILOT = {"autopilot", "oh-my-claudecode:autopilot"}
AUTOPILOT_REASON = "Autopilot runs only when you ask for it (global rule: do not use autopilot unless the user asks)"

FIXUP = re.compile(r"(fixup|squash|amend)!")
WIP = re.compile(r"(?i)wip\b")
CATEGORIES = {
    # Whole words only, so prose such as "author" or "the session ended" misses; `_` and digits
    # still separate words, so `get_password` hits. A session counts only as a token name.
    "auth": re.compile(
        r"(?i)(?<![a-z])(auth(n|z|enticat(e[ds]?|ion|ors?)|ori[sz](e[ds]?|ation))?|logins?|passw(or)?ds?"
        r"|credentials?|oauth|jwts?|session[_-]?(id|token|key|cookie)s?)(?![a-z])"
    ),
    "input": re.compile(r"\b(json\.loads|yaml\.load|pickle\.loads?|eval\(|exec\()"),
    "secrets": re.compile(r"(?i)(secret|api[_-]?key|private[_ ]key|bearer)"),
    "shell": re.compile(r"\b(subprocess|os\.system|shell=True|child_process)"),
    "network": re.compile(r"\b(requests\.|urllib|http\.client|socket\.|fetch\()"),
    "deserialization": re.compile(r"\b(pickle|marshal|yaml\.load|ObjectInputStream)"),
}

# Override repo config that would run programs (see the module docstring).
GIT_FLAGS = [
    "--no-optional-locks", "-c", "core.fsmonitor=false", "-c", "core.hooksPath=/dev/null", "-c", "diff.external=",
    "-c", "log.showSignature=false",
]
# A repo's diff driver or textconv filter is a program; keep diffs to built-in output.
DIFF_FLAGS = ["--no-ext-diff", "--no-textconv"]
# Lists the filter keys of every config file; reading config runs nothing.
FILTER_LISTING = ["config", "--null", "--name-only", "--get-regexp", r"^filter\."]


def filter_overrides(listing: str) -> list[str] | None:
    """-c flags that empty the programs of each filter in a FILTER_LISTING output.

    None when a name cannot be passed as `-c filter.<name>.<key>=` (it holds `=` or bytes that
    are not UTF-8) or the listing is cut short; the caller then skips the diff.
    """
    if not listing:
        return []
    if not listing.endswith("\0") or "�" in listing or len(listing.encode()) >= CAP:
        return None
    flags: list[str] = []
    names: set[str] = set()
    for key in listing[:-1].split("\0"):
        name = key[len("filter."):].rpartition(".")[0]  # filter.<name>.<key>; a name may hold dots
        if "=" in name:
            return None
        if name and name not in names:
            names.add(name)
            for setting in ("clean=", "smudge=", "process=", "required=false"):
                flags += ["-c", f"filter.{name}.{setting}"]
    return flags


class Git:
    """Runs git in one directory under one deadline; `run` returns the capped stdout or None."""

    def __init__(self, cwd: str) -> None:
        self.cwd = cwd
        self.deadline = time.monotonic() + DEADLINE_SECONDS
        self.exe = shutil.which("git", path=SAFE_PATH)
        self.env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
        self.env["PATH"] = SAFE_PATH
        self.filters: list[str] | None = None
        self.filters_read = False

    def diff(self, *args: str) -> str | None:
        """`git diff` with the repo's filter programs emptied; None when they cannot be."""
        if not self.filters_read:
            self.filters_read = True
            self.filters = filter_overrides(self.run(*FILTER_LISTING) or "")
        if self.filters is None:
            return None
        return self.run(*self.filters, "diff", *args)

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
        # -9 is our own kill in `finally`, sent after git closed stdout: the output is complete.
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
    """The categories hit by changed paths or added lines; removed lines do not count."""
    added = [line[1:] for line in diff.splitlines() if line.startswith("+") and not line.startswith("+++")]
    haystack = paths.splitlines() + added
    return [name for name, pattern in CATEGORIES.items() if any(pattern.search(text) for text in haystack)]


def review_context(cwd: str) -> str | None:
    """The review pre-check for the branch against its merge-base with the default branch, or None."""
    git = Git(cwd)
    ref = default_ref(git)
    if ref is None:
        return None
    base = git.run("merge-base", ref, "HEAD")
    if not base or not base.strip():
        return None
    base = base.strip()
    parts = []
    numstat = git.diff("--numstat", *DIFF_FLAGS, base) or ""
    lines = changed_lines(numstat)
    if lines > LARGE_DIFF:
        parts.append(f"the diff is {lines} changed lines (over {LARGE_DIFF}): run oh-my-claudecode:code-simplifier first")
    subjects = git.run("log", "--format=%s", f"{base}..HEAD") or ""
    if any(FIXUP.match(s) or WIP.match(s) for s in subjects.splitlines()):  # history cleanup first
        parts.append("the branch has fixup or WIP commits: run oh-my-claudecode:git-master to clean the history first")
    paths = git.diff("--name-only", *DIFF_FLAGS, base) or ""
    patch = git.diff("-U0", *DIFF_FLAGS, base) or ""
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
        # A NUL byte would make subprocess raise; such a cwd is skipped, not reported.
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
