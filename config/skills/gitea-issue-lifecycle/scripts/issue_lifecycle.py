#!/usr/bin/env python3
"""Deterministic helpers for the GitHub and Gitea issue lifecycle skills (stdlib, no network).

Each skill ships an identical copy, so neither depends on the other being deployed.

Subcommands:
  extract        print the spec block from an issue body file
  replace        write a new issue body with the spec block swapped (or appended)
  branch-name    print `{type}/{N}-{slug}` for an issue
  commit-check   validate a commit message (Conventional Commit ending in (#N))
  pr-body-check  validate a PR body (Closes line, Spec line, Review section)
  diff-check     scan `git diff <base>...HEAD` for spec IDs in code and committed spec files
  declaration-check  validate the path declaration against the issue's comments

Exit codes: 0 ok, 1 check failed, 2 usage error, 3 no spec markers, 4 malformed markers.
Issue and PR text is only ever read from files and treated as data.
"""

import argparse
import json
import os
import re
import subprocess
import sys
import tempfile
import unicodedata

START = "<!-- spec:start -->"
END = "<!-- spec:end -->"

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
BRANCH_TYPES = {
    "feat": "feature",
    "feature": "feature",
    "fix": "fix",
    "docs": "docs",
    "hotfix": "hotfix",
}
SLUG_MAX = 40

EXIT_OK, EXIT_FAIL, EXIT_USAGE, EXIT_NO_MARKERS, EXIT_MALFORMED = 0, 1, 2, 3, 4


class UsageError(Exception):
    pass


class MarkerError(Exception):
    def __init__(self, code, message):
        super().__init__(message)
        self.code = code


# ── file helpers ─────────────────────────────────────────────────────────────


def read_text(path):
    """Read a file (or stdin for "-") preserving every byte, including CRLF."""
    if path == "-":
        return sys.stdin.buffer.read().decode("utf-8", "surrogateescape")
    try:
        with open(path, "rb") as fh:
            return fh.read().decode("utf-8", "surrogateescape")
    except OSError as exc:
        raise UsageError(f"cannot read {path}: {exc.strerror}") from exc


def write_text(path, text):
    with open(path, "wb") as fh:
        fh.write(text.encode("utf-8", "surrogateescape"))


# ── spec block ───────────────────────────────────────────────────────────────


def _line_content(line):
    return line.rstrip("\r\n")


def locate_block(body):
    """Return (start_index, end_index) into body.splitlines(keepends=True).

    Only whole lines count as markers; a marker mentioned mid-line is text.
    """
    lines = body.splitlines(keepends=True)
    start = next((i for i, line in enumerate(lines) if _line_content(line) == START), None)
    if start is None:
        if any(_line_content(line) == END for line in lines):
            raise MarkerError(EXIT_MALFORMED, "end marker without a start marker")
        raise MarkerError(EXIT_NO_MARKERS, "no spec markers")
    end = next((i for i in range(start + 1, len(lines)) if _line_content(lines[i]) == END), None)
    if end is None:
        raise MarkerError(EXIT_MALFORMED, "start marker without an end marker")
    return lines, start, end


def extract_spec(body):
    lines, start, end = locate_block(body)
    inner = [_line_content(line) for line in lines[start + 1 : end]]
    return "".join(f"{line}\n" for line in inner)


def _clean_spec(spec):
    """Normalise to LF, drop one trailing newline and any marker lines wrapping the spec."""
    text = spec.replace("\r\n", "\n")
    text = text.removesuffix("\n")
    lines = text.split("\n")
    if lines and lines[0] == START:
        lines = lines[1:]
    if lines and lines[-1] == END:
        lines = lines[:-1]
    return "\n".join(lines)


def replace_spec(body, spec):
    nl = "\r\n" if "\r\n" in body else "\n"
    inner = _clean_spec(spec)
    block = START + nl + (inner.replace("\n", nl) + nl if inner else "") + END
    try:
        lines, start, end = locate_block(body)
    except MarkerError as exc:
        if exc.code != EXIT_NO_MARKERS:
            raise
        if body == "":
            sep = ""
        elif body.endswith(nl):
            sep = nl
        else:
            sep = nl + nl
        return body + sep + block + nl
    prefix = "".join(lines[:start])
    end_line = lines[end]
    terminator = end_line[len(_line_content(end_line)) :]
    rest = terminator + "".join(lines[end + 1 :])
    return prefix + block + rest


