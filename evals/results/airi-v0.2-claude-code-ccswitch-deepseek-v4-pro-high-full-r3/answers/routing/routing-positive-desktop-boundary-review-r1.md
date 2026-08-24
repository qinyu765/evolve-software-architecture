# AIRI 桌面应用架构评估（main / preload / renderer / 共享包边界）

## 1. 范围与置信度

评估对象是当前桌面应用 `apps/stage-tamagotchi` 的进程边界与共享包边界，面向两个未来诉求：**插件能力** 与 **多窗口扩展**。只给建议，不改代码。

仓库分类：**Electron 桌面应用**（不是 Tauri）。判定依据：`apps/stage-tamagotchi/package.json` 的 `main: "./out/main/index.js"`、`electron-vite`/`electron-builder` 构建、`electron` catalog 依赖；`crates/` 是遗留的旧 Tauri 桌面。Tauri 适配器只部分适用（本地桌面壳、窗口生命周期、IPC 契约、权限），进程模型不同（Node main 而非 Rust）。置信度：高。

## 2. 观察事实

| 声明 | 证据 | 类型 | 置信度 | 对决策的影响 |
| --- | --- | --- | --- | --- |
| 桌面是 Electron 三进程（main/preload/renderer）+ 共享包 | `electron.vite.config.ts` 三段构建、`src/main`、`src/preload`、`src/renderer` | 事实 | 高 | 后续所有边界都围绕这三段 |
| IPC 契约集中在单一 hub 文件 | `src/shared/eventa/index.ts`（约 500 行，defineEventa/defineInvokeEventa + re-export） | 事实 | 高 | 契约的组织方式是主要摩擦点之一 |
| eventa 尚不支持「窗口命名空间」上下文 | 多处 TODO：`src/main/index.ts:55-58`、`src/preload/shared.ts:9-12`、`windows/main/index.ts:211-214`、`windows/shared/referenced-window.ts:41-44`；handler 里手写 `sender.id === window.webContents.id`（`services/electron/window.ts:45-121`） | 事实 | 高 | 多窗口安全扩展的基础缺口 |
| 主进程是大型 DI 组合根，全部窗口/服务在 `whenReady` 一次装配 | `src/main/index.ts:113-270`，injeca `provide('windows:*')` | 事实 | 高 | 窗口创建不是统一策略，惰性创建是临时处理（desktop-overlay 的 NOTICE） |
| 窗口接线方式不统一（三种） | 12 个窗口走 injeca provider；`inlay` 由 tray 直接调用 `setupInlayWindow(...)`（`src/main/tray/index.ts:194`）；`dashboard` 定义了 `setupDashboardWindow` 但全局无任何 import | 事实 | 高 | 新增窗口无单一模式可循；存在死代码/WIP |
| 已有窗口复用抽象 | `libs/electron/window-manager/reusable.ts`（单例复用）、`windows/shared/referenced-window.ts`（按 id 多实例）、`windows/shared/window.ts`（base services + 导航保护） | 事实 | 高 | 抽象的原材料已存在，缺的是统一「窗口宿主」归属 |
| preload 极薄，只暴露 `electronAPI`（@electron-toolkit/preload）+ `platform` | `src/preload/index.ts`、`shared.ts`、`beat-sync.ts` | 事实 | 高 | renderer 的真实 IPC 面不在 preload，而在 eventa renderer adapter |
| renderer 有两个 HTML 入口，其余窗口共用 index.html + hash 路由区分角色 | `electron.vite.config.ts`（`main`/`beat-sync` 两个 input）；App.vue 用 `isSpotlightWindowRoute/isAuxiliaryChatRoute/isWidgetsWindowRoute` 分支 | 事实 | 高 | 多窗口的角色逻辑集中在共享 App.vue |
| 插件栈已成型：protocol / sdk / sdk-tamagotchi 三层 + main 进程宿主 | `packages/plugin-protocol`（纯类型+事件）、`packages/plugin-sdk`（ExtensionHost、local/remote websocket channels、node/web runtimes）、`packages/plugin-sdk-tamagotchi`（gamelet/widget/tool kits）；宿主在 `src/main/services/airi/plugins/*` | 事实 | 高 | 插件边界已相当完整，缺口在「插件能否拥有窗口」 |
| 插件清单是带权限模型的 v1 协议 | `extension.airi.json`，`apiVersion v1`，`entrypoints.{default,electron,node,web}`，权限面 apis/resources/capabilities/processors/pipelines（`packages/plugin-sdk/src/plugin-host/shared/types.ts`） | 事实 | 高 | 未来插件窗口能力应走同一权限模型，不另起炉灶 |
| 存在两条 IPC/传输通道 | eventa（renderer↔main 本地 RPC）+ server-channel（main 内嵌 loopback WS + TLS + authToken，renderer 经 `server-sdk`/`useModsServerChannelStore` 连接；`services/airi/channel-server`、`http-server`） | 事实 | 高 | 双契约体系需要明确「何时用哪条」 |
| stage-ui 是 renderer 侧业务心脏，web 与桌面共享 | `App.vue` 从 `@proj-airi/stage-ui` 拉取约 25 个 store/composable；`packages/stage-ui/package.json` 依赖 server-sdk、stage-shared、stage-ui-three 等 | 事实 | 高 | 领域逻辑在共享 renderer 包，桌面特有编排在 main，这是当前最清晰的一条边界 |
| 已有 Playwright 场景 harness 做多窗口分类 | `packages/scenarios-stage-tamagotchi-electron/src/runtime/windows.ts`（`waitForStageWindow`、`snapshotStageWindows` 按路由/标题/选择器分类） | 事实 | 高 | 多窗口验证的现成工具 |
| 无 ADR 目录；设计文档在 `docs/ai/context/plans/` | glob 无 `adr`；`docs/ai/context/plans/2026-05-09-character-cards-cloud-sync-design.md` | 事实 | 高 | 关键边界决策目前没有 ADR 承载 |
| 插件宿主内部有已知的所有权疑问 | `services/airi/plugins/host/index.ts:437-439` 的 `REVIEW:`（tool registry 归属藏在 builtInKitRuntime） | 事实 | 中 | 说明插件宿主边界仍在收敛 |

