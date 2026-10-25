"""Bash guard: asks before a command breaks a source-control rule of the global CLAUDE.md.

PreToolUse(Bash). One process reads the command once and parses it like a shell: `git` and `gh`
count only at command position (the start, or after && || ; | & a newline ( $( or a backtick,
past leading VAR=value words and `env`/`command`); quoted text, heredoc bodies, comments and
arguments of other commands never do. Each `cd`, `git checkout` and `git switch` applies in order,
so a commit is judged on the branch it lands on. The target repo is `git -C <path>`, else the
directory after the `cd` steps, else the payload's cwd. It asks when:

1. `git commit` lands on the default branch (origin/HEAD, else main or master) of a repo with an origin.
2. `git push` targets the default branch (empty refspec and HEAD mean the current branch; `:main`,
   `--delete`, `--mirror`, `--all`, `--prune` count; so does a force with HEAD on it), or
   `git branch -d/-D/-m/-M` names it; in a repo with an origin.
3. the commit subject is not a Conventional Commit ending in (#N), (owner/repo#N) or (KEY-N), only on
   a lifecycle branch (type/{issue}-slug); a `chore(release):` subject and an unreadable message pass.
4. a new branch name (checkout -b/-B, switch -c/-C, branch <name>, worktree add -b/-B) is not
   type/{issue}-slug, in a repo with an origin; improve/, experiment/ and omc-team/ are exempt.
5. the content going into a commit holds a secret file name or an added line matching a token pattern.
6. `gh issue edit`, `gh issue create` or `gh api` adds the label `approved`.

Anything it cannot determine passes. Every decision is "ask" with fixed reason strings; the only
values added are counts and fixed pattern names. Not a security boundary: aliases, eval and
scripts get past it; branch protection on the remote is the control that holds.

Hardening: git runs by absolute path with a fixed argv, no repo config that executes code, no
external diff or textconv, no GIT_* variables, output capped at 64 KiB. A file a command names is
opened O_NONBLOCK|O_NOFOLLOW, read only when fstat says regular, at most 64 KiB. One 5-second
deadline covers the hook. Always exits 0; an unexpected error is one fixed code on stderr.
"""

import json
import os
import re
import select
import shutil
import signal
import stat
import subprocess
import sys
import time

DEADLINE_SECONDS = 5
CAP = 64 * 1024
UNTRACKED_BUDGET = 1024 * 1024
MAX_DEPTH = 32
SUBJECT_MAX = 200
SAFE_PATH = "/usr/local/bin:/usr/bin:/bin"

GIT_FLAGS = [
    "--no-optional-locks", "-c", "core.fsmonitor=false", "-c", "core.hooksPath=/dev/null", "-c", "diff.external=",
]
DIFF_FLAGS = ["--no-ext-diff", "--no-textconv", "--no-color"]

# The subject rules are the lifecycle scripts' own (github-issue-lifecycle/scripts/issue_lifecycle.py,
# jira-ticket-lifecycle/scripts/ticket_lifecycle.py); a test compares them with `ast`.
CC_TYPES = (
    "feat",
    "fix",
    "docs",
    "style",
    "refactor",
    "perf",
    "test",
    "build",
    "ci",
    "chore",
    "revert",
)
SUBJECT_RE = re.compile(rf"^(?:{'|'.join(CC_TYPES)})(?:\([^()\s]+\))?(!)?: \S.*$")
ISSUE_REF_RE = re.compile(r"\((?:[\w.-]+/[\w.-]+)?#\d+\)$")
TICKET_REF_RE = re.compile(r" \(([A-Z][A-Z0-9_]{1,9}-[0-9]+)\)$")
RELEASE_PREFIX = "chore(release):"

LIFECYCLE_BRANCH = re.compile(r"(feature|fix|hotfix|docs|chore)/(\d+|[A-Z][A-Z0-9]+-\d+)-[a-z0-9-]+")
EXEMPT_PREFIXES = ("improve/", "experiment/", "omc-team/")

# Secret file: the same definition as secrets_guard.py; a test keeps them equal.
SAFE_SUFFIXES = {"example", "sample", "template"}
TOKENS = {
    "sk": re.compile(r"\bsk-[A-Za-z0-9]{20,}"),
    "ghp": re.compile(r"\bghp_[A-Za-z0-9]{36}"),
    "gho": re.compile(r"\bgho_[A-Za-z0-9]{36}"),
    "github_pat": re.compile(r"\bgithub_pat_[A-Za-z0-9_]{22,}"),
    "xox": re.compile(r"\bxox[bp]-[A-Za-z0-9-]{10,}"),
}

