# Atlas — Architecture Decision Log

Record meaningful decisions here. Do not treat proposals as finalized decisions until confirmed or verified.

## ADR-001 — Single-agent MVP

- **Status:** Accepted as initial scope
- **Context:** A multi-agent design adds coordination, cost, and failure modes before core behavior is proven.
- **Decision:** Start with one agent and a small explicit tool registry.
- **Alternatives:** Multi-agent orchestration; fixed workflow only.
- **Rationale:** The MVP must demonstrate adaptive tool selection while remaining easy to test and understand.
- **Consequences:** Easier debugging; less parallel specialization. Revisit only with evidence.

## ADR-002 — CLI before web UI

- **Status:** Accepted as initial scope
- **Context:** A frontend would add complexity before the core research loop is validated.
- **Decision:** Build a CLI MVP first.
- **Consequences:** Easier automated testing; no interactive UI initially.

## ADR-003 — OpenAI model API and Tavily search

- **Status:** Proposed; verify compatibility during implementation
- **Context:** The project needs a model that supports tool calling and a web-search provider.
- **Decision:** Initially target the OpenAI Python SDK/Responses API and Tavily Python SDK.
- **Required verification:** Current official API usage, SDK versions, model availability, account permissions, pricing, and error formats.
- **Alternatives:** Other compatible providers.
- **Consequences:** Requires separate application credentials and may incur usage charges.

## ADR-004 — Explicit Python tool registry

- **Status:** Accepted
- **Context:** Model output is untrusted and must not determine arbitrary code execution.
- **Decision:** Dispatch only explicitly registered functions after validating arguments and budgets.
- **Consequences:** New tools require code review and tests.

## ADR-005 — No persistent database in MVP

- **Status:** Accepted for MVP
- **Context:** One CLI research run can keep bounded state in memory and write a Markdown artifact.
- **Decision:** Avoid database/vector store until a concrete persistence requirement exists.
- **Revisit when:** User history, shared sessions, indexing, or resumable research is approved.

## ADR-006 — Evidence registry for citations

- **Status:** Accepted
- **Context:** Model-generated citations can be fabricated or mismatched.
- **Decision:** Keep source IDs and metadata in application-managed state and validate emitted citations against that registry.
- **Consequence:** Citation validity can be mechanically checked, although source-to-claim entailment still needs evaluation.

## Decision template

### ADR-NNN — Title
- Status: Proposed / Accepted / Superseded
- Date:
- Context:
- Decision:
- Alternatives:
- Rationale:
- Consequences:
- Revisit conditions:

## ADR-007 — Schedule US-101 in Sprint 1

- **Status:** Accepted pending user confirmation
- **Context:** Sprint 0 consistency review found `ROADMAP.md` assigning US-101 (submit a research question) to Sprint 1, while `SPRINTS.md` and `prompts/SPRINT_1.md` omitted it from Sprint 1 scope. US-101 is P0 and its acceptance criterion "no paid call for invalid input" is only meaningful in the same change that introduces the CLI entry point.
- **Decision:** Include US-101 in Sprint 1 scope in all three documents.
- **Alternatives:** Leave it unassigned; move it to Sprint 4 with the agent loop.
- **Rationale:** Question validation must exist before any provider client can be constructed, so separating it from the CLI skeleton would create an intermediate state that cannot satisfy its own acceptance criterion.
- **Consequences:** Sprint 1 grows by one story; exit gate now requires proof that invalid input is rejected before provider construction.
- **Revisit conditions:** If the user prefers to keep Sprint 1 to configuration only, move US-101 to Sprint 4 and revert this change.

## ADR-008 — Single packaging source of truth

- **Status:** Proposed
- **Context:** `ARCHITECTURE.md` section 4 lists both `requirements.txt` and `pyproject.toml`, which risks two divergent dependency lists.
- **Decision:** Adopt `pyproject.toml` as the only dependency source during Sprint 1, unless the user requires a `requirements.txt` for a specific deployment workflow.
- **Alternatives:** Keep both and generate one from the other; keep `requirements.txt` only.
- **Rationale:** Two manually maintained dependency lists are a known source of drift.
- **Consequences:** `ARCHITECTURE.md` section 4 should be updated during Sprint 1 if this is confirmed.
- **Revisit conditions:** A deployment target that requires `requirements.txt`.

