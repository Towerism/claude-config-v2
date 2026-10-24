Found while working #98 (not part of it).

The server tests' date helpers add whole 24-hour blocks to the real clock and then read the date in America/Chicago:

```ts
const day = (days: number) => new Intl.DateTimeFormat('en-CA', { timeZone: TZ }).format(new Date(Date.now() + days * DAY));
```

Across a DST change (e.g. 2026-11-01), a run in the hour after the league's midnight lands one day early, so expectations built from `day(n)` disagree with the server's calendar dates. Seen on 2026-10-15 shortly after midnight Chicago time:

- `test/server/tournaments.test.ts` › plans a schedule on read… (weekly dates expected 11-07, 11-14… got 11-08, 11-15…)
- `test/server/tournaments.test.ts` › plans a one-off, refusing the same event twice…
- `test/server/tournament-edit.test.ts` › a tournament made in play-tools › shows the form from a fresh read… (`opensOn` 11-01 vs 10-31)

It passes at any other hour, so CI rarely sees it.

**Fix:** compute today's league date once, then add calendar days (UTC date arithmetic), as `leagueDay` in `test/e2e/fixtures.ts` now does (#98). Check the other `test/server/*.test.ts` files with a `day()` helper too.



<!-- spec:start -->
# Spec: Server tests' date helper counts calendar days, not 24-hour blocks

**Author:** Claude (for @Acme) · **Date:** 2026-10-15 · **Status:** Approved · **Reviewers:** adversarial-reviewer (one pass)

## Context

Six server test files (`tournaments`, `tournament-create`, `tournament-edit`, `tournament-cancel`, `tdf-download`, `required-events`) each build league dates as `format(Date.now() + n × 24 h)` in `America/Chicago`. A day is not always 24 h in the league's zone, so any date projected across a DST change comes out one day early when the run falls in the hour after Chicago midnight (see the comment below: 00:35 CDT on 2026-10-15, `day(24)` → 2026-11-07 instead of 11-08). The server computes calendar dates, so the expectations disagree and three tests fail in that hour. CI rarely runs then, which makes it a latent flake.

#98's E2E fixtures already fixed their copy (`leagueDay`: today's league date, then UTC calendar-day arithmetic). This brings the server tests in line with one shared helper instead of six copies.

## Functional Requirements

- FR-1: A single test helper `leagueDay(days, timeZone, now = new Date())` MUST return the `YYYY-MM-DD` date that is `days` calendar days after `now`'s date in `timeZone` (negative `days` go back).
- FR-2: It MUST give the same result for every instant within one league day, including the hour after midnight, regardless of any DST change between today and the target date.
- FR-3: Every `test/server/*.test.ts` date helper built from `Date.now() + n × DAY` (the five `day()` copies and `required-events`' `ahead()`) MUST use `leagueDay` instead, and the per-file `DAY` constant and local formatters MUST be removed where nothing else uses them.
- FR-4: The helper MUST live under `test/server/` (beside `harness.ts`), so it never ships in `.output/`.

## Non-Functional Requirements

- NFR-1: **Determinism:** the helper's unit tests MUST NOT read the real clock; `now` is injected at fixed instants.
- NFR-2: **No behaviour change:** server tests MUST keep asserting the same things; only how expected dates are derived changes. `pnpm test:unit`, `pnpm test:server`, `pnpm lint` and `pnpm typecheck` MUST pass.

## Acceptance Criteria

### AC-1: The hour after league midnight before fall-back (FR-1, FR-2)
Given `now` = 2026-10-15T05:35:00Z (00:35 CDT), when `leagueDay(24, 'America/Chicago', now)`, then `2026-11-08`.
### AC-2: Last second of a league day (FR-1, FR-2)
Given `now` = 2026-10-15T04:59:59Z (23:59:59 CDT on 10-14), when `leagueDay(0, …)` and `leagueDay(1, …)`, then `2026-10-14` and `2026-10-15`.
### AC-3: Across fall-back and spring-forward, both directions (FR-1, FR-2)
Given `now` = 2026-11-02T05:30:00Z (23:30 CST on 11-01, just after fall-back), when `leagueDay(-1, …)` (back across fall-back) and `leagueDay(140, …)` (past the 2027-03-14 spring change), then `2026-10-31` and `2027-03-21` (the 24-hour helper gives 11-01 and 03-22).
### AC-4: Back across spring-forward in the hour after midnight (FR-1, FR-2)
Given `now` = 2027-03-15T05:30:00Z (00:30 CDT on 03-15), when `leagueDay(-1, …)` (back across spring-forward), then `2027-03-14` (the 24-hour helper gives 03-13).
### AC-5: Month and year rollovers (FR-1)
Given a month/year boundary, when `leagueDay(1, …)` at 2026-12-31 23:30 CST (2027-01-01T05:30:00Z), then `2027-01-01`; and `leagueDay(-1, …)` at 2027-03-01 12:00 CST gives `2027-02-28`.
### AC-6: Server tests use the helper (FR-3, NFR-2)
Given the changed server test files, when `pnpm test:server` runs, then it passes; `grep -rn "DAY)" test/server` finds no `Date.now() + n * DAY` date helper (review check).
### AC-7: Helper stays test-only (FR-4)
Given the change, when reviewed, then the helper file is `test/server/league-day.ts` and nothing under `app/`, `server/` or `shared/` imports it (review check).

## Edge Cases

- EC-1: Run at 00:00–00:59 league time before a DST change: covered by AC-1.
- EC-2: Run in the repeated 01:00–01:59 hour on fall-back day: today's date is read with `Intl` in the zone, so it is unambiguous; AC-3 covers that day.
- EC-3: Negative offsets across a change (`day(-20)`, `day(-400)` in existing tests): covered by AC-3's `-1` and AC-4.
- EC-4: Test files that also use `Date.now()` for polling deadlines (`Date.now() + 25_000`) keep doing so; only date derivation changes.

## API Contracts

```ts
// test/server/league-day.ts
/** The date `days` calendar days after `now`'s date in `timeZone`, as YYYY-MM-DD. */
export function leagueDay(days: number, timeZone: string, now?: Date): string;
```

No HTTP API changes.

## Data Models

N/A — test-only change, no schema or persisted data.

## Test plan (senior-qa applied)

- **Pyramid placement:** the date arithmetic is pure, so its DST behaviour is pinned by **unit** tests (`test/unit/league-day.test.ts`, AC-1–AC-5) with injected fixed instants. The server tests (integration) are only consumers; they are not made to reproduce the DST hour (that would need faking the server's clock too). No E2E.
- **Risk:** a wrong expected date can mask or fake a real date bug in tournament scheduling, so the cases target the boundary instants (just before/after league midnight, both DST directions, month/year rollovers), not line coverage.
- **Flake hazards:** wall-clock reads in the helper's tests → removed by injecting `now` (NFR-1). Server tests still read the real clock for "today", as does the server; both now agree on calendar arithmetic. The residual hazard (a run straddling league midnight between the test's read and the server's) exists today and is out of scope.
- **Isolation/fixtures:** the helper is stateless; no fixtures.
- **Behaviour over mocks:** no mocks; assertions are on returned dates.
- **Rewritten tests:** the six server files' local helpers are replaced; no tests deleted, no assertions changed.
- **Review checks, not tests:** AC-6's grep and AC-7.

## Out of Scope

- OS-1: The E2E fixture's `leagueDay` (#98's branch owns it; it can import this helper once both land).
- OS-2: Faking the server's clock to reproduce the midnight hour in server tests.
- OS-3: The midnight-straddle race between test and server clock reads.
<!-- spec:end -->

