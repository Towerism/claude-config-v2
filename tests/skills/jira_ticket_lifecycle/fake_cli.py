#!/usr/bin/env python3
"""A stateful stand-in for the `jira` and `gh` CLIs and Jira's REST API (development only;
the skill never runs it).

Installed on PATH under both names, it records every call as a JSON line in $FAKE_CLI_LOG
and answers from the state in $FAKE_CLI_STATE, which the run's own writes update, so a model
or a test that reads back what it wrote sees its change. A canned response in the state's
`canned` list wins over the state when its `match` words start the call, so a case can still
simulate an error.

    fake_cli.py serve --port-file F   serves the REST calls the skill makes, from the same
                                      state, on 127.0.0.1 (port 0, written to F)

All project values in a state are invented: project PAY, site example.atlassian.net.
"""

import fcntl
import json
import os
import re
import sys
import tempfile
from contextlib import contextmanager
from datetime import UTC, datetime
from urllib.parse import parse_qs, urlparse

SITE = "https://example.atlassian.net"
REPO = "https://github.com/o/r"
DONE_STATES = {"Done", "Closed"}


# ── state ────────────────────────────────────────────────────────────────────


@contextmanager
def locked_state(path):
    """Read the state under an exclusive lock and write it back atomically on exit."""
    with open(path + ".lock", "a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        with open(path, encoding="utf-8") as fh:
            state = json.load(fh)
        yield state
        fd, tmp = tempfile.mkstemp(dir=os.path.dirname(path) or ".")
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(state, fh, indent=1, sort_keys=True)
        os.replace(tmp, path)


def now():
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%S.000+0000")


def log(entry):
    path = os.environ.get("FAKE_CLI_LOG")
    if path:
        with open(path, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(entry) + "\n")


def me(state):
    return state.get("me", {"accountId": "acc-owner", "email": "owner@example.com"})


def find_user(state, name):
    for user in [me(state), *state.get("users", [])]:
        if name in (user.get("email"), user.get("accountId"), user.get("displayName")):
            return user
    return None


class Failure(Exception):
    def __init__(self, message, rc=1):
        super().__init__(message)
        self.rc = rc


def ticket(state, key):
    t = state.get("tickets", {}).get(key)
    if t is None:
        raise Failure(f"Issue does not exist: {key}")
    for field in ("labels", "comments", "attachments", "links", "changelog"):
        t.setdefault(field, [])
    return t


def change_labels(state, t, add=(), remove=()):
    before = list(t["labels"])
    labels = [x for x in before if x not in remove]
    labels += [x for x in add if x not in labels]
    if labels != before:
        t["labels"] = labels
        t["changelog"].append(
            {
                "author": {"accountId": me(state)["accountId"]},
                "created": now(),
                "items": [
                    {
                        "field": "labels",
                        "fromString": " ".join(before),
                        "toString": " ".join(labels),
                    }
                ],
            }
        )


# ── ADF ──────────────────────────────────────────────────────────────────────


def to_adf(markdown):
    """One paragraph per blank-line-separated block, which is close enough to what jira-cli's
    converter produces for the skill's checks."""
    blocks = [b.strip("\n") for b in re.split(r"\n\s*\n", markdown or "") if b.strip()]
    return {
        "type": "doc",
        "version": 1,
        "content": [
            {"type": "paragraph", "content": [{"type": "text", "text": b}]} for b in blocks
        ],
    }


def raw_issue(state, key, t):
    assignee = find_user(state, t["assignee"]) if t.get("assignee") else None
    return {
        "key": key,
        "fields": {
            "summary": t.get("summary", ""),
            "issuetype": {"name": t.get("type", "Task")},
            "status": {"name": t.get("state", "To Do")},
            "assignee": assignee
            and {
                "accountId": assignee["accountId"],
                "emailAddress": assignee.get("email"),
                "displayName": assignee.get("displayName", assignee.get("email")),
            },
            "labels": t["labels"],
            "description": to_adf(t.get("description", "")) if t.get("description") else None,
            "comment": {
                "comments": [{"id": str(i), "body": to_adf(c)} for i, c in enumerate(t["comments"])]
            },
            "attachment": [
                {"id": a["id"], "filename": a["filename"], "size": len(a.get("content", ""))}
                for a in t["attachments"]
            ],
        },
    }


# ── jira ─────────────────────────────────────────────────────────────────────


def options(argv, flags_with_values):
    """Split argv into positionals and a dict of option -> list of values; `--` ends options."""
    pos, opts, i = [], {}, 0
    while i < len(argv):
        a = argv[i]
        if a == "--":
            pos.extend(argv[i + 1 :])
            break
        if a in flags_with_values:
            opts.setdefault(a, []).append(argv[i + 1] if i + 1 < len(argv) else "")
            i += 2
        elif a.startswith("-"):
            opts.setdefault(a, []).append(True)
            i += 1
        else:
            pos.append(a)
            i += 1
    return pos, opts


def body_from(opts):
    if "--template" in opts:
        with open(opts["--template"][-1], encoding="utf-8") as fh:
            return fh.read()
    for flag in ("-b", "--body"):
        if flag in opts:
            return opts[flag][-1]
    return None


def jira(state, argv):
    words = argv[:2]
    if argv[:1] == ["me"]:
        return me(state)["email"] + "\n"
    if words == ["issue", "view"]:
        key = argv[2]
        t = ticket(state, key)
        if "--raw" in argv:
            return json.dumps(raw_issue(state, key, t))
        lines = [
            f"{key}  {t.get('summary', '')}",
            f"Status: {t.get('state', 'To Do')}",
            "",
            t.get("description", ""),
        ]
        lines += [f"Comment: {c}" for c in t["comments"][-5:]]
        return "\n".join(lines) + "\n"
    if words == ["issue", "list"]:
        pos, opts = options(argv[2:], {"-p", "-q", "--columns", "--paginate", "-l"})
        text = " ".join(pos).lower()
        words_wanted = [w for w in re.findall(r"[a-z0-9]+", text) if len(w) >= 3]
        rows = []
        for key, t in sorted(state.get("tickets", {}).items()):
            if t.get("state") in DONE_STATES:
                continue
            hay = (t.get("summary", "") + " " + t.get("description", "")).lower()
            if words_wanted and any(w in hay for w in words_wanted):
                cells = [
                    key,
                    t.get("summary", ""),
                    t.get("state", "To Do"),
                    t.get("assignee") or "",
                ]
                rows.append("\t".join(cells))
        if not rows:
            raise Failure("No result found for given query in project")
        return "\n".join(rows) + "\n"
    if words == ["issue", "create"]:
        _, opts = options(argv[2:], {"-p", "-t", "-s", "-b", "--template", "-l", "-a"})
        project = opts.get("-p", ["PAY"])[-1]
        numbers = [
            int(k.split("-")[1]) for k in state.get("tickets", {}) if k.startswith(project + "-")
        ]
        key = f"{project}-{max(numbers, default=100) + 1}"
        state.setdefault("tickets", {})[key] = {
            "summary": opts.get("-s", [""])[-1],
            "type": opts.get("-t", ["Task"])[-1],
            "state": "To Do",
            "description": body_from(opts) or "",
            "labels": [],
            "assignee": None,
        }
        t = ticket(state, key)
        change_labels(state, t, add=opts.get("-l", []))
        return f"✓ Issue created\n{SITE}/browse/{key}\n"
    if words == ["issue", "assign"]:
        key, user = argv[2], argv[3]
        t = ticket(state, key)
        found = find_user(state, user)
        if user == "x":
            t["assignee"] = None
        elif not found:
            raise Failure(f"Unable to find associated user for {user}")
        else:
            t["assignee"] = found["email"]
        return f'✓ User "{user}" assigned to issue "{key}"\n'
    if words == ["issue", "move"]:
        key, target = argv[2], argv[3]
        t = ticket(state, key)
        allowed = state.get("states", ["To Do", "In Progress", "In Review", "Done"])
        if target not in allowed:
            raise Failure(f'Invalid transition state "{target}"')
        t["state"] = target
        return f'✓ Issue transitioned to "{target}"\n'
    if words == ["issue", "edit"]:
        key = argv[2]
        _, opts = options(argv[3:], {"-b", "--body", "--label", "-l", "-s"})
        t = ticket(state, key)
        labels = opts.get("--label", []) + opts.get("-l", [])
        change_labels(
            state,
            t,
            add=[x for x in labels if not x.startswith("-")],
            remove=[x[1:] for x in labels if x.startswith("-")],
        )
        body = body_from(opts)
        if body is not None:
            if len(body) > state.get("descriptionLimit", 32767):
                raise Failure("The entered text is too long. It exceeds the allowed limit.")
            t["description"] = body
        if "-s" in opts:
            t["summary"] = opts["-s"][-1]
        return f"✓ Issue updated\n{SITE}/browse/{key}\n"
    if argv[:3] == ["issue", "comment", "add"]:
        pos, opts = options(argv[3:], {"--template", "-b"})
        key = pos[0]
        t = ticket(state, key)
        body = body_from(opts)
        t["comments"].append(body if body is not None else " ".join(pos[1:]))
        return f'✓ Comment added to issue "{key}"\n'
    if words == ["issue", "link"]:
        key, other, kind = argv[2], argv[3], argv[4]
        t = ticket(state, key)
        ticket(state, other)
        t["links"].append({"key": other, "type": kind})
        return f'✓ Issues linked as "{kind}"\n'
    if words == ["sprint", "list"]:
        pos, opts = options(argv[2:], {"--state", "--columns", "--paginate"})
        sprints = state.get("sprints", [])
        if pos:
            members = next((s.get("issues", []) for s in sprints if str(s["id"]) == pos[0]), None)
            if members is None:
                raise Failure(f"sprint {pos[0]} not found")
            if not members:
                raise Failure("No result found")
            return "\n".join(members) + "\n"
        active = [s for s in sprints if s.get("state", "active") == "active"]
        if not active:
            raise Failure("No result found")
        return "\n".join(f"{s['id']}\t{s['name']}" for s in active) + "\n"
    if words == ["sprint", "add"]:
        sprint_id, keys = argv[2], argv[3:]
        for s in state.get("sprints", []):
            if str(s["id"]) == sprint_id:
                for k in keys:
                    ticket(state, k)
                    if k not in s.setdefault("issues", []):
                        s["issues"].append(k)
                return f"✓ Issues added to the sprint {sprint_id}\n"
        raise Failure(f"sprint {sprint_id} not found")
    raise Failure(f"fake jira: unsupported command {' '.join(argv[:3])}", rc=2)


# ── gh ───────────────────────────────────────────────────────────────────────

PR_FIELDS = (
    "number",
    "url",
    "state",
    "isDraft",
    "reviewDecision",
    "body",
    "title",
    "mergedAt",
    "headRefName",
)
GH_VALUE_FLAGS = {
    "--json",
    "--jq",
    "-q",
    "--title",
    "-t",
    "--body",
    "-b",
    "--body-file",
    "-F",
    "--base",
    "-B",
    "--head",
    "-H",
    "--label",
    "-l",
}


def select_jq(value, expr):
    """Dotted paths only (`.a.b`, `.a[0]`); anything else is an error the caller can retry."""
    if not re.fullmatch(r"(\.[A-Za-z_][A-Za-z0-9_]*(\[\d+\])?)+|\.", expr.strip()):
        raise Failure(f"fake gh: unsupported --jq filter {expr!r}; retry without --jq")
    for part in re.findall(r"[A-Za-z_][A-Za-z0-9_]*|\[\d+\]", expr):
        value = value[int(part[1:-1])] if part.startswith("[") else (value or {}).get(part)
    return value if isinstance(value, str) else json.dumps(value)


def pr_by_number(state, number):
    pr = state.get("prs", {}).get(str(number))
    if pr is None:
        raise Failure(f"no pull requests found for {number}")
    return pr


def gh(state, argv):
    pos, opts = options(argv, GH_VALUE_FLAGS)
    jq = (opts.get("--jq") or opts.get("-q") or [None])[-1]

    def out(value):
        return (select_jq(value, jq) if jq else json.dumps(value)) + "\n"

    if pos[:2] == ["auth", "status"]:
        if state.get("ghAuth", True) is False:
            raise Failure("You are not logged into any GitHub hosts. To log in, run: gh auth login")
        return "github.com\n  ✓ Logged in to github.com account owner\n"
    if pos[:2] == ["repo", "view"]:
        return out({"defaultBranchRef": {"name": state.get("defaultBranch", "main")}, "url": REPO})
    if pos[:2] == ["pr", "create"]:
        number = max((int(n) for n in state.get("prs", {})), default=0) + 1
        body = opts.get("--body", opts.get("-b", [""]))[-1]
        body_file = (opts.get("--body-file") or opts.get("-F") or [None])[-1]
        if body_file:
            with open(body_file, encoding="utf-8") as fh:
                body = fh.read()
        url = f"{REPO}/pull/{number}"
        state.setdefault("prs", {})[str(number)] = {
            "number": number,
            "url": url,
            "state": "OPEN",
            "isDraft": "--draft" in opts or "-d" in opts,
            "reviewDecision": "",
            "body": body,
            "title": (opts.get("--title") or opts.get("-t") or [""])[-1],
            "mergedAt": None,
            "labels": opts.get("--label", []) + opts.get("-l", []),
        }
        return url + "\n"
    if pos[:2] == ["pr", "view"]:
        prs = state.get("prs", {})
        if len(pos) > 2:
            pr = pr_by_number(state, re.sub(r"\D", "", pos[2].rsplit("/", 1)[-1]))
        elif prs:
            pr = prs[max(prs, key=int)]
        else:
            raise Failure("no pull requests found for branch")
        fields = (opts.get("--json") or [",".join(PR_FIELDS)])[-1].split(",")
        return out({f: pr.get(f) for f in fields})
    if pos[:2] == ["pr", "edit"]:
        pr = pr_by_number(state, pos[2])
        body_file = (opts.get("--body-file") or opts.get("-F") or [None])[-1]
        if body_file:
            with open(body_file, encoding="utf-8") as fh:
                pr["body"] = fh.read()
        return pr["url"] + "\n"
    if pos[:2] == ["pr", "ready"]:
        pr = pr_by_number(state, pos[2])
        pr["isDraft"] = False
        return f'✓ Pull request #{pr["number"]} is marked as "ready for review"\n'
    if pos[:2] == ["pr", "merge"]:
        pr = pr_by_number(state, pos[2])
        pr["state"], pr["mergedAt"] = "MERGED", now()
        return f"✓ Merged pull request #{pr['number']}\n"
    raise Failure(f"fake gh: unsupported command {' '.join(pos[:3])}", rc=2)


# ── canned responses and the entry point ─────────────────────────────────────


def take_canned(entries, words):
    """The first entry whose `match` starts the call. `skip: n` lets n matching calls through
    to the state first; `times: n` stops the entry after n uses."""
    for entry in entries:
        if words.startswith(entry["match"]) and entry.get("times", 1) != 0:
            if entry.get("skip", 0) > 0:
                entry["skip"] -= 1
                continue
            if "times" in entry:
                entry["times"] -= 1
            return entry
    return None


def cli(prog, argv):
    log({"prog": prog, "argv": argv})
    with locked_state(os.environ["FAKE_CLI_STATE"]) as state:
        reply = take_canned(state.get("canned", []), " ".join([prog, *argv]))
        if reply is not None:
            sys.stdout.write(reply.get("stdout", ""))
            sys.stderr.write(reply.get("stderr", ""))
            return reply.get("rc", 0)
        try:
            sys.stdout.write((jira if prog == "jira" else gh)(state, argv))
            return 0
        except Failure as exc:
            sys.stderr.write(f"Error: {exc}\n")
            return exc.rc


# ── REST ─────────────────────────────────────────────────────────────────────


def rest(state, method, url, query, headers, body):
    """(status, JSON value or None) for one REST call, from the state."""
    reply = take_canned(state.get("restCanned", []), f"{method} {url.path}")
    if reply is not None:
        return reply.get("status", 500), reply.get("json")
    if not headers.get("Authorization", "").startswith("Basic "):
        return 401, {"errorMessages": ["not authenticated"]}
    if method == "GET" and url.path == "/rest/api/3/myself":
        m = me(state)
        return 200, {"accountId": m["accountId"], "emailAddress": m["email"]}
    hit = re.fullmatch(r"/rest/api/3/issue/([A-Z0-9_]+-\d+)/(changelog|attachments)", url.path)
    if hit:
        t = state.get("tickets", {}).get(hit.group(1))
        if t is None:
            return 404, {"errorMessages": ["Issue does not exist"]}
        if hit.group(2) == "changelog" and method == "GET":
            values = t.get("changelog", [])
            start = int(query.get("startAt", ["0"])[0])
            size = int(state.get("changelogPageSize", query.get("maxResults", ["100"])[0]))
            return 200, {
                "startAt": start,
                "maxResults": size,
                "total": len(values),
                "isLast": start + size >= len(values),
                "values": values[start : start + size],
            }
        if hit.group(2) == "attachments" and method == "POST":
            if headers.get("X-Atlassian-Token") != "no-check":
                return 403, {"errorMessages": ["XSRF check failed"]}
            name = re.search(rb'filename="([^"]+)"', body)
            content = body.split(b"\r\n\r\n", 1)[-1].rsplit(b"\r\n--", 1)[0]
            new_id = str(10000 + state.get("nextAttachment", 0))
            state["nextAttachment"] = state.get("nextAttachment", 0) + 1
            entry = {
                "id": new_id,
                "filename": name.group(1).decode() if name else "file",
                "content": content.decode("utf-8", "replace"),
            }
            t.setdefault("attachments", []).append(entry)
            return 200, [{"id": new_id, "filename": entry["filename"]}]
    gone = re.fullmatch(r"/rest/api/3/attachment/(\d+)", url.path)
    if gone and method == "DELETE":
        for t in state.get("tickets", {}).values():
            kept = [a for a in t.get("attachments", []) if a["id"] != gone.group(1)]
            if len(kept) != len(t.get("attachments", [])):
                t["attachments"] = kept
                return 204, None
        return 404, {"errorMessages": ["attachment not found"]}
    return 404, {"errorMessages": [f"fake REST: no route {method} {url.path}"]}


def make_handler(state_path):
    from http.server import BaseHTTPRequestHandler  # only the server needs it; CLI calls stay fast

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def handle_one(self, body=b""):
            log(
                {
                    "prog": "rest",
                    "method": self.command,
                    "path": self.path,
                    "auth": self.headers.get("Authorization", ""),
                    "atlassianToken": self.headers.get("X-Atlassian-Token"),
                    "body": body.decode("utf-8", "replace")[:200000],
                }
            )
            url = urlparse(self.path)
            with locked_state(state_path) as state:
                status, value = rest(
                    state, self.command, url, parse_qs(url.query), self.headers, body
                )
            data = b"" if value is None else json.dumps(value).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self):
            self.handle_one()

        def do_DELETE(self):
            self.handle_one()

        def do_POST(self):
            self.handle_one(self.rfile.read(int(self.headers.get("Content-Length", "0"))))

    return Handler


def serve(port_file):
    from http.server import ThreadingHTTPServer

    server = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(os.environ["FAKE_CLI_STATE"]))
    tmp = port_file + ".tmp"
    with open(tmp, "w") as fh:
        fh.write(str(server.server_address[1]))
    os.replace(tmp, port_file)
    server.serve_forever()


def main(argv):
    prog = os.path.basename(argv[0])
    if prog in ("jira", "gh"):
        return cli(prog, argv[1:])
    if argv[1:2] == ["serve"] and "--port-file" in argv:
        serve(argv[argv.index("--port-file") + 1])
        return 0
    sys.stderr.write("usage: install as jira or gh, or run `fake_cli.py serve --port-file F`\n")
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv))
