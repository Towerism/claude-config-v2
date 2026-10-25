---
documentLanguage: en
---

# Glossary

One entry per term: definition, boundaries, one resolved ambiguity. Write here the moment a term is settled. Vocabulary here is law for specs, tickets and code naming. Ship-specific terms only: a concept any sea chart carries does not get an entry.

## Guardrails
- Definition: the rules in `config/CLAUDE.global.md` that add conditions and checks on top of OMC's workflow (ADR-0001, ADR-0004).
- Boundary: adds routing and checks; is not a replacement for any OMC stage or skill.
- Avoid: "pipeline" (V1's own pipeline was dropped; OMC owns the workflow).
- Resolved ambiguity: ADR-0004 adds routing rules on top of OMC, a stated departure from "add only gaps" in ADR-0001.

## Host profile
- Definition: `hosts/<name>.json`, naming the skills, hooks, plugins, marketplaces and `defaultTracker` one machine gets (ADR-0002).
- Boundary: is the only per-machine file in the repo; machine-only values (Jira project and site) live outside it, in `~/.config/claude-config/local.json`.
- Avoid: "environment", "config set".
- Resolved ambiguity: profiles differ only in `name` and `defaultTracker`; a test fails otherwise.

## Pathway
- Definition: the stated condition under which a guardrail routes work to an OMC agent (ADR-0004).
- Boundary: every one of the 19 pinned OMC agents has a pathway; an agent appearing only in a roster is not one.
- Avoid: "mention", "roster entry".
- Resolved ambiguity: "tracer" the agent is not "tracer bullet" in TDD.