## ADR-010 — Installing provider SDKs with `pip --target` into the venv

- **Status:** Accepted
- **Context:** A plain `pip install` fails on this machine with a PEP 668 externally-managed-environment error, and the venv cannot bootstrap pip because `ensurepip` is unavailable (ADR-009).
- **Decision:** Install with `python3 -m pip install --target .venv/lib/python3.14/site-packages <pkg>`. This installs into the environment's own site-packages, requires no `--break-system-packages`, and leaves system and user site-packages untouched.
- **Alternatives:** `pip --user --break-system-packages` (would modify `~/.local`, shared with unrelated tools); installing `python3.14-venv` system-wide (requires sudo).
- **Rationale:** Contained to the project, no system override flag, and the `--system-site-packages` venv sees it immediately.
- **Consequences:** Packages installed this way are invisible to `pip freeze`/`pip list` inside the venv (pip itself is absent there), so the installed set is recorded in `pyproject.toml` and `docs/STATUS.md` instead.
- **Revisit conditions:** Re-evaluate if an isolated, fully reproducible environment becomes required.

## ADR-011 — Search response field names are mapped tolerantly

- **Status:** Accepted
- **Context:** The installed `tavily-python` 0.8.5 SDK returns the raw API JSON (`response.json()` passed through with `setdefault("results", [])`), so the SDK itself documents no result-item schema. Searching the SDK package for `published_date` returns no matches at all.
- **Decision:** The adapter reads `title`, `url`, `snippet`, `published_date`, and `score` defensively with type-checked `.get()` calls, treating every field except `url` as optional, and drops any item without a usable HTTP(S) URL.
- **Alternatives:** Assert a fixed schema and fail loudly on any deviation; fetch a live response first to confirm the exact field names.
- **Rationale:** A live call was not possible (no `TAVILY_API_KEY` on this machine), and guessing schema strictness would turn an unverified assumption into a hard failure path.
- **Consequences:** The adapter is resilient to missing or wrongly-typed fields, but `published_date` in particular is **unverified** until a live response is inspected. Normalization behaviour is fully covered by mocked tests.
- **Revisit conditions:** The first successful live smoke test in Sprint 2/6 should confirm the actual response schema and, if it differs, tighten the mapping.

## ADR-012 — DNS-rebinding defence by pinning the connection to a validated IP

- **Status:** Accepted and verified
- **Context:** `SECURITY.md` requires that "the connection strategy ensures the validated address is the one reached", and warns that if robust SSRF controls cannot be guaranteed the fetch feature should be narrowed or deferred. Validating DNS and then connecting by hostname leaves a time-of-check/time-of-use gap in which the DNS answer can change.
- **Decision:** Resolve and validate the destination first, then connect to that numeric address while binding SNI and certificate verification to the original hostname.
  - `requests` is used only as a thin client. The request URL is rewritten to the validated IP (`Destination.pinned_url`) and an explicit `Host` header carries the real hostname.
  - A `requests.adapters.HTTPAdapter` subclass reinitialises the urllib3 pool manager with `server_hostname` and `assert_hostname` set to the hostname.
  - Redirects are followed manually, one hop at a time, and every hop is re-validated from scratch by the same policy.
- **Verification (actually performed):**
  - urllib3 source inspected: `_keys_iter` carries both kwargs; `HTTPSConnectionPool` forwards `server_hostname` in `conn_kw`; plain `HTTPConnectionPool` drops it, so `HTTPConnection(server_hostname=...)` would `TypeError` — confirmed by direct instantiation, which is why HTTP pools are unaffected.
  - 9 transport tests against a local server (pinned connect, `Host` header, no `Authorization`, mid-stream byte cap).
  - Two live HTTPS fetches, real DNS, real certificates: `https://example.com/` → HTTP 200, title `Example Domain`; `https://www.wikipedia.org/` → HTTP 200, title `Wikipedia`. Both connected to a pinned address while `Host`/SNI/cert checks used the hostname.
- **Alternatives:** Validate-then-connect by hostname (leaves the rebinding gap); run a local DNS proxy; defer the feature as `SECURITY.md` permits.
- **Consequences:** Only `http`/`https` on ports 80/443 are reachable, because ports are restricted to keep the surface narrow. No proxies, cookies, or credentials are ever forwarded.
- **Revisit conditions:** If redirects, proxies, or alternate ports are ever needed, the pinning path must be re-reviewed.

## ADR-013 — No script execution and naive text extraction in the MVP

- **Status:** Accepted
- **Context:** PRD FR-04 requires extracting readable text "without executing scripts", and `SECURITY.md` treats retrieved content as untrusted.
- **Decision:** Parse HTML with the standard library's `html.parser.HTMLParser` only. `script`, `style`, `noscript`, `template`, `svg`, and `canvas` content is skipped by tag depth and discarded rather than surfaced as evidence.
- **Alternatives:** A headless browser (would execute page code, out of scope per charter); a third-party HTML-to-text library (a new dependency for no security gain).
- **Rationale:** The standard-library parser cannot execute anything, so "no page code executes" holds by construction rather than by policy.
- **Consequences:** JavaScript-rendered content is not visible, and extraction quality is basic. This is disclosed as a known limitation rather than hidden. The parser also collects only the first `<title>` and caps output at 100,000 characters.
- **Revisit conditions:** If extraction quality becomes a product requirement, revisit with an explicit dependency decision.

## ADR-014 — Stateless model turns with explicit replay, hard-bounded loop

- **Status:** Accepted
- **Context:** US-301/302/303 require adaptive tool use that is bounded and auditable. Providers can keep conversation state server-side (`previous_response_id`), but that makes runs non-inspectable and untestable offline.
- **Decision:** The model adapter is *stateless*: every turn sends the question plus every prior tool observation replayed as explicit `function_call`/`function_call_output` item pairs. The loop is bounded twice — `max_iterations` (default 8) and a wall-clock `ATLAS_DEADLINE_SECONDS` (default 120) — and which limit stopped the run is reported as an explicit `TerminationReason` (`completed`, `max_iterations`, `deadline_exceeded`, `model_error`, `no_output`).
- **Status honesty:** `ResearchState.finish()` only reports `completed` when a real final answer exists and no errors were recorded; iteration/deadline stops are `partial`, and a first-turn provider failure is `failed`. Tool results are truncated to 1,200 characters when replayed.
- **Untrusted model output:** tool calls are dispatched only through the local allowlist registry (`ToolRegistry`), which validates arguments against Pydantic models and suppresses identical calls after 3 executions. Refusals are classified (`unknown_tool`, `duplicate`, `invalid_arguments`) and counted in run state.
- **Verification:** 23 fake-model loop tests, including `test_later_action_depends_on_earlier_observation` (the exit-gate requirement), iteration exhaustion, deadline stop, provider failure, and duplicate suppression. **No live model call was made — no API key exists in this environment.**
- **Alternatives:** provider-side conversation state (rejected: opaque, untestable offline); unbounded "keep going until done" loop (rejected: PRD requires bounded execution).
- **Revisit conditions:** If a live run shows the model needs more than 8 turns or 120s for representative questions, revisit the defaults with measured evidence.

## ADR-015 — Reports are built from validated citations, never typed

