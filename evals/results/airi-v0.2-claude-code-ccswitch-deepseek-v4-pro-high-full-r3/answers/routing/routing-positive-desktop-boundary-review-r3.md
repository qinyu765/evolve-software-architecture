# AIRI 桌面端（stage-tamagotchi）进程与 package 边界评估

## 1. 范围与置信度

**评估对象**：`apps/stage-tamagotchi` 的 main / preload / renderer 三层，以及它与 `packages/` 中共享包（`stage-ui`、`stage-shared`、`stage-pages`、`electron-eventa`、`electron-vueuse`、`plugin-sdk`、`plugin-sdk-tamagotchi`、`plugin-protocol`）的边界，目标是为未来插件能力与多窗口扩展找一条可逆的演进路径。

**仓库类型判定（置信度高）**：pnpm monorepo + Electron 桌面应用，main 进程用 `injeca` 做依赖注入组合根，跨进程通信统一走 `@moeru/eventa`（类型化 invoke/event），renderer 是标准 Vue 3 应用，业务 UI/store 大量下沉到 `stage-ui`/`stage-pages` 与 web 端共享。**约束**：桌面端独有的能力（窗口、屏幕捕获、托盘、自动更新、插件 host、原生快捷键）集中在 `apps/stage-tamagotchi/src/main` 与 `src/shared/eventa`，不得污染 web 共享包。

---

## 2. 观察到的事实（证据）

**Main 进程 —— 组合根与窗口服务**
- `apps/stage-tamagotchi/src/main/index.ts` 是唯一组合根：用 `injeca.provide(...)` 注册 configs、services、各窗口 manager，最后 `injeca.start()`。窗口之间用 `dependsOn` 显式声明依赖（settings 依赖 14 项，main 依赖 13 项）。
- 每个窗口是一个 setup 函数，位于 `src/main/windows/<name>/index.ts`，并配套 `rpc/index.electron.ts` 注册 eventa invoke handler。窗口清单：about、beat-sync、caption、chat、dashboard、desktop-overlay、devtools、inlay、main、notice、onboarding、settings、spotlight、widgets（dashboard/inlay 不在组合根里直接注册，inlay 由 tray 按需调用）。
- 通用窗口工具在 `src/main/windows/shared/`（`window.ts`、`display.ts`、`persistence.ts`、`referenced-window.ts`）与 `src/main/libs/electron/window-manager/reusable.ts`（`createReusableWindow` 单例复用逻辑）。

**IPC/Eventa 边界**
- 契约集中在 `apps/stage-tamagotchi/src/shared/eventa/index.ts`（约 500 行），并按域拆分到 `plugin/{assets,capabilities,host,tools}.ts`。
- main 侧用 `createContext(ipcMain)` 或 `createContext(ipcMain, window)` + `defineInvokeHandler`；renderer 侧用 `useElectronEventaInvoke`（来自 `electron-vueuse`），其底层从 `window.electron.ipcRenderer` 建 context。
- **关键事实**：`ipcMain.setMaxListeners(0)` 散落在约 10 个文件里，且多个文件带同一句 TODO——「once we refactored eventa to support window-namespaced contexts, we can remove the setMaxListeners call」。说明 eventa 目前**没有按窗口命名空间路由事件**，窗口隔离是全局广播 + 手动过滤，作者已把它列为已知待办。

**Preload**
- 两个入口 `preload/index.ts`、`preload/beat-sync.ts` 都只是调用 `expose()`（`preload/shared.ts`）。preload 只暴露 `window.electron`（`@electron-toolkit/preload` 的 `electronAPI`）和 `window.platform`，另有可选 `exposeWithCustomAPI`。所有窗口 `sandbox: false`。
- 换句话说：preload 是**极薄的透传**，真正的「边界」是 main↔renderer 共享的 eventa 契约，preload 几乎不承载业务契约。

**Renderer**
- `src/renderer/main.ts` 是标准 Vue 入口；多个 HTML 入口（main、beat-sync）。renderer 通过 `src/shared/eventa` 契约 + `electron-vueuse` composable 与 main 通信，业务 store 大量复用 `stage-ui`。
- `src/renderer/stores/plugin-tools.ts` 把插件提供的 xsai 工具桥接进共享的 `useLlmToolsStore`，是插件能力接入聊天流的典型路径。

