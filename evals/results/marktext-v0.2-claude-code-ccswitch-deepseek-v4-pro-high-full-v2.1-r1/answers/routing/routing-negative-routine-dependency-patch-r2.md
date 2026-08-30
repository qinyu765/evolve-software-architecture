结论先说：以 `packages/desktop/package.json` 里最典型的 Electron workspace 依赖 `electron` 为例，它是 devDependency，当前范围是 `~42.1.0`。要升级到下一个补丁版本就是把这一行改成 `~42.1.1`，然后在仓库根目录跑一次 `pnpm install` 刷新 `pnpm-lock.yaml`。下面只做说明，不改任何文件。

## 选中的依赖与当前状态

`packages/desktop/package.json:134`：

```json
"electron": "~42.1.0",
```

`~`（波浪号）表示只允许补丁升级：`>=42.1.0 <42.2.0`。所以“下一个补丁版本”就是 **42.1.1**，对应的编辑是把范围写成 `~42.1.1`（仍只允许 42.1.x 内的补丁升级）。

`pnpm-lock.yaml` 里目前锁定的实际版本是 42.1.0，共有三处记录：

- `packages/desktop` 导入块（`pnpm-lock.yaml:277-279`）：`specifier: ~42.1.0` / `version: 42.1.0`
- 快照条目 `electron@42.1.0`（`pnpm-lock.yaml:5194`）：记录 integrity 哈希、engines、hasBin 等元数据
- 依赖图节点 `electron@42.1.0`（`pnpm-lock.yaml:14489`）：记录它自己的依赖（`@electron/get`、`@types/node`、`extract-zip` 等）和传递 peer 依赖

## 为什么要刷新 pnpm-lock.yaml

pnpm 的锁文件会被提交进仓库，它记录的是**精确解析后的版本和 integrity 哈希**，不是范围。如果只改 `package.json` 而不更新锁文件，两者就不一致；CI 或本地用 `--frozen-lockfile` 安装时，pnpm 会直接报 `lockfile is not up to date` 并拒绝安装。

刷新方式是在**仓库根目录**运行：

```bash
pnpm install
```

（这是一个 pnpm workspace，根目录的 lockfile 是唯一的；也可以 `pnpm update electron --filter marktext`，但直接 `pnpm install` 最稳妥，会按新范围重新解析并改写锁文件。）

刷新后锁文件会变动的条目不只是 electron 本体，还包括以 electron 为 peer 依赖的包。比如 `@electron-toolkit/preload` 和 `@electron-toolkit/utils` 的快照键是带 electron 版本后缀的：

- `@electron-toolkit/preload@3.0.2(electron@42.1.0)` → `(electron@42.1.1)`
- `@electron-toolkit/utils@4.0.0(electron@42.1.0)` → `(electron@42.1.1)`

同时导入块里这两行的 `version` 后缀、以及 `electron@42.1.0` 的快照条目和依赖图节点，都会更新到 42.1.1。

## 升级后的一个必要后续

CLAUDE.md 的「Important Build Notes」明确要求：**更改 Electron 版本后要运行 `pnpm run rebuild-native`（即 `electron-rebuild -f`）**，否则原生模块（如 `keytar`、`native-keymap`）可能对不上新的 Electron ABI。即使只是补丁升级，也建议跑一次再验证。

## 验证方式

- `git diff pnpm-lock.yaml` 应只显示 electron 相关的版本、哈希和 peer 后缀变化。
- 跑 `pnpm install --frozen-lockfile` 确认锁文件与 `package.json` 一致（此时不应报 lockfile 过期）。
- 按项目要求跑 `pnpm run typecheck` 和 `pnpm run lint`（依赖升级通常不影响类型/lint，但提交前按 CLAUDE.md 是必查项）。

补充一点：由于当前范围 `~42.1.0` 本身就允许 42.1.1，如果你不打算改 `package.json`，其实单独跑一次 `pnpm update electron` 也能把锁文件里的实际版本推进到 42.1.x 最新补丁。但按你的设定——显式把 `package.json` 里的依赖升级到下一个补丁版本——就是上面的 `~42.1.0` → `~42.1.1` + `pnpm install` 两步。
