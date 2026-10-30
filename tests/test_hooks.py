"""The two hooks: merge_confirm asks before a PR merge; host_default states the tracker for the repo."""

import ast
import io
import json
import os
import pathlib
import signal
import stat
import subprocess
import sys
import time
import types

import pytest

from tests.conftest import ROOT, load

HOOKS = ROOT / "config" / "hooks"


def run(name, payload, env=None):
    stdin = payload if isinstance(payload, bytes) else json.dumps(payload).encode()
    done = subprocess.run(
        [sys.executable, "-I", str(HOOKS / name)],
        input=stdin, capture_output=True, timeout=10, check=False,
        # HOME and XDG_CONFIG_HOME are the per-test temp dir (conftest), never the real ~/.config.
        env={"PATH": "/usr/bin:/bin", "HOME": os.environ["HOME"], "XDG_CONFIG_HOME": os.environ["XDG_CONFIG_HOME"], **(env or {})},
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
    "gh pr merge 5",
    "gh api -X PUT repos/o/r/pulls/3/merge",
    "gh api --paginate -XPUT -H 'Accept: x' repos/o/r/pulls/3/merge -f body=/x",
    "tea api repos/o/r/pulls/3/merge",
    "gh api graphql <<'EOF'\nmutation { mergePullRequest(input: {}) { clientMutationId } }\nEOF",
    'bash -c "gh pr merge 5"',
    'eval "gh pr merge"',
    "echo 5 | xargs gh pr merge",
    "echo $(gh pr merge 5)",
])
def test_merges_ask(command):
    out = json.loads(run("merge_confirm.py", bash(command)))
    assert out["hookSpecificOutput"]["permissionDecision"] == "ask"


@pytest.mark.parametrize("command", [
    'echo "run gh pr merge 5 when ready"',
    'grep -n "gh pr merge" docs/notes.md',
    'git commit -m "docs: say when gh pr merge is allowed (#7)"',
    "cat > note.md <<'EOF'\nrun gh pr merge --merge\nEOF",
    "python3 -c \"print('gh api /merge')\"",
])
def test_merge_confirm_ignores_commands_that_only_mention_a_merge(command):
    assert run("merge_confirm.py", bash(command)) == ""


@pytest.mark.parametrize("command", [
    "gh pr view 42", "git merge main", "gh pr create --title merge", "ls",
    # Only the endpoint operand of gh api or tea api counts as a /merge path, not a flag value.
    'gh api repos/o/r/issues/5/comments -f body="see /merge docs"',
    "gh api repos/o/r/issues/5/comments -F 'body=/merge'", "gh api repos/o/r/issues/5/comments --raw-field=body=/merge",
    "gh api repos/o/r/issues -H 'X-Note: /merge' --input ./merge/body.json",
    "tea api repos/o/r/issues/5/comments -d 'see /merge'",
])
def test_other_commands_pass_silently(command):
    assert run("merge_confirm.py", bash(command)) == ""


@pytest.mark.parametrize("payload", [b"", b"not json", b"[]", b'{"tool_input": {"command": 7}}'])
def test_merge_confirm_never_fails(payload):
    assert run("merge_confirm.py", payload) == ""


def test_merge_confirm_is_linear_on_dash_heavy_commands():
    run("merge_confirm.py", bash("gh pr " + "-a " * 20000))


@pytest.mark.parametrize("command", [
    "sudo gh pr merge 5", "sudo -u root -E -n gh pr merge 5", "doas gh pr merge 5", "nohup gh pr merge 5",
    "exec gh pr merge 5", "time -p gh pr merge 5", "timeout 5 gh pr merge 5", "nice -n 5 gh pr merge 5",
    "stdbuf -oL gh pr merge 5", "/usr/bin/gh pr merge 5", "GIT_DIR=x gh pr merge 5", "env -C x gh pr merge 5",
    "env -S 'gh pr merge 5'", "bash -lc 'gh pr merge 5'", "sh -ec 'gh pr merge 5'", "/bin/bash -c 'gh pr merge 5'",
    "zsh -c 'gh pr merge 5'", "bash -c 'bash -c \"gh pr merge 5\"'", "echo 'gh pr merge 5' | bash",
    "bash -s <<'EOF'\ngh pr merge 5\nEOF", "sudo bash -c 'gh pr merge 5'", "`gh pr merge 5`",
    "echo 5 | xargs -n 1 gh pr merge", "eval eval 'gh pr merge 5'",
    "gh api graphql -f query=\"$(cat <<'EOF'\nmutation { mergePullRequest(input: {}) { clientMutationId } }\nEOF\n)\"",
    "cat <<E | bash\ngh pr merge 5\nE",
    "watch -n 5 gh pr merge 5", "coproc gh pr merge 5", "builtin eval 'gh pr merge 5'", "dash -c 'gh pr merge 5'",
    "ksh -c 'gh pr merge 5'", 'printf "gh pr merge\\n" | sh', "printf '\\tgh pr merge 5' | sh",
    "echo gh pr merge 5; bash",  # accepted false ask: the parser records no separator, so `;` acts like `|`
])
def test_merges_behind_prefixes_and_shell_runners_ask(command):
    out = json.loads(run("merge_confirm.py", bash(command)))
    assert out["hookSpecificOutput"]["permissionDecision"] == "ask"


