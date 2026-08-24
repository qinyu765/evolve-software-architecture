# Electron main / preload / renderer IPC 长期演进方案（仅建议，未改代码）

## 1. 范围与置信度

- **范围**：为 `apps/stage-tamagotchi`（Electron 桌面端）设计一套可长期演进的 IPC 契约方案，重点是契约版本、错误传播、测试隔离、迁移成本四个维度的权衡。目标产物是「决策就绪」的建议，不是实现。
- **仓库分类**：Electron + TypeScript + Vue 的 pnpm monorepo；IPC 层基于 `@moeru/eventa`（catalog 版本 `1.0.0-beta.8`，见 `pnpm-workspace.yaml:110`），main 用 injeca 做依赖注入。
- **置信度**：对代码结构为**高**（全部来自源码阅读）；对 `@moeru/eventa` 内部实现为**中**——本次 checkout 没有安装 `node_modules/@moeru/eventa`，我对它的行为判断来自 `.agents/skills/eventa/SKILL.md`、`.d.ts` 类型用法（如 `InvokeEventa<Res, Req, ResErr, ReqErr>`）以及仓库内调用点。涉及 Eventa 内部协议的部分我在下文中标注为**推断**。

## 2. 观察到的事实

**契约定义**

- 应用级契约几乎全部堆在 `apps/stage-tamagotchi/src/shared/eventa/index.ts`（501 行），把窗口操作、server-channel、updater、MCP、widgets、godot-stage、快捷键、auth、i18n、trace 等混在一个文件里。
- 已经存在一次「按域拆分 + 兼容 barrel」的先例：`shared/eventa/plugin/{assets,capabilities,host,tools}.ts`，并由 `shared/eventa/plugin/domains.test.ts` 用 `expect(a).toBe(b)` 验证 barrel 再导出的是同一批契约对象。这是可复用的迁移模式。
- 跨应用可复用的核心 Electron 契约已经抽到 `packages/electron-eventa`（`electron.window/app/screen/systemPreferences/powerMonitor`、`electron-updater`）。
- 其他包也在各自定义 eventa 契约：`packages/stage-shared/src/beat-sync/eventa.ts`、`packages/stage-ui-three/src/trace/eventa.ts`、`packages/electron-screen-capture` 等。

**main 侧注册**

- `main/index.ts` 通过 injeca 组装约 15 个窗口管理器；每个窗口的 `rpc/index.electron.ts` 都重复 `createContext(ipcMain, window)` + `defineInvokeHandler(...)`，并重复调用 `setupBaseWindowElectronInvokes`（`main/windows/shared/window.ts:134`）。
- 多处出现同一句 `ipcMain.setMaxListeners(0)`，并带有 TODO：「eventa 支持 window-namespaced contexts 后即可移除」（`main/index.ts:55-58`、`dashboard/rpc/index.electron.ts:24-27`、`settings/rpc/index.electron.ts:47-50`、`desktop-overlay/rpc/index.electron.ts:34-37`）。这是当前 Eventa 上下文模型的已知限制：所有窗口共享 `ipcMain`，监听上限被全局抬高。

**preload / renderer 侧**

- preload 只做透传：`preload/shared.ts` 把 `@electron-toolkit/preload` 的 `electronAPI` 暴露为 `window.electron`（外加 `platform`、可选 `window.api`）。类型来自 `packages/stage-shared/src/window.ts` 的 `ElectronWindow`。
- renderer 直接拿 `window.electron.ipcRenderer` 传给 `createContext`：`stores/tools/builtin/widgets.ts:76`、`image-journal.ts:20`、`pages/settings/data/components/desktop-folder-section.vue:22` 等。也就是说，preload 暴露的是**传输层**（`ipcRenderer`），类型安全由「共享的 eventa 契约对象」而非 preload 表面承担。
- `packages/electron-vueuse` 提供了缓存式上下文 `useElectronEventaContext` / `useElectronEventaInvoke`（`use-electron-eventa-context.ts`），但仍有不少地方绕过它自行 `createContext(window.electron.ipcRenderer)`，造成重复。

**错误传播**

