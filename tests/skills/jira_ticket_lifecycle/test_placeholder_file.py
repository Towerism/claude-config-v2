"""sync-spec --placeholder-file: when the spec is too long and is attached, the description
shows the note, then the summary."""

import subprocess

from tests.skills.jira_ticket_lifecycle.conftest import script_command
from tests.skills.jira_ticket_lifecycle.test_sync_spec import (
    SPEC,
    blocks,
    repo_dir,
    steps,
    sync,
    working_copy,
)

LONG_SPEC = SPEC + ("- detail line for the spec\n" * 1600)
NOTE = "The spec is too long for the ticket description, so it is attached as PAY-142-spec.md."
SUMMARY = "Summary: the export writes a header row, then one row per member."


def attached_ticket(env, **ticket):
    env.add_ticket("PAY-142", **ticket)
    working_copy(env, text=LONG_SPEC)


def placeholder(env, text, name="summary.md"):
    return env.file(name, text)


def refused(env, *extra):
    """Usage errors print no JSON, so this returns the raw process result."""
    return env.run("sync-spec", "--key", "PAY-142", *extra, cwd=repo_dir(env))


def inner(description):
    b = [x.strip() for x in blocks(description)]
    return b[b.index("spec:start") + 1 : b.index("spec:end")]


def test_an_attached_spec_without_the_option_gets_the_one_line_note(rest_env):
    attached_ticket(rest_env)
    r, _out = sync(rest_env)
    assert r.returncode == 0, r.stdout
    t = rest_env.ticket("PAY-142")
    assert inner(t["description"]) == [NOTE]


def test_the_summary_follows_the_note_and_the_attachment_holds_the_spec(rest_env):
    env = rest_env
    attached_ticket(env)
    r, _out = sync(env, "--placeholder-file", placeholder(env, f"\n{SUMMARY}\n\n"))
    assert r.returncode == 0, r.stdout
    t = env.ticket("PAY-142")
    note, *rest = inner(t["description"])
    assert "attached as PAY-142-spec.md" in note and "distilled" in note
    assert rest == [SUMMARY]
    assert f"\n\n{SUMMARY}\n\nspec:end" in t["description"]  # stripped: one blank line each side
    assert t["attachments"][0]["content"] == LONG_SPEC


def test_a_blank_placeholder_gives_the_one_line_note(rest_env):
    env = rest_env
    attached_ticket(env)
    r, _out = sync(env, "--placeholder-file", placeholder(env, " \n\n"))
    assert r.returncode == 0, r.stdout
    assert inner(env.ticket("PAY-142")["description"]) == [NOTE]


def test_a_marker_line_in_the_summary_is_refused_before_anything_is_attached(rest_env):
    env = rest_env
    attached_ticket(env, description="Users want CSV.")
    for bad in ("spec:start", "  spec:end  "):
        r = refused(env, "--placeholder-file", placeholder(env, f"x\n{bad}\ny\n"))
        assert r.returncode == 2, r.stdout
        assert "spec:start or spec:end" in r.stderr
    assert env.ticket("PAY-142")["attachments"] == []
    assert env.ticket("PAY-142")["description"] == "Users want CSV."
    assert not [c for c in env.calls("rest") if c["method"] == "POST"]
    # known behaviour: the original is copied into a comment before the summary is checked,
    # so each refused run posts another copy
    moves = env.ticket("PAY-142")["comments"]
    assert len(moves) == 2 and all(m.startswith("Original description") for m in moves)
    # a line that only mentions the marker is allowed
    ok = placeholder(env, "see the spec:start line\n", "ok.md")
    r, _out = sync(env, "--placeholder-file", ok)
    assert r.returncode == 0, r.stdout


def test_a_summary_that_overflows_the_description_is_refused(rest_env):
    env = rest_env
    attached_ticket(env, description="Users want CSV.")
    r = refused(env, "--placeholder-file", placeholder(env, "x" * 32600))
    assert r.returncode == 2, r.stdout
    assert "Shorten it" in r.stderr
    assert env.ticket("PAY-142")["attachments"] == []
    assert env.ticket("PAY-142")["description"] == "Users want CSV."


def test_an_unreadable_summary_file_is_a_usage_error(rest_env):
    env = rest_env
    attached_ticket(env)
    missing = env.tmp / "missing.md"
    r = refused(env, "--placeholder-file", missing)
    assert r.returncode == 2
    assert f"cannot read {missing}" in r.stderr
    assert env.ticket("PAY-142")["attachments"] == []


def test_a_dash_reads_the_summary_from_stdin(rest_env):
    env = rest_env
    attached_ticket(env)
    result = subprocess.run(
        [*script_command(), "sync-spec", "--key", "PAY-142", "--placeholder-file", "-"],
        input=SUMMARY,
        capture_output=True,
        text=True,
        cwd=repo_dir(env),
        env=env.environ(),
        timeout=60,
        check=False,
    )
    assert result.returncode == 0, result.stdout
    assert inner(env.ticket("PAY-142")["description"])[1:] == [SUMMARY]


def test_a_spec_that_fits_never_reads_the_summary_file(rest_env):
    env = rest_env
    env.add_ticket("PAY-142")
    working_copy(env)
    r, _out = sync(env, "--placeholder-file", env.tmp / "missing.md")
    assert r.returncode == 0, r.stdout
    assert "FR-1" in env.ticket("PAY-142")["description"]


def test_pull_spec_still_sees_an_attachment_placeholder_with_a_summary(rest_env):
    env = rest_env
    attached_ticket(env)
    sync(env, "--placeholder-file", placeholder(env, SUMMARY))
    copy = env.state_home / "claude-config" / "jira-specs" / "roster" / "PAY-142.md"
    copy.unlink()
    _r, out = env.json("pull-spec", "--key", "PAY-142", cwd=repo_dir(env))
    assert steps(out)["working-copy"] == "failed"
    assert "attach" in out["steps"][0]["detail"]
    assert not copy.exists()