**推断（未直接读源码，需注意）**：renderer 侧 `@moeru/eventa/adapters/electron/renderer` 是通过 preload 暴露的 `electronAPI.ipcRenderer` 桥接的（因为 preload 只暴露了 `electronAPI`，且 eventa renderer adapter 必须在隔离环境下有通道）。这一点影响「窗口命名空间化」的落地位置，见第 8 节未知项。

## 3. 当前摩擦

按「改一处会扩散到几处」排序：

1. **窗口没有一个统一的「宿主」归属**。新增窗口要同时做四件事：写 `windows/<name>/index.ts`、写 `rpc/index.electron.ts`、在组合根 `main/index.ts` 加 provider、必要时加 renderer 路由/角色分支。而且目前三种接线方式并存（DI provider / tray 直接调用 / 未接线），`dashboard` 是死代码或半成品，`inlay` 绕过了 DI 图。每次新增窗口都需要「回忆」而不是「遵循」。

2. **事件路由是全局的，靠手写 sender.id 过滤**。所有 handler 挂在全局 `ipcMain` 上（`setMaxListeners(0/100)` 是症状），每个窗口服务自己判断「这个事件是不是发给我的」。这是多窗口扩展最真实的安全与认知负担——一个 handler 忘记过滤就会串窗。

3. **契约 hub 是单一巨型文件**。`shared/eventa/index.ts` 把窗口、server-channel、updater、MCP、godot-stage、shortcut、widgets、auth、i18n、plugin-host、desktop-overlay 全揉在一起（`plugin/*` 已拆出是正确方向）。它不是「错」的（有类型、可发现），但它是合并与认知的热点，且每个契约名是全局字符串，没有按窗口/域命名空间隔离。

4. **渲染器的窗口角色逻辑长在共享 App.vue 里**。每个窗口都跑同一份 App.vue，用 `isXxxRoute` 分支决定初始化哪些 store。新窗口 = 在共享组件里加分支。这是多窗口扩展在 renderer 侧的摩擦点。

