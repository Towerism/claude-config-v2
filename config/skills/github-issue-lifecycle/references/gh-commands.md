# gh commands used by this skill

Every GitHub read and write goes through `gh` with the user's login. Bodies always go through files (`--body-file`), never through command-line strings, so issue text is never interpolated into a shell command.

| Operation | Command | Errors to handle |
|---|---|---|
| Auth check | `gh auth status` | not logged in → stop, ask for `! gh auth login`, no writes |
| Read issue | `gh issue view N --json number,title,body,state,labels,assignees,url` | not found → say so, then search and ask |
| Search | `gh issue list --state open --search "<words>" --limit 10 --json number,title,state,labels` (then `--state all`) | 0 results → still ask, recommend **Create a new issue** |
| Create / file | `gh issue create --title "<imperative title>" --body-file <file> [--label hotfix]` | issues disabled on the repo → tell the user |
| Labels | `gh label create "<name>" --color <hex> --description "<text>" 2>/dev/null \|\| true` | already exists → harmless |
| Claim | `gh issue edit N --add-assignee @me --add-label "in progress"` | 403 → no write access; tell the user |
| Who am I | `gh api user -q .login` | |
| Label provenance | `gh api "repos/{owner}/{repo}/issues/N/events" --paginate --jq '[.[] \| select(.event=="labeled") \| {label: .label.name, actor: .actor.login}]'` | use the most recent `labeled` event per label |
| Read body for editing | `gh issue view N --json body > issue.json`, then write `.body` to a file with Python (no trailing newline added) | |
| Publish spec | `gh issue edit N --body-file <new-body>` | 403 → tell the user |
| Status labels | `gh issue edit N --add-label draft --remove-label approved` (and the reverse on approval) | |
| Comment | `gh issue comment N --body-file <file>` | 403 |
| Path declaration check | `gh api --paginate --slurp "repos/{owner}/{repo}/issues/N/comments" \| jq '[.[][] \| {url: .html_url, body: .body}]'` to a file, then `declaration-check` (step 2a; at step 5 and, with `--stamp`, at step 7) | exit 1 lists problems; `gh pr create` is asked about until the stamp exists |
| Default branch | `gh repo view --json defaultBranchRef --jq .defaultBranchRef.name` | |
| Open PRs for the issue | `gh pr list --search "N in:title,body" --state open --json number,headRefName` | |
| Create PR | `gh pr create --base <default> --title "<type(scope): subject (#N)>" --body-file <file> [--label hotfix]` | can't target default → warn the issue won't auto-close |
| Check linkage | `gh pr view --json closingIssuesReferences --jq '[.closingIssuesReferences[].number]'` | N missing → `gh pr edit --body-file <file>`, check again |
| Merge | `gh pr merge <pr> --merge --delete-branch` (or `--rebase`) | prompt declined → report waiting; squash-only repo → stop and ask |
| After merge | `gh issue view N --json state,stateReason` | not CLOSED/COMPLETED → report and ask |
| Project status | `gh project item-edit …` (only with the `project` scope) | no scope → skip and say so |
