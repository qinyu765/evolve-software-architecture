我已把 `stage-tamagotchi` 的 Eventa/Electron IPC 现状读了一遍（main 服务、preload、renderer 消费侧、测试），下面按架构评估的框架给出建议。结论先行：**不要推翻现有 Eventa + 字符串名的方案，也不要搞大爆炸重构；先做"契约身份 + 错误信封 + 边沿校验 + 一致性测试"这四件可逆的小事，把 window-namespaced router 留作有真实压力时才做的目标态。**

## 1. 范围与置信度

- **范围**：Electron `main` ↔ `preload` ↔ `renderer` 之间可长期演进的 IPC 方案，四个权衡轴：契约版本、错误传播、测试隔离、迁移成本。
- **仓库分类**：pnpm monorepo 中的 Electron 桌面应用（`apps/stage-tamagotchi`），Vue 3 renderer，IPC 已统一走 `@moeru/eventa`，DI 走 `injeca`。**置信度高**：契约、handler 注册、消费侧、测试都直接读到了源码。
- **置信度中**：`@moeru/eventa` 的适配器内部实现（错误如何序列化、是否支持契约元数据/版本协商）未能核实——本 checkout 没有 `node_modules`。项目自带的 `.agents/skills/eventa/SKILL.md` 只说了"handler 抛错会安全地传播给调用方"和"在边沿校验数据"，没提版本机制。

## 2. 观察到的现状（带证据）

**契约定义集中在单一 barrel**。`apps/stage-tamagotchi/src/shared/eventa/index.ts:33-501` 用 `defineInvokeEventa<Res, Req>(name)` / `defineEventa<T>(name)` 定义全部契约，名字是字符串常量，例如 `eventa:invoke:electron:windows:main:devtools:open`。这里**没有**任何 version / schemaVersion / apiVersion 字段（事实：对 `shared/` 的 `contract|version|schemaVersion|apiVersion` 检索只命中 plugin host 里的插件 manifest `version: string`，那不是契约版本）。

**preload 是薄透传，不是契约强制点**。`apps/stage-tamagotchi/src/preload/shared.ts:8-30` 用 `@electron-toolkit/preload` 的 `electronAPI` + `platform` 暴露到 `window`，其中包含 `ipcRenderer`；renderer 侧 `packages/electron-vueuse/src/composables/use-electron-eventa-context.ts:18-29` 直接拿 `window.electron.ipcRenderer` 建 eventa context。也就是说 contextIsolation 开着，但 renderer 拿到的是接近原始的 ipcRenderer 面，真正的业务校验只在个别 handler 里"自愿"做。

**main 按窗口建 context，但共享同一个全局 `ipcMain`**。每个窗口 rpc 文件都 `createContext(ipcMain, params.window)`（如 `apps/stage-tamagotchi/src/main/windows/main/rpc/index.electron.ts:48`），并且大量重复 `ipcMain.setMaxListeners(0)`。我数到 **17+ 处** `setMaxListeners(0)` 加 `main/index.ts:58` 一处 `setMaxListeners(100)`，全部带着同一句 TODO："等 eventa 支持 window-namespaced contexts 后可以删掉"。这是当前最明确的既有技术债信号。

**错误传播是"抛错 + 自由文本"，没有跨 IPC 的结构化错误码**。handler 直接 `throw`（eventa 会传给 renderer），renderer 用 `errorMessageFrom(error)` 兜底（`apps/stage-tamagotchi/src/renderer/bridges/electron-auth-callback.ts:40`）。同时代码里已经有两种并存的"错误通道"先例：结果联合类型（`WidgetsIframeRequestResultPayload` 的 `ok: true/false`，`shared/eventa/index.ts:177-202`；`ElectronMcpStdioTestResult { ok, error? }`，:308-313）和异步快照字段（`ElectronGodotStageStatus.lastError`、`DesktopOverlayReadiness`）。唯一成型的结构化错误是 HTTP server 的 `HttpError`（`main/services/airi/http-server/errors/index.ts:30-45`），但那属于另一个传输层，没有复用到 IPC。

**边沿校验不统一**。Godot 侧用 Valibot 校验载荷（`main/services/airi/godot-stage/index.ts:89-95`、:227-233），MCP 侧则只有手动 `stringifyError`（`main/services/airi/mcp-servers/index.ts:66-72`，这里还用了 `error instanceof Error ? message : String`，与 AGENTS.md 的 `errorMessageFrom` 惯例不一致）。大量契约（widgets、MCP、窗口操作）没有统一请求/响应校验。

