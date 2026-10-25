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
    assert len(text.splitlines()) < 80
    assert not PERSONAL.search(text)
    named = re.findall(r"`([a-z:-]+)`", text)
    for skill in [n for n in named if n.endswith("-lifecycle") or n.endswith("-handoff")]:
        assert (ROOT / "config" / "skills" / skill).is_dir(), skill
    for skill in TRACKERS.values():
        assert f"`{skill}`" in text
    assert "writing-docs" not in text


def test_global_rules_stand_aside_when_ralph_or_autopilot_opens_the_session():
    text = (ROOT / "config" / "CLAUDE.global.md").read_text()
    head = text.split("### Workflow, in order")[0]
    assert "first prompt" in head and "`ralph`" in head and "`autopilot`" in head
    assert "ignore" in head.lower()


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


# A pinned snapshot of OMC 5.7.13's agents and of the skills CLAUDE.global.md may name.
# A human bumps them when OMC changes; nothing derives them from the installed plugin.
OMC_AGENTS = [
    "analyst", "architect", "code-reviewer", "code-simplifier", "critic", "debugger", "designer",
    "document-specialist", "executor", "explore", "git-master", "planner", "qa-tester", "scientist",
    "security-reviewer", "test-engineer", "tracer", "verifier", "writer",
]
OMC_SKILLS = [
    "deep-interview", "ralplan", "drydock", "execute", "tdd", "team", "ralph", "autopilot", "review",
    "verify", "pr", "plan", "research", "cancel", "minimal-prose-discipline", "agent-doc-discipline",
]
# Reached by a skill the pipeline calls, so they need no bullet of their own.
REACHED_BY_SKILL = {"test-engineer", "planner", "architect", "critic", "executor", "explore"}
TRIGGER = re.compile(r"\b(when|if|touches|before|after)\b")
LIFECYCLE_SKILLS = ["github-issue-lifecycle", "gitea-issue-lifecycle", "jira-ticket-lifecycle"]


def global_text():
    return (ROOT / "config" / "CLAUDE.global.md").read_text()


def section(heading):
    """The lines under a `###` heading containing `heading`, up to the next heading."""
    lines = global_text().splitlines()
    start = next((i for i, l in enumerate(lines) if l.startswith("### ") and heading in l), None)
    assert start is not None, f"no section {heading!r}"
    body = []
    for line in lines[start + 1:]:
        if line.startswith("#"):
            break
        body.append(line)
    return body


def pathway_bullets():
    return [l for h in ("Agents by condition", "Variants by request type") for l in section(h) if l.startswith("- ")]


def bullet_for(agent, bullets):
    return [b for b in bullets if re.search(rf"`oh-my-claudecode:{agent}`", b)]


def test_every_omc_agent_has_a_pathway():
    bullets = pathway_bullets()
    for agent in OMC_AGENTS:
        if agent in REACHED_BY_SKILL:
            continue
        found = bullet_for(agent, bullets)
        assert found, f"{agent} has no bullet"
        assert TRIGGER.search(found[0]), f"{agent}'s bullet has no trigger word"
        others = [a for a in OMC_AGENTS if a != agent and bullet_for(a, [found[0]])]
        assert not others, f"{agent}'s bullet also names {others}"


def test_agent_references_are_real():
    known = set(OMC_AGENTS) | set(OMC_SKILLS)
    for name in re.findall(r"oh-my-claudecode:([a-z][a-z-]*[a-z])", global_text()):
        assert name in known, name


def test_variant_pipelines_name_their_agents():
    body = section("Variants by request type")
    selector = [l for l in body if l and not l.startswith("- ")]
    assert selector and all(t in selector[0] for t in ("Bug", "UI", "Docs", "Research"))
    bullets = [l for l in body if l.startswith("- ")]
    for kind, agents in {"Bug": ["debugger", "tracer"], "UI": ["designer"], "Docs": ["writer"], "Research": ["scientist"]}.items():
        mine = [b for b in bullets if b.startswith(f"- {kind}")]
        for agent in agents:
            assert bullet_for(agent, mine), f"{kind} variant lacks {agent}"


def test_conditional_triggers_are_concrete():
    bullets = section("Agents by condition")
    security = bullet_for("security-reviewer", bullets)[0].lower()
    assert all(w in security for w in ("auth", "input", "secret"))
    assert "300" in bullet_for("code-simplifier", bullets)[0]
    assert "exceeds 300 changed lines" in bullet_for("code-reviewer", bullets)[0]
    assert "does not count against the one-pass rule" in security
    team = next(b for b in bullets if "`team`" in b)
    assert "skip verifier" in team and "security-reviewer" in team and "code-reviewer" in team
    bug = next(b for b in section("Variants by request type") if b.startswith("- Bug") and "debugger" in b)
    assert "step 2 and Approval unchanged" in bug


def test_step7_cancels_team_and_ralph_before_push():
    steps = re.findall(r"^(\d+)\. (.*)$", global_text(), re.MULTILINE)
    assert [int(n) for n, _ in steps] == list(range(1, len(steps) + 1))
    step7 = steps[6][1]
    assert "When step 5 used `team` or `ralph`, run `/oh-my-claudecode:cancel` before pushing: OMC blocks every push while those modes are active." in step7


def test_global_md_has_no_cfg_markers():
    assert "CLAUDE-CONFIG:" not in global_text()


def test_writer_owns_human_read_prose():
    lines = global_text().splitlines()
    start = next(i for i, l in enumerate(lines) if l.startswith("Prose"))
    block = []
    for line in lines[start:]:
        if not line.strip():
            break
        block.append(line)

    def owner(token):
        return [l for l in block if token in l]

    writer = owner("`oh-my-claudecode:writer`")
    assert writer and "git-master" not in writer[0]
    assert all(w in writer[0] for w in ("docs", "comments", "issue"))
    assert "after tests are green and before step 6, after any history cleanup and simplification" in writer[0]
    git = owner("`oh-my-claudecode:git-master`")
    assert git and "commit" in git[0] and "writer" not in git[0]
    pr = owner("`/oh-my-claudecode:pr`")
    assert pr and "PR body" in pr[0]
    docs = owner("agent-doc-discipline")
    assert docs and "agents consume" in docs[0]
    assert any("error" in l.lower() for l in block)
    assert any("chat" in l and "minimal-prose-discipline" in l for l in block)
    for skill in LIFECYCLE_SKILLS:
        text = (ROOT / "config" / "skills" / skill / "SKILL.md").read_text()
        line = next(l for l in text.splitlines() if "Prose for people" in l)
        assert "Prose, by owner" in line, skill
        for token in ("oh-my-claudecode:writer", "oh-my-claudecode:git-master", "/oh-my-claudecode:pr"):
            assert token not in line, f"{skill}: owners restated: {token}"


def test_spikes_rule_is_stated():
    line = next((l for l in global_text().splitlines() if l.startswith("Spikes:")), "")
    for needle in ("scratch", "--setting-sources project", "spec", "never in the repo"):
        assert needle in line, needle


def test_self_review_rule_is_stated():
    line = next((l for l in global_text().splitlines() if l.startswith("Self-review:")), "")
    for needle in ("before any review agent", "done", "why", "not per ralplan round", "Research variant"):
        assert needle in line, needle


def test_adr_records_the_pathway_departure():
    adrs = sorted((ROOT / "docs" / "adr").glob("0004-*.md"))
    assert len(adrs) == 1
    text = adrs[0].read_text()
    assert "Status" in text and "#7" in text and "pathway" in text.lower()
    for agent in OMC_AGENTS:
        assert re.search(rf"\b{re.escape(agent)}\b", text), agent