5. **插件没有「拥有窗口」的路径**。现有 kit 是 gamelet/widget/tool；widget 窗口由宿主的 `windows:widgets` 管理器统一编排，插件只能往里投 iframe 内容（`widgetsIframeRequestEvent` 有 requestId 关联）。这不是缺陷（iframe 隔离反而更安全），但「未来插件能力」若指插件自带顶级窗口，目前没有这个 seam。

## 4. 质量属性优先级

1. **进程边界稳定性 / IPC 契约可演化**——插件与多窗口都在跨进程边界上扩展，契约的版本化、命名空间、错误形状是第一位。
2. **可扩展性**——插件能力面（明确的本需求）。
3. **可测试性**——不启动 Electron 就能测契约与窗口选项（仓库已有此传统）。
4. **生命周期正确性**——窗口创建/复用/销毁、启动/退出；多窗口会放大它。
5. 资源/性能——次要，不是本次决策的驱动项。

明确的取舍：可扩展性优先，但**用「一个真实变体出现才泛化」压住过度抽象**——不为尚不存在的「插件自带窗口」先建通用框架。

## 5. 选项对比

**选项 A（推荐）：先把「窗口」变成 main 内部的一等宿主能力，暂不向插件开放任意窗口。**
- 边界：新增 `WindowHost`（注册表）+ `WindowSpec`（id、路由、preload、复用策略、base services、rpc 装配、纯 options 构建）；完成 eventa 窗口命名空间；契约按域拆分。
- 带来的变化：新增窗口从「4 处复制」变成「1 份 spec + 1 份 rpc 模块」；串窗风险由框架消除。
- 假设：eventa 上游允许窗口命名空间化（未知，见第 8 节）。
- 迁移/回滚成本：低。spec 是现有 setup 函数的薄封装，随时回退到直接调用。
- 会被证明错误的情况：没有第二个真实窗口/插件窗口需求，或 eventa 上游改不动。
- 测试影响：契约测试 + Playwright 多窗口场景，正向。

**选项 B：一步到位做插件 window kit（把 WindowSpec 作为插件 kit + 权限模型暴露）。**
- 边界：插件可声明并拥有顶级窗口。
- 带来的变化：直接满足「插件自带窗口」，但引入权限面 `windows`、生命周期归属、多窗口路由到插件内容的安全面，成本高。
- 假设：插件真的有顶级窗口需求，而非 iframe 已够。
- 迁移/回滚成本：高；抽象一旦进插件协议（`plugin-protocol`）就难回退。
- 会被证明错误的情况：插件窗口需求被 iframe widget/gamelet 满足——这是目前证据指向的情况。

**选项 C（基线）：保持现状，只做增量修补。**
- 短期可辩护：14 个窗口已工作，插件 kit 已覆盖 gamelet/widget/tool。
- 代价：三种窗口接线方式继续并存，串窗过滤继续手写，App.vue 角色分支继续累积。这会在每次新窗口时收「税」。

## 6. 建议方向

选 **A**，理由：

- 它把「多窗口」做成 main 内部稳定 seam（`WindowSpec` 是声明式的、可测试的），同时**不**提前把窗口能力塞进插件协议——插件继续用已存在的 widgets/gamelet iframe（有 requestId 关联、有 iframe 隔离，反而更安全）。等出现第一个「插件确实需要顶级窗口」的真实用例，再把 `WindowSpec` 作为 kit 经现有权限模型（manifest `capabilities`）暴露，而不是另建一套。
- 「契约按域拆分」和「eventa 窗口命名空间」是纯正向的、与插件无关的债偿还。
- 明确「双传输」规则：**eventa = 本地 renderer↔main 窗口 RPC；server-channel（WS）= 网络形态边界（也服务远程/Web 插件与 web 客户端）**。这条规则值得写成 ADR，避免未来两个契约体系互相渗透。

被否的替代：B 过早泛化（违反「两个真实变体之前不建通用抽象」）；C 在已知摩擦上继续累积。

## 7. 迁移与验证（可逆、分步）

每步原则：**加新入口、保留旧入口**，spec 是薄封装，可随时回退。

