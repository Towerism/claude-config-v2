"""The Jira and GitHub steps against the stateful fake CLI and the local REST server."""

import json

import pytest

from tests.skills.jira_ticket_lifecycle.conftest import OTHER, SITE


def steps(out):
    return {s["name"]: s["status"] for s in out["steps"]}


def approve(env, key="PAY-142", words="i approve the spec"):
    return env.json("approve", "--key", key, "--quote-file", env.file("quote.txt", words))


# ── auth ─────────────────────────────────────────────────────────────────────


def test_auth_passes_when_everything_is_there(env):
    r, out = env.json("auth")
    assert r.returncode == 0, r.stderr
    assert out["ok"] is True


@pytest.mark.parametrize(
    ("change", "needle"),
    [({"JIRA_API_TOKEN": None}, "~/.zshenv"), ({"JIRA_API_TOKEN": ""}, "JIRA_API_TOKEN")],
)
def test_a_missing_token_exits_5_with_how_to_fix_it(env, change, needle):
    r = env.run("auth", **change)
    assert r.returncode == 5
    assert needle in r.stdout + r.stderr
    assert env.writes() == []


def test_a_failing_jira_login_or_gh_login_exits_5(env):
    env.update(canned=[{"match": "jira me", "rc": 1, "stderr": "401 Unauthorized"}])
    assert env.run("auth").returncode == 5
    env.update(canned=[], ghAuth=False)
    r = env.run("auth")
    assert r.returncode == 5
    assert "gh auth login" in r.stdout + r.stderr


def test_missing_programs_exit_5(env):
    (env.bin / "gh").unlink()
    r = env.run("auth")
    assert r.returncode == 5
    assert "gh" in r.stdout + r.stderr


def test_every_jira_step_checks_the_token_before_writing(env):
    env.add_ticket("PAY-142")
    r = env.run("claim", "--key", "PAY-142", JIRA_API_TOKEN=None)
    assert r.returncode == 5
    assert env.writes() == []


# ── view and search ──────────────────────────────────────────────────────────


def test_view_reads_a_ticket_by_key_number_or_url(env):
    env.add_ticket(
        "PAY-142", description="Users want CSV.", labels=["spec-draft"], state="In Progress"
    )
    for key in ("PAY-142", "142", f"{SITE}/browse/PAY-142"):
        r, out = env.json("view", "--key", key)
        assert r.returncode == 0, r.stderr
        assert out["key"] == "PAY-142"
        assert out["url"] == f"{SITE}/browse/PAY-142"
        t = out["ticket"]
        assert (t["summary"], t["state"], t["labels"]) == (
            "Export times out",
            "In Progress",
            ["spec-draft"],
        )
        assert "Users want CSV." in t["description"]
        assert t["hasSpecMarkers"] is False
    assert not [c for c in env.calls("jira") if c["argv"][:2] == ["issue", "list"]]


def test_view_of_a_missing_ticket_fails(env):
    r, out = env.json("view", "--key", "PAY-9")
    assert r.returncode == 1
    assert "does not exist" in out["steps"][0]["detail"]


def test_view_rejects_a_malformed_key(env):
    assert env.run("view", "--key", "pay 1; rm -rf /").returncode == 2


def test_search_lists_candidates_from_a_text_file(env):
    env.add_ticket("PAY-150", summary="Roster export times out on large files")
    env.add_ticket("PAY-151", summary="Login page typo")
    words = env.file("words.txt", 'export "timeout" \\ $(touch pwned)')
    r, out = env.json("search", "--text-file", words)
    assert r.returncode == 0, r.stderr
    assert [c["key"] for c in out["candidates"]] == ["PAY-150"]
    call = next(c for c in env.calls("jira") if c["argv"][:2] == ["issue", "list"])
    assert 'export \\"timeout\\" \\\\ $(touch pwned)' in call["argv"]
    assert not (env.tmp / "pwned").exists()
    jql = call["argv"][call["argv"].index("-q") + 1]
    assert "touch" not in jql and "export" not in jql


def test_search_with_no_match_returns_no_candidates(env):
    _, out = env.json("search", "--text-file", env.file("w.txt", "nothing matches this"))
    assert out["ok"] is True
    assert out["candidates"] == []


# ── create ───────────────────────────────────────────────────────────────────


def create_input(env, **fields):
    data = {
        "title": "Add CSV export to the roster page",
        "description": "Users want CSV.",
        **fields,
    }
    return env.file("create.json", json.dumps(data))


