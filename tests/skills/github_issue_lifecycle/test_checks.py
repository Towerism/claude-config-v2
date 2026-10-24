"""branch-name, commit-check, pr-body-check: release-impacting text rules."""

import json

import pytest

from tests.skills.github_issue_lifecycle.conftest import run, write


class TestBranchName:
    def test_feat_maps_to_feature_and_title_is_slugged(self):
        r = run(
            "branch-name",
            "--type",
            "feat",
            "--issue",
            42,
            "--title",
            "Add CSV export: roster (v2)!",
        )
        assert r.returncode == 0
        assert r.stdout.strip() == "feature/42-add-csv-export-roster-v2"

    @pytest.mark.parametrize(
        "cc,prefix",
        [
            ("fix", "fix"),
            ("docs", "docs"),
            ("refactor", "chore"),
            ("chore", "chore"),
            ("ci", "chore"),
        ],
    )
    def test_type_mapping(self, cc, prefix):
        r = run("branch-name", "--type", cc, "--issue", 7, "--title", "x")
        assert r.stdout.strip() == f"{prefix}/7-x"

    def test_hotfix_flag_wins(self):
        r = run("branch-name", "--type", "fix", "--issue", 9, "--title", "Login 500s", "--hotfix")
        assert r.stdout.strip() == "hotfix/9-login-500s"

    def test_long_title_is_cut_at_a_hyphen_boundary(self):
        title = "Make the attendance export include every tournament division header row"
        slug = run("branch-name", "--type", "feat", "--issue", 1, "--title", title).stdout.strip()
        slug = slug.split("/", 1)[1].split("-", 1)[1]
        assert len(slug) <= 40
        assert not slug.endswith("-")
        assert title.lower().replace(" ", "-").startswith(slug)

    def test_unicode_is_transliterated(self):
        r = run("branch-name", "--type", "feat", "--issue", 3, "--title", "Pokémon façade — naïve")
        assert r.stdout.strip() == "feature/3-pokemon-facade-naive"

    def test_empty_slug_falls_back_to_issue_number(self):
        r = run("branch-name", "--type", "feat", "--issue", 5, "--title", "日本語")
        assert r.stdout.strip() == "feature/5-issue-5"

    def test_unknown_type_is_a_usage_error(self):
        assert run("branch-name", "--type", "wip", "--issue", 5, "--title", "x").returncode == 2


class TestCommitCheck:
    def check(self, tmp_path, message):
        return run("commit-check", "--message", write(tmp_path, "msg", message))

    def test_conventional_subject_with_issue_passes(self, tmp_path):
        assert self.check(tmp_path, "feat(roster): add CSV export (#42)").returncode == 0

    def test_breaking_with_footer_passes(self, tmp_path):
        msg = "fix!: drop v1 route (#7)\n\nBREAKING CHANGE: /v1 is gone"
        assert self.check(tmp_path, msg).returncode == 0

    def test_breaking_without_footer_fails(self, tmp_path):
        r = self.check(tmp_path, "fix!: drop v1 route (#7)")
        assert r.returncode == 1
        assert "breaking change needs footer" in r.stdout

    def test_non_conventional_fails(self, tmp_path):
        r = self.check(tmp_path, "Add export")
        assert r.returncode == 1
        assert "not conventional" in r.stdout

    def test_missing_issue_reference_fails(self, tmp_path):
        r = self.check(tmp_path, "feat: add export")
        assert r.returncode == 1
        assert "missing (#N)" in r.stdout

    def test_cross_repo_reference_passes(self, tmp_path):
        assert (
            self.check(tmp_path, "fix(api): handle 404 (acme/kit#12)").returncode == 0
        )

    def test_message_from_stdin(self):
        r = run("commit-check", "--message", "-", stdin="docs: explain merge flow (#3)\n")
        assert r.returncode == 0

    def test_json_output_shape(self, tmp_path):
        r = run("commit-check", "--message", write(tmp_path, "m", "Add export"), "--json")
        data = json.loads(r.stdout)
        assert data["ok"] is False
        assert data["problems"][0]["code"] == "not-conventional"


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
