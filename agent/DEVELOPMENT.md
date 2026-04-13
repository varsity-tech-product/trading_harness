# Development Notes

Internal only. Do not surface staging or hidden environment flags in public docs.

## API Environments

- Production is the default environment for all external users.
- If `VARSITY_BASE_URL` is unset, the package uses production: `https://api.otter.trade/v1`.
- Staging is for local development only: `https://api.varsity.lol/v1`.

## Local Developer Overrides

Use one of these when developing against staging:

```bash
arena-agent init --home ~/.arena-agent-staging --env staging
arena-mcp setup --client codex --home ~/.arena-agent-staging --env staging
```

`--env` is intentionally hidden and only supports `prod` and `staging`.

`--base-url` remains the escape hatch for custom endpoints and takes precedence over `--env`.

Examples:

```bash
arena-agent init --base-url https://api.varsity.lol/v1
arena-mcp setup --client codex --base-url https://api.varsity.lol/v1
```

To switch an existing local setup back to production:

```bash
arena-agent init --home ~/.arena-agent-staging --env prod
arena-mcp setup --client codex --home ~/.arena-agent-staging --env prod
```

## Documentation Rule

- Public docs should only describe the production default path.
- Internal docs may mention `--env`, staging, and custom base URLs.
