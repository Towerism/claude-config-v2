"""auto_sync: at session start, the deployed config follows main on origin through a dedicated clone.

Each test builds its own world in a temp dir: a bare `origin`, a checkout of this repo's config,
tools and hosts pushed to it, and a Claude home deployed from that checkout (which creates the
sync clone). Nothing touches the network or the real home.
"""

import fcntl
import json
import os
import shutil
import signal
import subprocess
import sys
import time
import types

import pytest

from tests.conftest import ROOT

GIT_ENV = {
    "GIT_AUTHOR_NAME": "T", "GIT_AUTHOR_EMAIL": "t@example.com",
    "GIT_COMMITTER_NAME": "T", "GIT_COMMITTER_EMAIL": "t@example.com",
    "PATH": "/usr/bin:/bin", "HOME": "/nonexistent",
}
STARTUP = {"hook_event_name": "SessionStart", "source": "startup"}
RELOAD = {"hookSpecificOutput": {"hookEventName": "SessionStart", "reloadSkills": True}}
SKILL = "skills/fresh-session-handoff/SKILL.md"

# Runs the hook's main() as its __main__ block does, after `patch` (Python source) has run.
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


def git(repo, *args):
    return subprocess.run(
        ["git", "-C", str(repo), *args], check=True, capture_output=True, text=True, env=GIT_ENV
    ).stdout.strip()


@pytest.fixture
def world(tmp_path):
    w = types.SimpleNamespace(
        origin=tmp_path / "origin.git", seed=tmp_path / "seed", claude=tmp_path / "claude",
        clone=tmp_path / "data" / "claude-config", xdg=tmp_path / "xdg", mark=tmp_path / "git-ran",
    )
    w.env = {
        "PATH": "/usr/bin:/bin", "HOME": str(tmp_path / "home"),
        "XDG_CONFIG_HOME": str(w.xdg), "XDG_DATA_HOME": str(tmp_path / "data"),
    }
    subprocess.run(["git", "init", "-q", "--bare", "-b", "main", str(w.origin)], check=True, env=GIT_ENV)
    w.seed.mkdir()
    for part in ("config", "tools", "hosts"):
        shutil.copytree(ROOT / part, w.seed / part, ignore=shutil.ignore_patterns("__pycache__", ".omc"))
    git(w.seed, "init", "-q", "-b", "main")
    git(w.seed, "add", "-A")
    git(w.seed, "commit", "-q", "-m", "chore: base")
    git(w.seed, "remote", "add", "origin", str(w.origin))
    git(w.seed, "push", "-q", "origin", "main")
    done = cfg(w, w.seed, "deploy", "--host", "personal", "--yes")
    assert done.returncode == 0, done.stdout + done.stderr
    return w


def cfg(w, checkout, *args):
    return subprocess.run(
        [sys.executable, "-I", str(checkout / "tools" / "cfg.py"), *args, "--target", str(w.claude)],
        capture_output=True, text=True, env=w.env, timeout=60, check=False,
    )


def state(w):
    return json.loads((w.claude / "claude-config" / "state.json").read_text())


def merge_to_main(w, rel="config/skills/fresh-session-handoff/SKILL.md", text="\nMerged line.\n", force=False):
    """A change lands on origin's main, as after a merged PR (a force-push with `force`)."""
    path = w.seed / rel
    path.write_text(path.read_text() + text)
    git(w.seed, "add", "-A")
    if force:
        git(w.seed, "commit", "-q", "--amend", "-m", "chore: rewritten")
        git(w.seed, "push", "-q", "--force", "origin", "main")
    else:
        git(w.seed, "commit", "-q", "-m", "feat: change")
        git(w.seed, "push", "-q", "origin", "main")
    return git(w.seed, "rev-parse", "HEAD")


def hook(w, payload=STARTUP, patch=None):
    """(exit code, stdout, stderr) of the deployed hook; `patch` runs first, in its module."""
    script = str(w.claude / "hooks" / "auto_sync.py")
    argv = [sys.executable, "-I", script] if patch is None else [sys.executable, "-I", "-B", "-c", DRIVER, script, patch]
    done = subprocess.run(argv, input=json.dumps(payload).encode(), capture_output=True, env=w.env, timeout=60, check=False)
    return done.returncode, done.stdout, done.stderr


def no_git(w):
    """A patch that records any process the hook would start, and refuses to start it."""
    return (
        "def refuse(*args, **kwargs):\n"
        f"    open({str(w.mark)!r}, 'w').close()\n"
        "    raise OSError('refused')\n"
        "hook.subprocess.Popen = refuse\n"
    )


