"""spec-check --key: the GitHub skill's Test plan rules, applied to the local working copy."""

import pytest

SEAM = "- seam: the export CLI | catches: a wrong exit code | misses: a slow disk"


def spec(*plan, heading="## Test plan"):
    return "# Spec: CSV export\n\n## Goal\nExport the roster.\n\n" + "\n".join([heading, *plan]) + "\n"


def working_copy(env, text, key="PAY-142"):
    path = env.state_home / "claude-config" / "jira-specs" / env.repo.name / f"{key}.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    return path


def check(env, *extra):
    return env.run("spec-check", "--key", "PAY-142", *extra)


@pytest.mark.parametrize(
    "plan",
    [
        (SEAM,),
        ("test plan: skipped: docs-only change",),
        ("test plan: skipped: no seam: needed",),
        (SEAM.replace("- seam:", "* seam:"),),
        (SEAM.replace("- seam:", "+ seam:"),),
        (SEAM.replace("- seam:", "1. seam:"),),
    ],
    ids=["seam", "skip", "seam-in-prose", "star-marker", "plus-marker", "number-marker"],
)
def test_the_working_copy_passes(env, plan):
    working_copy(env, spec(*plan))
    r = check(env)
    assert r.returncode == 0, r.stdout + r.stderr


def test_without_a_section_a_skip_line_anywhere_passes(env):
    working_copy(env, spec("- test plan: skipped: docs-only change", heading="## Pipeline"))
    r = check(env)
    assert r.returncode == 0, r.stdout + r.stderr


@pytest.mark.parametrize(
    "text",
    [
        spec(SEAM, heading="## Tests"),
        spec("- seam: the export CLI | misses: a slow disk"),
        spec("- seam: the export CLI | catches: a wrong exit code"),
        spec("test plan: skipped:   "),
        spec("test plan: skipped: <reason>"),
        spec("- seam: the export CLI | catches: a bug", "test plan: skipped: none"),
        spec(SEAM, "- seam: the import CLI | catches: a wrong exit code"),
        spec("test plan: skipped: <a real reason>"),
        spec("seam: <seam> | catches: <what it catches> | misses: <what it lets through>"),
        spec("- seam: the export CLI | catches: <what it catches> | misses: a slow disk"),
        spec("- test plan: skipped: <reason>", heading="## Pipeline"),
        spec() + "\n## Pipeline\n- test plan: skipped: docs-only change\n",
        spec("1. seam: the export CLI | catches: a bug", "test plan: skipped: none"),
        spec("* seam: the export CLI | catches: a bug", "test plan: skipped: none"),
    ],
    ids=[
        "no-section",
        "no-catches",
        "no-misses",
        "empty-reason",
        "placeholder",
        "seams-decide",
        "every-seam",
        "placeholder-reason",
        "placeholder-seam",
        "one-placeholder-part",
        "no-section-placeholder-skip",
        "skip-outside-section",
        "number-marker-decides",
        "star-marker-decides",
    ],
)
def test_the_working_copy_fails(env, text):
    working_copy(env, text)
    assert check(env).returncode == 1


def test_it_reads_the_working_copy_and_never_the_ticket(env):
    working_copy(env, spec(SEAM))
    assert check(env).returncode == 0
    assert env.calls() == []


def test_spec_overrides_the_working_copy(env):
    working_copy(env, spec(SEAM))
    other = env.file("other.md", spec("test plan: skipped: <reason>"))
    assert check(env, "--spec", other).returncode == 1


def test_no_working_copy_is_a_usage_error(env):
    r = check(env)
    assert r.returncode == 2
    assert "PAY-142.md" in r.stderr


def test_spec_needs_no_jira_settings(env):
    (env.config / "claude-config" / "local.json").unlink()
    r = check(env, "--spec", env.file("spec.md", spec(SEAM)))
    assert r.returncode == 0, r.stdout + r.stderr


def test_a_skip_line_quoted_in_prose_does_not_count(env):
    working_copy(env, spec("The rule says `test plan: skipped: <reason>` is required.", heading="## Notes"))
    assert check(env).returncode == 1
