"""pr-body-check: the PR body rules."""

import re
import subprocess
import sys

import pytest

from tests.conftest import ROOT
from tests.skills.github_issue_lifecycle.conftest import run, write


class TestPrBodyCheck:
    GOOD = (
        "Implements the export.\n\nCloses #42\nSpec: #42\n\n"
        "## Review\nSpec check: every item built, nothing outside the spec\n- W1 fixed\n"
    )

    def check(self, tmp_path, body, *extra):
        return run("pr-body-check", "--body", write(tmp_path, "pr.md", body), "--issue", 42, *extra)

    def test_full_body_passes(self, tmp_path):
        assert self.check(tmp_path, self.GOOD).returncode == 0

    def test_only_a_mention_fails(self, tmp_path):
        r = self.check(tmp_path, "Work for #42\n")
        assert r.returncode == 1
        assert "closes" in r.stdout.lower()

    def test_two_issues_on_one_keyword_fails(self, tmp_path):
        r = self.check(tmp_path, self.GOOD.replace("Closes #42", "Closes #42, #43"))
        assert r.returncode == 1

    def test_missing_spec_line_fails(self, tmp_path):
        assert self.check(tmp_path, self.GOOD.replace("Spec: #42\n", "")).returncode == 1

    def test_missing_review_section_fails(self, tmp_path):
        assert self.check(tmp_path, self.GOOD.replace("## Review", "## Notes")).returncode == 1

    def test_cross_repo_close(self, tmp_path):
        body = self.GOOD.replace("Closes #42", "Closes acme/kit#42")
        assert self.check(tmp_path, body, "--repo", "acme/kit").returncode == 0
        assert self.check(tmp_path, body).returncode == 1

    def test_crlf_body(self, tmp_path):
        assert self.check(tmp_path, self.GOOD.replace("\n", "\r\n")).returncode == 0

    def test_a_spec_file_path_does_not_stand_for_the_issue(self, tmp_path):
        body = self.GOOD.replace("Spec: #42", "Spec: config/skills/foo/SPEC.md")
        assert self.check(tmp_path, body).returncode == 1

    def test_missing_spec_check_line_fails(self, tmp_path):
        body = self.GOOD.replace("Spec check: every item built, nothing outside the spec\n", "")
        r = self.check(tmp_path, body)
        assert r.returncode == 1
        assert "Spec check:" in r.stdout

    def test_an_empty_spec_check_line_fails(self, tmp_path):
        body = self.GOOD.replace("every item built, nothing outside the spec", "")
        assert self.check(tmp_path, body).returncode == 1

    def test_a_spec_check_line_outside_the_review_section_fails(self, tmp_path):
        line = "Spec check: every item built, nothing outside the spec\n"
        body = self.GOOD.replace(line, "").replace("## Review", line + "\n## Review")
        assert self.check(tmp_path, body).returncode == 1

    def test_a_review_subheading_does_not_open_the_review_section(self, tmp_path):
        body = self.GOOD.replace("## Review\n", "## Notes\n### Pre-review notes\n")
        r = self.check(tmp_path, body)
        assert r.returncode == 1
        assert "Spec check:" in r.stdout

    def test_a_subheading_inside_review_keeps_the_section_open(self, tmp_path):
        body = self.GOOD.replace("## Review\n", "## Review\n### Notes\n")
        assert self.check(tmp_path, body).returncode == 0

    @pytest.mark.parametrize("skill", ["github-issue-lifecycle", "gitea-issue-lifecycle"])
    def test_the_filled_in_template_passes(self, tmp_path, skill):
        skill_dir = ROOT / "config" / "skills" / skill
        text = (skill_dir / "assets" / "pr-body-template.md").read_text()
        text = re.sub(r"<!--.*?-->", "", text, flags=re.DOTALL).replace("#N", "#42")
        body = write(tmp_path, "pr.md", re.sub(r"<[^<>]*>", "filled in", text))
        script = skill_dir / "scripts" / "issue_lifecycle.py"
        r = subprocess.run(
            [sys.executable, "-I", str(script), "pr-body-check", "--body", body, "--issue", "42"],
            capture_output=True, text=True, timeout=30, check=False,
        )
        assert r.returncode == 0, r.stdout + r.stderr
