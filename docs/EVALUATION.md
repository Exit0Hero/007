# Atlas — Evaluation Results

> Per `docs/PRD.md` §10 this document *records* measured outcomes. Every
> number below was produced by a command that was actually executed; nothing
> here is estimated, and no accuracy figure exists without a recorded human
> review.

Sprint 8 (US-801 … US-808) added a reproducible, evidence-based evaluation
system for **answer quality**. It runs in two modes: an **offline fixture
evaluation** (no credentials, no network, deterministic) and an **opt-in live
evaluation** against the configured providers.

---

## 1. Running the offline evaluation

```bash
python -m agent007.evalrun run                 # all 24 cases
python -m agent007.evalrun run --smoke         # three-case smoke subset
python -m agent007.evalrun run --case EV-GEN-001 --case EV-SCI-001
python -m agent007.evalrun list                # show case IDs, categories, difficulty
```

* Requires **no credentials**: offline runs build `Settings.from_env({})`, so
  the ambient environment is deliberately ignored.
* Requires **no network**: each case supplies its own fixture providers (a
  scripted model and a scripted search corpus) — verified by a test that
  patches `socket.socket.connect` to fail.
* Writes two artifacts to `--out` (default `evaluation_results/<run_id>/`):

  | File | Purpose |
  |---|---|
  | `eval_results.json` | machine-readable result: every case, check, verdict, metric, and limitation |
  | `eval_summary.md` | human-readable summary: metric table, per-case detail, reviewer workflow |

### Exit codes

| Code | Meaning |
|---|---|
| `0` | every deterministic check passed and no provider failure was recorded |
| `2` | at least one case recorded a quality failure or a provider failure |
| `4` | dataset error (missing, malformed, empty, duplicate IDs, unknown case ID) |
| `5` | configuration error (for example `--live` without a configured live run) |

Re-running the same dataset reproduces the same checks and metrics: the
offline path is deterministic (covered by
`tests/test_eval_quality.py::test_offline_case_evaluation_is_deterministic`).

## 2. Selecting a small live subset

Live execution requires **explicit opt-in** and makes real, billable API
calls. Always smoke-test first:

```bash
python -m agent007.evalrun run --live --smoke            # first case of 3 categories
python -m agent007.evalrun run --live --case EV-GEN-001  # a single case
python -m agent007.evalrun run --live                    # the whole dataset (24 cases)
```

Configuration (names only — values are never printed or written to artifacts):

```bash
export ATLAS_MODE=live
export ATLAS_MODEL=<your model id>
export OPENAI_BASE_URL=https://openrouter.ai/api/v1   # optional, OpenAI-compatible endpoint
export OPENAI_API_KEY=<key>                            # or the provider's key
export EXA_API_KEY=<key>                               # exactly one search key is required
```

Guarantees enforced in code (`src/atlas/evallive.py`):

* the opt-in check runs **before any provider is constructed**, so a refusal
  performs no work and contacts nothing;
* existing bounds apply unchanged: `ATLAS_MAX_ITERATIONS`, `ATLAS_MAX_RESULTS`,
  `ATLAS_DEADLINE_SECONDS` (verified in the recorded run below);
* **one attempt per case — no automatic retry** of failed paid calls;
* provider/network failures are recorded as `provider_failure: true` with
  `completion_status: null`, never as a quality pass;
* every recorded string passes through `redact_secrets()` with the configured
  credentials, so no key can reach a log, exception, or artifact;
* a case that merely completes without raising is **not** thereby `pass`: the
  factual-accuracy and completeness fields stay `needs_review`.

## 3. Reviewing factual accuracy and citation support

Citation support is judged at three separate levels
(`src/atlas/quality.py`, US-803):

| Level | Question | How it is decided |
|---|---|---|
| `resolves` | does the cited ID exist in this run's source registry? | deterministic (`SourceRegistry.resolve`) |
| `excerpt_matches_evidence` | is the quoted excerpt verbatim in the stored evidence of that source? | deterministic (`excerpt_support_kind`, the same rule the report builder enforces) |
| `supports_claim` | does the source actually support the claim? | **always `needs_review`** until a human records a judgment |

