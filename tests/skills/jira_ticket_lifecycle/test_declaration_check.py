"""declaration-check: the path declaration verdicts from the shared fixture table, the stamp
keyed by ticket, and the rules this script shares with the GitHub lifecycle script."""

import json
import subprocess

import pytest

from tests.conftest import ROOT
from tests.skills import declaration_cases as dc
from tests.skills.declaration_cases import codes, ids
from tests.skills.jira_ticket_lifecycle.conftest import GIT_ENV, SCRIPT

GITHUB_SCRIPT = (
    ROOT / "config" / "skills" / "github-issue-lifecycle" / "scripts" / "issue_lifecycle.py"
)
SHARED = (
    "ADVISORY_STEPS",
    "CONDITIONAL_STEPS",
    "REQUIRED_STEPS",
    "VARIANT_STEPS",
    "DOCS_NA_STEPS",
    "DOCS_FACT",
    "NO_REVIEW_FACT",
    "NO_REVIEW_MODE",
    "STAMP_NAME",
    "DECL_START",
    "DECL_END",
)


REQUIRED = dc.script_constant(SCRIPT, "REQUIRED_STEPS")
ADVISORY = dc.script_constant(SCRIPT, "ADVISORY_STEPS")
VARIANT_STEPS = dc.script_constant(SCRIPT, "VARIANT_STEPS")


def steps(variant):
    return tuple(REQUIRED) + tuple(VARIANT_STEPS.get(variant, ())) + tuple(ADVISORY)


def declaration_text(case):
    return dc.render(case["declaration"], steps(case["variant"]), case["drop"])


def check(env, case, text=None, *extra, cwd=None):
    text = declaration_text(case) if text is None else text
    return env.run(
        "declaration-check",
        "--declaration",
        env.file("declaration.md", text),
        "--comments",
        env.file("comments.json", json.dumps(case["comments"])),
        "--author",
        case["author"],
        "--approval-mode",
        case["approval_mode"],
        "--spec",
        env.file("spec.md", case["spec"]),
        "--json",
        *extra,
        cwd=cwd,
    )


def assert_verdict(result, case):
    assert result.returncode == case["exit"], result.stdout + result.stderr
    if case["exit"] == 4:
        # Under --json, a malformed declaration prints only the error, with no verdict.
        assert json.loads(result.stdout) == {"error": result.stderr.strip()}
        assert result.stderr.strip()
    else:
        assert codes(result) == case["codes"]


def verdict_test(cases):
    @pytest.mark.parametrize("case", cases, ids=ids(cases))
    def test(self, env, case):
        assert_verdict(check(env, case), case)

    return test


class TestValid:
    test_passes = verdict_test(dc.VALID)

    def test_plain_output_says_ok(self, env):
        case = dc.VALID[0]
        r = env.run(
            "declaration-check",
            "--declaration",
            env.file("d.md", declaration_text(case)),
            "--comments",
            env.file("c.json", json.dumps(case["comments"])),
            "--author",
            dc.ME,
            "--approval-mode",
            "manual",
            "--spec",
            env.file("s.md", case["spec"]),
        )
        assert (r.returncode, r.stdout.strip()) == (0, "OK")

    def test_author_is_required(self, env):
        case = dc.VALID[0]
        r = env.run(
            "declaration-check",
            "--declaration",
            env.file("d.md", declaration_text(case)),
            "--comments",
            env.file("c.json", json.dumps(case["comments"])),
            "--approval-mode",
            "manual",
            "--spec",
            env.file("s.md", case["spec"]),
        )
        assert r.returncode == 2
        assert "--author" in r.stderr

    def test_needs_no_jira_settings(self, env):
        (env.config / "claude-config" / "local.json").unlink()
        assert check(env, dc.VALID[0]).returncode == 0


