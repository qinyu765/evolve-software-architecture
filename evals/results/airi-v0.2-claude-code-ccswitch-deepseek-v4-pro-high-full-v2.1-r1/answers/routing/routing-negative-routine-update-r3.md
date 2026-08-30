Verified. Here's what this routine upgrade involves — no files changed.

## Current state

- `pnpm-workspace.yaml:36` (inside the `catalog:` block):
  ```yaml
  '@anthropic-ai/claude-code': ^2.1.204
  ```
- The sole consumer is `plugins/airi-plugin-claude-code/package.json:24`, which pins it via the catalog: `"@anthropic-ai/claude-code": "catalog:"`.
- `pnpm-lock.yaml` currently resolves `@anthropic-ai/claude-code@2.1.204`, including its eight platform-specific optional dependencies (`@anthropic-ai/claude-code-darwin-arm64@2.1.204`, `-darwin-x64`, `-linux-*`, `-win32-*`).

## The change

Edit one line in the catalog:

```yaml
# before
'@anthropic-ai/claude-code': ^2.1.204
# after
'@anthropic-ai/claude-code': ^2.1.205
```

No change is needed in `plugins/airi-plugin-claude-code/package.json` — its `catalog:` reference automatically picks up the new range.

## Lock file refresh (required)

`pnpm-lock.yaml` still pins `2.1.204`, so it must be regenerated to record `2.1.205` and its updated platform binaries. Run:

```bash
pnpm install
```

This resolves the new `^2.1.205` range and rewrites the lock file. Because it's a patch bump within the same `^2.1.x` range, the update only touches the `claude-code` entry and its platform-specific optional deps — no other packages should move.

Two notes for the PR summary: `^2.1.204` already allows any `2.1.x ≥ 2.1.204`, so this change only raises the floor to `2.1.205` rather than enabling a new minor range; and the lock file change should be committed together with the catalog edit so CI (which installs from the lockfile) actually gets `2.1.205`.
