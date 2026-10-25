"""Secrets guard: Read, Grep and Glob never touch secret files; Bash asks before a listed reader takes one.

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
alternatives or brace groups denies.

Bash parses the command as bash_guard.py does (a copy of its parser; a test keeps them equal) and
asks only when a secret path is an operand of a listed reader at command position. A secret path
names a secret file, with or without a directory or a `--flag=` prefix. An unquoted glob word that
opens with a literal character and matches one of `.env`, `.env.local`, `.env.production` or
`deny-terms` (`.en?`, `.e*`) counts too. The readers:

- viewers: cat, tac, bat, less, more, head, tail, nl, od, xxd, strings, base64;
- filters, with the secret as a file and not the pattern: grep, rg, sed, awk, cut, sort, diff, jq
  (the files of grep -f, sed -f, awk -f, jq -f, --rawfile and --slurpfile count);
- movers and copies: cp, mv, scp, rsync, ln, tee;
- archivers and dumpers: wc, hexdump, tar, zip, dd if=, wget --post-file; git diff, git log -p and
  git show with the secret as a path operand;
- source and `.`, an input redirection `<`, docker --env-file, and curl -d, --data,
  --data-binary @file, -F name=@file and -T file.

The value of `--exclude` (and of `-x` for diff and zip) names a file to leave out, so it is not an
operand: `tar --exclude=.env -czf a.tgz .` passes.

VAR=value words and the wrappers `env`, `command`, `builtin`, sudo, doas, nohup, coproc, exec,
time -p, timeout N, nice -n N, stdbuf, watch and xargs are skipped; the file of `xargs -a` or
`--arg-file` is read, so a secret there asks. The text that `bash|sh|zsh|dash|ksh -c`, `eval` and
`env -S` run, a heredoc fed to a shell (`bash <<E`, `cat <<E | bash`), and the echo or printf text
before a bare shell (printf's `\\n` and `\\t` decoded) are parsed again. Other commands (echo,
printf, git commit -m, python3 -c, git log --grep), comments and heredoc bodies stay silent. It is a reminder, not a security boundary: an unlisted reader gets past it, and so do an
output redirection, `python3 x.py .env`, `git show HEAD:.env` and `cat $(echo .env)`. Nesting past
MAX_DEPTH, re-parses included, is unparsed and passes.

Nothing named by the input is opened, only resolved. Each Bash parse is one left-to-right pass, so
the scan is linear in the command length. Nothing from the input is printed. Always exits 0; one
5-second deadline; every error is one fixed code on stderr.
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
ASK_REASON = "A listed reader in this command takes a secret file (.env or deny-terms). Confirm you want it read."


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
    with contextlib.suppress(Exception):  # hook contract: exit 0, fixed code
        return os.path.realpath(Path.home() / ".config" / "claude-config" / "deny-terms")
    return None


# bash_guard.py's shell parser, copied unchanged: test_hook_parser_copies_equal_bash_guards compares them.

# Nesting limit for $(...) and `...`; deeper input is unparsed and passes.
MAX_DEPTH = 32

EXPANSION = "\0"  # stands in a word for $VAR, $(...) or `...`; a command holding a real NUL is ignored
# A run of ordinary characters; quotes, $, backslashes and globs are handled one at a time.
PLAIN = re.compile(r"[^\s;&|()<>'\"\\$`*?\[]+")
ASSIGNMENT = re.compile(r"[A-Za-z_][A-Za-z0-9_]*=")
# Shell keywords that may precede a command name; command_words skips them.
RESERVED = {"if", "then", "else", "elif", "do", "while", "until", "!", "{", "time"}
# Variables that choose another repo; a command that sets one is not judged (ADR-0004, deviation 7).
REPO_VARIABLES = ("GIT_DIR=", "GIT_WORK_TREE=", "GIT_INDEX_FILE=")


# Input beyond what the parser models (nesting past MAX_DEPTH): the hook passes.
class Unparsed(Exception):
    pass


# ── the shell parser ─────────────────────────────────────────────────────────


class Word:
    __slots__ = ("glob", "subs", "text")

    def __init__(self) -> None:
        self.text = ""
        self.subs: list[list[Segment]] = []  # the commands of each $(...) or `...` in the word
        self.glob = False


class Segment:
    """One simple command: its words and the bodies of its heredocs."""

    __slots__ = ("heredocs", "words")

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
            if c == closer:  # the end of the $(...) or `...` this call parses
                self.i += 1
                return
            if c in " \t\r":
                self.i += 1
            elif c == "\n":  # a heredoc body starts after the newline that ends its command line
                self.i += 1
                self.read_heredocs()
                seg = self.new_segment()
            elif c == "\\" and s.startswith("\n", self.i + 1):
                self.i += 2
            elif c == "#":
                end = s.find("\n", self.i)
                self.i = self.n if end < 0 else end
            # &> redirects stdout and stderr; it does not separate commands.
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
            # The body is read at the next newline (read_heredocs).
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
            # A closer ends the $(...) or `...` that this call is parsing.
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
            # A backslash quotes the next character; backslash-newline joins two lines.
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
            else:  # * ? [ make the word a pattern; git add treats such a word as broad
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
        elif nxt == "{":  # ${...}: the value is unknown, so skip to the closing brace
            end = s.find("}", self.i)
            self.i = self.n if end < 0 else end + 1
        elif nxt == "'" and not quoted:  # $'...': escapes are not decoded, so the value is unknown
            self.i += 1
            while self.i < self.n and s[self.i] != "'":
                self.i += 2 if s[self.i] == "\\" else 1
            self.i = min(self.i + 1, self.n)
        elif nxt and nxt in "@*#?$!-0123456789":  # special parameters ($1, $@, ...): value unknown
            self.i += 1
        elif nxt and (nxt.isalpha() or nxt == "_"):
            while self.i < self.n and (s[self.i].isalnum() or s[self.i] == "_"):
                self.i += 1
        else:
            parts.append("$")
            return
        parts.append(EXPANSION)

    def substitution(self, closer: str, depth: int) -> list[Segment]:
        """Parse the commands inside a $(...) or `...`; return the segments it added."""
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
                return []  # GIT_DIR and friends pick the repo: not judged (ADR-0004, deviation 7)
            i += 1
        elif text in RESERVED:
            i += 1
        elif text == "env":
            i += 1
            while i < len(words) and words[i].text.startswith("-"):
                # env -C and -S change the directory or split the arguments: not judged.
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


# ── wrappers around the copied parser ────────────────────────────────────────

SHELLS = {"bash", "sh", "zsh", "dash", "ksh"}
# Prefix commands, each with its short and long options that take a value; the command follows them.
PREFIXES = {
    "sudo": (
        {"-u", "-g", "-h", "-p", "-C", "-D", "-r", "-t", "-U", "-T"},
        {"--user", "--group", "--host", "--prompt", "--close-from", "--chdir", "--role", "--type", "--other-user", "--command-timeout"},
    ),
    "doas": ({"-u", "-C"}, set()),
    "nohup": (set(), set()),
    "coproc": (set(), set()),
    "builtin": (set(), set()),
    "watch": ({"-n", "-q"}, {"--interval", "--equexit"}),
    "exec": ({"-a"}, set()),
    "timeout": ({"-s", "-k"}, {"--signal", "--kill-after"}),  # a duration word follows the options
    "nice": ({"-n"}, {"--adjustment"}),
    "stdbuf": ({"-i", "-o", "-e"}, {"--input", "--output", "--error"}),
    "xargs": (
        {"-a", "-d", "-E", "-I", "-L", "-n", "-P", "-s"},
        {"--arg-file", "--delimiter", "--max-args", "--max-procs", "--max-chars", "--process-slot-var"},
    ),
}


def skip_options(words: list[Word], i: int, short: set[str], long: set[str]) -> int:
    """The index of the first word from i that is neither an option nor an option's value."""
    while i < len(words):
        text = words[i].text
        if text == "--":
            return i + 1
        if text.startswith("--"):
            i += 2 if text in long else 1
        elif text.startswith("-") and len(text) > 1:
            letters = text[1:]
            # In a group such as -oL, a letter that takes a value takes the rest of the group.
            at = next((j for j, ch in enumerate(letters) if "-" + ch in short), None)
            i += 2 if at == len(letters) - 1 else 1
        else:
            return i
    return i


