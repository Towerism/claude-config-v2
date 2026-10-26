"""declaration-check with the plain-text markers Jira keeps: Jira strips `<!-- -->` from stored
comments, so the Jira declaration is fenced by `path-declaration:start` and `:end` lines."""

import importlib.util

import pytest

from tests.skills import declaration_cases as dc
from tests.skills.declaration_cases import case
from tests.skills.jira_ticket_lifecycle.conftest import SCRIPT
from tests.skills.jira_ticket_lifecycle.test_declaration_check import assert_verdict, check

PLAIN_START = "path-declaration:start"
PLAIN_END = "path-declaration:end"


def plain_block(variant, *lines, start=PLAIN_START, end=PLAIN_END, gap=None):
    head = [start] if gap is None else [start, gap]
    body = [f"variant: {variant}", *lines, "{runs}"]
    tail = [end] if gap is None else [gap, end]
    return "\n".join(head + body + tail) + "\n"


VALID = [
    case("plain markers, adjacent lines", plain_block("feature"), exit=0),
    case("plain markers, blank lines around", plain_block("feature", gap=""), exit=0),
    case(
        "html markers still read",
        plain_block("feature", start=dc.START, end=dc.END),
        exit=0,
    ),
]
MISSING = [
    case(
        "markers stripped by Jira",
        "variant: feature\n{runs}\n",
        codes=["missing-declaration"],
    ),
]
MALFORMED = [
    case("plain start, html end", plain_block("feature", end=dc.END), exit=4),
    case("html start, plain end", plain_block("feature", start=dc.START), exit=4),
    case("html start with a plain start", dc.START + "\n" + plain_block("feature"), exit=4),
    case("two plain starts", PLAIN_START + "\n" + plain_block("feature"), exit=4),
    case("unclosed plain block", plain_block("feature", end="- n/a: x — y"), exit=4),
    case("plain end before start", plain_block("feature", start=PLAIN_END, end=PLAIN_START), exit=4),
]


@pytest.mark.parametrize("c", VALID + MISSING + MALFORMED, ids=lambda c: c["name"])
def test_verdicts(env, c):
    assert_verdict(check(env, c), c)


def load_script():
    spec = importlib.util.spec_from_file_location("ticket_lifecycle", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def para(text):
    return {"type": "paragraph", "content": [{"type": "text", "text": text}]}


def bullets(*items):
    return {
        "type": "bulletList",
        "content": [{"type": "listItem", "content": [para(i)]} for i in items],
    }


def test_declaration_survives_an_adf_round_trip():
    script = load_script()
    doc = {
        "type": "doc",
        "content": [
            para(PLAIN_START),
            para("variant: feature"),
            bullets("run: self-review — https://x/1", "n/a: design — no UI"),
            para(PLAIN_END),
        ],
    }
    text = "\n".join(script.adf_blocks(doc))
    assert script.declaration_lines(text) == [
        "variant: feature",
        "- run: self-review — https://x/1",
        "- n/a: design — no UI",
    ]