**插件系统（已相当完整）**
- `src/main/services/airi/plugins/`：`host/`（registry、config、debug）、`features/auto-reload`、`features/static-assets`（含 session cookie 适配器）、`kits/{gamelet,widget}`、`types.ts`。
- 依赖 `@proj-airi/plugin-sdk`（`ExtensionHost`，runtime: electron/node/web）与 `@proj-airi/plugin-sdk-tamagotchi`（gamelet/tool/widget kit）。
- 已有能力声明生命周期（announced/ready/degraded/withdrawn）、工具注册表、manifest 发现（`extensions/v1`）、enablement 持久化、静态资源服务。

**共享包边界**
- `stage-shared`：跨端小工具（auth/pkce、webgpu、global-shortcut、godot-stage、server-channel-qr、electron-renderer 全局类型、window.ts）。
- `electron-eventa`：通用窗口级 invoke 契约（screen/window/app/powerMonitor/systemPreferences/updater）。
- `electron-vueuse`：renderer 侧 electron 专用 composables + main 侧 `safeClose`/`isRendererUnavailable` 等。
- `plugin-sdk` / `plugin-sdk-tamagotchi` / `plugin-protocol`：插件 SDK、tamagotchi 专用 kit、以及一个更宏大的模块编排协议（含权限、配置、能力贡献模型）。

---

## 3. 当前摩擦（真正会让未来变更放大的地方）

1. **窗口无命名空间，是通往多窗口的头号阻塞（事实）**。eventa 目前不按窗口路由，导致 `setMaxListeners(0)` 全局放水、事件靠约定名字区分。`createContext(ipcMain, window)` 已存在但没真正发挥隔离作用。多窗口一旦落地，必须解决「哪个窗口在发起 / 事件发给哪个窗口」。
2. **契约类型三处重复（事实）**。`PluginCapabilityState`、`PluginManifestSummary`、`PluginRegistrySnapshot`、`PluginHostDebugSnapshot` 等同时出现在：
   - `apps/stage-tamagotchi/src/shared/eventa/plugin/*`
   - `packages/stage-ui/src/stores/devtools/plugin-host-debug.ts`
   - 权威来源 `@proj-airi/plugin-sdk` / `plugin-protocol`

   两处 TODO 明确写着「Replace these manually duplicated IPC types…」。这是典型类型漂移风险：改一个 capability 状态要手改三处。
3. **窗口 setup 高度模板化、近重复（事实）**。每个窗口重复 `new BrowserWindow`、preload 路径、`protectPrivilegedWindowNavigation`、`ready-to-show`、`load(withHashRoute(...))`、`createReusableWindow`、RPC 注册。`shared/window.ts` 只抽象了一小部分。加一个窗口 = 改组合根 + tray + 契约 + 手写 setup。
4. **组合根里的窗口依赖图是隐式所有权（推断）**。依赖关系靠 `dependsOn` 表达是好事，但「谁拥有哪个窗口、谁可以打开谁」散落在各 manager 的参数里，没有一个显式的窗口注册表/策略。多窗口（同类型多实例）会直接打破 `getWindow()` 单例假设和 `userFacingMainWindow` 单实例假设。
5. **插件能力模型与窗口生命周期未打通（推断）**。插件现在通过 gamelet/widget kit 在 widgets renderer 内挂 iframe，能力强但「插件能否拥有顶层窗口、能否参与窗口生命周期、权限如何执行」没有统一答案。`plugin-protocol` 里已有完整的 permission/config/capability 模型，但 tamagotchi host 是否执行权限校验**未知**（需要查证，见第 8 节）。
6. **信任边界需要留意（未知/待核）**。插件 iframe 挂在带特权 preload 的 widgets renderer 内，插件代码与宿主 preload 之间的隔离靠 iframe message-port/eventa relay 实现。多窗口插件化前应先审计这条隔离边界，避免插件获得 `window.electron` 的完整 IPC 能力。

---

## 4. 质量属性优先级（显式取舍）

| 优先级 | 属性 | 理由与取舍 |
|---|---|---|
| 1 | **可扩展性 / 可逆性** | 插件与多窗口是本次目标；所有步骤必须可逐步回滚。 |
| 2 | **边界清晰度（所有权）** | 类型单一权威来源、窗口单一注册表；牺牲一点「就近声明」的便利。 |
| 3 | **可测试性** | 通过 eventa 契约和窗口 manager 的公开行为测试，不新增 mock seam。 |
| 4 | **安全 / 信任边界** | 插件是第三方代码；隔离优先于便利，宁可插件能力受限。 |
| 5 | 性能 | 多窗口带来的额外 IPC/广播，当前不是瓶颈；避免为它引入过早优化。 |