COMMIT_REASON = "This commit lands on the default branch (global rule: never commit to the default branch; commit on the issue branch)"
PUSH_REASON = "This targets the default branch (global rule: never push, force-push or delete the default branch)"
SUBJECT_REASON = "The commit subject is not a Conventional Commit ending in the issue reference, such as 'fix(scope): text (#N)' (global rule)"
BRANCH_REASON = "The new branch name does not match feature|fix|hotfix|docs|chore/{issue}-{slug} (global rule)"
SECRET_REASON = "The commit content holds {files} secret file name(s) and {tokens} token match(es){kinds} (global rule: never commit tokens or .env)"
LABEL_REASON = "Adding the approved label needs your confirmation (global rule: set no approval marker yourself)"

EXPANSION = "\0"  # stands in a word for $VAR, $(...) or `...`; a command holding a real NUL is ignored
PLAIN = re.compile(r"[^\s;&|()<>'\"\\$`*?\[]+")
ASSIGNMENT = re.compile(r"[A-Za-z_][A-Za-z0-9_]*=")
RESERVED = {"if", "then", "else", "elif", "do", "while", "until", "!", "{", "time"}
REPO_VARIABLES = ("GIT_DIR=", "GIT_WORK_TREE=", "GIT_INDEX_FILE=")


class Timeout(Exception):
    pass


class Unparsed(Exception):
    pass


# ── the shell parser ─────────────────────────────────────────────────────────


class Word:
    __slots__ = ("text", "subs", "glob")

    def __init__(self) -> None:
        self.text = ""
        self.subs: list[list[Segment]] = []  # the commands of each $(...) or `...` in the word
        self.glob = False


class Segment:
    """One simple command: its words and the bodies of its heredocs."""

    __slots__ = ("words", "heredocs")

    def __init__(self) -> None:
        self.words: list[Word] = []
        self.heredocs: list[str] = []


