"""Invariants of the repo itself: the design philosophies, checked."""

import json
import re

import pytest

from tests.conftest import ROOT

SKILLS = sorted(p for p in (ROOT / "config" / "skills").iterdir() if p.is_dir())
HOSTS = sorted((ROOT / "hosts").glob("*.json"))
PERSONAL = re.compile(r"/home/|/Users/|/omc-dev|mfracker", re.I)


def front_matter(skill):
    text = (skill / "SKILL.md").read_text()
    match = re.match(r"---\n(.*?)\n---\n", text, re.S)
    assert match, f"{skill.name}: SKILL.md has no front matter"
    return dict(line.split(": ", 1) for line in match.group(1).splitlines() if ": " in line)


@pytest.mark.parametrize("skill", SKILLS, ids=lambda p: p.name)
def test_skill_is_well_formed(skill):
    meta = front_matter(skill)
    assert meta["name"] == skill.name
    assert 50 < len(meta["description"]) <= 1024


@pytest.mark.parametrize("skill", SKILLS, ids=lambda p: p.name)
def test_skills_are_zero_dependency(skill):
    """DP2: a skill is markdown. No scripts, manifests or installs to carry along."""
    files = [p for p in skill.rglob("*") if p.is_file()]
    assert all(p.suffix == ".md" for p in files), [p.name for p in files if p.suffix != ".md"]
    text = "\n".join(p.read_text() for p in files)
    assert not re.search(r"\b(pip|pip3|npm|npx|brew|apt|cargo) install\b", text)
    assert "scripts/" not in text


@pytest.mark.parametrize("skill", SKILLS, ids=lambda p: p.name)
def test_skills_name_no_machine_paths(skill):
    for path in skill.rglob("*.md"):
        assert not PERSONAL.search(path.read_text()), path


@pytest.mark.parametrize("host", HOSTS, ids=lambda p: p.stem)
def test_host_profile_resolves(host):
    data = json.loads(host.read_text())
    assert data["name"] == host.stem
    tracker = ROOT / "config" / "skills" / "issue-lifecycle" / "references"
    assert (tracker / f"{data['defaultTracker']}.md").is_file()
    for skill in data["skills"]:
        assert (ROOT / "config" / "skills" / skill / "SKILL.md").is_file()
    for hook in data["hooks"]:
        assert (ROOT / "config" / "hooks" / hook).is_file()
    assert "oh-my-claudecode@omc" in data["plugins"]


def test_hosts_differ_only_where_machines_differ():
    """DP1: a second machine is one JSON file, and it shares everything else."""
    first, *rest = (json.loads(h.read_text()) for h in HOSTS)
    for other in rest:
        assert {k for k in first if first[k] != other[k]} <= {"name", "defaultTracker"}


def test_every_skill_is_on_some_host_and_every_hook_is_wired():
    on_hosts = {s for h in HOSTS for s in json.loads(h.read_text())["skills"]}
    assert on_hosts == {p.name for p in SKILLS}
    fragment = (ROOT / "config" / "settings.fragment.json").read_text()
    for hook in (ROOT / "config" / "hooks").glob("*.py"):
        assert f"/hooks/{hook.name}" in fragment


def test_global_rules_stay_short_and_name_only_real_skills():
    text = (ROOT / "config" / "CLAUDE.global.md").read_text()
    assert len(text.splitlines()) < 60
    assert not PERSONAL.search(text)
    for skill in re.findall(r"`([a-z-]+)` skill", text):
        assert (ROOT / "config" / "skills" / skill).is_dir(), skill


def test_nothing_personal_is_committed():
    for path in ROOT.rglob("*"):
        if path.is_file() and ".git" not in path.parts and ".venv" not in path.parts and path.suffix in {".md", ".json", ".py", ".toml"}:
            if path.name == "test_repo.py":
                continue
            assert not re.search(r"/home/\w|mfracker", path.read_text()), path
