# Electron 主进程 / preload / renderer IPC 长期演进建议（AIRI stage-tamagotchi）

## 1. 范围与置信度

本建议针对 `apps/stage-tamagotchi` 的 Electron 三进程 IPC 契约层如何长期演进，重点权衡你点名的四个维度：契约版本、错误传播、测试隔离、迁移成本。结论是**在 Eventa 之上做渐进式加固，而不是重建协议或立刻上代码生成**。

- **事实**：仓库已经用 `@moeru/eventa`（catalog `1.0.0-beta.8`，`pnpm-workspace.yaml:110`）做类型化 IPC，契约集中在 `src/shared/eventa/`，主进程用 `createContext(ipcMain, window)` + `defineInvokeHandler`，渲染进程用 `createContext(window.electron.ipcRenderer)` + `defineInvoke`，preload 只暴露通用 `electron`/`platform`。
- **推断**：主进程和渲染进程由 electron-vite 打包成同一个应用、由 electron-updater 整体替换，因此二者**不会像客户端/服务器那样跨版本漂移**——真正漂移的边界是插件 iframe、插件 SDK 运行时和持久化配置。
- **未知**：本次 checkout 没有安装依赖，`@moeru/eventa` 内部对错误的序列化、事件投递、correlation id 的具体语义无法直接读源码核实（下面第 8 节给出最便宜的确认方式）。

## 2. 观测事实

**契约组织与身份**
- 契约是命名字符串 + TypeScript 泛型：`defineInvokeEventa<Response, Payload>('eventa:invoke:electron:...')`，事件用 `defineEventa<Payload>(...)`（`src/shared/eventa/index.ts:33-39`）。
- 500 行的单一 `index.ts` 混着内联 interface、重导出（`./plugin/*`、`@proj-airi/electron-eventa`）和工厂函数 `createRequestWindowEventa`（`index.ts:97`）。
- 契约的**唯一身份就是名字字符串**。已有一个靠类型检查抓不到的命名 bug：`packages/electron-eventa/src/electron/window.ts:6` 的 `startLoopGetBounds` 是 invoke 契约却用了 `eventa:event:` 前缀——这正是字符串身份无法自检的实证。

**三进程接线**
- 主进程：每个窗口 `createContext(ipcMain, win)`（`windows/settings/rpc/index.electron.ts:52`），artistry bridge 另有一个**全局** `createContext(ipcMain)`（`main/index.ts:263`）。
- preload：`index.ts`/`beat-sync.ts` 都只调 `expose()`，只暴露 `electron`（即 `@electron-toolkit/preload` 的 electronAPI，含 ipcRenderer）和 `platform`（`preload/shared.ts:17-30`）。`exposeWithCustomAPI` 已定义但**当前无调用**。preload 不是按契约的 allowlist。
- 渲染进程：三个消费点各自现建 context（`pages/settings/data/components/desktop-folder-section.vue:22`、`stores/tools/builtin/widgets.ts:76`、`image-journal.ts:20`），没有共享的渲染端 context/注册表。

**版本、错误、命名空间**
- IPC 层**没有任何版本机制**。版本只存在于外部边界：插件 manifest 的 `apiVersion: 'v1'`、kit descriptor 的 `version: '1.0.0'`（`plugins/index.test.ts:110-126`），以及持久化/websocket/iframe 消息的 Valibot 校验（`main/libs/electron/persistence.ts:50`、`godot-stage/index.ts:211-228`、`channel-server/index.ts:160`）。**Valibot 用在 socket/iframe/配置文件边界，唯独没用在 Electron IPC 边界。**
- 错误有**两套并存风格**：(a) invoke 里直接 `throw`，渲染端 `try/catch` 后用 `errorMessageFrom(error) ?? fallback` 提取字符串（`desktop-folder-section.vue:27-29`、`settings/rpc/index.electron.ts:67-72`）；(b) 多结果调用返回结果对象，如 `DesktopOverlayReadiness { state, error? }`、`ElectronMcpStdioTestResult { ok, error? }`、`WidgetsIframeRequestResultPayload`（`ok: true/false` 判别联合）。**没有错误码、没有统一信封。**
- 窗口命名空间尚未实现，仓库里 4 处 TODO 指向同一个修复，并用 `ipcMain.setMaxListeners(0/100)`、`ipcRenderer.setMaxListeners(0)` 兜底（`preload/shared.ts:9-12`、`settings/rpc/index.electron.ts:47-50`、`main/index.ts:55-58`、`shared/referenced-window.ts:41-45`）。

