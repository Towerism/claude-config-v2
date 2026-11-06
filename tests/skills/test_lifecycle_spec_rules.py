"""The lifecycle skills tell the agent to check the spec's seam list before storing it and to
record the two-way spec check in the PR body."""

import re

import pytest

from tests.conftest import ROOT

SKILLS = ("github-issue-lifecycle", "gitea-issue-lifecycle", "jira-ticket-lifecycle")


def step(skill, number):
    text = (ROOT / "config" / "skills" / skill / "SKILL.md").read_text()
    return re.search(rf"^### {number}\. .*?(?=^### )", text, re.MULTILINE | re.DOTALL).group(0)


@pytest.mark.parametrize("skill", SKILLS)
def test_step_4_plans_missing_seams_and_runs_spec_check(skill):
    text = step(skill, 4)
    assert "oh-my-claudecode:test-engineer" in text
    assert "spec-check" in text
    assert "`## Test plan`" in text and "`seam: … | catches: … | misses: …`" in text  # the form spec-check reads


@pytest.mark.parametrize("skill", SKILLS)
def test_spec_check_runs_before_the_spec_is_stored(skill):
    text = step(skill, 4)
    store = "sync-spec --key" if skill.startswith("jira") else "replace --body"
    assert text.index("spec-check") < text.index(store)


@pytest.mark.parametrize("skill", SKILLS)
def test_step_7_fills_in_the_spec_check_line(skill):
    assert "Spec check:" in step(skill, 7)


@pytest.mark.parametrize("skill", SKILLS)
def test_the_pr_template_has_a_spec_check_line_under_review(skill):
    text = (ROOT / "config" / "skills" / skill / "assets" / "pr-body-template.md").read_text()
    review = text.split("\n## Review\n", 1)[1]
    assert re.search(r"^Spec check: *\S", review, re.MULTILINE)
