"""global_memory: memories that hold in any repo sync between machines through a private git repo.

Each test builds its own world in a temp dir: a bare `origin` standing in for the memory repo, and
one or more machines, each with its own home, XDG dirs and a Claude home holding the deployed hook.
Nothing touches the network or the real home.
"""

import fcntl
import json
import os
import re
import shutil
import subprocess
import sys
import time
import types
import unicodedata

import pytest

from tests.conftest import ROOT, load
from tests.test_auto_sync import DRIVER, GIT_ENV, git, no_git, warned

# A write into the store: the event that always syncs, so the default for the sync tests.
IN_STORE = "<store>/x.md"  # hook() replaces it with a file in the machine's own store
SYNC = {"hook_event_name": "PostToolUse", "session_id": "s1", "tool_name": "Write", "tool_input": {"file_path": IN_STORE}}
READ = {"hook_event_name": "PreToolUse", "session_id": "s1", "tool_name": "Read", "tool_input": {"file_path": IN_STORE}}
EDIT = {**READ, "tool_name": "Edit"}
PROMPT = {"hook_event_name": "UserPromptSubmit", "session_id": "s1", "prompt": "hi"}
SESSION_END = {"hook_event_name": "SessionEnd", "session_id": "s1"}
STARTUP = {"hook_event_name": "SessionStart", "source": "startup"}
TERM = "AcmeCorp"
HOOK = load(ROOT / "config" / "hooks" / "global_memory.py", "global_memory_constants")
BUDGET = HOOK.BUDGET


@pytest.fixture
def origin(tmp_path):
    path = tmp_path / "origin.git"
    subprocess.run(["git", "init", "-q", "--bare", "-b", "main", str(path)], check=True, env=GIT_ENV)
    return path


def machine(tmp_path, origin, name="a", terms=TERM + "\n"):
    """A machine with the hook deployed, memory.repo set to `origin` and `terms` as deny-terms."""
    root = tmp_path / name
    m = types.SimpleNamespace(
        claude=root / "claude", xdg=root / "xdg", home=root / "home", mark=root / "git-ran",
        store=root / "data" / "claude-memory", origin=origin,
    )
    m.env = {
        "PATH": "/usr/bin:/bin", "HOME": str(m.home),
        "XDG_CONFIG_HOME": str(m.xdg), "XDG_DATA_HOME": str(root / "data"),
    }
    (m.claude / "hooks").mkdir(parents=True)
    shutil.copy(ROOT / "config" / "hooks" / "global_memory.py", m.claude / "hooks")
    (m.xdg / "claude-config").mkdir(parents=True)
    m.home.mkdir()
    if origin is not None:
        (m.xdg / "claude-config" / "local.json").write_text(json.dumps({"memory": {"repo": str(origin)}}))
    if terms is not None:
        (m.xdg / "claude-config" / "deny-terms").write_text(terms)
    return m


def hook(m, payload=SYNC, patch=None, stdin=None):
    """(exit code, stdout, stderr) of the deployed hook; `patch` runs first, in its module."""
    script = str(m.claude / "hooks" / "global_memory.py")
    argv = [sys.executable, "-I", script] if patch is None else [sys.executable, "-I", "-B", "-c", DRIVER, script, patch]
    if isinstance(payload, dict) and payload.get("tool_input") == {"file_path": IN_STORE}:
        payload = {**payload, "tool_input": {"file_path": str(m.store / "x.md")}}
    data = json.dumps(payload).encode() if stdin is None else stdin
    done = subprocess.run(argv, input=data, capture_output=True, env=m.env, timeout=60, check=False)
    return done.returncode, done.stdout, done.stderr


def quiet(m, payload=SYNC, patch=None):
    """Runs the hook, asserts the contract, and returns its parsed output ({} when it printed nothing)."""
    code, out, err = hook(m, payload, patch)
    assert (code, err) == (0, b"")
    return json.loads(out) if out else {}


def remember(m, name, body="Body.\n", description="A rule."):
    m.store.joinpath(name).write_text(f"---\nname: {name[:-3]}\ndescription: {description}\nmetadata:\n  type: feedback\n---\n\n{body}")


def remote_files(origin):
    """The files on origin's main; empty while it has no main."""
    done = subprocess.run(
        ["git", "-C", str(origin), "ls-tree", "-r", "--name-only", "main"],
        capture_output=True, text=True, env=GIT_ENV, check=False,
    )
    return set(done.stdout.splitlines())


def stamp(m, age, name="memory.pulled"):
    """Sets the last sync attempt (or, with memory.failed, the last failure) `age` seconds in the past."""
    path = m.claude / "claude-config" / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.touch()
    then = time.time() - age
    os.utime(path, (then, then))


def started(tmp_path, origin, name="a", **kwargs):
    """A machine whose store was cloned by a first session start."""
    m = machine(tmp_path, origin, name, **kwargs)
    quiet(m, STARTUP)
    assert (m.store / ".git").is_dir()
    return m


# --- the leak guard ----------------------------------------------------------------------


def test_a_memory_naming_a_deny_term_stays_local_and_untracked(tmp_path, origin):
    m = started(tmp_path, origin)
    remember(m, "clean.md")
    remember(m, "denied.md", body="Learned while working for aCMEcORP on the billing app.\n")
    out = quiet(m)
    assert out == {}
    assert remote_files(origin) == {"clean.md"}
    assert (m.store / "denied.md").is_file()
    assert git(m.store, "ls-files", "denied.md") == ""


def test_a_deny_terms_file_with_a_byte_order_mark_still_guards(tmp_path, origin):
    m = started(tmp_path, origin, terms="\ufeff" + TERM + "\n")
    remember(m, "clean.md")
    remember(m, "denied.md", body="About acmecorp.\n")
    assert quiet(m) == {}
    assert remote_files(origin) == {"clean.md"}


