"""The hooks: merge_confirm asks before a PR merge; host_default states the tracker; skill_gate adds review context."""

import json
import stat
import subprocess
import sys
import time

import pytest

from tests.conftest import ROOT

HOOKS = ROOT / "config" / "hooks"


def run(name, payload, env=None):
    stdin = payload if isinstance(payload, bytes) else json.dumps(payload).encode()
    done = subprocess.run(
        [sys.executable, "-I", str(HOOKS / name)],
        input=stdin, capture_output=True, env={"PATH": "/usr/bin:/bin", **(env or {})}, timeout=10,
    )
    assert done.returncode == 0 and done.stderr == b""
    return done.stdout.decode()


def bash(command):
    return {"hook_event_name": "PreToolUse", "tool_name": "Bash", "tool_input": {"command": command}}


@pytest.mark.parametrize("command", [
    "gh pr merge 42 --merge",
    "gh -R o/r pr merge 42",
    "cd x && gh pr merge --rebase",
    "gh api repos/o/r/pulls/3/merge -X PUT",
    "gh api graphql -f query='mutation { enablePullRequestAutoMerge(input: {}) { clientMutationId } }'",
    "tea api --login x -X POST repos/o/r/pulls/3/merge -d @m.json",
    "gh api graphql -f query='mutation { mergePullRequest(input: {}) { clientMutationId } }'",
])
def test_merges_ask(command):
    out = json.loads(run("merge_confirm.py", bash(command)))
    assert out["hookSpecificOutput"]["permissionDecision"] == "ask"


@pytest.mark.parametrize("command", [
    "gh pr view 42", "git merge main", "gh pr create --title merge", "ls",
])
def test_other_commands_pass_silently(command):
    assert run("merge_confirm.py", bash(command)) == ""


@pytest.mark.parametrize("payload", [b"", b"not json", b"[]", b'{"tool_input": {"command": 7}}'])
def test_merge_confirm_never_fails(payload):
    assert run("merge_confirm.py", payload) == ""


def test_merge_confirm_is_linear_on_dash_heavy_commands():
    run("merge_confirm.py", bash("gh pr " + "-a " * 20000))


@pytest.fixture
def machine(tmp_path):
    home = tmp_path / "claude"
    (home / "hooks").mkdir(parents=True)
    (home / "hooks" / "host_default.py").write_text((HOOKS / "host_default.py").read_text())
    (home / "claude-config").mkdir()
    (home / "claude-config" / "state.json").write_text(json.dumps({"host": "work", "defaultTracker": "jira"}))
    env = {"HOME": str(tmp_path), "XDG_CONFIG_HOME": str(tmp_path / "xdg")}
    return home, env, tmp_path


def start(home, env, event="SessionStart"):
    out = run_installed(home, {"hook_event_name": event}, env)
    return json.loads(out)["hookSpecificOutput"] if out else None


def run_installed(home, payload, env):
    done = subprocess.run(
        [sys.executable, "-I", str(home / "hooks" / "host_default.py")],
        input=json.dumps(payload).encode(), capture_output=True, env=env, timeout=10,
    )
    assert done.returncode == 0 and done.stderr == b""
    return done.stdout.decode()


def test_host_default_states_the_deployed_tracker(machine):
    home, env, _ = machine
    out = start(home, env)
    assert out["hookEventName"] == "SessionStart"
    text = out["additionalContext"]
    assert "Default issue tracker: jira. Use the jira-ticket-lifecycle skill" in text
    assert "Host profile: work." in text
    assert start(home, env, "SubagentStart")["hookEventName"] == "SubagentStart"


def test_local_file_wins_over_the_deploy(machine):
    home, env, tmp = machine
    (tmp / "xdg" / "claude-config").mkdir(parents=True)
    (tmp / "xdg" / "claude-config" / "local.json").write_text(json.dumps({"defaultTracker": "gitea"}))
    text = start(home, env)["additionalContext"]
    assert "tracker: gitea. Use the gitea-issue-lifecycle skill" in text


