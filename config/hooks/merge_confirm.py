"""PreToolUse(Bash) hook: every PR merge waits for the user's click.

Prints a permissionDecision of "ask" for `gh … pr … merge`, `gh api …/merge`, `tea api …/merge`,
and for a GraphQL `mergePullRequest` or `enablePullRequestAutoMerge` sent with `gh api`. A squash
merge (`--squash` or `-s` among the words of the `gh pr merge` command itself, or a `gh api …/merge`
sending merge_method=squash) gets its own reason, because the global rule forbids squash. Prints
nothing otherwise.
Always exits 0 and never denies. It is a reminder that catches the usual spellings,
not a security boundary: quoting tricks, aliases and `curl` get past it. The control that
holds is branch protection on the remote.

The check runs on every Bash command, so it reads the command once, left to
right, in time proportional to its length. A regular expression with nested
repeats did the same job but backtracked exponentially on commands holding
many dash-prefixed words (#20).
"""

import json
import re
import sys

REASON = "Merging needs your confirmation (global rule: merge only with your authorization)"

SQUASH_REASON = "Squash merges are against the global rule (merge commit or rebase, never squash); merging also needs your authorization"
# gh pr merge's --squash, or a short flag group that holds s.
SQUASH_FLAG = re.compile(r"--squash|-[A-Za-z]*s[A-Za-z]*")

# A word that ends in `gh` as a command: `gh`, `"gh`, or `x&&gh`.
GH_END = re.compile(r"\bgh$")
MERGE_WORD = re.compile(r"merge\b")
GH_API = re.compile(r"\b(?:gh|tea)\s+api\b")  # tea is the Gitea CLI
API_MERGE = re.compile(r"/merge\b")
# GraphQL mutations that merge now or queue a merge (auto-merge).
MERGE_MUTATION = re.compile(r"\b(?:mergePullRequest|enablePullRequestAutoMerge)\b")
WORD = re.compile(r"\S+")
# Where a simple command ends, so a later command's flags are not read as the merge's.
COMMAND_END = re.compile(r"[;|\n]|&&")
FIELD_FLAGS = ("-f", "-F", "--field", "--raw-field")

# Where a scan of `gh [flags] pr [flags] merge` stands after a word: before or
# after the `pr`, and just past it (START), a flag or a flag's value. Flags are
# words starting with "-", each optionally followed by one value word.
BEFORE_PR, AFTER_PR = 0, 1
START, FLAG, VALUE = 0, 1, 2
State = tuple[int, int]


def _step(state: State, word: str) -> set[State]:
    """The states a scan can be in after `word`; empty when the scan fails."""
    phase, kind = state
    nxt: set[State] = set()
    if len(word) > 1 and word.startswith("-"):  # a lone "-" is not a flag
        nxt.add((phase, FLAG))
    elif kind == FLAG:
        nxt.add((phase, VALUE))
    if phase == BEFORE_PR and word == "pr":
        nxt.add((AFTER_PR, START))
    return nxt


def merges_a_pr(command: str) -> bool:
    """Whether the command merges a pull request through `gh`."""
    return _pr_merge_args(command) is not None or _calls_merge_api(command)


def squashes(command: str) -> bool:
    """Whether the `gh pr merge` in the command passes `--squash` or a short flag group holding `s`,
    or a `gh api …/merge` sends the field merge_method=squash."""
    args = _pr_merge_args(command)
    if args is not None and any(SQUASH_FLAG.fullmatch(word) for word in args):
        return True
    scanned_to = -1
    for m in GH_API.finditer(command):
        if m.end() <= scanned_to:
            continue  # inside a simple command already read from an earlier `gh api`
        text = _simple_command(command, m.end())
        scanned_to = m.end() + len(text)
        words = text.split()
        if any(API_MERGE.search(word) for word in words) and _sends_squash_method(words):
            return True
    return False


def _simple_command(command: str, start: int) -> str:
    """The text from `start` to the end of its simple command (before ; && || | or a newline)."""
    end = COMMAND_END.search(command, start)
    return command[start : end.start() if end else len(command)]


def _sends_squash_method(words: list[str]) -> bool:
    """Whether a field flag (-f, -F, --field, --raw-field) sends merge_method=squash."""
    for i, word in enumerate(words):
        name, eq, rest = word.partition("=")
        if name in ("--field", "--raw-field") and eq:
            value = rest
        elif word in FIELD_FLAGS and i + 1 < len(words):
            value = words[i + 1]
        else:
            continue
        if value.strip("'\"") == "merge_method=squash":
            return True
    return False


def _pr_merge_args(command: str) -> list[str] | None:
    """The words of the `gh [flags] pr [flags] merge` simple command after `merge`; None when there is none."""
    states: set[State] = set()
    for m in WORD.finditer(command):
        word = m.group()
        if MERGE_WORD.match(word) and any(phase == AFTER_PR for phase, _ in states):
            return _simple_command(command, m.start() + len("merge")).split()
        states = {s for state in states for s in _step(state, word)}
        if GH_END.search(word):
            states.add((BEFORE_PR, START))  # a new gh command starts a new scan
    return None


def _calls_merge_api(command: str) -> bool:
    """`gh api` followed by a /merge path on the same line, or by mergePullRequest anywhere."""
    first = GH_API.search(command)
    if first and MERGE_MUTATION.search(command, first.end()):
        return True  # a GraphQL body often spans lines, so the mutation may sit on any line after gh api
    scanned_to = -1
    for m in GH_API.finditer(command):
        if m.end() <= scanned_to:
            continue  # this line's rest was already searched from an earlier `gh api`
        line_end = command.find("\n", m.end())
        line_end = len(command) if line_end < 0 else line_end
        if API_MERGE.search(command, m.end(), line_end):
            return True
        scanned_to = line_end
    return False


def main() -> None:
    try:
        command = json.loads(sys.stdin.buffer.read().decode("utf-8"))["tool_input"]["command"]
    except Exception:
        return
    if isinstance(command, str) and merges_a_pr(command):
        print(
            json.dumps(
                {
                    "hookSpecificOutput": {
                        "hookEventName": "PreToolUse",
                        "permissionDecision": "ask",
                        "permissionDecisionReason": SQUASH_REASON if squashes(command) else REASON,
                    }
                }
            )
        )


if __name__ == "__main__":
    try:
        main()
    finally:
        sys.exit(0)
