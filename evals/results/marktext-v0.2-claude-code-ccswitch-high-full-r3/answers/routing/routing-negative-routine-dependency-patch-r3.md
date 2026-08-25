结论：这是一次常规的依赖升级，需要同时改两处——`packages/desktop/package.json` 里的版本范围，以及仓库根目录的 `pnpm-lock.yaml`（它记录的是解析后的实际版本）。我只做说明，不修改任何文件。

## 选一个合适的依赖

`packages/desktop/package.json` 里有两类依赖：

- **workspace 依赖**：`@marktext/muyajs`、`@muyajs/core`，版本是 `workspace:*`，指向本仓库内的包，不走 npm 补丁升级，排除。
- **普通 npm 依赖**：比如 `axios: "^1.18.0"`（第 67 行），这是这次操作的对象。

以 `axios` 为例，它在 `pnpm-lock.yaml` 中已经解析为 `1.18.0`（见 `pnpm-lock.yaml:90-92` 的 importer 条目，以及 `:4266`、`:13445` 的快照条目）。

## 升级操作

假设下一个补丁版本是 `1.18.1`（实际以 `pnpm view axios version` 查到的为准），有两种等价做法：

**做法一（推荐，一步到位）：** 在仓库根目录执行

```bash
pnpm --filter marktext add axios@^1.18.1
```

这会同时更新 `packages/desktop/package.json` 的版本范围和根目录 `pnpm-lock.yaml` 的解析结果，保证两者一致。

**做法二（手动改清单再刷新锁文件）：**

1. 把 `packages/desktop/package.json` 中 `"axios": "^1.18.0"` 改为 `"^1.18.1"`。
2. 在根目录执行 `pnpm install` 刷新锁文件。

## 为什么必须刷新 pnpm-lock.yaml

- 这是 pnpm workspace，整个仓库只有**一个**根目录 `pnpm-lock.yaml`，里面有个专门的 importer 条目 `packages/desktop:`（`pnpm-lock.yaml:55`），记录了这个包每个依赖的 `specifier`（范围）和解析后的具体 `version`。
- 只改 `package.json` 不刷新锁文件，两者的 `specifier` 就会对不上。CI 若用 `pnpm install --frozen-lockfile`（冻结锁文件）会直接报错；即使不冻结，`pnpm install` 也会因为锁文件过期而要求重新生成。
- 锁文件才是安装时的真实依据。不刷新它，装出来的还是旧版本，升级等于没生效。

## 一个易混点

`^1.18.0` 这种 caret 范围本身就允许 `1.18.x` 乃至 `1.x` 的补丁/次版本，所以严格说「装一个补丁版本」不需要改范围，只要让锁文件解析到新版本即可。但把补丁升级作为一次**常规、可复现的变更**落进仓库时，惯例是同时更新清单里的范围并刷新锁文件，让代码评审和 CI 都能看到明确的版本变更。
