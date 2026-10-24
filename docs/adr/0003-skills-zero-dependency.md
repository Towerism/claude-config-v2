# ADR-0003: Skills are markdown; plumbing may have dependencies

**Status:** Accepted 2026-10-24.

## Context

V1 skills carried Python scripts, test suites and eval data. Each was something to install, version and keep working on every machine.

## Decision

A skill directory holds `.md` files only and tells Claude to use tools already on the machine (`git`, `gh`, `tea`, `jira`, standard Linux commands). Scripts that are plumbing (`tools/cfg.py`, the hooks, tests) may depend on anything that keeps the repo small. Today they need only Python 3.11+, and the tests need `pytest`.

## Consequences

`tests/test_repo.py` fails a skill with a non-markdown file, an install command, or a `scripts/` reference. V1's deterministic checks (commit-message lint, spec-marker replacement) became instructions in the skill text; if they prove unreliable, add them as plumbing under `tools/`, not inside the skill.