# ── branch names ─────────────────────────────────────────────────────────────


def slugify(title, issue):
    ascii_title = unicodedata.normalize("NFKD", title).encode("ascii", "ignore").decode()
    slug = re.sub(r"[^a-z0-9]+", "-", ascii_title.lower()).strip("-")
    if len(slug) > SLUG_MAX:
        cut = slug[: SLUG_MAX + 1]
        slug = (
            cut[:SLUG_MAX]
            if cut.endswith("-")
            else (cut.rsplit("-", 1)[0] if "-" in cut else cut[:SLUG_MAX])
        )
        slug = slug.strip("-")
    return slug or f"issue-{issue}"


def branch_name(cc_type, issue, title, hotfix=False):
    if cc_type not in CC_TYPES and cc_type not in BRANCH_TYPES:
        raise UsageError(f"unknown type {cc_type!r}")
    prefix = "hotfix" if hotfix else BRANCH_TYPES.get(cc_type, "chore")
    return f"{prefix}/{issue}-{slugify(title, issue)}"


# ── commit and PR checks ─────────────────────────────────────────────────────

SUBJECT_RE = re.compile(rf"^(?:{'|'.join(CC_TYPES)})(?:\([^()\s]+\))?(!)?: \S.*$")
ISSUE_REF_RE = re.compile(r"\((?:[\w.-]+/[\w.-]+)?#\d+\)$")
BREAKING_FOOTER_RE = re.compile(r"^BREAKING[ -]CHANGE: \S", re.MULTILINE)


def check_commit(message):
    message = message.replace("\r\n", "\n")
    subject, _, rest = message.partition("\n")
    problems = []
    match = SUBJECT_RE.match(subject)
    if not match:
        problems.append(
            ("not-conventional", f"not conventional: {subject!r} is not 'type(scope)!: subject'")
        )
    if not ISSUE_REF_RE.search(subject):
        problems.append(("missing-issue-ref", "missing (#N) at the end of the subject"))
    if match and match.group(1) and not BREAKING_FOOTER_RE.search(rest):
        problems.append(
            ("breaking-needs-footer", "breaking change needs footer 'BREAKING CHANGE: ...'")
        )
    return problems


def check_pr_body(body, issue, repo=None):
    lines = [line.strip() for line in body.replace("\r\n", "\n").split("\n")]
    target = f"{repo}#{issue}" if repo else f"#{issue}"
    problems = []
    if not any(re.fullmatch(r"closes " + re.escape(target), line, re.IGNORECASE) for line in lines):
        problems.append(("missing-closes", f"needs 'Closes {target}' alone on its own line"))
    spec_targets = "|".join(re.escape(t) for t in {target, f"#{issue}"})
    spec_line = re.compile(rf"spec: (?:{spec_targets})", re.IGNORECASE)
    if not any(spec_line.fullmatch(line) for line in lines):
        problems.append(("missing-spec-line", f"needs a 'Spec: {target}' line"))
    if not any(line.startswith("#") and "review" in line.lower() for line in lines):
        problems.append(("missing-review", "needs a Review section with the PR-diff review note"))
    return problems


# ── diff hygiene ─────────────────────────────────────────────────────────────

SPEC_ID_RE = re.compile(
    r"(?<![A-Za-z0-9])(?:(?:fr|nfr|ac|ec|os)-\d+(?![0-9])|(?:fr|nfr|ac|ec)\d+(?=_))", re.IGNORECASE
)
# In documentation an ID counts in any spelling (FR-23, FR23, fr_23), but only as a
# word of its own: the prefix may not follow a letter or digit.
DOC_ID_RE = re.compile(r"(?<![A-Za-z0-9])(nfr|fr|ac|ec|os)[-_]?(\d+)", re.IGNORECASE)
DOC_ID_GREP = "(nfr|fr|ac|ec|os)[-_]?[0-9]+"
SPEC_BASENAME_RE = re.compile(r"(^spec(-.+)?\.md$|-spec\.md$|\.spec\.md$)", re.IGNORECASE)
MARKDOWN = (".md", ".markdown")
FROZEN_SEGMENTS = {"history", "archive"}


