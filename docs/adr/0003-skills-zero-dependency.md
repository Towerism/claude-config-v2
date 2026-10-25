# ADR-0003: Skills have no third-party dependencies and nothing to install

**Status:** Accepted 2026-10-24. Amended 2026-10-25 (#2): development tooling may use make, a venv and ruff. Amended 2026-10-24 at the user's direction: the lifecycle skills carry deterministic stdlib-only scripts; "zero dependency" now means no third-party packages and no install step, only `python3`.

## Context

V1 skills carried Python scripts, test suites and eval data. The first V2 draft dropped all of it and turned the lifecycle skills into markdown. The user then asked for the scripts back: "the lifecycle skills should use python scripts to make the skills as deterministic as possible." V1's Jira skill did the text checks, spec-marker edits and every Jira call through one script, and read the project's key, site and workflow states from `~/.config/claude-config/local.json`, so the same skill fits any Jira project without edits.

## Decision

A skill directory holds markdown, plus Python under `scripts/` that imports only the standard library, plus JSON, markdown or text assets and examples. Nothing in a skill needs `pip`, `npm` or any other install: a machine with `python3` and the tracker's own CLI (`gh`, `tea`, `jira`) runs every skill. SKILL.md tells Claude to run a script as `python3 -I <skill dir>/scripts/<name>.py`, so the files need no exec bit.

Each skill is self-contained, because a host may deploy any subset: it never reads a file from a sibling skill. The Gitea skill ships its own copy of the GitHub skill's script; a test keeps the two copies identical.

Scripts that are plumbing (`tools/cfg.py`, the hooks, tests) may depend on anything that keeps the repo small. Today they need only Python 3.11+, and the tests need `pytest`. Development tooling (`make`, a `.venv` from `requirements-dev.txt`, `ruff`) is allowed for working on the repo only; skills and deployed code stay standard-library only.

## Consequences

`tests/test_repo.py` fails a skill with a file type outside that list, an import outside the standard library, an install command, a path into another skill, or a SKILL.md that names a bundled file that isn't there. The scripts' own tests live in `tests/skills/` and run against a fake `gh`, a fake `jira` and a local REST server, never a live tracker.
