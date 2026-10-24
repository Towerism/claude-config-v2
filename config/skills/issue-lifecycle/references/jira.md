# Jira commands

Tickets are read and written through the `jira` CLI ([jira-cli](https://github.com/ankitpokhrel/jira-cli)). Code lives on GitHub or Gitea, so PRs go through that tracker's reference (the PR rows work as written there, except "Check the link", which can't see a Jira key: use "Link PR" below). V1 drove Jira through a script; V2 uses the CLI directly, and these commands are unverified against a live Jira until the first use on the work machine. Report any that fail rather than guess.

## Settings

Project settings live on the machine, in the `jira` object of `~/.config/claude-config/local.json` (or `$XDG_CONFIG_HOME/claude-config/local.json`). Nothing in claude-config writes that file. If a value is missing, ask the user for it and show the JSON to add; never guess a value and never edit the file.

```json
{
  "jira": {
    "project": "PAY",
    "site": "https://example.atlassian.net",
    "states": { "inProgress": "In Progress", "review": "In Review", "done": "Done" },
    "stateOrder": ["To Do", "In Progress", "In Review", "Done"],
    "issueTypes": ["Task", "Bug", "Story"]
  }
}
```

`project` is the key (`PAY`), `site` the `https://` origin, `states` the three states to move to, `stateOrder` every state in workflow order. Move a ticket only forward along `stateOrder`; never move one whose state isn't listed.

## Commands

`<KEY>` is a key like `PAY-142`, or a bare number joined to `project`. Put text in files and pass `--template <file>` or `--body-file` style options the CLI supports; check `jira issue <cmd> --help` for the exact flag on the installed version.

| Step | Command |
|---|---|
| Auth check | `jira me` (failure: the token is missing; tell the user to export `JIRA_API_TOKEN` for non-interactive shells, for example in `~/.zshenv`, and stop) |
| Read | `jira issue view <KEY> --raw` |
| Search | `jira issue list -q "project = <project> AND text ~ \"<words>\"" --plain` |
| Create or file | `jira issue create -p <project> -t <type> -s "<summary>" --template <file> --no-input` |
| Claim | `jira issue assign <KEY> $(jira me)`, then `jira issue move <KEY> "<states.inProgress>"` |
| Add to sprint | `jira sprint add <sprint-id> <KEY>` when the user asks for it |
| Draft / approved markers | labels `spec-draft` and `spec-approved`; `jira issue edit <KEY> --label <name> --no-input` adds one, and `--label -<name>` removes it |
| Approval mode | exactly one of the labels `approval-manual`, `approval-adversarial`, `approval-no-review` |
| Comment | `jira issue comment add <KEY> --template <file> --no-input` |
| Replace spec | edit the description between the `<!-- spec:start -->` and `<!-- spec:end -->` markers: read it with `view --raw`, rewrite with `jira issue edit <KEY> --body-file`/`--template` as the installed CLI supports |
| Link PR | add a comment holding the PR URL, then `jira issue move <KEY> "<states.review>"` when the PR is ready |
| After merge | `jira issue move <KEY> "<states.done>"` |

Jira labels can't hold spaces, which is why the markers are `spec-draft`, `spec-approved` and `approval-*` rather than the GitHub names.

## Who added a label

Jira keeps this in the issue's changelog: `jira issue view <KEY> --raw` includes `changelog` when the CLI is asked to expand it, or use `GET <site>/rest/api/3/issue/<KEY>?expand=changelog`. Take the most recent history item that added the label and compare its author with `jira me`. If you cannot read the author, treat the label as not the user's.

## Pull requests

Put the key alone on a line in the PR body (`Refs PAY-142`); Jira links the PR when its GitHub or Gitea integration is installed, and "Link PR" above records it either way. A PR never closes a Jira ticket on its own: move it with "After merge".

## Branches and commits

The reference is the Jira key: branch `feature/PAY-142-short-slug`, commit subject ends `(PAY-142)`, and the PR body names the key. Everything else follows the main skill.
