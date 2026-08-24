已核实：`@anthropic-ai/claude-code` 在 `pnpm-workspace.yaml` 的顶层 `catalog:` 中，位于第 36 行，当前值为 `^2.1.204`。这是一次常规的补丁版本升级，改动只涉及这一处版本号。

## 需要改的内容（仅说明，未修改文件）

`pnpm-workspace.yaml` 第 36 行：

```yaml
catalog:
  '@anthropic-ai/claude-code': ^2.1.204
```

改为：

```yaml
catalog:
  '@anthropic-ai/claude-code': ^2.1.205
```

因为这是带 `^` 的 caret 范围，`^2.1.205` 实际解析为 `>=2.1.205 <3.0.0`，即只会允许 2.1.x 系列的 2.1.205 及之后的补丁版本，不改变主版本兼容范围。

## 不需要改的内容

第 435 行的 `onlyBuiltDependencies` 里也有一个 `'@anthropic-ai/claude-code'` 条目，但它只是包名白名单（允许安装后运行构建脚本），不携带版本号，所以这次升级不用动它。

## 需要刷新 pnpm 锁文件

catalog 版本变更后，`pnpm-lock.yaml` 中记录的解析版本会与新范围不一致，需要重新解析并刷新锁文件。可执行：

```bash
pnpm install
```

如果只想更新锁文件而不重新安装依赖，可以用：

```bash
pnpm install --lockfile-only
```

提交时应把 `pnpm-workspace.yaml` 和更新后的 `pnpm-lock.yaml` 一起纳入变更。