class Parser:
    """A single left-to-right pass over the command; nested $(...) and `...` recurse up to MAX_DEPTH."""

    def __init__(self, text: str) -> None:
        self.s = text
        self.n = len(text)
        self.i = 0
        self.segments: list[Segment] = []
        self.pending: list[tuple[str, bool, Segment]] = []  # heredocs that start after the next newline

    def parse(self) -> list[Segment]:
        self.commands(None, 0)
        return self.segments

    def new_segment(self) -> Segment:
        seg = Segment()
        self.segments.append(seg)
        return seg

    def commands(self, closer: str | None, depth: int) -> None:
        if depth > MAX_DEPTH:
            raise Unparsed
        s = self.s
        seg = self.new_segment()
        while self.i < self.n:
            c = s[self.i]
            if c == closer:
                self.i += 1
                return
            if c in " \t\r":
                self.i += 1
            elif c == "\n":
                self.i += 1
                self.read_heredocs()
                seg = self.new_segment()
            elif c == "\\" and s.startswith("\n", self.i + 1):
                self.i += 2
            elif c == "#":
                end = s.find("\n", self.i)
                self.i = self.n if end < 0 else end
            elif c == "&" and s.startswith(">", self.i + 1):
                self.i += 1
                self.redirection(seg, closer, depth)
            elif c in ";&|()":
                self.i += 1
                seg = self.new_segment()
            elif c in "<>":
                self.redirection(seg, closer, depth)
            else:
                word = self.word(closer, depth)
                if word.text.isdigit() and self.i < self.n and s[self.i] in "<>":
                    continue  # a file descriptor, as in 2>&1
                seg.words.append(word)

    def read_heredocs(self) -> None:
        pending, self.pending = self.pending, []
        s = self.s
        for delimiter, strip_tabs, seg in pending:
            lines = []
            while self.i < self.n:
                end = s.find("\n", self.i)
                end = self.n if end < 0 else end
                line = s[self.i:end]
                self.i = min(end + 1, self.n)
                if strip_tabs:
                    line = line.lstrip("\t")
                if line == delimiter:
                    break
                lines.append(line)
            seg.heredocs.append("\n".join(lines))

    def skip_blanks(self) -> None:
        while self.i < self.n and self.s[self.i] in " \t":
            self.i += 1

    def redirection(self, seg: Segment, closer: str | None, depth: int) -> None:
        s = self.s
        if s.startswith("<<<", self.i):
            self.i += 3
            self.skip_blanks()
            self.word(closer, depth)  # a here-string is data
            return
        if s.startswith("<<", self.i):
            self.i += 2
            strip_tabs = s.startswith("-", self.i)
            self.i += strip_tabs
            self.skip_blanks()
            self.pending.append((self.word(closer, depth).text, strip_tabs, seg))
            return
        while self.i < self.n and s[self.i] in "<>&|":
            self.i += 1
        self.skip_blanks()
        if self.i < self.n and s[self.i] not in "\n;&|()" and s[self.i] != closer:
            self.word(closer, depth)  # the redirection target is not an argument

    def word(self, closer: str | None, depth: int) -> Word:
        s = self.s
        w = Word()
        parts: list[str] = []
        while self.i < self.n:
            c = s[self.i]
            if c in " \t\r\n;&|()<>" or c == closer:
                break
            plain = PLAIN.match(s, self.i)
            if plain:
                parts.append(plain.group())
                self.i = plain.end()
                continue
            self.i += 1
            if c == "'":
                end = s.find("'", self.i)
                end = self.n if end < 0 else end
                parts.append(s[self.i:end])
                self.i = min(end + 1, self.n)
            elif c == '"':
                self.double_quoted(w, parts, depth)
            elif c == "\\":
                if self.i < self.n:
                    if s[self.i] != "\n":
                        parts.append(s[self.i])
                    self.i += 1
            elif c == "$":
                self.dollar(w, parts, depth, quoted=False)
            elif c == "`":
                w.subs.append(self.substitution("`", depth))
                parts.append(EXPANSION)
            else:  # * ? [
                w.glob = True
                parts.append(c)
        w.text = "".join(parts)
        return w

    def double_quoted(self, w: Word, parts: list[str], depth: int) -> None:
        s = self.s
        while self.i < self.n:
            c = s[self.i]
            self.i += 1
            if c == '"':
                return
            if c == "\\" and self.i < self.n and s[self.i] in '$`"\\\n':
                if s[self.i] != "\n":
                    parts.append(s[self.i])
                self.i += 1
            elif c == "$":
                self.dollar(w, parts, depth, quoted=True)
            elif c == "`":
                w.subs.append(self.substitution("`", depth))
                parts.append(EXPANSION)
            else:
                parts.append(c)

    def dollar(self, w: Word, parts: list[str], depth: int, quoted: bool) -> None:
        s = self.s
        nxt = s[self.i] if self.i < self.n else ""
        if nxt == "(":
            self.i += 1
            w.subs.append(self.substitution(")", depth))
        elif nxt == "{":
            end = s.find("}", self.i)
            self.i = self.n if end < 0 else end + 1
        elif nxt == "'" and not quoted:  # $'...': escapes are not decoded, so the value is unknown
            self.i += 1
            while self.i < self.n and s[self.i] != "'":
                self.i += 2 if s[self.i] == "\\" else 1
            self.i = min(self.i + 1, self.n)
        elif nxt and nxt in "@*#?$!-0123456789":
            self.i += 1
        elif nxt and (nxt.isalpha() or nxt == "_"):
            while self.i < self.n and (s[self.i].isalnum() or s[self.i] == "_"):
                self.i += 1
        else:
            parts.append("$")
            return
        parts.append(EXPANSION)

    def substitution(self, closer: str, depth: int) -> list[Segment]:
        start = len(self.segments)
        self.commands(closer, depth + 1)
        return self.segments[start:]


def command_words(seg: Segment) -> list[Word]:
    """The words from the command name on: assignments, `env`, `command` and keywords skipped."""
    words = seg.words
    i = 0
    while i < len(words):
        text = words[i].text
        if ASSIGNMENT.match(text):
            if text.startswith(REPO_VARIABLES):
                return []  # the repo is set by the environment: undeterminable
            i += 1
        elif text in RESERVED:
            i += 1
        elif text == "env":
            i += 1
            while i < len(words) and words[i].text.startswith("-"):
                if words[i].text in ("-C", "--chdir", "-S", "--split-string") or words[i].text.startswith("--chdir="):
                    return []
                i += 2 if words[i].text in ("-u", "--unset") else 1
        elif text == "command":
            i += 1
            while i < len(words) and words[i].text in ("-p", "--"):
                i += 1
        else:
            return words[i:]
    return []


# ── git ──────────────────────────────────────────────────────────────────────


