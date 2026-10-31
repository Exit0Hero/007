# 007

A modular, autonomous, evidence-grounded AI research agent that operates through a local command-line interface. It supports deterministic offline execution and live research using configurable LLM and web search providers.

**Note:** This is a local CLI application, not a hosted service.

## Features

- **Autonomous Research Loop**: Plans, searches, fetches evidence, and synthesizes findings
- **Evidence-Grounded Reports**: Every claim backed by traceable citations
- **Offline Mode**: Deterministic fixtures, no API keys or network required
- **Live Mode**: Use OpenRouter, OpenAI-compatible APIs, Exa, or Tavily
- **Budget-Aware**: Respects iteration, time, and tool call limits
- **Robust Error Handling**: Graceful failures with honest reporting
- **Evaluation Framework**: 24 test cases with automated quality checks

## Installation

```bash
git clone https://github.com/Exit0Hero/007.git
cd 007

python3 -m venv .venv
source .venv/bin/activate

pip install -e ".[dev]"
```

## Quick Start

### Offline Mode (no API keys needed)
```bash
007 "Explain retrieval-augmented generation" --output report.md
```

Offline mode uses deterministic fixtures and does not make real provider calls.

### Live Mode
1. Copy `.env.example` to `.env` and configure your credentials
2. Set `ATLAS_MODE=live` and your model/provider settings
3. Run your query

```bash
007 "Explain quantum computing basics" --output report.md
```

## Supported Providers

**LLM Providers:**
- OpenRouter (via OpenAI-compatible API)
- Any OpenAI-compatible endpoint

**Search Providers:**
- [Exa](https://exa.ai/)
- [Tavily](https://tavily.com/)

## Evaluation

```bash
# Offline smoke tests
python -m agent007.evalrun run --smoke

# Full offline evaluation
python -m agent007.evalrun run

# Live evaluation (requires credentials)
python -m agent007.evalrun run --live --smoke
```

## Development

```bash
# Run tests
python -m pytest

# Lint
ruff check .

# Format
ruff format .
```

## Security

- Never commit API keys or credentials
- Use `.env` files (gitignored)
- API keys are redacted from logs and errors
- Web content is treated as untrusted

## License

MIT License - see [LICENSE](LICENSE) for details.

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) for guidelines.
