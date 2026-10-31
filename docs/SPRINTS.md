# Atlas — Sprint Plan

## Sprint policy

One sprint is executed at a time. Each sprint has a goal, explicit story scope, verification plan, and exit gate. The coding agent stops after the sprint and waits for user approval.

## Sprint 0 — Discovery and governance

**Goal:** make the project plan accurate before feature implementation.
**Stories:** planning/documentation work.
**Tasks:** inspect repo, Python, Git; inspect existing instructions; prepare PRD, architecture, backlog, sprint plan, status, decision log, testing and security docs; resolve contradictions.
**Exit gate:** documents agree; repository state is accurately reported; no app feature implemented; next action is clear.

## Sprint 1 — Foundation and configuration

**Goal:** reproducible Python project and safe configuration.
**Stories:** US-101, US-102, US-501, US-503, US-504, US-502 (CLI skeleton).
**Tasks:** packaging, dependencies, config models, environment loading, `.gitignore`, test/lint config, minimal CLI with question validation.
**Verification:** configuration tests; invalid/missing config behavior; request-validation tests; test/lint commands; clean setup instructions.
**Exit gate:** setup reproducible; invalid questions rejected before any provider client is constructed; tests do not require paid APIs; secrets protected.

## Sprint 2 — Search integration

**Goal:** reliable normalized search adapter.
**Stories:** US-201, US-203.
**Tasks:** Tavily adapter, input/result validation, limits, error normalization, deduplication policy.
**Verification:** mocked success, malformed response, timeout, provider error, maximum result count.
**Exit gate:** deterministic tests pass; live smoke test reported separately if credentials exist.

## Sprint 3 — Secure page retrieval

**Goal:** safely retrieve readable page text.
**Stories:** US-202, US-203, US-601, US-602.
**Tasks:** URL validation, DNS/IP policy, redirect revalidation, bounded HTTP fetch, content-type/size checks, extraction.
**Verification:** forbidden schemes, localhost/private addresses, unsafe redirects, timeout, oversized response, malformed/empty content.
**Exit gate:** safety tests pass; no page code executes; limitations documented.

## Sprint 4 — Agent loop and tool calling

**Goal:** implement adaptive bounded tool use.
**Stories:** US-301, US-302, US-303, US-304, US-102.
**Tasks:** model adapter, explicit tool registry, validated dispatch, state tracking, bounded loop, stop reasons, safe error handling.
**Verification:** fake-model tests for one tool call, follow-up based on observation, final response, invalid tool, malformed arguments, repeated calls, iteration exhaustion, provider failure.
**Exit gate:** at least one test proves a later action depends on a previous observation; all execution is bounded.

## Sprint 5 — Evidence-grounded reporting

**Goal:** turn research state into a traceable report.
**Stories:** US-401, US-402, US-403, US-502.
**Tasks:** report structure, source registry, evidence excerpts, citation validation, Markdown output, CLI output path.
**Verification:** valid citations, unknown source IDs, missing evidence, conflicting sources, partial run.
**Exit gate:** no citation can refer to an unregistered source; uncertainty is explicit.

## Sprint 6 — Integration and evaluation

**Goal:** verify end-to-end behavior and resilience.
**Stories:** US-103, US-304, US-402, US-503, US-504, US-603.
**Tasks:** integration tests, representative research benchmark, error-path review, run metadata, documentation review.
**Verification:** all relevant tests; lint/type checks; at least three representative questions assessed against documented criteria; actual outcomes recorded.
**Exit gate:** MVP acceptance criteria reviewed; limitations and observed evaluation results documented.

## Sprint 7 — Optional interface/release preparation

**Goal:** add only approved post-MVP features.
**Possible stories:** US-701 through US-705.
**Gate:** Sprint 6 must pass and user must explicitly approve the chosen scope.
**Delivered:** US-703 (research depth, ADR-017) and US-706 (provider portability — Exa provider + OpenAI-compatible base URL, ADR-018); other stories declined with reasons.

## Sprint 8 — Research quality evaluation

**Goal:** measure whether Atlas produces accurate, relevant, complete, properly cited reports — honestly, without inventing numbers.
**Stories:** US-801 (dataset), US-802 (deterministic checks), US-803 (citation support levels), US-804 (human review workflow), US-805 (opt-in live runner), US-806 (metrics), US-807 (regression tests), US-808 (documentation).
**Gate:** Sprint 7 passes; user brief supplied 2026-10-25 and approved a 3-case live smoke run.
**Verification:** acceptance criteria in `docs/ROADMAP.md` (written before implementation); full offline suite and quality gates green; live smoke recorded only if actually executed.
**Delivered:** 24-case dataset (`evaluation_dataset/cases.json`, 8 categories, 3 cases each), eight deterministic checks + three-level citation verdicts (`src/atlas/quality.py`), artifacts and review workflow (`src/atlas/evalreport.py`), metrics with explicit denominators (`src/atlas/evalmetrics.py`), opt-in live runner (`src/atlas/evallive.py`), CLI (`python -m agent007.evalrun`), 86 new tests, docs rewritten. Offline baseline (24 cases, 0 quality failures) and the approved 3-case live smoke are recorded in `docs/EVALUATION.md`; ADR-019 documents the design.

## Sprint reporting template

- Sprint:
- Goal:
- Stories selected:
- Changes made:
- Commands actually run:
- Test results:
- Acceptance criteria verified:
- Acceptance criteria not verified:
- Known defects:
- Decisions/blockers:
- Documentation updated:
- Current status:
- Recommended next action:
