"""declaration-check: the path declaration verdicts from the shared fixture table, and the stamp."""

import json
import os
import subprocess

import pytest

from tests.skills import declaration_cases as dc
from tests.skills.declaration_cases import codes, ids
from tests.skills.github_issue_lifecycle.conftest import GIT_ENV, SCRIPT, run, write

REQUIRED = dc.script_constant(SCRIPT, "REQUIRED_STEPS")
ADVISORY = dc.script_constant(SCRIPT, "ADVISORY_STEPS")
VARIANT_STEPS = dc.script_constant(SCRIPT, "VARIANT_STEPS")


def steps(variant):
    return tuple(REQUIRED) + tuple(VARIANT_STEPS.get(variant, ())) + tuple(ADVISORY)


def declaration_text(case):
    return dc.render(case["declaration"], steps(case["variant"]), case["drop"])


def check(tmp_path, case, text=None, *extra, cwd=None):
    text = declaration_text(case) if text is None else text
    return run(
        "declaration-check",
        "--declaration",
        write(tmp_path, "declaration.md", text),
        "--comments",
        write(tmp_path, "comments.json", json.dumps(case["comments"])),
        "--approval-mode",
        case["approval_mode"],
        "--spec",
        write(tmp_path, "spec.md", case["spec"]),
        "--json",
        *extra,
        cwd=cwd,
    )


def assert_verdict(result, case):
    assert result.returncode == case["exit"], result.stdout + result.stderr
    if case["exit"] == 4:
        assert result.stdout == ""
        assert result.stderr.strip()
    else:
        assert codes(result) == case["codes"]


def verdict_test(cases):
    @pytest.mark.parametrize("case", cases, ids=ids(cases))
    def test(self, tmp_path, case):
        assert_verdict(check(tmp_path, case), case)

    return test


class TestValid:
    test_passes = verdict_test(dc.VALID)

    def test_plain_output_says_ok(self, tmp_path):
        case = dc.VALID[0]
        args = [
            "declaration-check",
            "--declaration",
            write(tmp_path, "d.md", declaration_text(case)),
            "--comments",
            write(tmp_path, "c.json", json.dumps(case["comments"])),
            "--approval-mode",
            "manual",
            "--spec",
            write(tmp_path, "s.md", case["spec"]),
        ]
        r = run(*args)
        assert (r.returncode, r.stdout.strip()) == (0, "OK")


class TestMissing:
    test_fails = verdict_test(dc.MISSING)

    @pytest.mark.parametrize("flag", [False, True], ids=["no flag", "absent file"])
    def test_no_declaration_file(self, tmp_path, flag):
        declaration = ["--declaration", tmp_path / "nope.md"] if flag else []
        r = run(
            "declaration-check",
            *declaration,
            "--comments",
            write(tmp_path, "c.json", "[]"),
            "--approval-mode",
            "manual",
            "--spec",
            write(tmp_path, "s.md", dc.SPEC),
            "--json",
        )
        assert (r.returncode, codes(r)) == (1, ["missing-declaration"])


class TestRequired:
    test_fails = verdict_test(dc.REQUIRED)


class TestQuotes:
    test_fails = verdict_test(dc.QUOTES)


class TestEvidence:
    test_fails = verdict_test(dc.EVIDENCE)


class TestUnknown:
    test_fails = verdict_test(dc.UNKNOWN)


class TestMalformed:
    test_exits_4_alone = verdict_test(dc.MALFORMED)


class TestLineEndings:
    @pytest.mark.parametrize("case", dc.ALL, ids=ids(dc.ALL))
    def test_crlf_and_trailing_spaces_keep_the_verdict(self, tmp_path, case):
        text = declaration_text(case).replace("\n", "  \r\n")
        assert_verdict(check(tmp_path, case, text), case)


class TestNotApplicable:
    test_verdicts = verdict_test(dc.NOT_APPLICABLE)


class TestSeams:
    test_verdicts = verdict_test(dc.SEAMS)


class TestVariants:
    test_verdicts = verdict_test(dc.VARIANTS)

    def test_bug_variant_requires_repro(self):
        assert "repro" in VARIANT_STEPS["bug"]
        assert "repro" not in REQUIRED


class TestStamp:
    def repo(self, tmp_path):
        repo = tmp_path / "repo"
        repo.mkdir()
        env = {**os.environ, **GIT_ENV}
        for args in (["init", "-q", "-b", "main"], ["switch", "-q", "-c", "feature/42-export"]):
            subprocess.run(["git", *args], cwd=repo, env=env, check=True, capture_output=True)
        return repo

    def test_pass_writes_branch_and_issue(self, tmp_path):
        repo = self.repo(tmp_path)
        r = check(tmp_path, dc.VALID[0], None, "--stamp", "--issue", 42, cwd=repo)
        assert r.returncode == 0, r.stdout + r.stderr
        stamp = repo / ".git" / "path-declaration-ok"
        assert stamp.read_text().splitlines() == ["feature/42-export", "42"]

    def test_fail_writes_no_stamp_and_clears_an_old_one(self, tmp_path):
        repo = self.repo(tmp_path)
        stamp = repo / ".git" / "path-declaration-ok"
        stamp.write_text("feature/42-export\n42\n")
        r = check(tmp_path, dc.REQUIRED[0], None, "--stamp", "--issue", 42, cwd=repo)
        assert r.returncode == 1
        assert not stamp.exists()

    def test_no_stamp_without_the_flag(self, tmp_path):
        repo = self.repo(tmp_path)
        assert check(tmp_path, dc.VALID[0], cwd=repo).returncode == 0
        assert not (repo / ".git" / "path-declaration-ok").exists()

    def test_stamp_needs_an_issue(self, tmp_path):
        repo = self.repo(tmp_path)
        assert check(tmp_path, dc.VALID[0], None, "--stamp", cwd=repo).returncode == 2
