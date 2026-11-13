# Gitea commands

Checked against tea 0.16.0.

- Call the API as `tea api --login <login> -i …`, with the login from `tea logins list` whose URL host matches the repo's `origin`. `<o>/<r>` is the owner and repo from `origin`.
- `tea api` exits 0 on a 404 or 403. `-i` writes the HTTP status line to stderr: read it after every call, and treat anything but 2xx as a failure.
- A request body is a JSON file passed as `-d @"$tmp/body.json"`, with the text JSON-escaped.

| Event | Call |
|---|---|
| Who am I | `GET user` → `login` |
| Read | `GET repos/<o>/<r>/issues/N`; a non-null `pull_request` means N is a PR, not an issue |
| Search | `GET "repos/<o>/<r>/issues?state=open&type=issues&limit=10&q=<words>"`, then `state=all`; join the words with `+` (`q=fix+login`), as tea sends the URL unencoded and a space gets a 400 |
| Create | `-X POST repos/<o>/<r>/issues` with `{"title": …, "body": …, "assignees": ["<login>"]}` |
| Assign | `-X PATCH repos/<o>/<r>/issues/N` with `{"assignees": ["<login>"]}` |
| Description | `-X PATCH repos/<o>/<r>/issues/N` with `{"body": …}` |
| Comment | `-X POST repos/<o>/<r>/issues/N/comments` with `{"body": …}` |
| After merge | `GET repos/<o>/<r>/issues/N`; if `state` is `open`, `-X PATCH` it with `{"state": "closed"}` |
