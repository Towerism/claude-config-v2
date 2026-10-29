"""Every failure of jira, gh or REST becomes a named failed step and exit 1, never a crash and
never a success; and the input checks that guard each step."""

import json

import pytest

from tests.skills.jira_ticket_lifecycle.conftest import OTHER, SETTINGS


def steps(out):
    return {s["name"]: s["status"] for s in out["steps"]}


def fail(match, stderr="Error: something broke", rc=1, **extra):
    return {"match": match, "rc": rc, "stderr": stderr, **extra}


PR = {
    "number": 1,
    "url": "https://github.com/o/r/pull/1",
    "state": "OPEN",
    "isDraft": True,
    "reviewDecision": "",
    "body": "b\n",
    "title": "t",
    "mergedAt": None,
}


def setup(env, ticket=None, pr=None, sprints=None, **settings):
    if settings:
        env.settings(**settings)
    if ticket is not None:
        env.add_ticket("PAY-142", **ticket)
    s = env.state()
    if pr is not None:
        s["prs"]["1"] = {**PR, **pr}
    if sprints is not None:
        s["sprints"] = sprints
    env.write_state(s)


SPRINT = [{"id": 7, "name": "Sprint 7", "state": "active", "issues": []}]

CASES = {
    "view: unreadable ticket JSON": (
        {},
        [fail("jira issue view", rc=0, stdout="garbage")],
        ("view",),
        "read",
    ),
    "search: CLI error": (
        None,
        [fail("jira issue list", "Error: 500 server")],
        ("search",),
        "search",
    ),
    "claim: missing ticket": (None, [], ("claim",), "read"),
    "claim: assign fails": ({}, [fail("jira issue assign")], ("claim",), "assign"),
    "claim: sprint list fails": (
        {"_settings": {"addToActiveSprint": True}},
        [fail("jira sprint list", "Error: board not found")],
        ("claim",),
        "sprint",
    ),
    "claim: sprint add fails": (
        {"_settings": {"addToActiveSprint": True}, "_sprints": SPRINT},
        [fail("jira sprint add")],
        ("claim",),
        "sprint",
    ),
    "create: CLI error": (None, [fail("jira issue create")], ("create",), "create"),
    "create: no key printed": (
        None,
        [fail("jira issue create", rc=0, stdout="ok\n")],
        ("create",),
        "create",
    ),
    "create: link fails": ({}, [fail("jira issue link")], ("create-link",), "link"),
    "approve: missing ticket": (None, [], ("approve",), "read"),
    "approve: comment fails": (
        {"labels": ["spec-draft"]},
        [fail("jira issue comment add")],
        ("approve",),
        "comment",
    ),
    "link-pr: missing ticket": (None, [], ("link-pr",), "read"),
    "link-pr: comment fails": ({}, [fail("jira issue comment add")], ("link-pr",), "comment"),
    "comment: too long": ({}, [], ("comment-long",), "comment"),
    "pr-body: view fails": ({}, [fail("gh pr view")], ("pr-body",), "body"),
    "pr-body: closed PR": ({"_pr": {"state": "CLOSED", "body": "x"}}, [], ("pr-body",), "body"),
    "pr-body: edit fails": (
        {"_pr": {"body": "x\n"}},
        [fail("gh pr edit")],
        ("pr-body-replace",),
        "body",
    ),
    "pr view: not JSON": (
        {},
        [fail("gh pr view", rc=0, stdout="nope")],
        ("merge-check",),
        "checks",
    ),
    "review: view fails": ({}, [fail("gh pr view")], ("review",), "pr"),
    "review: ready fails": ({"_pr": {}}, [fail("gh pr ready")], ("review",), "pr"),
    "review: missing ticket": (
        {"_pr": {"isDraft": False}, "_key": "PAY-9"},
        [],
        ("review",),
        "read",
    ),
    "done: missing ticket": (None, [], ("done",), "read"),
    "sync: missing ticket": (None, [], ("sync",), "read"),
    "sync: description edit fails": (
        {},
        [fail("jira issue edit", "Error: 403 forbidden")],
        ("sync",),
        "description",
    ),
    "sync: read-back fails": ({}, [fail("jira issue view", skip=1)], ("sync",), "record"),
    "pull: missing ticket": (None, [], ("pull",), "read"),
}


def command(env, kind, key="PAY-142"):
    f = env.file
    return {
        "view": ["view", "--key", key],
        "search": ["search", "--text-file", f("w.txt", "export")],
        "claim": ["claim", "--key", key],
        "create": [
            "create",
            "--input",
            f("c.json", json.dumps({"title": "T", "description": "D"})),
            "--file-only",
        ],
        "create-link": [
            "create",
            "--input",
            f("c.json", json.dumps({"title": "T"})),
            "--file-only",
            "--link",
            key,
        ],
        "approve": ["approve", "--key", key, "--quote-file", f("q.txt", "approve")],
        "link-pr": ["link-pr", "--key", key, "--pr-url", PR["url"]],
        "comment-long": ["comment", "--key", key, "--body-file", f("c.md", "x" * 40000)],
        "pr-body": ["pr-body", "--key", key, "--pr", "1", "--body", f("b.md", "new\n")],
        "pr-body-replace": [
            "pr-body",
            "--key",
            key,
            "--pr",
            "1",
            "--body",
            f("b.md", "new\n"),
            "--replace",
        ],
        "merge-check": ["merge-check", "--pr", "1"],
        "review": ["review", "--key", key, "--pr", "1"],
        "done": ["done", "--key", key],
        "sync": ["sync-spec", "--key", key, "--spec", f("s.md", "# Spec\n")],
        "pull": ["pull-spec", "--key", key],
    }[kind]


