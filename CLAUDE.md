# claude-config v2: working on this repo

The workflow here is OMC's: `/oh-my-claudecode:deep-interview` or `:ralplan` for anything non-trivial, then `:execute` with `:tdd`, `:review`, `:verify`. The design is in `README.md` and `docs/adr/`; a departure needs a new or updated ADR.

## Commands

- Tests: `python3 -I -m pytest`. Quote the result before saying done.
- Dry-run a deploy without touching `~/.claude`: `python3 -I tools/cfg.py plan --host personal --target "$(mktemp -d)"`.

## Rules

- Skills are markdown only (DP2). A script belongs in `tools/` or `config/hooks/`, never in a skill. `tests/test_repo.py` enforces it.
- Hooks stay standard library, exit 0 on any input, and print only checked values.
- The repo is public: no machine paths, accounts, tokens or client names. `~/.config/claude-config/deny-terms` stays outside the repo; never read it into output.
- Both host profiles stay identical apart from `name` and `defaultTracker`.
- Conventional Commits; never commit to the default branch.
