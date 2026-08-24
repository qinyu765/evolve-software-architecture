结论：下一条最值得治理的不是继续拆分 `stage-ui`，而是建立“共享业务层 ↔ Electron 能力/IPC”的稳定边界。当前最明显的泄漏点是 Artistry，其次是 Beat Sync。

## 1. 审查范围与置信度

基线是 detached HEAD `5228f9412`（2026-07-22）。我只读取了源码、package manifest、Vite 配置和 Git 历史；工作树复核未见文件改动，也未创建提交。

- 事实判断：高置信度。
- “这是下一条最值得治理的边界”：中高置信度，取决于未来是否继续增加桌面能力。

## 2. 可验证证据

| 观察 | 证据 | 判断 |
|---|---|---|
| 桌面端直接编译共享包源码 | [`electron.vite.config.ts:139`](/evaluation-path/treatment/apps/stage-tamagotchi/electron.vite.config.ts:139)–[`148`](/evaluation-path/treatment/apps/stage-tamagotchi/electron.vite.config.ts:148) | 包边界无法通过构建产物隔离，桌面改动很容易穿透到 shared source。 |
| Electron 产品 IPC 合约已有桌面侧集中位置 | [`src/shared/eventa/index.ts:218`](/evaluation-path/treatment/apps/stage-tamagotchi/src/shared/eventa/index.ts:218)、[`499`](/evaluation-path/treatment/apps/stage-tamagotchi/src/shared/eventa/index.ts:499) | 现有架构已经具备正确的合约归属方向。 |
| Artistry 合约和传输分散在三层 | [`stage-shared/src/artistry.ts`](/evaluation-path/treatment/packages/stage-shared/src/artistry.ts)、[`artistry-autonomous.ts:4`](/evaluation-path/treatment/packages/stage-ui/src/stores/modules/artistry-autonomous.ts:4)、[`comfyui.vue:25`](/evaluation-path/treatment/packages/stage-pages/src/pages/settings/providers/artistry/comfyui.vue:25)、[`artistry-bridge.ts:452`](/evaluation-path/treatment/apps/stage-tamagotchi/src/main/services/airi/widgets/artistry-bridge.ts:452) | shared UI、共享页面和桌面 main 都理解 Electron IPC，职责重复。 |
| Beat Sync 也把 Electron transport 放进 shared | [`detector.ts:159`](/evaluation-path/treatment/packages/stage-shared/src/beat-sync/detector.ts:159)、[`eventa.ts:11`](/evaluation-path/treatment/packages/stage-shared/src/beat-sync/eventa.ts:11) | `stage-shared` 同时承担领域逻辑、运行时判断和 Electron transport。 |
| 已有可复用的注入式边界 | [`plugin-host-debug.ts:81`](/evaluation-path/treatment/packages/stage-ui/src/stores/devtools/plugin-host-debug.ts:81)、[`App.vue:139`](/evaluation-path/treatment/apps/stage-tamagotchi/src/renderer/App.vue:139) | 不需要引入新的“大平台服务”框架，现有 bridge 模式足够作为迁移模板。 |

Git 历史也支持这一判断：

- 最近 240 条限定路径的 commit 中，有 57 条同时修改了 `apps/stage-tamagotchi` 与 `stage-ui`、`stage-shared` 或 `stage-pages`。这不是问题的单独证明，但说明跨包变更已经频繁发生。
- `4febd46ba`、`97f53a818` 曾连续调整 Beat Sync 的 contract 和 transport。
- `4e6da5ef0` 引入 Artistry 时，同时修改桌面 main、`stage-shared`、`stage-ui` 和 `stage-pages`。
- `9ffebd236` 已经抽出了通用 `electron-eventa`，说明团队已有“抽离 Electron 通用能力”的方向；目前缺的是产品级 IPC 与共享业务层之间的归属纪律。

## 3. 当前主要摩擦

[事实] 共享层现在混合了三类职责：

1. 跨平台领域逻辑和 UI 状态；
2. `isStageTamagotchi` 等运行时判断；
3. `window.electron`、Electron Eventa context、原始 IPC 地址和屏幕捕获等桌面实现。

[推断] 真正增加维护成本的不是“共享代码很多”，而是一个桌面能力往往同时修改：

- `apps/stage-tamagotchi/src/main`；
- `apps/stage-tamagotchi/src/shared/eventa`；
- `packages/stage-shared`；
- `packages/stage-ui`；
- `packages/stage-pages`。

[事实] Artistry 还存在重复的 `widgetsAdd` IPC 创建和多处 Electron context 获取。Beat Sync 的共享测试覆盖也不足，当前没有针对其 Electron 生命周期的专门测试。`stage-shared` 的运行时 Electron 依赖还出现在 devDependencies 中，进一步说明运行时边界没有完全清晰。

## 4. 方案比较

