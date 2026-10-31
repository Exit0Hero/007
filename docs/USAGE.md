# Usage Guide

## CLI Options

```bash
007 [OPTIONS] QUESTION
```

Options:
- `-o, --output PATH`: Write report to file
- `--max-iterations N`: Override iteration limit (1-64)
- `--max-results N`: Override search results limit (1-50)
- `--deadline SECONDS`: Override time limit
- `--version`: Show version
- `-h, --help`: Show help

## Modes

### Offline Mode (Default)
- No API keys required
- Uses deterministic fixtures
- Reproducible results
- Perfect for testing

### Live Mode
- Requires API credentials
- Real web search and LLM calls
- Evidence from live sources
- Subject to rate limits