def test_a_denied_file_already_committed_is_never_pushed(tmp_path, origin):
    m = started(tmp_path, origin)
    remember(m, "clean.md")
    quiet(m)
    remember(m, "denied.md", body="Notes from the ACMECORP engagement.\n")
    git(m.store, "add", "denied.md")
    git(m.store, "commit", "-q", "-m", "by hand")
    remember(m, "later.md")
    code, out, err = hook(m)
    assert (code, err) == (0, b"")
    text = warned(out, "blocked-files")
    assert TERM.casefold() not in text.casefold() and "denied" not in text
    assert remote_files(origin) == {"clean.md"}
    assert (m.claude / "claude-config" / "memory.log").read_text().splitlines()[-1].endswith(" blocked-files")


@pytest.mark.parametrize("terms", [None, "", "\n  \n", "unreadable"])
def test_without_usable_deny_terms_it_commits_and_pushes_nothing(tmp_path, origin, terms):
    m = started(tmp_path, origin, terms="x\n" if terms == "unreadable" else terms)
    if terms == "unreadable":
        (m.xdg / "claude-config" / "deny-terms").chmod(0)
    remember(m, "clean.md")
    code, out, err = hook(m)
    assert (code, err) == (0, b"")
    warned(out, "no-deny-terms")
    assert remote_files(origin) == set()
    assert git(m.store, "status", "--porcelain") == "?? clean.md"  # untracked: no commit was made


def test_memories_written_without_deny_terms_sync_once_terms_exist(tmp_path, origin):
    m = started(tmp_path, origin, terms=None)
    remember(m, "clean.md")
    remember(m, "denied.md", body="AcmeCorp secret\n")
    warned(hook(m)[1], "no-deny-terms")
    (m.xdg / "claude-config" / "deny-terms").write_text(TERM + "\n")
    assert quiet(m) == {}
    assert remote_files(origin) == {"clean.md"}
    assert git(m.store, "ls-files", "denied.md") == ""
    assert TERM.casefold() not in git(origin, "log", "-p", "--all").casefold()


def test_a_term_in_an_earlier_commit_blocks_the_push_even_once_the_file_is_gone(tmp_path, origin):
    m = started(tmp_path, origin)
    remember(m, "clean.md")
    quiet(m)
    remember(m, "denied.md", body="- Notes from the ACMECORP engagement.\n")
    git(m.store, "add", "denied.md")
    git(m.store, "commit", "-q", "-m", "by hand")
    git(m.store, "rm", "-q", "denied.md")
    git(m.store, "commit", "-q", "-m", "removed by hand")
    remember(m, "later.md")
    code, out, err = hook(m)
    assert (code, err) == (0, b"")
    warned(out, "blocked-files")
    assert remote_files(origin) == {"clean.md"}
    assert TERM.casefold() not in git(origin, "log", "-p", "--all").casefold()


def test_a_term_in_a_commit_identity_blocks_the_push(tmp_path, origin):
    m = started(tmp_path, origin)
    remember(m, "clean.md")
    work = {**GIT_ENV, "GIT_AUTHOR_EMAIL": "me@acmecorp.example", "GIT_COMMITTER_EMAIL": "me@acmecorp.example"}
    subprocess.run(["git", "-C", str(m.store), "add", "clean.md"], check=True, env=work)
    subprocess.run(["git", "-C", str(m.store), "commit", "-q", "-m", "by hand"], check=True, env=work)
    code, out, err = hook(m)
    assert (code, err) == (0, b"")
    warned(out, "blocked-files")
    assert TERM.casefold() not in git(origin, "log", "--all", "--format=%ae%n%ce").casefold()


def test_a_hand_commit_in_a_cloned_store_carries_the_store_identity(tmp_path, origin):
    m = started(tmp_path, origin)
    home = tmp_path / "work-home"
    home.mkdir()
    (home / ".gitconfig").write_text("[user]\n\tname = Work Name\n\temail = me@employer.example\n")
    remember(m, "clean.md")
    env = {"PATH": "/usr/bin:/bin", "HOME": str(home)}
    subprocess.run(["git", "-C", str(m.store), "add", "clean.md"], check=True, env=env)
    subprocess.run(["git", "-C", str(m.store), "commit", "-q", "-m", "by hand"], check=True, env=env)
    assert git(m.store, "log", "-1", "--format=%an %ae %cn %ce") == (
        "claude-memory claude-memory@localhost claude-memory claude-memory@localhost"
    )


def test_a_term_in_a_binary_file_blocks_the_push(tmp_path, origin):
    m = started(tmp_path, origin)
    (m.store / "blob.bin").write_bytes(b"\x00\x01 acmecorp \x00")
    git(m.store, "add", "blob.bin")
    git(m.store, "commit", "-q", "-m", "by hand")
    code, out, err = hook(m)
    assert (code, err) == (0, b"")
    warned(out, "blocked-files")
    assert remote_files(origin) == set()


@pytest.mark.parametrize("name,change", [
    ("old.md", "delete"), ("old.md", "edit"), ("globex-notes.md", "delete"),
])
def test_removing_a_newly_denied_term_goes_through(tmp_path, origin, name, change):
    m = started(tmp_path, origin)
    remember(m, name, body="Worked with Globex.\n")
    quiet(m)
    (m.xdg / "claude-config" / "deny-terms").write_text(TERM + "\nGlobex\n")
    if change == "delete":
        (m.store / name).unlink()
    else:
        remember(m, name, body="Worked with a client.\n")
    assert quiet(m) == {}
    if change == "delete":
        assert name not in remote_files(origin)
    else:
        assert git(origin, "show", f"main:{name}").endswith("Worked with a client.")


def test_a_term_typed_into_a_merge_resolution_blocks_the_push(tmp_path, origin):
    m = started(tmp_path, origin)
    remember(m, "clean.md")
    quiet(m)
    git(m.store, "checkout", "-q", "-b", "side")
    remember(m, "x.md", body="Side.\n")
    git(m.store, "add", "x.md")
    git(m.store, "commit", "-q", "-m", "side")
    git(m.store, "checkout", "-q", "main")
    remember(m, "x.md", body="Main.\n")
    git(m.store, "add", "x.md")
    git(m.store, "commit", "-q", "-m", "main")
    subprocess.run(["git", "-C", str(m.store), "merge", "side"], capture_output=True, env=GIT_ENV, check=False)
    remember(m, "x.md", body="- Resolved for acmecorp.\n")
    git(m.store, "add", "x.md")
    git(m.store, "commit", "-q", "--no-edit")
    code, out, err = hook(m)
    assert (code, err) == (0, b"")
    warned(out, "blocked-files")
    assert remote_files(origin) == {"clean.md"}


