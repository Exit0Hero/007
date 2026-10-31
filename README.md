# Atlas — OpenCode Project Starter Kit

Atlas is a single-agent Python research assistant that researches a question using approved web tools, adapts its next actions to retrieved evidence, and produces a Markdown report with traceable source references.

This starter kit gives OpenCode a persistent engineering charter, product requirements, architecture, backlog, sprint gates, security/testing policies, and reusable prompts.

## Start here

1. Extract this folder into your existing Atlas project directory, or use this folder as the project root.
2. Inspect any existing files before replacing them. Preserve useful work.
3. Open the project root in OpenCode.
4. Read `AGENTS.md`.
5. Paste `prompts/SPRINT_0.md` into OpenCode.
6. Review Sprint 0's documentation and status output before approving Sprint 1.
7. For later sprints, use `prompts/SPRINT_EXECUTION.md` and explicitly approve the sprint to execute.

## Target stack

- Python 3.11+
- OpenAI Python SDK / Responses API with function calling (any OpenAI-compatible endpoint via `OPENAI_BASE_URL`, e.g. OpenRouter)
- Web search via the Tavily Python SDK **or** Exa's HTTP API (no extra dependency)
- Pydantic for validated data and configuration
- python-dotenv for local configuration
- pytest for tests
- Ruff for linting and formatting

Verify current provider APIs, SDK versions, model availability, and pricing before relying on them. OpenCode's own model-provider credentials are separate from credentials used by the Atlas Python application.

## Local setup and usage

Verified against this repository on Python 3.14.4.

### Environment setup

```bash
cd atlas_opencode_starter
python3 -m venv --without-pip --system-site-packages .venv
source .venv/bin/activate
```

`--without-pip` is used because `ensurepip` is unavailable on this machine, and
`--system-site-packages` lets the environment reuse the already-installed
`pydantic`, `python-dotenv`, `pytest`, and `ruff`. This means Sprint 1 requires
**no dependency installation**. A fully isolated environment would additionally
require `pip install -e ".[dev]"`; that has not been performed.

### Run the CLI

```bash
PYTHONPATH=src python -m agent007.main "What is retrieval-augmented generation?"
PYTHONPATH=src python -m agent007.main "..." --output report.md
```

`src` must be on the path because the package has not been installed editable.

Offline mode (the default) validates the request and configuration only; it
performs no research and contacts no provider. With `ATLAS_MODE=live`,
`OPENAI_API_KEY`, `ATLAS_MODEL`, and **one** of `TAVILY_API_KEY` or
`EXA_API_KEY` set, the CLI runs the bounded agent loop, writes the
evidence-grounded Markdown report to `--output PATH` (or stdout), and prints
run metadata (iterations, tool calls, and token usage when the provider
reported it — otherwise explicitly
unavailable).

### Research depth (per-run overrides)

```bash
PYTHONPATH=src python -m agent007.main "..." --max-iterations 3 --max-results 2 --deadline 30
```

Each flag overrides the environment configuration for that run only and is
validated against the same bounds as `Settings` (iterations 1–64, results
1–50, deadline > 0 and ≤ 3600s). The effective values are printed with the run
metadata so a run can be reproduced. An out-of-range or non-numeric value is a
usage error (exit 2) and no research runs.

Exit codes:

| Code | Meaning |
|---|---|
| 0 | Completed: request validated, or (live) research finished and a report was written |
| 2 | Usage error (missing/unknown argument, out-of-range depth option) |
| 3 | Invalid research request |
| 4 | Invalid or incomplete configuration |
| 5 | Research executed but did not complete (partial, failed, or provider error) |

### Research quality evaluation (Sprint 8)

```bash
# Offline: no credentials, no network, deterministic
PYTHONPATH=src python -m agent007.evalrun run                 # all 24 cases
PYTHONPATH=src python -m agent007.evalrun run --smoke         # three-case subset
PYTHONPATH=src python -m agent007.evalrun list                # case IDs and categories

# Opt-in live: makes real API calls, single attempt per case, no retry
PYTHONPATH=src python -m agent007.evalrun run --live --smoke

# Re-score saved results after recording a human review
PYTHONPATH=src python -m agent007.evalrun summarize --results <eval_results.json> --reviews <reviews.json>
```

Each run writes `eval_results.json` (machine-readable) and `eval_summary.md`
(human-readable) to `--out`. Exit codes: `0` all checks passed, `2` a quality
or provider failure was recorded, `4` dataset error, `5` configuration error
(for example `--live` without configuration). Factual accuracy and
completeness stay `needs_review` until a human review is recorded — see
`docs/EVALUATION.md` for the reviewer workflow, metric definitions, and the
recorded results.

### Test and lint

```bash
python -m pytest
ruff check .
ruff format --check .
```

These run offline and require no credentials. Live provider tests are marked
`live` and deselected by default; run them with `pytest -m live` and real
credentials (they skip cleanly when credentials are absent).

### Configuration

Copy `.env.example` to `.env` and fill in real values only if you intend to
enable `ATLAS_MODE=live`. `.env` is git-ignored. No model ID is provided as a
default; `ATLAS_MODEL` must be set explicitly before live mode will start.
`OPENAI_BASE_URL` is optional and points the model adapter at any
OpenAI-compatible endpoint (Tavily is preferred for search when both search
keys are present, otherwise Exa is used).

## Documentation map

- `AGENTS.md`: persistent coding-agent instructions
- `docs/MASTER_CHARTER.md`: full project charter and operating rules
- `docs/PRD.md`: product requirements and MVP boundaries
- `docs/ARCHITECTURE.md`: modules, data flow, and agent loop
- `docs/ROADMAP.md`: epics and prioritized user stories
- `docs/SPRINTS.md`: sprint goals, scope, and exit gates
- `docs/STATUS.md`: canonical current project state
- `docs/DECISIONS.md`: architecture decision log
- `docs/EVALUATION.md`: recorded evaluation results, metric definitions, reviewer workflow, and what cannot be measured
- `docs/TESTING.md`: test strategy and verification policy
- `docs/SECURITY.md`: threat model and security requirements
- `docs/DEFINITION_OF_DONE.md`: completion checklist
- `docs/CONTRIBUTING.md`: development workflow
- `prompts/SPRINT_0.md`: documentation/planning-only prompt
- `prompts/SPRINT_EXECUTION.md`: reusable prompt for an approved sprint
- `prompts/SPRINT_1.md`: foundation sprint prompt

## Important status note

`docs/STATUS.md` is the canonical current state and reflects only verified
work. As of Sprint 8, the repository carries a 24-case research-quality
dataset and an evaluation CLI: the offline evaluation runs with no
credentials, and a user-approved 3-case live smoke ran against OpenRouter
(model) and Exa (search), recording 21/21 resolving citations and zero
provider failures. Offline tests still do **not** prove answer quality —
factual accuracy and completeness are reported as `needs_review` for every
case until a human review is recorded (`docs/EVALUATION.md`).