- **Status:** Accepted
- **Context:** US-402 requires that all citations resolve to registered sources, unknown IDs are rejected, and no fabricated evidence is rendered. PRD FR-10 makes citation validation a hard requirement.
- **Decision:** A `ReportBuilder` assembles reports. `add_finding()` resolves every cited ID against the run's `SourceRegistry` and **raises `CitationValidationError`** for unknown IDs before anything is rendered. Any quoted excerpt must be verbatim text stored on the cited source (normalised whitespace, case-insensitive match); otherwise it is treated as fabrication and rejected. Direct findings without an explicit excerpt automatically receive a verbatim excerpt from the first cited source that has stored evidence, and a direct finding citing only evidence-free sources is refused.
- **Uncertainty is explicit, structural, not prose:** snippet-only sources, partial/failed run status, refused tool calls, suppressed duplicates, and recorded run errors are all appended as report limitations. A run whose status is not `completed` always carries a limitation saying the answer may be incomplete.
- **Evidence tiers (US-403):** `Evidence.kind` distinguishes `page_text` (fetched) from `search_snippet` (never the page itself); `Finding.kind` distinguishes `direct` from `interpretation`, and the Markdown labels each finding accordingly.
- **CLI (US-502):** `--output PATH` writes the Markdown report. Exit codes: 0 completed, 2 usage, 3 invalid request, 4 configuration, 5 research executed but incomplete. Live mode is the only place providers are constructed; tests inject a fake runner so no paid call is possible.
- **Verification:** 29 report tests, 12 pipeline tests, 12 CLI-report tests, all offline.
- **Alternatives:** asking the model to emit citations unchecked (rejected: fabrication risk); rendering reports with free-text sources (rejected: not traceable).
- **Consequences:** reports can only cite what the run actually registered; a run that registered nothing produces an explicitly evidence-free report rather than an impressive-looking one.
- **Revisit conditions:** If automatic conflict detection between sources becomes a requirement, revisit with an explicit design for contradiction handling.

## ADR-016 — Live tests are marked, deselected, and skip honestly

- **Status:** Accepted
- **Context:** US-503 requires that the default test run needs no credentials and makes no paid calls, while still keeping live coverage runnable for when credentials exist.
- **Decision:** `pyproject.toml` sets `addopts = "-m 'not live'"`, so the default run deselects every live test. `tests/test_live.py` is entirely marked `live` and each test carries a `skipif` on its specific credential requirement, so `pytest -m live` without keys skips (never fails, never fakes). Live tests assert only *shape and bounds* — a turn is a string or tool calls; usage is reported or absent, never fabricated; a live run's citations must still resolve.
- **Evaluation:** `docs/EVALUATION.md` records the offline benchmark's measured outcomes and explicitly refuses to publish accuracy/quality/cost figures until a real live evaluation has been run (PRD §10).
- **Revisit conditions:** When credentials become available, run `pytest -m live` first, then consider a real evaluation with the documented metrics.

## ADR-017 — Sprint 7 scope: only US-703; the other optional stories are declined

- **Status:** Accepted
- **Context:** `docs/SPRINTS.md` gates Sprint 7 on explicit user-approved scope. The user delegated the choice ("do all further tasks according to your own recommended way"), so this ADR records the chosen scope and the reasoning, per the backlog rule that stories need acceptance criteria before scheduling.
- **Decision:** Implement **US-703 (user-configurable research depth)** only:
  - CLI flags `--max-iterations N`, `--max-results N`, `--deadline SECONDS` override the environment configuration for one run.
  - The override is applied by re-validating the whole `Settings` object, so the accepted ranges are defined in exactly one place and cannot drift from env-based configuration.
  - Effective values are printed with run metadata so a run can be reproduced.
  - A bad value is a usage error (exit 2); no research runs.
  - Acceptance criteria and verification approach were written into `docs/ROADMAP.md` **before** implementation, as the backlog rules require.
- **Declined, with reasons:**
  - **US-701 (web UI):** requires a web stack and hosting; outside the CLI charter, and no verified need exists (nothing has ever run live).
  - **US-702 (report history):** partially satisfied already — `atlas -o PATH` writes a report wherever the user wants, which covers "download". The history/retention half collides with US-705's privacy requirement and is declined.
  - **US-704 (deployment and monitoring):** infrastructure work with no live environment to deploy to or monitor; it would be unverifiable.
  - **US-705 (persistent research history):** the roadmap itself gates it on a privacy and retention design that does not exist.