def normal_id(text):
    """The comparable form of an ID: lowercase prefix, hyphen, number without leading zeros."""
    match = re.match(r"([a-z]+)[-_]?(\d+)", text, re.IGNORECASE)
    return f"{match.group(1).lower()}-{int(match.group(2))}"


def is_spec_name(path):
    if not path.lower().endswith(".md"):
        return False
    parts = path.split("/")
    return "specs" in parts[:-1] or bool(SPEC_BASENAME_RE.search(parts[-1]))


def has_subject(listing):
    """True when a directory listing (`git ls-tree` lines) holds a SKILL.md or any
    file that isn't Markdown, which makes a spec beside them a living spec."""
    for entry in listing.splitlines():
        meta, _, name = entry.partition("\t")
        if meta.split()[1:2] != ["blob"]:
            continue
        if name.rsplit("/", 1)[-1] == "SKILL.md" or not name.lower().endswith(MARKDOWN):
            return True
    return False


def cmd_diff_check(base, repo_dir):
    def git(*args, ok=(0,)):
        result = subprocess.run(["git", "-C", repo_dir, *args], capture_output=True, text=True, check=False)
        if result.returncode not in ok:
            raise UsageError(f"git {' '.join(args)} failed: {result.stderr.strip()}")
        return result.stdout

    def living_ids():
        # git grep exits 1 when nothing matches; that just means no IDs are defined.
        out = git("grep", "-I", "-i", "-z", "-E", DOC_ID_GREP, "HEAD", "--", "*.md", ok=(0, 1))
        ids = set()
        # Split on newlines only: str.splitlines() would also break inside a line at
        # separators such as U+2028, and lose the file name for the rest of it.
        for hit in out.split("\n"):
            name, _, text = hit.partition("\0")
            path = name.split(":", 1)[-1]
            if FROZEN_SEGMENTS & set(path.split("/")[:-1]):
                continue
            ids.update(normal_id(m.group(0)) for m in DOC_ID_RE.finditer(text))
        return ids

    diff = git("diff", "--no-color", "--no-ext-diff", "-U0", f"{base}...HEAD")
    added = git("diff", "--name-only", "--diff-filter=A", f"{base}...HEAD").splitlines()
    defined = None
    problems = []
    current, line_no = None, 0
    for line in diff.splitlines():
        if line.startswith("+++ "):
            current = line[6:] if line.startswith("+++ b/") else None
        elif line.startswith("@@"):
            hunk = re.search(r"\+(\d+)", line)
            line_no = int(hunk.group(1)) if hunk else 0
        elif line.startswith("+") and current:
            if not current.lower().endswith(".md"):
                for match in SPEC_ID_RE.finditer(line[1:]):
                    defined = living_ids() if defined is None else defined
                    if normal_id(match.group(0)) not in defined:
                        problems.append(("spec-id", f"{current}:{line_no}: {match.group(0)}"))
            line_no += 1
    for path in added:
        if not is_spec_name(path):
            continue
        folder = path.rsplit("/", 1)[0] + "/" if "/" in path else "."
        if not has_subject(git("ls-tree", "HEAD", "--", folder)):
            problems.append(("spec-file", f"{path} is a spec file away from its subject"))
    return problems


# ── path declaration ─────────────────────────────────────────────────────────

DECL_START = "<!-- path-declaration v1 -->"
DECL_END = "<!-- /path-declaration -->"
ADVISORY_STEPS = (
    "interview",
    "analyst",
    "docs-lookup",
    "test-plan",
    "history-cleanup",
    "simplifier",
    "qa",
    "design",
)
# Advisory steps that hinge on a fact, so `n/a` with that fact stands; the rest need a waiver.
CONDITIONAL_STEPS = ("history-cleanup", "simplifier", "qa", "design", "docs-lookup")
REQUIRED_STEPS = (
    "self-review",
    "spec-review",
    "review-notes",
    "tdd",
    "diff-review",
    "security-gate",
    "verify",
)
# Steps a variant requires on top of REQUIRED_STEPS.
VARIANT_STEPS = {"feature": (), "bug": ("repro",), "docs": (), "ui": (), "hotfix": ()}
DOCS_NA_STEPS = ("test-plan", "tdd")
DOCS_FACT = "variant: docs"
NO_REVIEW_FACT = "approval: no-review"
NO_REVIEW_MODE = "no-review"
STAMP_NAME = "path-declaration-ok"
# The first line of every comment a waiver cites; the user's words follow it.
ANSWER_HEAD = "Path declaration answer"
DECL_LINE_RE = re.compile(r"- (run|waived|n/a): ([^\s—]+)(?:\s+—\s*(.*))?")
OPEN_QUOTES, CLOSE_QUOTES = '"“', '"”'
FENCE_RE = re.compile(r"(```|~~~)")
SEAMS_RE = re.compile(r"#{1,6}\s+seams\b", re.IGNORECASE)


