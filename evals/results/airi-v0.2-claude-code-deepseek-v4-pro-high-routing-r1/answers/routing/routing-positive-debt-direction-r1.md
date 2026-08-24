# 1. 范围与置信度

要决策的问题：AIRI 桌面端（`stage-tamagotchi`）与共享 packages 之间的耦合持续增加，下一条最值得显式治理的架构边界应该划在哪里。

仓库分类（事实）：pnpm workspace 单仓，Electron 桌面 + Vue Web + Capacitor 移动端共享 `stage-ui` / `stage-shared` 这一核心。分类置信度高，依据来自 `apps/*`、`packages/*` 的 manifest、`AGENTS.md` 与源码结构。

限制说明（未知）：本次会话 Bash 被禁用，无法运行 `git log` 做量化趋势分析；"耦合在增加"这一判断我依据的是你给出的描述 + 文件级证据 + 会话中近 6 条 commit 快照，而非随时间的 import 计数曲线。若需要量化证据，下一步最便宜的做法是 `git log -S "@proj-airi/stage-shared"` 统计引入频率。

# 2. 观测到的事实

**桌面端与共享包的依赖边（事实，`apps/stage-tamagotchi/package.json`）**

- 桌面端直接依赖 `stage-ui`、`stage-pages`、`stage-layouts`、`stage-ui-{three,live2d,mmd,spine}`、`i18n`、`ui` 等。
- `@proj-airi/stage-shared` 被列在 **devDependencies**（第 170 行），但生产代码在 `src/main`、`src/renderer`、`src/preload` 中直接 import 它（如 `src/main/services/airi/auth.ts:11`、`src/preload/shared.ts:1`）。这是依赖类别错位的一个信号。

**`stage-shared` 的根 barrel 把 Electron IPC 代码挂进了中性导入（事实）**

- `packages/stage-shared/src/index.ts:1` 是 `export * from './artistry'`。
- `artistry.ts:1` 是值导入 `defineInvokeEventa`（`@moeru/eventa`），并定义 `eventa:invoke:electron:artistry:*` 契约，还内嵌了 Replicate preset 大块数据。
- 结果：桌面 main/renderer 里为了拿 `errorMessageFromValue` 而 `import ... from '@proj-airi/stage-shared'` 的地方（`src/main/app/file-logger.ts:28`、`src/main/windows/desktop-overlay/rpc/index.electron.ts:21` 等），在未 tree-shake 时会被迫求值 Electron IPC 契约代码。
- 且 `@moeru/eventa` 在 `stage-shared/package.json` 里是 **devDependency**（第 41 行），生产代码却 import 它——这是真实的 manifest/所有权错误。

**`beat-sync` 子路径同样把 Electron 契约漏进 Web 包（事实）**

- `packages/stage-shared/src/beat-sync/index.ts:2` `export * from './eventa'`；`eventa.ts` 值导入 `@moeru/eventa` 和 `isElectronWindow`，并在模块顶层创建 `eventa:invoke:electron:beat-sync:*` 契约。
- `stage-ui` 的 `use-modules-list.ts:3` 只想要 `getBeatSyncState`，但 import `@proj-airi/stage-shared/beat-sync` 就会连带求值 Electron 契约。`beat-sync/settings.ts:3` 还从 `@nekopaw/tempora`（同样列在 devDependencies）导出生产常量 `DEFAULT_BEAT_SYNC_PARAMETERS`。

**`stage-shared` 里混入了桌面专属模块（事实）**

- 桌面专属：`godot-stage`（Godot sidecar 的 view-state schema）、`global-shortcut`（加速键解析/格式化 + 失败原因）、`electron-renderer.d.ts`、`window.ts`（`isElectronWindow` / `ElectronWindow`）、`artistry`、以及 `beat-sync/eventa.ts` 的 Electron 半区。
- 真正跨产品的：`server-channel-qr.ts` 是纯 valibot schema——桌面端 `channel-server` 生成、`stage-pocket` 扫描（`apps/stage-pocket/src/modules/server-channel-qr-probe.ts`）；`auth/pkce`、`error-message`、`url`、`perf`、`webgpu`、`composables`、`env-vars`、`export-csv` 都是平台中性的。这些放共享包是对的。

