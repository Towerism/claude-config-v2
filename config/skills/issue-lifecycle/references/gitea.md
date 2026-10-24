# Gitea commands

Everything goes through `tea api` with a login on every call, and git for the rest. Never run `gh` in a Gitea repo. V1 checked these calls against one Gitea server (version 28.2.0, `tea` 0.16.0); on any other server they are unverified, so report a call that fails in a way not listed here.

Setup, once per issue:

- `git remote get-url origin` gives the host and `<o>/<r>`. If the host is `github.com`, this is a GitHub repo: use the GitHub reference.
- Pick the login in `tea login list` whose server matches the host; ask if none or several do. Every call is `tea api --login <login> -i -X <METHOD> <endpoint> [-d @<file>]`. `tea api` adds `/api/v1`, so endpoints have no leading slash.
- Values must be safe: `<o>` and `<r>` match `[A-Za-z0-9._-]+`, `<N>` is digits only, `<login>` is a name `tea login list` printed. Stop and ask if one doesn't fit.
- **`tea api` exits 0 even on a 404 or 403.** `-i` prints the HTTP status line to stderr; treat any status outside 2xx as a failed step, and also read the answer's fields (an issue has `number` and `state`; an error has `message`).
- Request bodies are JSON files written with the Write tool, never command-line strings.

| Step | Call |
|---|---|
| Auth check | `GET user`; stop if it fails and ask for `! tea login add`. Then `GET repos/<o>/<r>` and stop if `html_url`'s host differs from the remote's |
| Read | `GET repos/<o>/<r>/issues/<N>` (`number`, `state`, `body`, `labels[].id`, `assignees`; a non-null `pull_request` means it is a PR) |
| Search | `GET "repos/<o>/<r>/issues?state=open&type=issues&limit=10&q=<words>"`, then `state=all`; the server may ignore `q`, so filter titles yourself |
| Create or file | `POST repos/<o>/<r>/issues -d @issue.json` (`{"title": …, "body": …}`) |
| List labels | `GET repos/<o>/<r>/labels?limit=50&page=<p>` until a short page comes back |
| Create label | `POST repos/<o>/<r>/labels -d @label.json`, only for labels missing from the list: Gitea accepts a duplicate name |
| Claim | `PATCH repos/<o>/<r>/issues/<N> -d @assign.json` (`{"assignees": ["<login-name>"]}`), then add the `in progress` label |
| Add labels | `POST repos/<o>/<r>/issues/<N>/labels -d @labels.json` (`{"labels": [<ids>]}`) |
| Remove label | `DELETE repos/<o>/<r>/issues/<N>/labels/<id>` |
| Who added a label | `GET repos/<o>/<r>/issues/<N>/timeline`; an entry with `type` `label`, `label.name`, `user.login` and `body` `1` was an add. Follow pages |
| Replace body | `PATCH repos/<o>/<r>/issues/<N> -d @patch.json` (`{"body": …}`) |
| Comment | `POST repos/<o>/<r>/issues/<N>/comments -d @comment.json` |
| Repo facts | `GET repos/<o>/<r>`: `default_branch`, `allow_merge_commits`, `allow_rebase`, `allow_squash_merge` |
| Open PR | `POST repos/<o>/<r>/pulls -d @pr.json` (`title`, `head`, `base`, `body`) |
| Merge | `POST repos/<o>/<r>/pulls/<N>/merge -d @merge.json` (`{"Do": "merge", "delete_branch_after_merge": true}`, or `"rebase"`; never `"squash"`) |
| After merge | `GET repos/<o>/<r>/issues/<N>` has `state` `closed` |

Labels to create (list first): `in progress`, `draft`, `approved`, `hotfix`, `approval: manual`, `approval: adversarial`, `approval: no-review`.

Gitea doesn't report which issues a PR will close, so don't claim a link you can't read. Put `Closes #<N>` alone on a line in the PR body and check the issue's state after the merge.

The merge-confirm hook also catches `tea api …/merge`, so a merge shows a prompt. If the prompt is declined or unanswerable, the PR is waiting on the user.