@pytest.mark.parametrize("command", [
    "bash -c 'echo \"gh pr merge 5\"'", "sh -c 'grep \"gh pr merge\" notes.md'", "bash merge.sh gh pr merge 5",
    "printf 'gh pr merge 5'", "xargs echo gh pr merge 5", "cat <<E\ngh pr merge\nE", "sudo echo gh pr merge 5", "command -v gh pr merge",
    'bash -c "$CMD"',
    "tea pulls merge 5",  # known gap: `tea pulls merge` does not ask; a rule for it is out of scope
    "cat <<EOF\n$(gh pr merge 5)\nEOF",  # accepted miss: bash expands $(...) in an unquoted heredoc, the parser reads the body as data
    "echo " + "$(" * 40 + "gh pr merge 5" + ")" * 40,  # nesting past MAX_DEPTH is unparsed and passes
    "eval " * 40 + "gh pr merge 5",  # same for a chain of eval re-parses past MAX_DEPTH
])
def test_merge_confirm_ignores_text_no_shell_runs(command):
    assert run("merge_confirm.py", bash(command)) == ""


@pytest.mark.parametrize("command", [
    'bash -c "gh pr merge 5 --squash"', "sudo gh pr merge 5 -s", "echo 'gh pr merge 5 -s' | sh",
])
def test_squash_through_prefixes_and_shell_runners_gets_the_squash_reason(command):
    text = reason(command)
    assert "squash" in text.lower() and text != PLAIN_REASON


@pytest.mark.parametrize("command", [
    "bash -c '" * 20000 + "gh pr merge 5",
    "eval " * 20000 + "gh pr merge 5",
    "$(" * 20000 + "gh pr merge 5",
    "gh pr view 5;" * 100000,
], ids=["bash-c-nesting", "eval-eval", "substitution-nesting", "long"])
def test_merge_confirm_stays_linear_on_nested_and_long_commands(command):
    start = time.monotonic()
    run("merge_confirm.py", bash(command))
    assert time.monotonic() - start < 5


@pytest.fixture
def machine(tmp_path):
    home = tmp_path / "claude"
    (home / "hooks").mkdir(parents=True)
    (home / "hooks" / "host_default.py").write_text((HOOKS / "host_default.py").read_text())
    (home / "claude-config").mkdir()
    (home / "claude-config" / "state.json").write_text(json.dumps({"host": "work", "defaultTracker": "jira"}))
    env = {"HOME": str(tmp_path), "XDG_CONFIG_HOME": str(tmp_path / "xdg")}
    return home, env, tmp_path


def start(home, env, event="SessionStart", cwd=None):
    payload = {"hook_event_name": event} | ({"cwd": str(cwd)} if cwd is not None else {})
    out = run_installed(home, payload, env)
    return json.loads(out)["hookSpecificOutput"] if out else None


