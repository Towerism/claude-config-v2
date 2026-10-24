"""extract / replace: the spec block in the issue body. Body corruption is the top risk."""

import pytest

from tests.skills.github_issue_lifecycle.conftest import (
    END,
    FIXTURES,
    ORIGINAL,
    START,
    make_body,
    run,
    write,
)

NEW_SPEC = "# Spec: CSV export v2\n\nNew content."


@pytest.mark.parametrize("name", ["old-skill-issue-166.md", "old-skill-issue-155.md"])
class TestOldSkillBodies:
    def test_extract_returns_only_the_lines_between_the_markers(self, tmp_path, name):
        raw = (FIXTURES / name).read_text()
        lines = raw.splitlines()
        inner = lines[lines.index(START) + 1 : lines.index(END)]
        result = run("extract", "--body", FIXTURES / name)
        assert result.returncode == 0
        assert result.stdout == "\n".join(inner) + "\n"

    def test_replace_keeps_everything_outside_the_block_byte_for_byte(self, tmp_path, name):
        raw = (FIXTURES / name).read_bytes()
        spec = write(tmp_path, "spec.md", NEW_SPEC)
        out = tmp_path / "out.md"
        result = run("replace", "--body", FIXTURES / name, "--spec", spec, "--out", out)
        assert result.returncode == 0
        new = out.read_bytes()
        before = raw[: raw.index(START.encode())]
        after = raw[raw.index(END.encode()) + len(END) :]
        assert new.startswith(before)
        assert new.endswith(after)
        assert NEW_SPEC.encode() in new

    def test_round_trip_with_the_same_spec_is_identity(self, tmp_path, name):
        src = FIXTURES / name
        spec = write(tmp_path, "spec.md", run("extract", "--body", src).stdout)
        out = tmp_path / "out.md"
        run("replace", "--body", src, "--spec", spec, "--out", out)
        assert out.read_bytes() == src.read_bytes()


def test_marker_mentioned_mid_line_is_not_a_marker(tmp_path):
    body = (
        make_body(spec=f"# Spec\nThe block ends at `{END}` on its own line.\nAFTER\n") + "TRAILER\n"
    )
    result = run("extract", "--body", write(tmp_path, "b.md", body))
    assert "AFTER" in result.stdout
    assert "TRAILER" not in result.stdout and ORIGINAL not in result.stdout


def test_crlf_body_extracts_lf_and_replace_keeps_crlf_outside_block(tmp_path):
    body = make_body(spec="# Spec: X\nBODY", crlf=True)
    path = write(tmp_path, "b.md", body)
    result = run("extract", "--body", path)
    assert result.stdout == "# Spec: X\nBODY\n"
    out = tmp_path / "out.md"
    run("replace", "--body", path, "--spec", write(tmp_path, "s.md", NEW_SPEC), "--out", out)
    new = out.read_bytes()
    assert new.startswith(f"{ORIGINAL}\r\n\r\n{START}\r\n".encode())
    assert b"\nNew content." not in new.replace(b"\r\n", b"")  # no bare LF inside a CRLF body
    assert new.count(b"\n") == new.count(b"\r\n")


def test_no_markers_extract_prints_nothing_and_exits_3(tmp_path):
    result = run("extract", "--body", write(tmp_path, "b.md", make_body()))
    assert result.returncode == 3
    assert result.stdout == ""


def test_no_markers_replace_appends_block_below_original(tmp_path):
    path = write(tmp_path, "b.md", ORIGINAL)
    out = tmp_path / "out.md"
    result = run(
        "replace", "--body", path, "--spec", write(tmp_path, "s.md", NEW_SPEC), "--out", out
    )
    assert result.returncode == 0
    assert out.read_text() == f"{ORIGINAL}\n\n{START}\n{NEW_SPEC}\n{END}\n"


def test_missing_end_marker_exits_4_for_extract_and_replace_writes_nothing(tmp_path):
    path = write(tmp_path, "b.md", make_body(spec="# Spec", end_marker=False))
    assert run("extract", "--body", path).returncode == 4
    out = tmp_path / "out.md"
    result = run(
        "replace", "--body", path, "--spec", write(tmp_path, "s.md", NEW_SPEC), "--out", out
    )
    assert result.returncode == 4
    assert not out.exists()


def test_end_marker_without_start_is_malformed(tmp_path):
    path = write(tmp_path, "b.md", f"{ORIGINAL}\n{END}\n")
    assert run("extract", "--body", path).returncode == 4


def test_replace_strips_markers_if_the_new_spec_already_has_them(tmp_path):
    path = write(tmp_path, "b.md", make_body(spec="old"))
    out = tmp_path / "out.md"
    wrapped = f"{START}\n{NEW_SPEC}\n{END}\n"
    run("replace", "--body", path, "--spec", write(tmp_path, "s.md", wrapped), "--out", out)
    assert out.read_text().count(START) == 1


def test_replace_does_not_touch_text_after_the_block(tmp_path):
    body = make_body(spec="old") + "\nComment added later by a human.\n"
    path = write(tmp_path, "b.md", body)
    out = tmp_path / "out.md"
    run("replace", "--body", path, "--spec", write(tmp_path, "s.md", NEW_SPEC), "--out", out)
    assert out.read_text().endswith(f"{END}\n\nComment added later by a human.\n")


def test_large_body_is_handled(tmp_path):
    big = "x" * 70_000
    path = write(tmp_path, "b.md", make_body(original=big, spec="# Spec"))
    assert run("extract", "--body", path).stdout == "# Spec\n"
