# Contributing to 007

Thank you for your interest in contributing to 007!

## Getting Started

1. Fork the repository on GitHub
2. Clone your fork:
   ```bash
   git clone https://github.com/YOUR_USERNAME/007.git
   cd 007
   ```
3. Create a virtual environment:
   ```bash
   python3 -m venv .venv
   source .venv/bin/activate
   ```
4. Install development dependencies:
   ```bash
   pip install -e ".[dev]"
   ```

## Development

- Run tests: `python -m pytest`
- Run linting: `ruff check .`
- Run formatting: `ruff format .`
- Run offline evaluation: `python -m agent007.evalrun run --smoke`

## Coding Standards

- Follow existing code style
- Add tests for new functionality
- Keep changes focused and minimal
- Never commit secrets or credentials

## Pull Request Guidelines

1. Create a feature branch from main
2. Make your changes with clear commits
3. Ensure all tests pass
4. Update documentation as needed
5. Submit a pull request with a clear description

## Bug Reports & Feature Requests

Please use GitHub Issues to report bugs or propose features.
