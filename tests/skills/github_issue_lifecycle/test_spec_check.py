"""spec-check: a spec is stored only when its Test plan has a seam list or a reasoned skip."""

import pytest

from tests.skills.github_issue_lifecycle.conftest import run, write

SEAM = "- seam: the export CLI | catches: a wrong exit code | misses: a slow disk"


def spec(*plan, heading="## Test plan"):
    return "# Spec: CSV export\n\n## Goal\nExport the roster.\n\n" + "\n".join([heading, *plan]) + "\n"


def check(tmp_path, text):
    return run("spec-check", "--spec", write(tmp_path, "spec.md", text))


def test_a_seam_line_passes(tmp_path):
    assert check(tmp_path, spec(SEAM)).returncode == 0


def test_a_skip_with_a_real_reason_passes(tmp_path):
    assert check(tmp_path, spec("test plan: skipped: docs-only change")).returncode == 0


def test_no_test_plan_section_fails(tmp_path):
    r = check(tmp_path, spec(SEAM, heading="## Tests"))
    assert r.returncode == 1
    assert "Test plan" in r.stdout


def test_a_seam_line_without_catches_fails(tmp_path):
    assert check(tmp_path, spec("- seam: the export CLI | misses: a slow disk")).returncode == 1


def test_a_seam_line_without_misses_fails(tmp_path):
    assert check(tmp_path, spec("- seam: the export CLI | catches: a wrong exit code")).returncode == 1


def test_a_skip_with_an_empty_reason_fails(tmp_path):
    assert check(tmp_path, spec("test plan: skipped:   ")).returncode == 1


def test_the_placeholder_reason_fails(tmp_path):
    assert check(tmp_path, spec("test plan: skipped: <reason>")).returncode == 1


def test_seam_lines_decide_when_both_are_present(tmp_path):
    plan = ("- seam: the export CLI | catches: a wrong exit code", "test plan: skipped: none")
    assert check(tmp_path, spec(*plan)).returncode == 1


def test_a_seam_line_outside_the_section_does_not_count(tmp_path):
    text = spec("test plan: skipped: <reason>") + "\n## Notes\n" + SEAM + "\n"
    assert check(tmp_path, text).returncode == 1


def test_a_missing_spec_file_is_a_usage_error(tmp_path):
    assert run("spec-check", "--spec", tmp_path / "nope.md").returncode == 2


def test_prose_mentioning_seam_is_not_a_seam_line(tmp_path):
    assert check(tmp_path, spec("test plan: skipped: no seam: needed")).returncode == 0


def test_every_seam_line_must_be_complete(tmp_path):
    plan = (SEAM, "- seam: the import CLI | catches: a wrong exit code")
    assert check(tmp_path, spec(*plan)).returncode == 1


def test_a_placeholder_skip_reason_fails(tmp_path):
    assert check(tmp_path, spec("test plan: skipped: <a real reason>")).returncode == 1


def test_placeholder_seam_parts_fail(tmp_path):
    plan = "seam: <seam> | catches: <what it catches> | misses: <what it lets through>"
    assert check(tmp_path, spec(plan)).returncode == 1


def test_one_placeholder_seam_part_fails(tmp_path):
    plan = "- seam: the export CLI | catches: <what it catches> | misses: a slow disk"
    assert check(tmp_path, spec(plan)).returncode == 1


def test_without_a_section_a_skip_line_anywhere_passes(tmp_path):
    text = spec("- test plan: skipped: docs-only change", heading="## Pipeline")
    assert check(tmp_path, text).returncode == 0


def test_without_a_section_a_placeholder_skip_line_fails(tmp_path):
    text = spec("- test plan: skipped: <reason>", heading="## Pipeline")
    assert check(tmp_path, text).returncode == 1


def test_with_a_section_a_skip_line_outside_it_does_not_count(tmp_path):
    text = spec() + "\n## Pipeline\n- test plan: skipped: docs-only change\n"
    assert check(tmp_path, text).returncode == 1


@pytest.mark.parametrize("marker", ["* ", "+ ", "1. ", "12. "])
def test_a_seam_line_may_start_with_a_list_marker(tmp_path, marker):
    line = SEAM.replace("- seam:", marker + "seam:")
    assert check(tmp_path, spec(line)).returncode == 0


@pytest.mark.parametrize("marker", ["* ", "+ ", "1. "])
def test_an_incomplete_marked_seam_line_still_decides(tmp_path, marker):
    plan = (marker + "seam: the export CLI | catches: a wrong exit code", "test plan: skipped: none")
    assert check(tmp_path, spec(*plan)).returncode == 1
