# Contributing to Atlas

## Development approach

Work through approved user stories and one sprint at a time. Read `AGENTS.md` and the relevant documents in `docs/` before making changes.

## Local setup

The exact setup commands should be kept in `README.md` and verified against the repository's current packaging.

A typical virtual-environment workflow on Linux is:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
```

Install project dependencies only after reviewing the dependency list and obtaining approval where needed.

## Change workflow

1. Inspect `git status`.
2. Read the relevant story and acceptance criteria.
3. Propose a concise plan.
4. Implement the smallest change that satisfies the story.
5. Run targeted tests and required checks.
6. Review the diff.
7. Update documentation and status.
8. Report results and stop at the sprint boundary.

## Git safety

- Do not discard user changes.
- Do not run destructive Git commands without approval.
- Do not commit or push without approval.
- Never commit `.env`, API keys, virtual environments, caches, or sensitive reports.
- Before any commit, inspect `git status` and the staged diff.

## Code style

- Prefer clear names and focused functions.
- Add type hints to public interfaces.
- Validate external inputs.
- Use explicit exceptions for expected failure categories.
- Avoid hidden global state.
- Keep provider-specific details out of core report logic where practical.
- Add tests for bug fixes.

## Dependency policy

Add a dependency only when it is needed for an approved story. Check maintenance, compatibility, license, and API documentation where relevant. Do not add an agent framework or database for convenience alone.