@pytest.mark.parametrize("name,message", [("clean.md", "learned at acmecorp"), ("acmecorp-notes.md", "by hand")])
def test_a_term_in_a_commit_message_or_a_file_name_blocks_the_push(tmp_path, origin, name, message):
    m = started(tmp_path, origin)
    (m.store / name).write_text("Plain text.\n")  # the term only in the name or the message
    git(m.store, "add", name)
    git(m.store, "commit", "-q", "-m", message)
    code, out, err = hook(m)
    assert (code, err) == (0, b"")
    warned(out, "blocked-files")
    assert remote_files(origin) == set()


def test_memory_md_and_dot_files_are_never_synced(tmp_path, origin):
    m = started(tmp_path, origin)
    remember(m, "normal.md")
    (m.store / "MEMORY.md").write_text("- [Normal](normal.md)\n")
    (m.store / ".swap.md.swp").write_text("editor state")
    assert quiet(m) == {}
    assert remote_files(origin) == {"normal.md"}


# --- sync between machines ---------------------------------------------------------------


def test_a_first_run_against_an_empty_remote_creates_main_and_pushes(tmp_path, origin):
    m = started(tmp_path, origin)
    remember(m, "first.md")
    assert quiet(m) == {}
    assert remote_files(origin) == {"first.md"}
    assert git(origin, "symbolic-ref", "HEAD") == "refs/heads/main"


def test_two_machines_share_memories_both_ways(tmp_path, origin):
    a = started(tmp_path, origin, "a")
    remember(a, "from-a.md", description="Written on A.")
    assert quiet(a) == {}
    b = started(tmp_path, origin, "b")
    assert (b.store / "from-a.md").read_text() == (a.store / "from-a.md").read_text()
    remember(b, "from-b.md", description="Written on B.")
    assert quiet(b) == {}
    out = quiet(a, STARTUP)
    assert (a.store / "from-b.md").read_text() == (b.store / "from-b.md").read_text()
    assert "from-b — Written on B." in out["hookSpecificOutput"]["additionalContext"].splitlines()
    assert remote_files(origin) == {"from-a.md", "from-b.md"}


@pytest.mark.parametrize("resolve", ["merge", "rebase"])
def test_edits_to_the_same_memory_on_two_machines_keep_the_local_text_and_warn(tmp_path, origin, resolve):
    a = started(tmp_path, origin, "a")
    remember(a, "shared.md", body="Base.\n")
    quiet(a)
    b = started(tmp_path, origin, "b")
    remember(a, "shared.md", body="A's version.\n")
    remember(b, "shared.md", body="B's version.\n")
    assert quiet(a) == {}
    pushed = git(origin, "rev-parse", "main")
    code, out, err = hook(b)
    assert (code, err) == (0, b"")
    warned(out, "conflict")
    assert git(origin, "rev-parse", "main") == pushed
    assert (b.store / "shared.md").read_text().endswith("B's version.\n")
    assert "B's version." in git(b.store, "show", "main:shared.md")
    assert git(b.store, "status", "--porcelain") == ""
    assert not (b.store / ".git" / "rebase-merge").exists() and not (b.store / ".git" / "rebase-apply").exists()
    # Either hand resolution, then the next sync pushes it and both machines converge.
    editor = {**GIT_ENV, "GIT_EDITOR": "true"}
    subprocess.run(["git", "-C", str(b.store), resolve, "origin/main"], capture_output=True, env=editor, check=False)
    remember(b, "shared.md", body="Both versions.\n")
    git(b.store, "add", "shared.md")
    finish = ["commit", "-q", "--no-edit"] if resolve == "merge" else ["rebase", "--continue"]
    subprocess.run(["git", "-C", str(b.store), *finish], capture_output=True, env=editor, check=True)
    assert quiet(b) == {}
    assert git(origin, "rev-parse", "main") == git(b.store, "rev-parse", "main")
    assert git(origin, "show", "main:shared.md").endswith("Both versions.")
    quiet(a, STARTUP)
    assert (a.store / "shared.md").read_text() == (b.store / "shared.md").read_text()


@pytest.mark.parametrize("command,state", [("rebase", "rebase-merge"), ("merge", "MERGE_HEAD")])
def test_a_store_left_mid_rebase_or_merge_is_not_touched(tmp_path, origin, command, state):
    a = started(tmp_path, origin, "a")
    remember(a, "x.md", body="Base.\n")
    quiet(a)
    b = started(tmp_path, origin, "b")
    remember(a, "x.md", body="A.\n")
    quiet(a)
    remember(b, "x.md", body="B.\n")
    git(b.store, "commit", "-q", "-am", "b")
    git(b.store, "fetch", "-q", "origin")
    # A hand rebase or merge that stopped on its conflict, as when the user left it or git was killed.
    subprocess.run(["git", "-C", str(b.store), command, "origin/main"], capture_output=True, env=GIT_ENV, check=False)
    assert (b.store / ".git" / state).exists()
    before = git(b.store, "status", "--porcelain")
    remember(b, "new.md", body="Precious.\n")
    code, out, err = hook(b)
    assert (code, err) == (0, b"")
    warned(out, "conflict")
    assert (b.store / "new.md").read_text().endswith("Precious.\n")
    assert (b.store / ".git" / state).exists()
    assert git(b.store, "status", "--porcelain") == before + "\n?? new.md"


