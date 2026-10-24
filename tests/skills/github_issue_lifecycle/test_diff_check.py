"""diff-check against a real temp git repo: spec IDs in code and committed spec files."""

import json

from tests.skills.github_issue_lifecycle.conftest import make_repo, run

CLEAN = {
    "src/export.py": "def write_header():\n    return 'a,b'\n",
    "tests/test_export.py": "def test_export_writes_header():\n    pass\n",
}


def check(repo):
    return run("diff-check", "--base", "main", "--repo-dir", repo, "--json")


def test_spec_id_in_test_name_and_spec_file_both_reported(tmp_path):
    repo = make_repo(
        tmp_path,
        {
            "tests/test_x.py": "def test_ac3_rejects_empty():\n    pass\n",
            "docs/feature-spec.md": "# Spec\n",
        },
    )
    r = check(repo)
    assert r.returncode == 1
    codes = {p["code"] for p in json.loads(r.stdout)["problems"]}
    assert codes == {"spec-id", "spec-file"}


def test_clean_branch_passes(tmp_path):
    assert check(make_repo(tmp_path, CLEAN)).returncode == 0


def test_skill_spec_inspection_doc_and_playwright_spec_are_allowed(tmp_path):
    repo = make_repo(
        tmp_path,
        {
            ".claude/skills/foo/SKILL.md": "---\nname: foo\n---\n",
            ".claude/skills/foo/SPEC.md": "# Spec\n- FR-1: x\n",
            "docs/inspection.md": "# Inspection\n",
            "e2e/login.spec.ts": "test('login', () => {})\n",
        },
    )
    r = check(repo)
    assert r.returncode == 0, r.stdout


def test_uppercase_hyphenated_id_in_a_comment_is_reported(tmp_path):
    repo = make_repo(tmp_path, {"src/a.ts": "// covers AC-12\nexport const a = 1\n"})
    assert check(repo).returncode == 1


def test_infra_names_like_ec2_are_not_spec_ids(tmp_path):
    repo = make_repo(
        tmp_path,
        {"infra/main.tf": 'resource "aws_instance" "ec2 box" {}\n', "src/os2.py": "x = 'os2'\n"},
    )
    assert check(repo).returncode == 0


def test_specs_directory_and_spec_basenames_are_spec_files(tmp_path):
    for i, name in enumerate(["specs/auth.md", "SPEC.md", "spec-auth.md", "auth.spec.md"]):
        (tmp_path / str(i)).mkdir()
        repo = make_repo(tmp_path / str(i), {name: "# Spec\n"})
        problems = json.loads(check(repo).stdout)["problems"]
        assert [p["code"] for p in problems] == ["spec-file"], name


def test_spec_ids_in_markdown_docs_are_not_code(tmp_path):
    repo = make_repo(tmp_path, {"docs/adr/0003-export.md": "Addresses FR-2 of the design.\n"})
    assert check(repo).returncode == 0


def test_bad_base_is_a_usage_error(tmp_path):
    repo = make_repo(tmp_path, CLEAN)
    r = run("diff-check", "--base", "nope", "--repo-dir", repo)
    assert r.returncode == 2


def problems(repo):
    return json.loads(check(repo).stdout)["problems"]


def reported_ids(repo):
    return sorted(p["detail"].rsplit(": ", 1)[1] for p in problems(repo) if p["code"] == "spec-id")


LIVING_BASE = {
    "docs/design.md": "The export follows FR-23 and keeps the header row.\n",
    "config/settings.json": "{}\n",
    "config/SPEC.md": "- FR-15a: the fragment renders the home path.\n",
    "docs/history/old.md": "Frozen copy: AC-9 applied once.\n",
    "notes/archive/2025.md": "Archived: EC-4.\n",
}
CITING_CODE = {
    "src/export.py": "# FR-23 keeps the header row\nLIMIT = 'FR-15a'\nOLD = 'AC-9'\nX = 'NFR-4'\n",
    "tests/test_export.py": "def test_fr23_rejects_empty():\n    pass\n",
    "src/legacy.py": "# EC-4 from the archive\n",
}


def test_ids_that_living_docs_define_are_allowed_but_history_and_archive_do_not_count(tmp_path):
    repo = make_repo(tmp_path, CITING_CODE, base_files=LIVING_BASE)
    assert check(repo).returncode == 1
    assert reported_ids(repo) == ["AC-9", "EC-4", "NFR-4"]


def test_a_doc_added_on_the_branch_defines_ids_in_any_spelling(tmp_path):
    branch = {**CITING_CODE, "docs/more.md": "See NFR4, ac_9 and ec-004 for details.\n"}
    repo = make_repo(tmp_path, branch, base_files=LIVING_BASE)
    assert check(repo).returncode == 0, check(repo).stdout


def test_an_id_only_inside_a_longer_word_in_docs_is_not_defined(tmp_path):
    repo = make_repo(
        tmp_path,
        {"src/a.py": "# AC-3 behaviour\n"},
        base_files={"docs/codec.md": "We decode TRAC-3 and MAC3 streams.\n"},
    )
    assert reported_ids(repo) == ["AC-3"]


def test_a_spec_file_next_to_its_subject_is_accepted_and_one_among_docs_is_not(tmp_path):
    repo = make_repo(
        tmp_path,
        {
            "config/SPEC.md": "# Spec\n",
            "tools/foo/SPEC.md": "# Spec\n",
            "tools/foo/run.py": "print('x')\n",
            "skills/bar/SKILL.md": "---\nname: bar\n---\n",
            "skills/bar/SPEC.md": "# Spec\n",
            "docs/feature-spec.md": "# Spec\n",
            "specs/login.md": "# Spec\n",
        },
        base_files={"config/settings.json": "{}\n", "docs/guide.md": "# Guide\n"},
    )
    reported = sorted(p["detail"].split(" ", 1)[0] for p in problems(repo))
    assert reported == ["docs/feature-spec.md", "specs/login.md"]


def test_a_subfolder_is_not_a_subject_for_a_spec_beside_it(tmp_path):
    repo = make_repo(
        tmp_path,
        {"docs/feature-spec.md": "# Spec\n"},
        base_files={"docs/guide.md": "# Guide\n", "docs/img/diagram.svg": "<svg/>\n"},
    )
    assert [p["code"] for p in problems(repo)] == ["spec-file"]


def test_a_doc_line_with_an_unusual_line_separator_still_defines_its_ids(tmp_path):
    repo = make_repo(
        tmp_path,
        {"src/a.py": "# FR-7 keeps the order\n"},
        base_files={"docs/notes.md": "Intro\u2028then FR-7 applies.\n"},
    )
    assert check(repo).returncode == 0, check(repo).stdout