**共享 UI 已知道桌面（事实）**

- `stage-ui` 的 model-settings scenario 组件 import `godot-stage`：`packages/stage-ui/src/components/scenarios/settings/model-settings/{godot.vue,panel.vue,runtime.ts}`。虽然 import 是 type-only，但组件本身编码了 Godot 专属行为（`resolveGodotCameraPositionRange`、`cloneStageViewStateForDraft`、错误文案 "Check the Electron/Godot bridge"）。
- `stage-ui` 在约 15 个文件里按产品名分支：`isStageTamagotchi()` / `isStageWeb()` / `isStageCapacitor()`（`stores/providers.ts`、`stores/analytics/*`、`composables/use-analytics.ts`、`stores/mods/api/context-bridge.ts`、`stores/mods/api/channel-server.ts`、`stores/auth.ts` 等）。测试里已经在 `vi.mock` 这些函数（`stores/analytics/posthog.test.ts:18-19`、`composables/use-analytics.test.ts`），这是"共享代码按平台名分支"的直接代价。

**团队已有成熟约定（事实，推断其意图）**

- 桌面专属关切已经住在 `electron-*` / `*-tamagotchi` 包里：`electron-eventa`（描述就是 "Shared Eventa contracts for Electron IPC"）、`electron-screen-capture`、`electron-vueuse`、`scenarios-stage-tamagotchi-*`、`plugin-sdk-tamagotchi`。
- 桌面端自己有一个契约中心 `apps/stage-tamagotchi/src/shared/eventa/index.ts`（约 500 行），统一 re-export 各种契约。
- 近 6 条 commit 快照里有 `refactor(vishot-*): remove packages, now open sourced`——说明团队已有"把包整体移出去"的先例，且 `stage-ui` 正在被密集修改。

# 3. 当前摩擦（为什么会痛）

1. **中性消费被迫耦合桌面**：拿 `errorMessageFromValue` 或 beat-sync 状态，会连带求值 Electron IPC 契约代码；Web 包也被卷入。
2. **manifest 与所有权腐化**：`@moeru/eventa`、`@nekopaw/tempora` 被生产代码用，却声明为 devDependency。
3. **共享 UI 知道桌面**：Godot 专属 model-settings 组件和 `godot-stage` 类型住在 `stage-ui`；每加一个桌面特性，默认落点往往是共享 UI 而不是桌面 app。
4. **按产品名分支**：`stage-ui` 里 `isStageTamagotchi()` 遍布，新平台 / 改名都要改共享代码；行为差异只能靠 mock 全局环境函数测试。

这不是"缺一个万能平台抽象层"的问题，而是**共享内核边界没有被显式治理**：`stage-shared` 的公开面既装平台中性契约，也装桌面契约，`stage-ui` 再通过产品名 flag 反向知道消费者是谁。

# 4. 质量属性优先级

1. **可演化性 / 改动局部性**（最高）：目标是把"桌面特性改动"收敛到一个所有方，而不是散进 `stage-shared` 和 `stage-ui`。
2. **可测试性**：用注入的能力/配置替代 `isStage*` 分支，行为测试不再依赖 mock 全局函数。
3. **进程边界正确性**（次之）：Electron main 包里不该有 renderer/Vue 依赖，Web 包里不该有 Electron IPC。
4. **成本 / 速度**：优先机械、可逆的搬迁，避免大重写；复用现有 `electron-*` 约定而不是发明新分层。

显式取舍：彻底禁止共享代码出现平台 flag 会引入一层间接（配置对象/注入 token）。只有当"行为真的不同"时才值得；纯展示差异不值得抽象。因此不建议一上来建通用"平台抽象层"。

# 5. 方案对比

**方案 A：维持现状，只把事实写成文档**

