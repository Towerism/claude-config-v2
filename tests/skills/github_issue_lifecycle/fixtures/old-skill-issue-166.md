Upgrade `@acme/selfhost-kit` from 0.4.2 to [1.0.0](https://github.com/Acme/selfhost-kit/releases/tag/v1.0.0) (tag commit `4692fe46c64d522f611301cb4341fc2efa3bad48`), following the kit's *Upgrading from 0.4.x* guide (`docs/adopting.md`).


<!-- spec:start -->
# Spec: Upgrade @acme/selfhost-kit to 1.0.0

**Author:** Claude (for @Acme) · **Date:** 2026-10-15 · **Status:** Approved · **Reviewers:** adversarial-reviewer (one pass), @Acme

## Context

Attendance takes its platform code (setup code, limiter, logger and redaction, secrets, launcher, Nitro plugins, Docker assets, reusable image/release workflows, release config) from `@acme/selfhost-kit`, pinned at **0.4.2** in three places: `package.json` (exact version) and the two reusable-workflow `uses:` lines in `.github/workflows/ci.yml` (full SHA `4c453910…` + `# v0.4.2`). `test/unit/kit-pins.test.ts` fails CI when the three disagree (ADR-0014).

Kit [1.0.0](https://github.com/Acme/selfhost-kit/releases/tag/v1.0.0) (tag commit `4692fe46c64d522f611301cb4341fc2efa3bad48`) freezes the API. Its *Upgrading from 0.4.x* guide (`docs/adopting.md`) lists five breaking changes. For attendance they come to:

1. **`createLogger` requires `redactor`, `runLauncher` requires `logger`.** Already true here: every logger is built by `createAppLogger` (`server/logging/app-logger.ts`), and `server/bootstrap/launcher.ts` passes `logger: createAppLogger({ scope: 'startup' })`. No code change, but comments in `app-logger.ts`, `launcher.ts`, `eslint.config.mjs`, `test/unit/module-boundaries.test.ts`, architecture §10 and ADR-0014 say the kit "builds its own logger / hides only its base keys when none is passed". That is no longer true: the kit now throws. The ESLint rules stay, because `createRedactor()` with no `extraKeys` still hides only the base keys.
2. **Peer dependencies.** `vitest`, `semantic-release`, `@semantic-release/exec` and `conventional-changelog-conventionalcommits` are no longer kit peers, so `pnpm audit --prod` stops walking `.>@acme/selfhost-kit>vitest>tinypool`. The two `ignoreGhsas` entries added for that path (`GHSA-5gmw-xhrv-c9v3`, `GHSA-85c8-ppgw-ccpr`, both tinypool) and the CLAUDE.md paragraph about the kit's dev-tool peers can go. `h3` stays a peer, and Nuxt brings it.
3. **`positiveIntegerVars` capped at 2^53 − 1**, with the message `NAME must be a whole number from 1 to 9007199254740991 (got "…").` `NUXT_AUTH_RATE_LIMIT_LOGIN_MAX=9007199254740993` used to pass the launcher and fail later, in the limiter. `test/server/request-limits.test.ts` pins that later failure, so it must now expect the launcher's refusal.
4. **`level`/`format` typed as `LogLevel`/`LogFormat`.** `createAppLogger` forwards `CreateLoggerOptions`, so `pnpm typecheck` shows whether any caller passes a raw string.
5. **Nitro type names removed** (`NitroAppLike`, `DefaultErrorResponse`, `DefaultErrorHandler`). `git grep` finds no use.

The kit's reusable workflows keep their inputs and outputs. Their only change is that `app-image.yml` and `app-release.yml` now tag with `--prefer-index=false`, and the release job checks that each of `X.Y.Z` / `X.Y` / `latest` names exactly the tested digest before it pushes the git tag (selfhost-kit#30).

## Functional Requirements

- FR-1: `package.json` MUST pin `@acme/selfhost-kit` at exactly `1.0.0`, and `pnpm-lock.yaml` MUST resolve it to 1.0.0.
- FR-2: Both reusable-workflow `uses:` lines in `ci.yml` MUST point at `4692fe46c64d522f611301cb4341fc2efa3bad48 # v1.0.0`. Nothing else in `ci.yml` changes.
- FR-3: `pnpm.auditConfig.ignoreGhsas` MUST drop `GHSA-5gmw-xhrv-c9v3` and `GHSA-85c8-ppgw-ccpr`, and `pnpm audit --prod --audit-level high` MUST still pass. The other six (Nuxt build/dev-only) MUST stay unless the audit shows they're no longer reached; any that go are listed in the PR.
- FR-4: Startup MUST refuse a tuning variable in `POSITIVE_INTEGER_VARS` whose value is a whole number above 9007199254740991, naming the variable, before the database opens: in unit (`prepareRuntimeEnv` with `RUNTIME_ENV`) and in the built server through the launcher.
- FR-5: Values from 1 to 9007199254740991 MUST still be accepted, and a blank value MUST still mean "unset".
- FR-6: A `NITRO_*` override that the launcher doesn't check (`NITRO_AUTH_RATE_LIMIT_LOGIN_MAX=0`, …) MUST still fail startup through the limiter's own message, as today.
- FR-7: Every logger MUST still redact attendance's extra keys (birthdates, TDF body, vault key env names). The existing redaction-contract and module-boundary tests MUST pass unchanged in what they assert.
- FR-8: Comments and docs that describe the kit's pre-1.0 fallback logger (list in Context §1), the CLAUDE.md kit-peer paragraph, and ADR-0014's pinned-version mentions that describe the *current* pin MUST be updated to match 1.0.0. Historical sentences ("A7 pinned v0.4.2") stay.
- FR-9: The commit that moves the pins MUST be a Conventional Commit `fix(deps): …`, so it releases a patch (the Renovate rule for kit bumps uses the same type).

## Non-Functional Requirements

- NFR-1: (correctness of release) the CI run for the PR MUST be green on every required check (`check`, `e2e`, `image` incl. the three smoke scripts, kit-pins).
- NFR-2: (security) no new advisory at `high` or above in `pnpm audit --prod`. Nothing new reaches `.output/server/node_modules` beyond the kit's own files (check with `ls .output/server/node_modules/@acme/selfhost-kit/dist` before and after).
- NFR-3: (install) the Unraid install stays the same: no new template fields or env vars.

## Acceptance Criteria

### AC-1: (FR-1, FR-2, FR-9) Given the repo after the change, when `test/unit/kit-pins.test.ts` runs against the real `package.json` and `ci.yml`, then it passes with version `1.0.0` and SHA `4692fe46…`. (This test goes red when `package.json` alone is bumped.)
### AC-2: (FR-4) Given `prepareRuntimeEnv` and `RUNTIME_ENV`, when any `POSITIVE_INTEGER_VARS` entry is `9007199254740992` or `9007199254740993`, then it throws `InvalidConfigError` naming that variable.
### AC-3: (FR-5) Given `prepareRuntimeEnv`, when `NUXT_AUTH_RATE_LIMIT_LOGIN_MAX=9007199254740991`, then the prepared env holds `9007199254740991`. The existing "accepts positive integers" and "blank is unset" tests still pass.
### AC-4: (FR-4) Given the built server, when it starts with `NUXT_AUTH_RATE_LIMIT_LOGIN_MAX=9007199254740993`, then it exits non-zero and its output matches `NUXT_AUTH_RATE_LIMIT_LOGIN_MAX must be a whole number from 1 to 9007199254740991`. (The row moves from `request-limits.test.ts`'s "path the launcher does not check" block to `security.test.ts`'s launcher-refusal table.)
### AC-5: (FR-6) Given the built server, when it starts with each remaining `NITRO_*` row of `request-limits.test.ts`, then it still exits 1 with the limiter's `Invalid rate limit (…)` message before the database opens.
### AC-6: (FR-3, NFR-2) Given the updated `ignoreGhsas`, when `pnpm audit --prod --audit-level high` runs, then it exits 0.
### AC-7: (FR-7) Given the kit 1.0.0, when `pnpm test:unit` runs, then `server/logging/app-logger.test.ts` (redaction contract) and `test/unit/module-boundaries.test.ts` pass.
### AC-8: (FR-8) Review check: `git grep -nE "when none is passed|isn't given one|its default logger|dev-tool peers|selfhost-kit#24|# v0\.4\.2"` prints nothing outside historical ADR sentences.
### AC-9: (NFR-1) Given the PR, when CI runs, then every job is green, including the `image` job's three smoke scripts.

## Edge Cases

- EC-1: `9007199254740992` (2^53 exactly) is refused, not just 2^53 + 1 (AC-2).
- EC-2: `9007199254740991` (the cap) is accepted (AC-3).
- EC-3: A value with surrounding spaces, `' 5 '`, is accepted and passed on trimmed as `5` (new 1.0 behaviour; unit test in `app-env.test.ts`).
- EC-4: `pnpm install` from the lockfile in CI (`--frozen-lockfile`) fails if the lockfile wasn't regenerated: the lockfile is regenerated and committed with the bump.
- EC-5: The kit's npm 1.0.0 tarball and the `v1.0.0` git tag disagree: kit-pins only checks that the version strings and SHAs agree. Review check: the SHA is the tag's commit (`gh api repos/Acme/selfhost-kit/git/ref/tags/v1.0.0` → `4692fe46…`).
- EC-6: Renovate opens its own selfhost-kit 1.0.0 PR in the meantime: it's closed as a duplicate (or Renovate closes it itself) once this merges.
- EC-7: The release run after merge is the first real release through the kit's release path (#146). Its tags are now a single image manifest, not a one-entry list (`--prefer-index=false`), so #146's step 3 should expect `Descriptor.digest = D`. A comment on #146 says so; its own verification is not this issue's work.

## API Contracts

N/A — no HTTP route, request or response changes. The only contract touched is the kit's public API, which the app consumes unchanged (`createLogger({ …, redactor })`, `runLauncher({ prepare, server, logger })`, `prepareRuntimeEnv(env, RUNTIME_ENV)`):

```ts
// Unchanged in the app; 1.0.0 makes redactor and logger required:
interface CreateLoggerOptions { scope: string; level?: LogLevel; format?: LogFormat; redactor: Redactor }
interface LauncherOptions { prepare: (env: NodeJS.ProcessEnv) => PreparedEnv; server: string; logger: Logger }
// Startup error for a refused positiveIntegerVars value:
// InvalidConfigError: `${NAME} must be a whole number from 1 to 9007199254740991 (got "${value}").`
```

## Data Models

N/A — no schema, migration or persisted data changes. The config "model" that changes:

| Field | Type | Constraint |
|-------|------|------------|
| `package.json` `dependencies["@acme/selfhost-kit"]` | string | exactly `1.0.0` |
| `ci.yml` kit `uses:` ref | 40-hex SHA + `# vX.Y.Z` | `4692fe46c64d522f611301cb4341fc2efa3bad48 # v1.0.0`, same on both lines |
| `pnpm.auditConfig.ignoreGhsas` | string[] | minus the two tinypool GHSAs |

## Test plan

Written after reading senior-qa's `testing_strategies.md`, `qa_best_practices.md` and `test_automation_patterns.md`, and with the ci-cd-pipeline-builder notes for the `ci.yml` part.

- **Pyramid placement:** the cap logic belongs to the kit (tested there), so the app tests only its own wiring. Unit: `app-env.test.ts` gains 2^53 / 2^53+1 rows in the existing `it.each` (AC-2), plus the boundary and trimming cases (AC-3, EC-2, EC-3). Server (built app over HTTP/process): one row moves from `request-limits.test.ts` into `security.test.ts`'s launcher-refusal table (AC-4), because only the built server proves the launcher wiring. No E2E: no browser decision changes. Pin agreement stays at the unit layer (`kit-pins.test.ts`, which already reads the real files).
- **Coverage by risk, not numbers:** the riskiest behaviours are (1) a half-moved pin releasing a mismatched image, already guarded by kit-pins and green CI; (2) a logger losing attendance's redaction keys, guarded by the unchanged redaction contract; (3) startup accepting a limit the limiter later rejects. No new numeric targets.
- **Flake hazards:** the server tests spawn the built server and wait for exit. `runToExit` already waits for the process's exit code, not a timer, and asserts on captured output. The rows added here don't depend on time. No wall-clock assertions.
- **Isolation/fixtures:** unit rows reuse `tempSecretsDir`/`existingInstallSecrets` from `@acme/selfhost-kit/testing` and `base()`. Each server row gets a fresh process and data dir via `runToExit`.
- **Behaviour over mocks:** no mocks. Real `prepareRuntimeEnv`, real built launcher.
- **Rewritten/deleted tests:** the `9007199254740993` row and its "2^53 + 1 … the launcher lets it through" comment in `request-limits.test.ts` are deleted (now wrong) and re-added in `security.test.ts` with the launcher's message. Comments in `module-boundaries.test.ts` about the fallback logger are reworded. No assertion there changes.
- **Review checks, not tests:** AC-8 (stale-wording grep), EC-5 (SHA is the tag's commit), EC-6, EC-7 (#146 comment), NFR-2's `.output` listing, NFR-3.
- **Pipeline (`ci.yml`) plan, per ci-cd-pipeline-builder** (`pipeline-design-notes.md`, `deployment-gates.md`, `github-actions-templates.md`; `stack_detector.py` → node + docker, pnpm, `lint`/`test`/`build` + docker build): the only edit is the two SHA pins and their comments. Stages, commands, cache keys (pnpm + lockfile), secrets (only `GITHUB_TOKEN`), permissions and gate order (`check` → `e2e` + `image` → `release` on `main` only) are unchanged. No matrix (amd64 only, ADR-0006). Pitfalls: wrong-stack copy N/A; deploy before stable tests: release still `needs: [check, e2e, image]`; cache keys unchanged; matrix N/A; protected-branch release unchanged (main only); secrets not embedded. Rollback: revert the merge commit (both pins move back together). For a bad release, re-pin the previous `X.Y.Z` on Unraid (docs/deploy/unraid.md). Validation before merge: YAML parses (`node -e` with `yaml`), kit-pins test, and the PR's own CI run exercises the new `app-image.yml` (the release job's change only runs on `main` → verified after merge under #146). `act` isn't used: the reusable workflows need GHCR.

## Out of Scope

- OS-1: Adopting any new 1.0 API (e.g. `JsonErrorHandler`, `api/` reports). Not needed for the upgrade; separate issue if wanted.
- OS-2: Removing the six Nuxt-tooling `ignoreGhsas`. They wait for Nuxt's fix (CLAUDE.md), unless the audit shows them gone (FR-3).
- OS-3: Relaxing the ESLint `createAppLogger` rules. They still guard against a base-keys-only redactor.
- OS-4: Doing #146's post-release verification. It stays its own issue; only a comment is added (EC-7).
<!-- spec:end -->

