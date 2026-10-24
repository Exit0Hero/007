# Atlas — Product Roadmap and Backlog

## Priority definitions

- **P0:** Required for a safe, usable MVP.
- **P1:** Important hardening or usability improvement.
- **P2:** Optional enhancement after the MVP.

## Status definitions

Use `NOT STARTED`, `IN PROGRESS`, `BLOCKED`, `IMPLEMENTED, NOT VERIFIED`, `VERIFIED`, or `DEFERRED`. Do not mark work VERIFIED without recorded evidence.

## Story fields

Every story carries: stable ID, priority, acceptance criteria, sprint assignment, and a verification approach. Test-layer numbers refer to `docs/TESTING.md`. All listed verification approaches are expected to run offline unless the story explicitly says otherwise.

## Epic E1 — Research request management

### US-101 — Submit a research question (P0)
As a researcher, I want to enter a natural-language question so Atlas can investigate it.
Acceptance: non-empty input; whitespace-only rejection; maximum length; clear validation error; no paid call for invalid input.
Sprint: 1.
Verification: unit tests for empty, whitespace-only, boundary-length, and over-length input; assert validation fails before any provider client is constructed (layer 1).

### US-102 — Configure research limits (P0)
As a user, I want configurable limits so research is bounded.
Acceptance: validated settings; documented defaults; invalid values fail clearly; no unbounded loop.
Sprint: 1 and 4.
Verification: unit tests for default values, valid overrides, and rejected invalid values (iteration count, timeouts, result counts); loop-bound assertion exercised again in the agent loop (layers 1 and 3).

### US-103 — Understand completion (P0)
As a user, I want to know whether research completed, failed, or reached a limit.
Acceptance: explicit status and termination reason; partial work never labelled complete.
Sprint: 6.
Verification: fake-model runs forced into success, budget-exhausted, and provider-failure outcomes; assert the reported status matches the actual termination reason (layer 3).

## Epic E2 — Web research tools

### US-201 — Search the web (P0)
Acceptance: configured provider; normalized metadata; bounded results; timeouts and errors handled; no fabricated results.
Sprint: 2.
Verification: component tests against a mocked search SDK covering success normalization, malformed response, timeout, provider error, and the maximum result count (layer 2).

### US-202 — Read a source page (P0)
Acceptance: HTTP(S) only; SSRF protection; DNS and redirect validation; response/time limits; readable extraction; errors handled.
Sprint: 3.
Verification: security and component tests for forbidden schemes, private/loopback/link-local/multicast destinations, unsafe redirects, DNS-rebinding-style mismatches, timeout, oversized response, disallowed content type, and empty/malformed bodies (layers 6 and 2).

### US-203 — Preserve source identity (P0)
Acceptance: per-run stable source ID; URL and available metadata retained; deduplication policy; snippets distinguished from full content.
Sprint: 2–3.
Verification: unit tests asserting stable ID assignment across repeated URLs, metadata retention, dedup behaviour, and that snippet evidence is labelled distinctly from fetched content (layer 1).

## Epic E3 — Agent orchestration

### US-301 — Select research actions (P0)
Acceptance: documented model tool calling; explicit registry; argument validation; actual tool results returned to the model.
Sprint: 4.
Verification: fake-model test asserting a registered tool call executes and its result appears in the next model request; unregistered tool name and malformed arguments rejected (layer 3).

### US-302 — Adapt to findings (P0)
Acceptance: follow-up decisions depend on observations; agent may stop early; iteration is bounded.
Sprint: 4.
Verification: fake-model test where the second tool call is only valid if the first observation contains a specific value, proving adaptation rather than a fixed script; early-stop path exercised (layer 3).

### US-303 — Terminate safely (P0)
Acceptance: default maximum eight model/tool-loop iterations; overall deadline; controlled unsupported/repeated calls; explicit stop reason.
Sprint: 4.
Verification: fake-model tests for iteration exhaustion at the configured default, deadline breach, unsupported and repeated calls, each asserting an explicit stop reason (layer 3).

### US-304 — Isolate failures (P0)
Acceptance: expected errors categorized; bounded retries; no secret leakage.
Sprint: 4 and 6.
Verification: unit and agent-loop tests asserting categorized error types and bounded retry counts; captured logs and error messages asserted to contain no configured secrets (layers 1, 3, and 6).

## Epic E4 — Evidence-grounded reporting

### US-401 — Generate a research report (P0)
Acceptance: question, summary, findings, limitations, source references; Markdown output.
Sprint: 5.
Verification: report tests asserting all required sections are present for complete, partial, and evidence-free runs, with stable Markdown output (layer 4).

### US-402 — Validate citations (P0)
Acceptance: all citations resolve to registered sources; unknown IDs rejected; no fabricated evidence.
Sprint: 5–6.
Verification: report tests for valid citations, unknown source IDs, missing evidence, and conflicting evidence; an unregistered ID must raise a citation-validation error rather than being rendered (layer 4).

### US-403 — Preserve research evidence (P0)
Acceptance: bounded excerpts and metadata retained; direct evidence distinguished from interpretation.
Sprint: 5.
Verification: report tests asserting excerpt length bounds are enforced and that direct evidence and interpretation are labelled distinctly (layer 4).

## Epic E5 — Developer experience

### US-501 — Configure the application (P0)
Acceptance: environment-based secrets; placeholder-only example file; safe configuration errors.
Sprint: 1.
Verification: unit tests for environment loading, `.env` loading, missing-credential behaviour, and a check that `.env.example` contains placeholders only (layer 1).

### US-502 — Run locally (P0)
Acceptance: documented CLI; output path; useful errors and exit codes.
Sprint: 1 and 5.
Verification: CLI tests asserting exit codes for valid, invalid, and unconfigured runs; Sprint 1 covers the skeleton and error paths only, Sprint 5 adds report output (layer 1).

### US-503 — Test without paid calls (P0)
Acceptance: mocked unit/component tests; deterministic core tests; live tests separated.
Sprint: 1 onward.
Verification: default test run completes with no credentials present and no outbound network access; live tests carry a dedicated marker and are deselected by default (layer 5).

### US-504 — Maintainable code (P0)
Acceptance: public type hints, focused modules, lint/format checks, useful docs.
Sprint: all.
Verification: `ruff check .` and `ruff format --check .` exit 0; type hints present on public interfaces; results and exit codes recorded in the sprint report.

## Epic E6 — Security and resilience

### US-601 — Protect secrets (P0)
Acceptance: ignored local secrets; no secrets in logs, docs, tests, reports, or commits.
Sprint: 1 and 3.
Verification: test asserting `.env` is git-ignored and `.env.example` holds no real values; secret-redaction test asserting configured secrets never appear in logs or error output (layers 1 and 6).

### US-602 — Treat retrieved content as untrusted (P0)
Acceptance: page content cannot override instructions or execute code; tool permissions enforced in application code.
Sprint: 3–4.
Verification: adversarial-content tests asserting injected instructions in fetched text never reach the system prompt, never change tool permissions, and never cause code execution (layers 6 and 3).

### US-603 — Bound resource consumption (P0)
Acceptance: iteration, request, response, timeout, and result limits; no unlimited retry; usage reported when available.
Sprint: 4 and 6.
Verification: agent-loop and component tests for each limit (iterations, request timeout, response size, result count, retry count); provider usage recorded when the SDK returns it and reported as unavailable otherwise (layers 2 and 3).

## Optional post-MVP stories

- US-701: Web UI (P2). **Skipped** (ADR-017): needs a web stack and hosting; out of the CLI charter.
- US-702: Download/report history (P2). **Partially satisfied**: `atlas -o PATH` writes a report to any path the user chooses, which covers "download"; the history/retention half is declined because it collides with US-705's privacy requirement.
- US-703: User-configurable research depth (P2). **Scheduled as Sprint 7.**
- US-704: Deployment and monitoring (P2). **Skipped** (ADR-017): infrastructure work with no live environment to deploy to or monitor.
- US-705: Persistent research history (P2; requires privacy and retention design). **Skipped** (ADR-017): explicitly gated on a privacy and retention design that does not exist.

### US-703 — User-configurable research depth (Sprint 7)

**Acceptance criteria:**

1. The CLI accepts `--max-iterations N`, `--max-results N`, and `--deadline SECONDS`.
2. Each flag overrides the corresponding configured value for one run only; environment configuration stays authoritative when a flag is absent.
3. Values are validated against the same bounds as `Settings` (iterations 1–64, results 1–50, deadline > 0 and ≤ 3600s). An out-of-range or non-numeric value is a usage error (exit code 2) and no research runs.
4. The effective values are visible in the run's reported metadata, so a run can be reproduced.
5. Offline mode accepts and validates the flags without contacting any provider.

**Verification approach:** CLI tests asserting flag parsing, per-run override without mutating global configuration, rejection of out-of-range and non-numeric values with exit code 2, no research executed on rejection, and visibility of effective values in output — all with an injected fake runner (layer 1).

Verification approach for US-701 through US-705 is intentionally not specified. These stories have no sprint assignment and must gain acceptance criteria and a verification approach before they are scheduled.

## Backlog management rules

- Add a stable story ID before implementation.
- Every story must have acceptance criteria and a verification plan.
- Record dependencies and scope changes.
- Keep sprint scope small enough to review.
- Do not add features mid-sprint without explaining the impact.
- Do not mark a story complete based solely on generated code.
