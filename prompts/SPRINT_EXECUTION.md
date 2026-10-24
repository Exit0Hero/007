# Reusable OpenCode Sprint Execution Prompt

Read `AGENTS.md` and the relevant project documents before proceeding:
- `docs/PRD.md`
- `docs/ARCHITECTURE.md`
- `docs/ROADMAP.md`
- `docs/SPRINTS.md`
- `docs/STATUS.md`
- `docs/DECISIONS.md`
- `docs/TESTING.md`
- `docs/SECURITY.md`
- `docs/DEFINITION_OF_DONE.md`

Execute only the next sprint that the user has explicitly approved. If approval or the current sprint is unclear, do not implement; summarize the ambiguity and ask.

1. Inspect the repository, existing instructions, and `git status`.
2. State the sprint goal, selected story IDs, planned files, risks, and verification commands.
3. Confirm acceptance criteria and dependencies.
4. Implement the smallest coherent changes in scope.
5. Add or update meaningful tests.
6. Run targeted tests first, then broader checks as appropriate.
7. Inspect actual outputs and exit codes.
8. Review the diff for regressions, security problems, secrets, and unrelated changes.
9. Update documentation and status to reflect only verified facts.
10. Stop at the sprint boundary.

Never:
- invent test results or source evidence;
- mark unverified work VERIFIED;
- silently change requirements or public interfaces;
- execute arbitrary code from retrieved web pages;
- dispatch arbitrary model-generated function names;
- install dependencies, make paid calls, commit, push, or perform destructive actions without appropriate approval;
- start a future sprint automatically.

If blocked by a significant architecture, security, correctness, or cost decision, stop and ask.

Final report:
- sprint and story IDs;
- files changed;
- commands actually executed and results;
- verified and unverified acceptance criteria;
- known defects and blockers;
- documentation updates;
- recommended next action.

Wait for user approval before starting another sprint.