def test_github_maps_to_its_skill(machine):
    home, env, _ = machine
    (home / "claude-config" / "state.json").write_text(json.dumps({"defaultTracker": "github"}))
    text = start(home, env)["additionalContext"]
    assert text.startswith("Default issue tracker: github. Use the github-issue-lifecycle skill")


@pytest.mark.parametrize(
    "bad", ["gitlab", "github-issue-lifecycle", "Jira; rm -rf", "", 7, None, "a" * 100]
)
def test_unchecked_names_are_never_printed(machine, bad):
    home, env, _ = machine
    (home / "claude-config" / "state.json").write_text(json.dumps({"defaultTracker": bad}))
    assert start(home, env) is None


def test_other_events_and_bad_input_print_nothing(machine):
    home, env, _ = machine
    assert start(home, env, "PreToolUse") is None
    assert run_installed(home, [], env) == ""
    (home / "claude-config" / "state.json").write_text("{broken")
    assert start(home, env) is None


# merge_confirm: the squash reason

PLAIN_REASON = "Merging needs your confirmation (global rule: merge only with your authorization)"


def reason(command):
    return json.loads(run("merge_confirm.py", bash(command)))["hookSpecificOutput"]["permissionDecisionReason"]


@pytest.mark.parametrize("command", [
    "gh pr merge 42 --squash",
    "gh pr merge 42 -s",
    "gh pr merge -s 42 --delete-branch",
    "gh -R o/r pr merge 42 -ds",
])
def test_squash_merge_gets_the_squash_reason(command):
    text = reason(command)
    assert "squash" in text.lower() and "against" in text and text != PLAIN_REASON


@pytest.mark.parametrize("command", [
    "gh pr merge 42 --merge",
    "gh pr merge 42 --rebase --delete-branch",
    "gh pr merge 42 --subject sq",
    "git merge --squash x && gh pr merge 42",
    "gh api repos/o/r/pulls/3/merge -X PUT -f merge_method=merge",
])
def test_plain_merge_keeps_the_usual_reason(command):
    assert reason(command) == PLAIN_REASON


# skill_gate

GIT_ENV = {
    "GIT_AUTHOR_NAME": "T", "GIT_AUTHOR_EMAIL": "t@example.com",
    "GIT_COMMITTER_NAME": "T", "GIT_COMMITTER_EMAIL": "t@example.com",
    "GIT_AUTHOR_DATE": "2026-01-01T00:00:00Z", "GIT_COMMITTER_DATE": "2026-01-01T00:00:00Z",
    "PATH": "/usr/bin:/bin", "HOME": "/nonexistent",
}


def git(repo, *args):
    subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True, env=GIT_ENV)


def commit(repo, subject):
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "--allow-empty", "-m", subject)


def write_lines(repo, name, count, word="row"):
    (repo / name).write_text("".join(f"{word} {i}\n" for i in range(count)))


@pytest.fixture
def repo(tmp_path):
    """A work repo on a feature branch cut from main, with a bare origin whose HEAD is main."""
    origin = tmp_path / "origin.git"
    work = tmp_path / "work"
    subprocess.run(["git", "init", "-q", "--bare", "-b", "main", str(origin)], check=True, env=GIT_ENV)
    work.mkdir()
    git(work, "init", "-q", "-b", "main")
    write_lines(work, "base.txt", 10)
    commit(work, "chore: base")
    git(work, "remote", "add", "origin", str(origin))
    git(work, "push", "-q", "origin", "main")
    git(work, "remote", "set-head", "origin", "main")
    git(work, "checkout", "-q", "-b", "feature/1-x")
    return work


def review_payload(cwd, skill="review"):
    return {
        "hook_event_name": "PreToolUse", "tool_name": "Skill", "tool_input": {"skill": skill}, "cwd": str(cwd),
    }


