# Atlas — Project Report

**Project:** Atlas, a single-agent Python research assistant (CLI) that answers a
research question with an evidence-grounded Markdown report.
**Location:** `~/Desktop/007/atlas_opencode_starter_kit/atlas_opencode_starter`
**Date:** 2026-10-25
**Status:** Sprints 0–7 complete, verified, and committed locally — **including
a verified live end-to-end run** (Sprint 7b, US-706).

---

## 1. Executive summary

Atlas was built end-to-end from the sprint plan in `docs/` and `prompts/`:
CLI → pipeline → bounded agent loop → allowlisted tools (search, fetch) →
run-local source registry → citation-validating report builder, plus an offline
evaluation harness.

- **499 tests pass** (4 live tests deselected by default); `ruff check` and
  `ruff format --check` both exit 0.
- **Live mode verified end to end** (Sprint 7b): `pytest -m live` → 4 passed
  against OpenRouter (model) + Exa (search), and a real CLI run produced a
  completed, citation-resolving report. Earlier in the project no credentials
  existed, so live behaviour was unverified — that gap is now closed for the
  providers actually configured.
- **All work committed** as logical commits on branch `master`. Nothing was
  pushed — no remote exists and none was created.

**Honest caveat:** live runs verify *structure* (bounds, resolving citations,
honest status, reported token usage) — never answer *quality*. Only one model
was exercised live. The offline benchmark still refuses accuracy figures.

---

## 2. What was built

| Component | File | Purpose |
|---|---|---|
| Configuration | `src/atlas/config.py` | Frozen `Settings` from env/`.env`; `SecretStr` credentials; **no default model ID** (ADR-003) |
| Request models | `src/atlas/models.py` | Validated request, tool-call/observation models, honest status derivation (partial never labelled complete) |
| CLI | `src/atlas/main.py` | Exit codes 0/2/3/4/5, `--output`, per-run depth flags (US-703), run metadata |
| Search tool | `src/atlas/tools/search.py` | Tavily **and Exa** behind one `SearchProvider` protocol; API keys redacted from errors |
| Fetch tool | `src/atlas/tools/fetch.py` | SSRF-defended retrieval: scheme/port allowlist, routability checks, IP pinning with Host/SNI bound to hostname, per-hop redirect revalidation, byte cap, stdlib HTML extraction |
| Tool registry | `src/atlas/tools/registry.py` | Model output treated as untrusted: allowlisted names only, Pydantic-validated arguments, duplicate suppression |
| Model adapter | `src/atlas/model.py` | Stateless OpenAI Responses adapter — every turn replays question + observations explicitly (ADR-014) |
| Agent loop | `src/atlas/agent.py` | Double-bounded loop (max iterations + wall-clock deadline), explicit termination reasons |
| Source registry | `src/atlas/sources.py` | Stable IDs, canonical-URL dedup, snippet vs. page-text evidence tiers |
| Report builder | `src/atlas/report.py` | Citations resolved against the registry; verbatim excerpts only; limitations disclosed (ADR-015) |
| Pipeline | `src/atlas/pipeline.py` | Request → agent → sources → report, providers injected so the chain runs offline |
| Evaluation | `src/atlas/evaluation.py` | Deterministic offline benchmark (US-504) |

**Sprint 7 feature (US-703, scope chosen per user delegation and recorded as
ADR-017):** `--max-iterations N`, `--max-results N`, `--deadline SECONDS`
per-run overrides, re-validated through the same `Settings` constraints so
bounds live in exactly one place. Bad value → exit 2, no research runs;
effective values printed in run metadata for reproducibility.

