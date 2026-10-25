# Commands the skill runs, and the errors to expect

This reference lists every `jira`, `gh` and REST call behind each `ticket_lifecycle.py` subcommand, so you can tell what a failed step tried to do. You never run the `jira` writes yourself; the script does, with argument lists and no shell.

The `jira` flags below are the ones `ticket_lifecycle.py` passes to `ankitpokhrel/jira-cli`. On 2026-10-20, each row was compared with `jira <subcommand> --help` from jira 1.7.0 on the work machine, and every flag and argument exists. `issue edit`'s flag list doesn't describe removing a label with `--label -<name>`, but the command's own examples show it. If a later CLI version drops a flag, the script, its fake CLI and this page change together.

## Jira CLI

| Subcommand | Command | Errors to expect |
|---|---|---|
| `auth` | `jira me` | Exit non-zero or no output: the CLI isn't logged in (`jira init`). |
| `view`, and every step that reads first | `jira issue view KEY --raw` | "Issue does not exist": the key is wrong. Output that isn't JSON: an old CLI version. |
| `search` | `jira issue list -p <project> -q "statusCategory != Done" --plain --no-headers --columns key,summary,status,assignee --paginate 0:10 -- <text>` | "No result found" isn't an error: there are no candidates. The CLI puts `<text>` into a JQL text clause itself, so the script escapes `\` and `"` first. |
| `create` | `jira issue create -p <project> -t <type> -s <summary> --template <file> --no-input [-l hotfix]` | An unknown issue type for the project. |
| `create --link` | `jira issue link KEY OTHER <relatedLinkType>`, then a comment on OTHER | An unknown link type. |
| `claim`, `create` | `jira issue assign KEY <login from jira me>` | "Unable to find associated user". |
| `claim` (when `addToActiveSprint`) | `jira sprint list --state active --plain --no-headers --columns ID,NAME`; `jira sprint list <id> --plain --no-headers --columns key`; `jira sprint add <id> KEY` | No board in the CLI's config. No active sprint gives `none`, several give `ambiguous`. |
| `claim`, `review`, `done` | `jira issue move KEY <state>` | "Invalid transition": the workflow doesn't allow that move from the current state. |
| `set-mode`, `approve`, `sync-spec` | `jira issue edit KEY --label <add> --label -<remove> --no-input` | A label with a space, which Jira refuses. |
| `sync-spec` | `jira issue edit KEY -b <description> --no-input` | "too long" or "exceeds": the script attaches the spec instead. |
| `comment`, `approve`, `sync-spec`, `create --link` | `jira issue comment add KEY --template <file> --no-input` | More than 32,767 characters: refused before the call. |
| `link-pr` | `jira issue comment add KEY <PR URL> --no-input` | |

## REST, under `<site>/rest/api/3/`

The script makes exactly these four calls, only to the configured `site` over HTTPS, with the jira CLI's login and `JIRA_API_TOKEN` as basic auth. A jira CLI `server` on another host makes it refuse with exit 5 before any call.

| Subcommand | Call | Errors to expect |
|---|---|---|
| `label-actor`, `claim` (when someone has the ticket) | `GET myself` | 401: a wrong or expired token. |
| `label-actor` | `GET issue/KEY/changelog?startAt=N&maxResults=100`, every page | A failed page means the label isn't trusted. |
| `sync-spec` | `POST issue/KEY/attachments` with `X-Atlassian-Token: no-check` | 403: the token lacks attachment permission. The description stays as it was. |
| `sync-spec` | `DELETE attachment/{id}` | The `cleanup` step fails and names the attachment left behind. |

## GitHub CLI

| Subcommand or step | Command | Errors to expect |
|---|---|---|
| `auth` | `gh auth status` | Not logged in: ask the user to run `! gh auth login`. |
| `pr-body`, `review`, `merge-check` | `gh pr view N --json …` | No such PR. |
| `pr-body` | `gh pr edit N --body-file <file>` | |
| `review` | `gh pr ready N` | |
| You, steps 5 and 7 | `declaration-check` over files you write from `view --key` (step 2a); `--stamp` at step 7 | Exit 1 lists problems. |
| You, step 7 | `gh pr create --draft --base <default> --title … --body-file …` | |
| You, step 8 | `gh pr merge N --merge --delete-branch` (or `--rebase`) | The confirmation prompt is declined: the merge waits on the user. |
| You | `gh repo view --json defaultBranchRef` | |