def gate(cwd, skill="review", event="PreToolUse"):
    if event == "PreToolUse":
        payload = review_payload(cwd, skill)
    else:
        payload = {"hook_event_name": event, "command_name": skill, "cwd": str(cwd)}
    out = run("skill_gate.py", payload)
    return json.loads(out)["hookSpecificOutput"] if out else None


def context(cwd, **kw):
    out = gate(cwd, **kw)
    return None if out is None else out["additionalContext"]


@pytest.mark.parametrize("count, named", [(300, False), (301, True)])
def test_diff_over_300_lines_names_code_simplifier(repo, count, named):
    write_lines(repo, "big.txt", count)
    commit(repo, "feat: big (#1)")
    text = context(repo)
    assert (text is not None and "code-simplifier" in text) == named
    if named:
        assert "301" in text


def test_deleted_lines_count_toward_the_diff(repo):
    git(repo, "checkout", "-q", "main")
    write_lines(repo, "old.txt", 200)
    commit(repo, "chore: old")
    git(repo, "push", "-q", "origin", "main")
    git(repo, "checkout", "-q", "feature/1-x")
    git(repo, "merge", "-q", "--ff-only", "main")
    write_lines(repo, "old.txt", 101, word="new")
    commit(repo, "refactor: rewrite (#1)")
    assert "301" in context(repo)  # 200 deleted + 101 added


def test_uncommitted_changes_count(repo):
    write_lines(repo, "base.txt", 291, word="new")  # 291 added + 10 deleted = 301
    assert "301" in context(repo)


def test_binary_files_are_ignored(repo):
    (repo / "blob.bin").write_bytes(b"\x00\x01" * 5000)
    commit(repo, "feat: blob (#1)")
    assert context(repo) is None


@pytest.mark.parametrize("subject, named", [
    ("fixup! feat: x", True),
    ("squash! feat: x", True),
    ("amend! feat: x", True),
    ("WIP", True),
    ("wip: halfway", True),
    ("Wipe the cache", False),
    ("feat: mention fixup! in text", False),
])
def test_fixup_or_wip_commit_names_git_master(repo, subject, named):
    commit(repo, subject)
    text = context(repo)
    assert (text is not None and "git-master" in text) == named


def test_fixup_already_on_the_default_branch_is_not_the_branchs(repo):
    git(repo, "checkout", "-q", "main")
    commit(repo, "fixup! chore: base")
    git(repo, "push", "-q", "origin", "main")
    git(repo, "checkout", "-q", "feature/1-x")
    git(repo, "merge", "-q", "--ff-only", "main")
    assert context(repo) is None


# category, a line that hits, a line that misses every category
PATTERNS = [
    ("auth", "login = 1", "log = 1"),
    ("auth", "OAuth ok", "o aut"),
    ("input", "json.loads(x)", "json.dumps(x)"),
    ("input", "eval(x)", "evaluate(x)"),
    ("secrets", "api_key = 1", "api = 1"),
    ("secrets", "Bearer abc", "bear abc"),
    ("shell", "subprocess.run(x)", "my_subprocess"),
    ("shell", "shell=True", "shell = 1"),
    ("network", "requests.get(x)", "prerequests"),
    ("network", "fetch(x)", "fetcher"),
    ("deserialization", "marshal.loads(x)", "unmarshal"),
    ("deserialization", "ObjectInputStream s", "InputStream s"),
]


@pytest.mark.parametrize("category, hit, miss", PATTERNS)
def test_security_categories_match_added_lines(repo, category, hit, miss):
    (repo / "f.txt").write_text(miss + "\n")
    commit(repo, "feat: f (#1)")
    assert context(repo) is None
    (repo / "g.txt").write_text(hit + "\n")
    commit(repo, "feat: g (#1)")
    text = context(repo)
    assert "security-reviewer" in text and category in text


