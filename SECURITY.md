# Security Policy

## Reporting a Vulnerability

If you discover a security vulnerability in 007, please report it responsibly by opening a GitHub issue with the "security" label or contacting the maintainers directly.

## Security Considerations

- **API Keys**: Never commit API keys. Use environment variables or `.env` files (which are gitignored).
- **Local Only**: 007 is a local CLI tool, not a hosted service.
- **Untrusted Content**: Web content is treated as untrusted data. Instructions embedded in pages cannot override agent behavior.
- **Tool Sandboxing**: Tools use an allowlist with validation.
- **Secrets in Logs**: API keys are redacted from logs and error messages.

## Supported Versions

Only the latest version on the main branch is actively supported.