def snapshot(w):
    """Every file in the Claude home but the hook's own lock, with its bytes."""
    return {
        p.relative_to(w.claude).as_posix(): p.read_bytes()
        for p in w.claude.rglob("*")
        if p.is_file() and p.name != "sync.lock"
    }


def warned(out, reason):
    message = json.loads(out)
    assert list(message) == ["systemMessage"]
    assert reason in message["systemMessage"]
    return message["systemMessage"]


def last_log_line(w):
    return (w.claude / "claude-config" / "sync.log").read_text().splitlines()[-1]


# --- the clone a deploy sets up ----------------------------------------------------------


def test_a_first_deploy_creates_the_sync_clone_from_origin_and_records_it(world):
    w = world
    assert state(w)["syncClone"] == str(w.clone)
    assert git(w.clone, "remote", "get-url", "origin") == str(w.origin)
    assert git(w.clone, "symbolic-ref", "--short", "HEAD") == "main"
    assert git(w.clone, "rev-parse", "HEAD") == git(w.seed, "rev-parse", "HEAD")


def test_a_later_deploy_reuses_the_clone(world):
    w = world
    (w.clone / "kept.txt").write_text("still here")
    merge_to_main(w)
    assert cfg(w, w.seed, "deploy", "--yes").returncode == 0
    assert (w.clone / "kept.txt").read_text() == "still here"
    assert state(w)["syncClone"] == str(w.clone)


def fresh(w, tmp_path, name="other"):
    """The same world with an empty Claude home and no sync clone yet."""
    shutil.rmtree(w.clone)
    return types.SimpleNamespace(**{**vars(w), "claude": tmp_path / name})


def test_the_clone_comes_from_origin_not_from_the_local_main(world, tmp_path):
    w = world
    (w.seed / "local.txt").write_text("not pushed")
    git(w.seed, "add", "-A")
    git(w.seed, "commit", "-q", "-m", "chore: local only")
    other = fresh(w, tmp_path)
    assert cfg(other, w.seed, "deploy", "--host", "personal", "--yes").returncode == 0
    assert git(w.clone, "rev-parse", "main") == git(w.origin, "rev-parse", "main")
    assert git(w.clone, "rev-parse", "main") != git(w.seed, "rev-parse", "HEAD")
    assert not (w.clone / "local.txt").exists()


def test_an_unreachable_origin_leaves_no_clone_and_the_next_deploy_retries(world, tmp_path):
    w = world
    other = fresh(w, tmp_path)
    git(w.seed, "remote", "set-url", "origin", str(tmp_path / "gone.git"))
    done = cfg(other, w.seed, "deploy", "--host", "personal", "--yes")
    assert done.returncode == 0 and "warning" in done.stdout
    assert "syncClone" not in json.loads((other.claude / "claude-config" / "state.json").read_text())
    assert not w.clone.exists()
    git(w.seed, "remote", "set-url", "origin", str(w.origin))
    assert cfg(other, w.seed, "deploy", "--yes").returncode == 0
    assert json.loads((other.claude / "claude-config" / "state.json").read_text())["syncClone"] == str(w.clone)


def test_a_deploy_reuses_the_recorded_clone_wherever_it_is(world, tmp_path):
    w = world
    moved = tmp_path / "elsewhere" / "clone"
    moved.parent.mkdir()
    w.clone.rename(moved)
    data = state(w)
    data["syncClone"] = str(moved)
    (w.claude / "claude-config" / "state.json").write_text(json.dumps(data))
    merge_to_main(w)
    assert cfg(w, w.seed, "deploy", "--yes").returncode == 0
    assert state(w)["syncClone"] == str(moved) and not w.clone.exists()


def test_a_manual_deploy_that_cannot_fetch_warns_and_still_deploys(world, tmp_path):
    w = world
    git(w.clone, "remote", "set-url", "origin", str(tmp_path / "gone.git"))
    merge_to_main(w)
    done = cfg(w, w.seed, "deploy", "--yes")
    assert done.returncode == 0 and "warning" in done.stdout
    assert (w.claude / SKILL).read_text().endswith("\nMerged line.\n")


def test_a_checkout_without_origin_still_deploys_and_records_no_clone(world, tmp_path):
    w = world
    plain = tmp_path / "plain"
    shutil.copytree(w.seed, plain, ignore=shutil.ignore_patterns(".git"))
    git(plain, "init", "-q", "-b", "main")
    git(plain, "add", "-A")
    git(plain, "commit", "-q", "-m", "chore: base")
    shutil.rmtree(w.clone)
    other = types.SimpleNamespace(**{**vars(w), "claude": tmp_path / "other"})
    done = cfg(other, plain, "deploy", "--host", "personal", "--yes")
    assert done.returncode == 0
    assert "warning" in done.stdout and "origin" in done.stdout
    assert "syncClone" not in json.loads((other.claude / "claude-config" / "state.json").read_text())
    assert not w.clone.exists()


