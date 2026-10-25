# claude-config v2: working on this repo

The workflow here is OMC's: `/oh-my-claudecode:deep-interview` or `:ralplan` for anything non-trivial, then `:execute` with `:tdd`, `:review`, `:verify`. The design is in `README.md` and `docs/adr/`; a departure needs a new or updated ADR.

## Shared background

- Glossary: `GLOSSARY.md`. On term conflicts it wins; record a new term when it settles.
- Decisions: `docs/adr/`.

## Commands

- Tests: `python3 -I -m pytest`. Quote the result before saying done.
- Dry-run a deploy without touching `~/.claude`: `python3 -I tools/cfg.py plan --host personal --target "$(mktemp -d)"`.

## Rules

- Skills have no third-party dependencies and nothing to install (DP2, ADR-0003): markdown, plus stdlib-only Python under `scripts/`, run as `python3 -I <skill dir>/scripts/<name>.py`. A skill never reads from a sibling skill. `tests/test_repo.py` enforces it; the scripts' tests are in `tests/skills/`.
- Hooks stay standard library, exit 0 on any input, and print only checked values.
- The repo is public: no machine paths, accounts, tokens or client names. `~/.config/claude-config/deny-terms` stays outside the repo; never read it into output.
- Both host profiles stay identical apart from `name` and `defaultTracker`.
- Conventional Commits; never commit to the default branch.
