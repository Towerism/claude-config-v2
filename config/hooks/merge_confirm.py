"""PreToolUse(Bash) hook: every PR merge waits for the user's click.

The command is parsed as bash_guard.py parses it. A merge counts only at command position: at the
start of the command or after a separator (`&& || ; | &`, a newline, `(`, `$(` or a backtick), past
VAR=value words and the wrappers `env`, `command`, `builtin`, sudo, doas, nohup, coproc, exec,
time -p, timeout N, nice -n N, stdbuf, watch and xargs. It asks for:

- `gh [flags] pr [flags] merge`;
- `gh api` or `tea api` (tea is the Gitea CLI) with a `/merge` operand (the endpoint), not a flag
  value such as `-f body=...`; or with `mergePullRequest` or `enablePullRequestAutoMerge` in any of
  its words or its heredoc body.

The text that `bash|sh|zsh|dash|ksh -c`, `eval` and `env -S` run is parsed again, and so are a
heredoc fed to a shell (`bash <<E`, `cat <<E | bash`) and the echo or printf text before a bare
shell (`echo 'gh pr merge 5' | bash`; printf's `\\n` and `\\t` are decoded first). Quoted text,
heredoc bodies and comments of other commands do not ask: `echo "gh pr merge"`, `grep`,
`git commit -m` and `python3 -c` pass. A squash merge (`--squash`, a short flag group holding `s`
after `merge`, or a `gh api …/merge` sending merge_method=squash) gets its own reason, because the
global rule forbids squash. Otherwise the hook prints nothing.

It is a reminder, not a security boundary: aliases, scripts, `curl` and any runner it does not list
get past it. The control that holds is branch protection on the remote. Nesting past MAX_DEPTH,
re-parses included, is unparsed and passes. The parse is one left-to-right pass, so the time is
linear in the command length (#20). The hook always exits 0 and never denies; past the 5-second
deadline, or on any error, it prints nothing.
"""

import contextlib
import json
import os
import re
import signal
import sys

DEADLINE_SECONDS = 5

REASON = "Merging needs your confirmation (global rule: merge only with your authorization)"

SQUASH_REASON = "Squash merges are against the global rule (merge commit or rebase, never squash); merging also needs your authorization"
# `--squash`, or a short flag group holding `s`, in the arguments of gh pr merge.
SQUASH_FLAG = re.compile(r"--squash|-[A-Za-z]*s[A-Za-z]*")

API_MERGE = re.compile(r"/merge\b")
# GraphQL mutations that merge now or queue a merge (auto-merge).
MERGE_MUTATION = re.compile(r"\b(?:mergePullRequest|enablePullRequestAutoMerge)\b")
FIELD_FLAGS = ("-f", "-F", "--field", "--raw-field")
# gh api and tea api flags that take the next word as their value; that value is not the endpoint.
API_VALUE_FLAGS = {
    "-X", "--method", "-H", "--header", "-f", "-F", "--field", "--raw-field", "--input", "-q", "--jq",
    "-t", "--template", "-p", "--preview", "--hostname", "--cache", "-d", "--data", "--body", "-o",
    "--output", "-l", "--login", "-r", "--repo",
}

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

# Identical in secrets_guard.py; test_hook_wrapper_copies_are_the_same_in_both_hooks compares them.
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
    """The words from the command name on, past every prefix; ([], text) when env -S gives text to parse.
    When skipped is given, each prefix command skipped is appended to it with its options."""
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


# Escapes that shell_texts decodes in printf text before parsing it.
PRINTF_ESCAPE = re.compile(r"\\([nt\\])")
PRINTF_CHARACTERS = {"n": "\n", "t": "\t", "\\": "\\"}


def shell_texts(words: list[Word], seg: Segment, previous: list[Word], previous_heredocs: list[str]) -> list[str]:
    """What a bash, sh, zsh, dash or ksh command runs: its -c string. With no script, its heredocs,
    the heredocs of the command before it, and the text of the echo or printf before it. The parser
    keeps no separator, so `echo x; bash` counts too."""
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


def walk(text: str, depth: int, visit) -> bool:
    """Whether visit(words, seg) holds for a command in text, or in text that a shell, eval or env -S
    runs. Each re-parse adds one to depth, which MAX_DEPTH bounds."""
    parser = Parser(text)
    parser.commands(None, depth)
    previous: list[Word] = []
    previous_heredocs: list[str] = []
    for seg in parser.segments:
        words, script = resolve(seg.words)
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


# ── merges ───────────────────────────────────────────────────────────────────