A resolvable URL never implies support. To record a review:

1. Open a case's section in `eval_summary.md` and its report.
2. Read the case's rubric (`evaluation_dataset/cases.json`) and check each
   criterion against the report and its `## Sources` list.
3. Write a reviews file:

```json
{
  "reviews": [
    {
      "case_id": "EV-GEN-001",
      "factual_accuracy": "pass",
      "completeness_relevance": "pass",
      "supported_source_ids": ["S1", "S2"],
      "unsupported_source_ids": [],
      "reviewed_claims": 3,
      "unsupported_claims": 0,
      "reviewer": "your-name",
      "reviewed_at": "2026-10-25",
      "notes": "checked the boiling point against the cited page"
    }
  ]
}
```

4. Re-score without re-running anything:

```bash
python -m agent007.evalrun summarize \
  --results evaluation_results/live_smoke/eval_results.json \
  --reviews reviews.json
```

Statuses are exactly `pass`, `fail`, `unknown`, `needs_review`. Omitting a
field leaves it `needs_review`; a `pass` for a judgement field is rejected
without a matching `ReviewRecord`, so an unreviewed claim can never be
represented as verified.

## 4. Metric reference

Every metric carries `numerator`, `denominator`, `unknown` (cases that could
not be counted), and `value`. **A metric with no valid observations reports
`value: null` (`unavailable`), never `0`.**

| Metric | Numerator | Denominator | Unknown counts | What it does *not* mean |
|---|---|---|---|---|
| `completion_rate` | runs that ended `completed` | runs that produced a report | cases that never ran | not correctness |
| `citation_resolution_rate` | citation IDs that resolve | citation IDs rendered | cases with no checks | not that the source is trustworthy |
| `excerpt_verification_rate` | excerpts found verbatim in stored evidence | excerpts quoted | cases with no checks | not that the source supports the claim |
| `unsupported_claim_rate` | claims a reviewer judged unsupported | claims actually reviewed | cases without claim-level review | unavailable until a review exists |
| `factual_accuracy` | cases reviewed as `pass` | cases with a recorded accuracy review | unreviewed cases | unavailable (not `0`) until reviewed |
| `completeness_relevance` | cases reviewed as `pass` | cases with a recorded completeness review | unreviewed cases | unavailable until reviewed |
| `provider_failure_rate` | runs with a model/search/network failure | all cases | — | a provider failure is *not* a quality failure |
| `token_usage_average` / `_median` | total tokens reported | runs whose provider reported usage | runs with no usage data | unavailable when the provider reports nothing; never estimated |
| `estimated_cost` | — | — | all cases | **always unavailable**: no reliable per-model pricing is configured; cost is never estimated |

## 5. What this evaluator cannot establish

* **Structural checks passing does not mean the answer is correct.** The
  offline checks verify structure, citation resolution, excerpt fidelity,
  disclosure, status honesty, and case conditions — never truth.
* **Excerpt verification is not claim support.** It proves a quote exists in
  stored evidence, not that the source is authoritative or that it says what
  the claim says.
* **Offline fixture runs say nothing about a real model's research quality.**
  Their providers are scripted fakes; they measure the pipeline.
* **Required/prohibited claim matching is literal** (case-insensitive
  substring). A correct paraphrase counts as missing, and a phrase that also
  appears in a source snippet counts as prohibited. This is a blunt
  instrument, deliberately reported as `case_conditions` rather than as
  accuracy.
* **No LLM judge is used.** Claim support, accuracy, and completeness stay
  `needs_review` until a human records them.
* **Cost is never inferred**, because no pricing table is configured.

## 6. Recorded results

### 6.1 Offline baseline — 24 cases (executed 2026-10-25)

```bash
python -m agent007.evalrun run --out evaluation_results/offline_baseline
# exit 2 (EV-INC-003 is scripted to fail at the provider by design)
```

