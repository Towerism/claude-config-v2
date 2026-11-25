---
name: skillify-generalized
description: "Run skillify with the user choosing: list each candidate workflow from the session in its as-run and generalized forms, let the user pick which to promote, draft the generalized version, get an independent review, check the reviewer's untested claims, and verify the saved files. Use when the user runs skillify, asks to turn a workflow into a skill or save it as a skill, or asks which workflows from the session should become skills. Not for promoting an existing skill into a config repo, or drafting one straight into it (use promote-skill-to-config for both) or for editing a skill that already exists."
---

# Skillify, generalized and user-picked

Use with `/oh-my-claudecode:skillify`, which supplies the quality gate and the frontmatter format. This skill adds the steps around it. Why: the user judges which workflows are worth saving, and a workflow that isn't worth saving as run may be worth it once generalized.

## Steps

1. **List the candidates.** Go through the session for every repeatable multi-step workflow: the main task, sub-procedures inside it (such as a check you designed or a log you traced), and procedures the user corrected you into. Done when each candidate has a one-line name.
2. **Describe each candidate twice.**
   - *As run:* what this session did, in its specifics.
   - *Generalized:* the widest version whose steps still hold, with the session's specifics turned into inputs.

   Add the quality-gate verdict. Drop a candidate an existing skill (in the available-skills list or the learned-skill store) or a rule already covers, and list each drop with its reason. Done when each remaining candidate has both forms and a gate verdict, and adds something no existing skill or rule does.
3. **Let the user pick.** Show the candidates, then ask with AskUserQuestion, multi-select, recommended ones first, each option describing its generalized form. With more than 4 candidates, offer the top 3 plus "another one (name it)". Done when the user has picked. Take the generalized form unless their notes say otherwise.
4. **Draft each pick.** Load `/oh-my-claudecode:agent-doc-discipline` first. A skill specific to one repo goes in that repo's tracked `.omc/skills/`. Any other skill goes in `${XDG_DATA_HOME:-~/.local/share}/claude-memory/skills/<name>.md`, written with the Write or Edit tool. This overrides skillify's `omc-learned` path: the global-memory hook symlinks `~/.omc/skills` to that store, so the learned-skill loader reads it and it syncs across machines. When picks overlap, one skill holds the shared procedure and the others call it by name. Done when each file starts with frontmatter (name, description, triggers) and every step ends on a done condition.
5. **Get an independent review.** Launch `plugin-dev:skill-reviewer` on all drafts in one call. Ask it whether a fresh session can act on each draft cold, whether the triggers fire on real requests but not on nearby ones, for done conditions, for contradictions between the drafts, and for lines that only restate default behaviour. Done when its report is in. Why: an author approving their own draft misses what a cold reader trips on.
6. **Check before applying.** A cheap check settles each reviewer claim it marks untested, such as a path format or a tool's behaviour. Apply it if confirmed. When a suggestion can't be checked cheaply, write the requirement it serves rather than the untested mechanism, and list it as not settled. Done when every finding is applied, rejected with a reason, or listed as not settled.
7. **Verify the saved files.** Confirm each file's frontmatter parses with name and triggers present. For a global skill, confirm `readlink ~/.omc/skills` points at the store and the file is listed there. Done when both checks pass for every file.
8. **Report** each skill's name, path and one-line purpose, what the review changed, and what is not settled. If the user wants a skill invocable by name on every machine, offer `promote-skill-to-config` as the next step. Done when the report lists every pick and every unsettled finding.

## When nothing new happened

If skillify runs again and the session has no repeatable workflow since the last run, say so. Offer the leftover candidates from the last run, each with its generalized form. Ask with AskUserQuestion, including an option to name a different workflow. Done when the user has chosen.