**测试隔离靠模块级 mock，没有跨边界 harness**。main 侧测试 mock `defineInvokeHandler` / `createContext` / `electron` / 兄弟 service（`main/windows/desktop-overlay/rpc/index.electron.test.ts:11-43`）；renderer 侧 mock `useElectronEventaInvoke` 并按 `event.receiveEvent.id` 分发（`renderer/stores/plugin-tools.test.ts:36-45`）。有 `resetElectronEventaContextForTesting()`（`use-electron-eventa-context.ts:39-41`）。这些对单元测试足够，但**测不到**：序列化后的错误形状、契约名拼错、handler 忘记注册、超时/Abort 行为。

## 3. 当前摩擦（真正会放大变更成本的点）

1. **契约身份只有字符串名，没有"谁必须实现它"的登记**。加/改一个契约要同时动 barrel、一个 service、一个 renderer store，且没有机器可核对的"契约→handler"对应关系；拼错名字只有在运行时才会暴露。
2. **跨进程错误退化成字符串**。自定义 `Error.code`、`cause`、`name` 在 `ipcRenderer.invoke` 序列化后大概率只剩 message，renderer 只能靠 `errorMessageFrom` 或字符串匹配做分支——这正是"不可长期演进"的温床。
3. **window-namespaced 债务在扩散**。每个新窗口都在复制 `setMaxListeners(0)` + 那句 TODO，监听器数量 = 窗口数 × handler 数，问题会随窗口增多而放大，但今天还没到必须解决的程度。
4. **测试缝只覆盖模块边界，不覆盖传输边界**。契约演进（版本、错误形状）是唯一没有任何回归保护的地方。

## 4. 质量属性优先级（明确取舍）

按对本决策的实际支配力排序：

1. **可演进性（契约身份 + 边沿契约）**——这是"长期"问题，第一优先。
2. **测试隔离/可验证性**——没有它，契约演进没有安全网。
3. **迁移成本**——仓库有明确"渐进式重构、不搞大爆炸"的惯例，必须尊重。
4. **安全/最小暴露面**——次要但要在 preload 部分点明取舍。
5. **性能**——不是问题，`setMaxListeners` 是告警抑制不是性能瓶颈；不为此引入复杂度。

## 5. 三个可选方案

### 方案 A：维持现状（基线）

保持"barrel 契约 + 每窗口 `defineInvokeHandler` + 抛错 + 模块级 mock"。**可辩护**：main/renderer 随 Electron 包原子升级，跨版本偏差窗口很小，桌面单体里逐契约版本化属于过度设计。**代价**：错误是自由文本、无契约一致性检查、window-namespaced 债务持续增长。**何时此方案错**：出现"独立于主包升级的边界"（plugin SDK、server channel）或 renderer/main 开始出现 dev 热更新漂移 bug 时。

### 方案 B：增量加固（错误信封 + 边沿校验 + 一致性测试 + 握手）

保留 Eventa 和字符串名路由，加四件事：

- `IpcErrorShape = { code, message, details?, retryable? }` + `toIpcError`/`fromIpcError`，在 handler 注册处统一包装。
- 一个 `registerIpcHandler(context, contract, schema?, handler)` helper，做 Valibot 请求校验 → 调 handler → 统一错误序列化 → 日志。
- 契约→handler 一致性测试：导入 `shared/eventa` 契约清单，断言每个 `defineInvokeEventa`/`defineEventa` 在对应 service 有注册（漏注册即红）。
- 一个 `electronIpcGetCapabilities`（或 `electronIpcHandshake`）契约，renderer 启动时校验一次 `apiVersion`，漂移就提示"重启应用"。

**边界与所有权**：把"传输边沿"变成一处所有权（registry + helper），而不是散落在每个窗口。**迁移成本**：低、可逆，逐窗口替换 `defineInvokeHandler` 即可。**何时此方案错**：如果 eventa 本身已经/将会提供契约元数据和错误序列化，那 helper 会与上游重复——所以先查上游是前置步骤。

### 方案 C：window-scoped router + 版本化契约注册表（目标态）

把 TODO 里的"window-namespaced contexts"实现出来：一个 router 拥有每个窗口的 listener 生命周期（建/删/防重复注册），契约注册表带显式 `version`/`capabilities`，删除全部 `setMaxListeners` 调用。**边界与所有权**：真正解决监听器泄漏和多窗口隔离。**代价**：前置成本最高，且依赖 eventa 上游能力（未知）。**何时才做**：两个触发信号之一——eventa 上游落地该特性，或监听器/命名空间问题造成真实事故。**现在不要做**，否则是把"尚未发生的假设需求"提前抽象。

## 6. 推荐：方案 B，把方案 C 定为文档化的目标态