def run_installed(home, payload, env):
    done = subprocess.run(
        [sys.executable, "-I", str(home / "hooks" / "host_default.py")],
        input=json.dumps(payload).encode(), capture_output=True, env=env, timeout=10, check=False,
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


def test_local_default_tracker_is_ignored(machine):
    home, env, tmp = machine
    (tmp / "xdg" / "claude-config").mkdir(parents=True)
    (tmp / "xdg" / "claude-config" / "local.json").write_text(json.dumps({"defaultTracker": "gitea"}))
    text = start(home, env)["additionalContext"]
    assert "tracker: jira. Use the jira-ticket-lifecycle skill" in text
    assert text.endswith(" Source: host profile.")


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


# host_default: the tracker from the repo's history and origin, then the host profile

WINS = "unless the repo's CLAUDE.md names another tracker; the repo's choice wins."


def jira_project(tmp, project="PAY"):
    """local.json with a Jira project key, in the machine fixture's XDG_CONFIG_HOME."""
    (tmp / "xdg" / "claude-config").mkdir(parents=True, exist_ok=True)
    (tmp / "xdg" / "claude-config" / "local.json").write_text(json.dumps({"jira": {"project": project}}))


def tracker_line(machine, cwd, **extra):
    home, env, _ = machine
    out = start(home, env | extra, cwd=cwd)
    return out["additionalContext"] if out else None


def from_profile(text):
    return text == f"Host profile: work. Default issue tracker: jira. Use the jira-ticket-lifecycle skill {WINS} Source: host profile."


def test_a_jira_key_in_commit_subjects_names_jira(machine, repo):
    jira_project(machine[2])
    commit(repo, "fix: the PAY-1 crash")
    assert from_profile(tracker_line(machine, repo))  # one bare key is not enough
    commit(repo, "fix: the PAY-2 crash")
    assert tracker_line(machine, repo) == (
        f"Host profile: work. Default issue tracker: jira. Use the jira-ticket-lifecycle skill {WINS} "
        "Source: jira key in history."
    )


@pytest.mark.parametrize("subject,branch", [
    ("fix: the crash (PAY-1)", None),
    ("PAY-1: fix the crash", None),
    ("fix: the crash", "feature/PAY-1-crash"),
])
def test_a_conventional_jira_ref_names_jira(machine, repo, subject, branch):
    jira_project(machine[2])
    if branch:
        git(repo, "checkout", "-q", "-b", branch)
    commit(repo, subject)
    assert tracker_line(machine, repo).endswith(" Source: jira key in history.")


def test_one_bare_key_or_a_lowercase_key_does_not_name_jira(machine, repo):
    jira_project(machine[2], "UTF")
    commit(repo, "fix: read files as UTF-8 (#3)")
    assert from_profile(tracker_line(machine, repo))
    jira_project(machine[2], "PAY")
    commit(repo, "pay-1: fix the crash")
    commit(repo, "fix: the crash (pay-2)")
    assert from_profile(tracker_line(machine, repo))


def test_a_jira_key_beats_a_github_origin(machine, repo):
    jira_project(machine[2])
    git(repo, "remote", "set-url", "origin", "https://github.com/o/r.git")
    commit(repo, "PAY-1: fix the crash")
    text = tracker_line(machine, repo)
    assert "Default issue tracker: jira." in text and text.endswith(" Source: jira key in history.")


@pytest.mark.parametrize("url", [
    "https://github.com/o/r.git", "ssh://git@github.com/o/r.git", "git@github.com:o/r.git", "https://GitHub.com:443/o/r",
])
def test_a_github_origin_names_github(machine, repo, url):
    git(repo, "remote", "set-url", "origin", url)
    text = tracker_line(machine, repo)
    assert "Default issue tracker: github. Use the github-issue-lifecycle skill" in text
    assert " Source: origin." in text


def test_insteadof_is_applied_to_origin(machine, repo):
    git(repo, "remote", "set-url", "origin", "gh:o/r")
    assert from_profile(tracker_line(machine, repo))  # "gh" alone names no tracker
    git(repo, "config", "url.https://github.com/.insteadOf", "gh:")
    assert "Default issue tracker: github." in tracker_line(machine, repo)


def tea_hook(machine, monkeypatch, calls):
    """host_default imported in-process, with `tea logins list` answering from a fixed CSV."""
    hook = hook_module("host_default.py")
    real = hook.run_tool

    def fake(name, args, env, deadline, cwd=None):
        calls.append((name, args))
        if name == "tea":
            return "Name,URL,SSHHost,User,Default\nhome,https://gitea.example.org,ssh.example.org,u,true\n"
        return real(name, args, env, deadline, cwd)

    monkeypatch.setattr(hook, "run_tool", fake)
    return hook


@pytest.mark.parametrize("url", ["https://gitea.example.org/o/r.git", "git@ssh.example.org:o/r.git"])
def test_a_tea_login_host_names_gitea(machine, repo, monkeypatch, url):
    home, _, tmp = machine
    (tmp / "xdg" / "tea").mkdir(parents=True)
    (tmp / "xdg" / "tea" / "config.yml").write_text("logins: []\n")
    calls = []
    hook = tea_hook(machine, monkeypatch, calls)
    git(repo, "remote", "set-url", "origin", url)
    text = hook.message(home, tmp / "xdg", str(repo))
    assert "Default issue tracker: gitea. Use the gitea-issue-lifecycle skill" in text
    assert text.endswith(" Source: origin. Host profile default: jira.")
    assert ("tea", ["logins", "list", "-o", "csv"]) in calls
    git(repo, "remote", "set-url", "origin", "https://elsewhere.example.org/o/r.git")
    assert from_profile(hook.message(home, tmp / "xdg", str(repo)))


def test_tea_is_not_run_without_a_tea_config(machine, repo, monkeypatch):
    home, _, tmp = machine
    calls = []
    hook = tea_hook(machine, monkeypatch, calls)
    git(repo, "remote", "set-url", "origin", "https://gitea.example.org/o/r.git")
    assert from_profile(hook.message(home, tmp / "xdg", str(repo)))
    assert calls and all(name == "git" for name, _ in calls)


def test_a_github_origin_on_a_jira_host_names_both(machine, repo):
    git(repo, "remote", "set-url", "origin", "https://github.com/o/r.git")
    assert tracker_line(machine, repo) == (
        f"Host profile: work. Default issue tracker: github. Use the github-issue-lifecycle skill {WINS} "
        "Source: origin. Host profile default: jira."
    )


def test_no_signals_fall_back_to_the_host_profile(machine, repo):
    jira_project(machine[2])
    commit(repo, "fix: the crash (#4)")
    assert from_profile(tracker_line(machine, repo))


def test_a_work_host_repo_with_a_github_origin_and_no_key_names_github(machine, repo):
    jira_project(machine[2])
    git(repo, "remote", "set-url", "origin", "git@github.com:o/r.git")
    commit(repo, "fix: the crash (#4)")
    text = tracker_line(machine, repo)
    assert "Default issue tracker: github." in text and text.endswith(" Source: origin. Host profile default: jira.")


def test_no_host_profile_and_no_signals_prints_nothing(machine, repo):
    home, _, _ = machine
    (home / "claude-config" / "state.json").write_text(json.dumps({"host": "work"}))
    assert tracker_line(machine, repo) is None
    git(repo, "remote", "set-url", "origin", "https://github.com/o/r.git")
    assert tracker_line(machine, repo) == (
        f"Host profile: work. Default issue tracker: github. Use the github-issue-lifecycle skill {WINS} Source: origin."
    )


def test_unborn_head_and_a_non_git_cwd_fall_back(machine, tmp_path):
    jira_project(machine[2])
    unborn = tmp_path / "unborn"
    unborn.mkdir()
    git(unborn, "init", "-q", "-b", "main")
    plain = tmp_path / "plain"
    plain.mkdir()
    for cwd in (unborn, plain, tmp_path / "missing", "relative/dir", "/"):
        assert from_profile(tracker_line(machine, cwd)), cwd


def fast_history(path, subjects):
    """A repo on main whose history is `subjects`, oldest first, built in one git call."""
    path.mkdir()
    git(path, "init", "-q", "-b", "main")
    stream = "".join(
        f"commit refs/heads/main\ncommitter T <t@example.com> {1700000000 + i} +0000\n"
        f"data {len(s.encode())}\n{s}\n"
        for i, s in enumerate(subjects)
    )
    subprocess.run(["git", "-C", str(path), "fast-import", "--quiet"], input=stream.encode(), check=True, env=GIT_ENV)


def test_history_scan_is_bounded(machine, tmp_path, monkeypatch):
    jira_project(machine[2])
    old = tmp_path / "old"
    fast_history(old, ["PAY-1: a", "PAY-2: b", *[f"chore: {i}" for i in range(200)]])
    assert from_profile(tracker_line(machine, old))  # the keys are 201 and 202 commits back
    recent = tmp_path / "recent"
    fast_history(recent, ["PAY-1: a", "PAY-2: b", *[f"chore: {i}" for i in range(198)]])
    assert tracker_line(machine, recent).endswith(" Source: jira key in history.")
    calls = []
    hook = tea_hook(machine, monkeypatch, calls)
    hook.message(machine[0], machine[2] / "xdg", str(old))
    args = [a[len(hook.GIT_FLAGS):] for name, a in calls if name == "git"]
    assert all(a[:len(hook.GIT_FLAGS)] == hook.GIT_FLAGS for name, a in calls)
    assert ["log", "-n", "200", "--format=%s", "HEAD", "--"] in args
    assert any(a[0] == "for-each-ref" and "--count=500" in a for a in args)


def test_git_env_variables_are_ignored(machine, repo, tmp_path):
    jira_project(machine[2])
    other = tmp_path / "other"
    fast_history(other, ["PAY-1: a", "PAY-2: b"])
    git(other, "remote", "add", "origin", "https://github.com/o/r.git")
    env = {"GIT_DIR": str(other / ".git"), "GIT_WORK_TREE": str(other), "GIT_CONFIG_PARAMETERS": "'core.fsmonitor=true'"}
    assert from_profile(tracker_line(machine, repo, **env))


@pytest.mark.parametrize("project", ["pay", "PAY; echo LEAKCANARY", "P", "LEAKCANARYKEY", 7, ["PAY"]])
def test_an_unchecked_host_or_key_is_never_printed(machine, repo, project):
    tmp = machine[2]
    (tmp / "xdg" / "claude-config").mkdir(parents=True)
    (tmp / "xdg" / "claude-config" / "local.json").write_text(json.dumps({"jira": {"project": project}}))
    for i in (1, 2):
        commit(repo, f"{project}-{i}: LEAKCANARY")
    git(repo, "remote", "set-url", "origin", "https://LEAK_CANARY.example/o/r.git")
    text = tracker_line(machine, repo)
    assert from_profile(text) and "LEAK" not in text


# merge_confirm: the squash reason

PLAIN_REASON = "Merging needs your confirmation (claude-config merge rule: merge only with your authorization)"


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


@pytest.mark.parametrize("command", [
    "gh pr merge 5 --merge && ls -sh",
    "gh pr merge 5 --merge; ls -s",
    "gh pr merge 5 --merge || ls -s",
    "gh pr merge 5 --merge | tee -s",
    "gh pr merge 5 --merge\nls -s",
])
def test_squash_flags_of_later_commands_do_not_count(command):
    assert reason(command) == PLAIN_REASON


@pytest.mark.parametrize("command", [
    "gh api repos/o/r/pulls/3/merge -X PUT -f merge_method=squash",
    "gh api -X PUT repos/o/r/pulls/3/merge --field merge_method=squash",
    "gh api repos/o/r/pulls/3/merge -X PUT --raw-field=merge_method=squash",
    "gh api repos/o/r/pulls/3/merge -X PUT -F 'merge_method=squash'",
])
def test_an_api_squash_merge_gets_the_squash_reason(command):
    text = reason(command)
    assert "squash" in text.lower() and "against" in text and text != PLAIN_REASON


# git repos for the host_default tests

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


def test_host_default_scan_runs_no_fsmonitor_or_git_hook(repo, tmp_path):
    marks = tmp_path / "marks"
    marks.mkdir()
    executable(tmp_path / "fsmonitor.sh", f"#!/bin/sh\ntouch {marks}/fsmonitor\n")
    git(repo, "config", "core.fsmonitor", str(tmp_path / "fsmonitor.sh"))
    hooks = tmp_path / "githooks"
    hooks.mkdir()
    for name in ("reference-transaction", "post-checkout", "post-index-change"):
        executable(hooks / name, f"#!/bin/sh\ntouch {marks}/{name}\n")
    git(repo, "config", "core.hooksPath", str(hooks))
    host_default_scans(repo)
    assert list(marks.iterdir()) == []


def host_default_scans(repo, project="PAY"):
    """Runs host_default.py on `repo` with a Jira key set, so it reads the log, the refs and origin."""
    config = pathlib.Path(os.environ["XDG_CONFIG_HOME"]) / "claude-config"
    config.mkdir(parents=True, exist_ok=True)
    (config / "local.json").write_text(json.dumps({"jira": {"project": project}}))
    return run("host_default.py", {"hook_event_name": "SessionStart", "cwd": str(repo)})


def test_hooks_print_only_checked_values(repo, machine):
    word = "LEAKCANARY"
    for command in (f"gh pr merge 1 --squash --body {word}", f"gh pr merge {word} -s", f"gh pr merge {word}"):
        out = run("merge_confirm.py", bash(command))
        assert out and word not in out
    home, env, tmp = machine
    (tmp / "xdg" / "claude-config").mkdir(parents=True)
    (tmp / "xdg" / "claude-config" / "local.json").write_text(json.dumps({"jira": {"project": "PAY"}, "note": word}))
    commit(repo, f"PAY-1: {word}")
    out = start(home, env, cwd=repo)["additionalContext"]
    assert out.endswith(" Source: jira key in history.")
    assert word not in out and str(repo) not in out


# wiring

FRAGMENT = json.loads((ROOT / "config" / "settings.fragment.json").read_text())
HOOK_NAMES = ["merge_confirm.py", "host_default.py"]


def entries(event, name):
    return [
        (group.get("matcher"), hook)
        for group in FRAGMENT["hooks"].get(event, [])
        for hook in group["hooks"]
        if hook["command"].endswith(f"/hooks/{name}")
    ]


def test_two_hooks_are_registered_and_listed():
    def hook(name):
        return {"type": "command", "command": f"python3 -I {{claude_home}}/hooks/{name}", "timeout": 10}

    assert entries("PreToolUse", "merge_confirm.py") == [("Bash", hook("merge_confirm.py"))]
    assert entries("SessionStart", "host_default.py") == [(None, hook("host_default.py"))]
    assert entries("SubagentStart", "host_default.py") == [(None, hook("host_default.py"))]
    assert sorted(FRAGMENT["hooks"]) == ["PreToolUse", "SessionStart", "SubagentStart"]
    assert sum(len(groups) for groups in FRAGMENT["hooks"].values()) == 3
    for host in ("personal", "work"):
        assert json.loads((ROOT / "hosts" / f"{host}.json").read_text())["hooks"] == HOOK_NAMES


def test_every_hook_entry_outlasts_the_hooks_own_deadline():
    for groups in FRAGMENT["hooks"].values():
        for group in groups:
            for hook in group["hooks"]:
                assert hook["timeout"] == 10, hook["command"]
    for name in HOOK_NAMES:
        assert hook_module(name).DEADLINE_SECONDS == 5, name


# repo config that runs programs


def executable(path, body):
    path.write_text(body)
    path.chmod(path.stat().st_mode | stat.S_IXUSR)
    return path


def test_hooks_do_not_run_gpg_from_repo_config(repo, tmp_path):
    mark = tmp_path / "gpg-ran"
    script = executable(tmp_path / "gpg.sh", f"#!/bin/sh\ntouch {mark}\nexit 1\n")
    commit(repo, "feat: signed (#1)")
    raw = subprocess.run(["git", "-C", str(repo), "cat-file", "commit", "HEAD"], capture_output=True, check=True, env=GIT_ENV).stdout
    header, _, message = raw.partition(b"\n\n")
    signature = b"gpgsig -----BEGIN PGP SIGNATURE-----\n \n iQEzBAABCAAdFiEE\n -----END PGP SIGNATURE-----\n"
    signed = subprocess.run(
        ["git", "-C", str(repo), "hash-object", "-t", "commit", "-w", "--stdin"],
        input=header + b"\n" + signature + b"\n" + message, capture_output=True, check=True, env=GIT_ENV,
    ).stdout.decode().strip()
    git(repo, "update-ref", "HEAD", signed)
    git(repo, "config", "log.showSignature", "true")
    git(repo, "config", "gpg.program", str(script))
    subprocess.run(["git", "-C", str(repo), "log", "--format=%s", "-1"], capture_output=True, env=GIT_ENV, check=False)
    assert mark.exists()  # the fixture works: plain git log runs gpg.program
    mark.unlink()
    host_default_scans(repo)
    assert not mark.exists()


@pytest.mark.parametrize("transport", ["uploadpack", "sshCommand"])
@pytest.mark.parametrize("lazy_fetch_off", [True, False])
def test_host_default_never_fetches_a_missing_commit(machine, repo, tmp_path, monkeypatch, transport, lazy_fetch_off):
    # lazy_fetch_off=False drops GIT_NO_LAZY_FETCH from the hook's git env (as on git < 2.44),
    # so only protocol.allow=never stands between the scan and the transport.
    mark = tmp_path / "transport-ran"
    script = executable(tmp_path / "transport.sh", f"#!/bin/sh\ntouch {mark}\nexit 1\n")
    git(repo, "config", "extensions.partialClone", "origin")
    git(repo, "config", "remote.origin.promisor", "true")
    if transport == "uploadpack":
        git(repo, "config", "remote.origin.uploadpack", str(script))
    else:
        git(repo, "remote", "set-url", "origin", "ssh://git.example.org/o/r.git")
        git(repo, "config", "core.sshCommand", str(script))
    # A ref at a commit the promisor remote would be asked for; update-ref would fetch it itself.
    (repo / ".git" / "refs" / "heads" / "feature" / "1-x").write_text("12" * 20 + "\n")
    subprocess.run(["git", "-C", str(repo), "log", "-1", "HEAD", "--"], capture_output=True, env=GIT_ENV, check=False)
    assert mark.exists()  # the fixture works: plain git fetches the missing commit
    mark.unlink()
    jira_project(machine[2])
    hook = hook_module("host_default.py")
    real = hook.run_tool

    def tool(name, args, env, deadline, cwd=None):
        if not lazy_fetch_off:
            env = {k: v for k, v in env.items() if k != "GIT_NO_LAZY_FETCH"}
        return real(name, args, env, deadline, cwd)

    monkeypatch.setattr(hook, "run_tool", tool)
    assert from_profile(hook.message(machine[0], machine[2] / "xdg", str(repo)))
    assert not mark.exists()


# No bypass: a keyword or skill in the first prompt changes nothing


def test_no_hook_has_a_bypass():
    assert sorted(p.name for p in HOOKS.glob("*.py")) == sorted(HOOK_NAMES)
    for name in HOOK_NAMES:
        tree = ast.parse((HOOKS / name).read_text())
        names = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)}
        names |= {n.name for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)}
        assert "session_bypassed" not in names, name
        assert not [n for n in names if n.startswith("BYPASS_")], name


