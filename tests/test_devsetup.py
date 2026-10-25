"""The dev setup (requirements-dev.txt, Makefile) and the docs that name it."""

import re
import shlex
import shutil
import subprocess
import sys
import tomllib

import pytest

from tests.conftest import ROOT

MAKEFILE = ROOT / "Makefile"
TARGETS = ["setup", "test", "lint", "plan", "deploy", "status", "rollback"]
needs_make = pytest.mark.skipif(
    shutil.which("make") is None, reason="make not installed; the drift tests cover the Makefile"
)


def requirement_lines(path):
    lines = (line.split("#")[0].strip() for line in path.read_text().splitlines())
    return {line for line in lines if line}


def section(path, heading):
    text = path.read_text()
    match = re.search(rf"^## {re.escape(heading)}\n(.*?)(?=^## |\Z)", text, re.DOTALL | re.MULTILINE)
    assert match, f"{path.name} has no '## {heading}' section"
    return match.group(1)


def make_n(*args):
    """The recipe `make -n` would run, as one list of shell lines."""
    out = subprocess.run(
        ["make", "-n", "-C", str(ROOT), *args], capture_output=True, text=True, check=True
    )
    return out.stdout.splitlines()


def cfg_line(*args):
    lines = [line for line in make_n(*args) if "tools/cfg.py" in line]
    assert len(lines) == 1, lines
    return shlex.split(lines[0])


def test_requirements_dev_matches_pyproject_dev_group():
    dev = tomllib.loads((ROOT / "pyproject.toml").read_text())["dependency-groups"]["dev"]
    assert requirement_lines(ROOT / "requirements-dev.txt") == set(dev)
    assert {"pytest", "pytest-cov", "ruff"} <= {re.split(r"[<>=]", d)[0] for d in dev}


def test_requirements_dev_has_no_paths_urls_or_flags():
    for line in requirement_lines(ROOT / "requirements-dev.txt"):
        assert re.fullmatch(r"[A-Za-z0-9_.-]+(\[\w+\])?[<>=!~]=?[\w.]+", line), line


def test_makefile_declares_every_target_phony():
    text = MAKEFILE.read_text()
    phony = " ".join(re.findall(r"^\.PHONY:(.*)$", text, re.MULTILINE)).split()
    assert set(TARGETS) <= set(phony)


def test_venv_dir_is_gitignored():
    assert ".venv/" in (ROOT / ".gitignore").read_text().split()


def test_readme_develop_section_names_every_target():
    develop = section(ROOT / "README.md", "Develop")
    for target in ["setup", "test", "lint"]:
        assert f"make {target}" in develop
    assert "pip install pytest pytest-cov" not in develop
    assert "python3-venv" in develop


def test_readme_set_up_section_names_cfg_targets():
    setup = section(ROOT / "README.md", "Set up a machine")
    for target in ["plan", "deploy", "status", "rollback"]:
        assert f"make {target}" in setup


def test_claude_md_commands_keep_raw_commands_and_name_setup():
    commands = section(ROOT / "CLAUDE.md", "Commands")
    assert "python3 -I -m pytest" in commands
    assert "tools/cfg.py plan --host personal --target" in commands
    assert "make setup" in commands


def test_make_commands_in_docs_are_real_targets():
    for doc in ["README.md", "CLAUDE.md"]:
        for word in re.findall(r"`make (\w+)", (ROOT / doc).read_text()):
            assert word in TARGETS, (doc, word)


def test_adr_0003_allows_dev_tooling():
    adr = (ROOT / "docs/adr/0003-skills-zero-dependency.md").read_text()
    assert "make" in adr and "venv" in adr and "ruff" in adr


@needs_make
def test_setup_creates_venv_before_installing_requirements():
    lines = make_n("setup")
    venv = next(i for i, line in enumerate(lines) if "-m venv .venv" in line)
    pip = next(i for i, line in enumerate(lines) if ".venv/bin/pip install -r requirements-dev.txt" in line)
    assert venv < pip


@needs_make
def test_test_and_lint_run_through_the_venv():
    assert any(".venv/bin/python -I -m pytest" in line for line in make_n("test"))
    assert any(".venv/bin/ruff check" in line for line in make_n("lint"))


@needs_make
def test_test_sets_the_venv_up_when_missing():
    if (ROOT / ".venv/bin/python").exists():
        pytest.skip("a venv exists here")
    assert any("-m venv .venv" in line for line in make_n("test"))


@needs_make
def test_plan_forwards_host_and_target_as_single_arguments():
    argv = cfg_line("plan", "HOST=work", "TARGET=/tmp/a b")
    assert argv[argv.index("tools/cfg.py") - 1] == "-I"
    assert argv[argv.index("tools/cfg.py") + 1] == "plan"
    assert argv[argv.index("--host") + 1] == "work"
    assert argv[argv.index("--target") + 1] == "/tmp/a b"


@needs_make
def test_flags_are_omitted_when_unset():
    argv = cfg_line("plan")
    assert "--host" not in argv and "--target" not in argv


@needs_make
def test_deploy_is_a_dry_run_unless_yes_is_set():
    assert "--yes" not in cfg_line("deploy", "HOST=personal")
    assert "--yes" in cfg_line("deploy", "HOST=personal", "YES=1")


@needs_make
def test_force_and_yes_only_reach_deploy():
    assert "--force" not in cfg_line("deploy")
    assert "--force" in cfg_line("deploy", "FORCE=1")
    for target in ["plan", "status", "rollback"]:
        argv = cfg_line(target, "YES=1", "FORCE=1")
        assert "--yes" not in argv and "--force" not in argv, target


@needs_make
def test_status_and_rollback_map_to_cfg_subcommands():
    for target in ["status", "rollback"]:
        argv = cfg_line(target, "TARGET=/tmp/x")
        assert argv[argv.index("tools/cfg.py") + 1] == target
        assert argv[argv.index("--target") + 1] == "/tmp/x"


def test_cfg_plan_against_a_temp_target_changes_nothing(tmp_path):
    result = subprocess.run(
        [sys.executable, "-I", str(ROOT / "tools/cfg.py"), "plan", "--host", "personal", "--target", str(tmp_path)],
        capture_output=True, text=True, check=False,
    )
    assert result.returncode == 0, result.stderr
    assert list(tmp_path.iterdir()) == []
