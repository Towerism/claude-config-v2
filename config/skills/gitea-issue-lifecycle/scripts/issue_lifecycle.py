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

Exit codes: 0 ok, 1 check failed, 2 usage error, 3 no spec markers, 4 malformed markers.
Issue and PR text is only ever read from files and treated as data.
"""

import argparse
import json
import re
import subprocess
import sys
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
    if text.endswith("\n"):
        text = text[:-1]
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
BREAKING_FOOTER_RE = re.compile(r"^BREAKING[ -]CHANGE: \S", re.M)


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
    if not any(re.fullmatch(r"closes " + re.escape(target), line, re.I) for line in lines):
        problems.append(("missing-closes", f"needs 'Closes {target}' alone on its own line"))
    spec_targets = "|".join(re.escape(t) for t in {target, f"#{issue}"})
    spec_line = re.compile(rf"spec: (?:{spec_targets})", re.I)
    if not any(spec_line.fullmatch(line) for line in lines):
        problems.append(("missing-spec-line", f"needs a 'Spec: {target}' line"))
    if not any(line.startswith("#") and "review" in line.lower() for line in lines):
        problems.append(("missing-review", "needs a Review section with the PR-diff review note"))
    return problems


# ── diff hygiene ─────────────────────────────────────────────────────────────

SPEC_ID_RE = re.compile(
    r"(?<![A-Za-z0-9])(?:(?:fr|nfr|ac|ec|os)-\d+(?![0-9])|(?:fr|nfr|ac|ec)\d+(?=_))", re.I
)
# In documentation an ID counts in any spelling (FR-23, FR23, fr_23), but only as a
# word of its own: the prefix may not follow a letter or digit.
DOC_ID_RE = re.compile(r"(?<![A-Za-z0-9])(nfr|fr|ac|ec|os)[-_]?(\d+)", re.I)
DOC_ID_GREP = "(nfr|fr|ac|ec|os)[-_]?[0-9]+"
SPEC_BASENAME_RE = re.compile(r"(^spec(-.+)?\.md$|-spec\.md$|\.spec\.md$)", re.I)
MARKDOWN = (".md", ".markdown")
FROZEN_SEGMENTS = {"history", "archive"}


def normal_id(text):
    """The comparable form of an ID: lowercase prefix, hyphen, number without leading zeros."""
    match = re.match(r"([a-z]+)[-_]?(\d+)", text, re.I)
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
        result = subprocess.run(["git", "-C", repo_dir, *args], capture_output=True, text=True)
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


# ── CLI ──────────────────────────────────────────────────────────────────────

EPILOG = """Examples:
  issue_lifecycle.py extract --body body.md > spec.md
  issue_lifecycle.py replace --body body.md --spec spec.md --out new-body.md
  issue_lifecycle.py branch-name --type feat --issue 42 --title "Add CSV export"
  issue_lifecycle.py commit-check --message msg.txt --json
  issue_lifecycle.py pr-body-check --body pr.md --issue 42
  issue_lifecycle.py diff-check --base origin/main

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
