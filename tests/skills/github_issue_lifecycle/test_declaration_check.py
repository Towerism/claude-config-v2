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
CONDITIONAL = dc.script_constant(SCRIPT, "CONDITIONAL_STEPS")


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
        "--author",
        case["author"],
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
            "--author",
            dc.ME,
            "--approval-mode",
            "manual",
            "--spec",
            write(tmp_path, "s.md", case["spec"]),
        ]
        r = run(*args)
        assert (r.returncode, r.stdout.strip()) == (0, "OK")

    def test_author_is_required(self, tmp_path):
        case = dc.VALID[0]
        r = run(
            "declaration-check",
            "--declaration",
            write(tmp_path, "d.md", declaration_text(case)),
            "--comments",
            write(tmp_path, "c.json", json.dumps(case["comments"])),
            "--approval-mode",
            "manual",
            "--spec",
            write(tmp_path, "s.md", case["spec"]),
        )
        assert r.returncode == 2
        assert "--author" in r.stderr


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
            "--author",
            dc.ME,
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


class TestAuthor:
    test_verdicts = verdict_test(dc.AUTHOR)


class TestWaiverShape:
    test_verdicts = verdict_test(dc.WAIVER_SHAPE)


class TestConditional:
    test_verdicts = verdict_test(dc.CONDITIONAL)

    def test_conditional_steps_are_advisory_and_exclude_the_judgement_calls(self):
        assert set(CONDITIONAL) < set(ADVISORY)
        assert not {"interview", "analyst", "test-plan"} & set(CONDITIONAL)


class TestUrls:
    test_verdicts = verdict_test(dc.URLS)


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
        for args in (
            ["init", "-q", "-b", "main"],
            ["commit", "-q", "--allow-empty", "-m", "chore: base (#1)"],
            ["switch", "-q", "-c", "feature/42-export"],
        ):
            subprocess.run(["git", *args], cwd=repo, env=env, check=True, capture_output=True)
        return repo

    def head(self, repo):
        out = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=repo, check=True, capture_output=True, text=True
        )
        return out.stdout.strip()

    def test_pass_writes_branch_issue_and_head(self, tmp_path):
        repo = self.repo(tmp_path)
        r = check(tmp_path, dc.VALID[0], None, "--stamp", "--issue", 42, cwd=repo)
        assert r.returncode == 0, r.stdout + r.stderr
        stamp = repo / ".git" / "path-declaration-ok"
        assert stamp.read_text().splitlines() == ["feature/42-export", "42", self.head(repo)]

    def test_stamp_replaces_a_symlink_instead_of_following_it(self, tmp_path):
        repo = self.repo(tmp_path)
        outside = tmp_path / "outside.txt"
        outside.write_text("keep\n")
        stamp = repo / ".git" / "path-declaration-ok"
        stamp.symlink_to(outside)
        r = check(tmp_path, dc.VALID[0], None, "--stamp", "--issue", 42, cwd=repo)
        assert r.returncode == 0, r.stdout + r.stderr
        assert outside.read_text() == "keep\n"
        assert not stamp.is_symlink()
        assert stamp.read_text().splitlines()[0] == "feature/42-export"
        assert [p.name for p in (repo / ".git").iterdir() if p.name.startswith("tmp")] == []

    def test_fail_writes_no_stamp_and_clears_an_old_one(self, tmp_path):
        repo = self.repo(tmp_path)
        stamp = repo / ".git" / "path-declaration-ok"
        stamp.write_text("feature/42-export\n42\n")
        r = check(tmp_path, dc.REQUIRED[0], None, "--stamp", "--issue", 42, cwd=repo)
        assert r.returncode == 1
        assert not stamp.exists()

    def stamped(self, tmp_path):
        repo = self.repo(tmp_path)
        r = check(tmp_path, dc.VALID[0], None, "--stamp", "--issue", 42, cwd=repo)
        assert r.returncode == 0, r.stdout + r.stderr
        stamp = repo / ".git" / "path-declaration-ok"
        assert stamp.exists()
        return repo, stamp

    def test_two_blocks_on_a_rerun_clear_the_stamp(self, tmp_path):
        repo, stamp = self.stamped(tmp_path)
        r = check(tmp_path, dc.MALFORMED[0], None, "--stamp", "--issue", 42, cwd=repo)
        assert r.returncode == 4
        assert not stamp.exists()

    def test_unreadable_comments_on_a_rerun_clear_the_stamp(self, tmp_path):
        repo, stamp = self.stamped(tmp_path)
        missing = str(tmp_path / "missing.json")
        extra = ("--comments", missing, "--stamp", "--issue", 42)
        r = check(tmp_path, dc.VALID[0], None, *extra, cwd=repo)
        assert r.returncode == 2
        assert not stamp.exists()

    def test_stamp_without_an_issue_on_a_rerun_clears_the_stamp(self, tmp_path):
        repo, stamp = self.stamped(tmp_path)
        assert check(tmp_path, dc.VALID[0], None, "--stamp", cwd=repo).returncode == 2
        assert not stamp.exists()

    def test_no_stamp_without_the_flag(self, tmp_path):
        repo = self.repo(tmp_path)
        assert check(tmp_path, dc.VALID[0], cwd=repo).returncode == 0
        assert not (repo / ".git" / "path-declaration-ok").exists()

    def test_stamp_needs_an_issue(self, tmp_path):
        repo = self.repo(tmp_path)
        assert check(tmp_path, dc.VALID[0], None, "--stamp", cwd=repo).returncode == 2
