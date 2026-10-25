"""Shared fixture table for the `declaration-check` subcommand of every lifecycle script.

Each case is plain data: a declaration template, the issue's comments, the approval mode, the
spec text and the expected verdict. A template's `{runs}` expands to a `run` line citing
RUN_URL for each step of the variant that the template does not name and the case does not
list in `drop`. The tests fill it in with `render()` from the step sets each script
defines, so the table never restates those sets. The helpers below it are shared by the tests.
"""

import ast
import json
import re

START = "<!-- path-declaration v1 -->"
END = "<!-- /path-declaration -->"

RUN_URL = "https://tracker.example/issues/42#comment-100"
NO_URL = "https://tracker.example/issues/42#comment-101"
WIZARD_URL = "https://tracker.example/issues/42#comment-102"
OTHER_URL = "https://tracker.example/issues/42#comment-103"
FOREIGN_URL = "https://tracker.example/issues/7#comment-900"

COMMENTS = [
    {"url": RUN_URL, "body": "Ran the step; notes below."},
    {"url": NO_URL, "body": "Review the proposed pipeline?\n\nNo"},
    {"url": WIZARD_URL, "body": "Skip the analyst pass: yes, skip it. The change is one line."},
    {"url": OTHER_URL, "body": "Unrelated discussion."},
]

SPEC = "## Goal\nExport the roster.\n"
SPEC_WITH_SEAMS = "## Goal\nExport the roster.\n\n## Seams\n- export_csv(rows)\n"
SPEC_SEAMS_IN_FENCE = "## Goal\nExport.\n\n```\n## Seams\n```\n"

LINE_RE = re.compile(r"^- (?:run|waived|n/a): (\S+)", re.M)


def block(variant, *lines):
    head = [START] + ([f"variant: {variant}"] if variant is not None else [])
    return "\n".join(head + list(lines) + ["{runs}", END]) + "\n"


def render(template, steps, drop=()):
    """Expand `{runs}` with a run line for each of `steps` the template does not name."""
    named = set(LINE_RE.findall(template))
    runs = [f"- run: {s} — {RUN_URL}" for s in steps if s not in named and s not in drop]
    return template.replace("{runs}", "\n".join(runs))


def case(name, declaration, exit=1, codes=(), variant="feature", **extra):
    return {
        "name": name,
        "declaration": declaration,
        "variant": variant,
        "comments": COMMENTS,
        "approval_mode": "manual",
        "spec": SPEC,
        "drop": (),
        "exit": exit,
        "codes": sorted(codes),
        **extra,
    }


VALID = [
    case("every step run", block("feature"), exit=0),
    case(
        "advisory waived in the wizard",
        block("feature", f'- waived: analyst — "yes, skip it" — {WIZARD_URL}'),
        exit=0,
    ),
    case(
        "advisory steps waived by the No answer",
        block(
            "feature",
            f'- waived: analyst — "No" — {NO_URL}',
            f'- waived: simplifier — "No" — {NO_URL}',
        ),
        exit=0,
    ),
    case(
        "curly quotes",
        block("feature", f"- waived: analyst — “yes, skip it” — {WIZARD_URL}"),
        exit=0,
    ),
    case(
        "advisory n/a with a fact",
        block("feature", "- n/a: design — not a UI change"),
        exit=0,
    ),
]

MISSING = [
    case("empty declaration", "", codes=["missing-declaration"]),
    case("no block in the text", "Path: the usual one.\n", codes=["missing-declaration"]),
]

REQUIRED = [
    case("required step absent", block("feature"), drop=("verify",), codes=["required-not-run"]),
    case(
        "required step n/a",
        block("feature", "- n/a: verify — nothing to verify"),
        codes=["required-not-run"],
    ),
    case(
        "required step waived",
        block("feature", f'- waived: tdd — "yes, skip it" — {WIZARD_URL}'),
        codes=["required-waived"],
    ),
    case(
        "required step waived by the No answer",
        block("feature", f'- waived: diff-review — "No" — {NO_URL}'),
        codes=["required-waived"],
    ),
]

QUOTES = [
    case(
        "empty quote",
        block("feature", f'- waived: analyst — "" — {WIZARD_URL}'),
        codes=["waiver-needs-quote"],
    ),
    case(
        "whitespace quote",
        block("feature", f'- waived: analyst — "   " — {WIZARD_URL}'),
        codes=["waiver-needs-quote"],
    ),
    case(
        "unquoted waiver",
        block("feature", f"- waived: analyst — yes, skip it — {WIZARD_URL}"),
        codes=["waiver-needs-quote"],
    ),
]

