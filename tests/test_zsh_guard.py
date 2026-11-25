"""zsh_guard: denies two zsh patterns that leak secrets. Each case runs the real hook as a process.

Spikes (zsh 5.9.2, `zsh -c`, run before the hook was written):

Modifiers. zsh applies `:MOD` to an unbraced `$NAME` in double quotes and unquoted, not in single quotes:
  X=a/b; echo "$X:t"             -> b
  X=a/b; echo $X:t               -> b
  X=a/b; echo "$X:token"         -> boken        (":t" applied, "oken" left)
  X=a/b; echo "$X:hello"         -> aello        (":h" applied)
  set -- a/b; echo "$1:t"        -> b
  X=a/b; echo "$X:gt"            -> b
  X=a/b; echo "$X:s/a/z/"        -> z/b
  X=a/b.c; echo "$X:r" "$X:e" "$X:h" "$X:u" "$X:q"  -> a/b c a A/B.C a/b.c
  X=ab; echo "$X:l" "$X:a" "$X:A" "$X:c" "$X:Q" "$X:P"  -> ab /private/tmp/ab /private/tmp/ab /usr/sbin/ab ab /private/tmp/ab
  X=a/b; echo "$X:&"            -> a/b          (":&" repeats the last substitution)
Left alone (colon kept as text):
  X=a/b; echo "${X}:t"           -> a/b:t
  X=a/b; echo "$X:x" "$X: y"     -> a/b:x a/b: y
  A=u; B=p; echo "Authorization: $A:$B"  -> Authorization: u:p   (":" then "$" is no modifier)
  X=a/b; echo '$X:t'             -> $X:t
  X=a/b; echo \\$X:t              -> $X:t
  X=ab; echo "$X:L" "$X:w" "$X:f"  -> ab:L ab:w ab:f

MULTIOS (on by default in zsh): a redirect of stdout to a file in a pipe's left segment tees stdout into the pipe too.
  echo secret 2>&1 >/dev/null | cat            -> secret
  echo secret >/dev/null 2>&1 | cat            -> secret
  echo secret 2>&1 1>/dev/null | cat           -> secret
  echo secret > f 2>&1 | cat; cat f            -> secret, secret
  echo secret 2>&1 | cat                       -> secret   (no second redirect: the pipe is what was asked for)
  echo secret >/dev/null 2>&1 && echo ok | cat -> ok      (no pipe after the redirects)
  setopt nomultios; echo secret 2>&1 >/dev/null | cat  -> (nothing)
"""

import json
import subprocess
import sys

import pytest

from tests.conftest import ROOT

HOOK = ROOT / "config" / "hooks" / "zsh_guard.py"


def run(stdin):
    stdin = stdin if isinstance(stdin, bytes) else json.dumps(stdin).encode()
    done = subprocess.run([sys.executable, "-I", str(HOOK)], input=stdin, capture_output=True, timeout=10, check=False)
    assert done.returncode == 0 and done.stderr == b""
    return done.stdout.decode()


def bash(command):
    return {"hook_event_name": "PreToolUse", "tool_name": "Bash", "tool_input": {"command": command}}


def reason(command):
    out = run(bash(command))
    if not out:
        return None
    data = json.loads(out)
    assert set(data) == {"hookSpecificOutput"}
    assert data["hookSpecificOutput"]["hookEventName"] == "PreToolUse"
    assert data["hookSpecificOutput"]["permissionDecision"] == "deny"
    return data["hookSpecificOutput"]["permissionDecisionReason"]


MODIFIED = [
    'echo "$X:t"', "echo $X:h", 'echo "$1:t"', 'echo "$X:gs/a/b/"', 'echo "$X:s/a/b/"', 'echo "$X:token"',
    'curl "https://$HOST:user@x"', 'echo "$X:&"', 'echo "$X:gt"', "echo 'a' \"$Y:t\"",
    *(f'echo "$X:{m}"' for m in "hrtelquQaAcP"),
]
UNMODIFIED = [
    'echo "${X}:t"', 'echo "$X:x"', 'echo "$X: y"', 'echo "Authorization: $A:$B"', 'echo "$X"', 'echo "$X:"',
    'echo "$PATH:/usr/bin"', 'echo "$X:3000"', "echo '$X:t'", r'echo \$X:t', r'echo "\$X:t"', 'echo "$X:L"',
    "echo '$X:t' \"${Y}:t\"",
]


@pytest.mark.parametrize("command", MODIFIED)
def test_denies_an_unbraced_variable_a_colon_modifier_would_eat(command):
    assert "${VAR}:" in reason(command)


@pytest.mark.parametrize("command", UNMODIFIED)
def test_leaves_colons_zsh_keeps_as_text(command):
    assert reason(command) is None


MULTIOS = [
    "cmd 2>&1 >/dev/null | grep x", "cmd >f 2>&1 | grep x", "cmd 2>&1 >>f | x", "cmd 2>&1 1>f | x", "cmd &>f 2>&1 | x",
    "a | b 2>&1 >f | c", "a && cmd 2>&1 >f | c",
]
SAFE_REDIRECTS = [
    "cmd 2>&1 | cat", "cmd >/dev/null 2>&1 && x", "cmd 2>/dev/null | cat", "cmd >f | cat", 'echo "2>&1 >f" | cat',
    "a | b 2>&1 >f", "cmd 2>&1 >f; x | y", "cmd 2>&1 >f || x", "cmd 2>&1 >&3 | x",
]


@pytest.mark.parametrize("command", MULTIOS)
def test_denies_stderr_to_pipe_plus_stdout_redirect(command):
    assert "nomultios" in reason(command)


@pytest.mark.parametrize("command", SAFE_REDIRECTS)
def test_leaves_redirects_that_do_not_tee_into_a_pipe(command):
    assert reason(command) is None


@pytest.mark.parametrize(
    "stdin",
    [
        b"", b"not json", b"[]", b"null", b"\xff\xfe",
        {"tool_name": "Read", "tool_input": {"command": 'echo "$X:t"'}},
        {"tool_name": "Bash"}, {"tool_name": "Bash", "tool_input": {}}, {"tool_name": "Bash", "tool_input": {"command": 5}},
        {"tool_name": "Bash", "tool_input": "echo"},
    ],
)
def test_fails_open_on_other_tools_and_bad_input(stdin):
    assert run(stdin) == ""