def unjudged_skipped(words: list[Word]) -> tuple[list[Word], str | None]:
    """The words without the prefixes command_words gives up on: GIT_DIR= and friends and env -C DIR
    are dropped, and env -S hands back its string, with the words after it, as text to parse again."""
    kept: list[Word] = []
    i = 0
    while i < len(words):
        text = words[i].text
        if ASSIGNMENT.match(text) or text in RESERVED or text == "command":
            if not text.startswith(REPO_VARIABLES):
                kept.append(words[i])
            i += 1
        elif text == "env":
            kept.append(words[i])
            i += 1
            while i < len(words) and words[i].text.startswith("-"):
                flag = words[i].text
                if flag in ("-C", "--chdir"):
                    i += 2
                elif flag.startswith("--chdir="):
                    i += 1
                elif flag in ("-S", "--split-string"):
                    return [], " ".join(w.text for w in words[i + 1:])
                elif flag.startswith("--split-string="):
                    return [], " ".join([flag.partition("=")[2], *(w.text for w in words[i + 1:])])
                elif flag.startswith("-S"):
                    return [], " ".join([flag[2:], *(w.text for w in words[i + 1:])])
                else:
                    kept.append(words[i])
                    i += 1
        else:
            break
    return kept + words[i:], None


def resolve(words: list[Word], skipped: list[list[Word]] | None = None) -> tuple[list[Word], str | None]:
    """The words from the command name on, past every prefix, or ([], text) when env -S gives text to parse.
    Each prefix command skipped, with its options, is added to skipped when it is given."""
    for _ in range(MAX_DEPTH):
        words, text = unjudged_skipped(words)
        if text is not None:
            return [], text
        seg = Segment()
        seg.words = words
        found = command_words(seg)
        if not found:
            return [], None
        start = len(words) - len(found)
        name = os.path.basename(found[0].text)
        if found[0].text == "-p" and start and words[start - 1].text == "time":
            words = found[1:]
        elif name in PREFIXES:
            i = skip_options(found, 1, *PREFIXES[name])
            if skipped is not None:
                skipped.append(found[:i])
            words = found[i + (name == "timeout"):]
        else:
            return found, None
    raise Unparsed