def test_create_makes_a_ticket_and_only_assigns_it(env):
    env.settings(addToActiveSprint=True)
    env.update(sprints=[{"id": 7, "name": "Sprint 7", "state": "active", "issues": []}])
    r, out = env.json("create", "--input", create_input(env, type="Bug"))
    assert r.returncode == 0, r.stdout
    key = out["key"]
    t = env.ticket(key)
    assert (t["summary"], t["type"], t["assignee"], t["state"]) == (
        "Add CSV export to the roster page",
        "Bug",
        "owner@example.com",
        "To Do",
    )
    assert t["description"] == "Users want CSV."
    assert env.state()["sprints"][0]["issues"] == []


def test_create_file_only_makes_no_claim(env):
    r, out = env.json("create", "--input", create_input(env), "--file-only")
    assert r.returncode == 0
    t = env.ticket(out["key"])
    assert (t["assignee"], t["state"]) == (None, "To Do")
    assert not [
        c for c in env.calls("jira") if c["argv"][:2] in (["issue", "assign"], ["issue", "move"])
    ]


def test_create_hotfix_labels_the_ticket(env):
    _, out = env.json("create", "--input", create_input(env), "--file-only", "--hotfix")
    assert env.ticket(out["key"])["labels"] == ["hotfix"]


def test_create_and_link_comments_on_each_related_ticket(env):
    env.add_ticket("PAY-150")
    env.add_ticket("PAY-151", description="keep me")
    r, out = env.json(
        "create", "--input", create_input(env), "--file-only", "--link", "PAY-150", "PAY-151"
    )
    assert r.returncode == 0, r.stdout
    key = out["key"]
    assert env.ticket(key)["links"] == [
        {"key": "PAY-150", "type": "Relates"},
        {"key": "PAY-151", "type": "Relates"},
    ]
    assert env.ticket("PAY-150")["comments"] == [f"Being worked in {SITE}/browse/{key}."]
    assert env.ticket("PAY-151")["description"] == "keep me"


def test_summary_format_and_its_repo_placeholder(env):
    env.settings(summaryFormat="{repo}: {title}")
    _, out = env.json("create", "--input", create_input(env, repo="roster"), "--file-only")
    assert env.ticket(out["key"])["summary"] == "roster: Add CSV export to the roster page"
    assert env.run("create", "--input", create_input(env), "--file-only").returncode == 2


def test_create_rejects_an_unknown_type_or_an_empty_title(env):
    assert env.run("create", "--input", create_input(env, type="Epic")).returncode == 2
    assert env.run("create", "--input", create_input(env, title="  ")).returncode == 2
    assert env.run("create", "--input", env.file("bad.json", "[1]")).returncode == 2


def test_shell_text_in_a_summary_reaches_jira_as_one_argument(env):
    title = "$(touch pwned) `touch pwned2` '; touch pwned3 # \""
    _, out = env.json("create", "--input", create_input(env, title=title), "--file-only")
    call = next(c for c in env.calls("jira") if c["argv"][:2] == ["issue", "create"])
    assert call["argv"][call["argv"].index("-s") + 1] == title
    assert env.ticket(out["key"])["summary"] == title
    assert not list(env.tmp.rglob("pwned*"))


# ── claim ────────────────────────────────────────────────────────────────────


def test_claim_only_assigns(rest_env):
    env = rest_env
    env.settings(addToActiveSprint=True)
    env.update(sprints=[{"id": 7, "name": "Sprint 7", "state": "active", "issues": []}])
    env.add_ticket("PAY-142")
    r, out = env.json("claim", "--key", "PAY-142")
    assert r.returncode == 0, r.stdout
    assert steps(out) == {"assign": "done"}
    t = env.ticket("PAY-142")
    assert (t["assignee"], t["state"], t["labels"]) == ("owner@example.com", "To Do", [])
    assert env.state()["sprints"][0]["issues"] == []
    calls = [c["argv"] for c in env.calls("jira")]
    assert not [a for a in calls if a[:1] == ["sprint"] or a[:2] == ["issue", "move"]]
    before = len(env.writes())
    r, out = env.json("claim", "--key", "PAY-142")
    assert steps(out) == {"assign": "skipped"}
    assert len(env.writes()) == before


def test_claim_refuses_someone_elses_ticket_unless_taking_over(rest_env):
    env = rest_env
    env.add_ticket("PAY-142", assignee=OTHER["email"])
    r, out = env.json("claim", "--key", "PAY-142")
    assert r.returncode == 1
    assert steps(out) == {"assign": "refused"}
    assert "Someone Else" in out["steps"][0]["detail"]
    assert env.writes() == []
    r, out = env.json("claim", "--key", "PAY-142", "--take-over")
    assert r.returncode == 0
    assert env.ticket("PAY-142")["assignee"] == "owner@example.com"


