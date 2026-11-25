# ADR-0019: Fresh-session handoff at OMC stage boundaries

**Status:** Accepted 2026-11-25, issue #99. Amended 2026-11-25, issue #103: background jobs (decision 5).

## Context

V1's `fresh-session-handoff` skill was dropped, and nothing writes a cold-start note for an arbitrary session ([gap analysis](../gap-analysis.md)). Long OMC sessions fill the context until autocompaction summarises it, at whatever point in a task that happens. The owner wants the session to start fresh at a natural break instead, with no keystroke.

Claude Code has no hook output or tool that runs `/clear` or starts a new session. A trial on Claude Code 2.1.332, with Haiku in a tmux session, showed that a Stop hook which starts a detached `tmux send-keys '/clear' Enter` does clear the session, and that the fresh session then waits until a prompt is typed.

## Decision

1. **A `session-handoff` skill decides when and what.** It tells the model to hand off between skills, before the next stage skill is invoked: once a spec is written, once a plan is approved, once an execute run is done, when a hook reports context past the limit, and when the owner asks for a handoff and the next step is known. It also says when not to: outside an interactive tmux session or a background job, while ralph or autopilot runs, and while an ultragoal `/goal` is active. The model writes the note to `.omc/handoffs/<session id>.md` and ends its turn; the model picks the moment and the next skill.
2. **One Stop hook, `handoff_stop.py`, does the typing.** In an interactive session (`CLAUDE_CODE_ENTRYPOINT=cli`) inside a tmux pane, once a note for the session exists, it types `/clear` and then a prompt naming the note into `$TMUX_PANE`, once per note. Past min(60% of the context window, 300,000 tokens), read from OMC's HUD statusline cache, it blocks one stop per session so the model gets a chance to write a note. It never blocks a stop that is already re-entrant (`stop_hook_active`), as OMC's own Stop hook avoids it too.
3. **The prompt names the note; there is no SessionStart hook.** The fresh session needs a typed prompt anyway, so that prompt tells it to read the note and run its next skill.
4. **tmux becomes an optional runtime dependency,** and this is the repo's first Stop hook. Without tmux the hook does nothing.
5. **A background job gets a new background job.** A session started with `claude --bg` has no pane to type into. When the hook sees `CLAUDE_JOB_DIR` and no usable pane, it runs `claude --bg "<prompt>"` from the project directory instead of typing `/clear`, once per note, and the context-limit block applies there too. A pane wins when both are present. On Claude Code 2.1.332, a job's Stop hook saw `CLAUDE_JOB_DIR` and no `TMUX_PANE`, and a chain of three jobs, each started from the previous job's Stop hook with its environment inherited, ran with a job directory and session id of its own each. The old job is left idle in `claude agents`. The new job is started without the old job's command-line flags, such as its model.

## Alternatives considered

- A new `claude -p` process per stage, or a subagent per stage: both leave the user's terminal; the owner chose a clear in the same pane.
- OMC's `spawn-next` chain: it halts when a session is cleared.
- Detecting OMC stages in the hook: the routing belongs to the model, which already knows which skill comes next.
- OMC's context guard as the trigger: it takes only a percentage, so it cannot express the 300,000-token cap, and it advises `/compact`.
- A SessionStart hook injecting the note: a second hook, plus guards against injecting an old note later, when the typed prompt can name the file.
- Cancelling ralph, handing off and restarting it: ralph keeps its stories and feedback baseline per session, so the fresh run would lose the stories already passed.

## Consequences

- The handoff depends on Claude Code accepting a typed `/clear` after the delays in the hook. A Claude Code release may change that; the scripted tmux check is rerun on upgrade.
- The limit depends on OMC's HUD cache schema. A change there makes the limit go silent, and OMC's own 75% guard speaks instead.
- Sessions outside tmux that are not background jobs, nested `claude -p` runs and sessions without the HUD statusline get no handoff and no forced limit.
- The background route depends on `claude --bg` and `CLAUDE_JOB_DIR` behaving as they did on 2.1.332. If a release sets `TMUX_PANE` in jobs, the pane route would take over and type into that pane.
- No handoff happens while ralph or autopilot runs; those runs keep OMC's context guard and autocompaction.
- Keys the user types at the same moment can interleave with the typed ones. Old notes and markers stay in `.omc/handoffs/`.

## Follow-ups

- A one-run check that a cancelled autopilot resumes in a fresh session, which would let autopilot hand off too.
- Carrying ralph progress across sessions.
- A route for sessions outside tmux that are not background jobs, and a transcript fallback for context use without the HUD cache.