- **Consequences:** the application remains a local CLI with no persistence and no new dependencies.
- **Revisit conditions:** if a real deployment target or a retention policy ever exists, US-702/704/705 can be rescheduled with proper criteria.

## ADR-018 — Provider portability: Exa search provider and OpenAI-compatible base URL

- **Status:** Accepted (US-706)
- **Context:** The user supplied working credentials for **Exa** (search), **Groq**, and **OpenRouter** (model) — none of which are Tavily or OpenAI. Live mode required exactly `OPENAI_API_KEY` + `TAVILY_API_KEY`, so valid keys could not run the application. Acceptance criteria were written into `docs/ROADMAP.md` under US-706 before implementation.
- **Decision:**
  - Live mode now accepts **one of** `TAVILY_API_KEY` or `EXA_API_KEY` for search; neither set is still a configuration error that names both variables.
  - `ExaSearchProvider` implements the existing `SearchProvider` protocol with the same bounded validation, `SearchResult` normalization, and API-key redaction as the Tavily provider. It posts to `https://api.exa.ai/search` with the minimal request shape (`query`, `numResults`, `contents.highlights`) through an injected transport — no new runtime dependency, all tests offline.
  - `OPENAI_BASE_URL` (optional, must be http(s)) points the model adapter at any OpenAI-compatible endpoint; when unset, behaviour is unchanged. The adapter now passes `api_key`/`base_url` from `Settings` when present, falling back to the SDK's environment lookup.
  - Provider selection is deterministic: **Tavily when configured, otherwise Exa**.
  - `ATLAS_MODEL` is still never defaulted; `EXA_API_KEY` and `OPENAI_BASE_URL` join the set of `SecretStr`-protected / validated settings.
- **Why not Groq:** Groq is OpenAI-compatible but serves only `/chat/completions`; Atlas's adapter speaks the **Responses API** (ADR-014). Supporting Groq would require a second model adapter — declined as unnecessary since OpenRouter's Responses endpoint works. The Groq key is stored locally and unused.
- **Verification (executed, not assumed):** all three keys validated with real calls; `pytest -m live` → **4 passed** (model, usage, search+fetch, end-to-end research run) using OpenRouter + Exa; a real CLI run produced a **completed** report (`live_report.md`, exit 0) with resolving citations and honest evidence tiers.
- **Consequences:** live mode is runnable in this environment without paid OpenAI/Tavily accounts. Answer *quality* remains unmeasured — the offline benchmark still refuses accuracy claims (PRD §10).
- **Revisit conditions:** if a second *chat-completions-only* provider must be supported, add a distinct adapter rather than bending the Responses-based one.

## ADR-019 — Research quality evaluation: offline-first, review-gated accuracy

- **Status:** Accepted (Sprint 8, US-801 … US-808)
- **Context:** Sprints 0–7b verified structure, bounds, and honesty, but *answer quality* was unmeasured — the gap recorded in `docs/STATUS.md`. The brief required a reproducible evaluation that never invents numbers. Acceptance criteria were written into `docs/ROADMAP.md` before implementation.
- **Decision:**
  - **One dataset, two runners.** `evaluation_dataset/cases.json` (24 cases, 8 required categories, fixtures included) is version-controlled *outside* `src/`. `python -m atlas.evalrun` runs it offline by default; `--live` is the only way to reach real providers.
  - **Offline runs ignore the environment.** `Settings.from_env({})` plus per-case fixture providers make the offline path credential-free, network-free, and reproducible; a test blocks `socket.socket.connect` to prove no external call happens.
  - **Three-level citation verdicts.** `resolves` and `excerpt_matches_evidence` are deterministic; `supports_claim` is `needs_review` until a human records it — a resolving URL never implies support.
  - **Reuse over duplication.** `evaluate()` (Sprint 6) backs the `status_honesty` check; `ReportBuilder`'s excerpt rule was extracted into public `excerpt_support_kind()` so builder and evaluator share one implementation; citation resolution stays in `SourceRegistry.resolve`.
  - **Accuracy is review-gated in code.** A `CaseResult` with `factual_accuracy: pass` and no `ReviewRecord` fails validation, so an unreviewed claim can never be represented as verified.
  - **Metrics show their working.** Every metric reports numerator, denominator, and unknown count; no valid observations → `value: null` (`unavailable`), never `0`. Cost is always unavailable because no pricing table exists.
  - **Live is opt-in, bounded, single-attempt.** The refusal check runs before any provider is constructed; existing iteration/result/deadline bounds apply; there is no automatic retry; recorded strings are redacted with the configured credentials.
