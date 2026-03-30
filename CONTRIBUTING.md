# Contributing to Arena Agent

Thanks for your interest in contributing! Here's how you can help.

## Reporting Bugs

Open a [bug report](https://github.com/varsity-tech-product/trading_harness/issues/new?template=bug_report.yml) with:

- What you expected vs. what happened
- Steps to reproduce
- Your environment (OS, Node version, Python version)

## Suggesting Features

Open a [feature request](https://github.com/varsity-tech-product/trading_harness/issues/new?template=feature_request.yml) describing:

- The problem you're trying to solve
- Your proposed solution
- Alternatives you've considered

## Submitting Pull Requests

1. Fork the repo and create a branch from `main`
2. Make your changes
3. Run tests: `cd agent && npm test`
4. Ensure your code compiles: `python3 -m py_compile <file>` for Python changes
5. Open a PR with a clear description of what and why

### Code Style

- **TypeScript** (agent/): Follow existing patterns, `strict` mode enabled
- **Python** (arena_agent/): Standard library conventions, type hints preferred

### What We're Looking For

- Bug fixes with reproduction steps
- New TA-Lib indicator integrations
- Agent backend support (new LLM providers)
- Documentation improvements
- Test coverage

## Development Setup

```bash
# TypeScript (agent/)
cd agent && npm install && npm run build && npm test

# Python (arena_agent/)
pip install -e ".[full]"
```

## Questions?

Open a [GitHub Discussion](https://github.com/varsity-tech-product/trading_harness/discussions) or file an issue.
