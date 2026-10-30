"""pr-body-check: the PR body rules."""

from tests.skills.github_issue_lifecycle.conftest import run, write


class TestPrBodyCheck:
    GOOD = "Implements the export.\n\nCloses #42\nSpec: #42\n\n## Review\n- W1 fixed\n"

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
