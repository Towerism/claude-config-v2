"""Publishing a spec into a ticket: the moved original, the markers, the refusal when someone
edited the description, the attachment for a long spec, and rebuilding the working copy."""

import json
import os
import subprocess

from tests.skills.jira_ticket_lifecycle.conftest import GIT_ENV

SPEC = "# Spec: CSV export\n\n- FR-1: The export MUST write a header row.\n"


def steps(out):
    return {s["name"]: s["status"] for s in out["steps"]}


def repo_dir(env, name="roster"):
    repo = env.tmp / name
    if not repo.exists():
        repo.mkdir()
        subprocess.run(
            ["git", "init", "-q", "-b", "main"], cwd=repo, check=True, env={**os.environ, **GIT_ENV}
        )
    return repo


def working_copy(env, key="PAY-142", text=SPEC, repo="roster"):
    path = env.state_home / "claude-config" / "jira-specs" / repo / f"{key}.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    return path


def sync(env, *extra, cwd=None):
    return env.json("sync-spec", "--key", "PAY-142", *extra, cwd=cwd or repo_dir(env))


def blocks(text):
    return [b for b in text.split("\n\n") if b]


def test_first_sync_moves_the_original_then_writes_the_spec_between_markers(rest_env):
    env = rest_env
    env.add_ticket("PAY-142", description="Users want CSV.", labels=["spec-approved"])
    working_copy(env)
    r, _out = sync(env)
    assert r.returncode == 0, r.stdout
    t = env.ticket("PAY-142")
    assert t["comments"][0].startswith("Original description, moved here by jira-ticket-lifecycle")
    assert "Users want CSV." in t["comments"][0]
    b = blocks(t["description"])
    assert (
        b[0]
        == "_Spec maintained by jira-ticket-lifecycle. The original description is in a comment._"
    )
    assert b[1] == "spec:start" and b[-1].strip() == "spec:end"
    assert "FR-1: The export MUST write a header row." in t["description"]
    assert t["labels"] == ["spec-draft"]
    record = json.loads(
        (
            env.state_home / "claude-config" / "jira-specs" / "roster" / "PAY-142.synced.json"
        ).read_text()
    )
    assert len(record["descriptionSha256"]) == 64 and record["attachmentId"] is None


def test_a_second_sync_writes_no_comment_and_isnt_refused(rest_env):
    env = rest_env
    env.add_ticket("PAY-142", description="Users want CSV.")
    working_copy(env)
    sync(env)
    working_copy(env, text=SPEC + "- FR-2: The export MUST quote commas.\n")
    r, _out = sync(env)
    assert r.returncode == 0, r.stdout
    t = env.ticket("PAY-142")
    assert len(t["comments"]) == 1
    assert "FR-2" in t["description"]
    assert t["description"].startswith("_Spec maintained by jira-ticket-lifecycle. The original")


def test_a_ticket_with_no_description_gets_the_plain_header(rest_env):
    rest_env.add_ticket("PAY-142")
    working_copy(rest_env)
    sync(rest_env)
    t = rest_env.ticket("PAY-142")
    assert t["comments"] == []
    assert t["description"].startswith("_Spec maintained by jira-ticket-lifecycle._\n")


def test_an_edit_on_the_ticket_since_the_last_sync_is_refused(rest_env):
    env = rest_env
    env.add_ticket("PAY-142")
    working_copy(env)
    sync(env)
    s = env.state()
    s["tickets"]["PAY-142"]["description"] += "\n\nA reviewer's note."
    env.write_state(s)
    edited = env.ticket("PAY-142")["description"]
    r, out = sync(env)
    assert r.returncode == 1
    assert steps(out) == {"read": "done", "check": "refused"}
    assert "A reviewer's note." in out["steps"][1]["current"]
    assert out["steps"][1]["new"] == SPEC
    assert env.ticket("PAY-142")["description"] == edited
    r, out = sync(env, "--replace")
    assert r.returncode == 0
    assert "A reviewer's note." not in env.ticket("PAY-142")["description"]


def test_markers_with_no_local_record_are_refused(rest_env):
    env = rest_env
    env.add_ticket(
        "PAY-142",
        description=(
            "_Spec maintained by jira-ticket-lifecycle._\n\nspec:start\n\nold\n\nspec:end\n"
        ),
    )
    working_copy(env)
    r, out = sync(env)
    assert r.returncode == 1
    assert steps(out)["check"] == "refused"


def test_broken_markers_exit_4_and_write_nothing(rest_env):
    rest_env.add_ticket("PAY-142", description="spec:start\n\nhalf a spec\n")
    working_copy(rest_env)
    r = rest_env.run("sync-spec", "--key", "PAY-142", "--replace", cwd=repo_dir(rest_env))
    assert r.returncode == 4
    assert rest_env.writes() == []


def test_a_failed_move_comment_leaves_the_description_alone(rest_env):
    env = rest_env
    env.add_ticket("PAY-142", description="Users want CSV.")
    env.update(canned=[{"match": "jira issue comment add", "rc": 1, "stderr": "403"}])
    working_copy(env)
    r, out = sync(env)
    assert r.returncode == 1
    assert steps(out)["move"] == "failed"
    assert env.ticket("PAY-142")["description"] == "Users want CSV."


