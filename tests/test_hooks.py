"""The two hooks: merge_confirm asks before a PR merge; host_default states the tracker."""

import json
import subprocess
import sys

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
    assert "Default issue tracker: jira" in out["additionalContext"] and "work" in out["additionalContext"]
    assert start(home, env, "SubagentStart")["hookEventName"] == "SubagentStart"


def test_local_file_wins_over_the_deploy(machine):
    home, env, tmp = machine
    (tmp / "xdg" / "claude-config").mkdir(parents=True)
    (tmp / "xdg" / "claude-config" / "local.json").write_text(json.dumps({"defaultTracker": "gitea"}))
    assert "tracker: gitea" in start(home, env)["additionalContext"]


@pytest.mark.parametrize("bad", ["gitlab", "Jira; rm -rf", "", 7, None, "a" * 100])
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
