"""The text subcommands: settings and pr-body-check. Neither touches Jira."""

import json

import pytest

from tests.skills.jira_ticket_lifecycle.conftest import SETTINGS

# ── settings ─────────────────────────────────────────────────────────────────


def test_complete_settings_print_with_defaults_filled_in(env):
    r, out = env.json("settings", "--json")
    assert r.returncode == 0, r.stderr
    assert out["project"] == "PAY"
    assert out["issueTypes"] == ["Task", "Bug", "Story"]
    assert out["defaultIssueType"] == "Task"
    assert out["addToActiveSprint"] is False
    assert out["summaryFormat"] == "{title}"
    assert out["relatedLinkType"] == "Relates"
    assert out["requireApprovedPr"] is False
    assert out["labels"]["draft"] == "spec-draft"
    assert out["specDir"] == str(env.state_home / "claude-config" / "jira-specs")


def test_old_approval_label_keys_still_load(env):
    """Approval modes are retired; a local.json written for them still loads."""
    env.settings(labels={"manual": "approval-manual", "noReview": "approval-no-review"})
    r, out = env.json("settings", "--json")
    assert r.returncode == 0, r.stderr
    assert sorted(out["labels"]) == ["approved", "draft", "hotfix"]


@pytest.mark.parametrize(
    ("overrides", "key"),
    [
        ({"project": None}, "project"),
        ({"project": "pay"}, "project"),
        ({"site": "http://example.atlassian.net"}, "site"),
        ({"stateOrder": ["To Do", "In Progress", "Done"]}, "stateOrder"),
        ({"states": {"inProgress": "In Progress", "done": "Done"}}, "states.review"),
        ({"issueTypes": ["Task"], "defaultIssueType": "Epic"}, "defaultIssueType"),
        ({"labels": {"draft": "spec draft"}}, "labels.draft"),
        ({"addToActiveSprint": "yes"}, "addToActiveSprint"),
    ],
)
def test_faulty_settings_exit_6_naming_the_key(env, overrides, key):
    values = {**SETTINGS, **overrides}
    values = {k: v for k, v in values.items() if v is not None}
    path = env.settings(raw=json.dumps({"jira": values}))
    before = (path.read_bytes(), path.stat().st_mtime_ns)
    r = env.run("settings")
    assert r.returncode == 6
    assert key in r.stderr
    assert (path.read_bytes(), path.stat().st_mtime_ns) == before


def test_no_jira_object_exits_6(env):
    env.settings(raw=json.dumps({"defaultTracker": "jira"}))
    r = env.run("settings")
    assert r.returncode == 6
    assert "jira" in r.stderr


def test_missing_or_broken_file_exits_6(env):
    env.settings(raw="{not json")
    assert env.run("settings").returncode == 6
    (env.config / "claude-config" / "local.json").unlink()
    r = env.run("settings")
    assert r.returncode == 6
    assert "local.json" in r.stderr


def test_relative_xdg_config_home_is_ignored(env):
    fallback = env.home / ".config" / "claude-config" / "local.json"
    fallback.parent.mkdir(parents=True)
    fallback.write_text(json.dumps({"jira": {**SETTINGS, "project": "HOME"}}))
    r, out = env.json("settings", "--json", XDG_CONFIG_HOME="relative/dir", XDG_STATE_HOME="rel")
    assert r.returncode == 0, r.stderr
    assert out["project"] == "HOME"
    assert out["specDir"] == str(env.home / ".local" / "state" / "claude-config" / "jira-specs")


def test_spec_dir_setting_expands_the_home_directory(env):
    env.settings(specDir="~/specs")
    _, out = env.json("settings", "--json")
    assert out["specDir"] == str(env.home / "specs")


def test_text_output_lists_the_settings(env):
    r = env.run("settings")
    assert r.returncode == 0
    assert "project: PAY" in r.stdout


# ── pr-body-check ────────────────────────────────────────────────────────────

TICKET_LINE = "Ticket: https://example.atlassian.net/browse/PAY-142"


def codes(result):
    return {p["code"] for p in json.loads(result.stdout)["problems"]}


def pr(env, body):
    return env.run("pr-body-check", "--body", env.file("pr.md", body), "--key", "PAY-142", "--json")


def good_body(spec="Spec: PAY-142"):
    return (
        f"{TICKET_LINE}\n{spec}\n\n## Tests\n- export writes a header: "
        f"test_export.py\n\n## Review\nClean.\n"
    )


def test_valid_bodies_pass(env):
    assert pr(env, good_body()).returncode == 0
    assert pr(env, good_body("spec: pay-142")).returncode == 0


@pytest.mark.parametrize(
    ("body", "code"),
    [
        (good_body().replace(TICKET_LINE + "\n", ""), "missing-ticket-line"),
        (
            good_body().replace(TICKET_LINE, TICKET_LINE.replace("PAY-142", "PAY-7")),
            "missing-ticket-line",
        ),
        (good_body("Spec: docs/notes.md"), "missing-spec-line"),
        (good_body("Spec: config/skills/foo/SPEC.md"), "missing-spec-line"),
        (good_body() + "\n### AC-1: export\n", "spec-copied"),
        (good_body() + "\nGiven a roster\nWhen exported\nThen a header\n", "spec-copied"),
        (good_body().replace("## Review\nClean.\n", ""), "missing-review"),
    ],
)
def test_bad_bodies_fail_with_a_code(env, body, code):
    r = pr(env, body)
    assert r.returncode == 1
    assert code in codes(r)


def test_ticket_line_must_come_first(env):
    body = "Some intro\n" + good_body()
    assert "missing-ticket-line" in codes(pr(env, body))


# ── usage ────────────────────────────────────────────────────────────────────


def test_no_subcommand_is_a_usage_error(env):
    assert env.run().returncode == 2


def test_help_lists_only_file_options_for_free_text(env):
    r = env.run("--help")
    assert r.returncode == 0
    for sub in ("search", "approve", "comment", "create", "sync-spec", "pr-body"):
        h = env.run(sub, "--help").stdout
        for banned in ("--text ", "--quote ", "--title ", "--summary "):
            assert banned not in h, (sub, banned)