# The printf escapes decoded before its text is parsed again.
PRINTF_ESCAPE = re.compile(r"\\([nt\\])")
PRINTF_CHARACTERS = {"n": "\n", "t": "\t", "\\": "\\"}


def shell_texts(words: list[Word], seg: Segment, previous: list[Word], previous_heredocs: list[str]) -> list[str]:
    """What a bash, sh or zsh command runs: its -c string; with no script, its heredocs, the heredocs
    of the command before it, and the text of the echo or printf before it (the parser keeps no
    separator, so `echo x; bash` counts too)."""
    with_c = False
    i = 1
    while i < len(words):
        text = words[i].text
        i += 1
        if text in ("-o", "+o", "-O", "+O"):
            i += 1
        elif text.startswith("-") and not text.startswith("--") and len(text) > 1:
            with_c = with_c or "c" in text
        elif not text.startswith("--"):
            return [text] if with_c else []  # the -c string, or a script file
    if with_c:
        return []
    texts = seg.heredocs + previous_heredocs
    if previous and os.path.basename(previous[0].text) in ("echo", "printf"):
        args = previous[1:]
        while args and re.fullmatch(r"-[neE]+", args[0].text):
            args = args[1:]
        text = " ".join(w.text for w in args)
        if os.path.basename(previous[0].text) == "printf":
            text = PRINTF_ESCAPE.sub(lambda m: PRINTF_CHARACTERS[m.group(1)], text)
        texts.append(text)
    return texts


