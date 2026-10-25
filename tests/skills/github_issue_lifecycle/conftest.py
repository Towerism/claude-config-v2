"""Shared helpers for the github-issue-lifecycle tests: run the script as a subprocess,
build bodies and git repos, and put a recording `gh` on PATH."""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from tests.conftest import ROOT

SKILL_DIR = ROOT / "config" / "skills" / "github-issue-lifecycle"
SCRIPT = SKILL_DIR / "scripts" / "issue_lifecycle.py"
FIXTURES = Path(__file__).resolve().parent / "fixtures"

START = "<!-- spec:start -->"
END = "<!-- spec:end -->"
ORIGINAL = "Users want to export the roster as CSV."


def run(*args, stdin=None, cwd=None):
    """Run issue_lifecycle.py and return the CompletedProcess (bytes in, text out)."""
    return subprocess.run(
        [sys.executable, "-I", str(SCRIPT), *map(str, args)],
        input=stdin,
        capture_output=True,
        text=True,
        cwd=cwd,
        timeout=30,
        check=False,
    )


def make_body(original=ORIGINAL, spec=None, crlf=False, end_marker=True):
    """Issue body factory: original text, optionally followed by a spec block."""
    text = original
    if spec is not None:
        text += f"\n\n{START}\n{spec}\n"
        if end_marker:
            text += f"{END}\n"
    if crlf:
        text = text.replace("\n", "\r\n")
    return text


def write(tmp_path, name, content):
    path = tmp_path / name
    if isinstance(content, bytes):
        path.write_bytes(content)
    else:
        path.write_bytes(content.encode())
    return path


GIT_ENV = {
    "GIT_AUTHOR_NAME": "Test",
    "GIT_AUTHOR_EMAIL": "test@example.invalid",
    "GIT_COMMITTER_NAME": "Test",
    "GIT_COMMITTER_EMAIL": "test@example.invalid",
    "GIT_AUTHOR_DATE": "2026-01-01T00:00:00Z",
    "GIT_COMMITTER_DATE": "2026-01-01T00:00:00Z",
    "GIT_CONFIG_GLOBAL": os.devnull,
    "GIT_CONFIG_SYSTEM": os.devnull,
}


def _write_files(repo, files):
    for rel, content in files.items():
        path = repo / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)


def make_repo(tmp_path, files_on_branch, base_files=None):
    """Temp git repo: `main` with README.md plus base_files, then `feature` adding
    files_on_branch."""
    repo = tmp_path / "repo"
    repo.mkdir()
    env = {**os.environ, **GIT_ENV}

    def git(*args):
        subprocess.run(["git", *args], cwd=repo, env=env, check=True, capture_output=True)

    git("init", "-q", "-b", "main")
    (repo / "README.md").write_text("base\n")
    _write_files(repo, base_files or {})
    git("add", ".")
    git("commit", "-q", "-m", "chore: base (#1)")
    git("switch", "-q", "-c", "feature")
    _write_files(repo, files_on_branch)
    git("add", ".")
    git("commit", "-q", "-m", "feat: change (#2)")
    return repo


FAKE_GH = r"""
import json, os, sys
args = sys.argv[1:]
with open(os.environ["GH_LOG"], "a") as f:
    f.write(json.dumps(args) + "\n")
state = os.environ["GH_STATE"]
fail_path = os.path.join(state, "fail.json")
fail = json.load(open(fail_path)) if os.path.exists(fail_path) else {}
key = " ".join(args[:2])
if key in fail:
    sys.stderr.write(fail[key] + "\n")
    sys.exit(1)
if args[:2] == ["label", "create"] and os.path.exists(os.path.join(state, "labels_exist")):
    sys.stderr.write("label already exists\n")
    sys.exit(1)
sys.exit(0)
"""


class FakeGh:
    """A recording `gh` on PATH. Each call is logged as a JSON list of args."""

    def __init__(self, tmp: Path):
        self.tmp = tmp
        self.bin = tmp / "bin"
        self.state = tmp / "state"
        self.log = tmp / "gh.log"
        self.bin.mkdir()
        self.state.mkdir()
        gh = self.bin / "gh"
        gh.write_text(f"#!{sys.executable}\n" + FAKE_GH)
        gh.chmod(0o755)

    def labels_exist(self):
        (self.state / "labels_exist").write_text("1")

    def calls(self):
        if not self.log.exists():
            return []
        return [json.loads(line) for line in self.log.read_text().splitlines()]

    def run_bash(self, script: str):
        env = {
            **os.environ,
            "PATH": f"{self.bin}:{os.environ['PATH']}",
            "GH_LOG": str(self.log),
            "GH_STATE": str(self.state),
        }
        return subprocess.run(
            ["bash", "-c", script],
            env=env,
            cwd=self.tmp,
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )


@pytest.fixture
def gh(tmp_path):
    return FakeGh(tmp_path)
