# Releasing `@varsity-arena/agent`

## Preconditions

- npm scope `@varsity-arena` exists
- you have publish access to `@varsity-arena/agent`
- `NPM_TOKEN` is configured in GitHub Actions for automated publishes
- package version in `package.json` is updated

## Local release checklist

From [`packages/mcp`](/home/rick/Desktop/arena/packages/mcp):

```bash
npm install
npm run build
npm pack --dry-run
```

Sanity-check:

- package name is `@varsity-arena/agent`
- `dist/` is included
- README references `npm install -g @varsity-arena/agent`
- no secrets or local paths appear in the packed file list

## Manual publish

```bash
npm login
npm publish --access public
```

## Recommended version flow

```bash
npm version patch
git push origin main --follow-tags
```

## Automated publish

The GitHub Actions workflow publishes on:

- manual dispatch
- tags matching `agent-v*`

Recommended tag format:

```bash
git tag agent-v0.1.1
git push origin agent-v0.1.1
```

## Post-release verification

```bash
npm view @varsity-arena/agent version
npm install -g @varsity-arena/agent
arena-agent --help
arena-mcp --help
```
