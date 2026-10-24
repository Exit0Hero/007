# OpenCode Prompt — Sprint 1: Foundation and Configuration

Run this only after the user has reviewed and approved Sprint 1.

Read `AGENTS.md`, `docs/PRD.md`, `docs/ARCHITECTURE.md`, `docs/ROADMAP.md`, `docs/SPRINTS.md`, `docs/STATUS.md`, `docs/DECISIONS.md`, `docs/TESTING.md`, `docs/SECURITY.md`, and `docs/DEFINITION_OF_DONE.md`.

## Scope

Stories:
- US-101: Submit a research question
- US-102: Configure research limits
- US-501: Configure the application
- US-503: Test without paid API calls
- US-504: Maintainable code
- US-502: Minimal CLI skeleton

## Tasks

1. Inspect repository and Git state; preserve all existing work.
2. Propose a plan with file-level changes and verification commands.
3. Confirm installed Python version and compatibility with the declared minimum.
4. Create the minimal package/configuration/test setup required by these stories.
5. Add `.gitignore` and `.env.example` with placeholder values only.
6. Implement validated configuration and safe missing-credential behavior.
7. Add a minimal CLI entry point with clear errors, including research-question validation (US-101); do not implement search, fetching, agent orchestration, or report generation yet.
8. Add deterministic tests for valid and invalid configuration, request validation, and CLI behavior.
9. Configure Ruff and pytest in a way that matches the actual project layout.
10. Run the relevant tests and checks; inspect their actual output.
11. Review the diff for secret leakage and scope creep.
12. Update the backlog, sprint plan, and `docs/STATUS.md`.

## Constraints

- Do not call paid APIs.
- Do not invent a model ID or assert provider availability.
- Do not add a frontend, database, vector store, or agent framework.
- Do not commit or push.
- Ask before installing dependencies if installation has not been approved.
- Stop at Sprint 1 and wait for approval.

## Exit report

List stories, files changed, commands actually run, test results, acceptance criteria verified/unverified, known issues, and the next recommended sprint.