def test_a_keyword_first_prompt_does_not_silence_it(machine, tmp_path):
    home, env, _ = machine
    transcript = tmp_path / "session.jsonl"
    transcript.write_text(json.dumps({"type": "user", "message": {"role": "user", "content": "ralph"}}) + "\n")
    payload = {"hook_event_name": "SessionStart", "transcript_path": str(transcript)}
    out = json.loads(run_installed(home, payload, env))["hookSpecificOutput"]
    assert out["additionalContext"].startswith("Host profile: work. Default issue tracker: jira.")
    merge = json.loads(run("merge_confirm.py", bash("gh pr merge 42") | {"transcript_path": str(transcript)}))
    assert merge["hookSpecificOutput"]["permissionDecision"] == "ask"


def module(path, name):
    """Import a file by path without leaving bytecode next to it."""
    before = sys.dont_write_bytecode
    sys.dont_write_bytecode = True
    try:
        return load(path, name)
    finally:
        sys.dont_write_bytecode = before


def hook_module(name):
    return module(HOOKS / name, f"hook_{name[:-3]}_under_test")


# Exact output on malformed input, on an error and past the deadline (#3)

EVENT_ONLY = {
    "merge_confirm.py": {"hook_event_name": "PreToolUse", "tool_name": "Bash"},
    "host_default.py": {"hook_event_name": "SessionStart"},
}
HOST_CONTEXT = (
    b'{"hookSpecificOutput": {"hookEventName": "SessionStart", "additionalContext": "Host profile: work. '
    b"Default issue tracker: jira. Use the jira-ticket-lifecycle skill unless the repo's CLAUDE.md names "
    b'another tracker; the repo\'s choice wins. Source: host profile."}}\n'
)
MALFORMED = [b"{}", b'{"tool_input": {}}', b'{"tool_name": 1}', b"null", b"", b"{", b"\xff\xfe"]


