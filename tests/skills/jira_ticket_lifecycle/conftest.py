"""Shared fixtures: run the script as a subprocess against the stateful fake CLI, a local
REST server and temp settings, so no test reads the owner's real files or reaches Jira."""

import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

import pytest

from tests.conftest import ROOT

SKILL_DIR = ROOT / "config" / "skills" / "jira-ticket-lifecycle"
SCRIPT = SKILL_DIR / "scripts" / "ticket_lifecycle.py"
FAKE = Path(__file__).resolve().parent / "fake_cli.py"
TOKEN = "placeholder-token-7f3a"
SITE = "https://example.atlassian.net"

SETTINGS = {
    "project": "PAY",
    "site": SITE,
    "states": {"inProgress": "In Progress", "review": "In Review", "done": "Done"},
    "stateOrder": ["To Do", "In Progress", "In Review", "Done"],
}
ME = {"accountId": "acc-owner", "email": "owner@example.com", "displayName": "Owner"}
OTHER = {
    "accountId": "acc-other",
    "email": "someone-else@example.com",
    "displayName": "Someone Else",
}


def script_command():
    """The command that runs the script under test."""
    return [sys.executable, "-I", str(SCRIPT)]


def make_ticket(**fields):
    """Seed ticket factory: a To Do task with no assignee unless fields say otherwise."""
    return {
        "summary": "Export times out",
        "type": "Task",
        "state": "To Do",
        "description": "",
        "labels": [],
        "assignee": None,
        **fields,
    }


class Env:
    """A temp world: settings, jira CLI config, fake jira and gh on PATH, and a REST server."""

    def __init__(self, tmp: Path):
        self.tmp = tmp
        self.bin = tmp / "bin"
        self.bin.mkdir()
        for name in (
            "jira",
            "gh",
        ):  # copies, so a test that replaces one never touches the fake itself
            shutil.copy(FAKE, self.bin / name)
        self.state_path = tmp / "fake-state.json"
        self.log_path = tmp / "fake.log"
        self.home = tmp / "home"
        self.home.mkdir()
        self.config = tmp / "xdg-config"
        self.state_home = tmp / "xdg-state"
        self.jira_config = tmp / "jira.yml"
        self.jira_config.write_text(
            f"server: {SITE}\nlogin: owner@example.com\nproject:\n  key: PAY\n"
        )
        self.server = None
        self.port = None
        self.repo = tmp / "roster"
        self.repo.mkdir()
        subprocess.run(
            ["git", "init", "-q", "-b", "main"],
            cwd=self.repo,
            check=True,
            env={**os.environ, **GIT_ENV},
            capture_output=True,
        )
        self.write_state({"me": ME, "users": [OTHER], "tickets": {}, "sprints": [], "prs": {}})
        self.settings()

    # state ---------------------------------------------------------------
    def write_state(self, state):
        self.state_path.write_text(json.dumps(state))

    def state(self):
        return json.loads(self.state_path.read_text())

    def update(self, **changes):
        s = self.state()
        s.update(changes)
        self.write_state(s)

    def add_ticket(self, key, **fields):
        s = self.state()
        s["tickets"][key] = make_ticket(**fields)
        self.write_state(s)

    def ticket(self, key):
        return self.state()["tickets"][key]

    def settings(self, raw=None, **overrides):
        path = self.config / "claude-config" / "local.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        if raw is not None:
            path.write_text(raw)
        else:
            path.write_text(
                json.dumps(
                    {"defaultTracker": "jira", "jira": {**SETTINGS, **overrides}}
                )
            )
        return path

    # calls ---------------------------------------------------------------
    def calls(self, prog=None):
        if not self.log_path.exists():
            return []
        entries = [json.loads(line) for line in self.log_path.read_text().splitlines()]
        return [e for e in entries if prog is None or e["prog"] == prog]

    def writes(self):
        """Calls that change Jira or GitHub state."""
        changing = (
            ["issue", "edit"],
            ["issue", "assign"],
            ["issue", "move"],
            ["issue", "create"],
            ["issue", "comment"],
            ["issue", "link"],
            ["sprint", "add"],
        )
        out = [c for c in self.calls("jira") if c["argv"][:2] in changing]
        out += [c for c in self.calls("rest") if c["method"] in ("POST", "DELETE")]
        out += [
            c
            for c in self.calls("gh")
            if c["argv"][:2] in (["pr", "edit"], ["pr", "ready"], ["pr", "merge"])
        ]
        return out

    # REST server ---------------------------------------------------------
    def start_rest(self):
        port_file = self.tmp / "port"
        env = self.environ()
        self.server = subprocess.Popen(
            [sys.executable, "-I", str(FAKE), "serve", "--port-file", str(port_file)],
            env=env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        for _ in range(500):
            if port_file.exists():
                self.port = int(port_file.read_text())
                return self.port
            time.sleep(0.01)
        raise RuntimeError("fake REST server didn't start")

    def stop(self):
        if self.server:
            self.server.terminate()
            self.server.wait(timeout=10)

    def environ(self, **extra):
        env = {
            "PATH": f"{self.bin}:/usr/bin:/bin",
            "HOME": str(self.home),
            "XDG_CONFIG_HOME": str(self.config),
            "XDG_STATE_HOME": str(self.state_home),
            "JIRA_CONFIG_FILE": str(self.jira_config),
            "JIRA_API_TOKEN": TOKEN,
            "FAKE_CLI_STATE": str(self.state_path),
            "FAKE_CLI_LOG": str(self.log_path),
            "LIFECYCLE_TIMEOUT": "10",
        }
        if self.port:
            env["LIFECYCLE_JIRA_REST"] = f"http://127.0.0.1:{self.port}"
        env.update({k: v for k, v in extra.items() if v is not None})
        for k, v in extra.items():
            if v is None:
                env.pop(k, None)
        return env

    def run(self, *args, cwd=None, **env):
        result = subprocess.run(
            [*script_command(), *map(str, args)],
            capture_output=True,
            text=True,
            cwd=cwd or self.repo,
            env=self.environ(**env),
            timeout=60,
            check=False,
        )
        assert TOKEN not in result.stdout + result.stderr, "the token leaked into output"
        return result

    def json(self, *args, **kw):
        r = self.run(*args, **kw)
        try:
            return r, json.loads(r.stdout)
        except ValueError:
            raise AssertionError(
                f"not JSON (rc {r.returncode}): {r.stdout!r} {r.stderr!r}"
            ) from None

    def file(self, name, content):
        path = self.tmp / name
        path.write_text(content)
        return path


@pytest.fixture
def env(tmp_path):
    e = Env(tmp_path)
    yield e
    e.stop()


@pytest.fixture
def rest_env(env):
    env.start_rest()
    return env


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


def make_repo(tmp_path, files_on_branch, base_files=None, name="repo"):
    """Temp git repo: `main` with README.md plus base_files, then `feature` adding
    files_on_branch, as in the GitHub lifecycle skill's tests."""
    repo = tmp_path / name
    repo.mkdir()
    env = {**os.environ, **GIT_ENV}

    def git(*args):
        subprocess.run(["git", *args], cwd=repo, env=env, check=True, capture_output=True)

    git("init", "-q", "-b", "main")
    (repo / "README.md").write_text("base\n")
    _write_files(repo, base_files or {})
    git("add", ".")
    git("commit", "-q", "-m", "chore: base (PAY-1)")
    git("switch", "-q", "-c", "feature")
    _write_files(repo, files_on_branch)
    git("add", ".")
    git("commit", "-q", "-m", "feat: change (PAY-2)")
    return repo
