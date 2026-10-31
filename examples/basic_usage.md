# Basic Usage Examples

## Offline Mode
```bash
# Simple query
007 "What is machine learning?"

# Save to file
007 "Explain quantum entanglement" --output quantum_report.md
```

## Live Mode
```bash
# With OpenRouter
export ATLAS_MODE=live
export OPENAI_API_KEY=your_key
export OPENAI_BASE_URL=https://openrouter.ai/api/v1
export ATLAS_MODEL=nvidia/nemotron-3.5-lightning:free
export EXA_API_KEY=your_exa_key

007 "Latest developments in AI" --output ai_report.md
```

## Evaluation
```bash
# Run smoke tests
python -m agent007.evalrun run --smoke

# Run all tests
python -m agent007.evalrun run
```
