# Settings

The skill reads its settings from the `jira` object in `~/.config/claude-config/local.json` (or `$XDG_CONFIG_HOME/claude-config/local.json` when `XDG_CONFIG_HOME` is an absolute path). That file lives only on the machine that uses it: nothing in claude-config writes it, deploys it or commits it. When a required value is missing, `ticket_lifecycle.py settings` exits 6 and names it; ask the user for the value and show them the JSON to add.

## A complete example

Every value here is invented. Replace them with the project's own.

```json
{
  "jira": {
    "project": "PAY",
    "site": "https://example.atlassian.net",
    "states": { "inProgress": "In Progress", "review": "In Review", "done": "Done" },
    "stateOrder": ["To Do", "In Progress", "In Review", "Done"],
    "issueTypes": ["Task", "Bug", "Story"],
    "addToActiveSprint": true
  }
}
```

The top-level `defaultTracker` is ignored. The tracker comes from the repo's CLAUDE.md, a `jira.project` key in its history, its `origin`, or the host profile. The script reads only the `jira` object.

## Every key

| Key | Required | Default | Meaning |
|---|---|---|---|
| `project` | yes | | The project key, such as `PAY`: an uppercase letter, then 1 to 9 uppercase letters, digits or underscores. |
| `site` | yes | | The site's `https://` origin, with no path. Browse links use it, and it is the only host REST calls may reach; the jira CLI's `server` must match it. |
| `states.inProgress`, `states.review`, `states.done` | yes | | The workflow state to move to when claiming, when the PR is ready, and after the merge. |
| `stateOrder` | yes | | Every state in workflow order, holding the three above in that order. Moves only go forward along it, and a ticket in a state not listed is never moved. |
| `issueTypes` | no | `["Task", "Bug", "Story"]` | Types a new ticket may have. |
| `defaultIssueType` | no | the first of `issueTypes` | |
| `addToActiveSprint` | no | `false` | Add a claimed ticket to the active sprint of the board in the jira CLI's config. |
| `summaryFormat` | no | `"{title}"` | The summary of a new ticket. `{repo}` is also available, such as `"{repo}: {title}"`. |
| `relatedLinkType` | no | `"Relates"` | The link type for "create a new ticket and link these". |
| `requireApprovedPr` | no | `false` | When true, `merge-check` also needs a non-draft PR with an approving review. |
| `labels` | no | below | Label names, to override any default. Jira labels can't hold spaces. |
| `specDir` | no | `~/.local/state/claude-config/jira-specs` | Where the local working copies of specs live, one folder per repo. |

Default labels: `draft` is `spec-draft`, `approved` is `spec-approved` and `hotfix` is `hotfix`. The old `manual`, `adversarial` and `noReview` keys are ignored.

## What else the machine needs

- The jira CLI (`ankitpokhrel/jira-cli`), set up with `jira init`, which writes its server, login and board to `~/.config/.jira/.config.yml`.
- `JIRA_API_TOKEN` exported for non-interactive shells, for example in `~/.zshenv`, because the skill's commands don't run in an interactive shell.
- `gh`, logged in with `gh auth login`.
