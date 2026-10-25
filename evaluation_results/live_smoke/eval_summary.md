# Evaluation summary

- **Run:** `eval-live-20261025T074851Z`
- **Generated:** 2026-10-25T07:48:51+00:00
- **Mode:** live
- **Dataset:** /home/akkushon-kamen/Desktop/007/atlas_opencode_starter_kit/atlas_opencode_starter/evaluation_dataset/cases.json (version 1.0.0)
- **Model:** nvidia/nemotron-3.5-lightning:free
- **Search provider:** exa

## Metrics

| Metric | Value | Numerator | Denominator | Unknown / unreviewed |
|---|---|---|---|---|
| Case completion rate | 0.67 | 2 | 3 | 0 |
| Citation resolution rate | 1.00 | 21 | 21 | 0 |
| Evidence-excerpt verification rate | 1.00 | 21 | 21 | 0 |
| Unsupported-claim rate (reviewed claims only) | unavailable | 0 | 0 | 3 |
| Factual accuracy (reviewed cases only) | unavailable | 0 | 0 | 3 |
| Completeness and relevance (reviewed cases only) | unavailable | 0 | 0 | 3 |
| Provider failure rate | 0.00 | 0 | 3 | 0 |
| Average token usage (reported runs) | 1853.67 | 5561 | 3 | 0 |
| Median token usage (reported runs) | 2170.00 | 5561 | 3 | 0 |
| Estimated cost (USD) | unavailable | None | None | 3 |

## Cases

| Case | Category | Status | Citations | Excerpts | Factual accuracy | Completeness | Provider failure |
|---|---|---|---|---|---|---|---|
| EV-GEN-001 | general_factual | completed | pass | pass | needs_review | needs_review | no |
| EV-SCI-001 | science_technology | completed | pass | pass | needs_review | needs_review | no |
| EV-PRG-001 | programming | partial | pass | pass | needs_review | needs_review | no |

## Per-case detail

### EV-GEN-001 — What is the boiling point of water at sea level in degrees Celsius?

- evaluated: 2026-10-25T07:48:09+00:00 (live)
- model: nvidia/nemotron-3.5-lightning:free; search: exa
- run: completed (stopped: completed)
- citation resolution: pass
- evidence excerpts: pass
- factual accuracy: needs_review
- completeness/relevance: needs_review
- failure: case_conditions: required claim missing: '100 degrees Celsius'
- limitation: factual accuracy and completeness/relevance require a recorded human review; deterministic checks cover structure, citations, and disclosure only
- limitation: one attempt per case; provider failures are recorded, not retried
- review: **not recorded** — see the reviewer workflow below

### EV-SCI-001 — What does the James Webb Space Telescope observe, and why is that wavelength range useful?

- evaluated: 2026-10-25T07:48:29+00:00 (live)
- model: nvidia/nemotron-3.5-lightning:free; search: exa
- run: completed (stopped: completed)
- citation resolution: pass
- evidence excerpts: pass
- factual accuracy: needs_review
- completeness/relevance: needs_review
- limitation: factual accuracy and completeness/relevance require a recorded human review; deterministic checks cover structure, citations, and disclosure only
- limitation: one attempt per case; provider failures are recorded, not retried
- review: **not recorded** — see the reviewer workflow below

### EV-PRG-001 — What is a list comprehension in Python and when should a plain loop be preferred?

- evaluated: 2026-10-25T07:48:51+00:00 (live)
- model: nvidia/nemotron-3.5-lightning:free; search: exa
- run: partial (stopped: max_iterations)
- citation resolution: pass
- evidence excerpts: pass
- factual accuracy: needs_review
- completeness/relevance: needs_review
- failure: case_conditions: status 'partial' not in allowed ['completed']
- limitation: factual accuracy and completeness/relevance require a recorded human review; deterministic checks cover structure, citations, and disclosure only
- limitation: one attempt per case; provider failures are recorded, not retried
- review: **not recorded** — see the reviewer workflow below

## Reviewer workflow

1. Open the generated report for a case and its `## Sources` list.
2. For each rubric criterion of that case (see the dataset), decide `pass`, `fail`, or `needs_review`.
3. Record judgments in a reviews file: `{"reviews": [{"case_id": "EV-GEN-001", "factual_accuracy": "pass", "completeness_relevance": "pass", "reviewer": "name", "reviewed_at": "YYYY-MM-DD"}]}`.
4. Re-run `python -m atlas.evalrun summarize --results <results.json> --reviews <reviews.json>` to recompute metrics.

Fields left out of a review stay `needs_review`; metrics only count cases that were actually reviewed. Nothing here becomes `pass` without a recorded judgment.

## What this evaluation cannot establish

- Structural checks passing does **not** mean the answer is factually correct; factual accuracy requires the recorded review above.
- Excerpt verification proves a quote exists in stored evidence, not that the source is trustworthy or that it supports the claim.
- Offline fixture runs measure the pipeline, never a real model's research quality.

## Run limitations

- deterministic checks cover structure, citations, excerpt support, disclosure, status honesty, and case conditions only
- factual accuracy and completeness/relevance stay needs_review until a human review is recorded; no accuracy figure is computed without one
- cost is always unavailable: no reliable per-model pricing is configured