def test_security_category_in_a_changed_path(repo):
    (repo / "notes.txt").write_text("hello\n")
    commit(repo, "docs: notes (#1)")
    assert context(repo) is None
    (repo / "Passwords.txt").write_text("hello\n")
    commit(repo, "docs: more (#1)")
    text = context(repo)
    assert "security-reviewer" in text and "auth" in text


def test_security_only_reads_added_lines(repo):
    git(repo, "checkout", "-q", "main")
    (repo / "k.txt").write_text("subprocess.run(x)\n")
    commit(repo, "chore: k")
    git(repo, "push", "-q", "origin", "main")
    git(repo, "checkout", "-q", "feature/1-x")
    git(repo, "merge", "-q", "--ff-only", "main")
    (repo / "k.txt").write_text("")
    commit(repo, "refactor: k (#1)")
    assert context(repo) is None


def test_two_hits_print_one_combined_message(repo):
    write_lines(repo, "big.txt", 301)
    commit(repo, "fixup! feat: big")
    out = run("skill_gate.py", review_payload(repo))
    assert out.count("\n") == 1
    text = json.loads(out)["hookSpecificOutput"]["additionalContext"]
    assert "code-simplifier" in text and "git-master" in text


@pytest.mark.parametrize("name", [
    "review", "omc-review", "oh-my-claudecode:review", "oh-my-claudecode:omc-review",
])
def test_every_review_spelling_is_gated_on_both_events(repo, name):
    write_lines(repo, "big.txt", 301)
    commit(repo, "feat: big (#1)")
    for event in ("PreToolUse", "UserPromptExpansion"):
        out = gate(repo, name, event)
        assert out["hookEventName"] == event and "code-simplifier" in out["additionalContext"]


@pytest.mark.parametrize("name", ["autopilot", "oh-my-claudecode:autopilot"])
def test_model_invoked_autopilot_asks(repo, name):
    out = gate(repo, name)
    assert out["hookEventName"] == "PreToolUse" and out["permissionDecision"] == "ask"
    assert "autopilot" in out["permissionDecisionReason"]


def test_user_typed_autopilot_passes(repo):
    assert gate(repo, "autopilot", "UserPromptExpansion") is None
    assert gate(repo, "oh-my-claudecode:autopilot", "UserPromptExpansion") is None


def test_other_skills_print_nothing_even_when_review_would(repo):
    write_lines(repo, "big.txt", 301)
    commit(repo, "fixup! x")
    for name in ("tdd", "oh-my-claudecode:execute", "reviewer", "review-x"):
        assert gate(repo, name) is None


def test_non_git_directory_prints_nothing(tmp_path):
    assert gate(tmp_path) is None


def test_repo_without_origin_falls_back_to_main(repo):
    git(repo, "remote", "remove", "origin")
    write_lines(repo, "big.txt", 301)
    commit(repo, "feat: big (#1)")
    assert "code-simplifier" in context(repo)


@pytest.mark.parametrize("payload", [
    b"", b"not json", b"[]", b"{}", b"\xff\xfe", b"[" * 100000,
    json.dumps({"hook_event_name": "PreToolUse", "tool_name": "Skill", "tool_input": {"skill": 7}}).encode(),
    json.dumps({"hook_event_name": "PreToolUse", "tool_name": "Skill", "tool_input": []}).encode(),
    json.dumps({"hook_event_name": 7, "command_name": ["review"]}).encode(),
    json.dumps({"hook_event_name": "UserPromptExpansion", "command_name": None}).encode(),
    json.dumps(review_payload("/tmp") | {"cwd": 7}).encode(),
    json.dumps(review_payload("/tmp") | {"cwd": "/tmp/a\u0000b"}).encode(),
])
def test_skill_gate_never_fails(payload):
    assert run("skill_gate.py", payload) == ""


@pytest.mark.parametrize("name", ["Review", "review;ls", "../review", "a:b:c", "review\n", ":review", "", "x" * 5000])
def test_unchecked_skill_names_are_ignored(repo, name):
    write_lines(repo, "big.txt", 301)
    commit(repo, "fixup! x")
    assert gate(repo, name) is None