Declined stories (ADR-017): US-701 (web UI — outside CLI charter), US-702
history half (privacy gate; "download" already covered by `-o`), US-704
(deployment — no live environment), US-705 (persistent history — gated on a
privacy design that doesn't exist).

**Sprint 7b feature (US-706, ADR-018):** provider portability. The supplied
credentials were Exa/Groq/OpenRouter — not Tavily/OpenAI — so live mode was
unreachable. Added an `ExaSearchProvider` (same protocol, bounds, and
redaction contract; injected transport; no new dependency), an optional
`OPENAI_BASE_URL` for OpenAI-compatible endpoints, and a one-of search
credential rule (Tavily **or** Exa). Groq is deliberately unused: it has no
Responses API. Acceptance criteria were written before implementation.

---

## 3. Verification evidence

All run on the committed tree:

| Check | Command | Result |
|---|---|---|
| Full offline suite | `.venv/bin/python -m pytest` | **499 passed, 4 deselected**, exit 0 |
| Lint | `ruff check .` | All checks passed, exit 0 |
| Format | `ruff format --check .` | exit 0 |
| **Live suite** | `pytest -m live` (OpenRouter + Exa) | **4 passed** — model, usage, search+fetch, full end-to-end run |
| **Live CLI run** | `python -m atlas.main "..." -o live_report.md` | exit 0; completed report, sources resolve, evidence tiers honest, usage 1475 in / 517 out |
| Credential checks | direct API pings | Exa ✓, Groq ✓, OpenRouter ✓ incl. `/responses` |
| Offline benchmark | `run_offline_benchmark()` | **3/3** questions met all 4 documented criteria (see `docs/EVALUATION.md`) |
| Secret scan | grep of full git history (`git log -p --all`) | 0 secret-like additions |
| `.env` | `git check-ignore` | ignored, not tracked |
| Remote | `git remote` | 0 remotes — nothing pushed |

### Test suite breakdown (23 files, 5,525 test lines vs. 3,580 source lines)

| Area | File(s) | Tests |
|---|---|---|
| SSRF / fetch policy | `test_fetch_policy.py` | 74 |
| Fetch orchestration + transport | `test_fetch.py`, `test_fetch_transport.py` | 48 |
| Search + SDK contract | `test_search.py`, `test_search_sdk_contract.py` | 45 |
| Exa provider (US-706) | `test_exa_search.py` | 28 |
| Provider portability (US-706) | `test_provider_portability.py` | 16 |
| Config + request validation | `test_config.py`, `test_request.py` | 44 |
| Report + sources | `test_report.py`, `test_sources.py` | 57 |
| CLI (incl. depth flags) | `test_cli*.py` (4 files) | 58 |
| Agent + model + registry | `test_agent.py`, `test_model.py`, `test_registry.py` | 68 |
| Pipeline + evaluation | `test_pipeline.py`, `test_evaluation.py` | 31 |
| Security integration | `test_integration_security.py` | 12 |
| Extraction | `test_extract.py` | 18 |
| Live (deselected) | `test_live.py` | 4 (4 passed with credentials) |

---

## 4. Delivery: 15 commits on `master`

```
4b3f73d US-706: Exa search provider and OpenAI-compatible base URL (ADR-018)
d01095a Adversarial-content integration tests and deselected live tests (US-602/603/503)
bb1a14e Report, pipeline, and evaluation tests (US-401/402/403/504)
70a2223 Agent-loop, registry, and model-adapter tests (US-301/302/303/304)
75b663b Secure-fetch safety tests: SSRF policy, redirects, extraction (US-202/601/602)
fc8ae05 Source registry and search-provider tests (US-201/203/601)
b338fa8 CLI, configuration, and request tests (US-501/502/703)
f7cc546 Offline evaluation harness with recorded benchmark outcomes (US-504)
816005d End-to-end pipeline and evidence-grounded report builder (US-401/402/403)
e4457d8 Stateless model adapter and double-bounded agent loop (US-304/301-303)
0b44a5d Web research tools: search, secure fetch, allowlisted registry
68030fc Run-local source registry with stable IDs and deduplication (US-203)
ea55e77 Core: error taxonomy, validated settings, models, CLI entry point
663b014 Project charter, planning docs, and build configuration
```

(plus this report as the final commit)

- Git identity was unset, so a **repo-local** one was configured:
  `Atlas Builder <atlas-builder@localhost>`. Change it with
  `git config user.name` / `git config user.email` and rebase to amend.
- **Nothing pushed** — no remote exists and none was created.
- Credentials live only in the git-ignored `.env`; they were shared in chat
  and should be rotated if that channel is not private.

---

## 5. Sprint / story completion

| Sprint | Stories | Status |
|---|---|---|
| 0 | Charter, PRD, architecture, sprint plan | complete |
| 1 | US-101, US-102 (partial), US-501 | complete |
| 2 | US-201, US-203 (partial), US-503 | complete |
| 3 | US-202, US-601, US-602 | complete — live HTTPS pinning verified |
| 4 | US-301–304, US-102 | complete |
| 5 | US-401–403, US-502 | complete |
| 6 | US-103, US-402, US-503, US-504, US-603 | complete |
| 7 | US-703 (scope per ADR-017) | complete |
| 7b | US-706 provider portability (ADR-018) | complete — **live run verified** |

18 ADRs recorded (`docs/DECISIONS.md`, ADR-001…018).

---

## 6. Known limitations (stated honestly)

1. **Live runs verify structure, not answer quality.** Bounds, resolving
   citations, honest status, and reported token usage are checked; accuracy
   is not. Only **one model** was exercised live
   (`nvidia/nemotron-3.5-lightning:free` via OpenRouter) — tool-call fidelity
   on other models is unverified.
2. **No live evaluation.** `docs/EVALUATION.md` records offline fixture results
   only and explicitly refuses accuracy/quality/cost figures (PRD §10).
3. **Groq is unused.** The key works, but Groq exposes only
   `/chat/completions`; Atlas's adapter speaks the Responses API (ADR-018).
   Supporting it would require a second model adapter.
4. **Conflict detection is not automatic** — callers may declare conflicts as
   limitations; the report does not detect contradictions itself.
5. **No retry/backoff** for transient provider errors (deliberate: US-603
   forbids unlimited retry).
6. The package is **not installed**; CLI and scripts need `PYTHONPATH=src`.
7. **No remote repository** — the work exists only on this machine. The API
   keys were shared in chat; rotate them if that channel is not private.

---

## 7. How to run it

```bash
cd ~/Desktop/007/atlas_opencode_starter_kit/atlas_opencode_starter

# Offline validation (default, no credentials needed)
PYTHONPATH=src python -m atlas.main "What is retrieval-augmented generation?"

# Quality gates
.venv/bin/python -m pytest        # 499 passed, 4 deselected
ruff check .                      # exit 0
ruff format --check .             # exit 0

# Live mode — keys are already in the git-ignored .env; export them:
set -a; source .env; set +a
export ATLAS_MODE=live OPENAI_API_KEY="$OPENROUTER_API_KEY" \
       OPENAI_BASE_URL=https://openrouter.ai/api/v1 \
       ATLAS_MODEL=nvidia/nemotron-3.5-lightning:free

.venv/bin/python -m pytest -m live        # 4 passed
PYTHONPATH=src python -m atlas.main "Your question" --output report.md
```

**Current state:** the only remaining verification gap is answer *quality*
(see §6) — run more questions through the offline benchmark's criteria, or
add an LLM-judge evaluation, if quality claims are ever needed.