@pytest.mark.parametrize("name", sorted(CASES))
def test_a_failure_is_a_named_failed_step(rest_env, name):
    env = rest_env
    ticket, canned, (kind,), step = CASES[name]
    key = "PAY-142"
    if ticket is not None:
        ticket = dict(ticket)
        settings = ticket.pop("_settings", {})
        pr = ticket.pop("_pr", None)
        sprints = ticket.pop("_sprints", None)
        key = ticket.pop("_key", key)
        setup(env, ticket, pr=pr, sprints=sprints, **settings)
    env.update(canned=canned)
    r, out = env.json(*command(env, kind, key))
    assert r.returncode == 1, (r.stdout, r.stderr)
    assert out["ok"] is False
    failed = [s for s in out["steps"] if s["status"] in ("failed", "refused")]
    assert failed and failed[-1]["name"] == step, out["steps"]
    assert failed[-1].get("detail")


def test_claim_on_someone_elses_ticket_when_myself_fails(rest_env):
    rest_env.add_ticket("PAY-142", assignee=OTHER["email"])
    rest_env.update(restCanned=[{"match": "GET /rest/api/3/myself", "status": 500}])
    r, out = rest_env.json("claim", "--key", "PAY-142")
    assert r.returncode == 1
    assert steps(out) == {"assign": "failed"}


def test_label_actor_read_failure_and_unrelated_changelog_items(rest_env):
    env = rest_env
    r, out = env.json("label-actor", "--key", "PAY-142", "--label", "x")
    assert steps(out) == {"read": "failed"}
    env.add_ticket("PAY-142", labels=["spec-approved"])
    s = env.state()
    s["tickets"]["PAY-142"]["changelog"] = [
        {
            "author": {"accountId": "acc-owner"},
            "items": [{"field": "status", "toString": "spec-approved"}],
        }
    ]
    env.write_state(s)
    r, out = env.json("label-actor", "--key", "PAY-142", "--label", "spec-approved")
    assert r.returncode == 1
    assert out["addedByMe"] is None
    assert "no change that added the label" in out["steps"][-1]["detail"]


def test_an_attachment_upload_with_no_id_fails(rest_env):
    rest_env.add_ticket("PAY-142")
    rest_env.update(
        restCanned=[
            {"match": "POST /rest/api/3/issue/PAY-142/attachments", "status": 200, "json": {}}
        ]
    )
    _r, out = rest_env.json(
        "sync-spec", "--key", "PAY-142", "--spec", rest_env.file("s.md", "x\n" * 20000)
    )
    assert steps(out)["attachment"] == "failed"
    assert "no attachment id" in out["steps"][-1]["detail"]


def test_a_failed_note_write_after_an_upload_keeps_old_attachments(rest_env):
    env = rest_env
    env.add_ticket("PAY-142")
    env.update(canned=[fail("jira issue edit", "Error: 403")])
    r, out = env.json("sync-spec", "--key", "PAY-142", "--spec", env.file("s.md", "x\n" * 20000))
    assert r.returncode == 1
    assert steps(out)["attachment"] == "done"
    assert steps(out)["description"] == "failed"
    assert "older attachments were kept" in out["steps"][-1]["detail"]


def test_pull_spec_cant_download_an_attached_spec(rest_env):
    env = rest_env
    env.add_ticket("PAY-142")
    env.run("sync-spec", "--key", "PAY-142", "--spec", env.file("s.md", "x\n" * 20000))
    r, out = env.json("pull-spec", "--key", "PAY-142")
    assert r.returncode == 1
    assert "PAY-142-spec.md" in out["steps"][-1]["detail"]


def test_sync_needs_a_working_copy(env):
    env.add_ticket("PAY-142")
    assert env.run("sync-spec", "--key", "PAY-142").returncode == 2


def test_sync_has_no_skill_spec_pointer(env):
    env.add_ticket("PAY-142")
    assert env.run("sync-spec", "--key", "PAY-142", "--pointer", "skills/a/SPEC.md").returncode == 2


