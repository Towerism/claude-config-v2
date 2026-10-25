"""The fake CLI itself: answers the tests rely on."""

import json
import subprocess
import sys

import pytest


@pytest.mark.parametrize(
    ("numbers", "latest"), [(["7"], 7), (["2", "10", "9"], 10), (["10", "9", "2"], 10)]
)
def test_pr_view_without_a_number_shows_the_highest_numbered_pr(env, numbers, latest):
    env.update(prs={n: {"number": int(n), "url": f"https://github.com/o/r/pull/{n}"} for n in numbers})
    done = subprocess.run(
        [sys.executable, "-I", str(env.bin / "gh"), "pr", "view", "--json", "number"],
        capture_output=True, text=True, env=env.environ(), timeout=30, check=False,
    )
    assert done.returncode == 0, done.stderr
    assert json.loads(done.stdout) == {"number": latest}
