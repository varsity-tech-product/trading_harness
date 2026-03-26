# Security Policy

## Reporting a Vulnerability

If you discover a security vulnerability, please report it responsibly:

1. **Do NOT** open a public GitHub issue
2. Email **security@varsity.tech** with details
3. Include steps to reproduce, impact assessment, and any suggested fixes

We will acknowledge your report within 48 hours and aim to release a fix within 7 days for critical issues.

## Scope

This policy covers:

- The `@varsity-arena/agent` npm package
- The `arena_agent` Python runtime
- The `varsity_tools.py` SDK
- API key handling and credential storage

## Expression Engine Safety

The expression engine (`arena_agent/agents/expression_policy.py`) evaluates user-defined Python expressions in a sandboxed environment:

- AST whitelist — only comparison, boolean, and arithmetic operators allowed
- Empty `__builtins__` — no function calls, imports, or code execution
- No access to `os`, `sys`, `subprocess`, or any dangerous modules

If you find a way to escape this sandbox, please report it immediately.
