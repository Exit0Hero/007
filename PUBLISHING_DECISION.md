# Publishing Decision (007)

- Decision: Push to a new public GitHub repo (deliberate).
- Repo name: 007 (user-facing)
- Import/package: agent007
- CLI: 007
- Remotes before: none
- Git repo initialized locally; committed changes (rename + fix A).
- Secret scan: checked for API keys in tracked files; .env remains gitignored (not committed). Keys were shared in chat earlier and should be rotated.
- GitHub auth: `gh` auth failed (invalid token). Manual push required or auth refresh.
- Attempted: `gh repo create 007 --public --source=. --remote=origin --push` (failed due to auth). Also attempted adding remote and pushing directly (auth failed).
