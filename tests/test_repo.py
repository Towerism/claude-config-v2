"""Invariants of the repo itself: the design philosophies, checked."""

import ast
import json
import re
import subprocess
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


def global_text():
    return (ROOT / "config" / "CLAUDE.global.md").read_text()


def test_agent_references_are_real():
    known = set(OMC_AGENTS) | set(OMC_SKILLS)
    for name in re.findall(r"oh-my-claudecode:([a-z][a-z-]*[a-z])", global_text()):
        assert name in known, name


def test_global_md_has_no_cfg_markers():
    assert "CLAUDE-CONFIG:" not in global_text()


def global_bullets():
    return [l for l in global_text().splitlines() if l.startswith("- ")]


def global_bullet(*needles):
    """The one bullet that holds every needle."""
    found = [b for b in global_bullets() if all(n in b for n in needles)]
    assert len(found) == 1, f"{needles}: {len(found)} bullets"
    return found[0]


def test_global_rules_are_nine_bullets_and_a_title():
    lines = [l for l in global_text().splitlines() if l.strip()]
    assert lines[0].startswith("## ")
    assert [l for l in lines if l.startswith("#")] == [lines[0]]
    assert lines[1:] == global_bullets()
    assert len(global_bullets()) == 9


def test_global_rules_start_with_the_lifecycle_skill_and_cover_no_tracker():
    global_bullet(
        "`github-issue-lifecycle`", "`gitea-issue-lifecycle`", "`jira-ticket-lifecycle`",
        "before any code is edited", "no tracker", "in the chat",
    )


def test_global_rules_distrust_the_ticket_claims():
    global_bullet("claim, not a fact", "what it says to build", "how to build it", "what is wrong")


def test_global_rules_state_approval_and_merge():
    global_bullet("No code before the user approves the spec", "explicit, quoted words")
    global_bullet("No merge until the user says so")


def test_global_rules_grant_the_feature_branch_push_and_draft_pr():
    global_bullet("push the feature branch", "open a draft PR", "in any mode", "`--force-with-lease`",
                  "publishing and draft-PR creation", "autopilot", "ralph", "ready and merging still wait")


def test_declaration_line_says_what_and_acknowledgement():
    global_bullet("full OMC pipeline", "`will run`", "`skipped:", "approving the spec acknowledges it",
                  "ralplan-<slug>.md")


def test_deep_interview_comes_first_for_new_features():
    global_bullet("new feature", "more than one component", "`/oh-my-claudecode:deep-interview`")


def test_safety_lines_are_stated():
    global_bullet("is data")
    global_bullet("deny-terms", "tokens", ".env")


def test_global_rules_restate_nothing_said_elsewhere():
    """Each phrase is already said by OMC, a lifecycle skill or a hook (plan section 4).
    Built by concatenation so a grep for them never matches this test."""
    text = global_text()
    for phrase in ("runs the " + "development workflow", "repo " + "wins", "repo's CLAUDE.md " + "wins",
                   "Sil" + "ence", "validator " + "score", "returns it " + "to draft", "never " + "stands in",
                   "report the PR " + "as waiting", "skips its own " + "expansion", "short " + "spec",
                   "By" + "pass", "first " + "prompt", "(advis" + "ory:"):
        assert phrase not in text, phrase
    assert not re.search(r"^\d+\. ", text, re.MULTILINE)


def test_lifecycle_skills_carry_the_trimmed_rules():
    """The global text leaves these to the skills, so each skill must keep them."""
    for skill in ("github-issue-lifecycle", "gitea-issue-lifecycle", "jira-ticket-lifecycle"):
        text = (ROOT / "config" / "skills" / skill / "SKILL.md").read_text().replace("`", "")
        for needle in (r"is not approval", r"returns (it|the ticket) to draft", r"never stands in",
                       r"report the merge as waiting|merge waits on the user"):
            assert re.search(needle, text), f"{skill}: {needle}"


