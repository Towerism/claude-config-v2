"""The shell blocks in SKILL.md, run as written: the claim block against a fake gh, and the
temp-folder line."""

import os
import re
import subprocess
from pathlib import Path

import pytest

from tests.skills.github_issue_lifecycle.conftest import SKILL_DIR

SKILL = (SKILL_DIR / "SKILL.md").read_text()
LABELS = [
    "in progress",
    "draft",
    "approved",
    "hotfix",
]


def claim_block():
    blocks = re.findall(r"```bash\n(.*?)```", SKILL, re.DOTALL)
    return next(b for b in blocks if 'gh label create "in progress"' in b)


def test_claim_is_idempotent_and_assigns(gh):
    gh.labels_exist()
    for _ in range(2):
        result = gh.run_bash("set -e\n" + claim_block())
        assert result.returncode == 0, result.stderr
    calls = gh.calls()
    requested = {c[2] for c in calls if c[:2] == ["label", "create"]}
    assert requested == set(LABELS)
    claim = ["issue", "edit", "42", "--add-assignee", "@me", "--add-label", "in progress"]
    assert calls.count(claim) == 2


def test_claim_on_a_fresh_repo(gh):
    result = gh.run_bash("set -e\n" + claim_block())
    assert result.returncode == 0
    assert sum(1 for c in gh.calls() if c[:2] == ["label", "create"]) == len(LABELS)


def temp_line():
    return next(line.strip() for line in SKILL.splitlines() if "mktemp" in line)


@pytest.mark.parametrize("job_dir", [False, True])
def test_the_temp_folder_line_never_writes_into_the_working_tree(tmp_path, job_dir):
    cwd, tmpdir, job = tmp_path / "repo", tmp_path / "sys-tmp", tmp_path / "job"
    for d in (cwd, tmpdir, job / "tmp"):
        d.mkdir(parents=True)
    env = {k: v for k, v in os.environ.items() if k != "CLAUDE_JOB_DIR"}
    env["TMPDIR"] = str(tmpdir)
    if job_dir:
        env["CLAUDE_JOB_DIR"] = str(job)
    script = temp_line() + '\nprintf %s "$tmp"'
    out = subprocess.run(["bash", "-c", script], cwd=cwd, env=env, capture_output=True, text=True, check=False)
    made = Path(out.stdout)
    assert made.is_dir() and not list(cwd.iterdir())
    assert made.parent == (job / "tmp" if job_dir else tmpdir)