def declaration_lines(text):
    """The lines inside the one declaration block, or None when there is no block."""
    lines = [line.strip() for line in text.splitlines()]
    starts = [i for i, line in enumerate(lines) if line == DECL_START]
    ends = [i for i, line in enumerate(lines) if line == DECL_END]
    if not starts and not ends:
        return None
    if len(starts) > 1 or len(ends) > 1:
        raise MarkerError(EXIT_MALFORMED, "more than one path-declaration block")
    if not ends:
        raise MarkerError(EXIT_MALFORMED, "path-declaration block is not closed")
    if not starts or ends[0] < starts[0]:
        raise MarkerError(EXIT_MALFORMED, "closing marker without an opening marker")
    return lines[starts[0] + 1 : ends[0]]


def has_seams_heading(spec):
    in_fence = False
    for line in spec.splitlines():
        line = line.strip()
        if FENCE_RE.match(line):
            in_fence = not in_fence
        elif not in_fence and SEAMS_RE.match(line):
            return True
    return False


def squash(text):
    return " ".join(text.split())


def check_waiver(step, rest, bodies):
    quote, sep, url = rest.rpartition("—")
    if not sep:
        quote, url = rest, ""
    quote, url = quote.strip(), url.strip()
    if (
        len(quote) < 2
        or quote[0] not in OPEN_QUOTES
        or quote[-1] not in CLOSE_QUOTES
        or not quote[1:-1].strip()
    ):
        return [("waiver-needs-quote", f"{step}: the waiver needs the user's words in quotes")]
    if url not in bodies:
        detail = f"{step}: {url or 'no URL'} is not your comment on the issue"
        return [("waiver-not-recorded", detail)]
    head, _, answer = bodies[url].partition("\n")
    if not head.startswith(ANSWER_HEAD):
        detail = f"{step}: the comment at {url} does not start with {ANSWER_HEAD!r}"
        return [("waiver-not-recorded", detail)]
    words = squash(quote[1:-1])
    if len(words) < 2 or words not in squash(answer):
        return [("waiver-not-recorded", f"{step}: the quote is not in the answer at {url}")]
    return []


def na_allowed(step, fact, variant, approval_mode):
    if variant == "docs" and step in DOCS_NA_STEPS and fact == DOCS_FACT:
        return True
    if step == "spec-review":
        return fact == NO_REVIEW_FACT and approval_mode == NO_REVIEW_MODE
    if step in DOCS_NA_STEPS:
        return False
    return step == "security-gate" or step in CONDITIONAL_STEPS