def subcommand(words: list[Word], i: int, name: str) -> int | None:
    """The index after `name` when the words from i are flags, each with at most one value, then `name`."""
    after_flag = False
    while i < len(words):
        text = words[i].text
        i += 1
        if text == name:
            return i
        if len(text) > 1 and text.startswith("-"):  # a lone "-" is not a flag
            after_flag = True
        elif after_flag:
            after_flag = False
        else:
            return None
    return None


def pr_merge_args(words: list[Word]) -> list[Word] | None:
    """The words after `merge` of a `gh [flags] pr [flags] merge` command; None for any other command."""
    if os.path.basename(words[0].text) != "gh":
        return None
    i = subcommand(words, 1, "pr")
    i = None if i is None else subcommand(words, i, "merge")
    return None if i is None else words[i:]


def api_operands(words: list[Word]) -> list[str] | None:
    """The operands after `api` of a `gh api` or `tea api` call, its endpoint among them; flags and
    the values of API_VALUE_FLAGS are left out. None for any other command."""
    if os.path.basename(words[0].text) not in ("gh", "tea"):
        return None
    i = subcommand(words, 1, "api")
    if i is None:
        return None
    operands = []
    while i < len(words):
        text = words[i].text
        i += 1
        if text in API_VALUE_FLAGS:
            i += 1
        elif not (len(text) > 1 and text.startswith("-")):
            operands.append(text)
    return operands


def calls_merge_api(words: list[Word], seg: Segment) -> bool:
    """Whether a `gh api` or `tea api` call merges: a /merge path operand, or a merge mutation in its
    words or heredoc, or in the words or heredoc of a $(...) or backtick among its words."""
    operands = api_operands(words)
    if operands is None:
        return False
    if any(API_MERGE.search(t) for t in operands):
        return True
    bodies = [w.text for w in words] + seg.heredocs
    for word in words:
        for inner in word.subs:
            for sub in inner:
                bodies += sub.heredocs + [w.text for w in sub.words]
    return any(MERGE_MUTATION.search(body) for body in bodies)


def sends_squash_method(texts: list[str]) -> bool:
    """Whether a field flag (-f, -F, --field, --raw-field) sends merge_method=squash."""
    for i, text in enumerate(texts):
        name, eq, rest = text.partition("=")
        if name in ("--field", "--raw-field") and eq:
            value = rest
        elif text in FIELD_FLAGS and i + 1 < len(texts):
            value = texts[i + 1]
        else:
            continue
        if value == "merge_method=squash":
            return True
    return False


def merging_commands(command: str) -> list[list[Word]]:
    """The words of each command that merges a pull request; none for unparsed input."""
    found: list[list[Word]] = []

    def visit(words: list[Word], seg: Segment) -> bool:
        if pr_merge_args(words) is not None or calls_merge_api(words, seg):
            found.append(words)
        return False

    try:
        walk(command, 0, visit)
    except Unparsed:
        return []
    return found


def merges_a_pr(command: str | list[list[Word]]) -> bool:
    """Whether the command, or its merging commands from merging_commands, merges a pull request
    through `gh` or `tea`."""
    return bool(merging_commands(command) if isinstance(command, str) else command)


def squashes(command: str | list[list[Word]]) -> bool:
    """Whether a merging `gh pr merge` passes `--squash` or a short flag group holding `s` after `merge`,
    or a merging `gh api …/merge` sends the field merge_method=squash. Takes the command or its merging
    commands from merging_commands."""
    for words in merging_commands(command) if isinstance(command, str) else command:
        args = pr_merge_args(words)
        if args is not None and any(SQUASH_FLAG.fullmatch(w.text) for w in args):
            return True
        operands = api_operands(words) or []
        if any(API_MERGE.search(t) for t in operands) and sends_squash_method([w.text for w in words]):
            return True
    return False


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
        command = payload["tool_input"]["command"]
        parsed = True
    if not parsed:
        return
    if session_bypassed(payload):
        return
    # Past the deadline, or on any error, nothing is printed.
    with contextlib.suppress(Exception):  # hook contract: exit 0, fixed code
        signal.signal(signal.SIGALRM, on_deadline)
        signal.alarm(DEADLINE_SECONDS)
        found = merging_commands(command) if isinstance(command, str) and "\0" not in command else []
        if merges_a_pr(found):
            reason = SQUASH_REASON if squashes(found) else REASON
            signal.alarm(0)  # disarm first, so the alarm cannot fire during the print
            print(json.dumps({"hookSpecificOutput": {
                "hookEventName": "PreToolUse", "permissionDecision": "ask", "permissionDecisionReason": reason,
            }}))
        signal.alarm(0)


if __name__ == "__main__":
    try:
        main()
    finally:
        sys.exit(0)
