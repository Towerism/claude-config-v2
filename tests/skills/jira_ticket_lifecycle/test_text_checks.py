"""The text subcommands: settings, branch-name, commit-check and pr-body-check. None of them
touches Jira."""

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
    assert out["labels"]["noReview"] == "approval-no-review"
    assert out["specDir"] == str(env.state_home / "claude-config" / "jira-specs")


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


# ── branch-name ──────────────────────────────────────────────────────────────


def branch(env, title, *extra):
    path = env.file("title.txt", title)
    return env.run("branch-name", "--key", "PAY-142", "--title-file", path, *extra)


def test_branch_name_from_a_title(env):
    r = branch(env, "Add CSV export: roster (v2)!", "--type", "feat")
    assert r.stdout.strip() == "feature/PAY-142-add-csv-export-roster-v2"


@pytest.mark.parametrize(
    ("args", "prefix"),
    [
        (("--type", "fix"), "fix/"),
        (("--type", "docs"), "docs/"),
        (("--type", "refactor"), "chore/"),
        (("--type", "feat", "--hotfix"), "hotfix/"),
    ],
)
def test_branch_prefix_follows_the_type(env, args, prefix):
    assert branch(env, "Login fails", *args).stdout.startswith(prefix + "PAY-142-")


def test_long_title_cut_at_a_hyphen(env):
    r = branch(
        env, "Make the export of attendance rosters handle very large files", "--type", "feat"
    )
    slug = r.stdout.strip().split("PAY-142-", 1)[1]
    assert len(slug) <= 40
    assert not slug.endswith("-")
    assert "attendance-rosters-handle" in slug or slug.startswith("make-the-export")


def test_title_with_nothing_ascii_falls_back(env):
    assert branch(env, "日本語", "--type", "feat").stdout.strip() == "feature/PAY-142-ticket-142"


def test_shell_text_in_a_title_is_just_text(env):
    r = branch(env, "$(touch pwned) `id`", "--type", "feat")
    assert r.stdout.strip() == "feature/PAY-142-touch-pwned-id"
    assert not (env.tmp / "pwned").exists()


def test_unknown_type_and_bad_key_are_usage_errors(env):
    assert branch(env, "x", "--type", "wat").returncode == 2
    path = env.file("t.txt", "x")
    assert (
        env.run("branch-name", "--type", "feat", "--key", "pay-1", "--title-file", path).returncode
        == 2
    )


# ── commit-check ─────────────────────────────────────────────────────────────


def commit(env, message, *extra):
    return env.run("commit-check", "--message", env.file("msg.txt", message), "--json", *extra)


def codes(result):
    return {p["code"] for p in json.loads(result.stdout)["problems"]}


def test_conventional_subjects_with_a_ticket_ref_pass(env):
    assert commit(env, "feat(roster): add CSV export (PAY-142)").returncode == 0
    msg = "fix!: drop v1 route (PAY-7)\n\nBREAKING CHANGE: v1 is gone\n"
    assert commit(env, msg).returncode == 0


@pytest.mark.parametrize(
    ("message", "code"),
    [
        ("fix!: drop v1 route (PAY-7)", "breaking-needs-footer"),
        ("feat: add export", "missing-ticket-ref"),
        ("feat: add export (#42)", "missing-ticket-ref"),
        ("feat: add export (PAY-7) ", "missing-ticket-ref"),
        ("Add export (PAY-7)", "not-conventional"),
    ],
)
def test_bad_subjects_fail_with_a_code(env, message, code):
    r = commit(env, message)
    assert r.returncode == 1
    assert code in codes(r)


def test_key_option_requires_that_ticket(env):
    r = commit(env, "feat: add export (PAY-7)", "--key", "PAY-142")
    assert r.returncode == 1
    assert codes(r) == {"wrong-ticket-ref"}
    assert commit(env, "feat: add export (PAY-142)", "--key", "PAY-142").returncode == 0


def test_text_output_and_stdin(env):
    r = env.run("commit-check", "--message", env.file("m.txt", "feat: x"))
    assert r.returncode == 1
    assert "FAIL missing-ticket-ref" in r.stdout
    ok = env.run("commit-check", "--message", env.file("m2.txt", "feat: x (PAY-1)"))
    assert ok.stdout.startswith("OK")


def test_a_missing_message_file_is_a_usage_error(env):
    r = env.run("commit-check", "--message", env.tmp / "nope.txt", "--json")
    assert r.returncode == 2
    assert "error" in json.loads(r.stdout)


# ── pr-body-check ────────────────────────────────────────────────────────────

TICKET_LINE = "Ticket: https://example.atlassian.net/browse/PAY-142"


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
    for sub in ("search", "approve", "comment", "create", "branch-name", "sync-spec", "pr-body"):
        h = env.run(sub, "--help").stdout
        for banned in ("--text ", "--quote ", "--title ", "--summary "):
            assert banned not in h, (sub, banned)
