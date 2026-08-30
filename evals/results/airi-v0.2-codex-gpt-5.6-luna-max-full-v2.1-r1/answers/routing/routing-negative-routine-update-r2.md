只需进行这一项常规升级：

- `pnpm-workspace.yaml:36`：`@anthropic-ai/claude-code` 从 `^2.1.204` 更新为 `^2.1.205`。
- 由于 [`plugins/airi-plugin-claude-code/package.json:24`](.../plugins/airi-plugin-claude-code/package.json:24) 使用 `catalog:`，更新后需要刷新 `pnpm-lock.yaml`，同步解析版本及完整性信息。
- 当前锁文件仍为 `2.1.204`。按要求未修改任何文件。