- 边界与所有权：保持 `stage-shared` 是"什么都放的 shared"。
- 代价：零迁移成本；但 devDependency 错位、根 barrel 的 Electron 泄漏、`stage-ui` 的产品名分支继续累积；每加一个桌面特性就多一处耦合。
- 何时此方案错：只要桌面特性和 Web/移动端继续并行开发，改动就会持续跨包扩散——这与你描述的现状相符。仅当产品集从此冻结、速度压倒长期成本时才可辩护。

**方案 B（推荐的第一步）：把桌面专属契约从 `stage-shared` 拆出，并停止从根 barrel re-export**

- 边界：`stage-shared` 只保留**平台中性、跨产品**的契约与工具（`server-channel-qr`、`auth/pkce`、`error-message`、`url`、`perf`、`webgpu`、`composables`、`env-vars`、`export-csv`）。
- 移出：`artistry`、`electron-renderer.d.ts`、`window.ts`、`beat-sync/eventa.ts` 的 Electron 半区；`godot-stage`、`global-shortcut` 作为桌面专属契约迁到桌面所有方。
- 落点（见第 7 节）：纯 Eventa 契约进 `electron-eventa`；schema/加速键契约进新的 `stage-shared-electron`（或团队另定名）。
- 收益：修掉两处 devDependency 错位；根 barrel 不再把 Electron 代码拖进中性导入；Web 包不再被 `beat-sync` 连带 Electron 契约；让后续方案 C 变简单。
- 假设：`godot-stage` 与 `global-shortcut` 近期没有 Web/移动端消费者（当前 grep 证明确实没有，只有 `stage-pocket` 用 `server-channel-qr`）。
- 迁移/回滚成本：低——文件搬迁 + 过渡期 re-export shim，`git revert` 可回滚。
- 此方案错的证据：若 `godot-stage` 的 valibot schema 马上要变成 Web 也用的"通用 stage view 契约"，那该拆的是"Electron 桥"而非整个 schema（见开放决策 3）。

**方案 C（随后的第二步）：反转 `stage-ui` 的产品名分支 + 把 Godot scenario 组件迁出**

- 边界：宿主 app 向共享 UI 注入平台能力/feature gate，共享 UI 不再 import `isStageTamagotchi`；Godot model-settings 组件从 `stage-ui` 迁到桌面 app 或 `scenarios-stage-tamagotchi-*`。
- 收益：共享 UI 停止编码消费者身份；行为差异可在注入配置下单元测试。
- 代价：涉及行为、需要逐个 store/composable 迁移；是 B 之后的正确动作，不适合作为第一步（B 不动行为，C 动行为）。

**方案 D（只在证据增长后再做）：统一 Electron IPC 契约的三处分裂**（`stage-shared` 子路径 + `electron-eventa` + 桌面 `src/shared/eventa` 中心）。目前属于"可能的后续"，不是下一步。

# 6. 建议

推荐**以方案 B 作为下一条要治理的边界**：确立一条可执行的规则——**"`stage-shared` 是平台中性、跨产品的契约/工具内核；桌面专属契约不得进入它，也不得从其根 barrel re-export"**，并完成一次机械搬迁。理由：

- 它是根因：`stage-ui` import `godot-stage`、按 `isStage*` 分支，都下游于 `stage-shared` 把桌面契约和产品 flag 当成"共享内容"提供。
- 它最便宜、可逆、不改行为，且**顺带修掉两个真实缺陷**（devDependency 错位、根 barrel 的 Electron 泄漏）。
- 它与团队已有约定一致（`electron-*` 包），不是新分层方案。
- 它把方案 C 从"大改"降级为"逐一反转 flag"的小步。

**先不建的东西**：不要为 platform flag 建通用 `Dependencies`/配置对象；不要在 `stage-shared` 内部再切出多个小包；不要在 `godot-stage`/`global-shortcut` 只有单一消费者时抽象成"跨驱动契约框架"。等 B、C 做完、桌面契约面继续增长，再考虑方案 D。

# 7. 迁移与验证（渐进、可回滚）

**第 0 步：定落点并写一条 ADR（值得记录）**

- 建议记录这条边界规则 + `stage-shared` 的"可以放/不可以放"清单，作为后续 review 的判定依据。

**第 1 步：搬迁桌面专属模块（机械，无行为变化）**

