"""Where the token may go, what the script may run, and what never reaches a shell."""

import ast
import json

from tests.skills.jira_ticket_lifecycle.conftest import SCRIPT, TOKEN


def rest_calls(env):
    return [c for c in env.calls("rest")]


def test_rest_goes_only_to_the_site_or_the_loopback_seam(rest_env):
    env = rest_env
    env.add_ticket("PAY-142")
    env.jira_config.write_text("server: https://other.example.net\nlogin: owner@example.com\n")
    r = env.run("label-actor", "--key", "PAY-142", "--label", "x")
    assert r.returncode == 5
    assert "other.example.net" in r.stdout + r.stderr
    env.jira_config.write_text("server: https://example.atlassian.net/\nlogin: owner@example.com\n")
    r = env.run(
        "label-actor",
        "--key",
        "PAY-142",
        "--label",
        "x",
        LIFECYCLE_JIRA_REST="https://evil.example",
    )
    assert r.returncode == 5
    r = env.run(
        "label-actor", "--key", "PAY-142", "--label", "x", LIFECYCLE_JIRA_REST="http://127.0.0.2:80"
    )
    assert r.returncode == 5
    assert rest_calls(env) == []
    r = env.run("label-actor", "--key", "PAY-142", "--label", "x")
    assert r.returncode == 1
    assert rest_calls(env)


def test_a_jira_config_without_a_login_or_file_is_an_auth_error(rest_env):
    env = rest_env
    env.add_ticket("PAY-142")
    env.jira_config.write_text("server: https://example.atlassian.net\n")
    assert env.run("label-actor", "--key", "PAY-142", "--label", "x").returncode == 5
    env.jira_config.unlink()
    assert env.run("label-actor", "--key", "PAY-142", "--label", "x").returncode == 5
    assert rest_calls(env) == []


def test_the_token_never_appears_in_output_even_on_rest_errors(rest_env):
    env = rest_env
    env.add_ticket("PAY-142")
    env.update(
        restCanned=[
            {
                "match": "GET /rest/api/3/myself",
                "status": 401,
                "json": {"errorMessages": [f"bad token {TOKEN}"]},
            }
        ]
    )
    r = env.run("label-actor", "--key", "PAY-142", "--label", "x")
    assert TOKEN not in r.stdout + r.stderr
    assert r.returncode == 1


def test_an_unreachable_rest_server_is_a_failed_step(env):
    env.add_ticket("PAY-142")
    r, out = env.json(
        "label-actor", "--key", "PAY-142", "--label", "x", LIFECYCLE_JIRA_REST="http://127.0.0.1:9"
    )
    assert r.returncode == 1
    assert out["addedByMe"] is None


def test_a_slow_cli_times_out_as_a_failed_step(env):
    env.add_ticket("PAY-142")
    slow = env.bin / "jira"
    slow.unlink()
    slow.write_text("#!/bin/sh\nsleep 5\n")
    slow.chmod(0o755)
    r, out = env.json("done", "--key", "PAY-142", LIFECYCLE_TIMEOUT="1")
    assert r.returncode == 1
    assert "timed out" in json.dumps(out)


def test_the_script_never_uses_a_shell_and_imports_no_raw_sockets():
    tree = ast.parse(SCRIPT.read_text())
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(a.name.split(".")[0] for a in node.names)
        elif isinstance(node, ast.ImportFrom):
            imported.add((node.module or "").split(".")[0])
        elif isinstance(node, ast.keyword) and node.arg == "shell":
            raise AssertionError("shell= passed to a subprocess call")
        elif (
            isinstance(node, ast.Attribute)
            and node.attr in ("system", "popen")
            and getattr(node.value, "id", "") == "os"
        ):
            raise AssertionError(f"os.{node.attr} used")
    assert not imported & {"socket", "http", "requests"}
    stdlib = {
        "argparse",
        "base64",
        "hashlib",
        "json",
        "os",
        "re",
        "shutil",
        "subprocess",
        "sys",
        "tempfile",
        "unicodedata",
        "urllib",
        "uuid",
        "datetime",
    }
    assert imported <= stdlib


def test_metacharacters_in_every_free_text_file_stay_inert(rest_env):
    env = rest_env
    nasty = "$(touch pwned) `touch pwned2` '; touch pwned3 # \\ \""
    env.add_ticket("PAY-142", summary=f"Export {nasty}")
    env.run("search", "--text-file", env.file("w.txt", nasty))
    env.run("comment", "--key", "PAY-142", "--body-file", env.file("c.md", nasty))
    env.run("approve", "--key", "PAY-142", "--quote-file", env.file("q.txt", nasty))
    env.run(
        "branch-name",
        "--type",
        "feat",
        "--key",
        "PAY-142",
        "--title-file",
        env.file("t.txt", nasty),
    )
    env.run(
        "create",
        "--input",
        env.file("c.json", json.dumps({"title": nasty, "description": nasty})),
        "--file-only",
    )
    assert not list(env.tmp.rglob("pwned*"))
    t = env.ticket("PAY-142")
    assert t["comments"][0] == nasty
    assert nasty in t["comments"][1]
