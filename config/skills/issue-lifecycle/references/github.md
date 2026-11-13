# GitHub commands

Run in the repo; `gh` targets its `origin`. Checked against gh 2.102.1.

| Event | Command |
|---|---|
| Read | `gh issue view N --json number,title,body,state,assignees,url` |
| Search | `gh issue list --state open --search "<words>" --limit 10 --json number,title,assignees`, then `--state all` |
| Create | `gh issue create --title "<title>" --body-file "$tmp/body.md" --assignee @me` |
| Assign | `gh issue edit N --add-assignee @me` |
| Description | `gh issue edit N --body-file "$tmp/body.md"` |
| Comment | `gh issue comment N --body-file "$tmp/comment.md"` |
| After merge | `gh issue view N --json state`; if `OPEN`, `gh issue close N --reason completed` |

`Closes #N` closes the issue only when the PR merges into the default branch; the after-merge check catches the other cases.
