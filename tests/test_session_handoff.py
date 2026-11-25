"""handoff_stop.py: the Stop hook that hands a session off to a fresh context (ADR-0019).

Each test runs the hook as Claude Code does (a subprocess fed a JSON payload), with a fake `tmux`
on PATH that logs its argv, and the sender's delays set to zero through the DRIVER pattern.
"""

from __future__ import annotations

import json
import os
import pathlib
import subprocess
import sys
import time

import pytest

from tests.conftest import ROOT

HOOK = ROOT / "config" / "hooks" / "handoff_stop.py"
SID = "0b1e2f3a-4c5d-4e6f-8a9b-0c1d2e3f4a5b"
PANE = "%7"
NO_TOOLS = "/nonexistent-bin"  # a PATH with no tmux or claude; CI images ship tmux in /usr/bin

# Runs the hook's main() as its __main__ block does, with the sender's delays at zero.
DRIVER = """
import importlib.util, sys
spec = importlib.util.spec_from_file_location("hook", sys.argv[1])
hook = importlib.util.module_from_spec(spec)
spec.loader.exec_module(hook)
hook.CLEAR_DELAY = hook.PROMPT_DELAY = 0
try:
    hook.main()
finally:
    sys.exit(0)
"""


@pytest.fixture
def env(tmp_path):
    """A project with an empty handoffs dir, a fake tmux that logs argv, and an interactive tmux session."""
    project = tmp_path / "project"
    (project / ".omc" / "handoffs").mkdir(parents=True)
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    log = tmp_path / "tmux.log"
    tmux = bin_dir / "tmux"
    tmux.write_text(f'#!/bin/sh\nprintf "%s\\n" "$*" >> {log}\n')
    tmux.chmod(0o755)
    claude_log = tmp_path / "claude.log"
    claude = bin_dir / "claude"
    claude.write_text(f'#!/bin/sh\nprintf "%s|%s\\n" "$PWD" "$*" >> {claude_log}\necho out; echo err >&2\n')
    claude.chmod(0o755)
    return {
        "PATH": f"{bin_dir}:/usr/bin:/bin",
        "HOME": os.environ["HOME"],
        "CLAUDE_CODE_ENTRYPOINT": "cli",
        "TMUX_PANE": PANE,
        "CLAUDE_PROJECT_DIR": str(project),
        "OMC_STATE_DIR": str(tmp_path / "omc"),
        "_project": project,
        "_log": log,
        "_claude_log": claude_log,
        "_bin": bin_dir,
    }


def run(env, payload):
    """Exit code, stdout and stderr of the hook fed `payload`."""
    real_env = {k: v for k, v in env.items() if not k.startswith("_")}
    stdin = payload if isinstance(payload, bytes) else json.dumps(payload).encode()
    done = subprocess.run(
        [sys.executable, "-I", "-B", "-c", DRIVER, str(HOOK)],
        input=stdin, capture_output=True, env=real_env, timeout=10, check=False,
    )
    return done.returncode, done.stdout, done.stderr


def stop(**extra):
    return {"hook_event_name": "Stop", "session_id": SID, "stop_hook_active": False, **extra}


def note(env, sid=SID):
    path = env["_project"] / ".omc" / "handoffs" / f"{sid}.md"
    path.write_text("next skill: /oh-my-claudecode:ralplan spec.md\n")
    return path


def sent(env, lines=3, wait=5.0):
    """The tmux calls the detached sender made, once it has made `lines` of them (or the wait ran out)."""
    deadline = time.monotonic() + wait
    while time.monotonic() < deadline:
        if env["_log"].exists() and len(env["_log"].read_text().splitlines()) >= lines:
            break
        time.sleep(0.05)
    return env["_log"].read_text().splitlines() if env["_log"].exists() else []


def nothing_sent(env):
    time.sleep(0.5)  # long enough for a detached sender with zero delays to have logged
    return not env["_log"].exists()


# Send path