- Eventa 的官方规则（`.agents/skills/eventa/SKILL.md`）：「handlers 可以安全抛错，eventa 会传播给调用方」。所以当前错误传播依赖「跨 IPC 抛异常 → promise reject」。
- 但错误形态不统一：有的 handler 直接抛（`settings/rpc/index.electron.ts:67-71` 抛 `TypeError`）；有的把错误编码进 payload 字段（`DesktopOverlayReadiness.error`、`ElectronMcpStdioTestResult.error`、`ElectronGodotStageStatus.lastError`）；有的吞掉并降级（`desktop-overlay/rpc/index.electron.ts:51-59`）。
- renderer 端用 `errorMessageFrom` / `errorMessageFromValue` 把错误字符串化后展示（`spotlight.vue:56`、`image-journal.ts:174`）。但仓库里存在多个重复的本地 `errorMessageFromValue` 实现（`services/computer-use-mcp`、`plugins/airi-plugin-web-extension`、`packages/audio`），与 AGENTS.md 要求的「用 `@moeru/std` 的 `errorMessageFrom`」不一致。
- 已有**结构化错误码先例**：`packages/stage-shared/src/godot-stage/view-state.ts:154-172` 定义了 `StageViewErrorCode`（`'invalid-payload' | 'invalid-state-file' | ...`）和带 `code/message/requestId` 的 `StageViewErrorPayload`，并用 Valibot schema 解析。

**测试隔离**

- `desktop-overlay/rpc/index.electron.test.ts` 展示了当前做法：`vi.mock('@moeru/eventa')`、`vi.mock('@moeru/eventa/adapters/electron/main')`、`vi.mock('electron')`、`vi.mock('../../shared/window')`，然后断言 `defineInvokeHandler` 被调用、捕获 handler 手动执行。它测的是**注册接线**，不是真实传输。
- `window-contract.test.ts` 测试纯函数窗口配置，不碰 Electron 运行时。
- `electron-vueuse` 提供 `resetElectronEventaContextForTesting()` 重置模块级缓存上下文。
- Eventa 本身支持同进程内存 `createContext()`，仓库里已用它测过 iframe 运行时（`iframe-request.test.ts`、`eventa-runtime.test.ts`）——这是可复用的 handler 测试接缝。

**版本/兼容**

- 桌面端内部契约没有显式版本字段；两侧随应用一起发布，所以内部漂移风险低。但有两个边界是独立演进的：**plugin host**（`shared/eventa/plugin/*`）和 **widget iframe 中继**（`WidgetsIframeRequestPayload` / `WidgetsIframeRequestResultPayload`）。这些边界目前也没有 schemaVersion 或协商机制。

## 3. 当前的摩擦点

1. **契约 god-file**：`shared/eventa/index.ts` 是 500 行的混合清单，加一个端点就要动它，无法按窗口/领域判断归属。**事实**。
2. **每窗口注册样板重复**：每个 `rpc/index.electron.ts` 重复 `createContext`、`setMaxListeners(0)`、base services 调用。**事实**。
3. **preload 泄漏传输层**：renderer 直接接触 `window.electron.ipcRenderer`，一旦想改成能力面或换传输，所有调用点都要动。**事实**。
4. **错误语义缺失**：调用方无法区分「参数校验失败 / 服务不可用 / 超时 / 契约不匹配」，只能解析字符串。**推断**（由事实 3.4 推出）。
5. **测试隔离靠重度 mock**：每个窗口 RPC 测试都重复 mock Eventa + electron，且不测真实错误路径。**事实**。
6. **无版本策略**：内部靠「同时改两侧」，跨独立版本边界（plugin、iframe 中继）没有兼容策略。**事实**。

## 4. 质量属性优先级（明确取舍）

对这个决策，真正支配性的属性按重要性排序：

1. **可演进性 / 迁移成本**（用户显式要求的两个维度合并考虑）——契约要能按域演进，且每步可逆。
2. **可测试性（测试隔离）**——handlers 应能在不启动 Electron、不 mock 传输的前提下单测。
3. **类型安全 / 契约正确性**——错误传播要结构化，错误码要在类型层面可见。
4. **可运维性 / 可诊断性**——错误要带 code/cause/requestId，便于日志和排查。
5. **性能**——**不支配**。IPC 调用量低，Eventa 的 invoke 模式足够。

安全（最小化 preload 暴露面）是重要的**约束**，但不在这里排第一，因为当前 `sandbox: false` + 暴露 `ipcRenderer` 是既有事实；是否收紧属于第 8 节的开放决策。

## 5. 方案对比

### 方案 A：保留 Eventa，做「契约分层 + 声明式注册 + 结构化错误 + 边界版本化」（渐进演进）

