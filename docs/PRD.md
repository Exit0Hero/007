# Product Requirements Document (PRD)

## 1. Summary

Atlas is a single-agent research assistant that uses a language model and a small allowlist of web-research tools to investigate a question and produce an evidence-grounded Markdown report.

## 2. Problem statement

Manual research requires repeated searching, opening pages, comparing claims, tracking citations, and organizing findings. A language model answering from its existing knowledge alone may omit recent information or provide unsupported claims. Atlas aims to make this workflow more systematic and traceable.

## 3. Goals

- Research a user-supplied question using live sources when configured.
- Choose follow-up actions based on findings rather than only running a fixed script.
- Preserve source identity and useful evidence.
- Produce readable reports with citations and limitations.
- Remain testable, secure, bounded, and understandable.

## 4. Non-goals

Atlas does not guarantee truth, replace expert review, access restricted content, perform external side effects, or autonomously execute arbitrary code. It is not a multi-agent system in the MVP.

## 5. Personas

### Researcher
Wants a structured overview of a technical or general topic, with links to evidence.

### Developer/maintainer
Wants observable behavior, reliable tests, bounded costs, clear modules, and honest error reporting.

## 6. User journeys

1. User submits a research question.
2. Atlas validates the input and initializes run budgets.
3. The model chooses a permitted research action.
4. Atlas validates and executes the tool call.
5. Results are added to research state and returned to the model.
6. The model may request more research or finish.
7. Atlas validates source references and generates a report.
8. User receives the report and a completion/partial-completion status.

## 7. Functional requirements

### FR-01 Request validation
Reject empty or whitespace-only questions. Enforce a documented maximum length. Invalid requests must not trigger paid API calls.

### FR-02 Configuration
Load provider credentials from environment variables or a local ignored `.env`. Validate settings and report missing configuration safely.

### FR-03 Web search
Search via the configured provider. Normalize title, URL, snippet, and available date. Bound result count. Handle provider errors honestly.

### FR-04 Page retrieval
Fetch permitted HTTP(S) pages with strict URL, DNS, redirect, timeout, content-type, and size controls. Extract readable text without executing scripts.

### FR-05 Tool selection
Use model tool/function calling to select among an explicit allowlist. Validate all tool names and arguments in application code.

### FR-06 Adaptive research
Use tool observations to inform later action selection. The system must not be merely a fixed sequence of searches.

### FR-07 Bounded execution
Enforce a default maximum of eight model/tool-loop iterations, an overall deadline, and configurable resource limits. Return a clear termination reason.

### FR-08 Source registry
Assign stable IDs within a run, preserve canonical URL and available metadata, and avoid unnecessary duplicates.

### FR-09 Report generation
Generate Markdown containing the question, executive summary, findings, comparisons where relevant, uncertainty/limitations, and source list.

### FR-10 Citation validation
Every citation must refer to a registered source. Do not invent source IDs, URLs, dates, authors, or unsupported source-to-claim relationships.

### FR-11 Error handling
Handle validation, provider, timeout, rate-limit, malformed-response, and unexpected errors without exposing secrets.

### FR-12 CLI
Provide a documented local command to submit a question and save or print the resulting report.

### FR-13 Observability
Expose run status, iteration count, tool names, outcomes, and termination reason. Avoid logging secrets or unrestricted page contents.

## 8. Non-functional requirements

- **Security:** SSRF protections, strict tool allowlist, untrusted-content handling, secret hygiene.
- **Reliability:** bounded loops, timeouts, clear error categories.
- **Testability:** deterministic unit tests with mocked external services.
- **Maintainability:** typed public interfaces, focused modules, documented decisions.
- **Reproducibility:** dependency declarations and setup instructions.
- **Cost control:** bounded tool/model calls; do not claim exact cost without usage and pricing evidence.
- **Usability:** readable errors and Markdown output.

## 9. Acceptance criteria for MVP

The MVP must demonstrate:
1. Valid request accepted; invalid request rejected.
2. Search adapter returns normalized, bounded results.
3. Fetcher rejects prohibited destinations and handles timeouts/oversized responses.
4. Agent can select a tool, receive its result, and choose a subsequent action.
5. Agent terminates within configured limits.
6. Report citations map to actual source records.
7. Insufficient evidence is disclosed rather than fabricated.
8. Core tests run without provider credentials.
9. Live integration smoke tests are clearly separated from mocked tests.
10. Setup, usage, testing, and known limitations are documented.

## 10. Product metrics for evaluation

Record, rather than prematurely promise:
- Research run completion rate on a fixed test set.
- Citation validity rate.
- Human-rated evidence support.
- Useful-source proportion.
- Tool calls per successful report.
- Median runtime and provider failures.
- Approximate token/API usage when provider usage data is available.

Do not report accuracy, quality, or cost figures until a repeatable evaluation has actually been run.

## 11. Risks and mitigations

- Unsupported claims → evidence tracking and human review.
- Prompt injection → treat retrieved content as untrusted data.
- SSRF → URL/IP/redirect validation and bounded HTTP client.
- Infinite loops → iteration/deadline budgets.
- API cost → configurable budgets and mock-based tests.
- Stale sources → preserve dates when available and disclose missing dates.
- Provider API changes → verify official documentation and isolate provider-specific code.