def test_an_original_too_long_for_a_comment_is_left_alone(rest_env):
    env = rest_env
    env.add_ticket("PAY-142", description="x" * 33000)
    working_copy(env)
    _r, out = sync(env)
    assert steps(out)["move"] == "failed"
    assert "32,767" in out["steps"][-1]["detail"]
    assert env.ticket("PAY-142")["description"] == "x" * 33000


def test_a_long_spec_is_attached_and_old_copies_removed_only_after(rest_env):
    env = rest_env
    env.add_ticket("PAY-142")
    long_spec = SPEC + ("- detail line for the spec\n" * 1600)
    assert len(long_spec) > 40000
    working_copy(env, text=long_spec)
    r, _out = sync(env)
    assert r.returncode == 0, r.stdout
    t = env.ticket("PAY-142")
    assert [a["filename"] for a in t["attachments"]] == ["PAY-142-spec.md"]
    assert t["attachments"][0]["content"] == long_spec
    assert "attached as PAY-142-spec.md" in t["description"]
    assert "spec:start" in t["description"]
    first_id = t["attachments"][0]["id"]
    working_copy(env, text=long_spec + "- one more\n")
    sync(env)
    names = [(a["filename"], a["id"]) for a in env.ticket("PAY-142")["attachments"]]
    assert len(names) == 1 and names[0][1] != first_id
    rest = env.calls("rest")
    post = max(i for i, c in enumerate(rest) if c["method"] == "POST")
    delete = max(i for i, c in enumerate(rest) if c["method"] == "DELETE")
    assert post < delete
    assert all(
        c["auth"].startswith("Basic ") and c["atlassianToken"] == "no-check"
        for c in rest
        if c["method"] == "POST"
    )
    working_copy(env, text=SPEC)
    r, _out = sync(env)
    assert r.returncode == 0
    assert env.ticket("PAY-142")["attachments"] == []
    assert "FR-1" in env.ticket("PAY-142")["description"]


def test_a_failed_upload_leaves_the_description_unchanged(rest_env):
    env = rest_env
    env.add_ticket("PAY-142")
    working_copy(env)
    sync(env)
    before = env.ticket("PAY-142")["description"]
    env.update(restCanned=[{"match": "POST /rest/api/3/issue/PAY-142/attachments", "status": 500}])
    working_copy(env, text=SPEC * 2000)
    r, out = sync(env)
    assert r.returncode == 1
    assert steps(out)["attachment"] == "failed"
    assert env.ticket("PAY-142")["description"] == before


def test_jiras_size_error_falls_back_to_the_attachment(rest_env):
    env = rest_env
    env.add_ticket("PAY-142")
    env.update(descriptionLimit=200)
    working_copy(env, text=SPEC * 4)
    r, _out = sync(env)
    assert r.returncode == 0, r.stdout
    assert [a["filename"] for a in env.ticket("PAY-142")["attachments"]] == ["PAY-142-spec.md"]


def test_a_failed_cleanup_is_reported_but_the_spec_is_current(rest_env):
    env = rest_env
    env.add_ticket("PAY-142")
    working_copy(env, text=SPEC * 2000)
    sync(env)
    env.update(restCanned=[{"match": "DELETE /rest/api/3/attachment/", "status": 500}])
    working_copy(env, text=SPEC * 2001)
    r, out = sync(env)
    assert r.returncode == 1
    assert steps(out)["attachment"] == "done"
    assert steps(out)["cleanup"] == "failed"


def test_main_checkout_and_worktree_share_one_working_copy(rest_env):
    env = rest_env
    env.add_ticket("PAY-142")
    main = repo_dir(env, "roster")
    g = {**os.environ, **GIT_ENV}
    (main / "README.md").write_text("x\n")
    subprocess.run(["git", "add", "."], cwd=main, check=True, env=g)
    subprocess.run(["git", "commit", "-q", "-m", "chore: x (PAY-1)"], cwd=main, check=True, env=g)
    wt = env.tmp / "wt" / "feature-PAY-142"
    subprocess.run(
        ["git", "worktree", "add", "-q", "-b", "f", str(wt)], cwd=main, check=True, env=g
    )
    working_copy(env)
    _r, out = env.json("pull-spec", "--key", "PAY-142", cwd=wt)
    assert steps(out) == {"working-copy": "skipped"}
    assert out["steps"][0]["detail"].endswith("roster/PAY-142.md")


def test_pull_spec_rebuilds_from_the_markers_and_writes_the_record(rest_env):
    env = rest_env
    env.add_ticket("PAY-142")
    working_copy(env)
    sync(env)
    copy = env.state_home / "claude-config" / "jira-specs" / "roster" / "PAY-142.md"
    copy.unlink()
    (copy.parent / "PAY-142.synced.json").unlink()
    r, out = env.json("pull-spec", "--key", "PAY-142", cwd=repo_dir(env))
    assert r.returncode == 0, r.stdout
    assert steps(out)["working-copy"] == "done"
    assert "may differ in formatting" in out["steps"][0]["detail"]
    assert "FR-1: The export MUST write a header row." in copy.read_text()
    r, out = sync(env)
    assert r.returncode == 0, r.stdout


def test_pull_spec_with_no_spec_on_the_ticket_says_so(rest_env):
    rest_env.add_ticket("PAY-142", description="Users want CSV.")
    r, out = rest_env.json("pull-spec", "--key", "PAY-142", cwd=repo_dir(rest_env))
    assert r.returncode == 0
    assert steps(out) == {"working-copy": "none"}
    assert out["steps"][0]["detail"].endswith("roster/PAY-142.md")