- **边界**：契约对象仍是唯一事实源，但按域拆成模块，由 barrel 保持旧导入路径不变；每个窗口用「契约 bundle」声明它暴露哪些端点；错误用统一的 `ElectronRpcError` envelope；只对会漂移的边界加 `schemaVersion`。
- **带来什么**：消除 god-file 和注册样板；错误可在类型层面按 code 分发；handler 可用内存 context 单测。
- **迁移成本**：**低-中**。每步行为保持，barrel 再导出让旧 import 全部继续可用；可逐域回滚。
- **假设**：Eventa 的 throw-to-reject 传播行为足够可靠，不必自建 envelope 传输层。**未知**：Eventa 1.0.0-beta.8 的 `ResErr` 泛型在跨 IPC 序列化时是否保留 `name/stack/cause`（**需装依赖后读 `dist` 验证**）。
- **测试后果**：handler 测试从 mock 传输变成内存 context 测试；传输层只留一层 smoke。
- **何时此方案错**：如果最终要彻底隐藏 `ipcRenderer`（安全驱动），它只是中间态。

### 方案 B：能力面 preload 门面 + 方案 A（更高安全/隔离，更高迁移成本）

- **边界**：preload 不再暴露 `ipcRenderer`，而是从契约 bundle 生成类型化的 `window.airi.<domain>.<op>()` 门面，内部持有唯一 Eventa renderer context。renderer 不感知传输。
- **带来什么**：最小暴露面（安全）、renderer 传输无关、preload 门面可被纯函数测试、能力可协商（`window.airi.__version` + `available()`）。
- **迁移成本**：**中-高**。要触碰所有 `window.electron.ipcRenderer` 调用点，但可在保留现有 Eventa context 的前提下双轨过渡（先切门面，再下线裸暴露）。
- **测试后果**：隔离最好——preload 门面是契约的纯投影，用内存 context 就能测。
- **何时此方案错**：若团队接受「桌面端内部传输可以暴露」，它的收益主要是安全收紧，可能不划算。

### 方案 C：上游 Eventa window-namespaced context + 契约 codegen

- **边界**：修复 TODO 指向的根因（Eventa 缺 window 命名空间分发），并按契约清单生成 preload/renderer 绑定。
- **带来什么**：根除 `setMaxListeners` hack、最干净的生成式绑定。
- **迁移成本**：**高**，且依赖上游 `@moeru/eventa` 改动或本地 fork；**未知**：上游是否已计划支持。这是「昂贵抽象」，当前不建议先做。

### 方案 D：维持现状（作为对照基线）

现状在「桌面端同版本发布」的假设下仍然**可辩护**：类型安全靠共享契约对象，Eventa 已能传播异常。但 god-file、注册样板、非结构化错误、重 mock 测试会随窗口/端点数量线性放大，因此不作为推荐。

## 6. 推荐

**推荐方案 A 作为主线，把方案 B 作为后续可选切片，方案 C 明确推迟到上游支持。**

理由：A 直接消除当前最痛的三个摩擦（god-file、样板、非结构化错误），且每一步都是行为保持、可逆的渐进重构，迁移成本最低。B 的价值（安全最小暴露面）真实，但不应和 A 一起做——先让契约分层和错误 envelope 落地，门面只是把同一批契约换个暴露形状。C 是「一次性修到完美」的陷阱，应等 A/B 验证了契约形状后再评估。

四个维度的具体设计：

- **契约版本（分层，不全量加版本）**
  - 桌面端内部（main↔renderer）随应用原子发布，**不加 wire 版本**，靠类型检查 + barrel 恒等测试（复用 `plugin/domains.test.ts` 模式）保证同步。
  - 只在会独立漂移的边界显式版本化：**plugin host**、**widget iframe 中继**，以及未来任何会持久化/缓存的契约。做法：payload 增加 `schemaVersion`，边界用 Valibot 在入口解析（repo 已有 `parseStageViewSnapshotPayload` 先例）；演进规则是「只加可选字段，不删不改字段语义」；破坏性变更发新版本号 + 旧版本共存窗口。
- **错误传播（结构化 envelope + 类型化错误泛型）**
  - 定义 `ElectronRpcError`（`code: 稳定机器可读码`、`message`、`retryable`、`cause?`、`requestId?`），复用 `StageViewErrorPayload` 的成熟先例。
  - 使用 Eventa 已经暴露的 `InvokeEventa<Res, Req, ResErr, ReqErr>` 的 `ResErr` 泛型，让每个契约在类型层面声明「这个调用会以哪种错误失败」。
  - handler 继续抛错（Eventa 传播机制不变），但只抛 typed error；边界处用**一个** `toElectronRpcError` 归一化任意 throw。renderer 从「`errorMessageFrom` 字符串解析」改为「按 `code` 分发、`message` 只用于展示」。
