# Jira commands

## Settings

Read the `jira` object in `$XDG_CONFIG_HOME/claude-config/local.json` (`~/.config/claude-config/local.json` when `XDG_CONFIG_HOME` is unset). The file lives only on the machine; nothing in claude-config writes or commits it. Other keys in it are ignored.

```json
{
  "jira": {
    "project": "PAY",
    "states": { "inProgress": "In Progress", "review": "In Review", "done": "Done" },
    "defaultIssueType": "Task",
    "addToActiveSprint": true
  }
}
```

`project` and the three `states` are required: when one is missing, skip the Jira update and show the user this example. `defaultIssueType` defaults to `Task`; `addToActiveSprint` to `false`. The values are invented; each project sets its own.

## Commands

`ankitpokhrel/jira-cli`, checked against 1.7.0. It needs `jira init` done and `JIRA_API_TOKEN` exported.

| Event | Command |
|---|---|
| Who am I | `jira me` |
| Read | `jira issue view KEY --raw` (`fields.status.name`, `fields.assignee`) |
| Search | `jira issue list -p <project> -q "statusCategory != Done" --plain --no-headers --columns key,summary,status,assignee --paginate 0:10 -- "<words>"`, then without `-q`; exit 1 with "No result found" means no match |
| Create | `jira issue create -p <project> -t <defaultIssueType> -s "<title>" --template "$tmp/body.md" -a "$(jira me)" --no-input`; the new key is in the output |
| Assign | `jira issue assign KEY "$(jira me)"` |
| Move | `jira issue move KEY "<state>"`; skip it when the ticket is already there |
| Sprint | `jira sprint list --state active --plain --no-headers --columns ID,NAME`; with exactly one row, `jira sprint add <ID> KEY`; with none or several, tell the user and skip |
| Description | `jira issue edit KEY --no-input < "$tmp/body.md"` |
| Comment | `jira issue comment add KEY --template "$tmp/comment.md" --no-input` |

"Invalid transition" on a move means the project's workflow has no direct move from the current state: tell the user which state the ticket is in.
