# Atlas — Security Requirements and Threat Model

## 1. Assets to protect

- Provider API keys.
- Local files and environment.
- User research question and local report artifacts.
- Application integrity and execution resources.
- Network access from the page-fetch tool.
- Trustworthiness of citations and report claims.

## 2. Threats

### Prompt injection in web content
A page may contain instructions intended to manipulate the model.

Controls:
- Treat retrieved text as quoted/untrusted evidence, never as system instructions.
- Tool permissions are enforced in Python, not by the model.
- Do not expose secrets or privileged capabilities to the model context.
- Test with adversarial page content.

### Server-side request forgery (SSRF)
A malicious URL or redirect could target internal services.

Controls:
- Permit HTTP and HTTPS only.
- Reject localhost, private, loopback, link-local, multicast, reserved, and otherwise disallowed IP destinations as appropriate.
- Resolve and validate addresses before connection.
- Revalidate every redirect.
- Guard against DNS rebinding; use a connection strategy that ensures the validated address is the one reached.
- Do not forward credentials to arbitrary destinations.
- Bound redirects, timeouts, and response sizes.
- Test edge cases rather than relying only on string checks.

### Secret leakage
Credentials may leak into Git, logs, tracebacks, or reports.

Controls:
- Store secrets in environment variables or ignored `.env`.
- `.env.example` contains placeholders only.
- Ignore `.env`, virtual environments, caches, and local outputs where appropriate.
- Redact authorization headers and secrets from logs.
- Never ask the user to paste credentials into chat.
- Review `git diff` and `git status` before commits.

### Arbitrary tool execution
A model could request an unknown function or craft malicious arguments.

Controls:
- Explicit allowlist of tool names.
- Validate arguments against schemas.
- Enforce permissions and budgets in application code.
- Never use `eval`, dynamic imports, or shell execution to dispatch model tool calls.
- Never execute code found on web pages.

### Resource exhaustion and cost runaway
Repeated model calls or large pages can exhaust time, memory, or API budget.

Controls:
- Maximum eight model/tool-loop iterations by default.
- Overall deadline.
- Bounded search results and page size.
- Request timeouts.
- Bounded retries.
- Clear budget-exhausted status.
- Report provider usage when available.

### Misleading citations
A model may cite an irrelevant or nonexistent source.

Controls:
- Maintain an application-managed source registry.
- Validate all emitted source IDs/URLs.
- Preserve evidence excerpts.
- Disclose when source-to-claim support has not been verified.
- Never fabricate metadata.

## 3. Safe defaults

- No shell or arbitrary code tools.
- No write-capable external tools.
- No browser automation.
- No unrestricted URLs.
- No secrets in model context.
- No unlimited loops or retries.
- No automatic commits, pushes, or destructive operations.

## 4. Security verification

Security requirements must have tests. Do not mark a security feature verified because a prompt or comment says it is secure.

A page fetcher needs careful handling of URL parsing, DNS resolution, redirects, proxies, and the actual network connection. If robust SSRF controls cannot be guaranteed with the chosen implementation, narrow the allowed destinations or defer the fetch feature until a safe implementation is available.

## 5. Incident handling

If a secret is accidentally committed or exposed:
1. Stop further exposure.
2. Tell the user what type of secret may be affected without repeating it.
3. Recommend revoking/rotating the credential.
4. Remove it from active files and history only with careful, approved procedures.
5. Inspect logs and repository state for additional exposure.