# --- a session start ---------------------------------------------------------------------


def test_a_session_start_deploys_what_was_merged_to_main(world):
    w = world
    before = state(w)["deployedAt"]
    head = merge_to_main(w)
    code, out, err = hook(w)
    assert (code, err) == (0, b"")
    assert json.loads(out) == RELOAD
    assert (w.claude / SKILL).read_text().endswith("\nMerged line.\n")
    assert git(w.clone, "rev-parse", "main") == head
    after = state(w)
    assert after["deployedAt"] != before and after["host"] == "personal" and after["syncClone"] == str(w.clone)


def test_a_session_start_with_nothing_new_changes_nothing(world):
    w = world
    before = snapshot(w)
    assert hook(w) == (0, b"", b"")
    assert snapshot(w) == before


def test_a_hand_edit_is_overwritten_and_rollback_restores_it(world):
    w = world
    (w.claude / SKILL).write_text("my edit")
    code, out, _ = hook(w)
    assert code == 0 and json.loads(out) == RELOAD
    assert (w.claude / SKILL).read_text() == (w.seed / "config" / SKILL).read_text()
    assert cfg(w, w.seed, "rollback").returncode == 0
    assert (w.claude / SKILL).read_text() == "my edit"


def test_a_failed_fetch_keeps_the_config_logs_and_warns(world, tmp_path):
    w = world
    merge_to_main(w)
    git(w.clone, "remote", "set-url", "origin", str(tmp_path / "gone.git"))
    before = snapshot(w)
    code, out, err = hook(w)
    assert (code, err) == (0, b"")
    warned(out, "fetch-failed")
    assert last_log_line(w).endswith(" fetch-failed")
    assert {k: v for k, v in snapshot(w).items() if k != "claude-config/sync.log"} == before


def test_a_fetch_past_its_deadline_starts_no_deploy(world):
    w = world
    merge_to_main(w)
    before = snapshot(w)
    code, out, err = hook(w, patch="hook.FETCH_SECONDS = 0\n")
    assert (code, err) == (0, b"")
    warned(out, "timeout")
    assert last_log_line(w).endswith(" timeout")
    assert {k: v for k, v in snapshot(w).items() if k != "claude-config/sync.log"} == before


def test_a_started_deploy_outlasts_the_fetch_deadline(world):
    w = world
    # The merged cfg.py takes longer than the whole fetch deadline before it deploys.
    slow = (w.seed / "tools" / "cfg.py").read_text().replace("\nROOT = ", "\ntime.sleep(2)\nROOT = ", 1)
    (w.seed / "tools" / "cfg.py").write_text(slow)
    merge_to_main(w)
    start = time.monotonic()
    code, out, err = hook(w, patch="hook.FETCH_SECONDS = 1\n")
    assert time.monotonic() - start >= 2
    assert (code, err) == (0, b"")
    assert json.loads(out) == RELOAD
    assert (w.claude / SKILL).read_text().endswith("\nMerged line.\n")


def test_a_main_that_cannot_fast_forward_is_not_applied(world):
    w = world
    old = git(w.clone, "rev-parse", "main")
    merge_to_main(w, force=True)
    before = snapshot(w)
    code, out, err = hook(w)
    assert (code, err) == (0, b"")
    assert "make deploy YES=1" in warned(out, "diverged")
    assert last_log_line(w).endswith(" diverged")
    assert git(w.clone, "rev-parse", "main") == old
    assert {k: v for k, v in snapshot(w).items() if k != "claude-config/sync.log"} == before
    # The repair the warning names: a manual deploy resets the clone's main to origin's.
    assert cfg(w, w.seed, "deploy", "--yes").returncode == 0
    assert git(w.clone, "rev-parse", "main") == git(w.origin, "rev-parse", "main")
    code, out, _ = hook(w)
    assert code == 0 and b"systemMessage" not in out


def read_only_claude_md(w, tmp_path):
    """CLAUDE.md as a link into a read-only directory: a deploy fails after it has written files."""
    shelf = tmp_path / "shelf"
    shelf.mkdir()
    (shelf / "CLAUDE.md").write_bytes((w.claude / "CLAUDE.md").read_bytes())
    (w.claude / "CLAUDE.md").unlink()
    (w.claude / "CLAUDE.md").symlink_to(shelf / "CLAUDE.md")
    shelf.chmod(0o555)
    return shelf