# ── Bash: a listed reader taking a secret file ───────────────────────────────


class InputParser(Parser):
    """The copied Parser, also keeping the target word of each `<` input redirection."""

    def __init__(self, text: str) -> None:
        super().__init__(text)
        self.inputs: list[Word] = []

    def redirection(self, seg: Segment, closer: str | None, depth: int) -> None:
        s = self.s
        if not s.startswith("<", self.i) or s.startswith("<<", self.i):
            super().redirection(seg, closer, depth)
            return
        # The same steps as Parser.redirection, keeping the target it drops.
        while self.i < self.n and s[self.i] in "<>&|":
            self.i += 1
        self.skip_blanks()
        if self.i < self.n and s[self.i] not in "\n;&|()" and s[self.i] != closer:
            self.inputs.append(self.word(closer, depth))


def walk(text: str, depth: int, visit) -> bool:
    """Whether a `<` input names a secret, or visit(words, seg) holds for a command, in text or in text
    that a shell, eval or env -S runs. Each re-parse adds one to depth, which MAX_DEPTH bounds."""
    parser = InputParser(text)
    parser.commands(None, depth)
    if any(secret_path(w.text, w.glob) for w in parser.inputs):
        return True
    previous: list[Word] = []
    previous_heredocs: list[str] = []
    for seg in parser.segments:
        skipped: list[list[Word]] = []
        words, script = resolve(seg.words, skipped)
        # xargs -a reads its arguments from a file.
        if any(os.path.basename(p[0].text) == "xargs" and flag_reads(p[1:], "-a", "--arg-file") for p in skipped):
            return True
        if script is not None:
            texts = [script]
        elif not words:
            continue
        else:
            name = os.path.basename(words[0].text)
            if name in SHELLS:
                texts = shell_texts(words, seg, previous, previous_heredocs)
            elif name == "eval":
                texts = [" ".join(w.text for w in words[1:])]
            elif visit(words, seg):
                return True
            else:
                texts = []
            previous, previous_heredocs = words, seg.heredocs
        if any(walk(t, depth + 1, visit) for t in texts):
            return True
    return False


