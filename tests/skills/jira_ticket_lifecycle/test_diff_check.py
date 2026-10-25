"""diff-check must answer exactly as github-issue-lifecycle's does on the same repos, since
both apply the same rule; a Jira key in code is never a requirement ID."""

import json
import subprocess
import sys

import pytest

from tests.skills.jira_ticket_lifecycle.conftest import SKILL_DIR, make_repo

GH_SCRIPT = SKILL_DIR.parent / "github-issue-lifecycle" / "scripts" / "issue_lifecycle.py"

CLEAN = {"src/export.py": "def write_header():\n    return 'a,b'\n"}
LIVING_BASE = {
    "docs/design.md": "The export follows FR-23 and keeps the header row.\n",
    "config/settings.json": "{}\n",
    "config/SPEC.md": "- FR-15a: the fragment renders the home path.\n",
    "docs/history/old.md": "Frozen copy: AC-9 applied once.\n",
    "notes/archive/2025.md": "Archived: EC-4.\n",
}
CITING_CODE = {
    "src/export.py": "# FR-23 keeps the header row\nLIMIT = 'FR-15a'\nOLD = 'AC-9'\nX = 'NFR-4'\n",
    "tests/test_export.py": "def test_fr23_rejects_empty():\n    pass\n",
    "src/legacy.py": "# EC-4 from the archive\n",
}
SCENARIOS = {
    "id-and-spec-file": (
        {
            "tests/test_x.py": "def test_ac3_rejects_empty():\n    pass\n",
            "docs/feature-spec.md": "# Spec\n",
        },
        None,
    ),
    "clean": (CLEAN, None),
    "skill-spec-and-lookalikes": (
        {
            ".claude/skills/foo/SKILL.md": "---\nname: foo\n---\n",
            ".claude/skills/foo/SPEC.md": "# Spec\n- FR-1: x\n",
            "docs/inspection.md": "# Inspection\n",
            "e2e/login.spec.ts": "test('login', () => {})\n",
        },
        None,
    ),
    "infra-names": (
        {"infra/main.tf": 'resource "aws_instance" "ec2 box" {}\n', "src/os2.py": "x = 'os2'\n"},
        None,
    ),
    "living-docs": (CITING_CODE, LIVING_BASE),
    "doc-added-on-branch": (
        {**CITING_CODE, "docs/more.md": "See NFR4, ac_9 and ec-004.\n"},
        LIVING_BASE,
    ),
    "spec-files-beside-subjects": (
        {
            "config/SPEC.md": "# Spec\n",
            "tools/foo/SPEC.md": "# Spec\n",
            "tools/foo/run.py": "print('x')\n",
            "skills/bar/SKILL.md": "---\n",
            "skills/bar/SPEC.md": "# Spec\n",
            "docs/feature-spec.md": "# Spec\n",
            "specs/login.md": "# Spec\n",
        },
        {"config/settings.json": "{}\n", "docs/guide.md": "# Guide\n"},
    ),
    "subfolder-beside-a-spec": (
        {"docs/feature-spec.md": "# Spec\n"},
        {"docs/guide.md": "# Guide\n", "docs/img/diagram.svg": "<svg/>\n"},
    ),
    "line-separator": (
        {"src/a.py": "# FR-7 keeps the order\n"},
        {"docs/notes.md": "Intro then FR-7 applies.\n"},
    ),
}


def diff_check(script, repo):
    r = subprocess.run(
        [
            sys.executable,
            "-I",
            str(script),
            "diff-check",
            "--base",
            "main",
            "--repo-dir",
            str(repo),
            "--json",
        ],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    return r.returncode, json.loads(r.stdout)["problems"]


@pytest.mark.parametrize("name", sorted(SCENARIOS))
def test_reports_exactly_what_the_github_skill_reports(env, tmp_path, name):
    branch, base = SCENARIOS[name]
    repo = make_repo(tmp_path, branch, base_files=base)
    r = env.run("diff-check", "--base", "main", "--repo-dir", repo, "--json")
    assert (r.returncode, json.loads(r.stdout)["problems"]) == diff_check(GH_SCRIPT, repo)


def test_the_living_docs_case_reports_the_undefined_ids(env, tmp_path):
    repo = make_repo(tmp_path, CITING_CODE, base_files=LIVING_BASE)
    r = env.run("diff-check", "--base", "main", "--repo-dir", repo, "--json")
    ids = sorted(p["detail"].rsplit(": ", 1)[1] for p in json.loads(r.stdout)["problems"])
    assert ids == ["AC-9", "EC-4", "NFR-4"]


def test_a_jira_key_in_code_is_not_reported(env, tmp_path):
    repo = make_repo(tmp_path, {"src/a.py": "# PAY-142 export timeout\nTICKET = 'PAY-142'\n"})
    r = env.run("diff-check", "--base", "main", "--repo-dir", repo)
    assert r.returncode == 0, r.stdout


def test_a_bad_base_is_a_usage_error(env, tmp_path):
    repo = make_repo(tmp_path, CLEAN)
    assert env.run("diff-check", "--base", "nope", "--repo-dir", repo).returncode == 2