def test_claim_refuses_a_done_ticket_unless_reopening(rest_env):
    rest_env.add_ticket("PAY-142", state="Done")
    r, out = rest_env.json("claim", "--key", "PAY-142")
    assert r.returncode == 1
    assert steps(out) == {"move": "refused"}
    r, out = rest_env.json("claim", "--key", "PAY-142", "--reopen")
    assert rest_env.ticket("PAY-142")["assignee"] == "owner@example.com"
    assert steps(out) == {"assign": "done"}


# ── label provenance ─────────────────────────────────────────────────────────


def test_label_actor_trusts_only_the_owners_latest_addition(rest_env):
    env = rest_env
    env.add_ticket("PAY-142", labels=["spec-draft"])
    approve(env)
    r, out = env.json("label-actor", "--key", "PAY-142", "--label", "spec-approved")
    assert r.returncode == 0, r.stdout
    assert (out["present"], out["addedByMe"]) == (True, True)
    s = env.state()
    log = s["tickets"]["PAY-142"]["changelog"]
    log.append(
        {
            "author": {"accountId": OTHER["accountId"]},
            "created": "x",
            "items": [{"field": "labels", "fromString": "spec-approved", "toString": ""}],
        }
    )
    log.append(
        {
            "author": {"accountId": OTHER["accountId"]},
            "created": "y",
            "items": [{"field": "labels", "fromString": "", "toString": "spec-approved"}],
        }
    )
    s["tickets"]["PAY-142"]["labels"] = ["spec-approved"]
    s["changelogPageSize"] = 1
    env.write_state(s)
    r, out = env.json("label-actor", "--key", "PAY-142", "--label", "spec-approved")
    assert r.returncode == 1
    assert out["addedByMe"] is False
    assert out["author"] == OTHER["accountId"]
    pages = [c for c in env.calls("rest") if "changelog" in c["path"]]
    assert any("startAt=2" in c["path"] for c in pages)


def test_label_actor_does_not_trust_a_label_when_a_page_fails(rest_env):
    rest_env.add_ticket("PAY-142", labels=["spec-draft"])
    approve(rest_env)
    rest_env.update(
        restCanned=[{"match": "GET /rest/api/3/issue/PAY-142/changelog", "status": 500}]
    )
    r, out = rest_env.json("label-actor", "--key", "PAY-142", "--label", "spec-approved")
    assert r.returncode == 1
    assert out["addedByMe"] is None


def test_label_actor_on_an_absent_label(rest_env):
    rest_env.add_ticket("PAY-142")
    r, out = rest_env.json("label-actor", "--key", "PAY-142", "--label", "spec-approved")
    assert r.returncode == 1
    assert (out["present"], out["addedByMe"]) == (False, None)


# ── comment and approve ──────────────────────────────────────────────────────


def test_comment_posts_a_file(env):
    env.add_ticket("PAY-142")
    note = "## Review\n\n$(touch pwned) stays text.\n"
    r, _ = env.json("comment", "--key", "PAY-142", "--body-file", env.file("note.md", note))
    assert r.returncode == 0
    assert env.ticket("PAY-142")["comments"] == [note]
    assert not (env.tmp / "pwned").exists()


def test_approve_quotes_the_words_and_swaps_the_labels(env):
    env.add_ticket("PAY-142", labels=["spec-draft"])
    r, _out = approve(env)
    assert r.returncode == 0, r.stdout
    t = env.ticket("PAY-142")
    assert t["labels"] == ["spec-approved"]
    assert "> i approve the spec" in t["comments"][-1]


def test_approve_moves_to_in_progress_and_adds_to_the_sprint(env):
    env.settings(addToActiveSprint=True)
    env.update(sprints=[{"id": 7, "name": "Sprint 7", "state": "active", "issues": []}])
    env.add_ticket("PAY-142", labels=["spec-draft"])
    r, out = approve(env)
    assert r.returncode == 0, r.stdout
    assert [x["name"] for x in out["steps"]] == ["comment", "labels", "sprint", "move"]
    assert steps(out) == {"comment": "done", "labels": "done", "sprint": "done", "move": "done"}
    t = env.ticket("PAY-142")
    assert (t["state"], t["labels"]) == ("In Progress", ["spec-approved"])
    assert "PAY-142" in env.state()["sprints"][0]["issues"]
    writes = [["issue", "comment"], ["issue", "edit"], ["sprint", "add"], ["issue", "move"]]
    order = [c["argv"][:2] for c in env.calls("jira") if c["argv"][:2] in writes]
    assert order == writes