def test_a_failed_fetch_or_push_keeps_the_new_memory(tmp_path, origin):
    m = started(tmp_path, origin)
    remember(m, "new.md")
    git(m.store, "remote", "set-url", "origin", str(tmp_path / "gone.git"))
    assert hook(m) == (0, b"", b"") and last_log(m).endswith(" fetch-failed")
    assert (m.store / "new.md").is_file() and git(m.store, "ls-tree", "--name-only", "main") == "new.md"
    git(m.store, "remote", "set-url", "origin", str(origin))
    git(m.store, "remote", "set-url", "--push", "origin", str(tmp_path / "gone.git"))
    remember(m, "newer.md")
    assert hook(m) == (0, b"", b"") and last_log(m).endswith(" push-failed")
    assert (m.store / "newer.md").is_file()
    assert set(git(m.store, "ls-tree", "--name-only", "main").splitlines()) == {"new.md", "newer.md"}
    assert remote_files(origin) == set()


# --- failures and when it does nothing ---------------------------------------------------


@pytest.mark.parametrize("local", [None, {}, {"memory": {}}, {"memory": {"repo": ""}}, {"memory": "x"}, {"memory": {"repo": 1}}])
@pytest.mark.parametrize("payload", [STARTUP, SYNC, READ, PROMPT])
def test_without_a_memory_repo_it_runs_no_git_and_prints_nothing(tmp_path, origin, local, payload):
    m = machine(tmp_path, None)
    if local is not None:
        (m.xdg / "claude-config" / "local.json").write_text(json.dumps(local))
    assert hook(m, payload, patch=no_git(m)) == (0, b"", b"")
    assert not m.mark.exists() and not m.store.exists()


@pytest.mark.parametrize("stdin", [b"", b"{", b"\xff\xfe", b"null", b"[]", b"{}", b'{"hook_event_name": "Stop"}'])
def test_bad_input_or_another_event_runs_no_git_and_prints_nothing(tmp_path, origin, stdin):
    m = machine(tmp_path, origin)
    assert hook(m, patch=no_git(m), stdin=stdin) == (0, b"", b"")
    assert not m.mark.exists()


def test_an_unreachable_remote_warns_and_logs(tmp_path, origin):
    m = machine(tmp_path, tmp_path / "gone.git")
    out = quiet(m, STARTUP)
    assert "clone-failed" in out["systemMessage"] and "hookSpecificOutput" not in out
    assert (m.claude / "claude-config" / "memory.log").read_text().splitlines()[-1].endswith(" clone-failed")
    s = started(tmp_path, origin, "b")
    git(s.store, "remote", "set-url", "origin", str(tmp_path / "gone.git"))
    code, out, err = hook(s, STARTUP)
    assert (code, err) == (0, b"")
    assert "fetch-failed" in json.loads(out)["systemMessage"]


@pytest.mark.parametrize("patch,reason", [
    ("hook.SAFE_PATH = '/nonexistent'\n", "no-git"),
    ("hook.FETCH_SECONDS = 0\n", "timeout"),
])
def test_no_git_or_a_step_past_its_deadline_warns(tmp_path, origin, patch, reason):
    m = machine(tmp_path, origin)
    code, out, err = hook(m, STARTUP, patch)
    assert (code, err) == (0, b"")
    assert reason in json.loads(out)["systemMessage"]