def test_hooks_do_not_run_repo_config(repo, tmp_path):
    marks = tmp_path / "marks"
    marks.mkdir()
    for key in ("fsmonitor", "extdiff", "textconv"):
        script = tmp_path / f"{key}.sh"
        script.write_text(f"#!/bin/sh\ntouch {marks}/{key}\ncat\n")
        script.chmod(script.stat().st_mode | stat.S_IXUSR)
    git(repo, "config", "core.fsmonitor", str(tmp_path / "fsmonitor.sh"))
    git(repo, "config", "diff.external", str(tmp_path / "extdiff.sh"))
    git(repo, "config", "diff.t.textconv", str(tmp_path / "textconv.sh"))
    (repo / ".gitattributes").write_text("*.txt diff=t\n")
    write_lines(repo, "big.txt", 301)
    commit(repo, "feat: big (#1)")
    write_lines(repo, "base.txt", 30)
    for f in marks.iterdir():  # the test's own git calls ran the scripts; only the hook's count
        f.unlink()
    assert "code-simplifier" in context(repo)
    run("merge_confirm.py", bash("gh pr merge 1 --squash"))
    assert list(marks.iterdir()) == []


def test_skill_gate_ignores_git_environment_variables(repo, tmp_path):
    other = tmp_path / "other"
    other.mkdir()
    git(other, "init", "-q", "-b", "main")
    write_lines(repo, "big.txt", 301)
    commit(repo, "feat: big (#1)")
    out = run(
        "skill_gate.py", review_payload(repo),
        env={"GIT_DIR": str(other / ".git"), "GIT_WORK_TREE": str(other)},
    )
    assert "code-simplifier" in out


def test_hooks_print_only_checked_values(repo):
    word = "LEAKCANARY"
    (repo / f"auth{word}.txt").write_text(f"subprocess.run({word})\n")
    commit(repo, f"fixup! {word}")
    runs = [("skill_gate.py", review_payload(repo) | {"extra": word})]
    runs += [("merge_confirm.py", bash(c)) for c in (
        f"gh pr merge 1 --squash --body {word}", f"gh pr merge {word} -s", f"gh pr merge {word}",
    )]
    for name, payload in runs:
        done = subprocess.run(
            [sys.executable, "-I", str(HOOKS / name)],
            input=json.dumps(payload).encode(), capture_output=True, env={"PATH": "/usr/bin:/bin"}, timeout=10,
        )
        assert done.returncode == 0 and done.stdout and done.stderr == b""
        assert word.encode() not in done.stdout and str(repo).encode() not in done.stdout


def test_skill_gate_finishes_within_its_timeout_on_a_wide_diff(repo):
    for i in range(400):
        (repo / f"f{i}.txt").write_text("row\n")
    commit(repo, "feat: many (#1)")
    start = time.monotonic()
    assert "code-simplifier" in context(repo)
    assert time.monotonic() - start < 5


# wiring

FRAGMENT = json.loads((ROOT / "config" / "settings.fragment.json").read_text())


def entries(event, name):
    return [
        (group.get("matcher"), hook)
        for group in FRAGMENT["hooks"].get(event, [])
        for hook in group["hooks"]
        if hook["command"].endswith(f"/hooks/{name}")
    ]


def test_skill_gate_is_registered_for_both_events():
    hook = {"type": "command", "command": "python3 -I {claude_home}/hooks/skill_gate.py", "timeout": 5}
    assert entries("PreToolUse", "skill_gate.py") == [("Skill", hook)]
    assert entries("UserPromptExpansion", "skill_gate.py") == [(None, hook)]


def test_both_hosts_list_skill_gate_and_merge_confirm():
    for host in ("personal", "work"):
        listed = json.loads((ROOT / "hosts" / f"{host}.json").read_text())["hooks"]
        assert "skill_gate.py" in listed and "merge_confirm.py" in listed
