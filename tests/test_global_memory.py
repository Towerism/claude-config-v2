"""global_memory: memories that hold in any repo sync between machines through a private git repo.

Each test builds its own world in a temp dir: a bare `origin` standing in for the memory repo, and
one or more machines, each with its own home, XDG dirs and a Claude home holding the deployed hook.
Nothing touches the network or the real home.
"""

import fcntl
import json
import re
import shutil
import subprocess
import sys
import types

import pytest

from tests.conftest import ROOT, load
from tests.test_auto_sync import DRIVER, GIT_ENV, git, no_git, warned

END = {"hook_event_name": "SessionEnd"}
STARTUP = {"hook_event_name": "SessionStart", "source": "startup"}
TERM = "AcmeCorp"
BUDGET = load(ROOT / "config" / "hooks" / "global_memory.py", "global_memory_budget").BUDGET


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


def hook(m, payload=END, patch=None, stdin=None):
    """(exit code, stdout, stderr) of the deployed hook; `patch` runs first, in its module."""
    script = str(m.claude / "hooks" / "global_memory.py")
    argv = [sys.executable, "-I", script] if patch is None else [sys.executable, "-I", "-B", "-c", DRIVER, script, patch]
    data = json.dumps(payload).encode() if stdin is None else stdin
    done = subprocess.run(argv, input=data, capture_output=True, env=m.env, timeout=60, check=False)
    return done.returncode, done.stdout, done.stderr


def quiet(m, payload=END, patch=None):
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
    warned(hook(m)[1], "fetch-failed")
    assert (m.store / "new.md").is_file() and git(m.store, "ls-tree", "--name-only", "main") == "new.md"
    git(m.store, "remote", "set-url", "origin", str(origin))
    git(m.store, "remote", "set-url", "--push", "origin", str(tmp_path / "gone.git"))
    remember(m, "newer.md")
    warned(hook(m)[1], "push-failed")
    assert (m.store / "newer.md").is_file()
    assert set(git(m.store, "ls-tree", "--name-only", "main").splitlines()) == {"new.md", "newer.md"}
    assert remote_files(origin) == set()


# --- failures and when it does nothing ---------------------------------------------------


@pytest.mark.parametrize("local", [None, {}, {"memory": {}}, {"memory": {"repo": ""}}, {"memory": "x"}, {"memory": {"repo": 1}}])
@pytest.mark.parametrize("payload", [STARTUP, END])
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
    code, out, err = hook(s)
    assert (code, err) == (0, b"")
    warned(out, "fetch-failed")


@pytest.mark.parametrize("patch,reason", [
    ("hook.SAFE_PATH = '/nonexistent'\n", "no-git"),
    ("hook.FETCH_SECONDS = 0\n", "timeout"),
])
def test_no_git_or_a_step_past_its_deadline_warns(tmp_path, origin, patch, reason):
    m = machine(tmp_path, origin)
    code, out, err = hook(m, END, patch)
    assert (code, err) == (0, b"")
    warned(out, reason)


def test_a_held_lock_makes_it_skip_the_sync_quietly(tmp_path, origin):
    m = started(tmp_path, origin)
    remember(m, "clean.md")
    with open(m.claude / "claude-config" / "memory.lock", "a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        assert hook(m, END, patch=no_git(m)) == (0, b"", b"")
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


def test_session_end_syncs_and_prints_no_index(tmp_path, origin):
    m = started(tmp_path, origin)
    remember(m, "kept.md")
    assert quiet(m, END) == {}
    assert remote_files(origin) == {"kept.md"}


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