def check_declaration(text, comments, approval_mode, spec, author):
    block = declaration_lines(text)
    if block is None:
        return [("missing-declaration", "no path-declaration block")]
    # Only comments by `author` count as evidence; a comment without a usable URL is dropped.
    bodies = {
        c["url"]: c.get("body") or ""
        for c in comments
        if isinstance(c.get("url"), str) and c["url"] and c.get("author") == author
    }
    problems, variants, entries = [], [], {}
    for line in block:
        if not line:
            continue
        if line.startswith("variant:"):
            variants.append(line.split(":", 1)[1].strip())
            continue
        match = DECL_LINE_RE.fullmatch(line)
        if not match:
            problems.append(("unknown-step", f"cannot read the line {line!r}"))
            continue
        kind, step, rest = match.groups("")
        if step in entries:
            problems.append(("unknown-step", f"{step} is declared more than once"))
            continue
        entries[step] = (kind, rest.strip())

    variant = variants[0] if len(variants) == 1 else None
    if variant not in VARIANT_STEPS:
        names = ", ".join(VARIANT_STEPS)
        problems.append(("unknown-step", f"needs one variant line naming one of {names}"))
    required = REQUIRED_STEPS + VARIANT_STEPS.get(variant, ())
    for step, (kind, rest) in entries.items():
        if step not in required and step not in ADVISORY_STEPS:
            problems.append(("unknown-step", f"{step} is not a step of the {variant} variant"))
        elif kind == "run":
            if rest not in bodies:
                detail = f"{step}: cite your issue comment that records it"
                problems.append(("run-needs-evidence", detail))
        elif kind == "waived":
            if step in required:
                problems.append(("required-waived", f"{step} is required and cannot be waived"))
            else:
                problems.extend(check_waiver(step, rest, bodies))
        elif not rest:
            problems.append(("na-needs-fact", f"{step}: n/a needs the fact that makes it so"))
        elif not na_allowed(step, rest, variant, approval_mode):
            code = "required-not-run" if step in required else "waiver-not-recorded"
            problems.append((code, f"{step}: n/a with {rest!r} does not stand in for a run"))
    for step in required:
        if step not in entries:
            problems.append(("required-not-run", f"{step} is required and not declared"))
    for step in ADVISORY_STEPS:
        if step not in entries:
            problems.append(("waiver-not-recorded", f"{step} is skipped without a recorded answer"))
    if entries.get("test-plan", ("",))[0] == "waived" and not has_seams_heading(spec):
        problems.append(("seams-needed", "test-plan is waived, so the spec needs a Seams heading"))
    return problems


def write_stamp(issue, passed):
    """Write the per-worktree stamp that lets the PR command through, or remove it on failure."""

    def git(*args):
        result = subprocess.run(["git", *args], capture_output=True, text=True, check=False)
        if result.returncode:
            raise UsageError(f"git {' '.join(args)} failed: {result.stderr.strip()}")
        return result.stdout.strip()

    git_dir = git("rev-parse", "--git-dir")
    path = os.path.join(git_dir, STAMP_NAME)
    if passed:
        text = f"{git('branch', '--show-current')}\n{issue}\n{git('rev-parse', 'HEAD')}\n"
        # A new file renamed over the stamp: a symlink at its path is replaced, not followed.
        fd, tmp = tempfile.mkstemp(dir=git_dir)
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(text)
        os.replace(tmp, path)
    elif os.path.lexists(path):
        os.remove(path)


def cmd_declaration_check(args):
    """Run the check; any outcome but a pass revokes an earlier stamp."""
    code = EXIT_USAGE
    try:
        code = declaration_check(args)
        return code
    finally:
        if args.stamp and code != EXIT_OK:
            try:
                write_stamp(args.issue, False)
            except UsageError:
                pass  # no git dir to find, so no stamp to remove


def declaration_check(args):
    if args.stamp and args.issue is None:
        raise UsageError("--stamp needs --issue")
    try:
        comments = json.loads(read_text(args.comments))
    except ValueError as exc:
        raise UsageError(f"{args.comments} is not JSON: {exc}") from exc
    if not isinstance(comments, list) or not all(isinstance(c, dict) for c in comments):
        raise UsageError(f"{args.comments} must hold a list of {{url, body, author}} objects")
    spec = read_text(args.spec)
    text = ""
    if args.declaration and os.path.exists(args.declaration):
        text = read_text(args.declaration)
    mode = args.approval_mode.strip()
    problems = check_declaration(text, comments, mode, spec, args.author.strip())
    if args.stamp:
        write_stamp(args.issue, not problems)
    return report(problems, args.json)


# ── CLI ──────────────────────────────────────────────────────────────────────

EPILOG = """Examples:
  issue_lifecycle.py extract --body body.md > spec.md
  issue_lifecycle.py replace --body body.md --spec spec.md --out new-body.md
  issue_lifecycle.py branch-name --type feat --issue 42 --title "Add CSV export"
  issue_lifecycle.py commit-check --message msg.txt --json
  issue_lifecycle.py pr-body-check --body pr.md --issue 42
  issue_lifecycle.py diff-check --base origin/main
  issue_lifecycle.py declaration-check --declaration decl.md --comments comments.json \\
      --author octocat --approval-mode manual --spec spec.md --stamp --issue 42

Exit codes: 0 ok, 1 check failed, 2 usage error, 3 no spec markers, 4 malformed markers."""


