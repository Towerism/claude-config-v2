> Adapted from `standards/git/git-workflow-standards.md` in [alirezarezvani/claude-skills](https://github.com/alirezarezvani/claude-skills).
> MIT License, Copyright (c) 2025 Alireza Rezvani. Adapted 2026-10-15 for this user's repos.

# Git workflow

In a Gitea repo the `gh` commands on this page don't apply and you never run `gh`: steps 7 and 8 of this skill's SKILL.md replace them with `tea api` calls.

## Contents
- Adaptations from the source
- Commit messages
- Branches
- Pull requests and merging
- Releases
- Hotfix
- Rollback and fixing mistakes
- Do and don't

## Adaptations from the source

The source standard was written for the claude-skills repo itself. These parts were changed or removed:

| Source | Here | Why |
|---|---|---|
| Squash merge | Merge commit or rebase merge, never squash | semantic-release builds release notes from every commit; squashing collapses them into one title |
| Manual release tags | semantic-release creates tags | hand-made tags conflict with semantic-release |
| claude-skills scope list | scopes come from each repo's modules | the list only fits that repo |
| `feature/{domain}-{component}` names | `{type}/{N}-{slug}` with the issue number | every branch traces to its issue |
| Branch protection, git hooks | not covered | repo setup, tracked separately |
| Hard reset and forced pushes to the default branch for rollback | `git revert` only | history on the default branch is never rewritten |

## Commit messages

Conventional Commits 1.0.0:

```
<type>(<scope>)!: <subject> (#N)

[body]

[BREAKING CHANGE: what breaks and how to migrate]
```

- **type** decides the release (Semantic Versioning 2.0.0): `feat` → minor, `fix` → patch, `!` plus a `BREAKING CHANGE:` footer → major. `docs`, `style`, `refactor`, `perf`, `test`, `build`, `ci`, `chore`, `revert` don't release on their own (per the repo's semantic-release config).
- **scope** is a module of the repo (`roster`, `api`, `auth`), optional.
- **subject** is imperative and lower-case, and ends with the issue reference `(#N)` (`(owner/repo#N)` across repos).
- A breaking change needs both the `!` and the footer. A changed or removed entry in a published API report (`api/*.api.md`) is always breaking.
- One logical change per commit (atomic). Because history is kept per commit, every commit on the branch is itself a valid Conventional Commit.

Examples:

```
feat(roster): add CSV export (#42)
fix(api): return 404 for unknown tournament (#57)
feat(auth)!: require session cookie on all routes (#61)

BREAKING CHANGE: bearer tokens are no longer accepted; sign in again.
```

## Branches

`{type}/{N}-{slug}`:

| Change type | Branch prefix |
|---|---|
| `feat` | `feature/` |
| `fix` | `fix/` |
| `docs` | `docs/` |
| hotfix issue | `hotfix/` |
| anything else | `chore/` |

- `slug` is kebab-case ASCII, at most 40 characters. These names are a convention; nothing checks them.
- The worktree uses the same name.
- Branches that already exist under the older `{N}-slug` form keep their name.
- Keep the branch current with `git fetch` then `git rebase origin/<default>`; don't merge the default branch into it.

## Pull requests and merging

- Target the default branch, so `Closes #N` closes the issue on merge.
- Title: a Conventional Commit subject ending `(#N)`.
- Body: `Closes #N` alone on its line, `Spec: #N`, a map from acceptance criteria to tests, and the review note.

```bash
gh pr create --base main --title "feat(roster): add CSV export (#42)" --body-file "$tmp/pr.md"
gh pr merge 42 --merge --delete-branch     # or --rebase where merge commits are disabled
```

- Delete the branch after merging (`--delete-branch`), and the local branch and worktree too.
- Never commit directly to the default branch.

## Releases

semantic-release runs in CI on the default branch: it reads the commit types since the last release, picks the version, writes the changelog, and creates the tag. Nobody tags by hand.

## Hotfix

```bash
git fetch origin
git switch -c hotfix/57-login-500 origin/main
# fix, test, commit:  fix(auth): handle expired session on login (#57)
gh pr create --base main --label hotfix --title "fix(auth): handle expired session on login (#57)" --body-file "$tmp/pr.md"
```

A hotfix is still an issue with the `hotfix` label, and its spec still needs the user's approval. The release happens through semantic-release like any other `fix`.

## Rollback and fixing mistakes

- Undo a merged change with a new commit: `git revert <sha>` (or `git revert -m 1 <merge-sha>` for a merge commit), through a normal PR.
- Fix the last, **unpushed** commit message with `git commit --amend`.
- A **pushed** commit on a feature branch with a bad message: rewrite it on the feature branch and push with `--force-with-lease`.
- History on the default branch is never rewritten.

## Do and don't

Do:
- use Conventional Commits for every commit, with the issue number;
- keep commits atomic and messages specific;
- run the repo's tests before committing;
- pull/rebase before pushing;
- work on a branch for every change, and delete it after merging.

Don't:
- commit to the default branch;
- rewrite shared history;
- commit secrets or credentials;
- mix unrelated changes in one commit;
- write vague messages ("fix stuff", "updates").