| 方案 | 优点 | 代价与风险 | 判断 |
|---|---|---|---|
| 维持现状 | 不需要迁移；新增功能最快 | 每个桌面能力继续把 Electron 分支带入 shared；测试难以覆盖真实 transport；跨包改动继续扩大 | 只有在桌面能力基本冻结时才合理 |
| 注入运行时能力/port | 保留 `stage-ui` 的共享业务价值；Electron 细节集中到桌面端；Web 可提供另一实现；易测试 | 需要一次 bootstrap wiring 和接口设计 | **推荐** |
| 大规模拆成 `stage-ui-core`、`stage-ui-desktop` 等包 | 编译边界最强 | 会触及大量 deep imports 和 source aliases，短期变更面过大；可能把合理的共享业务也拆碎 | 目前过早 |
| 只把所有 contract 移到 `electron-eventa` | 能减少部分地址重复 | 通用 Electron 包不应拥有 Artistry、Beat Sync 这类 AIRI 产品语义；transport 耦合仍会留在 shared | 只能作为局部动作，不能单独解决问题 |

## 5. 推荐目标形态

```text
stage-ui / stage-pages
        ↓ 注入的领域能力
neutral capability contract / shared domain types
        ↑                         ↑
Web implementation       Electron renderer adapter
                                  ↓
                  desktop eventa contracts
                                  ↓
                  Electron main services/native APIs
```

建议的归属规则：

- `@proj-airi/electron-eventa`：继续拥有通用 Electron 合约。
- `apps/stage-tamagotchi/src/shared/eventa`：拥有只属于 AIRI 桌面端的 Artistry、窗口、插件、Widget 等 IPC 合约。
- `apps/stage-tamagotchi/src/main/services`：拥有持久化配置、provider、原生能力和 IPC handler。
- `stage-ui` / `stage-pages`：只依赖按领域划分的能力接口，不直接创建 Electron context、不访问 `window.electron`、不写原始 Electron IPC 地址。
- `stage-shared`：保留跨平台数据类型、纯逻辑和确实中立的协议；逐步移除 Electron screen capture、Electron Eventa 等具体 transport。

接口应按领域拆分，例如 `ArtistryRuntime`、`BeatSyncRuntime`，不要新增一个包含所有能力的 `PlatformService` 大对象。现有 `PluginHostDebugBridge` 已经证明这种注入方式适合本仓库。

## 6. 渐进路线

### 第一步：先治理 Artistry

Artistry 最适合作为第一条 vertical slice，因为它：

- 有明确的桌面 main bridge；
- 同时存在 shared store、shared page 和桌面 renderer 的直接 Electron 调用；
- 已有 Web fetch fallback；
- 变更历史集中在一个相对明确的功能域。

建议顺序：

1. 保留中立的 Artistry 数据类型，但将 Electron invoke contract 归到桌面 contract 模块。
2. 让桌面 bootstrap 注入 Electron 实现，让 Web bootstrap 注入 fetch 实现。
3. 让 `stage-ui` autonomous store 和 `stage-pages` ComfyUI 页面只调用能力接口。
4. 删除重复的 `defineInvokeEventa`、Electron context 创建和 `window.electron` 访问。
5. 为能力接口、IPC 序列化、成功/失败/超时分别补测试。

### 第二步：迁移 Beat Sync

不要一次重写 Beat Sync。先拆出：

- 中立的检测参数、状态和算法；
- Web `getDisplayMedia` 实现；
- Electron screen capture 与 Eventa transport。

BroadcastChannel 如果仍然完全依赖 Web API、且不包含 Electron 专属逻辑，可以继续作为中立 transport；重点是把 `setupElectronScreenCapture` 和 Electron renderer context 移出中立 detector。

### 第三步：收紧包边界

迁移完成后再做机械治理：

- 对 `stage-ui`、`stage-pages`、中立的 `stage-shared` 设置禁止直接导入 Electron transport 的检查；
- 将真实运行时依赖放入正确的 runtime package；
- 逐步减少 `stage-ui` 的 `stores/*`、`libs/*` 等 deep exports；
- 统计一个桌面能力涉及的 package 数量是否下降。

暂时不要把整个 `stage-ui` 拆成多个新包。只有当上述边界治理后，仍然有大量无法隔离的桌面专属代码，再考虑大拆分。

## 7. 验证标准

迁移一个能力后，至少应满足：

- shared 页面和 store 不再直接访问 Electron transport；
- 每个产品 IPC contract 只有一个归属；
- Web 和桌面入口都明确提供能力实现；
- 测试覆盖 payload 序列化、错误映射、超时和生命周期；
- Beat Sync 额外覆盖 start、stop、restart、窗口关闭；
- 桌面设置页、Artistry headless generation 和 Beat Sync 做一次打包运行验证；
- 新增桌面能力不再默认同时修改多个 shared package。

需要保留的开放决策是：未来是否会有第二个 Electron 桌面应用。如果只有 `stage-tamagotchi`，产品 IPC contract 保持 app-local 最简单；如果会复用到多个桌面应用，再单独建立 contract-only package。

本次未修改文件、创建提交或改变外部状态；也未运行可能产生缓存的构建流程。以上结论来自本地源码、manifest、配置和 Git 历史的只读检查。

[EVAL:evolve-software-architecture-loaded]