def hook_result(name, stdin, machine):
    """Exit code, stdout and stderr of a hook fed `stdin`; host_default runs as deployed in `machine`."""
    home, env, _ = machine
    script = home / "hooks" / name if name == "host_default.py" else HOOKS / name
    done = subprocess.run(
        [sys.executable, "-I", str(script)],
        input=stdin, capture_output=True, env={"PATH": "/usr/bin:/bin", **env}, timeout=10, check=False,
    )
    return done.returncode, done.stdout, done.stderr


@pytest.mark.parametrize("stdin", MALFORMED)
@pytest.mark.parametrize("name", HOOK_NAMES)
def test_malformed_input_exits_0_with_no_output(name, stdin, machine):
    assert hook_result(name, stdin, machine) == (0, b"", b"")


def test_host_default_on_a_list_payload_exits_0_with_no_output(machine):
    assert hook_result("host_default.py", b"[]", machine) == (0, b"", b"")


@pytest.mark.parametrize("name", HOOK_NAMES)
def test_an_event_without_tool_input_gives_the_usual_output(name, machine):
    expected = HOST_CONTEXT if name == "host_default.py" else b""
    assert hook_result(name, json.dumps(EVENT_ONLY[name]).encode(), machine) == (0, expected, b"")


# Runs a hook's main() as its __main__ block does. `patch` is Python source, run after the
# module loads as `hook`, that replaces one of the hook's functions.
DRIVER = """
import importlib.util, sys
spec = importlib.util.spec_from_file_location("hook", sys.argv[1])
hook = importlib.util.module_from_spec(spec)
spec.loader.exec_module(hook)
exec(sys.argv[2])
try:
    hook.main()
finally:
    sys.exit(0)
"""
RAISE = "def boom(*args, **kwargs):\n    raise RuntimeError\n"