def test_a_note_in_tmux_sends_clear_then_a_prompt_naming_the_note(env):
    path = note(env)
    assert run(env, stop()) == (0, b"", b"")
    calls = sent(env)
    assert calls[0] == f"send-keys -t {PANE} /clear Enter"
    assert calls[1].startswith(f"send-keys -t {PANE} -l ")
    assert str(path) in calls[1]
    assert calls[2] == f"send-keys -t {PANE} Enter"
    assert (path.parent / f"{SID}.sent").exists()


def test_the_send_path_ignores_stop_hook_active(env):
    note(env)
    assert run(env, stop(stop_hook_active=True)) == (0, b"", b"")
    assert len(sent(env)) == 3


def test_two_stops_for_one_note_send_once(env):
    note(env)
    run(env, stop())
    run(env, stop())
    time.sleep(0.5)
    assert len(sent(env)) == 3


@pytest.mark.parametrize("change", [
    {"CLAUDE_CODE_ENTRYPOINT": "sdk-cli"},
    {"CLAUDE_CODE_ENTRYPOINT": None},
    {"TMUX_PANE": None},
    {"TMUX_PANE": "%7;x"},
    {"TMUX_PANE": "main:0"},
    {"PATH": NO_TOOLS},  # no tmux
], ids=["sdk-cli", "no-entrypoint", "no-pane", "pane-injection", "pane-name", "no-tmux"])
def test_nothing_is_sent_outside_an_interactive_tmux_session(env, change):
    note(env)
    for key, value in change.items():
        if value is None:
            env.pop(key)
        else:
            env[key] = value
    assert run(env, stop()) == (0, b"", b"")
    assert nothing_sent(env)


def test_nothing_is_sent_without_a_note(env):
    assert run(env, stop()) == (0, b"", b"")
    assert nothing_sent(env)


def test_another_sessions_note_is_not_sent(env):
    note(env, sid="another-session")
    assert run(env, stop()) == (0, b"", b"")
    assert nothing_sent(env)


@pytest.mark.parametrize("sid", ["../escape", "", "a/b", 7, None])
def test_an_invalid_session_id_sends_nothing(env, sid):
    note(env)
    assert run(env, stop(session_id=sid)) == (0, b"", b"")
    assert nothing_sent(env)


def test_the_project_dir_falls_back_to_the_payload_cwd(env):
    path = note(env)
    project = str(env.pop("CLAUDE_PROJECT_DIR"))
    assert run(env, stop(cwd=project)) == (0, b"", b"")
    assert str(path) in sent(env)[1]


def test_no_note_text_reaches_the_pane(env):
    path = note(env)
    path.write_text("!rm -rf ~\n/oh-my-claudecode:cancel\n")
    run(env, stop())
    assert not any("rm -rf" in call or "cancel" in call for call in sent(env))


@pytest.mark.parametrize("stdin", [b"", b"{", b"null", b"[]", b"\xff\xfe", b'{"hook_event_name": "Stop"}',
                                   b'{"hook_event_name": "Stop", "session_id": {}}'])
def test_malformed_input_exits_0_with_no_output(env, stdin):
    note(env)
    assert run(env, stdin) == (0, b"", b"")
    assert nothing_sent(env)


def test_other_events_are_ignored(env):
    note(env)
    assert run(env, stop(hook_event_name="SubagentStop")) == (0, b"", b"")
    assert nothing_sent(env)


# Context-limit path. The limit is min(60% of the window, 300,000 tokens): 120,000 for a
# 200k window, 300,000 for a 1M window.

def cache(env, *, window, usage=None, percentage=None, where="project"):
    """Write the OMC HUD statusline cache for this session, in the project or under OMC_STATE_DIR."""
    context = {"context_window_size": window}
    if usage is not None:
        # Output tokens are not context; a large count here must not change the result.
        context["current_usage"] = {"input_tokens": 1, "output_tokens": 999_999,
                                    "cache_creation_input_tokens": 1000, "cache_read_input_tokens": usage - 1001}
    if percentage is not None:
        context["used_percentage"] = percentage
    root = env["_project"] / ".omc" if where == "project" else pathlib.Path(env["OMC_STATE_DIR"]) / "proj-1a2b"
    path = root / "state" / "sessions" / SID / "hud-stdin-cache.json"
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps({"session_id": SID, "context_window": context}))
    return path


