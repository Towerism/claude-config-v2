# GitHub commands

Everything goes through `gh` with the user's login. `<N>` is the issue number. Text bodies are files: `$tmp/issue.md`, `$tmp/body.md`, `$tmp/comment.md`.

`<pr>` is the PR number, which differs from the issue number `<N>`. Make a temp directory per run:

```bash
base=${CLAUDE_JOB_DIR:+$CLAUDE_JOB_DIR/tmp}; tmp=$(mktemp -d "${base:-${TMPDIR:-/tmp}}/issue-XXXXXX")
```

| Step | Command |
|---|---|
| Auth check | `gh auth status` (failure: ask for `! gh auth login`) |
| Read | `gh issue view <N> --json number,title,body,state,labels,assignees,url` |
| Search | `gh issue list --state open --search "<words>" --limit 10 --json number,title,state,labels`, then `--state all` |
| Create or file | `gh issue create --title "$(cat "$tmp/title.txt")" --body-file "$tmp/issue.md"` (the title is a file too; its text is never typed into the command) |
| Claim | `gh issue edit <N> --add-assignee @me --add-label "in progress"` |
| Create labels | `gh label create "<name>" --color <hex> 2>/dev/null \|\| true` (fails harmlessly when it exists) |
| Replace body | `gh issue edit <N> --body-file "$tmp/new-body.md"` |
| Draft marker | `gh issue edit <N> --add-label draft --remove-label approved` |
| Approve | `gh issue comment <N> --body-file "$tmp/approval.md"`, then `gh issue edit <N> --add-label approved --remove-label draft` |
| Who added a label | `gh api "repos/{owner}/{repo}/issues/<N>/events" --paginate --jq '[.[] \| select(.event=="labeled") \| {label: .label.name, actor: .actor.login}]'`; take the most recent event for the label and compare its actor with `gh api user -q .login` |
| Default branch | `gh repo view --json defaultBranchRef -q .defaultBranchRef.name` |
| Open PR | `gh pr create --base <default> --title "$(cat "$tmp/pr-title.txt")" --body-file "$tmp/pr.md"` (add `--label hotfix` for hotfixes) |
| Check the link | `gh pr view --json closingIssuesReferences --jq '[.closingIssuesReferences[].number]'` must hold `<N>`; if not, `gh pr edit <pr> --body-file "$tmp/pr.md"` re-parses the keywords |
| Allowed merge methods | `gh repo view --json mergeCommitAllowed,rebaseMergeAllowed,squashMergeAllowed` |
| Merge | `gh pr merge <pr> --merge` (`--rebase` if merge commits are disabled; never `--squash`). No `--delete-branch`: the branch is still checked out in its worktree |
| After merge | `gh issue view <N> --json state,stateReason` expects `CLOSED` / `COMPLETED`; `gh issue edit <N> --remove-label "in progress"`; after removing the worktree and local branch, `git push origin --delete <branch>` |

Labels to create: `in progress` (FBCA04), `draft` (D4C5F9), `approved` (0E8A16), `hotfix` (B60205), and `approval: manual`, `approval: adversarial`, `approval: no-review` (5319E7).

The PR body closing line is `Closes #<N>` alone on its line, one keyword per issue (`Closes owner/repo#<N>` across repos).

If the token has the `project` scope, also set the issue's Project Status to In Progress; otherwise say you skipped it.

The repo's merge-confirm hook asks the user before any `gh pr merge`, so a merge always shows a prompt.