def test_approve_rerun_after_a_failed_move_posts_no_second_comment(env):
    env.add_ticket("PAY-142", labels=["spec-draft"])
    env.update(
        canned=[{"match": "jira issue move", "rc": 1, "stderr": "transition not allowed"}]
    )
    r, out = approve(env)
    assert r.returncode == 1
    assert steps(out)["move"] == "failed"
    assert "transition not allowed" in out["steps"][-1]["detail"]
    env.update(canned=[])
    r, out = approve(env)
    assert r.returncode == 0, r.stdout
    assert steps(out) == {"comment": "skipped", "labels": "skipped", "move": "done"}
    t = env.ticket("PAY-142")
    assert (len(t["comments"]), t["state"]) == (1, "In Progress")


def test_approve_rerun_after_a_failed_label_step_posts_no_second_comment(env):
    env.add_ticket("PAY-142", labels=["spec-draft"])
    env.update(canned=[{"match": "jira issue edit", "rc": 1, "stderr": "label update failed"}])
    r, out = approve(env)
    assert r.returncode == 1
    assert steps(out) == {"comment": "done", "labels": "failed"}
    env.update(canned=[])
    r, out = approve(env)
    assert r.returncode == 0, r.stdout
    assert steps(out)["comment"] == "skipped" and steps(out)["labels"] == "done"
    t = env.ticket("PAY-142")
    assert (len(t["comments"]), t["labels"]) == (1, ["spec-approved"])


def test_approve_after_a_return_to_draft_records_the_words_again(env):
    env.add_ticket("PAY-142", labels=["spec-draft"])
    approve(env)
    s = env.state()
    s["tickets"]["PAY-142"]["labels"] = ["spec-draft"]
    env.write_state(s)
    r, out = approve(env, words="the revised spec is approved")
    assert r.returncode == 0, r.stdout
    assert steps(out)["comment"] == "done"
    assert len(env.ticket("PAY-142")["comments"]) == 2
    # The same words again are already on the ticket, so they are not posted a third time.
    s = env.state()
    s["tickets"]["PAY-142"]["labels"] = ["spec-draft"]
    env.write_state(s)
    r, out = approve(env)
    assert r.returncode == 0, r.stdout
    assert steps(out)["comment"] == "skipped"
    assert len(env.ticket("PAY-142")["comments"]) == 2


def test_approve_leaves_a_later_state_alone(env):
    env.add_ticket("PAY-142", state="In Review", labels=["spec-draft"])
    _, out = approve(env)
    assert steps(out)["move"] == "skipped"
    assert env.ticket("PAY-142")["state"] == "In Review"


def test_approve_reports_an_unknown_state_and_exits_1(env):
    env.add_ticket("PAY-142", state="Blocked", labels=["spec-draft"])
    r, out = approve(env)
    assert r.returncode == 1
    assert steps(out)["move"] == "unknown-state"
    t = env.ticket("PAY-142")
    assert (t["state"], t["labels"]) == ("Blocked", ["spec-approved"])


@pytest.mark.parametrize(
    ("sprints", "status"),
    [([], "none"), ([{"id": 1, "name": "A"}, {"id": 2, "name": "B"}], "ambiguous")],
)
def test_no_or_several_active_sprints_are_warnings(env, sprints, status):
    env.settings(addToActiveSprint=True)
    env.update(sprints=sprints)
    env.add_ticket("PAY-142", labels=["spec-draft"])
    r, out = approve(env)
    assert r.returncode == 0
    assert steps(out)["sprint"] == status


def test_approve_needs_the_users_quote(env):
    env.add_ticket("PAY-142", labels=["spec-draft"])
    assert env.run("approve", "--key", "PAY-142").returncode == 2
    r = env.run("approve", "--key", "PAY-142", "--quote-file", env.file("empty.txt", " \n"))
    assert r.returncode == 2
    assert env.run("approve", "--key", "PAY-142", "--mode", "no-review").returncode == 2
    t = env.ticket("PAY-142")
    assert (t["labels"], t.get("comments", [])) == (["spec-draft"], [])


# ── PR link, body, review, merge-check, done ─────────────────────────────────

PR_URL = "https://github.com/o/r/pull/1"


def add_pr(env, **fields):
    s = env.state()
    s["prs"]["1"] = {
        "number": 1,
        "url": PR_URL,
        "state": "OPEN",
        "isDraft": True,
        "reviewDecision": "",
        "body": "Ticket: x\n",
        "title": "feat: x (PAY-142)",
        "mergedAt": None,
        **fields,
    }
    env.write_state(s)


