# Atlas — Current Status

> This is the canonical current-state summary. Update it only after inspecting the actual repository and verifying the reported work.

## Current state

- **Current sprint:** Sprint 7b — US-706 (provider portability: Exa search provider + OpenAI-compatible base URL), implemented per ADR-018 after user-provided credentials made live mode reachable.
- **Overall implementation status:** MVP **COMPLETE** plus two approved post-MVP features (US-703 research depth, US-706 provider portability). The full pipeline — CLI → pipeline → agent loop → allowlisted tools → source registry → citation-validating report — runs **live end to end** and offline.
- **Live integrations: VERIFIED.** `pytest -m live` → **4 passed** (model call, usage reporting, real search + fetch, full end-to-end research run) against **OpenRouter** (model, Responses API) and **Exa** (search). A real CLI run produced a completed, citation-resolving report (`live_report.md`, exit 0). Groq's key validates and generates but is unused: Groq has no Responses API (ADR-018).
- **Last test run:** `.venv/bin/python -m pytest` → **499 passed, 4 deselected** in ~1.9s, exit code 0 (offline suite).
- **Blockers:** None.

## Verification evidence

| Check | Command | Result |
|---|---|---|
| Full offline suite | `.venv/bin/python -m pytest` | **499 passed, 4 deselected**, exit 0 |
| Lint | `ruff check .` | `All checks passed!`, exit 0 |
| Format | `ruff format --check .` | exit 0 |
| **Live suite** | `pytest -m live` (OpenRouter + Exa creds) | **4 passed** in 19.2s — first live model call, live search, live end-to-end run |
| **Live CLI run** | `python -m atlas.main "..." --output live_report.md` | exit 0; completed report, 6+ sources, citations resolve, evidence tiers honest, token usage reported (1475 in / 517 out) |
| Offline benchmark | `run_offline_benchmark()` | 3/3 representative questions met all 4 documented criteria (see `docs/EVALUATION.md`) |
| Credential checks | direct API pings | Exa search ✓, Groq generation ✓, OpenRouter generation ✓, OpenRouter `/responses` ✓ |
| Secret scan | grep over `git log -p --all` | no secret-like patterns committed; `.env` git-ignored |

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

- **Answer quality is not measured.** Live runs verify *structure and honesty* (bounded iterations, resolving citations, explicit status, reported token usage) — never accuracy. `docs/EVALUATION.md` still refuses accuracy/quality/cost figures (PRD §10).
- **Groq is unused.** Its key works, but Groq exposes only `/chat/completions`; Atlas's adapter speaks the Responses API (ADR-018). Supporting it would need a second adapter.
- **One model was exercised live** (`nvidia/nemotron-3.5-lightning:free` via OpenRouter). Other models — especially tool-calling fidelity — are unverified.
- **Conflict detection between sources is not automatic** — a caller may declare conflicts as limitations.
- No retries with backoff for transient provider errors (deliberate: US-603 forbids unlimited retry).
- The package is not installed; CLI and scripts need `PYTHONPATH=src`.
- The repository has no remote; nothing was pushed. Live credentials live only in the git-ignored `.env` (they were shared in chat and should be rotated if that channel is not private).

## Next action

All planned sprints (0–6) and the approved Sprint 7 scope (US-703, US-706) are complete and verified — offline and live. Natural next steps: rotate the shared keys, try additional models via `ATLAS_MODEL`/`OPENAI_BASE_URL`, or revisit the declined stories (US-701/704/705) if a deployment target or privacy design ever exists.