def test_a_held_lock_makes_it_skip_the_sync_quietly(tmp_path, origin):
    m = started(tmp_path, origin)
    remember(m, "clean.md")
    with open(m.claude / "claude-config" / "memory.lock", "a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        stamp(m, HOOK.PULL_SECONDS + 5)
        assert hook(m, READ, patch=no_git(m)) == (0, b"", b"")
        out = quiet(m, STARTUP, patch=no_git(m))
    assert list(out) == ["hookSpecificOutput"]
    assert "clean — A rule." in out["hookSpecificOutput"]["additionalContext"].splitlines()
    assert not m.mark.exists()


# --- the index ---------------------------------------------------------------------------


def context(m, payload=STARTUP, patch=None):
    return quiet(m, payload, patch)["hookSpecificOutput"]["additionalContext"]


def test_the_index_fits_its_budget_and_counts_what_it_leaves_out(tmp_path, origin):
    m = started(tmp_path, origin)
    header = context(m)
    desc = "d" * 100
    width = len(f"\nm0000 — {desc}")
    fits = (BUDGET - len(header)) // width
    for i in range(fits):
        remember(m, f"m{i:04d}.md", description=desc)
    text = context(m)
    assert len(text) <= BUDGET
    assert len([line for line in text.splitlines() if line.startswith("m0")]) == fits
    assert text.splitlines()[-1].startswith("m0")  # nothing left out, so no count line
    for i in range(fits, 2 * fits):
        remember(m, f"m{i:04d}.md", description=desc)
    text = context(m)
    listed = len([line for line in text.splitlines() if line.startswith("m0")])
    assert len(text) <= BUDGET and fits - 2 <= listed < fits
    assert re.match(r"(\d+) ", text.splitlines()[-1]).group(1) == str(2 * fits - listed)


def test_only_safe_names_and_one_line_descriptions_enter_the_index(tmp_path, origin):
    m = started(tmp_path, origin)
    remember(m, "ok.md", description="Plain.")
    remember(m, "long.md", description="x" * 300)
    remember(m, "quoted.md", description='"In quotes."')
    remember(m, "single.md", description="'It''s single.'")
    remember(m, "backslash.md", description=r'"In C:\\tmp say \"hi\"."')
    remember(m, "escaped.md", description=r'"Call it a \"refactor\"; never write \"slop\""')
    remember(m, "escapes.md", description="red \x1b[31mtext\x1b[0m\r tab\there \u202eevil\u2028next\x7f\x85 end")
    for name in ("Upper.md", "-dash.md", "under_score.md", "space name.md", "dots.v2.md", "x.md.txt"):
        remember(m, name, description="Should not show.")
    (m.store / "nofront.md").write_text("description: not frontmatter\n")
    (m.store / "unclosed.md").write_text("---\nname: unclosed\n")
    (m.store / "binary.md").write_bytes(b"---\ndescription: \xff\xfe\x00bin\n---\n")
    (m.store / "linked.md").symlink_to(m.store / "ok.md")
    text = context(m)
    assert not re.search("[\x00-\x09\x0b-\x1f\x7f-\x9f\u2028\u2029\u202a-\u202e]", text)
    lines = text.splitlines()
    entries = lines[1:-1]
    assert all(re.fullmatch(r"[a-z0-9][a-z0-9-]*( — .{1,110})?", line) for line in entries), entries
    assert {line.split()[0] for line in entries} == {
        "ok", "long", "quoted", "single", "backslash", "escaped", "escapes", "nofront", "unclosed", "binary",
    }
    assert "ok — Plain." in entries and "quoted — In quotes." in entries and "single — It's single." in entries
    assert 'backslash — In C:\\tmp say "hi".' in entries
    assert 'escaped — Call it a "refactor"; never write "slop"' in entries
    assert "long — " + "x" * 110 in entries
    assert "nofront" in entries and "unclosed" in entries
    assert "Should not show" not in text
    assert lines[-1].startswith("6 ")  # five unsafe .md names and the symlink; x.md.txt is no memory


@pytest.mark.parametrize("source", ["startup", "resume", "clear", "compact"])
def test_every_session_start_prints_the_index_and_only_startup_syncs(tmp_path, origin, source):
    m = started(tmp_path, origin)
    remember(m, "kept.md", description="Kept.")
    out = quiet(m, {"hook_event_name": "SessionStart", "source": source}, patch=no_git(m))
    assert "kept — Kept." in out["hookSpecificOutput"]["additionalContext"].splitlines()
    assert m.mark.exists() == (source == "startup")


def test_session_end_pushes_what_no_write_event_saw_and_prints_nothing(tmp_path, origin):
    m = started(tmp_path, origin)  # the attempt stamp is fresh: session end syncs regardless
    remember(m, "kept.md")
    remember(m, "gone.md")
    assert hook(m, SESSION_END) == (0, b"", b"")
    assert remote_files(origin) == {"kept.md", "gone.md"}
    (m.store / "gone.md").unlink()  # deleted through the shell: no write event
    assert hook(m, SESSION_END) == (0, b"", b"")
    assert remote_files(origin) == {"kept.md"}
    git(m.store, "remote", "set-url", "origin", str(tmp_path / "gone.git"))
    remember(m, "later.md")
    assert hook(m, SESSION_END) == (0, b"", b"")
    assert last_log(m).endswith(" fetch-failed")


# --- the skills link ---------------------------------------------------------------------


@pytest.mark.parametrize("existing", [None, "dir", "file", "symlink"])
def test_the_skills_link_is_made_only_where_nothing_exists(tmp_path, origin, existing):
    m = machine(tmp_path, origin)
    path = m.home / ".omc" / "skills"
    other = tmp_path / "elsewhere"
    if existing:
        path.parent.mkdir()
    if existing == "dir":
        path.mkdir()
        (path / "mine.md").write_text("mine")
    elif existing == "file":
        path.write_text("mine")
    elif existing == "symlink":
        path.symlink_to(other)
    quiet(m, STARTUP)
    if existing is None:
        assert path.is_symlink() and path.resolve() == (m.store / "skills").resolve() and path.is_dir()
    elif existing == "dir":
        assert not path.is_symlink() and [p.name for p in path.iterdir()] == ["mine.md"]
    elif existing == "file":
        assert path.read_text() == "mine"
    else:
        assert path.readlink() == other


def test_a_pushed_memory_edited_to_name_a_deny_term_keeps_its_edit_local(tmp_path, origin):
    a = started(tmp_path, origin, "a")
    remember(a, "shared.md", body="Clean text.\n")
    quiet(a)
    pushed = git(origin, "show", "main:shared.md")
    b = started(tmp_path, origin, "b")
    remember(b, "other.md")
    quiet(b)
    remember(a, "shared.md", body="Now about acmecorp.\n")
    edited = (a.store / "shared.md").read_text()
    for _ in range(2):  # the edit is staged and unstaged again on every sync
        assert quiet(a) == {}  # exit 0, empty stderr, nothing printed
        assert git(origin, "show", "main:shared.md") == pushed
        assert "acmecorp" not in git(origin, "log", "-p", "--all").casefold()
        assert (a.store / "shared.md").read_text() == edited
        assert (a.store / "other.md").read_text() == (b.store / "other.md").read_text()
        assert git(a.store, "rev-parse", "main") == git(origin, "rev-parse", "main")


def test_a_skills_symlink_from_the_remote_never_leads_outside_the_store(tmp_path, origin):
    outside = tmp_path / "outside"
    outside.mkdir()
    seed = tmp_path / "seed"
    subprocess.run(["git", "clone", "-q", str(origin), str(seed)], check=True, capture_output=True, env=GIT_ENV)
    (seed / "skills").symlink_to(outside)
    git(seed, "add", "-A")
    git(seed, "commit", "-q", "-m", "tampered")
    git(seed, "push", "-q", "origin", "HEAD:main")
    m = started(tmp_path, origin)
    assert not (m.store / "skills").is_symlink()
    link = m.home / ".omc" / "skills"
    assert not link.exists() or link.resolve().is_relative_to(m.store.resolve())


def test_a_relative_xdg_config_home_is_ignored(tmp_path, origin):
    m = machine(tmp_path, origin)
    (m.home / ".config").mkdir()
    (m.xdg / "claude-config").rename(m.home / ".config" / "claude-config")
    m.env["XDG_CONFIG_HOME"] = "no-such-relative-dir"
    quiet(m, STARTUP)
    assert (m.store / ".git").is_dir()


# --- sync during the session -------------------------------------------------------------


def last_log(m):
    return (m.claude / "claude-config" / "memory.log").read_text().splitlines()[-1]


def test_a_write_syncs_at_once_and_prints_nothing(tmp_path, origin):
    m = started(tmp_path, origin)  # the attempt stamp is fresh
    remember(m, "new.md")
    assert hook(m, SYNC) == (0, b"", b"")
    assert remote_files(origin) == {"new.md"}


def test_a_write_waits_for_a_held_lock_and_a_prompt_skips(tmp_path, origin):
    m = started(tmp_path, origin)
    remember(m, "new.md")
    with open(m.claude / "claude-config" / "memory.lock", "a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        stamp(m, HOOK.PULL_SECONDS + 5)
        assert hook(m, PROMPT) == (0, b"", b"")
        assert remote_files(origin) == set()
        proc = subprocess.Popen(
            [sys.executable, "-I", str(m.claude / "hooks" / "global_memory.py")],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=m.env,
        )
        proc.stdin.write(json.dumps({**SYNC, "tool_input": {"file_path": str(m.store / "x.md")}}).encode())
        proc.stdin.close()
        time.sleep(1)
        assert proc.poll() is None  # still waiting for the lock
    out, err = proc.stdout.read(), proc.stderr.read()
    proc.stdout.close()
    proc.stderr.close()
    assert (proc.wait(timeout=60), out, err) == (0, b"", b"")
    assert remote_files(origin) == {"new.md"}


@pytest.mark.parametrize("world", ["unreachable", "no-git", "deadline", "held-lock", "no-deny-terms", "no-repo"])
def test_a_read_prints_nothing_in_any_failure_world(tmp_path, origin, world):
    remote = {"unreachable": tmp_path / "gone.git", "no-repo": None}.get(world, origin)
    m = machine(tmp_path, remote, terms=None if world == "no-deny-terms" else TERM + "\n")
    patch = {"no-git": "hook.SAFE_PATH = '/nonexistent'\n", "deadline": "hook.READ_SECONDS = 0\n"}.get(world)
    (m.claude / "claude-config").mkdir()
    with open(m.claude / "claude-config" / "memory.lock", "a") as lock:
        if world == "held-lock":
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        assert hook(m, READ, patch) == (0, b"", b"")
    reason = {"unreachable": "clone-failed", "no-git": "no-git", "deadline": "timeout", "no-deny-terms": "no-deny-terms"}
    if world in reason:
        assert last_log(m).endswith(" " + reason[world])


HANG = (
    "real = hook.subprocess.Popen\n"
    "def popen(argv, **kwargs):\n"
    "    return real(['/bin/sleep', '30'] if 'fetch' in argv else argv, **kwargs)\n"
    "hook.subprocess.Popen = popen\n"
    "hook.READ_SECONDS = 1\n"
    "hook.FETCH_SECONDS = 4\n"
)


@pytest.mark.parametrize("payload,short", [(READ, True), (STARTUP, False)])
def test_a_hanging_fetch_is_cut_at_the_events_network_deadline(tmp_path, origin, payload, short):
    m = started(tmp_path, origin)
    stamp(m, HOOK.PULL_SECONDS + 5)
    begin = time.monotonic()
    code, _, err = hook(m, payload, HANG)
    assert (code, err) == (0, b"")
    assert (time.monotonic() - begin < 4) == short  # the read path stops at 1 s, session start waits 4 s
    assert last_log(m).endswith(" timeout")


@pytest.mark.parametrize("payload", [PROMPT, {"hook_event_name": "SessionStart", "source": "resume"}])
@pytest.mark.parametrize("age,syncs", [(-5, False), (5, True), (-HOOK.PULL_SECONDS - 30, True)])  # last: in the future
def test_throttled_events_sync_only_when_the_last_attempt_is_old_enough(tmp_path, origin, payload, age, syncs):
    m = started(tmp_path, origin)
    remember(m, "new.md")
    stamp(m, HOOK.PULL_SECONDS + age)
    code, _, err = hook(m, payload)
    assert (code, err) == (0, b"")
    assert (remote_files(origin) == {"new.md"}) == syncs


def test_startup_syncs_even_with_a_fresh_stamp(tmp_path, origin):
    m = started(tmp_path, origin)
    remember(m, "new.md")
    stamp(m, 0)
    quiet(m, STARTUP)
    assert remote_files(origin) == {"new.md"}


def test_a_failed_attempt_counts_as_an_attempt(tmp_path, origin):
    m = started(tmp_path, origin)
    git(m.store, "remote", "set-url", "origin", str(tmp_path / "gone.git"))
    stamp(m, HOOK.PULL_SECONDS + 5)
    assert hook(m, PROMPT) == (0, b"", b"")
    lines = (m.claude / "claude-config" / "memory.log").read_text().splitlines()
    assert lines[-1].endswith(" fetch-failed")
    assert hook(m, PROMPT) == (0, b"", b"")
    assert (m.claude / "claude-config" / "memory.log").read_text().splitlines() == lines


# --- what a session has seen -------------------------------------------------------------


def delta(m, payload=PROMPT):
    """The delta a prompt prints after a sync (the stamp is made stale first); None when it prints nothing."""
    stamp(m, HOOK.PULL_SECONDS + 5)
    code, out, err = hook(m, payload)
    assert (code, err) == (0, b"")
    if not out:
        return None
    data = json.loads(out)
    assert list(data) == ["hookSpecificOutput"] and data["hookSpecificOutput"]["hookEventName"] == "UserPromptSubmit"
    return data["hookSpecificOutput"]["additionalContext"]


def seen_by_b(tmp_path, origin):
    """Machine A, and machine B whose session s1 has seen the store."""
    a = started(tmp_path, origin, "a")
    remember(a, "old.md", description="Old.")
    remember(a, "kept.md", description="Kept.")
    quiet(a)
    b = started(tmp_path, origin, "b")
    quiet(b, {**STARTUP, "session_id": "s1"})
    return a, b


def test_a_prompt_shows_what_other_machines_added_or_changed_once(tmp_path, origin):
    a, b = seen_by_b(tmp_path, origin)
    remember(a, "old.md", description="Old, edited.")
    remember(a, "new.md", description="New.")
    (a.store / "kept.md").unlink()
    quiet(a)
    for payload in (READ, SYNC):  # only a prompt prints the delta
        stamp(b, HOOK.PULL_SECONDS + 5)
        assert hook(b, payload) == (0, b"", b"")
    text = delta(b)
    assert text != context(b, {"hook_event_name": "SessionStart", "source": "resume"})  # a delta, not the index
    assert text.splitlines()[1:] == ["new — New.", "old — Old, edited."]
    assert delta(b) is None


def test_the_delta_is_sanitised_and_capped_like_the_index(tmp_path, origin):
    a, b = seen_by_b(tmp_path, origin)
    remember(a, "Upper.md")
    remember(a, "under_score.md")
    remember(a, "escapes.md", description=f"red {chr(27)}[31mtext{chr(0x2028)}next{chr(0x202e)}end")
    for i in range(200):
        remember(a, f"m{i:03d}.md", description="d" * 100)
    quiet(a)
    text = delta(b)
    assert len(text) <= BUDGET
    assert not [c for c in text.replace("\n", "") if unicodedata.category(c)[0] == "C" or c in (chr(0x2028), chr(0x2029))]
    lines = text.splitlines()
    entries = lines[1:-1]
    assert all(re.fullmatch(r"[a-z0-9][a-z0-9-]*( — .{1,110})?", line) for line in entries), entries
    assert "escapes — red [31mtextnextend" in entries
    assert "Upper" not in text and "under_score" not in text
    assert lines[-1].startswith(f"{203 - len(entries)} ")


def test_a_resumed_session_behind_main_gets_the_whole_index_not_a_delta(tmp_path, origin):
    a, b = seen_by_b(tmp_path, origin)
    remember(a, "new.md", description="New.")
    quiet(a)
    stamp(b, HOOK.PULL_SECONDS + 5)
    out = quiet(b, {"hook_event_name": "SessionStart", "source": "resume", "session_id": "s1"})
    assert out["hookSpecificOutput"]["hookEventName"] == "SessionStart"
    assert {"old — Old.", "kept — Kept.", "new — New."} <= set(out["hookSpecificOutput"]["additionalContext"].splitlines())
    assert delta(b) is None  # the resume recorded the commit it showed


@pytest.mark.parametrize("state", ["missing", "garbled", "unknown", "no-dir", "dir-is-file"])
def test_without_a_usable_seen_record_a_prompt_shows_the_full_index_once(tmp_path, origin, state):
    a = started(tmp_path, origin, "a")
    b = started(tmp_path, origin, "b")
    seen = b.claude / "claude-config" / "memory-seen"
    if state == "dir-is-file":
        seen.write_text("x")
    elif state != "no-dir":
        seen.mkdir()
        if state != "missing":
            # A ref name resolves in git, but is no commit id: not a usable record.
            (seen / "s1").write_text("main\n" if state == "garbled" else "0" * 40 + "\n")
    remember(a, "new.md", description="New.")
    quiet(a)
    shown = delta(b)
    if state == "dir-is-file":  # no record can be written: printing the index on every prompt would be noise
        assert shown is None and delta(b) is None
        return
    assert shown == context(b, {"hook_event_name": "SessionStart", "source": "resume"})  # the stamp is fresh: no sync
    assert "new — New." in shown.splitlines()
    assert delta(b) is None
    remember(a, "newer.md", description="Newer.")
    quiet(a)
    assert delta(b).splitlines()[1:] == ["newer — Newer."]


def test_a_session_started_on_an_empty_store_hears_of_the_first_memory(tmp_path, origin):
    a = started(tmp_path, origin, "a")
    quiet(a, {**STARTUP, "session_id": "s1"})  # main has no commit yet: nothing is recorded
    assert delta(a) is None
    assert not (a.claude / "claude-config" / "memory-seen" / "s1").exists()
    b = started(tmp_path, origin, "b")
    remember(b, "new.md", description="New.")
    quiet(b)
    assert "new — New." in delta(a).splitlines()
    assert delta(a) is None


@pytest.mark.parametrize("sid", ["../x", "a/b", "", "x" * 65, 5, None, ["s"]])
def test_an_unsafe_session_id_is_never_a_file_name(tmp_path, origin, sid):
    m = started(tmp_path, origin)
    remember(m, "kept.md")
    quiet(m)  # main has a commit, so there is something to record
    quiet(m, {**STARTUP, "session_id": sid})
    stamp(m, HOOK.PULL_SECONDS + 5)
    assert hook(m, {**PROMPT, "session_id": sid}) == (0, b"", b"")
    seen = m.claude / "claude-config" / "memory-seen"
    assert not (m.claude / "claude-config" / "x").exists()
    assert not seen.exists() or list(seen.iterdir()) == []


def test_seen_files_past_their_age_are_removed_only_at_startup(tmp_path, origin):
    m = started(tmp_path, origin)
    seen = m.claude / "claude-config" / "memory-seen"
    seen.mkdir()
    day = 24 * 3600
    for name, age in (("old", HOOK.SEEN_DAYS * day + day), ("young", HOOK.SEEN_DAYS * day - day)):
        (seen / name).write_text("0" * 40)
        then = time.time() - age
        os.utime(seen / name, (then, then))
    for payload in (PROMPT, READ, SYNC):
        stamp(m, HOOK.PULL_SECONDS + 5)
        hook(m, payload)
    assert (seen / "old").exists()
    quiet(m, STARTUP)
    assert not (seen / "old").exists() and (seen / "young").exists()


@pytest.mark.parametrize("payload", [READ, PROMPT, {"hook_event_name": "SessionStart", "source": "resume"}])
def test_the_leak_guard_holds_on_every_syncing_event(tmp_path, origin, payload):
    m = started(tmp_path, origin)
    remember(m, "clean.md")
    remember(m, "denied.md", body="About acmecorp.\n")
    stamp(m, HOOK.PULL_SECONDS + 5)
    code, _, err = hook(m, payload)
    assert (code, err) == (0, b"")
    assert remote_files(origin) == {"clean.md"}
    assert git(m.store, "ls-files", "denied.md") == ""


@pytest.mark.parametrize("payload", [SYNC, READ, PROMPT, {"hook_event_name": "SessionStart", "source": "resume"}])
def test_no_event_commits_without_deny_terms(tmp_path, origin, payload):
    m = started(tmp_path, origin, terms=None)
    remember(m, "clean.md")
    stamp(m, HOOK.PULL_SECONDS + 5)
    code, _, err = hook(m, payload)
    assert (code, err) == (0, b"")
    assert remote_files(origin) == set()
    assert git(m.store, "status", "--porcelain") == "?? clean.md"


# --- review round: pull before each store access, backstop, bounds -----------------------


def test_every_read_or_edit_of_the_store_pulls_first(tmp_path, origin):
    a, b = seen_by_b(tmp_path, origin)
    assert delta(b) is None  # B's prompt synced: its attempt stamp is fresh from here on
    remember(a, "old.md", description="Old, edited on A.")
    quiet(a)
    assert hook(b, READ) == (0, b"", b"")  # inside the attempt window, still pulls
    assert (b.store / "old.md").read_text() == (a.store / "old.md").read_text()
    remember(a, "old.md", description="Old, edited on A again.")
    quiet(a)
    assert hook(b, EDIT) == (0, b"", b"")  # an edit with no read before it pulls too
    assert (b.store / "old.md").read_text() == (a.store / "old.md").read_text()
    remember(b, "old.md", description="Old, edited on B.")
    assert quiet(b) == {}  # B's write pushes without a conflict
    assert "Old, edited on B." in git(origin, "show", "main:old.md")


def test_a_read_backs_off_after_a_failed_sync_until_the_window_passes(tmp_path, origin):
    m = started(tmp_path, origin)
    failed = m.claude / "claude-config" / "memory.failed"
    git(m.store, "remote", "set-url", "origin", str(tmp_path / "gone.git"))
    assert hook(m, READ) == (0, b"", b"") and failed.exists()
    assert hook(m, READ, patch=no_git(m)) == (0, b"", b"")
    assert not m.mark.exists()  # inside the back-off: no git at all
    for age in (HOOK.PULL_SECONDS + 5, -HOOK.PULL_SECONDS - 30):  # outside it, and a stamp in the future
        stamp(m, age, "memory.failed")
        assert hook(m, READ, patch=no_git(m)) == (0, b"", b"")
        assert m.mark.exists()
        m.mark.unlink()
    git(m.store, "remote", "set-url", "origin", str(origin))
    stamp(m, HOOK.PULL_SECONDS + 5, "memory.failed")
    remember(m, "new.md")
    assert hook(m, READ) == (0, b"", b"")
    assert not failed.exists() and remote_files(origin) == {"new.md"}


def test_a_waiting_event_gives_up_on_a_lock_held_too_long(tmp_path, origin):
    m = started(tmp_path, origin)
    remember(m, "new.md")
    with open(m.claude / "claude-config" / "memory.lock", "a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        for payload in (SYNC, SESSION_END):
            begin = time.monotonic()
            assert hook(m, payload, "hook.WAIT_SECONDS = 1\n") == (0, b"", b"")
            assert 1 <= time.monotonic() - begin < 10
    assert remote_files(origin) == set()


def test_the_seen_record_is_the_commit_the_prompt_compared_against(tmp_path, origin):
    a, b = seen_by_b(tmp_path, origin)
    remember(a, "new.md", description="New.")
    quiet(a)
    # Another session's sync lands between the comparison and the record.
    race = (
        "real = hook.changes\n"
        "def changes(*args):\n"
        "    text = real(*args)\n"
        f"    hook.subprocess.run(['git', '-C', {str(b.store)!r}, 'commit', '-q', '--allow-empty', '-m', 'race'], check=True)\n"
        "    return text\n"
        "hook.changes = changes\n"
    )
    stamp(b, HOOK.PULL_SECONDS + 5)
    shown = git(origin, "rev-parse", "main")
    code, out, err = hook(b, PROMPT, race)
    assert (code, err) == (0, b"") and "new — New." in json.loads(out)["hookSpecificOutput"]["additionalContext"]
    assert (b.claude / "claude-config" / "memory-seen" / "s1").read_text().strip() == shown


def test_a_symlinked_seen_directory_is_never_cleaned(tmp_path, origin):
    m = started(tmp_path, origin)
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    (elsewhere / "old").write_text("keep")
    then = time.time() - (HOOK.SEEN_DAYS + 1) * 24 * 3600
    os.utime(elsewhere / "old", (then, then))
    (m.claude / "claude-config" / "memory-seen").symlink_to(elsewhere)
    quiet(m, STARTUP)
    assert (elsewhere / "old").read_text() == "keep"


@pytest.mark.parametrize("tool_input", [
    {"file_path": "OUTSIDE"}, {"file_path": "<store>/../x.md"}, None, "text", [], {}, {"file_path": 5}, {"path": IN_STORE},
])
@pytest.mark.parametrize("base", [SYNC, READ])
def test_a_tool_event_for_anything_but_a_store_file_runs_no_git(tmp_path, origin, base, tool_input):
    m = started(tmp_path, origin)
    remember(m, "new.md")
    if isinstance(tool_input, dict) and isinstance(tool_input.get("file_path"), str):
        path = tool_input["file_path"].replace("OUTSIDE", str(tmp_path / "x.md")).replace("<store>", str(m.store))
        tool_input = {"file_path": path}
    assert hook(m, {**base, "tool_input": tool_input}, patch=no_git(m)) == (0, b"", b"")
    assert not m.mark.exists()


@pytest.mark.parametrize("payload,network,act", [
    (STARTUP, True, True), (SYNC, False, True), (READ, False, False), (PROMPT, False, False), (SESSION_END, False, False),
])
def test_which_events_warn_for_which_reasons(tmp_path, origin, payload, network, act):
    m = started(tmp_path, origin)
    git(m.store, "remote", "set-url", "origin", str(tmp_path / "gone.git"))  # a network reason
    stamp(m, HOOK.PULL_SECONDS + 5)
    code, out, err = hook(m, payload)
    assert (code, err) == (0, b"") and last_log(m).endswith(" fetch-failed")
    assert ("systemMessage" in (json.loads(out) if out else {})) == network
    (m.xdg / "claude-config" / "deny-terms").unlink()  # a reason the user must act on
    stamp(m, HOOK.PULL_SECONDS + 5)
    stamp(m, HOOK.PULL_SECONDS + 5, "memory.failed")
    code, out, err = hook(m, payload)
    assert (code, err) == (0, b"") and last_log(m).endswith(" no-deny-terms")
    assert ("systemMessage" in (json.loads(out) if out else {})) == act
