# /push2git

Generate a professional commit summary from the current git diff and write it to a new file in `.git/commits/`.

## Instructions

1. Run `git diff HEAD` to get all unstaged changes.
2. Run `git diff --cached` to get all staged changes.
3. Run `git status --short` to get the full list of changed/new/deleted files.
4. Determine the next commit file number by checking what files already exist in `.git/commits/` — if `commit1.md`, `commit2.md` exist, the next is `commit3.md`. If the folder doesn't exist, create it and start at `commit1.md`.
5. Write a new file at `.git/commits/commitN.md` using the format below.
6. Do NOT run `git add`, `git commit`, or `git push` — this command only writes the summary file.

## Output File Format

```
# Commit Summary — commitN

## Suggested Commit Message
<type>(<scope>): <concise one-line summary under 72 chars>

## Changed Files
| File | Change Type | Summary |
|------|-------------|---------|
| path/to/file.py | modified | One-line description of what changed and why |
| path/to/new_file.py | added | One-line description of what this file does |
| path/to/old_file.py | deleted | Why this was removed |

## Diff Stats
<output of git diff --stat HEAD>

## Notes
<any ambiguous changes, TODOs left in code, or things reviewer should know>
```

## Commit Message Type Prefixes
- `feat`: new feature
- `fix`: bug fix
- `refactor`: restructure without behavior change
- `chore`: config, deps, tooling
- `docs`: documentation only
- `test`: test additions or changes
- `perf`: performance improvement

## Rules
- The one-liner per file must be specific — not "updated file" or "made changes"
- Scope in commit message should be the primary module or feature area touched
- If changes span unrelated concerns, note that in the Notes section and suggest splitting the commit
- Never invent changes that aren't in the diff
