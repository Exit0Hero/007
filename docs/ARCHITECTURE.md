# Atlas — Architecture

## 1. Architectural approach

Start with a small, modular monolith and one research agent. Use explicit Python functions as tools, a bounded controller loop, validated data structures, and a report generator. Avoid an agent framework unless a later, documented decision demonstrates the need.

## 2. High-level data flow

```text
CLI request
   |
   v
Request/config validation
   |
   v
Research state + execution budgets
   |
   v
LLM with approved tool definitions
   |
   +---- final response ----> report/evidence validation ----> Markdown report
   |
   +---- tool call ---------> schema validation
                                  |
                                  v
                            explicit tool registry
                              /             \
                         web_search       fetch_page
                              \             /
                               normalized result
                                      |
                                      v
                              append observation
                                      |
                                      +---- back to model
```

## 3. Module responsibilities

### `src/atlas/main.py`
CLI entry point. Parse arguments, load config, call the agent, write output, and return an appropriate exit code. Keep research logic elsewhere.

### `src/atlas/config.py`
Validated settings and environment loading. No secrets in source. Support a clear distinction between offline/mock mode and live provider mode.

### `src/atlas/models.py`
Pydantic or typed models for research requests, search results, source records, tool results, run status, and report metadata.

### `src/atlas/agent.py`
Bounded control loop, model requests, explicit tool registry, tool-call validation/dispatch, research state, usage/iteration tracking, and termination reasons.

### `src/atlas/tools/search.py`
Tavily adapter. Provider-specific request/response mapping, result limits, error normalization.

### `src/atlas/tools/fetch.py`
Secure HTTP fetching, destination validation, redirect checks, size/time limits, and readable-text extraction. Must not execute page content.

### `src/atlas/report.py`
Report assembly, source registry, citation validation, limitation disclosure, and Markdown output.

## 4. Proposed initial repository structure

```text
007/
├── AGENTS.md
├── README.md
├── requirements.txt
├── pyproject.toml
├── .gitignore
├── .env.example
├── docs/
│   ├── MASTER_CHARTER.md
│   ├── PRD.md
│   ├── ARCHITECTURE.md
│   ├── ROADMAP.md
│   ├── SPRINTS.md
│   ├── STATUS.md
│   ├── DECISIONS.md
│   ├── TESTING.md
│   ├── SECURITY.md
│   ├── DEFINITION_OF_DONE.md
│   └── CONTRIBUTING.md
├── prompts/
│   ├── SPRINT_0.md
│   ├── SPRINT_1.md
│   └── SPRINT_EXECUTION.md
├── src/atlas/
└── tests/
```

Create source files only when the relevant sprint requires them. This documentation kit does not mean application modules are already implemented.

## 5. Agent loop contract

1. Validate the question.
2. Initialize research state and budgets.
3. Send the request, context, and approved tool schemas to the configured model.
4. Inspect the actual SDK response structure.
5. If a tool call is requested, validate its name and arguments.
6. Enforce permission, time, iteration, and resource budgets.
7. Execute only the registered function.
8. Normalize and bound the result.
9. Record tool execution and observation.
10. Return the result to the model and continue.
11. If the model completes, validate evidence and build the report.
12. If limits or unrecoverable errors occur, return an explicit partial/failure status.

The model is not the security boundary. Application code must enforce all tool permissions and limits.

## 6. Tool contracts

### `web_search`
Input: query string and bounded result count.
Output: normalized list of source candidates with title, URL, snippet, and available date.
Side effects: external search API call only.
Restrictions: bounded query size/results/time; no arbitrary browsing instructions.

### `fetch_page`
Input: URL from a source candidate or a validated URL.
Output: source metadata and bounded extracted text.
Side effects: outbound HTTP GET only.
Restrictions: HTTP(S) only, SSRF protections, redirect revalidation, response/time limits, content-type restrictions, no scripts or code execution.

## 7. Research state

The state should contain only what the current run needs:
- Original question.
- Research objectives/questions, if used.
- Source registry.
- Bounded evidence excerpts.
- Tool observations.
- Iteration and resource counters.
- Completion status and reason.

Do not add persistent user memory or a database to the MVP without a requirement.

## 8. Error model

Represent expected failures distinctly, such as:
- InvalidRequest
- ConfigurationError
- SearchProviderError
- FetchError
- ToolValidationError
- ModelProviderError
- BudgetExceeded
- CitationValidationError

Exact class names can be chosen during implementation. Avoid swallowing broad exceptions without recording a safe diagnostic.

## 9. Configuration and secrets

Application secrets:
- `OPENAI_API_KEY`
- `TAVILY_API_KEY`

Non-secret configuration may include:
- `ATLAS_MODEL`
- `ATLAS_MAX_ITERATIONS`
- `ATLAS_MAX_RESULTS`
- `ATLAS_TIMEOUT_SECONDS`

Use `.env.example` for placeholder names and `.gitignore` for `.env`. Verify model availability and current SDK API usage before implementation.

## 10. Architecture constraints

- One process, one agent, one research run at a time for the initial CLI.
- No arbitrary shell/code tool.
- No model-controlled dynamic imports or unrestricted function dispatch.
- No vector database.
- No multi-agent framework.
- No frontend until the CLI MVP works.
- Keep provider adapters replaceable where reasonable, but do not over-engineer provider abstraction.