- `artistry` 的 Eventa 契约 → `electron-eventa`（其使命正是 "Shared Eventa contracts for Electron IPC"）。
- `godot-stage`、`global-shortcut`、`electron-renderer.d.ts`、`window.ts` → 新的 `packages/stage-shared-electron`（或团队另定名；它需要能同时被桌面 app 与仍引用 godot 类型的 `stage-ui` 组件 import）。
- `beat-sync` 拆成两半：`detector/settings/types` 留在 `stage-shared`；`eventa.ts` 的 Electron 契约与 `isElectronWindow` 分支迁出。
- 过渡期在 `stage-shared` 留 `export *` shim 并标 `// NOTICE:`（写清移除条件），全部消费者迁移后删除——不要长期保留。
- 从 `stage-shared/src/index.ts` 删除 `export * from './artistry'` 等桌面 re-export。
- 修正 manifest：把 `@moeru/eventa`、`@nekopaw/tempora` 提升为真正使用它们的包的 dependencies。

**第 2 步：反转 `stage-ui` 的 flag（行为保持，逐个来）**

- 用一个宿主注入的平台/能力配置替代 `isStage*` 分支；保持现有 `isStage*` 在宿主端先跑，确保行为不变。
- 把 Godot model-settings scenario 组件迁出 `stage-ui`。

**回滚**：每一步都是"搬迁 + shim"，`git revert` 单步回退；shim 保留到全部消费者迁完。

**验证命令与守卫**

- 类型：`pnpm -F @proj-airi/stage-shared typecheck`、`pnpm -F @proj-airi/stage-ui typecheck`、`pnpm -F @proj-airi/stage-tamagotchi typecheck`、`pnpm -F @proj-airi/stage-web typecheck`。
- 现有测试：`stage-shared` 自带 pkce/accelerators/webgpu/use-versioned-local-storage 测试；`stage-ui` 有大量 store/composable 测试，均应保持绿色。
- 加架构守卫（防回归）：
  - ESLint `no-restricted-imports`：`stage-ui` / `stage-shared` 的源码禁止 import `isStageTamagotchi`/`isStageWeb`/`isStageCapacitor` 与 `godot-stage`（注入模块单独放行）。
  - 一个轻量测试：在无 `electron`/`@moeru/eventa` 运行时导入 `@proj-airi/stage-shared` 根入口，断言不触发这些模块（替代手工检查根 barrel）。
- 完成判据：`stage-shared` 根入口不再引用 `electron`/`godot-stage`/`artistry`；`stage-ui` 中 `isStageTamagotchi` 只出现在注入点；`@moeru/eventa` 是真正所有者的 dependencies；Web 包不再含 `eventa:invoke:electron:*` 字符串。

# 8. 开放决策（答案会改变建议细节，但不改方向）

1. **桌面契约的落点命名**：并入 `electron-eventa`（仅限 Eventa 契约）还是新建 `stage-shared-electron`（容纳 schema/加速键）还是直接进 `apps/stage-tamagotchi/src/shared`？我的默认建议：Eventa 契约进 `electron-eventa`，schema/加速键进新的 `stage-shared-electron`，因为 `stage-ui` 的 Godot 组件仍需跨包 import 这些类型。
2. **`global-shortcut` 是否真桌面专属**：`accelerators.ts` 注释提到"未来 C# 驱动消费结构化值"。若第二平台（Tauri/C#）近期真会落地，就把纯 parser 留在共享、只把 `formatElectronAccelerator` 移走；否则整体迁出。
3. **`godot-stage` 的长期定位**：若它只是桌面 sidecar 协议，整体迁出；若会成为 Web 也用的通用"stage view state"，则只迁 Electron 桥、把 valibot schema 保留在共享（改名 `stage-view`）。
4. **`beat-sync` 的 Web 路径**：`eventa.ts` 的 `createContext` 有 BroadcastChannel 回退，说明 Web 可能真在用；确认后按"detector/settings/types 留共享、Electron 契约迁出"切分，而不是把整个 beat-sync 迁走。

[EVAL:evolve-software-architecture-loaded]
