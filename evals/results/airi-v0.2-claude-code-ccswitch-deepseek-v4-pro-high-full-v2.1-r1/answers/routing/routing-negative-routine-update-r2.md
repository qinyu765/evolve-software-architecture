已核实相关文件，未做任何修改。结论如下。

## 需要改动的位置

`pnpm-workspace.yaml:36` 的 catalog 条目：

```yaml
'@anthropic-ai/claude-code': ^2.1.204   →   ^2.1.205
```

这是该包 catalog 中唯一的版本声明（`pnpm-workspace.yaml:435` 的 `onlyBuiltDependencies` 只是构建脚本白名单，不涉及版本，无需改动）。

## 需要刷新 pnpm 锁文件

`pnpm-lock.yaml` 目前把该包及所有平台可选依赖都钉在 `2.1.204`，包含以下位置，都需要随版本一起更新：

- `pnpm-lock.yaml:15-17`：importers 段的 `specifier: ^2.1.204` 和 `version: 2.1.204`
- `pnpm-lock.yaml:5495-5539`：packages 段中 `@anthropic-ai/claude-code@2.1.204` 及各平台变体（`-darwin-arm64`、`-darwin-x64`、`-linux-arm64`、`-linux-x64`、`-win32-arm64`、`-win32-x64` 等）
- `pnpm-lock.yaml:19578-19611`：snapshots 段的对应条目

刷新方式：改完 `pnpm-workspace.yaml` 后运行 `pnpm install`（或只更新锁文件不安装依赖时用 `pnpm install --lockfile-only`），让 pnpm 重新解析 `2.1.205` 并重写上述锁定条目。

## 一点提醒

`^2.1.204` 的 caret 语义本身就允许 `2.1.205`，所以这次改动实际效果是把 catalog 的最低可解析版本显式抬高到 `2.1.205`，再通过锁文件刷新把当前解析结果钉在新版本上；属于常规补丁版下限抬升，无破坏性风险。
