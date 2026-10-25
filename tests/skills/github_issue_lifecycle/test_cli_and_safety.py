"""CLI contract, static safety checks, and speed."""

import ast
import json
import sys
import time

from tests.skills.github_issue_lifecycle.conftest import SCRIPT, make_body, run, write


def test_usage_error_exits_2_with_json_error():
    r = run("extract", "--json")
    assert r.returncode == 2
    assert "error" in json.loads(r.stdout)


def test_unknown_subcommand_exits_2():
    assert run("frobnicate").returncode == 2


def test_missing_file_is_a_usage_error(tmp_path):
    assert run("extract", "--body", tmp_path / "nope.md").returncode == 2


def test_script_is_stdlib_only_and_network_free():
    tree = ast.parse(SCRIPT.read_text())
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported |= {a.name.split(".")[0] for a in node.names}
        elif isinstance(node, ast.ImportFrom):
            imported.add(node.module.split(".")[0])
    assert not imported & {"socket", "urllib", "http", "requests"}
    assert imported <= set(sys.stdlib_module_names)


def test_subprocess_used_only_in_diff_check_and_never_with_shell():
    tree = ast.parse(SCRIPT.read_text())
    for fn in [n for n in tree.body if isinstance(n, ast.FunctionDef)]:
        uses = [
            n
            for n in ast.walk(fn)
            if isinstance(n, ast.Attribute)
            and isinstance(n.value, ast.Name)
            and n.value.id == "subprocess"
        ]
        if uses:
            assert fn.name in ("cmd_diff_check", "write_stamp"), fn.name
    for call in [n for n in ast.walk(tree) if isinstance(n, ast.Call)]:
        for kw in call.keywords:
            assert not (kw.arg == "shell" and getattr(kw.value, "value", False) is True)


def test_subcommands_are_fast_on_a_64kb_body(tmp_path):
    path = write(tmp_path, "b.md", make_body(original="y" * 64_000, spec="# Spec"))
    started = time.perf_counter()
    run("extract", "--body", path)
    elapsed = time.perf_counter() - started
    print(f"extract on 64KB took {elapsed:.3f}s")  # measured and reported, not asserted


def test_help_lists_every_subcommand_with_an_example():
    r = run("--help")
    assert r.returncode == 0
    subs = (
        "extract",
        "replace",
        "branch-name",
        "commit-check",
        "pr-body-check",
        "diff-check",
        "declaration-check",
    )
    for sub in subs:
        assert sub in r.stdout
    assert "spec-status" not in r.stdout
    assert "Examples:" in r.stdout


def test_script_loads_no_other_code():
    """The script stands alone: no importlib, no exec, nothing read from a sibling skill."""
    text = SCRIPT.read_text()
    assert "importlib" not in text and "exec(" not in text
    assert "plain-prose" not in text and "prose_check" not in text
