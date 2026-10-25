"""Invariants of the repo itself: the design philosophies, checked."""

import ast
import json
import re
import subprocess
import sys

import pytest

from tests.conftest import ROOT
from tests.skills.declaration_cases import script_constant


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
PERSONAL = re.compile(r"/home/|/Users/|/omc-dev|mfracker", re.IGNORECASE)


def front_matter(skill):
    text = (skill / "SKILL.md").read_text()
    match = re.match(r"---\n(.*?)\n---\n", text, re.DOTALL)
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
    for skill in [n for n in named if n.endswith(("-lifecycle", "-handoff"))]:
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
        if path.is_file() and ".git" not in path.parts and ".venv" not in path.parts and (path.suffix in {".md", ".json", ".py", ".toml", ".txt"} or path.name == "Makefile"):
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


def test_precedence_over_omc_is_stated_before_the_workflow():
    head = global_text().split("### Workflow, in order")[0]
    assert "override" in head and "lightest-weight path" in head
    assert "only the user can waive" in head.lower()
    assert "untagged" in head and "required" in head


GITHUB_SCRIPT = (
    ROOT / "config" / "skills" / "github-issue-lifecycle" / "scripts" / "issue_lifecycle.py"
)


def test_advisory_tags_match_the_scripts_advisory_set():
    tagged = re.findall(r"\(advisory: ([a-z-]+)\)", global_text())
    assert len(tagged) == len(set(tagged))
    assert set(tagged) == set(script_constant(GITHUB_SCRIPT, "ADVISORY_STEPS"))
    assert not set(tagged) & set(script_constant(GITHUB_SCRIPT, "REQUIRED_STEPS"))


def test_path_declaration_follows_step_2_and_asks_a_plain_question():
    text = global_text()
    start = text.index("2. Start:")
    end = text.index("3. Test plan:")
    block = text[start:end]
    assert "Path declaration" in block
    for needle in ("Review the proposed pipeline?", "yes/no", "lists no skipped steps", "wizard",
                   "waived", "never skipped", "spec approval"):
        assert needle in block, needle


def test_self_review_does_not_let_required_steps_be_skipped():
    line = next(l for l in global_text().splitlines() if l.startswith("Self-review:"))
    assert "otherwise say why not" not in line
    assert "required" in line and "advisory" in line
    assert "only when the user waived it" in line and "adds no value" not in line


LIFECYCLE_SKILLS = ("github-issue-lifecycle", "gitea-issue-lifecycle", "jira-ticket-lifecycle")


@pytest.mark.parametrize("skill", LIFECYCLE_SKILLS)
def test_lifecycle_skill_declares_the_path_after_the_claim_and_checks_it_twice(skill):
    text = (ROOT / "config" / "skills" / skill / "SKILL.md").read_text()
    claim = text.index("### 2. Claim it")
    declare = text.index("Path declaration")
    approval = text.index("### 5. Approval and labels")
    pr = text.index("### 7. Open the PR")
    settle = text.index("### 3. Settle the approval mode")
    assert claim < declare < settle
    section = text[declare:settle]
    for needle in ("Review the proposed pipeline?", "plain yes or no", "lists no skipped steps",
                   "verbatim", "<!-- path-declaration v1 -->", "<!-- /path-declaration -->",
                   "- run: ", "- waived: ", "- n/a: ", "variant:"):
        assert needle in section, needle
    checks = [m.start() for m in re.finditer("declaration-check", text)]
    assert not any(declare < c < approval for c in checks), "check belongs to approval and PR time"
    assert any(approval < c < pr for c in checks), "check before approved is set"
    assert any(c > pr for c in checks), "check at PR time"
    assert "--stamp" in text[pr:] and "--approval-mode" in text and "--spec" in text


@pytest.mark.parametrize("skill", LIFECYCLE_SKILLS)
def test_lifecycle_skill_checks_the_declaration_against_your_own_comments(skill):
    text = (ROOT / "config" / "skills" / skill / "SKILL.md").read_text()
    calls = [l for l in text.splitlines() if "declaration-check --" in l]
    assert calls
    for line in calls:
        assert '--author "$me"' in line, line
    assert "{url, body, author}" in text
    assert "authenticated login" in text
    section = text[text.index("### 2a. Path declaration"):text.index("### 3. Settle")]
    assert "`Path declaration answer: <question asked>`" in section
    conditional = script_constant(GITHUB_SCRIPT, "CONDITIONAL_STEPS")
    line = next(l for l in section.splitlines() if l.startswith("Step ids."))
    sentence = line[line.index("Conditional advisory steps"):]
    sentence = sentence[:sentence.index(".") + 1]
    assert set(re.findall(r"`([a-z-]+)`", sentence)) == set(conditional)


def test_adr_records_that_required_steps_bind_omc():
    adrs = sorted((ROOT / "docs" / "adr").glob("0005-*.md"))
    assert len(adrs) == 1
    text = adrs[0].read_text()
    assert "**Status:** Accepted by the owner on 2026-10-25, issue #14." in text
    assert "branch, issue and HEAD" in text
    limit = text[text.index("## Limit"):]
    for needle in ("gh pr new", "--repo", "tea api", "gh api", "unverifiable"):
        assert needle in limit, needle
    assert "ADR-0001" in text and "ADR-0004" in text
    assert "lightest-weight path" in text and "bash_guard" in text
    assert "writes the comments itself" in text


def suppresses_exception(node):
    """Whether `node` is contextlib.suppress(Exception) or suppress(Exception)."""
    if not isinstance(node, ast.Call):
        return False
    func = node.func
    if isinstance(func, ast.Attribute):
        module = func.value
        named = func.attr == "suppress" and isinstance(module, ast.Name) and module.id == "contextlib"
    else:
        named = isinstance(func, ast.Name) and func.id == "suppress"
    return named and any(isinstance(a, ast.Name) and a.id == "Exception" for a in node.args)


def test_only_hooks_suppress_every_exception():
    """The hook contract allows a blind catch; anywhere else it hides real bugs (#3)."""
    tracked = subprocess.run(
        ["git", "-C", str(ROOT), "ls-files", "*.py"], capture_output=True, text=True, check=True
    ).stdout.split()
    others = [path for path in tracked if not path.startswith("config/hooks/")]
    assert others
    for path in others:
        tree = ast.parse((ROOT / path).read_text())
        assert not any(suppresses_exception(node) for node in ast.walk(tree)), path


CI_WORKFLOW = ROOT / ".github" / "workflows" / "ci.yml"


def test_ci_workflow_runs_lint_and_tests_on_pull_requests():
    """A pull request fails when `make lint` or `make test` fails (#24). Read as text: no YAML dependency."""
    text = CI_WORKFLOW.read_text()
    assert re.search(r"^on:\s*\n\s+pull_request:", text, re.MULTILINE)
    assert not re.search(r"^\s+push:", text, re.MULTILINE)
    assert re.search(r"^\s+- run: make lint$", text, re.MULTILINE)
    assert re.search(r"^\s+- run: make test$", text, re.MULTILINE)
    assert re.search(r"^permissions:\s*\n\s+contents: read\s*$", text, re.MULTILINE)
    assert text.count("permissions:") == 1
    assert re.search(r"^\s+timeout-minutes: \d+$", text, re.MULTILINE)
    floor = re.search(r'requires-python = ">=([\d.]+)"', (ROOT / "pyproject.toml").read_text())[1]
    setup = re.search(r"uses: actions/setup-python@\S+.*\n\s+with:\s*\n\s+python-version: \"([\d.]+)\"", text)
    assert setup and setup[1] == floor