class TestMissing:
    test_fails = verdict_test(dc.MISSING)

    @pytest.mark.parametrize("flag", [False, True], ids=["no flag", "absent file"])
    def test_no_declaration_file(self, env, flag):
        declaration = ["--declaration", env.tmp / "nope.md"] if flag else []
        r = env.run(
            "declaration-check",
            *declaration,
            "--comments",
            env.file("c.json", "[]"),
            "--author",
            dc.ME,
            "--approval-mode",
            "manual",
            "--spec",
            env.file("s.md", dc.SPEC),
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
    def test_crlf_and_trailing_spaces_keep_the_verdict(self, env, case):
        text = declaration_text(case).replace("\n", "  \r\n")
        assert_verdict(check(env, case, text), case)


class TestNotApplicable:
    test_verdicts = verdict_test(dc.NOT_APPLICABLE)


class TestAuthor:
    test_verdicts = verdict_test(dc.AUTHOR)


class TestWaiverShape:
    test_verdicts = verdict_test(dc.WAIVER_SHAPE)


class TestConditional:
    test_verdicts = verdict_test(dc.CONDITIONAL)


class TestUrls:
    test_verdicts = verdict_test(dc.URLS)


class TestSeams:
    test_verdicts = verdict_test(dc.SEAMS)


class TestVariants:
    test_verdicts = verdict_test(dc.VARIANTS)

    def test_bug_variant_requires_repro(self):
        assert "repro" in VARIANT_STEPS["bug"]
        assert "repro" not in REQUIRED


class TestSpecTextRule:
    """A scenario-like waiver quote still passes; the PR body's spec-copy rule does not apply."""

    @pytest.mark.parametrize(
        "words", ["Given the change is one line, skip it", "When in doubt, no"]
    )
    def test_a_quote_that_reads_like_a_scenario_passes(self, env, words):
        url = dc.WIZARD_URL
        body = f"Path declaration answer: Skip the analyst pass?\n\n{words}"
        comments = [*dc.COMMENTS[:2], {"url": url, "body": body, "author": dc.ME}]
        case = dc.case(
            "scenario quote",
            dc.block("feature", f'- waived: analyst — "{words}" — {url}'),
            exit=0,
            comments=comments,
        )
        assert_verdict(check(env, case), case)


class TestStamp:
    def repo(self, env):
        for args in (
            ["commit", "-q", "--allow-empty", "-m", "chore: base (PAY-1)"],
            ["switch", "-q", "-c", "feature/PAY-142-export"],
        ):
            subprocess.run(
                ["git", *args],
                cwd=env.repo,
                env={**env.environ(), **GIT_ENV},
                check=True,
                capture_output=True,
            )
        return env.repo

    def head(self, repo):
        out = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=repo, check=True, capture_output=True, text=True
        )
        return out.stdout.strip()

    def test_pass_writes_branch_key_and_head(self, env):
        repo = self.repo(env)
        r = check(env, dc.VALID[0], None, "--stamp", "--key", "PAY-142", cwd=repo)
        assert r.returncode == 0, r.stdout + r.stderr
        stamp = repo / ".git" / "path-declaration-ok"
        lines = stamp.read_text().splitlines()
        assert lines == ["feature/PAY-142-export", "PAY-142", self.head(repo)]

    def test_stamp_replaces_a_symlink_instead_of_following_it(self, env):
        repo = self.repo(env)
        outside = env.tmp / "outside.txt"
        outside.write_text("keep\n")
        stamp = repo / ".git" / "path-declaration-ok"
        stamp.symlink_to(outside)
        r = check(env, dc.VALID[0], None, "--stamp", "--key", "PAY-142", cwd=repo)
        assert r.returncode == 0, r.stdout + r.stderr
        assert outside.read_text() == "keep\n"
        assert not stamp.is_symlink()
        assert stamp.read_text().splitlines()[0] == "feature/PAY-142-export"

    def test_fail_writes_no_stamp_and_clears_an_old_one(self, env):
        repo = self.repo(env)
        stamp = repo / ".git" / "path-declaration-ok"
        stamp.write_text("feature/PAY-142-export\nPAY-142\n")
        r = check(env, dc.REQUIRED[0], None, "--stamp", "--key", "PAY-142", cwd=repo)
        assert r.returncode == 1
        assert not stamp.exists()

    def stamped(self, env):
        repo = self.repo(env)
        r = check(env, dc.VALID[0], None, "--stamp", "--key", "PAY-142", cwd=repo)
        assert r.returncode == 0, r.stdout + r.stderr
        stamp = repo / ".git" / "path-declaration-ok"
        assert stamp.exists()
        return repo, stamp

    def test_two_blocks_on_a_rerun_clear_the_stamp(self, env):
        repo, stamp = self.stamped(env)
        r = check(env, dc.MALFORMED[0], None, "--stamp", "--key", "PAY-142", cwd=repo)
        assert r.returncode == 4
        assert not stamp.exists()

    def test_unreadable_comments_on_a_rerun_clear_the_stamp(self, env):
        repo, stamp = self.stamped(env)
        missing = str(env.tmp / "missing.json")
        extra = ("--comments", missing, "--stamp", "--key", "PAY-142")
        r = check(env, dc.VALID[0], None, *extra, cwd=repo)
        assert r.returncode == 2
        assert not stamp.exists()

    def test_stamp_without_a_key_on_a_rerun_clears_the_stamp(self, env):
        repo, stamp = self.stamped(env)
        assert check(env, dc.VALID[0], None, "--stamp", cwd=repo).returncode == 2
        assert not stamp.exists()

    def test_no_stamp_without_the_flag(self, env):
        repo = self.repo(env)
        assert check(env, dc.VALID[0], cwd=repo).returncode == 0
        assert not (repo / ".git" / "path-declaration-ok").exists()

    def test_stamp_needs_a_key(self, env):
        repo = self.repo(env)
        assert check(env, dc.VALID[0], None, "--stamp", cwd=repo).returncode == 2

    def test_stamp_refuses_a_malformed_key(self, env):
        repo = self.repo(env)
        r = check(env, dc.VALID[0], None, "--stamp", "--key", "pay 142", cwd=repo)
        assert r.returncode == 2
        assert not (repo / ".git" / "path-declaration-ok").exists()


@pytest.mark.parametrize("name", SHARED)
def test_the_step_rules_match_the_github_script(name):
    ours, theirs = dc.script_constant(SCRIPT, name), dc.script_constant(GITHUB_SCRIPT, name)
    if isinstance(ours, tuple):
        assert set(ours) == set(theirs)
    else:
        assert ours == theirs