- **Why not an LLM judge:** a judge model would add a paid dependency, its own failure modes, and an accuracy number that is not independently verifiable. Claim support stays `needs_review` instead.
- **Why the dataset lives outside `src/`:** evaluation fixtures are test data, not application code; keeping them separate lets the schema be validated without shipping fixtures with the package.
- **Verification (executed, not assumed):** `pytest` → **585 passed, 4 deselected**; `ruff check .` and `ruff format --check .` clean. Offline baseline over all 24 cases: **0 deterministic check failures**, 1 scripted provider failure (by design), all 24 accuracy fields `needs_review`. The user-approved 3-case live smoke ran against OpenRouter + Exa: 2/3 completed, 21/21 citations resolved, 0 provider failures, 0 reviews recorded. Both runs are recorded in `docs/EVALUATION.md` and committed under `evaluation_results/`.
- **Consequences:** answer quality is now *measured where it can be measured honestly* and explicitly marked unverified where it cannot. Producing an accuracy percentage requires a human review pass, which has not been done for any case.
- **Revisit conditions:** if a review pass is ever performed, record it in a reviews file and re-run `evalrun summarize`; if reliable pricing is configured, replace the always-unavailable cost metric with a computed one.

## Open decisions from Sprint 0

Resolved during Sprint 1 — see the "Sprint 0 decisions resolved in Sprint 1" section below.

1. ~~**Maximum question length.**~~ Resolved: `MAX_QUESTION_LENGTH = 4000` characters in `src/atlas/models.py`, documented in `README.md`.
2. ~~**Git repository absent.**~~ Resolved: repository initialised during Sprint 1. No commit was made, since commits require separate approval.
3. ~~**No virtual environment.**~~ Resolved: `.venv` created. See ADR-009 for the non-standard flags required on this machine.
4. **Python version floor.** Partially resolved: `tavily-python` 0.8.5 imports and its contract tests pass on Python 3.14.4, so search-side compatibility is verified. Still open for `openai`, which is not installed; that must be checked before Sprint 4 pins dependencies.
5. ~~**Packaging source.**~~ Resolved as ADR-008 (accepted): `pyproject.toml` is the sole dependency source; no `requirements.txt` was created.

## ADR-009 — Non-isolated virtual environment on this machine

- **Status:** Accepted as an interim measure
- **Context:** `python3 -m venv .venv` failed with `ensurepip is not available`, so `pip` cannot bootstrap inside a fresh venv and `pip install -e .` is unavailable. All Sprint 1 dependencies were already present in the system interpreter.
- **Decision:** Create the environment as `python3 -m venv --without-pip --system-site-packages .venv`, giving a project-local interpreter with zero package installations.
- **Alternatives:** Install the `python3.14-venv` system package; install dependencies into an isolated environment.
- **Rationale:** Sprint 1 needs no new dependencies, and installing packages or system packages requires explicit approval that has not been given. This satisfies US-503 (tests run with no credentials and no paid calls) immediately.
- **Consequences:** The environment is not fully isolated, so a package installed elsewhere on the system would be visible to Atlas. Reproducibility of the setup is therefore weaker than an isolated environment. Package versions are pinned only by lower bounds in `pyproject.toml`.
- **Revisit conditions:** Approval to install packages, or the availability of `ensurepip`. Sprint 2 will need `openai` and `tavily` installed regardless, so this decision must be revisited then.