- **测试隔离（三层，去掉重 mock）**
  1. **契约恒等测试**：barrel 再导出的是同一对象（已有先例）。
  2. **handler 单测**：用内存 `createContext()` + `defineInvokeHandler` + `defineInvoke` 直接测业务 handler，不碰 `electron`、不 `vi.mock('@moeru/eventa')`。
  3. **传输 smoke**：仅保留一层真实 Electron adapter 的端到端冒烟（类似 `scripts/desktop-overlay-live-window-smoke.ts` 的思路），覆盖「真实错误能跨 IPC 到达 renderer」这一条。
  - 抽一个 `createWindowRpcHarness` 测试辅助，替代当前 `desktop-overlay/rpc/index.electron.test.ts` 里散落的 `vi.mock`。
- **迁移成本（barrel + 逐域 + 双轨）**
  - 每步通过 barrel 保持旧 import 不变；只移动、不改行为；`git revert` 单文件即可回滚。
  - 方案 B 的 preload 门面用双轨过渡：先保留 `window.electron.ipcRenderer`，门面就绪后逐步切换调用点，最后删除裸暴露。

## 7. 迁移与验证（按序、可逆）

1. **纵向切片**：选结构最干净的 `desktop-overlay`（它已有独立 `contracts.ts`、`window-contract.ts`、测试），落地「域模块 + 声明式 bundle + typed error + 内存 handler 测试」。这一步产出可复制的样板，并回答「Eventa `ResErr` 跨 IPC 的真实行为」这个未知。
2. **拆分 god-file**：把 `shared/eventa/index.ts` 按域拆成 `windows/`、`server-channel/`、`updater/`、`mcp/`、`widgets/`、`godot-stage/`、`shortcut/`、`auth/`、`i18n/` 等，barrel 再导出，配恒等测试（完全复用 `plugin/domains.test.ts` 模式）。
3. **声明式注册**：每个窗口改成「`createContext` 一次 + 传 bundle + `defineInvokeHandlers`」，消除 `setMaxListeners` 之外的重复样板。
4. **错误 envelope 落地**：定义 `ElectronRpcError` + `toElectronRpcError`，迁移 handler 抛错与 renderer 处理。
5. **测试 harness**：抽 `createWindowRpcHarness`，把 `desktop-overlay/rpc/index.electron.test.ts` 那类测试改成内存 context。
6. **版本化边界**：给 plugin host / widget iframe 中继加 `schemaVersion` + Valibot 入口解析。
7. **（可选，后置）**：preload 能力面门面，双轨切换，最后下线 `ipcRenderer` 裸暴露。
8. **（推迟）**：Eventa 上游支持 window-namespaced context 后，移除所有 `setMaxListeners` hack。

**完成判据（可观察）**：

- 不再向 `shared/eventa/index.ts` 这个 god-file 添加任何新契约，新契约都进域模块。
- 每个 RPC 契约都有 `ResErr` 类型；renderer 按 `code` 分发而不是按字符串匹配。
- 新增 handler 的测试不出现 `vi.mock('electron')` 或 `vi.mock('@moeru/eventa')`，只在内存 context 上跑。
- 新窗口的 RPC 注册只包含「base services + 一个 bundle」，无重复样板。
- 版本化边界契约的破坏性变更会触发类型/校验失败（不是静默兼容）。

## 8. 开放决策（答案会改变推荐）

1. **plugin host 与 widget iframe 中继是否真的跨独立发布版本？** 若是，第 6/7 步的完整版本协商值得做；若仍是同仓同发，只需 schema 校验。（需产品/团队确认）**未知**。
2. **是否把 preload 收紧为能力面门面（方案 B）？** 这是安全姿态决策：当前 `sandbox: false` 且暴露 `ipcRenderer`；收紧需要产品与安全达成一致，并评估对插件 iframe 运行时的兼容影响。
3. **Eventa 的 window-namespaced context 是上游计划内还是需要本地 fork？** 决定方案 C 的时机与成本。**未知**。
4. **错误码的本地化放在 main 边界还是 renderer？** 当前 renderer 自己本地化（`spotlight.vue` 用 `t()`）；若 error envelope 在 main 生成 message，需要明确 message 是「机器日志」还是「用户可展示」。

建议下一步先从第 1 步的 `desktop-overlay` 纵向切片开始，用最小的真实迁移验证「Eventa 错误跨 IPC 的保留行为」这个唯一的技术未知，再决定是否扩大范围。

[EVAL:evolve-software-architecture-loaded]