明确**不**把「彻底统一所有插件为一个框架」「迁移到新进程模型」列为目标——那是昂贵的抽象，当前证据不支持。

---

## 5. 选项对比

### 选项 A：维持现状 + 定点修补（可辩护，但不足以支撑多窗口）
- **边界**：不新增层，只修最痛的点（契约去重、少量窗口 helper）。
- **收益**：成本最低，零风险。
- **代价**：`setMaxListeners(0)` 与窗口模板重复继续存在；多窗口一旦做，还是要回到窗口命名空间问题。**证据使其失效的点**：只要出现「同一窗口类型需要第二个实例」的需求，此选项就不够。

### 选项 B：增量加深现有 seam（推荐）
在现有结构内做三个「深模块」，不引入新框架：
1. **完成 eventa 窗口命名空间并逐窗口采纳**——消除 `setMaxListeners(0)`，让事件能按窗口路由，这是多窗口的地基。
2. **抽一个声明式窗口工厂/注册表**——把 13 个 setup 的公共生命周期收进 `createWindowManager({ route, preload, size, ... })`，产出「可复用窗口」能力；多实例只是给注册表加实例 key，而不是新写一套。
3. **契约单一权威 + 重导出**——让 `plugin-sdk`/`plugin-protocol` 成为插件相关类型的唯一来源，`shared/eventa/plugin/*` 与 `stage-ui` devtools store 只重导出；用编译期/契约测试锁住。

**收益**：每一步都是可逆小步，直接服务于插件与多窗口；不破坏现有 eventa/DI 心智模型。**代价**：需要动到 `@moeru/eventa`（窗口命名空间特性）——这是外部依赖，需确认可控性与工作量（见开放决策）。**证据使其失效的点**：如果 eventa 的窗口命名空间改造被证明短期不可行，则 B 的第 1 步需要换成「应用层自建窗口路由表」。

### 选项 C：正式「桌面 shell + 插件贡献框架」大重构
- **边界**：新建 `packages/stage-desktop-shell`，窗口与插件都作为 shell 的「贡献」注册进来，插件通过统一 contribution API 声明窗口/UI/工具。
- **收益**：最干净，插件与窗口一视同仁。
- **代价**：迁移面大、抽象过早；当前窗口种类 14 个且形态差异大（panel/overlay/隐藏工具窗口），强行统一会制造大量「通用但没人用的壳」。**建议**：不现在做；若插件窗口需求变成「插件可声明任意顶层窗口 + 生命周期 + 权限」且出现 ≥2 个真实用例，再评估。

---

## 6. 推荐方向

**采用选项 B（增量加深现有 seam）**，并明确「什么该稳定、什么会变、什么还不知道」：

- **该稳定**：eventa 作为唯一 IPC 契约机制；`injeca` 作为 main 组合根；`plugin-sdk`/`plugin-protocol` 作为插件类型与协议的权威来源；窗口的「创建/导航/持久化」生命周期作为共享工厂。
- **会变**：窗口是否单例（→ 实例 key 化）；插件能贡献的能力面（iframes → 可能到顶层窗口）；契约类型的物理位置（但语义稳定）。
- **还不知道**：`@moeru/eventa` 窗口命名空间的可控性与工期；插件是否需要真正顶层窗口；权限模型是否要在 host 强制执行。

**第一刀垂直切片建议**：拿「notice」窗口做窗口命名空间 + 声明式工厂的首个迁移对象（它最简单、`createRequestWindowEventa` 已经是参数化工厂的雏形，`src/shared/eventa/index.ts:97`），跑通「同类型窗口两实例、事件互不串扰」的验收测试后，再推广到 settings/chat/widgets。

---

## 7. 迁移与验证（全部可逆）

**迁移步骤（每步可独立回滚，不改变对外行为）**