def run_git(exe: str, cwd: str, args: list[str], deadline: float) -> str | None:
    """git's stdout capped at CAP, or None on failure or past the deadline. The tests' seam."""
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    env["PATH"] = SAFE_PATH
    try:
        proc = subprocess.Popen(
            [exe, *GIT_FLAGS, *args],
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


def git_parts(words: list[Word]) -> tuple[list[str] | None, str, list[Word]] | None:
    """The -C paths (None when --git-dir or --work-tree leaves the repo open), subcommand and arguments."""
    paths: list[str] | None = []
    i = 1
    while i < len(words):
        text = words[i].text
        if text == "-C":
            if paths is not None:
                paths.append(words[i + 1].text if i + 1 < len(words) else EXPANSION)
            i += 2
        elif text in ("-c", "--namespace", "--config-env"):
            i += 2
        elif text in ("--git-dir", "--work-tree"):
            paths = None
            i += 2
        elif text.startswith(("--git-dir=", "--work-tree=")):
            paths = None
            i += 1
        elif text.startswith("-"):
            i += 1
        else:
            return paths, text, words[i + 1:]
    return None


def join_path(base: str | None, path: str) -> str | None:
    if EXPANSION in path:
        return None
    if path.startswith("~"):
        path = os.path.expanduser(path)
    if os.path.isabs(path):
        return os.path.normpath(path)
    if base is None:
        return None
    return os.path.normpath(os.path.join(base, path)) if path else base


def read_file(path: str, first_line: bool = False) -> bytes | None:
    """At most CAP bytes of a regular file, never following a final symlink and never blocking."""
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NONBLOCK | os.O_NOFOLLOW | os.O_CLOEXEC)
    except (OSError, ValueError):
        return None
    try:
        if not stat.S_ISREG(os.fstat(fd).st_mode):
            return None
        chunks: list[bytes] = []
        size = 0
        while size < CAP:
            chunk = os.read(fd, CAP - size)
            if not chunk:
                break
            chunks.append(chunk)
            size += len(chunk)
            if first_line and b"\n" in chunk:
                break
        data = b"".join(chunks)
        return data.split(b"\n", 1)[0] if first_line else data
    except OSError:
        return None
    finally:
        os.close(fd)


# ── the rules' pure checks ───────────────────────────────────────────────────


def names_secret(name: str) -> bool:
    if name == "deny-terms" or name == ".env":
        return True
    return name.startswith(".env.") and name[5:] not in SAFE_SUFFIXES


def subject_ok(subject: str) -> bool:
    """The lifecycle scripts' commit-check on a subject: Conventional, ending in (#N), (o/r#N) or (KEY-N)."""
    return bool(SUBJECT_RE.match(subject)) and bool(ISSUE_REF_RE.search(subject) or TICKET_REF_RE.search(subject))


def branch_name_ok(name: str) -> bool:
    return name.startswith(EXEMPT_PREFIXES) or LIFECYCLE_BRANCH.fullmatch(name) is not None


def first_subject(text: str) -> str | None:
    """The first non-blank line, right-stripped as git does; None when there is none or it is too long."""
    start = 0
    while start <= len(text):
        end = text.find("\n", start)
        end = len(text) if end < 0 else end
        if end - start > SUBJECT_MAX + 64:
            return None  # too long to be a checked subject, even after stripping
        line = text[start:end].rstrip()
        if line:
            return line if len(line) <= SUBJECT_MAX else None
        start = end + 1
    return None


def message_text(text: str, word: Word) -> str | None:
    """A message value's text: literal, or the heredoc of a lone $(cat <<EOF ...)."""
    if EXPANSION not in text:
        return text
    if text == EXPANSION and len(word.subs) == 1:
        inner = [seg for seg in word.subs[0] if seg.words or seg.heredocs]
        if len(inner) == 1 and [w.text for w in inner[0].words] == ["cat"] and len(inner[0].heredocs) == 1:
            return inner[0].heredocs[0]
    return None


COMMIT_VALUE_LONG = {
    "--message": "m", "--file": "F", "--reuse-message": "C", "--reedit-message": "c", "--fixup": "C",
    "--squash": "C", "--author": "", "--date": "", "--template": "", "--trailer": "", "--cleanup": "",
    "--pathspec-from-file": "",
}


def commit_options(args: list[Word]) -> tuple[list[tuple[str, Word]], list[str], bool, bool]:
    """(the -m values, the -F values, whether the message comes from a commit, whether -a is set)."""
    messages: list[tuple[str, Word]] = []
    files: list[str] = []
    reused = every = False
    i = 0
    while i < len(args):
        word = args[i]
        text = word.text
        i += 1
        if text == "--":
            break
        kind, value = None, None
        if text.startswith("--"):
            name, eq, rest = text.partition("=")
            if name == "--all":
                every = True
            elif name in COMMIT_VALUE_LONG:
                kind = COMMIT_VALUE_LONG[name]
                if eq:
                    value = (rest, word)
                elif i < len(args):
                    value = (args[i].text, args[i])
                    i += 1
        elif text.startswith("-") and len(text) > 1:
            for j, ch in enumerate(text[1:], 1):
                if ch == "a":
                    every = True
                elif ch in "mFCct":
                    kind = "C" if ch == "c" else ("" if ch == "t" else ch)
                    rest = text[j + 1:]
                    if rest:
                        value = (rest, word)
                    elif i < len(args):
                        value = (args[i].text, args[i])
                        i += 1
                    break
                elif ch == "S":
                    break  # -S[<keyid>]: the rest is its value
        if value is None:
            continue
        if kind == "m":
            messages.append(value)
        elif kind == "F":
            files.append(value[0])
        elif kind == "C":
            reused = True
    return messages, files, reused, every


