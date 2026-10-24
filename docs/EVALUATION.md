# Atlas — Evaluation Results

> Per `docs/PRD.md` §10: this document *records* measured outcomes. It does not
> promise accuracy, quality, or cost figures, because no live evaluation has
> been run.

## What was evaluated

An **offline benchmark** of three representative questions, executed
deterministically by `atlas.evaluation.run_offline_benchmark()` against
scripted providers (`src/atlas/evaluation.py`). It measures the *pipeline* —
agent loop, tool registry, source registration, citation validation, report
building — not any real model's research quality.

**Live evaluation was not run.** No `OPENAI_API_KEY` and no `TAVILY_API_KEY`
exist in this environment, so every claim below comes from fixtures. Live
tests exist in `tests/test_live.py`, are marked `live`, and are deselected by
default (`addopts = "-m 'not live'"`); they currently skip for missing
credentials.

## Documented criteria (applied to every question)

From `docs/ROADMAP.md` verification lines for US-103, US-402, US-603:

1. the run reaches an explicit terminal status;
2. partial work is never labelled `completed`;
3. every rendered citation resolves to a registered source;
4. tool execution stays inside the configured iteration bound (8 by default).

## Measured results (run on 2026-10-24)

| # | Question | Status | Termination | Tool calls | Findings | Sources | Citations valid | Meets criteria |
|---|---|---|---|---|---|---|---|---|
| 1 | What is the Atlas research agent? | `completed` | `completed` | 1 | 2 | 2 | yes | **yes** |
| 2 | What is a bounded agent loop? | `partial` | `completed` | 1 | 0 | 0 | yes | **yes** |
| 3 | Tell me about Atlas in detail. | `partial` | `max_iterations` | 8 | 2 | 2 | yes | **yes** |

3/3 questions met all four criteria. The run is reproducible:
`run_offline_benchmark()` is deterministic (asserted by
`test_offline_benchmark_is_deterministic`).

## How to read these outcomes

**Question 1 — normal path.** Search returned results, sources were
registered, the model answered on turn 2. 2 findings (one per registered
source with evidence), all citations resolve.

**Question 2 — search provider failure.** The search provider raised
`SearchProviderError("quota exceeded")`. The run was **not** silently marked
clean: the tool error was recorded, the run was reported `partial` even though
the loop stopped because the model produced an answer (`reason=completed`,
`status=partial` — reason describes why the loop stopped, status describes
outcome quality), and the failure is disclosed as a report limitation. Zero
findings, because no evidence was ever registered. This is the honesty
property US-103/US-402 exist to guarantee.

**Question 3 — over-calling model.** The scripted model requested 20 search
calls; the loop stopped it at the iteration bound (8). Status `partial`,
termination `max_iterations`, and the report carries a limitation saying the
answer may be incomplete. The loop cannot run forever.

## Metrics not recorded, and why

Per PRD §10, these are *not* reported because measuring them requires live
runs with real providers and human rating:

- research run **completion rate** on real questions (fixtures are scripted);
- **citation validity rate** against real web sources (fixtures register
  what the fixture says);
- human-rated **evidence support**;
- **useful-source proportion** (needs human judgement);
- median **runtime against real providers** and provider failure rates;
- **token/API usage**: the fixtures report no usage, and Atlas prints
  `token usage: unavailable (provider did not report usage)` rather than
  estimating. Question 1's run recorded `token_usage_reported=False`.

## Running the benchmark yourself

```bash
PYTHONPATH=src .venv/bin/python -c "from atlas.evaluation import run_offline_benchmark; print([r.metrics.as_dict() for r in run_offline_benchmark()])"
```

Running the **live** tests (requires real credentials, costs money):

```bash
ATLAS_MODE=live OPENAI_API_KEY=... TAVILY_API_KEY=... ATLAS_MODEL=... \
  .venv/bin/python -m pytest -m live
```