def test_a_deploy_that_fails_midway_is_rolled_back(world, tmp_path):
    w = world
    shelf = read_only_claude_md(w, tmp_path)
    try:
        merge_to_main(w)
        before = snapshot(w)
        code, out, err = hook(w)
        assert (code, err) == (0, b"")
        text = warned(out, "deploy-rolled-back")
        assert "current config stays" not in text
        assert last_log_line(w).endswith(" deploy-rolled-back")
        assert {k: v for k, v in snapshot(w).items() if k != "claude-config/sync.log"} == before
    finally:
        shelf.chmod(0o755)


def test_a_deploy_that_fails_midway_and_cannot_roll_back_says_so(world, tmp_path):
    w = world
    shelf = read_only_claude_md(w, tmp_path)
    no_rollback = (
        "real = hook.run\n"
        "def run(argv, *args, **kwargs):\n"
        "    return 1 if 'rollback' in argv else real(argv, *args, **kwargs)\n"
        "hook.run = run\n"
    )
    try:
        merge_to_main(w)
        code, out, err = hook(w, patch=no_rollback)
        assert (code, err) == (0, b"")
        text = warned(out, "deploy-failed-partial")
        assert "make rollback" in text and "current config stays" not in text
        assert last_log_line(w).endswith(" deploy-failed-partial")
    finally:
        shelf.chmod(0o755)


def test_a_clone_others_can_write_to_is_not_run(world):
    w = world
    (w.clone / "tools" / "cfg.py").chmod(0o666)
    merge_to_main(w)
    before = snapshot(w)
    code, out, err = hook(w)
    assert (code, err) == (0, b"")
    warned(out, "unsafe-clone")
    assert {k: v for k, v in snapshot(w).items() if k != "claude-config/sync.log"} == before


def test_untracked_files_in_the_clone_are_not_deployed(world):
    w = world
    (w.clone / "config" / "skills" / "fresh-session-handoff" / "planted.md").write_text("planted")
    merge_to_main(w)
    code, out, _ = hook(w)
    assert code == 0 and json.loads(out) == RELOAD
    assert not (w.claude / "skills" / "fresh-session-handoff" / "planted.md").exists()


def test_a_failed_deploy_is_reported(world):
    w = world
    broken = (w.seed / "tools" / "cfg.py").read_text().replace("\nROOT = ", "\nsys.exit(3)\nROOT = ", 1)
    (w.seed / "tools" / "cfg.py").write_text(broken)
    merge_to_main(w)
    before = snapshot(w)
    code, out, err = hook(w)
    assert (code, err) == (0, b"")
    assert "current config stays" in warned(out, "deploy-failed")
    assert last_log_line(w).endswith(" deploy-failed")
    assert {k: v for k, v in snapshot(w).items() if k != "claude-config/sync.log"} == before


def test_the_warning_and_log_hold_only_fixed_words(world, tmp_path):
    w = world
    git(w.clone, "remote", "set-url", "origin", str(tmp_path / "LEAKCANARY.git"))
    _, out, _ = hook(w)
    text = warned(out, "fetch-failed")
    log = (w.claude / "claude-config" / "sync.log").read_text()
    assert "LEAKCANARY" not in text + log and str(tmp_path) not in text + log


def test_the_log_keeps_only_its_last_lines(world, tmp_path):
    w = world
    (w.claude / "claude-config" / "sync.log").write_text("".join(f"old {i}\n" for i in range(500)))
    git(w.clone, "remote", "set-url", "origin", str(tmp_path / "gone.git"))
    hook(w)
    lines = (w.claude / "claude-config" / "sync.log").read_text().splitlines()
    assert len(lines) == 200 and lines[0] == "old 301" and lines[-1].endswith(" fetch-failed")


# --- when it does nothing ----------------------------------------------------------------


def test_opting_out_runs_no_git_and_changes_nothing(world):
    w = world
    (w.xdg / "claude-config").mkdir(parents=True)
    (w.xdg / "claude-config" / "local.json").write_text(json.dumps({"autoSync": False}))
    merge_to_main(w)
    before = snapshot(w)
    assert hook(w, patch=no_git(w)) == (0, b"", b"")
    assert not w.mark.exists()
    assert snapshot(w) == before
    assert hook(w) == (0, b"", b"")  # unpatched too: nothing is fetched or deployed
    assert snapshot(w) == before and not (w.clone / ".git" / "FETCH_HEAD").exists()