def commit_subject(args: list[Word], seg: Segment, cwd: str) -> str | None:
    messages, files, reused, _ = commit_options(args)
    if reused:
        return None
    if messages:
        text = message_text(*messages[0])
        return None if text is None else first_subject(text)
    if files:
        if files[0] == "-":
            return first_subject(seg.heredocs[0]) if len(seg.heredocs) == 1 else None
        path = join_path(cwd, files[0])
        data = None if path is None else read_file(path, first_line=True)
        if data is None:
            return None
        try:
            line = data.decode("utf-8").rstrip()
        except UnicodeDecodeError:
            return None
        return line if line and len(line) <= SUBJECT_MAX else None
    return None


def added_lines(patch: str):
    in_hunk = False
    for line in patch.split("\n"):
        if line.startswith("diff --git "):
            in_hunk = False
        elif line.startswith("@@"):
            in_hunk = True
        elif in_hunk and line.startswith("+"):
            yield line[1:]


def label_values(texts: list[str], names: set[str], short: str):
    i = 0
    while i < len(texts):
        text = texts[i]
        i += 1
        name, eq, rest = text.partition("=")
        if name in names:
            if eq:
                yield rest
            elif i < len(texts):
                yield texts[i]
                i += 1
        elif short and text.startswith("-" + short) and not text.startswith("--"):
            if len(text) > 2:
                yield text[2:]
            elif i < len(texts):
                yield texts[i]
                i += 1


def is_approved(value: str) -> bool:
    return "approved" in (part.strip() for part in value.split(","))


def adds_approved(args: list[Word]) -> bool:
    texts = [w.text for w in args]
    if len(texts) >= 2 and texts[0] == "issue" and texts[1] in ("edit", "create"):
        return any(is_approved(v) for v in label_values(texts[2:], {"--add-label", "--label"}, "l"))
    if texts and texts[0] == "api":
        for value in label_values(texts[1:], {"-f", "-F", "--field", "--raw-field"}, ""):
            key, eq, rest = value.partition("=")
            if eq and key in ("labels", "labels[]") and is_approved(rest):
                return True
    return False


# ── the rules against git state ──────────────────────────────────────────────