def blocked(result):
    code, out, err = result
    assert (code, err) == (0, b"")
    if not out:
        return False
    decision = json.loads(out)
    assert decision["decision"] == "block"
    assert "session-handoff" in decision["reason"]
    return True


@pytest.mark.parametrize("window,usage,expected", [
    (200_000, 119_999, False), (200_000, 120_000, True),
    (1_000_000, 299_999, False), (1_000_000, 300_000, True),
])
def test_the_limit_is_60_percent_or_300k_tokens_whichever_is_smaller(env, window, usage, expected):
    cache(env, window=window, usage=usage)
    assert blocked(run(env, stop())) is expected
    assert nothing_sent(env)


@pytest.mark.parametrize("percentage,expected", [(59, False), (60, True)])
def test_used_percentage_counts_when_current_usage_is_absent(env, percentage, expected):
    cache(env, window=200_000, percentage=percentage)
    assert blocked(run(env, stop())) is expected


def test_the_cache_under_omc_state_dir_is_found(env):
    cache(env, window=200_000, usage=150_000, where="state_dir")
    assert blocked(run(env, stop()))


def test_the_limit_blocks_once_per_session(env):
    cache(env, window=200_000, usage=150_000)
    assert blocked(run(env, stop()))
    assert not blocked(run(env, stop()))


def test_a_reentrant_stop_is_not_blocked(env):
    cache(env, window=200_000, usage=150_000)
    assert not blocked(run(env, stop(stop_hook_active=True)))


def test_a_written_note_sends_instead_of_blocking(env):
    cache(env, window=200_000, usage=150_000)
    note(env)
    assert not blocked(run(env, stop()))
    assert len(sent(env)) == 3


@pytest.mark.parametrize("change", [{"CLAUDE_CODE_ENTRYPOINT": "sdk-cli"}, {"TMUX_PANE": None}, {"PATH": NO_TOOLS}],
                         ids=["sdk-cli", "no-pane", "no-tmux"])
def test_no_block_outside_an_interactive_tmux_session(env, change):
    cache(env, window=200_000, usage=150_000)
    for key, value in change.items():
        if value is None:
            env.pop(key)
        else:
            env[key] = value
    assert not blocked(run(env, stop()))


@pytest.mark.parametrize("content", [
    None, "{", "null", '{"context_window": null}',
    '{"context_window": {"context_window_size": null, "used_percentage": 90}}',
    '{"context_window": {"context_window_size": 200000, "used_percentage": "90"}}',
], ids=["missing", "malformed", "null", "null-window", "null-size", "string-percentage"])
def test_a_missing_or_malformed_cache_is_silent(env, content):
    if content is not None:
        cache(env, window=200_000, usage=150_000).write_text(content)
    assert not blocked(run(env, stop()))


# Background-job route (issue #103): a `claude --bg` job has CLAUDE_JOB_DIR and no pane, so the
# hook starts a new background job with the prompt instead of typing into tmux.

def bg(env, **changes):
    """The env of a background job: no pane, a job dir, then `changes` (None removes a key)."""
    env.pop("TMUX_PANE")
    env["CLAUDE_JOB_DIR"] = str(env["_project"].parent / "job")
    for key, value in changes.items():
        if value is None:
            env.pop(key, None)
        else:
            env[key] = value
    return env


def jobs(env, lines=1, wait=5.0):
    """The `claude` calls the hook made, as (cwd, args), once there are `lines` of them (or the wait ran out)."""
    log = env["_claude_log"]
    deadline = time.monotonic() + wait
    while time.monotonic() < deadline and not (log.exists() and len(log.read_text().splitlines()) >= lines):
        time.sleep(0.05)
    return [tuple(line.split("|", 1)) for line in log.read_text().splitlines()] if log.exists() else []