**测试隔离现状**
- 模式 A（接线冒烟测试）：mock 掉 `defineInvokeHandler`/`createContext`，只断言服务被装配、readiness 返回什么（`desktop-overlay/rpc/index.electron.test.ts:11-35`）。
- 模式 B（进程内集成）：只 mock 掉 electron 适配器的 `createContext`，让它返回**真实的**核心 `eventa.createContext()`，然后真跑 handler + `defineInvoke`（`plugins/index.test.ts:66-75`）。这是目前最接近契约集成测试的层，但每个测试都要手写一遍 mock，没有共享假件。
- 没有真正跨进程（真实 ipcMain↔ipcRenderer）的测试，也没有“每个契约名有且仅有一个 handler”这类契约不变量测试。

## 3. 当前摩擦

- **改动放大**：新增一个契约要动三处（共享 index、某窗口的 `rpc/index.electron.ts`、渲染端调用点），无代码生成，拼错名字只会在运行时暴露为“无 handler”。
- **没有可检测漂移的缝**：名字即身份，改名/改形状后主、渲染端在运行时静默失配。
- **错误不透明**：跨进程后错误结构丢失，调用方靠字符串匹配区分“校验失败 / 不存在 / 不可用”，脆弱且每个调用点各写一套。
- **监听器累积**：无窗口命名空间 → 全局监听器只增不减 → `setMaxListeners` hack。这是唯一一个今天就在漏、且随窗口增多会恶化的真问题，仓库自己也标了 4 个 TODO。
- **测试缝半成品**：进程内集成模式很好，但缺共享假件和契约不变量检查。

## 4. 质量属性优先级

| 优先级 | 属性 | 目标 | 当前证据 | 会牺牲的属性 |
|---|---|---|---|---|
| 1 | 进程边界稳定性（契约演进 + 可升级） | 契约改动可本地化、漂移可被开发期发现 | 无版本、无校验、无命名自检 | 成本（要加少量元数据/工具） |
| 2 | 可测试性 | 通过公开契约验证行为，无需打包运行时 | 模式 B 已达标但缺共享假件 | 成本（一次性的测试基建） |
| 3 | 安全性（preload 信任边界） | preload 只暴露契约允许的面 | 目前暴露通用 ipcRenderer | 成本（后续迁移） |
| 4 | 成本 | 增量、可回滚、不重造轮子 | 团队已标准化 Eventa | — |

**性能不是本决策的驱动因素**：这是本地桌面进程，invoke 频率低，瓶颈在业务服务（Godot sidecar、MCP、模型运行时）而非 IPC 序列化。不要为此引入任何额外层。

## 5. 方案对比

**方案 A：保持现状 + 定向加固（推荐第一步）**
在 Eventa 上补三样东西：一个类型化错误信封（`code/message/cause/retryable`）、一个共享的内存 context 测试假件、一个契约命名不变量检查。等待 `@moeru/eventa` 上游补上窗口命名空间（仓库 4 处 TODO 已在等它）。
- 边界/所有权不变，Eventa 仍是传输与类型层；新增的只有 `toIpcError`/`fromIpcError` 工具和测试基建。
- 迁移成本最低、全部可加性、可随时回滚；不解决“契约数量增长后的登记簿问题”。

**方案 B：契约注册表 + 代码生成（长期方向，暂不做）**
把契约写成数据（name、request/response/event schema、version），从单一来源生成 `defineInvokeEventa` 包装、运行时校验器、preload allowlist 和主进程 handler 存根。
- 单一事实来源，边界校验和 preload allowlist 成为免费副产品；但前期工具成本高，可能和 `@moeru/eventa` 的 API 演进打架。
- **决策门**：当契约数量或跨进程消费者（例如 stage-web/mobile 复用 stage 契约、插件 SDK 版本面扩大）明显增长时再启动。

**方案 C：自建显式信封协议（否决）**
每个 invoke 包 `{ v, id, ok, result, error: { code, ... } }`，与 Eventa 解耦。
- 完全掌控版本与错误，但**重造了 Eventa 已经做的事**，迁移成本最高、有分歧风险。收益只在“要换掉 Eventa”时才成立，而现在没有换掉它的理由。

## 6. 建议

**契约版本：战略性的最小版本化，不要给 main↔renderer 建协商协议。**
主进程和渲染进程随应用原子发布，跨版本漂移的真实边界是：插件 iframe（本地 http 服务从 user-data 插件目录加载，更新后仍存在）、插件 SDK 运行时（已有 `apiVersion: 'v1'`）、持久化配置（已有 Valibot + 显式回退优先级）。因此：
- main↔renderer 的**破坏性改动直接随应用原子改**，配套一个 dev-only 的运行时 schema 校验（Valibot `safeParse` 按契约元数据生成），把失配在开发期暴露，而不是运行时协商。
- 在契约对象上加**可内省的 `version` 元数据字段**（不改 wire 格式），破坏性变化才改名字里的版本段（如 `...:v2:get-config`），加性变化继续用“字段可选 + 缺省回退”的既有风格。
- 把真正的版本化投入放到插件/iframe 和持久化边界——那里已有 `apiVersion`/`version` 和 Valibot，是唯一会跨版本共存的地方。