def test_link_pr_comments_once(env):
    env.add_ticket("PAY-142")
    env.run("link-pr", "--key", "PAY-142", "--pr-url", PR_URL)
    _, out = env.json("link-pr", "--key", "PAY-142", "--pr-url", PR_URL)
    assert steps(out) == {"comment": "skipped"}
    assert env.ticket("PAY-142")["comments"] == [PR_URL]


def test_link_pr_rejects_a_url_that_isnt_a_github_pr(env):
    env.add_ticket("PAY-142")
    assert (
        env.run("link-pr", "--key", "PAY-142", "--pr-url", "https://evil.example/pull/1").returncode
        == 2
    )


def test_pr_body_writes_only_over_its_own_last_copy(env):
    env.add_ticket("PAY-142")
    add_pr(env, body="first\n")
    first = env.file("b1.md", "first\n")
    _, out = env.json("pr-body", "--key", "PAY-142", "--pr", "1", "--body", first)
    assert steps(out) == {"body": "skipped"}
    second = env.file("b2.md", "second\n")
    _, out = env.json("pr-body", "--key", "PAY-142", "--pr", "1", "--body", second)
    assert steps(out) == {"body": "done"}
    assert env.state()["prs"]["1"]["body"] == "second\n"
    s = env.state()
    s["prs"]["1"]["body"] = "edited by a reviewer\n"
    env.write_state(s)
    r, out = env.json("pr-body", "--key", "PAY-142", "--pr", "1", "--body", first)
    assert r.returncode == 1
    assert steps(out) == {"body": "refused"}
    assert out["steps"][0]["current"] == "edited by a reviewer\n"
    r, _ = env.json("pr-body", "--key", "PAY-142", "--pr", "1", "--body", first, "--replace")
    assert r.returncode == 0
    assert env.state()["prs"]["1"]["body"] == "first\n"


def test_pr_body_with_no_copy_refuses_a_body_it_didnt_write(env):
    env.add_ticket("PAY-142")
    add_pr(env, body="someone's text\n")
    _r, out = env.json(
        "pr-body", "--key", "PAY-142", "--pr", "1", "--body", env.file("b.md", "mine\n")
    )
    assert steps(out) == {"body": "refused"}


def test_review_marks_the_pr_ready_and_moves_the_ticket(env):
    env.add_ticket("PAY-142", state="In Progress")
    add_pr(env)
    r, _out = env.json("review", "--key", "PAY-142", "--pr", "1")
    assert r.returncode == 0, r.stdout
    assert env.state()["prs"]["1"]["isDraft"] is False
    assert env.ticket("PAY-142")["state"] == "In Review"


def test_review_of_a_closed_pr_is_refused(env):
    env.add_ticket("PAY-142", state="In Progress")
    add_pr(env, state="MERGED")
    r, out = env.json("review", "--key", "PAY-142", "--pr", "1")
    assert r.returncode == 1
    assert steps(out)["pr"] == "refused"
    assert env.ticket("PAY-142")["state"] == "In Progress"


@pytest.mark.parametrize(
    ("fields", "require", "rc", "needle"),
    [
        ({}, False, 0, None),
        ({"state": "CLOSED"}, False, 1, "open"),
        ({}, True, 1, "draft"),
        ({"isDraft": False}, True, 1, "approved"),
        ({"isDraft": False, "reviewDecision": "APPROVED"}, True, 0, None),
    ],
)
def test_merge_check(env, fields, require, rc, needle):
    env.settings(requireApprovedPr=require)
    add_pr(env, **fields)
    r, out = env.json("merge-check", "--pr", "1")
    assert r.returncode == rc
    if needle:
        assert needle in json.dumps(out)
    assert not [c for c in env.calls("gh") if c["argv"][:2] == ["pr", "merge"]]


def test_done_moves_forward_only(env):
    env.add_ticket("PAY-142", state="In Review")
    r, out = env.json("done", "--key", "PAY-142")
    assert r.returncode == 0
    assert env.ticket("PAY-142")["state"] == "Done"
    _, out = env.json("done", "--key", "PAY-142")
    assert steps(out) == {"move": "skipped"}


def test_results_can_also_go_to_a_file(env):
    env.add_ticket("PAY-142", state="In Review")
    out_file = env.tmp / "result.json"
    env.run("done", "--key", "PAY-142", "--out", out_file)
    assert json.loads(out_file.read_text())["key"] == "PAY-142"