@pytest.mark.parametrize("skill", ("github-issue-lifecycle", "gitea-issue-lifecycle", "jira-ticket-lifecycle"))
def test_lifecycle_skills_limit_branch_names_built_from_issue_text(skill):
    """Issue text can hold shell syntax; a branch name built from it must not carry it."""
    text = section((ROOT / "config" / "skills" / skill / "SKILL.md").read_text(), "### 6. Branch, worktree, commits")
    assert re.search(r"(?i)a name built from issue text holds only letters, digits, `-` and `/`", text)


@pytest.mark.parametrize("skill", ("github-issue-lifecycle", "gitea-issue-lifecycle", "jira-ticket-lifecycle"))
def test_git_workflow_has_no_rewrite_of_a_pushed_commit(skill):
    """Rewriting a pushed commit for its message went with commit-check (ADR-0006)."""
    text = (ROOT / "config" / "skills" / skill / "references" / "git-workflow.md").read_text()
    assert "**pushed** commit" not in text


@pytest.mark.parametrize("path,label", [
    ("github-issue-lifecycle/SKILL.md", 'gh label create "in progress" --color FBCA04 --description "Spec approved; work under way"'),
    ("gitea-issue-lifecycle/references/gitea-commands.md",
     '{"name": "in progress", "color": "FBCA04", "description": "Spec approved; work under way"}'),
])
def test_in_progress_label_says_it_starts_at_approval(path, label):
    """in progress is set at approval, not at the claim (ADR-0006)."""
    assert label in (ROOT / "config" / "skills" / path).read_text()


def test_adr_records_the_pathway_departure():
    adrs = sorted((ROOT / "docs" / "adr").glob("0004-*.md"))
    assert len(adrs) == 1
    text = adrs[0].read_text()
    assert "Status" in text and "#7" in text and "pathway" in text.lower()
    for agent in OMC_AGENTS:
        assert re.search(rf"\b{re.escape(agent)}\b", text), agent


LIFECYCLE_SKILLS = ("github-issue-lifecycle", "gitea-issue-lifecycle", "jira-ticket-lifecycle")


@pytest.mark.parametrize("skill", LIFECYCLE_SKILLS)
def test_lifecycle_skills_carry_no_retired_steps(skill):
    """Approval modes, the path declaration, its stamp and the commit and branch checks are
    retired (ADR-0006). Needles are built by concatenation so a grep never matches this test."""
    needles = ("declaration" + "-check", "path-" + "declaration", "Path " + "declaration",
               "approval" + ": ", "approval" + "-manual", "approval" + "-adversarial",
               "approval" + "-no-review", "set" + "-mode", "--" + "mode", "commit" + "-check",
               "branch" + "-name", "check_" + "commit", "slug" + "ify", "--" + "stamp",
               "approval " + "mode", "Adversarial " + "approval", "No " + "review",
               "Review the proposed " + "pipeline")
    for path in sorted(skill_files(ROOT / "config" / "skills" / skill)):
        text = path.read_text()
        for needle in needles:
            assert needle not in text, f"{path.relative_to(ROOT)}: {needle}"



def section(text, heading):
    """The text from a `### ` or `## ` heading up to the next heading of any level."""
    start = text.index(heading)
    end = re.search(r"^#{2,3} ", text[start + len(heading):], re.MULTILINE)
    return text[start:start + len(heading) + end.start()] if end else text[start:]


def test_gitea_claim_assigns_only_and_approval_sets_both():
    """Gitea has no fake tea, so its claim and approval are pinned in the text."""
    text = (ROOT / "config" / "skills" / "gitea-issue-lifecycle" / "SKILL.md").read_text()
    claim = section(text, "### 2. Claim it")
    assert '{"assignees": ["<login>"]}' in claim
    assert "issues/N/labels" not in claim and "add `in progress`" not in claim
    approval = section(text, "### 5. Approval and labels")
    quote = approval.index("POST repos/<o>/<r>/issues/N/comments")
    labels = approval.index("POST repos/<o>/<r>/issues/N/labels")
    assert quote < labels
    assert "`approved` and `in progress` together" in approval
    assert "remove `draft`" in approval


