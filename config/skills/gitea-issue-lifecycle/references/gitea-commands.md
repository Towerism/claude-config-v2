# Gitea calls used by this skill

**Checked on one server; unverified on any other.** On 2026-10-22, `tea` 0.16.0 ran every call in this file against the owner's Gitea server (which reports version 28.2.0), in a throwaway repo that was deleted afterwards. Results:

- `--login`, `-X`, `-d @file` and the `/api/v1/` prefix work as written, and a body holding quotes and `$(...)` arrives intact.
- **`tea api` exits 0 even when the server answers 404 or 403.** `-i` prints the HTTP status line to stderr, so add it to every call and treat a status outside 2xx as a failed step. Also treat an error `message` or a missing field in the answer as a failure.
- **A plain issue has `"pull_request": null`.** Only a non-null value means the number is a PR. `type=issues` in a list leaves PRs out.
- **Gitea accepts a second label with the same name** (status 201, a new id), so always list the labels first and create only the missing ones.
- Label paging works with `limit` and `page`. Labels are added by id (status 200) and removed by id (status 204).
- A timeline entry for a label has `type` `label`, `label.name`, `user.login`, and `body` `1` when the label was added and an empty string when it was removed.
- `html_url` and `default_branch` are on the repo answer, with `allow_merge_commits`, `allow_rebase` and `allow_squash_merge`. A PR has `mergeable` and `state`.
- `Do: merge` and `Do: rebase` both merged with `delete_branch_after_merge` (status 200), and the head branch was gone afterwards. A merge into the default branch closed the issue named by `Closes #N` in the PR body.
- Body edits round-trip byte for byte, and the script's `extract` found the spec block afterwards.
- The server did not ignore `q` in the one search tried, but search by words on a repo with data was not exercised. Still filter titles yourself.

If a flag is rejected on another version, run `tea api --help` and report the difference.

Every call is `tea api --login <login> -i -X <METHOD> <endpoint> [-d @<file>]`; the table omits `-i` for width. `tea api` adds the server's `/api/v1` prefix, so endpoints have no leading slash. `<login>` is the entry in `tea login list` whose server host matches the remote's host. Bodies always go through files, never through command-line strings, so issue text is never interpolated into a shell command.

| Operation | Call | Check in the answer |
|---|---|---|
| Who am I | `tea api --login <login> -X GET user` | `login`; stop if it fails |
| Read issue | `tea api --login <login> -X GET repos/<o>/<r>/issues/N` | `number`, `state`, `body`, `labels[].id`, `assignees`; a non-null `pull_request` means it is a PR (a plain issue has `"pull_request": null`) |
| Search | `tea api --login <login> -X GET "repos/<o>/<r>/issues?state=open&type=issues&limit=10&q=<words>"` (then `state=all`) | the server may ignore `q`; filter titles yourself |
| Create or file | `tea api --login <login> -X POST repos/<o>/<r>/issues -d @issue.json` | `number` |
| List labels | `tea api --login <login> -X GET repos/<o>/<r>/labels` | follow pages until a short page comes back |
| Create label | `tea api --login <login> -X POST repos/<o>/<r>/labels -d @label.json` | `id`; only for labels missing from the list |
| Assign | `tea api --login <login> -X PATCH repos/<o>/<r>/issues/N -d @assign.json` | `assignees` |
| Add labels | `tea api --login <login> -X POST repos/<o>/<r>/issues/N/labels -d @labels.json` | ids in `{"labels": [..]}` |
| Remove label | `tea api --login <login> -X DELETE repos/<o>/<r>/issues/N/labels/<id>` | |
| Label provenance | `tea api --login <login> -X GET repos/<o>/<r>/issues/N/timeline` | entry with `type` `label`, `label.name`, `user.login`, `body` `1` when added; follow pages |
| Publish spec | `tea api --login <login> -X PATCH repos/<o>/<r>/issues/N -d @patch.json` | `body` |
| Comment | `tea api --login <login> -X POST repos/<o>/<r>/issues/N/comments -d @comment.json` | `id` |
| List comments (path declaration check, steps 2a, 5, 7) | `tea api --login <login> repos/<o>/<r>/issues/N/comments` (every page) | `html_url` and `body` go to the comments file |
| Repo facts | `tea api --login <login> -X GET repos/<o>/<r>` | `default_branch`, `allow_merge_commits`, `allow_rebase`, `allow_squash_merge` |
| Create PR | `tea api --login <login> -X POST repos/<o>/<r>/pulls -d @pr.json` | `number` |
| Merge | `tea api --login <login> -X POST repos/<o>/<r>/pulls/N/merge -d @merge.json` | only after the chat confirmation; never `"Do": "squash"` |
| After merge | `tea api --login <login> -X GET repos/<o>/<r>/issues/N` | `state` is `closed` |

Request bodies:

```json
{"title": "Add CSV export to the roster page", "body": "..."}
{"name": "in progress", "color": "FBCA04", "description": "Claimed"}
{"labels": [12, 15]}
{"assignees": ["login"]}
{"title": "feat(roster): add CSV export (#42)", "body": "...", "head": "feature/42-add-csv-export", "base": "main"}
{"Do": "merge", "delete_branch_after_merge": true}
```

Gitea has no counterpart of GitHub's `closingIssuesReferences`, so the link from a PR to its issue can't be read back before the merge. The `Closes #N` line in the body does the linking, `pr-body-check` checks that line, and the issue's `state` after the merge confirms it.

| Change type | Branch prefix |
|---|---|
| `feat` | `feature/` |
| `fix` | `fix/` |
| `docs` | `docs/` |
| hotfix issue | `hotfix/` |
| anything else | `chore/` |