def no_job(env):
    time.sleep(0.5)  # long enough for a detached launch to have logged
    return not env["_claude_log"].exists()


def test_a_note_in_a_background_job_starts_a_new_background_job_naming_the_note(env):
    path = note(bg(env))
    assert run(env, stop()) == (0, b"", b"")
    [(cwd, args)] = jobs(env)
    assert pathlib.Path(cwd).resolve() == env["_project"].resolve()
    assert args.startswith("--bg Read ")
    assert str(path) in args
    assert (path.parent / f"{SID}.sent").exists()
    assert nothing_sent(env)


def test_two_stops_for_one_note_start_one_background_job(env):
    note(bg(env))
    run(env, stop())
    run(env, stop())
    time.sleep(0.5)
    assert len(jobs(env)) == 1


def test_the_background_launch_ignores_stop_hook_active(env):
    note(bg(env))
    run(env, stop(stop_hook_active=True))
    assert len(jobs(env)) == 1


def test_tmux_wins_when_a_session_has_both_a_pane_and_a_job_dir(env):
    env["CLAUDE_JOB_DIR"] = str(env["_project"].parent / "job")
    note(env)
    run(env, stop())
    assert len(sent(env)) == 3
    assert no_job(env)


@pytest.mark.parametrize("change", [
    {"TMUX_PANE": "%7;x"},
    {"TMUX_PANE": ""},
], ids=["invalid-pane", "empty-pane"])
def test_a_job_with_an_unusable_pane_starts_a_background_job(env, change):
    note(bg(env, **change))
    run(env, stop())
    assert len(jobs(env)) == 1


def test_a_job_without_tmux_on_path_starts_a_background_job(env):
    bin_dir = env["_bin"]
    (bin_dir / "tmux").unlink()
    note(bg(env))
    run(env, stop())
    assert len(jobs(env)) == 1


@pytest.mark.parametrize("change", [
    {"CLAUDE_CODE_ENTRYPOINT": "sdk-cli"},
    {"CLAUDE_CODE_ENTRYPOINT": None},
    {"CLAUDE_JOB_DIR": None},
    {"CLAUDE_JOB_DIR": ""},
    {"PATH": NO_TOOLS},  # no claude
], ids=["sdk-cli", "no-entrypoint", "no-job-dir", "empty-job-dir", "no-claude"])
def test_nothing_is_started_outside_an_interactive_background_job(env, change):
    note(bg(env, **change))
    assert run(env, stop()) == (0, b"", b"")
    assert no_job(env)
    assert nothing_sent(env)


@pytest.mark.parametrize("sid", ["../escape", "a/b", None])
def test_an_invalid_session_id_starts_no_background_job(env, sid):
    note(bg(env))
    assert run(env, stop(session_id=sid)) == (0, b"", b"")
    assert no_job(env)
    assert nothing_sent(env)


def test_no_note_text_reaches_the_background_job(env):
    path = note(bg(env))
    path.write_text("!rm -rf ~\n/oh-my-claudecode:cancel\n")
    run(env, stop())
    assert not any("rm -rf" in args or "cancel" in args for _, args in jobs(env))


def test_the_limit_blocks_once_in_a_background_job(env):
    cache(bg(env), window=200_000, usage=150_000)
    assert blocked(run(env, stop()))
    assert not blocked(run(env, stop()))


@pytest.mark.parametrize("change", [{"CLAUDE_CODE_ENTRYPOINT": "sdk-cli"}, {"PATH": NO_TOOLS}],
                         ids=["sdk-cli", "no-claude"])
def test_no_block_in_a_background_job_that_cannot_hand_off(env, change):
    cache(bg(env, **change), window=200_000, usage=150_000)
    assert not blocked(run(env, stop()))