class Guard:
    def __init__(self, deadline: float, exe: str | None) -> None:
        self.deadline = deadline
        self.exe = exe
        self.cache: dict[tuple, object] = {}
        self.branches: dict[str, str | None] = {}  # per work tree: the branch after this command's steps
        self.scanned: set[tuple[str, str]] = set()
        self.reasons: list[str] = []
        self.secret_files: set[str] = set()
        self.tokens: set[tuple[str, str]] = set()
        self.add_and_commit = False
        self.untracked_left = UNTRACKED_BUDGET

    def ask(self, reason: str) -> None:
        if reason not in self.reasons:
            self.reasons.append(reason)

    def git(self, cwd: str, *args: str) -> str | None:
        if self.exe is None:
            return None
        if time.monotonic() >= self.deadline:
            raise Timeout
        out = run_git(self.exe, cwd, list(args), self.deadline)
        if time.monotonic() >= self.deadline:
            raise Timeout
        return out

    def cached(self, key: tuple, compute):
        if key not in self.cache:
            self.cache[key] = compute()
        return self.cache[key]

    # repo facts

    def top(self, d: str | None) -> str | None:
        if d is None:
            return None

        def compute():
            out = self.git(d, "rev-parse", "--show-toplevel")
            top = out.rstrip("\n") if out else ""
            return top if os.path.isabs(top) else None

        return self.cached(("top", d), compute)

    def has_origin(self, top: str) -> bool:
        return self.cached(("origin", top), lambda: "origin" in (self.git(top, "remote") or "").split("\n"))

    def default(self, top: str) -> str | None:
        def compute():
            head = (self.git(top, "symbolic-ref", "--quiet", "--short", "refs/remotes/origin/HEAD") or "").strip()
            if head.startswith("origin/") and len(head) > 7:
                return head[7:]
            refs = self.refs(top, "refs/heads/main", "refs/heads/master", "refs/remotes/origin/main", "refs/remotes/origin/master")
            for name in ("main", "master"):
                if f"refs/heads/{name}" in refs or f"refs/remotes/origin/{name}" in refs:
                    return name
            return None

        return self.cached(("default", top), compute)

    def is_default(self, top: str, name: str | None) -> bool:
        if not name:
            return False
        default = self.default(top)
        return name == default if default else name in ("main", "master")

    def refs(self, top: str, *patterns: str) -> set[str]:
        return set((self.git(top, "for-each-ref", "--format=%(refname)", *patterns) or "").split("\n"))

    def branch(self, top: str) -> str | None:
        if top not in self.branches:
            out = (self.git(top, "symbolic-ref", "--quiet", "--short", "HEAD") or "").strip()
            self.branches[top] = out or None
        return self.branches[top]

    # the walk

    def check(self, segments: list[Segment], cwd: str | None) -> str | None:
        commands = [words for seg in segments if (words := command_words(seg))]
        subs = [git_parts(w) for w in commands if os.path.basename(w[0].text) == "git"]
        names = {p[1] for p in subs if p}
        self.add_and_commit = "add" in names and "commit" in names
        for seg in segments:
            words = command_words(seg)
            if not words or EXPANSION in words[0].text:
                continue
            name = os.path.basename(words[0].text)
            if name == "cd":
                cwd = self.cd(cwd, [w.text for w in words[1:]])
            elif name == "git":
                self.git_command(seg, words, cwd)
            elif name == "gh" and adds_approved(words[1:]):
                self.ask(LABEL_REASON)
        if self.secret_files or self.tokens:
            kinds = sorted({kind for kind, _ in self.tokens})
            self.ask(SECRET_REASON.format(
                files=len(self.secret_files), tokens=len(self.tokens),
                kinds=f" (patterns: {', '.join(kinds)})" if kinds else "",
            ))
        return "; ".join(self.reasons) or None

    def cd(self, cwd: str | None, args: list[str]) -> str | None:
        while args and args[0] in ("-L", "-P", "-e", "-@"):
            args = args[1:]
        if args and args[0] == "--":
            args = args[1:]
        if not args:
            home = os.environ.get("HOME")
            return home if home and os.path.isabs(home) else None
        if args[0] == "-":
            return None
        return join_path(cwd, args[0])

    def git_command(self, seg: Segment, words: list[Word], cwd: str | None) -> None:
        parts = git_parts(words)
        if parts is None or parts[0] is None:
            return
        paths, sub, args = parts
        d = cwd
        for path in paths:
            d = join_path(d, path)
        handler = {
            "commit": self.commit, "push": self.push, "add": self.add, "checkout": self.checkout,
            "switch": self.switch, "branch": self.branch_command, "worktree": self.worktree,
        }.get(sub)
        if handler is None:
            return
        top = self.top(d)
        if top is not None:
            handler(top, d, args, seg)

    def new_branch(self, top: str, name: str) -> None:
        if EXPANSION not in name and self.has_origin(top) and not branch_name_ok(name):
            self.ask(BRANCH_REASON)

    # rules 1, 3 and 5: commits

    def commit(self, top: str, d: str, args: list[Word], seg: Segment) -> None:
        branch = self.branch(top)
        if branch and self.has_origin(top) and self.is_default(top, branch):
            self.ask(COMMIT_REASON)
        if branch and LIFECYCLE_BRANCH.fullmatch(branch):
            subject = commit_subject(args, seg, d)
            if subject is not None and not subject.startswith(RELEASE_PREFIX) and not subject_ok(subject):
                self.ask(SUBJECT_REASON)
        if self.add_and_commit:
            self.scan(top, "broad")
        self.scan(top, "head" if commit_options(args)[3] else "cached")

    def add(self, top: str, d: str, args: list[Word], seg: Segment) -> None:
        broad = False
        options = True
        for word in args:
            text = word.text
            if options and text == "--":
                options = False
            elif options and text.startswith("-") and len(text) > 1:
                long_broad = text.partition("=")[0] in (
                    "--all", "--update", "--no-ignore-removal", "--patch", "--interactive", "--edit", "--pathspec-from-file",
                )
                if long_broad or (not text.startswith("--") and any(ch in "Aupie" for ch in text[1:])):
                    broad = True
            elif EXPANSION in text or word.glob or text.startswith(":"):
                broad = True
            else:
                path = join_path(d, text)
                if path is None or os.path.isdir(path):
                    broad = True
                    continue
                if names_secret(os.path.basename(path)):
                    self.secret_files.add(path)
                data = read_file(path)
                if data is not None:
                    self.scan_lines(data.decode("utf-8", errors="replace").split("\n"))
        if broad:
            self.scan(top, "broad")

    def scan(self, top: str, kind: str) -> None:
        if (top, kind) in self.scanned:
            return
        self.scanned.add((top, kind))
        if kind == "cached":
            self.scan_diff(top, "--cached")
            return
        if not self.scan_diff(top, "HEAD"):
            self.scan_diff(top, "--cached")  # no commit yet
        if kind == "broad":
            out = self.git(top, "ls-files", "-z", "-o", "--exclude-standard") or ""
            for name in out.split("\0"):
                if not name:
                    continue
                path = os.path.join(top, name)
                if names_secret(os.path.basename(name)):
                    self.secret_files.add(path)
                if self.untracked_left > 0:
                    data = read_file(path)
                    if data is not None:
                        self.untracked_left -= len(data)
                        self.scan_lines(data.decode("utf-8", errors="replace").split("\n"))

    def scan_diff(self, top: str, rev: str) -> bool:
        names = self.git(top, "diff", *DIFF_FLAGS, "--name-only", "-z", "--diff-filter=d", rev)
        if names is None:
            return False
        for name in names.split("\0"):
            if name and names_secret(os.path.basename(name)):
                self.secret_files.add(os.path.join(top, name))
        self.scan_lines(added_lines(self.git(top, "diff", *DIFF_FLAGS, "-U0", rev) or ""))
        return True

    def scan_lines(self, lines) -> None:
        for line in lines:
            for kind, pattern in TOKENS.items():
                for match in pattern.finditer(line):
                    self.tokens.add((kind, match.group()))

    # rule 2: pushes and branch deletes

    def push(self, top: str, d: str, args: list[Word], seg: Segment) -> None:
        if not self.has_origin(top):
            return
        force = every = delete = tags = False
        positional: list[str] = []
        i = 0
        while i < len(args):
            text = args[i].text
            i += 1
            if text == "--":
                positional += [w.text for w in args[i:]]
                break
            if text.startswith("--"):
                name = text.partition("=")[0]
                if name in ("--mirror", "--all", "--branches", "--prune"):
                    every = True
                elif name == "--force":
                    force = True
                elif name == "--delete":
                    delete = True
                elif name == "--tags":
                    tags = True
                elif name in ("--repo", "--push-option", "--receive-pack", "--exec") and "=" not in text:
                    i += 1
            elif text.startswith("-") and len(text) > 1:
                for j, ch in enumerate(text[1:], 1):
                    if ch == "f":
                        force = True
                    elif ch == "d":
                        delete = True
                    elif ch == "o":
                        i += 0 if text[j + 1:] else 1
                        break
            else:
                positional.append(text)
        if every:
            self.ask(PUSH_REASON)
            return
        current = self.branch(top)
        targets: list[str | None] = []
        if len(positional) < 2 and not delete and not tags:
            targets.append(current)
        for spec in positional[1:]:
            if EXPANSION in spec:
                continue
            if spec.startswith("+"):
                force = True
                spec = spec[1:]
            if delete:
                dst = spec
            else:
                src, colon, dst = spec.partition(":")
                dst = dst if colon and dst else src
                if dst == "HEAD":
                    dst = current
            if dst and dst.startswith("refs/heads/"):
                dst = dst[len("refs/heads/"):]
            targets.append(dst)
        if any(self.is_default(top, t) for t in targets) or (force and self.is_default(top, current)):
            self.ask(PUSH_REASON)

    def branch_command(self, top: str, d: str, args: list[Word], seg: Segment) -> None:
        delete = move = other = remote = False
        positional: list[str] = []
        i = 0
        while i < len(args):
            text = args[i].text
            i += 1
            if text == "--":
                positional += [w.text for w in args[i:]]
                break
            if text.startswith("--"):
                name = text.partition("=")[0]
                if name == "--delete":
                    delete = True
                elif name == "--move":
                    move = True
                elif name in ("--remotes",):
                    remote = other = True
                elif name not in ("--force", "--track", "--no-track", "--quiet", "--create-reflog", "--recurse-submodules"):
                    other = True  # copy, list, display, upstream and description modes
                    if name in ("--set-upstream-to", "--sort", "--format", "--points-at") and "=" not in text:
                        i += 1
            elif text.startswith("-") and len(text) > 1:
                for j, ch in enumerate(text[1:], 1):
                    if ch in "dD":
                        delete = True
                    elif ch in "mM":
                        move = True
                    elif ch == "r":
                        remote = other = True
                    elif ch == "u":
                        other = True
                        i += 0 if text[j + 1:] else 1
                        break
                    elif ch not in "ftq":
                        other = True
            else:
                positional.append(text)
        if delete:
            if not remote and self.has_origin(top) and any(self.is_default(top, n) for n in positional):
                self.ask(PUSH_REASON)
        elif move:
            old = positional[0] if len(positional) >= 2 else self.branch(top)
            if self.has_origin(top) and self.is_default(top, old):
                self.ask(PUSH_REASON)
        elif not other and positional:
            self.new_branch(top, positional[0])

    # rule 4 and the branch a later commit lands on

    def checkout(self, top: str, d: str, args: list[Word], seg: Segment) -> None:
        created = target = None
        detach = paths = False
        i = 0
        while i < len(args):
            text = args[i].text
            i += 1
            if text == "--":
                paths = True
                break
            if text in ("-b", "-B", "--orphan"):
                if i < len(args):
                    created = args[i].text
                    i += 1
            elif text.startswith("--orphan="):
                created = text[len("--orphan="):]
            elif text[:2] in ("-b", "-B") and len(text) > 2:
                created = text[2:]
            elif text == "--detach":
                detach = True
            elif text == "-":
                target = target or "-"
            elif text.startswith("-"):
                continue
            elif target is None:
                target = text
        if created is not None:
            self.new_branch(top, created)
            self.branches[top] = None if EXPANSION in created else created
        elif target is not None and not paths:
            if detach or target == "-" or EXPANSION in target:
                self.branches[top] = None
            elif self.refs(top, f"refs/heads/{target}", f"refs/remotes/origin/{target}") & {f"refs/heads/{target}", f"refs/remotes/origin/{target}"}:
                self.branches[top] = target
            elif self.git(top, "rev-parse", "--verify", "--quiet", f"{target}^{{commit}}") is not None:
                self.branches[top] = None  # a detached HEAD
            # otherwise a path: the branch is unchanged

    def switch(self, top: str, d: str, args: list[Word], seg: Segment) -> None:
        created = target = None
        detach = False
        i = 0
        while i < len(args):
            text = args[i].text
            i += 1
            name, eq, rest = text.partition("=")
            if text in ("-c", "-C", "--create", "--force-create", "--orphan"):
                if i < len(args):
                    created = args[i].text
                    i += 1
            elif eq and name in ("--create", "--force-create", "--orphan"):
                created = rest
            elif text[:2] in ("-c", "-C") and len(text) > 2 and not text.startswith("--"):
                created = text[2:]
            elif text in ("-d", "--detach"):
                detach = True
            elif text == "-":
                target = target or "-"
            elif text.startswith("-"):
                continue
            elif target is None:
                target = text
        if created is not None:
            self.new_branch(top, created)
            self.branches[top] = None if EXPANSION in created else created
        elif target is not None:
            self.branches[top] = None if detach or target == "-" or EXPANSION in target else target

    def worktree(self, top: str, d: str, args: list[Word], seg: Segment) -> None:
        if not args or args[0].text != "add":
            return
        for i, word in enumerate(args[1:-1], 1):
            if word.text in ("-b", "-B"):
                self.new_branch(top, args[i + 1].text)
                return