class Parser(argparse.ArgumentParser):
    def error(self, message):
        raise UsageError(message)


def build_parser():
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--json", action="store_true", help="machine-readable output")
    parser = Parser(
        prog="issue_lifecycle.py",
        description=__doc__.split("\n")[0],
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=EPILOG,
    )
    sub = parser.add_subparsers(dest="cmd", parser_class=Parser)

    p = sub.add_parser("extract", parents=[common], help="print the spec block")
    p.add_argument("--body", required=True, help="issue body file")
    p = sub.add_parser("replace", parents=[common], help="swap or append the spec block")
    p.add_argument("--body", required=True, help="current issue body file")
    p.add_argument("--spec", required=True, help="new spec file")
    p.add_argument("--out", required=True, help="where to write the new body")
    p = sub.add_parser("branch-name", parents=[common], help="print the branch name")
    p.add_argument(
        "--type",
        required=True,
        help="Conventional Commit type of the change (feat, fix, docs, ...)",
    )
    p.add_argument("--issue", required=True, type=int, help="issue number")
    p.add_argument("--title", required=True, help="issue title")
    p.add_argument("--hotfix", action="store_true", help="use the hotfix/ prefix")
    p = sub.add_parser("commit-check", parents=[common], help="validate a commit message")
    p.add_argument("--message", required=True, help="file, or - for stdin")
    p = sub.add_parser("pr-body-check", parents=[common], help="validate a PR body")
    p.add_argument("--body", required=True, help="PR body file")
    p.add_argument("--issue", required=True, type=int, help="issue the PR closes")
    p.add_argument("--repo", help="owner/repo when the issue is in another repo")
    p = sub.add_parser("diff-check", parents=[common], help="scan the branch diff")
    p.add_argument("--base", required=True, help="base ref, e.g. origin/main")
    p.add_argument("--repo-dir", default=".", help="repository to scan")
    p = sub.add_parser("declaration-check", parents=[common], help="validate the path declaration")
    p.add_argument("--declaration", help="file holding the declaration comment")
    p.add_argument(
        "--comments", required=True, help="JSON list of the issue's {url, body, author}"
    )
    p.add_argument("--author", required=True, help="your login; only its comments count")
    p.add_argument("--approval-mode", required=True, help="the issue's approval mode label value")
    p.add_argument("--spec", required=True, help="spec file")
    p.add_argument("--stamp", action="store_true", help="on pass, stamp this worktree for the PR")
    p.add_argument("--issue", type=int, help="issue number written into the stamp")
    return parser


def report(problems, as_json):
    """Print the check result and return the exit code."""
    if as_json:
        detail = [{"code": c, "detail": d} for c, d in problems]
        print(json.dumps({"ok": not problems, "problems": detail}))
    else:
        for code, detail in problems:
            print(f"FAIL {code}: {detail}")
        if not problems:
            print("OK")
    return EXIT_FAIL if problems else EXIT_OK


def run(argv):
    args = build_parser().parse_args(argv)
    if args.cmd is None:
        raise UsageError("a subcommand is required")
    if args.cmd == "extract":
        sys.stdout.write(extract_spec(read_text(args.body)))
        return EXIT_OK
    if args.cmd == "replace":
        new_body = replace_spec(read_text(args.body), read_text(args.spec))
        write_text(args.out, new_body)
        return EXIT_OK
    if args.cmd == "branch-name":
        print(branch_name(args.type, args.issue, args.title, args.hotfix))
        return EXIT_OK
    if args.cmd == "commit-check":
        message = read_text(args.message)
        return report(check_commit(message), args.json)
    if args.cmd == "pr-body-check":
        body = read_text(args.body)
        return report(check_pr_body(body, args.issue, args.repo), args.json)
    if args.cmd == "declaration-check":
        return cmd_declaration_check(args)
    return report(cmd_diff_check(args.base, args.repo_dir), args.json)


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    try:
        return run(argv)
    except UsageError as exc:
        if "--json" in argv:
            print(json.dumps({"error": str(exc)}))
        sys.stderr.write(f"usage error: {exc}\n")
        return EXIT_USAGE
    except MarkerError as exc:
        sys.stderr.write(f"{exc}\n")
        return exc.code


if __name__ == "__main__":
    sys.exit(main())
