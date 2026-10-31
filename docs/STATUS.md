# Atlas — Current Status

> This is the canonical current-state summary. Update it only after inspecting the actual repository and verifying the reported work.

## Current state

- **Current sprint:** Sprint 8 — research quality evaluation (US-801 … US-808), implemented per ADR-019: a 24-case dataset, eight deterministic checks, three-level citation verdicts, review-gated accuracy, metrics with explicit denominators, and an opt-in live runner.
- **Overall implementation status:** MVP **COMPLETE**, two approved post-MVP features (US-703, US-706), and the evaluation system (Sprint 8). The full pipeline — CLI → pipeline → agent loop → allowlisted tools → source registry → citation-validating report — runs **live end to end** and offline, and can now be evaluated for research quality without inventing numbers.
- **Live integrations: VERIFIED.** `pytest -m live` → **4 passed** (model call, usage reporting, real search + fetch, full end-to-end research run) against **OpenRouter** (model, Responses API) and **Exa** (search). The Sprint 8 **live evaluation smoke (3 cases)** also ran for real: 2/3 completed, 21/21 citations resolved, 0 provider failures, 0 recorded reviews (see `docs/EVALUATION.md`).
- **Evaluation: VERIFIED offline, partially executed live.** Offline baseline over all 24 cases: 0 deterministic check failures, 1 scripted provider failure (by design), every accuracy field `needs_review`.
- **Last test run:** `.venv/bin/python -m pytest` → **585 passed, 4 deselected** in ~2.0s, exit code 0 (offline suite).
- **Blockers:** None.

## Verification evidence

| Check | Command | Result |
|---|---|---|
| Full offline suite | `.venv/bin/python -m pytest` | **585 passed, 4 deselected**, exit 0 |
| Lint | `ruff check .` | `All checks passed!`, exit 0 |
| Format | `ruff format --check .` | exit 0 |
| **Live suite** | `pytest -m live` (OpenRouter + Exa creds) | **4 passed** in 19.2s — first live model call, live search, live end-to-end run |
| **Live CLI run** | `python -m agent007.main "..." --output live_report.md` | exit 0; completed report, 6+ sources, citations resolve, evidence tiers honest, token usage reported (1475 in / 517 out) |
| Offline benchmark | `run_offline_benchmark()` | 3/3 representative questions met all 4 documented criteria (see `docs/EVALUATION.md`) |
| **Offline evaluation** | `python -m agent007.evalrun run` (24 cases) | exit 2 by design; **0 deterministic check failures**, 1 scripted provider failure, 46/46 citations resolved, 46/46 excerpts verified, all 24 accuracy fields `needs_review` |
| **Live evaluation smoke** | `python -m agent007.evalrun run --live --smoke` (3 cases, user-approved) | exit 2; 2/3 completed, 21/21 citations resolved, 0 provider failures, tokens 5561 total, no reviews recorded, no secrets in artifacts |
| Credential checks | direct API pings | Exa search ✓, Groq generation ✓, OpenRouter generation ✓, OpenRouter `/responses` ✓ |
| Secret scan | grep over `git log -p --all` and the committed evaluation artifacts | no secret-like patterns committed; `.env` git-ignored |

## US-801 … US-808 — Research quality evaluation (Sprint 8, ADR-019)

Acceptance criteria were written into `docs/ROADMAP.md` **before** implementation, per the backlog rules.

| Criterion | Evidence |
|---|---|
| 1. ≥20 documented cases across 8 categories | `evaluation_dataset/cases.json` — **24 cases**, 3 per required category; schema-validated (`tests/test_eval_dataset.py`) |
| 2. Offline evaluation with no credentials or network | `Settings.from_env({})` + per-case fixtures; `test_offline_run_makes_no_network_calls_without_credentials` blocks `socket.socket.connect` |
| 3. Invalid citations and unsupported excerpts detected | `test_unknown_source_id_fails_resolution_and_replay_checks`, `test_incorrect_excerpt_fails_excerpt_support`, builder rejection tests |
| 4. Factual accuracy unverified until reviewed | `CaseResult` rejects `pass` without a `ReviewRecord`; `test_fresh_result_cannot_claim_verified_accuracy`; all 24 baseline fields are `needs_review` |
| 5. JSON + Markdown artifacts generated | `eval_results.json` / `eval_summary.md` written by `evalrun run` and `evalrun summarize`; committed snapshots under `evaluation_results/` |
| 6. Live evaluation explicit and bounded | `require_live_opt_in()` refuses before building providers (exit 5); one attempt, no retry, existing bounds; recorded smoke run in `docs/EVALUATION.md` |
| 7. Metrics distinguish pass/fail/unknown | `src/atlas/evalmetrics.py` — numerator/denominator/unknown per metric, `unavailable` (never `0`) with no observations |
| 8. Regression tests | 5 new files, **86 new tests** (`tests/test_eval_dataset.py`, `test_eval_quality.py`, `test_eval_results.py`, `test_eval_run.py` + coverage of every US-807 item) |
| 9. Full suite + gates green | `pytest` 585 passed / 4 deselected; `ruff check .` and `ruff format --check .` exit 0 |
| 10. Accurate documentation | `docs/EVALUATION.md` rewritten with executed results and explicit limitations; `docs/DECISIONS.md` ADR-019 |