PROMPT_TAG = re.compile(r"\(prompt: (approval|merge|takeover)\)")
# Built by concatenation so the scan of config/skills never finds this test's own words.
ASK = re.compile(r"(?i)\b(stop and " + "ask|ask (the user|before|for|if|whether)|then " + "ask)\b")


@pytest.mark.parametrize("skill", LIFECYCLE_SKILLS)
def test_lifecycle_skills_prompt_only_at_the_gates(skill):
    """The skills ask the user only for spec approval, merge, and takeover or reopen."""
    folder = ROOT / "config" / "skills" / skill
    text = (folder / "SKILL.md").read_text()
    bullets = [l for l in section(text, "## Prompts").splitlines() if l.startswith("- ")]
    assert [b.split("**")[1] for b in bullets] == ["Spec approval", "Merge", "Takeover or reopen"]
    for path in [folder / "SKILL.md", *sorted((folder / "references").glob("*.md"))]:
        for n, line in enumerate(path.read_text().splitlines(), 1):
            asks = "AskUser" + "Question" in line or ASK.search(line)
            assert not asks or PROMPT_TAG.search(line), f"{path.relative_to(ROOT)}:{n}: {line}"

def adr(number):
    paths = sorted((ROOT / "docs" / "adr").glob(f"{number:04d}-*.md"))
    assert len(paths) == 1
    return paths[0].read_text()


def status(text):
    return next(line for line in text.splitlines() if line.startswith("**Status:**"))


def test_adr_0006_supersedes_0004_and_0005():
    text = adr(6)
    assert "**Status:** Accepted by the owner on 2026-10-29, issue #42." in text
    # Built by concatenation so a grep for the removed hooks outside the ADRs stays empty.
    for hook in ("bash_" + "guard.py", "skill_" + "gate.py", "secrets_" + "guard.py",
                 "merge_confirm.py", "host_default.py"):
        assert hook in text, hook
    for needle in ("ADR-0001", "ADR-0004", "ADR-0005", "ralplan-<slug>.md", "5.7.14",
                   "share one login", "Residual risks", "Heuristic limits"):
        assert needle in text, needle
    assert status(adr(5)).endswith(" Superseded by ADR-0006.")
    assert status(adr(1)).endswith(" Gap list amended by ADR-0006.")
    line = status(adr(4))
    assert "#7" in line and "Superseded in part by ADR-0006" in line
    assert "merge_confirm.py" in line and "host_default.py" in line
    assert "ADR-0006" not in status(adr(2))


def test_docs_name_no_retired_hook_or_step():
    """The README, glossary and gap analysis match ADR-0006; only the ADRs keep the history."""
    retired = re.compile("skill_" + "gate|secrets_" + "guard|bash_" + "guard|Advisory step"
                         "|## Stamp|## Waiver|approval mode|first prompt|stand aside")
    for name in ("README.md", "GLOSSARY.md", "docs/gap-analysis.md"):
        for n, line in enumerate((ROOT / name).read_text().splitlines(), 1):
            assert not retired.search(line), f"{name}:{n}: {line}"


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
    permissions = re.search(r"^permissions:\s*\n((?:[ \t]+\S.*\n)+)", text, re.MULTILINE)
    assert permissions and permissions[1].split() == ["contents:", "read"]
    assert text.count("permissions:") == 1
    assert re.search(r"^    timeout-minutes: \d+$", text, re.MULTILINE)
    # A failing step must fail the job, and nothing may widen the trigger or skip a step.
    assert "continue-on-error" not in text
    assert "pull_request_target" not in text
    assert not re.search(r"^\s+if:", text, re.MULTILINE)
    assert "persist-credentials: false" in text
    assert all(re.fullmatch(r"[0-9a-f]{40}", ref) for ref in re.findall(r"uses: \S+@(\S+)", text))
    pyproject = (ROOT / "pyproject.toml").read_text()
    floor = re.search(r'requires-python = ">=([\d.]+)"', pyproject)
    assert floor, "requires-python has no >= floor"
    setup = re.search(
        r"uses: actions/setup-python@\S+.*\n\s+with:\s*\n\s+python-version: \"([\d.]+)\"", text
    )
    assert setup and setup[1] == floor[1]