# Readers whose every operand, and every --flag=value, is a file.
FILE_READERS = {
    "cat", "tac", "bat", "less", "more", "head", "tail", "nl", "od", "xxd", "strings", "base64",
    "cut", "sort", "diff", "cp", "mv", "scp", "rsync", "ln", "tee", "wc", "hexdump", "tar", "zip",
    "source", ".",
}
# Flags whose value names files to leave out, not a file to read; --exclude for any other reader.
# rsync -x and tar -x mean something else, so only diff and zip get -x.
EXCLUDES = {"diff": {"-x", "--exclude"}, "zip": {"-x", "--exclude"}}
GREP_FLAGS = (
    {"-e", "--regexp"},
    {"-f", "--file"},
    {
        "-m", "--max-count", "-A", "--after-context", "-B", "--before-context", "-C", "--context",
        "-d", "--directories", "-D", "--devices", "--include", "--exclude", "--exclude-dir",
        "--exclude-from", "--label", "--binary-files", "--group-separator",
    },
)
# Readers whose first operand is a pattern, script or filter. Each entry is (flags whose value is
# the pattern, flags whose value is a file, other flags that take a value).
PATTERN_READERS = {
    "grep": GREP_FLAGS,
    "egrep": GREP_FLAGS,
    "fgrep": GREP_FLAGS,
    "rg": (
        {"-e", "--regexp"},
        {"-f", "--file"},
        {
            "-g", "--glob", "--iglob", "-t", "--type", "-T", "--type-not", "-m", "--max-count",
            "-A", "--after-context", "-B", "--before-context", "-C", "--context", "-j", "--threads",
            "-M", "--max-columns", "-r", "--replace", "-E", "--encoding", "-d", "--max-depth",
            "--type-add", "--sort", "--sortr", "--pre", "--max-filesize", "--path-separator",
            "--colors", "--ignore-file",
        },
    ),
    "sed": ({"-e", "--expression"}, {"-f", "--file"}, {"-l", "--line-length"}),
    "awk": (set(), {"-f", "--file"}, {"-F", "--field-separator", "-v", "--assign"}),
    "jq": (set(), {"-f", "--from-file"}, {"-L", "--indent"}),
}
# git log, diff and show flags that take a value, so the value is not read as a path.
GIT_VALUES = {
    "-n", "--max-count", "--skip", "-S", "-G", "--grep", "--author", "--committer", "--since",
    "--until", "-L", "-O", "--format", "--pretty",
}
CURL_DATA = {"-d", "--data", "--data-binary", "--data-ascii", "--data-urlencode", "--json"}
CURL_FORM = {"-F", "--form"}
CURL_UPLOAD = {"-T", "--upload-file"}
# Other curl flags that take a value; -XPOST reads as -X with the value POST.
CURL_VALUES = {"-X", "-H", "-o", "-u", "-A", "-e", "-b", "-c", "-K", "-m", "-w", "-x", "-E", "-r", "-C", "-Y", "-y", "-z"}


def secret_path(text: str, glob: bool) -> bool:
    """Whether a path names a secret file; a glob word also when it matches one (`.en?`, `.e*`)."""
    base = os.path.basename(text)
    if names_secret(base):
        return True
    return glob and (glob_matches_secret(base) or base.startswith((".env", "deny-terms")))


def options(args: list[Word], takes_value: set[str]) -> tuple[list[tuple[str, str, bool]], list[Word]]:
    """(flag, value, value is a glob) for each flag, and the operands. A short flag in takes_value
    takes the rest of its group or the next word; a long one its =value, or the next word when listed.
    An unlisted flag takes no value, so its value word is read as an operand."""
    flags: list[tuple[str, str, bool]] = []
    operands: list[Word] = []
    i = 0
    while i < len(args):
        word = args[i]
        text = word.text
        i += 1
        if text == "--":
            operands += args[i:]
            break
        if text.startswith("--"):
            name, eq, rest = text.partition("=")
            if eq:
                flags.append((name, rest, word.glob))
            elif name in takes_value and i < len(args):
                flags.append((name, args[i].text, args[i].glob))
                i += 1
            else:
                flags.append((name, "", False))
        elif text.startswith("-") and len(text) > 1:
            for j in range(1, len(text)):
                flag = "-" + text[j]
                if flag in takes_value:
                    if j + 1 < len(text):
                        flags.append((flag, text[j + 1:], word.glob))
                    elif i < len(args):
                        flags.append((flag, args[i].text, args[i].glob))
                        i += 1
                    break
                flags.append((flag, "", False))
        else:
            operands.append(word)
    return flags, operands


def pattern_reads(args: list[Word], pattern_flags: set[str], file_flags: set[str], values: set[str]) -> bool:
    flags, operands = options(args, pattern_flags | file_flags | values)
    if any(flag in file_flags and secret_path(value, glob) for flag, value, glob in flags):
        return True
    if not any(flag in pattern_flags | file_flags for flag, _, _ in flags):
        operands = operands[1:]  # the pattern, script or filter
    return any(secret_path(w.text, w.glob) for w in operands)