def test_view_reads_lists_line_breaks_and_odd_nodes(env):
    env.add_ticket("PAY-142")
    raw = {
        "key": "PAY-142",
        "fields": {
            "summary": "S",
            "status": {"name": "To Do"},
            "labels": [],
            "description": {
                "type": "doc",
                "content": [
                    {
                        "type": "paragraph",
                        "content": [
                            {"type": "text", "text": "one"},
                            {"type": "hardBreak"},
                            {"type": "text", "text": "two"},
                            "stray",
                        ],
                    },
                    {
                        "type": "bulletList",
                        "content": [
                            {
                                "type": "listItem",
                                "content": [
                                    {
                                        "type": "paragraph",
                                        "content": [{"type": "text", "text": "item"}],
                                    }
                                ],
                            }
                        ],
                    },
                ],
            },
        },
    }
    env.update(canned=[{"match": "jira issue view", "stdout": json.dumps(raw)}])
    _, out = env.json("view", "--key", "PAY-142")
    assert out["ticket"]["description"] == "one\ntwo\n\n- item"


def test_search_skips_lines_that_arent_tickets(env):
    env.update(
        canned=[{"match": "jira issue list", "stdout": "KEY\tSUMMARY\nPAY-1\tA thing\topen\t\n"}]
    )
    _, out = env.json("search", "--text-file", env.file("w.txt", "thing"))
    assert [c["key"] for c in out["candidates"]] == ["PAY-1"]


def test_input_checks(env):
    f = env.file
    assert env.run("search", "--text-file", f("w.txt", "   \n")).returncode == 2
    assert (
        env.run(
            "create", "--input", f("c.json", json.dumps({"title": "T", "description": 5}))
        ).returncode
        == 2
    )
    assert (
        env.run("create", "--input", f("c.json", json.dumps({"title": "T" * 300}))).returncode == 2
    )
    assert env.run("create", "--input", f("c.json", "{nope")).returncode == 2
    assert env.run("approve", "--key", "PAY-142").returncode == 2


def test_missing_programs(env):
    (env.bin / "jira").unlink()
    r = env.run("done", "--key", "PAY-142", PATH=str(env.bin))
    assert r.returncode == 5
    assert "jira" in r.stderr
    (env.bin / "gh").unlink()
    r, out = env.json("auth", PATH=str(env.bin))
    assert r.returncode == 5
    assert "jira, gh" in out["steps"][0]["detail"]
    r, out = env.json("merge-check", "--pr", "1", PATH=str(env.bin))
    assert r.returncode == 1
    assert "isn't on PATH" in out["steps"][0]["detail"]


def test_review_of_a_pr_already_ready(env):
    setup(env, {"state": "In Progress"}, pr={"isDraft": False})
    _, out = env.json("review", "--key", "PAY-142", "--pr", "1")
    assert steps(out)["pr"] == "skipped"


@pytest.mark.parametrize(
    ("labels", "fault"),
    [("not a dict", "labels"), ({"bogus": "x"}, "labels.bogus"), ({"draft": "my-draft"}, None)],
)
def test_label_settings(env, labels, fault):
    env.settings(raw=json.dumps({"jira": {**SETTINGS, "labels": labels}}))
    r = env.run("settings", "--json")
    if fault:
        assert r.returncode == 6 and fault in r.stderr
    else:
        assert json.loads(r.stdout)["labels"]["draft"] == "my-draft"


def test_a_state_order_that_isnt_a_list(env):
    env.settings(stateOrder="To Do, Done")
    r = env.run("settings")
    assert r.returncode == 6 and "stateOrder" in r.stderr


def test_states_out_of_order(env):
    env.settings(stateOrder=["To Do", "In Review", "In Progress", "Done"])
    assert "in that order" in env.run("settings").stderr


def test_temp_files_go_under_the_job_directory(env, tmp_path):
    env.add_ticket("PAY-142")
    job = tmp_path / "job"
    job.mkdir()
    env.run(
        "comment",
        "--key",
        "PAY-142",
        "--body-file",
        env.file("c.md", "hi"),
        CLAUDE_JOB_DIR=str(job),
    )
    quote = env.file("q.txt", "i approve the spec")
    approve = env.run(
        "approve", "--key", "PAY-142", "--quote-file", quote, CLAUDE_JOB_DIR=str(job)
    )
    assert approve.returncode == 0
    call = [c for c in env.calls("jira") if c["argv"][:3] == ["issue", "comment", "add"]][-1]
    template = call["argv"][call["argv"].index("--template") + 1]
    assert template.startswith(str(job / "tmp") + "/")


def test_claim_when_jira_me_fails(env):
    env.add_ticket("PAY-142")
    env.update(canned=[fail("jira me", "Error: 401")])
    r = env.run("claim", "--key", "PAY-142")
    assert r.returncode == 5
    assert "jira me" in r.stderr


def test_pull_spec_treats_the_attachment_note_as_no_spec_even_if_the_file_is_gone(rest_env):
    env = rest_env
    env.add_ticket("PAY-142")
    env.run("sync-spec", "--key", "PAY-142", "--spec", env.file("s.md", "x\n" * 20000))
    s = env.state()
    s["tickets"]["PAY-142"]["attachments"] = []
    env.write_state(s)
    r, out = env.json("pull-spec", "--key", "PAY-142")
    assert r.returncode == 1
    assert "PAY-142-spec.md" in out["steps"][-1]["detail"]
    assert not list(env.state_home.rglob("PAY-142.md"))
