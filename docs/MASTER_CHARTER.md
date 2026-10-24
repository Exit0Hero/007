# Atlas — Master Project Charter

## 1. Project identity

- **Name:** Atlas
- **Type:** Single-agent AI research application
- **Primary language:** Python
- **Primary interface for MVP:** Command-line interface
- **Research output:** Markdown report with traceable sources
- **Development method:** User-story-driven, sprint-based, incremental delivery
- **Current baseline:** Planning kit only; implementation state must be verified from the repository

## 2. Product vision

Atlas accepts a natural-language research question, plans and conducts research using registered tools, observes results, identifies gaps, performs follow-up research when useful, and produces a structured report with evidence and source references.

Example question: “Compare retrieval-augmented generation and AI agents for production applications. Explain architecture, use cases, failure modes, evaluation, and operational considerations.”

## 3. Product principles

1. Evidence over confidence.
2. Bounded autonomy.
3. Explicit tool permissions.
4. Observable execution.
5. Reproducible development.
6. Graceful failure.
7. Incremental complexity.
8. Honest status reporting.

## 4. Primary user

A student, developer, or researcher who wants an initial research report with links to the material used.

## 5. Initial MVP capabilities

- Accept and validate a research question.
- Search the web through a configured search provider.
- Fetch and extract readable content from permitted web pages.
- Use a model's tool-calling interface to select actions.
- Adapt follow-up actions based on tool observations.
- Enforce iteration, time, and content limits.
- Generate a Markdown report with a source registry.
- Validate that citations refer to sources actually retrieved.
- Test core behavior without paid API calls.

## 6. Out of scope for MVP

- Multi-agent orchestration.
- Arbitrary shell or Python execution by the model.
- Browser automation and form submission.
- Sending email or other external side effects.
- User accounts and multi-tenant hosting.
- Vector databases or embedding pipelines.
- Complex RAG infrastructure.
- Background autonomous scheduling.
- Production deployment before the CLI is reliable.
- Unsupported claims of research accuracy or time saved.

## 7. Proposed stack

- Python 3.11+
- OpenAI Python SDK with the documented Responses API and function calling
- Tavily Python SDK for web search
- Pydantic
- python-dotenv
- pytest
- Ruff
- A static type checker if justified by the sprint

Check the official documentation, installed versions, model availability, and account access before relying on any version-sensitive details. The application credentials are separate from OpenCode's own model-provider configuration.

## 8. Engineering responsibilities

The coding agent must inspect before editing, plan before implementation, keep changes in scope, test behavior, review diffs, update status, disclose uncertainty, and stop at the sprint boundary.

It must not invent test results, citations, API behavior, or implementation status.

## 9. Product success criteria

The MVP is successful when it can:
- Accept a valid research question.
- Search and retrieve real sources when configured.
- Make at least one adaptive tool-selection decision based on observations.
- Stop within explicit budgets.
- Produce a report whose citations map to retrieved sources.
- Handle common provider, network, validation, and model errors.
- Run deterministic unit tests without paid API calls.
- Provide reproducible setup and run instructions.

## 10. Current execution rule

Begin with Sprint 0: inspect the real repository and prepare project documentation. Do not implement application features until the user explicitly approves Sprint 1.
