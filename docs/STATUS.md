# Atlas — Current Status

> This is the canonical current-state summary. Update it only after inspecting the actual repository and verifying the reported work.

## Current state

- **Current sprint:** Sprint 7 — executed with user-delegated scope (US-703 only; see ADR-017)
- **Overall implementation status:** MVP **COMPLETE**, plus one approved post-MVP feature. The entire pipeline — CLI → pipeline → agent loop → allowlisted tools → source registry → citation-validating report — is implemented, tested offline, and benchmarked. **Live model and live search integrations have never been executed** (no credentials exist in this environment); live behaviour is unverified.
- **Last verified commit:** see `git log`. Work is committed on branch `master`; nothing was pushed (no remote exists and none was created).
- **Last test run:** `.venv/bin/python -m pytest` → **455 passed, 4 deselected** in 1.21s, exit code 0
- **Live provider integrations:** Not run. Search: no `TAVILY_API_KEY`. Model: no `OPENAI_API_KEY`. Page fetching was exercised live in Sprint 3 against two public HTTPS sites (`example.com`, `wikipedia.org`).
- **Blockers:** None.

## Verification evidence

| Check | Command | Result |
|---|---|---|
| Full offline suite | `.venv/bin/python -m pytest` | **455 passed, 4 deselected** in 1.21s, exit 0 |
| Lint | `ruff check .` | `All checks passed!`, exit 0 |
| Format | `ruff format --check .` | `53 files already formatted`, exit 0 |
| Live tests deselected by default | `pytest -m live` | 4 skipped (no credentials) — never faked |
| Offline benchmark | `run_offline_benchmark()` | 3/3 representative questions met all 4 documented criteria (see `docs/EVALUATION.md`) |
| Depth-flag tests | `pytest tests/test_cli_depth.py` | 25 passed |
| Secret scan | grep for key-shaped patterns | no secret-like patterns in src/tests/docs |

## Sprint 7 (US-703 — user-configurable research depth)

Scope chosen and recorded in ADR-017 (user delegated the decision). Acceptance criteria were written into `docs/ROADMAP.md` before implementation, per the backlog rules.

| Criterion | Evidence |
|---|---|
| 1. CLI accepts `--max-iterations`, `--max-results`, `--deadline` | `test_all_three_flags_are_accepted`, `test_deadline_accepts_fractional_seconds` |
| 2. Per-run override; environment authoritative when flag absent | `test_flag_overrides_environment_for_one_run_only`, `test_absent_flags_leave_configured_values_untouched`, `test_override_does_not_mutate_the_settings_class_defaults` |
| 3. Bounds enforced by the same `Settings` constraints; bad value = exit 2, no research | 8 out-of-range + 3 non-numeric parametrized tests, `test_no_research_runs_on_rejection`, `test_valid_boundary_values_are_accepted` |
| 4. Effective values visible in output | `test_offline_status_prints_effective_depth`, `test_run_metadata_prints_effective_depth` |
| 5. Offline mode validates flags without providers | `test_offline_mode_rejects_bad_flags_without_any_provider`, `test_offline_mode_with_valid_flags_never_researches` |

Implementation note: the override re-validates the whole `Settings` object, so accepted ranges are defined in exactly one place and cannot drift from environment-based configuration.

**Declined stories (ADR-017):** US-701 (web UI — outside CLI charter, unverifiable), US-704 (deployment/monitoring — no live environment), US-705 (persistent history — gated on a privacy design that does not exist); US-702's history half declined, its "download" half already satisfied by `-o/--output`.

## Stories completed earlier (Sprints 1–6)

| Sprint | Stories | Status |
|---|---|---|
| 1 | US-101, US-102 (partial), US-501 | complete |
| 2 | US-201, US-203 (partial), US-503 | complete |
| 3 | US-202, US-601, US-602 | complete — live HTTPS pinning verified |
| 4 | US-301, US-302, US-303, US-304, US-102 | complete |
| 5 | US-401, US-402, US-403, US-502 | complete |
| 6 | US-103, US-402, US-503, US-504, US-603 | complete |

## Known limitations

- **No live model or search call has ever been made.** The OpenAI adapter's request shape and the Tavily provider are tested against fakes; real-world auth, rate limits, model tool-call fidelity, and answer quality are **unverified**. Four live tests are written and ready (`pytest -m live`) but skip without credentials.
- **No live evaluation.** `docs/EVALUATION.md` records offline fixture results only and explicitly refuses to report accuracy, quality, or cost figures (PRD §10).
- **Conflict detection between sources is not automatic** — a caller may declare conflicts as limitations; the report does not detect contradictions itself.
- No retries with backoff for transient provider errors (deliberate: US-603 forbids unlimited retry; one call, one recorded error).
- The package is not installed; CLI and scripts need `PYTHONPATH=src`.
- The repository has no remote; nothing was pushed.

## Next action

All planned sprints (0–6) and the approved Sprint 7 scope are complete and verified. To run Atlas for real: set `ATLAS_MODE=live`, `OPENAI_API_KEY`, `TAVILY_API_KEY`, and `ATLAS_MODEL`, then run `pytest -m live` first to confirm the provider integrations, before trusting any report.