@pytest.mark.parametrize("recorded", [None, "missing", "relative"])
def test_without_a_recorded_clone_it_does_nothing(world, tmp_path, recorded):
    w = world
    data = state(w)
    if recorded is None:
        del data["syncClone"]
    else:
        data["syncClone"] = str(tmp_path / "nowhere") if recorded == "missing" else "data/claude-config"
    (w.claude / "claude-config" / "state.json").write_text(json.dumps(data))
    merge_to_main(w)
    assert hook(w, patch=no_git(w)) == (0, b"", b"")
    assert not w.mark.exists()


@pytest.mark.parametrize("payload", [
    {"hook_event_name": "SessionStart", "source": "resume"},
    {"hook_event_name": "SessionStart", "source": "clear"},
    {"hook_event_name": "SubagentStart"},
    [],
])
def test_only_a_new_session_syncs(world, payload):
    w = world
    merge_to_main(w)
    assert hook(w, payload, patch=no_git(w)) == (0, b"", b"")
    assert not w.mark.exists()


def test_a_held_lock_makes_it_skip_quietly(world):
    w = world
    merge_to_main(w)
    with open(w.claude / "claude-config" / "sync.lock", "a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        assert hook(w, patch=no_git(w)) == (0, b"", b"")
    assert not w.mark.exists()


def slow_deploy(w, tmp_path):
    """Merges a cfg.py that marks its start, then waits 3 s before it deploys; returns the mark."""
    started = tmp_path / "deploy-started"
    cfg_py = w.seed / "tools" / "cfg.py"
    cfg_py.write_text(cfg_py.read_text().replace(
        "\nROOT = ", f"\nPath({str(started)!r}).touch()\ntime.sleep(3)\nROOT = ", 1
    ))
    merge_to_main(w)
    return started


def start_hook(w):
    proc = subprocess.Popen(
        [sys.executable, "-I", str(w.claude / "hooks" / "auto_sync.py")],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=w.env,
    )
    proc.stdin.write(json.dumps(STARTUP).encode())
    proc.stdin.close()
    return proc


def finish(proc):
    """(exit code, stdout, stderr) of a hook started with start_hook."""
    out, err = proc.stdout.read(), proc.stderr.read()
    proc.stdout.close()
    proc.stderr.close()
    return proc.wait(timeout=60), out, err


def wait_for(condition, seconds=30):
    end = time.monotonic() + seconds
    while not condition():
        assert time.monotonic() < end, "timed out"
        time.sleep(0.05)


def test_a_session_start_during_a_deploy_skips_it(world, tmp_path):
    w = world
    started = slow_deploy(w, tmp_path)
    backups = w.claude / "claude-config" / "backups"
    count = len(list(backups.iterdir()))
    first = start_hook(w)
    wait_for(started.exists)
    begin = time.monotonic()
    assert hook(w) == (0, b"", b"")
    assert time.monotonic() - begin < 2  # it skipped; it did not run a deploy of its own
    code, out, err = finish(first)
    assert (code, err) == (0, b"") and json.loads(out) == RELOAD
    assert len(list(backups.iterdir())) == count + 1


def test_a_deploy_keeps_the_lock_after_its_hook_is_killed(world, tmp_path):
    w = world
    started = slow_deploy(w, tmp_path)
    before = state(w)["deployedAt"]
    first = start_hook(w)
    wait_for(started.exists)
    os.kill(first.pid, signal.SIGKILL)
    finish(first)
    assert hook(w, patch=no_git(w)) == (0, b"", b"")
    assert not w.mark.exists()
    wait_for(lambda: state(w)["deployedAt"] != before)  # the deploy still finishes


def test_git_runs_without_repo_hooks_or_fsmonitor(world, tmp_path):
    w = world
    marks = tmp_path / "marks"
    marks.mkdir()
    hooks = tmp_path / "githooks"
    hooks.mkdir()
    for name in ("fsmonitor", "post-checkout", "reference-transaction", "post-merge"):
        script = hooks / name
        script.write_text(f"#!/bin/sh\ntouch {marks}/{name}\n")
        script.chmod(0o755)
    git(w.clone, "config", "core.hooksPath", str(hooks))
    git(w.clone, "config", "core.fsmonitor", str(hooks / "fsmonitor"))
    merge_to_main(w)
    code, out, _ = hook(w)
    assert code == 0 and json.loads(out) == RELOAD
    assert list(marks.iterdir()) == []


def test_git_variables_from_the_session_are_ignored(world, tmp_path):
    w = world
    merge_to_main(w)
    w.env = {**w.env, "GIT_DIR": str(tmp_path / "elsewhere"), "GIT_WORK_TREE": str(tmp_path)}
    code, out, _ = hook(w)
    assert code == 0 and json.loads(out) == RELOAD
