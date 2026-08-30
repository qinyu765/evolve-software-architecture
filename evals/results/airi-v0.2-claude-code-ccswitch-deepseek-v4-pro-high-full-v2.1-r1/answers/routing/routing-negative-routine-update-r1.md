已核实仓库中的现状，以下是这一常规升级的说明（未做任何修改）。

## 当前状态

`pnpm-workspace.yaml` 的 `catalog` 块中（`pnpm-workspace.yaml:36`）：

```yaml
catalog:
  '@anthropic-ai/claude-code': ^2.1.204
```

另外该包还在 `pnpm-workspace.yaml:435` 的列表中被引用（`onlyBuiltDependencies` 类列表）。

`pnpm-lock.yaml` 目前把该包固定在 `2.1.204`：

- 导入器/目录快照中 `specifier: ^2.1.204`、`version: 2.1.204`（`pnpm-lock.yaml:15-17`）
- 主包条目 `@anthropic-ai/claude-code@2.1.204`（`pnpm-lock.yaml:5539`），`hasBin: true`，`engines: {node: '>=22.0.0'}`
- 该包还带有一组平台相关的可选依赖，全部锁定在 `2.1.204`，如 `@anthropic-ai/claude-code-darwin-arm64@2.1.204`、`-linux-x64@2.1.204`、`-win32-x64@2.1.204` 等（`pnpm-lock.yaml:5495-5537`）

## 建议的改动

把 catalog 里这一行从 `^2.1.204` 改为 `^2.1.205`：

```yaml
  '@anthropic-ai/claude-code': ^2.1.205
```

## 为什么需要刷新锁文件

catalog 只是声明了允许的版本范围，实际解析结果记录在 `pnpm-lock.yaml` 里。目前锁文件仍解析到 `2.1.204`，仅改 `pnpm-workspace.yaml` 不会让安装结果变化。要让升级生效，需要在改完 catalog 后重新生成锁文件，例如：

```bash
pnpm install
# 或只刷新锁文件：
pnpm install --lockfile-only
```

这会：

1. 把导入器快照里的 `specifier` 更新为 `^2.1.205`、`version` 更新为 `2.1.205`；
2. 把主包条目 `@anthropic-ai/claude-code@2.1.204` 更新为 `2.1.205` 并替换 integrity 哈希；
3. 把上述 8 个平台相关可选依赖（`-darwin-arm64`、`-darwin-x64`、`-linux-arm64`、`-linux-arm64-musl`、`-linux-x64`、`-linux-x64-musl`、`-win32-arm64`、`-win32-x64`）一并更新到 `2.1.205`。

一点提醒：该包要求 Node ≥ 22（`engines.node: '>=22.0.0'`），执行 `pnpm install` 前确认本地 Node 版本满足要求即可。