理由：它在这四个权衡轴上都是最便宜的杠杆——版本用"身份稳定 + 边沿校验 + 握手"解决而不引入重型版本协商；错误用已有先例（result-union + `HttpError`）形式化而不是发明新风格；测试用"一致性 + 双端 harness"补齐唯一无保护的层；迁移逐窗口渐进、每步可回滚。

**契约版本的具体建议**（这是问题核心，分开说）：

- **channel 名是稳定身份，永不改名、不把版本塞进名字**（`...:v2` 只在破坏性变更时作为"新契约"，而不是同一契约的版本后缀）。
- **单体 main↔renderer**（随包原子升级）：不逐契约版本化，只加一次启动握手校验 `apiVersion`，这是检测 stale preload/renderer 的最便宜手段。
- **复杂载荷**：在 payload 内放 `schemaVersion: 1` + Valibot 边沿校验，收到未知版本抛 `CONTRACT_MISMATCH`（结构化码，不是字符串）。破坏性变更 = 新增契约 + 旧契约留一个发布周期 shim。
- **真正的独立版本边界**（plugin SDK 的 gamelet iframe、server channel、desktop-overlay polling）：这些边界才需要逐契约版本字段，因为"同包原子升级"假设在它们身上不成立。

**错误传播的具体建议**：

- 两条通道分工明确，别强统一：
  - **领域内可预期失败** → 响应载荷用 result-union（照搬 `WidgetsIframeRequestResultPayload` / `ElectronMcpStdioTestResult` 的先例），调用方按机器可读的 `ok`/`state` 分支。
  - **基础设施/意外失败** → 保持 eventa 的 throw，但统一序列化为 `IpcErrorShape`，renderer 一律 `errorMessageFrom` 兜底，禁止字符串匹配错误码。
- 预留机器码集合（够用即可）：`CONTRACT_MISMATCH`、`NOT_READY`、`NOT_RUNNING`、`TIMEOUT`、`VALIDATION`、`UNKNOWN`。

**测试隔离的具体建议**：

- 保留现有模块级 mock（它们对 store 单元测试是合理的），不重写。
- 新增两类：`contracts.conformance.test.ts`（契约→handler 一致性）和一个小型双端 harness（`createContext()` 内存 adapter 或真实 renderer adapter + mock ipcRenderer），专门测序列化后的错误形状、超时、`AbortSignal`。这正好补上现在完全没保护的那一层。
- 不碰 `globalThis`/`Object.defineProperty` 那套（AGENTS.md 已禁止），preload 侧如需隔离用现有 `resetElectronEventaContextForTesting`。

## 7. 迁移与验证（分步、可回滚）

1. **先查上游（半天，不写代码）**：确认 `@moeru/eventa` 是否已支持契约元数据/版本/结构化错误序列化。这决定 helper 是"薄包装"还是"与上游重复"，是唯一可能改变方案 B 细节的未知。
2. **第一步垂直切片**：挑一个窗口（建议 `desktop-overlay`，它已有契约测试和 degraded 状态先例），引入 `registerIpcHandler` + `IpcErrorShape` + 边沿校验 + 一致性测试，跑通全流程。这是最小可验证的纵向切片。
3. **横向铺开**：逐窗口把 `defineInvokeHandler(context, ...)` 替换为 `registerIpcHandler(...)`，每换一个跑一次该窗口相关测试。回滚点 = 每个窗口独立提交。
4. **加握手**：`electronIpcGetCapabilities` 一个契约，renderer 启动消费一次。
5. **退出标准（可观测）**：
   - 契约→handler 一致性测试在 CI 红即失败，新增契约必须登记。
   - 所有新增跨边界载荷有 Valibot 校验（可考虑 lint/测试强制）。
   - renderer 无字符串匹配错误码。
   - 17+ 处 `setMaxListeners` 收敛到一处或清零（这是方案 C 的完成标志，不是方案 B 的前置）。
6. **方案 C 的触发信号**：eventa 上游落地 window-namespaced，或出现真实的多窗口监听/命名空间事故。触发前保持"不做"。

## 8. 待决问题（会改变建议的问题）

1. **eventa 上游能力**：是否支持契约元数据、结构化错误序列化、window-namespaced context？（本 checkout 无 `node_modules`，需读源码或 Context7 确认。）
2. **preload 定位**：是否要把 preload 从"透传 ipcRenderer"改成"curated API 面"（contextBridge 只暴露白名单函数）？这是安全收紧 vs 迁移成本（会让 eventa renderer adapter 无法直接用 ipcRenderer）的取舍，需要拍板。
3. **独立版本边界的发布节奏**：plugin SDK 与 server channel 是否真的独立于 Electron 包升级？这决定版本字段只放 payload 还是需要逐契约版本协商。

[EVAL:evolve-software-architecture-loaded]
