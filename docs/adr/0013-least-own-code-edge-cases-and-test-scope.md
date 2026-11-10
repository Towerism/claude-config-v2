# ADR-0013: Least own code wins, weigh each edge case, and test real logic only

**Status:** Accepted by the owner on 2026-11-10, issue #64. Amends ADR-0011 (decision 4).

## Context

ADR-0011 told the agent to pick the option with the least complexity to own, counting its own code plus each dependency's upkeep. The owner asked for three rules: the first replaces that principle, and the other two are new. The owner gave a reason for the first two: our own code is what we maintain, and a mature library has already handled its edge cases; gold plating costs upkeep and protects nothing.

## Decision

1. **Least own code wins.** The dependency principle changes from "least complexity to own, counting your own code plus each dependency's upkeep" to "least own code wins; few dependencies is not a goal". Browser bundle size still counts. The mechanics are unchanged: name each new dependency in the spec with what it replaces, and a dependency found mid-build goes into the spec first.
2. **Weigh each edge case.** Handle one only when it is realistic for how the code is used and the handling code is small next to the risk. Otherwise skip it and say why in the spec.
3. **Test real logic only.** Drop tests that repeat the code line by line or re-check a linter in the same pipeline. List each behaviour left untested in a `Not tested, and why` list in the spec's test plan.

The rules live in `config/CLAUDE.global.md` under `### Dependencies and tests`.

## Consequences

- The `Not tested, and why` list is text only: by the owner's choice, `spec-check` does not enforce it.
- ADR-0003 is unchanged: this repo's skill scripts stay standard-library only, as its CLAUDE.md says, whatever decision 1 says elsewhere.