## US-706 — Provider portability (Sprint 7b, ADR-018)

Credentials supplied by the user were Exa/Groq/OpenRouter — not Tavily/OpenAI — so live mode was unreachable. Acceptance criteria were written into `docs/ROADMAP.md` **before** implementation.

| Criterion | Evidence |
|---|---|
| 1. One of `TAVILY_API_KEY` / `EXA_API_KEY` satisfies live mode; neither names both | `test_exa_alone_satisfies_live_search_credentials`, `test_neither_search_key_is_a_configuration_error_naming_both` |
| 2. Exa provider honors the `SearchProvider` contract (bounds, normalization, redaction) | `tests/test_exa_search.py` — 27 tests with an injected fake transport |
| 3. Optional `OPENAI_BASE_URL` (http(s) only), default behaviour unchanged | `test_base_url_is_loaded`, `test_non_http_base_url_is_rejected`, `test_model_adapter_without_base_url_keeps_the_sdk_default` |
| 4. Deterministic selection: Tavily, else Exa | `test_tavily_is_preferred_when_both_keys_exist`, `test_exa_is_used_when_only_the_exa_key_exists` |
| 5. No new runtime dependency; transport injected | `RequestsExaTransport` imports `requests` (already a dependency) only at construction; all tests offline |
| 6. Real end-to-end run or honest failure, never faked | `pytest -m live` → 4 passed; `live_report.md` written by a real run (kept out of git) |

## Sprint 7 (US-703 — user-configurable research depth)

Scope chosen and recorded in ADR-017 (user delegated the decision). Acceptance criteria were written into `docs/ROADMAP.md` before implementation, per the backlog rules. Delivered: `--max-iterations`, `--max-results`, `--deadline` per-run overrides re-validated through `Settings`; bad value = exit 2 with no research; effective values printed in run metadata. 25 tests in `tests/test_cli_depth.py`.

**Declined stories (ADR-017):** US-701 (web UI — outside CLI charter, unverifiable), US-704 (deployment/monitoring — no live environment), US-705 (persistent history — gated on a privacy design that does not exist); US-702's history half declined, its "download" half already satisfied by `-o/--output`.

## Stories completed (sprint index)

| Sprint | Stories | Status |
|---|---|---|
| 1 | US-101, US-102 (partial), US-501 | complete |
| 2 | US-201, US-203 (partial), US-503 | complete |
| 3 | US-202, US-601, US-602 | complete — live HTTPS pinning verified |
| 4 | US-301, US-302, US-303, US-304, US-102 | complete |
| 5 | US-401, US-402, US-403, US-502 | complete |
| 6 | US-103, US-402, US-503, US-504, US-603 | complete |
| 7b | US-706 (ADR-018) | complete — live end-to-end verified |
| 8 | US-801 … US-808 (ADR-019) | complete — 585 offline tests, offline baseline + 3-case live smoke recorded |

## Known limitations

- **Answer *quality* is measured structurally, not factually.** The Sprint 8 evaluation verifies structure, citation resolution, excerpt fidelity, disclosure, status honesty, and case conditions deterministically. **Factual accuracy, completeness, and relevance are `needs_review` for every case** — no human review has been recorded, so no accuracy percentage exists (by design, ADR-019).
- **Claim matching is literal.** Required/prohibited claims are case-insensitive substring tests, so a correct paraphrase counts as missing (this is what failed EV-GEN-001 in the live smoke).
- **Offline fixtures measure the pipeline, not a real model.** Only 3 of 24 cases have been executed live so far.
- **Groq is unused.** Its key works, but Groq exposes only `/chat/completions`; Atlas's adapter speaks the Responses API (ADR-018). Supporting it would need a second adapter.
- **One model was exercised live** (`nvidia/nemotron-3.5-lightning:free` via OpenRouter). Other models — especially tool-calling fidelity — are unverified.
- **Conflict detection between sources is not automatic** — a caller may declare conflicts as limitations.
- No retries with backoff for transient provider errors (deliberate: US-603 forbids unlimited retry; the live evaluator is single-attempt by design).
- The package is not installed; CLI and scripts need `PYTHONPATH=src`.
- The repository has no remote; nothing was pushed. Live credentials live only in the git-ignored `.env` (they were shared in chat and should be rotated if that channel is not private).

## Next action

All planned sprints (0–6), the approved Sprint 7 scope (US-703, US-706), and Sprint 8 (US-801 … US-808) are complete and verified. Natural next steps: **record a human review pass** so accuracy/completeness metrics become available, run the full 24-case live evaluation (user approval required), rotate the shared keys, or revisit the declined stories (US-701/704/705) if a deployment target or privacy design ever exists.
