按只读要求，本次未修改文件、未提交，也未刷新锁文件。

核对结果：

- `pnpm-workspace.yaml:36` 当前为 `^2.1.204`，目标应改为 `^2.1.205`。
- `plugins/airi-plugin-claude-code/package.json:24` 使用 `catalog:`。
- `pnpm-lock.yaml:16`、`pnpm-lock.yaml:17` 及相关平台包仍记录 `2.1.204`。

因此实际升级时需要同步刷新 `pnpm-lock.yaml`，使锁定版本和完整性信息更新到 `2.1.205`。