# ── entry ────────────────────────────────────────────────────────────────────


def evaluate(payload) -> str | None:
    """The ask reason for a PreToolUse(Bash) payload, or None. Tests substitute run_git and DEADLINE_SECONDS."""
    if not isinstance(payload, dict) or payload.get("tool_name", "Bash") != "Bash":
        return None
    tool_input = payload.get("tool_input")
    command = tool_input.get("command") if isinstance(tool_input, dict) else None
    if not isinstance(command, str) or "\0" in command or ("git" not in command and "gh" not in command):
        return None
    cwd = payload.get("cwd")
    if not isinstance(cwd, str) or "\0" in cwd or not os.path.isabs(cwd):
        cwd = None
    deadline = time.monotonic() + DEADLINE_SECONDS
    try:
        segments = Parser(command).parse()
        return Guard(deadline, shutil.which("git", path=SAFE_PATH)).check(segments, cwd)
    except (Timeout, Unparsed):
        return None


def on_deadline(signum, frame) -> None:
    raise Timeout


def main() -> None:
    try:
        payload = json.loads(sys.stdin.buffer.read().decode("utf-8"))
    except Exception:
        return
    try:
        signal.signal(signal.SIGALRM, on_deadline)
        signal.alarm(DEADLINE_SECONDS)
        reason = evaluate(payload)
        signal.alarm(0)
        if reason:
            print(json.dumps({"hookSpecificOutput": {
                "hookEventName": "PreToolUse", "permissionDecision": "ask", "permissionDecisionReason": reason,
            }}))
    except Timeout:
        return
    except Exception:
        sys.stderr.write("bash_guard: error\n")


if __name__ == "__main__":
    try:
        main()
    finally:
        sys.exit(0)