EVIDENCE = [
    case(
        "run cites a spec section",
        block("feature", "- run: verify — https://tracker.example/issues/42#seams"),
        codes=["run-needs-evidence"],
    ),
    case(
        "run cites spec#section",
        block("feature", "- run: tdd — spec#seams"),
        codes=["run-needs-evidence"],
    ),
    case(
        "run cites another issue's comment",
        block("feature", f"- run: verify — {FOREIGN_URL}"),
        codes=["run-needs-evidence"],
    ),
    case("run without evidence", block("feature", "- run: verify"), codes=["run-needs-evidence"]),
    case(
        "waiver quote not in the cited comment",
        block("feature", f'- waived: analyst — "skip everything" — {WIZARD_URL}'),
        codes=["waiver-not-recorded"],
    ),
    case(
        "waiver quote cites the wrong comment",
        block("feature", f'- waived: analyst — "yes, skip it" — {OTHER_URL}'),
        codes=["waiver-not-recorded"],
    ),
    case(
        "waiver cites a comment not on the issue",
        block("feature", f'- waived: analyst — "yes, skip it" — {FOREIGN_URL}'),
        codes=["waiver-not-recorded"],
    ),
    case(
        "advisory step skipped without a recorded answer",
        block("feature"),
        drop=("analyst",),
        codes=["waiver-not-recorded"],
    ),
]

UNKNOWN = [
    case("unknown step", block("feature", f"- run: lint — {RUN_URL}"), codes=["unknown-step"]),
    case(
        "duplicate step",
        block("feature", f"- run: verify — {RUN_URL}", f"- run: verify — {RUN_URL}"),
        codes=["unknown-step"],
    ),
    case("unknown variant", block("spike"), variant="feature", codes=["unknown-step"]),
    case("no variant line", block(None), codes=["unknown-step"]),
    case("unreadable line", block("feature", "* ran everything"), codes=["unknown-step"]),
    case(
        "repro outside the bug variant",
        block("feature", f"- run: repro — {RUN_URL}"),
        codes=["unknown-step"],
    ),
]

MALFORMED = [
    case("two blocks", block("feature") + block("feature"), exit=4),
    case("unclosed block", f"{START}\nvariant: feature\n{{runs}}\n", exit=4),
    case("lone closing marker", f"variant: feature\n{{runs}}\n{END}\n", exit=4),
    case("closing before opening", f"{END}\n{START}\n{{runs}}\n", exit=4),
]

NOT_APPLICABLE = [
    case(
        "n/a without a fact",
        block("feature", "- n/a: design —"),
        codes=["na-needs-fact"],
    ),
    case("n/a without a separator", block("feature", "- n/a: qa"), codes=["na-needs-fact"]),
    case(
        "security gate n/a with a fact",
        block("feature", "- n/a: security-gate — diff touches no auth, input, shell or network"),
        exit=0,
    ),
    case(
        "spec review n/a under no-review",
        block("feature", "- n/a: spec-review — approval: no-review"),
        approval_mode="no-review",
        exit=0,
    ),
    case(
        "spec review n/a while the label says manual",
        block("feature", "- n/a: spec-review — approval: no-review"),
        codes=["required-not-run"],
    ),
    case(
        "spec review n/a with another fact",
        block("feature", "- n/a: spec-review — small change"),
        approval_mode="no-review",
        codes=["required-not-run"],
    ),
]

SEAMS = [
    case(
        "test plan waived without seams",
        block("feature", f'- waived: test-plan — "No" — {NO_URL}'),
        codes=["seams-needed"],
    ),
    case(
        "test plan waived with seams",
        block("feature", f'- waived: test-plan — "No" — {NO_URL}'),
        spec=SPEC_WITH_SEAMS,
        exit=0,
    ),
    case(
        "seams heading only inside a code fence",
        block("feature", f'- waived: test-plan — "No" — {NO_URL}'),
        spec=SPEC_SEAMS_IN_FENCE,
        codes=["seams-needed"],
    ),
]

VARIANTS = [
    case("bug runs repro", block("bug"), variant="bug", exit=0),
    case(
        "bug without repro",
        block("bug"),
        variant="bug",
        drop=("repro",),
        codes=["required-not-run"],
    ),
    case(
        "docs marks test plan and tdd n/a",
        block("docs", "- n/a: test-plan — variant: docs", "- n/a: tdd — variant: docs"),
        variant="docs",
        exit=0,
    ),
    case(
        "docs n/a with another fact",
        block("docs", "- n/a: tdd — no code"),
        variant="docs",
        codes=["required-not-run"],
    ),
    case(
        "feature borrows the docs fact for tdd",
        block("feature", "- n/a: tdd — variant: docs"),
        codes=["required-not-run"],
    ),
    case(
        "feature borrows the docs fact for the test plan",
        block("feature", "- n/a: test-plan — variant: docs"),
        codes=["waiver-not-recorded"],
    ),
    case("ui", block("ui"), variant="ui", exit=0),
    case("hotfix", block("hotfix"), variant="hotfix", exit=0),
]

ALL = VALID + MISSING + REQUIRED + QUOTES + EVIDENCE + UNKNOWN + MALFORMED + NOT_APPLICABLE
ALL += SEAMS + VARIANTS


def script_constant(script, name):
    """Read a module-level constant from a script without importing the script."""
    for node in ast.parse(script.read_text()).body:
        if isinstance(node, ast.Assign) and getattr(node.targets[0], "id", None) == name:
            return ast.literal_eval(node.value)
    raise AssertionError(f"{script.name} has no {name}")


def codes(result):
    return sorted({p["code"] for p in json.loads(result.stdout)["problems"]})


def ids(cases):
    return [c["name"] for c in cases]