| Metric | Value | Working |
|---|---|---|
| Case completion rate | 0.92 | 22 / 24 (EV-PRG-003 and EV-INC-003 are partial by design) |
| Citation resolution rate | 1.00 | 46 / 46 |
| Evidence-excerpt verification rate | 1.00 | 46 / 46 |
| Unsupported-claim rate | unavailable | 0 / 0, unknown = 24 |
| Factual accuracy | unavailable | 0 / 0, unknown = 24 |
| Completeness and relevance | unavailable | 0 / 0, unknown = 24 |
| Provider failure rate | 0.04 | 1 / 24 (EV-INC-003's fixture raises `SearchProviderError`) |
| Average / median token usage | unavailable | 0 runs reported usage (fixtures never fabricate usage) |
| Estimated cost | unavailable | never estimated |

* **Deterministic check failures: 0** across all 24 cases.
* Factual accuracy and completeness are `needs_review` for **all 24** cases —
  no review has been recorded for this dataset yet.
* Artifacts: `evaluation_results/offline_baseline/eval_results.json` and
  `eval_summary.md` (committed).

### 6.2 Live smoke — 3 cases (executed 2026-10-25, user-approved)

```bash
python -m agent007.evalrun run --live --smoke --out evaluation_results/live_smoke
# model nvidia/nemotron-3.5-lightning:free via OPENAI_BASE_URL, search: exa
# bounds applied: max_iterations=8, max_results=5, deadline=120s
```

| Metric | Value | Working |
|---|---|---|
| Case completion rate | 0.67 | 2 / 3 |
| Citation resolution rate | 1.00 | 21 / 21 |
| Evidence-excerpt verification rate | 1.00 | 21 / 21 |
| Provider failure rate | 0.00 | 0 / 3 |
| Average token usage | 1853.67 | 5561 / 3 runs |
| Median token usage | 2170.00 | 5561 / 3 runs |
| Factual accuracy / completeness | unavailable | 0 / 0, unknown = 3 (no review recorded) |
| Estimated cost | unavailable | no pricing data |

Per case:

| Case | Status | Citations | Excerpts | Deterministic failures |
|---|---|---|---|---|
| EV-GEN-001 | completed | pass | pass | `case_conditions`: required literal phrase `100 degrees Celsius` not found in the rendered report |
| EV-SCI-001 | completed | pass | pass | none |
| EV-PRG-001 | partial (`max_iterations`, 4 duplicate calls suppressed) | pass | pass | `case_conditions`: status `partial` not in the case's allowed `completed` |

Honest reading: **2 quality failures, 0 provider failures, 0 recorded
reviews.** Two of three runs hit their deterministic conditions; the third
passed every structural check. None of this is a factual-accuracy result —
that remains `needs_review` for all three cases. Artifacts:
`evaluation_results/live_smoke/` (committed; secret-scanned: no key-like
strings).

## 7. Avoiding secret exposure and unintended cost

* Offline is the default. `--live` is the only flag that makes a network call,
  and it refuses (exit 5) without explicit configuration.
* Keys are read from the environment at run time; they are never written into
  fixtures, source files, results, or summaries, and every recorded string is
  redacted with the configured credentials.
* `.env` stays git-ignored; `git log -p` has been scanned for key-like
  patterns before every commit.
* Each live case costs one bounded research run (≤ 8 model turns, ≤ 5 search
  results, ≤ 120 s by default) with **no retry**, so a failing provider costs
  one attempt, not a loop.
* Start with `--live --case <id>`, then `--live --smoke`, before considering
  a full live run.

## 8. The earlier offline benchmark (Sprint 6, US-504)

`atlas.evaluation.run_offline_benchmark()` still runs three representative
questions against scripted providers and checks the four documented pipeline
criteria (terminal status, no over-labelled completion, resolving citations,
bounds respected). It measures the *pipeline* only. Its rules were reused —
not duplicated — by the Sprint 8 checks: `evaluate()` backs the
`status_honesty` check and `excerpt_support_kind()` backs `excerpt_support`.