def driven(name, patch, payload):
    done = subprocess.run(
        [sys.executable, "-I", "-B", "-c", DRIVER, str(HOOKS / name), patch],
        input=json.dumps(payload).encode(), capture_output=True, timeout=20, check=False,
        env={"PATH": "/usr/bin:/bin", "HOME": os.environ["HOME"], "XDG_CONFIG_HOME": os.environ["XDG_CONFIG_HOME"]},
    )
    return done.returncode, done.stdout, done.stderr


@pytest.mark.parametrize("name,patch,payload", [
    ("host_default.py", RAISE + "hook.message = boom", {"hook_event_name": "SessionStart"}),
    ("merge_confirm.py", RAISE + "hook.merging_commands = boom", bash("gh pr merge 5")),
])
def test_an_error_in_the_last_step_writes_nothing(name, patch, payload):
    assert driven(name, patch, payload) == (0, b"", b"")


def test_merge_confirm_parses_the_command_once_for_both_checks(monkeypatch, capsys):
    hook = hook_module("merge_confirm.py")
    walk, parses = hook.walk, []

    def counted(text, depth, visit):
        parses.append(depth)
        return walk(text, depth, visit)

    monkeypatch.setattr(hook, "walk", counted)
    monkeypatch.setattr(hook.sys, "stdin", types.SimpleNamespace(buffer=io.BytesIO(json.dumps(bash("gh pr merge 5 -s")).encode())))
    handler = signal.getsignal(signal.SIGALRM)
    try:
        hook.main()
    finally:
        signal.alarm(0)
        signal.signal(signal.SIGALRM, handler)
    assert parses == [0]
    assert json.loads(capsys.readouterr().out)["hookSpecificOutput"]["permissionDecisionReason"] == hook.SQUASH_REASON


def test_a_slow_repo_scan_still_prints_the_host_profile_line(machine, repo):
    home, env, tmp = machine
    jira_project(tmp)
    # Every git call hangs until its budget runs out, as on a huge or stalled repo.
    patch = (
        "import time\n"
        "def slow(name, args, env, deadline, cwd=None):\n"
        "    time.sleep(max(0, deadline - time.monotonic()))\n"
        "hook.run_tool = slow\n"
    )
    done = subprocess.run(
        [sys.executable, "-I", "-B", "-c", DRIVER, str(home / "hooks" / "host_default.py"), patch],
        input=json.dumps({"hook_event_name": "SessionStart", "cwd": str(repo)}).encode(),
        capture_output=True, timeout=20, check=False, env={"PATH": "/usr/bin:/bin", **env},
    )
    assert (done.returncode, done.stderr) == (0, b"")
    assert from_profile(json.loads(done.stdout)["hookSpecificOutput"]["additionalContext"])


def test_merge_confirm_past_its_deadline_writes_nothing():
    patch = "import time\nhook.DEADLINE_SECONDS = 1\nhook.merges_a_pr = lambda command: time.sleep(5)\n"
    assert driven("merge_confirm.py", patch, bash("gh pr merge 5")) == (0, b"", b"")
