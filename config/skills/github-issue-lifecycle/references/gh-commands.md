# gh commands used by this skill

Every GitHub read and write goes through `gh` with the user's login. Bodies always go through files (`--body-file`), never through command-line strings, so issue text is never interpolated into a shell command.

| Operation | Command | Errors to handle |
|---|---|---|
| Auth check | `gh auth status` | not logged in → stop, report that `! gh auth login` is needed, no writes |
| Read issue | `gh issue view N --json number,title,body,state,labels,assignees,url` | not found → say so, then search |
| Search | `gh issue list --state open --search "<words>" --limit 10 --json number,title,state,labels` (then `--state all`) | no clear title match → create a new issue listing the near misses |
| Create / file | `gh issue create --title "<imperative title>" --body-file <file> [--label hotfix]` | issues disabled on the repo → tell the user |
| Labels | `gh label create "<name>" --color <hex> --description "<text>" 2>/dev/null \|\| true` | already exists → harmless |
| Claim | `gh issue edit N --add-assignee @me` | 403 → no write access; tell the user |
| Who am I | `gh api user -q .login` | |
| Label provenance | `gh api "repos/{owner}/{repo}/issues/N/events" --paginate --jq '[.[] \| select(.event=="labeled") \| {label: .label.name, actor: .actor.login}]'` | use the most recent `labeled` event per label |
| Read body for editing | `gh issue view N --json body > issue.json`, then write `.body` to a file with Python (no trailing newline added) | |
| Publish spec | `gh issue edit N --body-file <new-body>` | 403 → tell the user |
| Status labels | `gh issue edit N --add-label draft --remove-label approved` on a new spec; `gh issue edit N --add-label approved --add-label "in progress" --remove-label draft` on approval, after the quote comment | |
| Comment | `gh issue comment N --body-file <file>` | 403 |
| Default branch | `gh repo view --json defaultBranchRef --jq .defaultBranchRef.name` | |
| Open PRs for the issue | `gh pr list --search "N in:title,body" --state open --json number,headRefName` | |
| Create PR | `gh pr create --base <default> --title "<type(scope): subject (#N)>" --body-file <file> [--label hotfix]` | can't target default → warn the issue won't auto-close |
| Check linkage | `gh pr view --json closingIssuesReferences --jq '[.closingIssuesReferences[].number]'` | N missing → `gh pr edit --body-file <file>`, check again |
| Merge | `gh pr merge <pr> --merge --delete-branch` (or `--rebase`) | prompt declined → report waiting; squash-only repo → report and skip the merge |
| After merge | `gh issue view N --json state,stateReason` | not CLOSED/COMPLETED → report and stop |
| Project status | `gh project item-edit …` (only with the `project` scope) | no scope → skip and say so |
