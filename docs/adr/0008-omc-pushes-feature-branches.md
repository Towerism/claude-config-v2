# ADR-0008: OMC pushes the feature branch in any mode

**Status:** Accepted 2026-10-30, issue #48. Amends ADR-0004 ("Layering with OMC") and ADR-0006 (decision 2).

## Context

Two things stopped OMC from pushing while `autopilot` or `ralph` ran:

- OMC's `git-guardrails.mjs` PreToolUse hook blocks `git push`, `git reset --hard`, `git clean -f`, `git branch -D`, `git checkout .` and `git restore .` whenever ralph, autopilot, team or ultragoal is active. Its only setting is `OMC_GIT_GUARDRAILS`; `0` turns every check off, in every mode, and wins over everything else.
- The `autopilot` and `ralph` skills say "Do not push or open a PR based on completion alone" unless "the user or mode invocation explicitly authorizes publishing".

ADR-0004 recorded that the host profiles do not set `OMC_GIT_GUARDRAILS`. The owner asked for the opposite: "OMC is allowed to push within autopilot and ralph".

## Decision

1. **`config/settings.fragment.json` sets `env.OMC_GIT_GUARDRAILS` to `"0"`.** `cfg.py` copies each fragment `env` key into the deployed `settings.json`, overwriting that key and leaving other keys alone, and records the keys in `state.json` as `envKeys`. Rollback removes only those keys and drops `env` when it is left empty. Both host profiles get it through the shared fragment.
2. **The global block gains a ninth line**: OMC may push the feature branch it works on, in any mode, without asking; this is the explicit publishing authorization the `autopilot` and `ralph` skills wait for. Force pushes use `--force-with-lease` only. "No merge until the user says so" is unchanged. This amends ADR-0006's eight-line block.

## Alternatives rejected

- **Leave the variable unset and rely on the line alone.** The hook would still block every push in an unattended run, so the line could not be acted on.
- **A finer setting that allows only `git push`.** OMC 5.7.14 has none; adding one would mean patching OMC.
- **Limit the grant to `autopilot` and `ralph`.** The owner removed that limit when the spec was revised on #48.

## Consequences

- `OMC_GIT_GUARDRAILS=0` turns off OMC's `git-guardrails` hook entirely, in every mode. Pushes are allowed in autopilot, ralph, team and ultragoal, and `git reset --hard`, `git clean -f`, `git branch -D`, `git checkout .` and `git restore .` are no longer blocked in any unattended run.
- The feature-branch and `--force-with-lease` limits are text only; no hook enforces them. Branch protection on `main` remains the control against pushes to the default branch.
- Opening a draft PR is not part of this grant; the request named pushing only.
- Recheck on each OMC upgrade that `OMC_GIT_GUARDRAILS=0` still disables the hook and that the skills' publishing sentence is unchanged.