def jq_reads(args: list[Word]) -> bool:
    kept: list[Word] = []
    i = 0
    while i < len(args):
        text = args[i].text
        if text in ("--rawfile", "--slurpfile"):  # NAME FILE
            if i + 2 < len(args) and secret_path(args[i + 2].text, args[i + 2].glob):
                return True
            i += 3
        elif text in ("--arg", "--argjson"):  # NAME VALUE
            i += 3
        elif text in ("--args", "--jsonargs"):  # the rest are arguments, not files
            break
        else:
            kept.append(args[i])
            i += 1
    return pattern_reads(kept, *PATTERN_READERS["jq"])


def git_reads(args: list[Word]) -> bool:
    """git diff, git log -p or git show with a secret path operand."""
    i = 0
    while i < len(args) and args[i].text.startswith("-"):
        i += 2 if args[i].text in ("-C", "-c", "--git-dir", "--work-tree", "--namespace", "--config-env") else 1
    if i >= len(args) or args[i].text not in ("diff", "log", "show"):
        return False
    flags, operands = options(args[i + 1:], GIT_VALUES)
    if args[i].text == "log" and not any(flag in ("-p", "-u", "--patch") for flag, _, _ in flags):
        return False
    return any(secret_path(w.text, w.glob) for w in operands)


def curl_reads(args: list[Word]) -> bool:
    flags, _ = options(args, CURL_DATA | CURL_FORM | CURL_UPLOAD | CURL_VALUES)
    for flag, value, glob in flags:
        if flag in CURL_DATA and "@" in value:
            path = value.partition("@")[2]
        elif flag in CURL_FORM and ("=@" in value or "=<" in value):
            path = value.partition("=")[2][1:].split(";")[0]
        elif flag in CURL_UPLOAD:
            path = value
        else:
            continue
        if secret_path(path, glob):
            return True
    return False


def flag_reads(args: list[Word], *names: str) -> bool:
    """Whether the value of one of the flags `names` (docker --env-file, wget --post-file, xargs -a)
    is a secret path."""
    flags, _ = options(args, set(names))
    return any(name in names and secret_path(value, glob) for name, value, glob in flags)


def reads_secret(words: list[Word], seg: Segment) -> bool:
    """Whether a command is a listed reader that takes a secret path (see the module docstring)."""
    name = os.path.basename(words[0].text)
    args = words[1:]
    if name in FILE_READERS:
        excludes = EXCLUDES.get(name, {"--exclude"})
        flags, operands = options(args, excludes)
        return any(flag not in excludes and secret_path(value, glob) for flag, value, glob in flags) or any(
            secret_path(w.text, w.glob) for w in operands
        )
    if name == "jq":
        return jq_reads(args)
    if name in PATTERN_READERS:
        return pattern_reads(args, *PATTERN_READERS[name])
    if name == "git":
        return git_reads(args)
    if name == "curl":
        return curl_reads(args)
    if name in ("docker", "docker-compose"):
        return flag_reads(args, "--env-file")
    if name == "wget":
        return flag_reads(args, "--post-file")
    if name == "dd":
        return any(w.text.startswith("if=") and secret_path(w.text[3:], w.glob) for w in args)
    return False


def command_names_secret(command: str) -> bool:
    """Whether a listed reader in the Bash command takes a secret file. Unparsed input passes."""
    try:
        return walk(command, 0, reads_secret)
    except Unparsed:
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
    parsed = False
    with contextlib.suppress(Exception):  # hook contract: exit 0, fixed code
        payload = json.loads(sys.stdin.buffer.read().decode("utf-8"))
        if session_bypassed(payload):
            return
        name = payload["tool_name"]
        fields = payload["tool_input"]
        if not isinstance(name, str) or not isinstance(fields, dict):
            return
        parsed = True
    if not parsed:
        return
    failed = True
    with contextlib.suppress(Exception):  # hook contract: exit 0, fixed code
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
        failed = False
    if failed:
        sys.stderr.write("secrets_guard: error\n")  # the only output on error: a fixed code


if __name__ == "__main__":
    try:
        main()
    finally:
        sys.exit(0)