**错误传播：统一成“异常为主、结果对象为辅”的一种风格。**
- invoke 失败用**类型化错误信封**跨进程：`{ code: 'VALIDATION' | 'NOT_FOUND' | 'UNAVAILABLE' | 'TIMEOUT' | 'INTERNAL', message, cause?, retryable? }`。在共享包提供 `toIpcError`/`fromIpcError` 一对工具：主进程抛带 code 的错误，渲染端重建并保留结构，同时继续兼容 `errorMessageFrom` 取字符串的现有调用点。
- 多结果调用（部分成功、探测、就绪状态）继续用**结果对象判别联合**（`ok: true/false`、`{ state, error? }`）——这已经是仓库里惯用且正确的形状，把它标准化，不要再发明第三种。
- 这直接回应“错误传播”：调用方能按 code 分支，而不是按字符串猜。

**测试隔离：把模式 B 变成共享基建，再补两条廉价不变量。**
- 抽出 `createEventaTestContext()` 共享假件（真实核心 context + `dispose`），替换各测试手写的 `vi.mock('@moeru/eventa/adapters/electron/main')` 样板。
- 加一个**契约注册不变量测试**：每个契约名在每个窗口有且仅有一个 handler、且名字前缀与契约种类（invoke/event）一致——这能同时抓住 `startLoopGetBounds` 这类命名 bug 和重复注册。
- 服务测试继续走 `defineInvoke`（公开契约），不要为测私有实现新增导出或依赖袋。

**命名空间与 preload：这是最高杠杆、也是唯一在漏的真问题。**
- 优先推动/等待 `@moeru/eventa` 的窗口命名空间 context（仓库 4 处 TODO 已明确指向它），一次性删掉所有 `setMaxListeners` hack。**不要**自己并行建一层命名空间。
- preload 的**长期正确终点是按契约的 allowlist**（安全边界），但这是更大的迁移，先明确记录为方向；近期先把手写面显式命名、收缩 `exposeWithCustomAPI` 的用途或删除死代码。

**组织：契约就近归属。**
- 让 `src/shared/eventa` 保持纯类型/契约、无副作用，契约就近放到所属窗口/服务（`desktop-overlay/rpc/contracts.ts` 已经暗示了这个方向）；顺手修掉 `window.ts:6` 的命名不一致，并清掉 `index.ts:218-220` 那处重复的 `PluginCapabilityPayload` TODO。

## 7. 迁移与验证

全部步骤可加性、可回滚：

1. **第一个垂直切片**：选一个服务（建议 `desktop-overlay` 或 MCP），把它的 invoke 错误改成 `toIpcError`/`fromIpcError` 信封，并补上“唯一 handler + 命名前缀”不变量测试。这一片验证信封端到端跑通，成本一天内。
2. **第二步**：抽共享 `createEventaTestContext()`，先在 `plugins/index.test.ts` 和 `desktop-overlay/rpc/index.electron.test.ts` 落地，删除手写 mock 样板。
3. **第三步**：加契约命名 lint/类型检查（名字前缀必须匹配 `defineInvokeEventa` vs `defineEventa`）。
4. 每步之后跑 `pnpm -F @proj-airi/stage-tamagotchi exec vitest run` 与 `pnpm lint`，确认现有套件绿、无行为变化。
5. **验证清单**：契约不变量测试（唯一名/前缀）、错误形状测试（code+message 跨“进程内 context”保真）、现有的插件/desktop-overlay 套件、以及主进程日志里能按 handler 名 + 错误 code 观测失败。
6. **完成判据**：新增契约不再要求测试里重复 mock 适配器；任何 invoke 失败都能在渲染端按 code 分支；`setMaxListeners` hack 消失（在上游命名空间落地后）。

## 8. 未决问题

- **`@moeru/eventa` beta.8 的实际序列化/错误/事件语义**：本 checkout 未安装依赖，无法核实它是否已保留 `Error.name`/`code`、事件投递的 correlation key 是什么。最便宜的确认方式是 `pnpm install` 后读 `node_modules/@moeru/eventa`（或直接读该版本源码/README），**在写 `toIpcError` 信封之前先做**，否则可能和它自带的错误序列化打架。
- **preload allowlist 的时点**：现在就做（安全优先）还是等契约注册表落地后顺带生成（成本优先），取决于插件 iframe 的威胁模型——需要产品/安全确认。
- **方案 B 的触发阈值**：契约数量或跨进程消费者增长到多少才值得上代码生成，需要团队定一个可观测的门槛（例如契约数、或 stage-web/mobile 开始复用 Electron 契约时）。

[EVAL:evolve-software-architecture-loaded]
