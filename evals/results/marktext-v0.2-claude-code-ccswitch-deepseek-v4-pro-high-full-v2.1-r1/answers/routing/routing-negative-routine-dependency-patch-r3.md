## 结论

要升级的是 `packages/desktop/package.json` 里的常规 Electron 依赖 —— `electron` 本体。它当前声明在 `devDependencies` 中：

- `packages/desktop/package.json:134` — `"electron": "~42.1.0"`

对应锁文件里的两条证据：

- `pnpm-lock.yaml:277-279` — specifier `~42.1.0` 解析为 version `42.1.0`
- `pnpm-lock.yaml:5194-5197` — 快照 `electron@42.1.0`（带 integrity 哈希 `sha512-0szNwC...`）

## 升级内容

下一个补丁版本是 **42.1.1**，即把声明从 `~42.1.0` 改为 `~42.1.1`：

```jsonc
// 前
"electron": "~42.1.0"
// 后
"electron": "~42.1.1"
```

一点说明：`~42.1.0` 这个波浪号范围本身允许 `>=42.1.0 <42.2.0`，所以严格说它已能解析到 42.1.x 的最新补丁。把下限显式提到 `~42.1.1` 的语义是「声明并锁定到这个补丁基线」，真正的落地靠刷新锁文件。42.1.1 是否已发布需要以 npm registry（如 `pnpm outdated electron` 的输出）为准，仓库本身不记录上游已发布的版本号。

## 为什么必须刷新 pnpm-lock.yaml

只改 `package.json` 不会改变实际安装结果 —— 安装时读取的是 `pnpm-lock.yaml`。当前锁文件把 Electron 固定为 `42.1.0`，不刷新的话，`electron@42.1.0` 这个快照及其 integrity 哈希不会变。需要更新的不止一处：

- `pnpm-lock.yaml:5194` 的 `electron@42.1.0:` 快照要换成 `electron@42.1.1:`，integrity 哈希随之改变。
- `pnpm-lock.yaml:277-279` 的 importer 段里 version 从 `42.1.0` 变为 `42.1.1`。
- 依赖 Electron 作为 peer 的条目也会跟着改名，例如 `@electron-toolkit/preload@3.0.2(electron@42.1.0)` 和 `@electron-toolkit/utils@4.0.0(electron@42.1.0)`（`pnpm-lock.yaml:10775-10781`）会变成 `(electron@42.1.1)`。

刷新方式：在仓库根目录运行 `pnpm install`（会同时执行 postinstall、重建原生模块、minify locales），或只更新锁文件用 `pnpm install --lockfile-only` / `pnpm update electron`。刷新后 git diff 里应同时看到 `package.json` 和 `pnpm-lock.yaml` 两处变更。

## 后续提醒

Electron 版本变化会影响原生模块的 ABI。按项目约定（见 `CLAUDE.md` 的 Native modules 一节），升级后还需要运行 `pnpm run rebuild-native`（即 `electron-rebuild -f`）重建 `native-keymap`、`keytar` 等原生依赖。

以上仅为说明，未修改任何文件。