**第 0 步：ADR 定调（零代码）。** 记录两条：双通道规则（eventa vs server-channel）与窗口所有权（宿主 vs 插件）。产出：`docs/ai/context/plans/` 下或新建 ADR。完成标准：团队对「插件窗口暂用 iframe，何时升级」达成书面共识。

**第 1 步：完成 eventa 窗口命名空间化。** 这是全仓库 TODO 已指向的方向。新增 `createWindowContext(ipcMain, window)`（或推动 `@moeru/eventa` 上游支持），让 handler 按窗口路由，删除 `ipcMain.setMaxListeners` 和 `sender.id` 手写过滤。验证：现有 `desktop-overlay/rpc/index.electron.test.ts` 范式（mock eventa adapter）扩展到每个窗口；断言「事件只到目标窗口」。回滚：旧 `createContext(ipcMain, window)` 双参 API 保留。

**第 2 步：引入 `WindowHost` + `WindowSpec`。** spec 字段：`id`、`route`、`preload`、复用策略（`singleton`/`multi`/`single-shot`，对应现有 reusable/referenced/一次性）、`baseServices`（复用 `setupBaseWindowElectronInvokes`）、`rpcSetup`、`buildOptions`（纯函数，参照 `desktop-overlay/window-contract.ts`）。把 14 个窗口逐个转 spec；`dashboard` 先确认归属（死代码则删、WIP 则接上）；`inlay` 从 tray 直接调用改为 `host.open('inlay')`。验证：`pnpm -F @proj-airi/stage-tamagotchi typecheck` + Playwright 场景覆盖 main/settings/chat/spotlight/inlay 的「开→关→重开」，并断言 singleton 窗口二次打开复用同一实例（`createReusableWindow` 语义）。

**第 3 步：契约文件按域拆分。** `shared/eventa/` 下拆 `windows/`、`server-channel/`、`mcp/`、`updater/`、`shortcut/` 等（`plugin/*` 已完成），保留 barrel `index.ts` 作为迁移期兼容。验证：契约名唯一性单测 + 类型检查 + 无循环导入。

**第 4 步：renderer 窗口角色显式化。** 把 App.vue 的 `isSpotlightWindowRoute/isAuxiliaryChatRoute/isWidgetsWindowRoute/isSettingsWindowRoute` 抽成 shared 层窗口描述符（窗口 id/路由 → 需初始化的运行时部分），新窗口不再改 App.vue 分支。stage-ui 的 store 保持共享，只把「角色装配」变成每窗口配置。验证：现有 Playwright 场景 + 每个角色的初始化单测。

**第 5 步（触发式，暂不做）：插件 window kit。** 触发信号：出现真实插件顶级窗口需求。届时把 `WindowSpec` 经 `registerKit` 暴露，权限走 manifest `capabilities`，不另起炉灶。

**通用验证手段**：契约测试（mock eventa adapter）、纯函数窗口选项测试（`window-contract.test.ts` 范式）、Playwright 多窗口场景（`scenarios-stage-tamagotchi-electron`）、`pnpm -F @proj-airi/stage-tamagotchi typecheck` + `pnpm lint` + 定向 `vitest run`。

## 8. 待决问题（答案会改变建议）

1. **eventa 窗口命名空间化能否在上游 `@moeru/eventa` 完成，还是需要本地 fork/适配层？** 这是外部依赖未知，决定第 1 步的成本与形态。最便宜的求证：给 `@moeru/eventa` 提 issue 或读其源码确认 context 是否已支持多 window 路由。
2. **插件的真实需求是「顶级窗口」还是 iframe widget/gamelet 已足够？** 决定是否做第 5 步。目前证据（已有 widget/gamelet/tool 三 kit、iframe 有 requestId 关联）指向后者。
3. **`dashboard` 窗口是死代码还是 WIP？** 需要 owner 确认，影响第 2 步的删/接决策。
4. **双通道（eventa + server-channel）是否长期共存？** 若未来统一，ADR 应写明收敛路径，避免契约体系分裂。
5. **preload 面是否要为窗口命名空间扩展？** 当前 preload 只暴露 `electronAPI`（推断为 eventa renderer 的桥），若窗口命名空间需要额外元数据，preload 暴露面要同步设计。

---

[EVAL:evolve-software-architecture-loaded]
