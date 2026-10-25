"""Invariants of the repo itself: the design philosophies, checked."""

import ast
import json
import re
import sys

import pytest

from tests.conftest import ROOT


def hook_trackers():
    """The hook's tracker-to-skill map, read without importing it (no bytecode cache lands in
    config/hooks)."""
    tree = ast.parse((ROOT / "config" / "hooks" / "host_default.py").read_text())
    for node in tree.body:
        if isinstance(node, ast.Assign) and getattr(node.targets[0], "id", None) == "TRACKERS":
            return ast.literal_eval(node.value)
    raise AssertionError("host_default.py has no TRACKERS map")


TRACKERS = hook_trackers()

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


def skill_files(skill):
    return [p for p in skill.rglob("*") if p.is_file() and "__pycache__" not in p.parts]


@pytest.mark.parametrize("skill", SKILLS, ids=lambda p: p.name)
def test_skills_are_zero_dependency(skill):
    """DP2: no third-party packages and nothing to install. A skill is markdown, plus
    standard-library Python under scripts/ and JSON or text assets; it needs only python3."""
    for path in skill_files(skill):
        rel = path.relative_to(skill)
        if rel.parts[0] == "scripts":
            assert path.suffix == ".py" and len(rel.parts) == 2, rel
        else:
            assert path.suffix in {".md", ".json", ".txt"}, rel
            assert not path.stat().st_mode & 0o111, f"{rel} is executable"
    text = "\n".join(p.read_text() for p in skill_files(skill))
    assert not re.search(r"\b(pip|pip3|npm|npx|brew|apt|apt-get|cargo) install\b", text)


@pytest.mark.parametrize("skill", SKILLS, ids=lambda p: p.name)
def test_skill_scripts_import_only_the_standard_library(skill):
    scripts = sorted((skill / "scripts").glob("*.py"))
    siblings = {p.stem for p in scripts}
    for script in scripts:
        for node in ast.walk(ast.parse(script.read_text())):
            if isinstance(node, ast.Import):
                names = [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom):
                assert node.level == 0, f"{script.name}: relative import"
                names = [node.module]
            else:
                continue
            for name in names:
                top = name.split(".")[0]
                assert top in sys.stdlib_module_names or top in siblings, f"{script.name}: {name}"


@pytest.mark.parametrize("skill", SKILLS, ids=lambda p: p.name)
def test_skills_are_self_contained(skill):
    """A host may deploy any subset of skills, so a skill never reaches into another one,
    and every bundled file its SKILL.md names is there."""
    others = {p.name for p in SKILLS} - {skill.name}
    for path in skill_files(skill):
        text = path.read_text()
        for other in others:
            assert f"../{other}" not in text, f"{path.relative_to(skill)} reaches into {other}"
        assert "<skills-dir>" not in text
    text = (skill / "SKILL.md").read_text()
    for ref in re.findall(r"(?<![\w/.-])((?:references|scripts|assets|examples)/[\w.-]+)", text):
        assert (skill / ref).is_file(), f"{skill.name}/SKILL.md names missing {ref}"


@pytest.mark.parametrize("skill", SKILLS, ids=lambda p: p.name)
def test_skills_name_no_machine_paths(skill):
    for path in skill_files(skill):
        assert not PERSONAL.search(path.read_text()), path


@pytest.mark.parametrize("host", HOSTS, ids=lambda p: p.stem)
def test_host_profile_resolves(host):
    data = json.loads(host.read_text())
    assert data["name"] == host.stem
    skill = TRACKERS[data["defaultTracker"]]
    assert skill in data["skills"]
    for skill in data["skills"]:
        assert (ROOT / "config" / "skills" / skill / "SKILL.md").is_file()
    for hook in data["hooks"]:
        assert (ROOT / "config" / "hooks" / hook).is_file()
    assert "oh-my-claudecode@omc" in data["plugins"]


def test_every_tracker_maps_to_a_shipped_lifecycle_skill():
    for skill in TRACKERS.values():
        assert (ROOT / "config" / "skills" / skill / "SKILL.md").is_file(), skill


def test_gitea_ships_the_same_script_as_github():
    """The copy keeps each skill self-contained; this keeps the two copies from drifting."""
    skills = ROOT / "config" / "skills"
    github = skills / "github-issue-lifecycle" / "scripts" / "issue_lifecycle.py"
    gitea = skills / "gitea-issue-lifecycle" / "scripts" / "issue_lifecycle.py"
    assert github.read_bytes() == gitea.read_bytes()


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
    named = re.findall(r"`([a-z:-]+)`", text)
    for skill in [n for n in named if n.endswith("-lifecycle") or n.endswith("-handoff")]:
        assert (ROOT / "config" / "skills" / skill).is_dir(), skill
    for skill in TRACKERS.values():
        assert f"`{skill}`" in text
    assert "writing-docs" not in text


def test_workflow_plans_the_tests_before_the_spec():
    text = (ROOT / "config" / "CLAUDE.global.md").read_text()
    steps = re.findall(r"^\d+\. (.*)$", text, re.MULTILINE)
    plan = next((i for i, s in enumerate(steps) if s.startswith("Test plan:") and "oh-my-claudecode:test-engineer" in s), None)
    spec = next((i for i, s in enumerate(steps) if s.startswith("Spec:")), None)
    assert plan is not None and spec is not None, "workflow needs a Test plan step and a Spec step"
    assert plan < spec
    assert "after the test plan" in steps[spec]


def test_nothing_personal_is_committed():
    for path in ROOT.rglob("*"):
        if path.is_file() and ".git" not in path.parts and ".venv" not in path.parts and path.suffix in {".md", ".json", ".py", ".toml"}:
            if path.name == "test_repo.py":
                continue
            assert not re.search(r"/home/\w|mfracker", path.read_text()), path