1. **基线盘点**：写一个只读的「窗口清单」测试/文档，枚举所有窗口 manager、route、preload、invoke 契约和 handler 注册点。这既是回归基线，也是后续审计 `setMaxListeners(0)` 的清单。
2. **采纳窗口命名空间（外部依赖先确认）**：确认 `@moeru/eventa` 是否本组织可控；先在 notice 窗口切到 window-scoped context，验证两实例隔离，删掉该文件的一处 `setMaxListeners(0)`。回滚 = 恢复原 context 调用。
3. **抽 `createWindowManager` 声明式工厂**：定义 `{ route, preload, defaultBounds, alwaysOnTop, onCreated, onClosed, setupInvokes }` 描述符，把 `createReusableWindow` + 导航保护 + `ready-to-show` + 持久化收进去。逐个窗口迁移，setup 函数签名先保持不变；每个窗口迁移后用现有 `*.test.ts` 回归。多实例能力 = 描述符加 `instanceKey`。
4. **契约去重**：把 `plugin-sdk`/`plugin-protocol` 定为唯一来源，`shared/eventa/plugin/*` 与 `stage-ui/src/stores/devtools/plugin-host-debug.ts` 改为 `export type { ... } from ...`。删除三处重复定义。加一个类型级断言（`expectType`/`satisfies`）防漂移。
5. **插件窗口能力（延迟到最后）**：若需要，给插件 host 增加一个 window kit，让插件通过窗口注册表（而非直接碰 Electron）开窗，并配套 capability/permission 门控。先只支持 gamelet/widget kit 已覆盖的 iframe 场景。

**验证方法**

- **类型检查 + lint**（项目要求）：`pnpm type-check`、`pnpm lint`，每个迁移步后跑。
- **契约漂移测试**：断言 `shared/eventa/plugin/*` 的类型与 `plugin-sdk` 权威类型可赋值（新增 `*.test.ts`，模式参照现有 `shared/eventa/plugin/domains.test.ts`、`widgets-gamelet-request.test.ts`）。
- **多窗口验收测试**：同一窗口类型开两个实例，断言 lifecycle 事件互不串扰、invoke 路由到正确实例。这是第 2/3 步的核心退出条件。
- **架构守卫（可选）**：一条 lint 规则或测试，禁止 `ipcMain.setMaxListeners(0)` 出现在非白名单路径，作为迁移进度标尺。
- **运行时冒烟**：参照 `scripts/desktop-overlay-live-window-smoke.ts` 与 `src/shared/desktop-overlay-live-window-smoke.ts` 的既有模式，跑「main + 两个 settings 窗口 + 一个插件 widget」的端到端冒烟；打包冒烟用现有 `pnpm -F @proj-airi/stage-tamagotchi` 命令族。
- **单元测试走公开接口**：窗口 manager 与插件 host 的测试通过返回的 manager 对象（`getWindow`/`openWindow`/`pushWidget` 等）断言，不新增仅用于 mock 的私有导出。

---

## 8. 开放决策（答案会改变推荐）

1. **`@moeru/eventa` 的窗口命名空间特性是否可控、工期如何？** 这是选项 B 第 1 步的前置。若不可控，改为在应用层维护窗口路由表。**最便宜的求证方式**：查 `node_modules/@moeru/eventa` 源码与仓库是否本组织所有（`moeru-ai` 是同一 org，大概率可控，但需确认）。
2. **插件是否需要「顶层窗口」还是 iframe 已够？** 决定是否做插件 window kit。若仅需 iframe，第 5 步可无限期推迟。
3. **权限模型是否要在 tamagotchi host 强制执行？** `plugin-sdk` 里有 permissions service、`plugin-protocol` 里有完整 `ModulePermissionDeclaration`，但 host 是否接线**未知**。多窗口/插件扩大攻击面前应查证并补齐。
4. **多窗口语义**：是「同类型多实例」（如多个 chat 窗口）还是「更多窗口类型」？前者要求实例 key 化（第 3 步），后者只需继续加 setup。两者迁移优先级不同。
5. **插件 iframe 的信任边界审计**：插件代码当前挂载在带特权 preload 的 widgets renderer 内，隔离是否足够（iframe 是否拿到 `window.electron`）需要专门审计后再放行窗口级插件能力。

---

**一句话结论**：当前架构已具备可复用的 eventa 契约层、injeca 组合根和相当完整的插件 host；长期方向不是推倒重来，而是完成「窗口命名空间」这个已声明的待办、把重复的窗口 setup 收进声明式工厂、把插件契约类型归一到 SDK——三步各自可逆，多窗口和插件能力都会顺势落地，而不是另起框架。

[EVAL:evolve-software-architecture-loaded]
