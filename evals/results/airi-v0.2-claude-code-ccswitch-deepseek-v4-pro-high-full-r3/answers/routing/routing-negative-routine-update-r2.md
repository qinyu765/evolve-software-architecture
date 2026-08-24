这是一个常规补丁升级,当前仓库状态如下:

## 需要改动的位置

`pnpm-workspace.yaml` 第 36 行的 catalog 条目:

```yaml
catalog:
  ...
  '@anthropic-ai/claude-code': ^2.1.204   # → 改为 ^2.1.205
  ...
```

改动只有这一处版本号。该依赖通过 catalog 被 `plugins/airi-plugin-claude-code` 以 `catalog:` 方式引用(`plugins/airi-plugin-claude-code/package.json:24`),所以升级后插件无需单独改 `package.json`。

## 锁文件刷新

当前 `pnpm-lock.yaml` 锁定的是 `2.1.204`:

- catalog 快照区(`pnpm-lock.yaml:15-17`):
  ```yaml
  '@anthropic-ai/claude-code':
    specifier: ^2.1.204
    version: 2.1.204
  ```

把 specifier 改成 `^2.1.205` 后,锁文件仍指向旧版本,与 catalog 不一致。因此需要在改完 `pnpm-workspace.yaml` 后刷新锁文件,让 `pnpm` 把 `version` 提升到 `2.1.205`,并同步更新该包的全部平台二进制(如 `pnpm-lock.yaml` 中 `2.1.204` 的 darwin/linux/win32 各平台条目)。

## 刷新命令

```bash
pnpm install
```

或指定到受影响工作区(可选,通常全量即可):

```bash
pnpm install --filter @proj-airi/airi-plugin-claude-code
```

`pnpm install` 会自动根据新的 catalog specifier 重新解析并更新 `pnpm-lock.yaml`。

## 验证

升级后应确认锁文件不再出现 `2.1.204`(至少 `@anthropic-ai/claude-code` 主包及平台二进制均指向 `2.1.205`),并按常规跑一下插件侧的类型检查:

```bash
pnpm -F @proj-airi/airi-plugin-claude-code typecheck
```

按你的要求,本轮只做说明,未修改任何文件。
