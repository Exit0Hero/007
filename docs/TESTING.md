# Atlas — Testing Strategy

## Principles

- Test behavior, not just implementation details.
- Keep unit tests deterministic.
- Mock paid/external APIs in normal test runs.
- Separate mocked tests from live integration tests.
- Do not weaken a test simply to obtain a green run.
- Record actual commands and outcomes.

## Test layers

### 1. Unit tests
Pure validation, URL policy helpers, source deduplication, budget checks, citation validation, and report formatting.

### 2. Component tests
Search/fetch adapters tested with mocked SDKs, HTTP responses, redirects, timeouts, and errors.

### 3. Agent-loop tests
Use a fake model adapter that emits known tool calls and final responses. Verify:
- registered tool call executes;
- tool output is fed back into the next model request;
- a later action can depend on an earlier observation;
- invalid tool names are rejected;
- malformed arguments are rejected;
- repeated calls and budget exhaustion terminate;
- provider errors are surfaced safely.

### 4. Report tests
Verify valid references, unknown source IDs, missing evidence, conflicting evidence, incomplete runs, and stable Markdown formatting.

### 5. Integration tests
Call real providers only when credentials are available and the user has approved any usage that may incur charges. Mark these tests separately, for example with a pytest marker.

### 6. Security tests
Test prohibited URL schemes, private/loopback/link-local destinations, redirect revalidation, DNS/IP checks, oversized responses, timeouts, prompt-injection text, and secret redaction.

### 7. Evaluation tests (Sprint 8)
Deterministic tests for the research-quality evaluation: dataset validation (valid, empty, malformed, duplicate IDs, missing fields), the eight quality checks, three-level citation verdicts, review-gated accuracy statuses, metric denominators and `unavailable` values, secret redaction, provider-failure classification, offline execution with sockets blocked, and live-mode refusal without opt-in. Fake providers and fixtures only — no live dependency in ordinary runs.

## Suggested commands

The exact commands must match `pyproject.toml` and the implemented packaging setup.

```bash
python -m pytest
ruff check .
ruff format --check .
```

Run focused tests first, for example:

```bash
python -m pytest tests/test_config.py -q
```

Do not run commands before the corresponding configuration exists. If a command is unavailable, report that rather than implying success.

## Coverage

Coverage can be introduced if useful, but do not optimize a percentage at the expense of meaningful tests. If a coverage threshold is adopted, record the threshold and actual measured result.

## Reporting template

- Command:
- Exit code:
- Result:
- Tests passed/failed/skipped:
- Environment or credential limitations:
- Follow-up required:
