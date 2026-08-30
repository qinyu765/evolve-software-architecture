已完成仓库调研。结论先行：**AIRI 的 main↔renderer IPC 不需要一套通用的"契约版本协商"机制**——三者作为同一个 Electron 产物原子升级，运行时不存在版本偏差；真正的版本问题只出现在跨制品边界（plugin SDK、gamelet iframe 中继、server channel WebSocket）。长期演进的杠杆在另外三个地方：把"窗口作用域"从每个 handler 手写的 `sender` 检查收敛掉、把混乱的错误模型统一成两层、用 eventa 自带的内存 context 把测试从 mock 内部实现改为接口级隔离。

下面是按证据展开的建议。

---

## 1. 范围与信心

**决策范围**：`apps/stage-tamagotchi` 内 Electron main / preload / renderer 三层的 IPC 契约与调用方式，如何长期演进。

**仓库分类**：桌面 Electron 应用（`apps/stage-tamagotchi`），IPC 由 `@moeru/eventa` 统一承载（transport-agnostic），main 侧用 `injeca` 做依赖组装。信心：**高**——事件契约、main 注册、renderer 调用、preload 暴露、测试模式、错误表示我都逐文件核对过，证据充分。

## 2. 观察到的事实

**契约定义与分层（当前形态是合理的）**

- 契约集中在 `apps/stage-tamagotchi/src/shared/eventa/index.ts`，用 `defineInvokeEventa<Res, Req>(id)` / `defineEventa<Payload>(id)` 声明，id 是手写的字符串（如 `eventa:invoke:electron:shortcut:register`）。
- 已有域拆分雏形：`src/shared/eventa/plugin/{host,capabilities,tools,assets}.ts` 是源，`index.ts` 用兼容 barrel 重导出，并用 `domains.test.ts` 锁定重导出关系。
- 纯 Electron API 契约放在 `packages/electron-eventa`（`window.ts`、`app.ts`、`electron-updater/index.ts`），renderer 侧组合子放在 `packages/electron-vueuse`（`getElectronEventaContext()`）。
- 已有 `createRequestWindowEventa(namespace)` 工厂（`shared/eventa/index.ts:97`）从 namespace 推导 id，减少手写字符串出错——这是值得推广的族级契约模式。

**main 侧注册（窗口作用域是手写的，这是最大摩擦）**

- 每个窗口用 `createContext(ipcMain, window)` 建 context，`defineInvokeHandler(context, contract, handler)` 注册。
- 但 `ipcMain` 是进程级全局的，所有窗口注册**同一批 channel**，于是每个 handler 都要手写 `options.raw.ipcMainEvent.sender.id === window.webContents.id` 来挡掉别的窗口：
  - `services/electron/window.ts:45-122`（约 8 处）
  - `services/airi/auth.ts:86,160`
  - `services/airi/widgets/index.ts:29-38`（抽了个 `isFromWindow`，但仍是每 handler 调用）
  - `windows/spotlight/index.ts:129-137`
- 为让 N 个窗口同 channel 共存，到处 `ipcMain.setMaxListeners(0)`，并带 TODO：*"once we refactored eventa to support window-namespaced contexts, we can remove setMaxListeners"*（`main/index.ts:55-58`、`windows/main/index.ts:214`、`windows/desktop-overlay/rpc/index.electron.ts:34-37`）。这是对问题最准确的自我诊断。

**renderer 侧调用（入口不统一）**

- 部分走 `getElectronEventaContext()`（`packages/electron-vueuse/.../use-electron-eventa-context.ts`，惰性单例 + `resetElectronEventaContextForTesting`）。
- 部分直接 `createContext(window.electron.ipcRenderer)`（`renderer/stores/tools/builtin/widgets.ts:76`、`image-journal.ts:20`、`pages/settings/data/components/desktop-folder-section.vue:22`）。

**preload（暴露面过大）**

- 所有窗口共用一个 `preload/index.mjs` → `expose()`，通过 `@electron-toolkit/preload` 把**整个 `electronAPI`（含 `ipcRenderer`）**挂到 `window.electron`（`preload/shared.ts:8-30`）。
- 所有窗口 `webPreferences: { sandbox: false }`（`windows/main/index.ts:88-91` 等 12 处）。即 preload 有完整 Node 能力，且 renderer 拿到的是原始 ipcRenderer 桥。

**错误传播（当前有四种并存表示）**

- handler 直接 throw（eventa 会传播，`.agents/skills/eventa/SKILL.md:227`："Handlers can throw errors safely — eventa propagates them to the caller"），例：`channel-server/index.ts:504`、`mcp-servers/index.ts:281`。
- 判别联合结果 `{ ok: false, reason }`：`global-shortcut` 的 `ShortcutRegistrationResult`。
- 结果内嵌 `isError`/`error` 字段：`ElectronMcpCallToolResult.isError`、`ElectronMcpStdioTestResult { ok, error }`。
- 状态对象带 `error?`：`AutoUpdaterState.error`（`packages/electron-eventa/src/electron-updater/index.ts:22-44`）、`DesktopOverlayReadiness { state, error? }`。
- eventa 类型其实预留了 `InvokeEventa<Res, Req, ResErr, ReqErr>` 四个泛型（`electron-vueuse/.../use-electron-eventa-context.ts:35`），但全仓库**没有任何一处**用 `ResErr/ReqErr`，都落在默认 `Error`。

**测试隔离（当前靠 mock 内部实现，脆弱）**

- `vitest.config.ts:16-17` 设 `fileParallelism: false, maxWorkers: 1`——因为被测代码会碰进程级 `ipcMain`/electron 全局。
- `services/electron/global-shortcut.test.ts:119-130` 有一条 hack：mock `defineInvokeHandler` 时把 contract 的 `sendEvent.id` **去掉 `-send` 后缀**才能对上契约名——测试依赖了 eventa 的内部 channel 命名。
- `desktop-overlay/rpc/index.electron.test.ts` mock 了 `createContext`/`defineInvokeHandler`/`ipcMain`。
- 好的一面：`shared/eventa/widgets-gamelet-request.test.ts` 用字面量断言契约 id，说明团队已经把 id 当稳定公共契约对待。

**版本先例**

- server channel QR payload 已带显式 `version: 1`（`channel-server/index.ts:117-122`）；plugin SDK 的 `CapabilityDescriptor`、`pluginProtocolListProviders` 是跨制品类型。

## 3. 当前摩擦（根因，不是症状）

1. **窗口作用域是散落的职责**。`createContext(ipcMain, window)` 没有真正按窗口隔离 channel，sender 过滤散在 ~20 处、且每处语义略有不同（有的返回默认值、有的静默 return）。新增一个窗口或一个契约都要重新理解并复制这套守卫。
2. **错误模型没有所有权**。"该 throw 还是该返回 `ok:false`"没有规则，导致同一类失败有四种形状，renderer 侧要 `errorMessageFrom` + 判别字段混着用。
3. **测试隔离依赖 eventa 的内部实现细节**（channel 后缀、进程级 ipcMain），因此被迫串行执行，且换 eventa 版本就可能碎。
4. **契约集是一个浅模块**：500 行的扁平 index.ts 只是"契约清单"，缺少按域拆分的可读结构（plugin 子目录是正确方向，但主契约没跟上）。
5. **preload 是最大攻击面**：`sandbox:false` + 全量 ipcRenderer 暴露，renderer 一旦被注入就等同于主进程能力边界被打开。这属于必须列入约束项的风险。

## 4. 质量属性优先级（刻意排序）

1. **可演化性 / 迁移成本**（用户明确要求，也是本次的主目标）——胜过一切。
2. **可测试性 / 测试隔离**（用户明确要求）。
3. **错误可诊断性**（用户明确要求）。
4. **安全 / 最小权限**（preload 设计必须回答）。
5. **性能**——**不排前面**。控制面 IPC（快捷键、窗口、MCP）对延迟不敏感；唯一的连续路径是 `startLoopGetBounds` 的循环推送和 overlay 轮询，现有事件式设计已够，不应为此牺牲契约清晰度。

显式取舍：为换取 1–4，接受"一次机械重构 + 少量纪律性约束"，**拒绝**为 5 引入任何二进制协议或手写序列化。

## 5. 方案对比

### 方案 A：维持现状 + 局部治理

保持手写 sender 检查、mock 测试、四种错误形状，只补"契约 id 快照测试"和错误规则文档。

- 优点：迁移成本≈0。
- 缺点：每加窗口/契约，sender 守卫与 mock hack 继续复制；测试仍锁死在 eventa 内部命名；错误模型继续分叉。
- **会被证伪的信号**：窗口数、契约数、或跨 transport 需求继续增长——复制成本线性放大，届时治理成本已超过今天一次重构的成本。

### 方案 B（推荐）：收敛 seams，不引新框架

只利用 eventa 已有的能力做三件事，外加在真正的跨制品边界用 versioned envelope。

- **B1 窗口作用域收敛**：抽 `defineWindowScopedInvokeHandler(context, window, contract, handler)` 一个 helper 包住 sender 检查；长期目标是 eventa upstream 的 window-namespaced context（TODO 已写），届时删 helper。
- **B2 双层错误模型**（见 §6）：传输层统一 envelope + 领域层判别联合。
- **B3 测试 seam**：用 eventa 内存 context 替代对 `defineInvokeHandler`/channel 命名的 mock；前提是把 context 改为注入。
- 优点：长期演化成本最低，测试从"mock 实现"升为"接口级"；不破坏 transport-agnostic（server channel 同一套 eventa 继续复用）。
- 缺点：需要一次机械重构（context 注入）和团队对错误模型的纪律。
- 迁移/回滚：逐步、可逐服务提交、可回滚（每步行为不变，见 §7）。

### 方案 C：激进——自建 typed facade / codegen

preload 只暴露 `window.api.<domain>.<method>` 窄门面，main 端自动注册，甚至上 codegen。

- 优点：最强安全与契约可视化。
- 缺点：与 eventa 的 transport-agnostic 模型冲突，等于在 eventa 之上再造一层；迁移成本最高；丢掉跨 transport 复用；需要长期维护 codegen。
- **会被证伪的信号**：除非出现"renderer 代码不可信、且必须逐 channel 白名单"的强安全需求，否则不建议。

## 6. 推荐方案（B）的具体设计

### 6.1 契约版本：把"版本"用在正确的地方

- **main↔preload↔renderer：不引入运行时版本协商。** 三者随同一产物原子升级，没有"老 renderer 打新 main"的合法状态。契约 id 是**编译期稳定键**；演进规则只有两条：*只加不减*、*改名=在审查里显式可见的破坏性变更*。
- 用一个**契约注册快照测试**锁定全部 id 字符串（现有 `widgets-gamelet-request.test.ts` 已是雏形，扩成全量 sorted 列表 + 每契约的请求/响应类型名）。它让任何 id 重命名在 PR diff 里一眼可见，成本极低，不需要 codegen。
- **真正需要版本 envelope 的是三个跨制品边界**，且已有先例可循：
  1. **plugin SDK**（`pluginProtocolListProviders`、`CapabilityDescriptor`）——插件可能与宿主不同步；
  2. **gamelet iframe 中继**（`WidgetsIframeRequestPayload` 带 `requestId` 已是很好的 envelope 雏形）；
  3. **server channel WebSocket**（QR 已带 `version: 1`）。
  - 在这三处用 `{ v: 1, ...payload }` + 显式兼容策略（读旧写新 / 不识别则拒绝并报明确错误码），不要把它们和 main↔renderer 的内部契约混在一套版本机制里。
- 契约文件本身：继续把 `shared/eventa/index.ts` 的扁平清单按域拆成 `window/`、`mcp/`、`widgets/`、`auth/` 等深模块（plugin 子目录是模板），`index.ts` 只做 barrel。族级契约优先用 `createRequestWindowEventa` 这类 factory 推导 id。

### 6.2 错误传播：两层模型

- **规则（一条可执行的判据）**：调用方*需要分支处理*的预期结果 → 放进**返回类型**（判别联合，如 `{ ok: false, reason }`）；*异常条件*（bug、前置不满足、依赖不可用）→ **throw**，由传输层归一化。当前四种形状按此归并：
  - `ShortcutRegistrationResult`、`ElectronMcpStdioTestResult` 的 `ok` 判断 → 保留在领域返回类型（正确）。
  - `AutoUpdaterState.error`、`DesktopOverlayReadiness.error` → 保留（这是*状态*的一部分，不是调用失败，语义不同，不算违规）。
  - `applyServerChannelConfig` 的 throw → 改成结构化传输错误。
- **传输层 envelope**：统一为 `{ code: string, message: string, cause?: unknown }`，`code` 用每域稳定枚举，renderer 映射 i18n。**不**再依赖 `errorMessageFrom` 到处手撕 `Error.message`，也**不**依赖 Electron `ipcRenderer.invoke` 的 `Error invoking remote method ...` 包装字符串。
- 启用 eventa 已预留的 `ResErr/ReqErr` 泛型（现在全空），让"这个契约会抛什么错"进类型；至少先在新契约上落地。
- **取消/超时是传输错误的一等公民**：eventa 文档已有 `AbortController` 支持（`.agents/skills/eventa/SKILL.md:138-154`），overlay 轮询的 NOTICE 注释（`desktop-overlay-polling.ts:252-259`）正是不具备 abort 的代价。给传输 envelope 预留 `cancelled` 码位，但现在不建流式/取消框架（见 §7"暂不构建"）。

### 6.3 测试隔离：以 eventa 内存 context 为 seam

- eventa 的无 transport `createContext()`（`.agents/skills/eventa/SKILL.md:34-45` 已展示）就是现成的 fake：测试里 `const ctx = createContext()`，然后 `defineInvokeHandler(ctx, contract, handler)` + `defineInvoke(ctx, contract)` 走**真实 eventa**，不再 mock `defineInvokeHandler`，也不再需要 `-send` 后缀 hack。
- **前提改造**：服务不得自己 `createContext(ipcMain)`，必须接收注入的 context。当前反例是 `createServerChannelService({ serverChannel })` 在函数内部 `createContext(ipcMain)`（`channel-server/index.ts:451-459`）并靠全局 `serverChannelServiceRegistered` 防重——这是 testability 和 DI 双重反模式。`createWindowService`/`createWidgetsService` 已是正确形态（`{ context, window }`）。
- 一旦 context 注入到位，`fileParallelism:false / maxWorkers:1` 可移除（测试不再碰进程级 ipcMain），electron adapter 只留一个薄的 `createContext(ipcMain, window)` mock。

### 6.4 preload：收窄为类型化门面

- 现状是"暴露整个 ipcRenderer + `sandbox:false`"。方向：**把 `createContext(ipcRenderer)` 移进 preload**，preload 只向外暴露 `context.invoke/on/emit` 的类型化表面（或按域拆成 `window.airi.window`、`window.airi.mcp` …），renderer 不再直接拿 `ipcRenderer`。这同时是 allowlist 和版本化的自然 seam。
- **约束**：`contextBridge` 对暴露的对象/函数有序列化限制，eventa context 能否整体跨 bridge 需要验证；这也是为什么它是 open decision 而不是第 1 步。
- `sandbox:false` 是否能收敛到 `sandbox:true`，受制于 `uiohook-napi`、屏幕捕获、beat-sync 专用 preload 等 Node 依赖——标为约束，不在本次决策里强行解决，但 preload 门面收敛不依赖它，可先行。

## 7. 迁移与验证（可逆、分步）

每一步都保持运行时行为不变，可独立提交、可回滚：

1. **Phase 0（零行为变化，先立规则）**：写 ADR 记录两条决策——"main↔renderer 无运行时版本协商，id 是编译期稳定键"、"双层错误模型"。补全量契约 id 快照测试。
2. **Phase 1（context 注入）**：把内部 `createContext` 的服务逐个改为接收 `context`，由各窗口的 `setupXxxElectronInvokes` 统一创建。用内存 context 把 `global-shortcut.test.ts` 的 `-send` hack 替换掉，作为第一块试金石。
3. **Phase 2（错误 envelope）**：引入共享 `IpcError` + `code` 枚举，先落在一个域（建议 MCP 或 server channel），连同启用 `ResErr` 泛型。
4. **Phase 3（窗口作用域收敛）**：加 `defineWindowScopedInvokeHandler` helper，替换 ~20 处 sender 检查；同时统一 handler cleanup——`defineInvokeHandler` 返回清理函数（`windows/main/index.ts:217` 已用），但多数注册没捕获，窗口关闭后 handler 残留，应在 window 的 `closed` 事件统一 dispose。
5. **Phase 4（preload 门面，可选、最后）**：preload 内建 renderer context、收窄暴露面。

**验证方式**：每个 phase 跑 `pnpm -F @proj-airi/stage-tamagotchi typecheck` + 目标 `vitest run`；契约快照测试保证 id 未意外漂移；Phase 3 后删除 `setMaxListeners` 并确认多窗口仍各收到自己的事件（已有 `global-shortcut` 多 context 广播测试可复用）。

**暂不构建**：通用版本协商层、流式/取消框架、codegen 门面。触发再评估的信号：出现第一个需要 main↔renderer 长连接流（如模型生成进度推送）或插件宿主独立发布的明确需求。

## 8. 待定决策（回答会改变建议）

1. **eventa 是否计划 upstream "window-namespaced context"**（TODO 已写）？若短期能落地，Phase 3 的 helper 是临时的、可标注移除条件；若遥遥无期，helper 就是长期方案。
2. **preload 门面的暴露形状**：eventa context 能否直接 `contextBridge` 暴露，还是需要 preload 侧包一层薄 API？需一个 spike 验证，结果决定 Phase 4 的形态。
3. **`sandbox:false` 的收敛优先级**：是否接受"门面先收敛、sandbox 后收敛"的两段式安全路径，取决于 screen-capture/uiohook 的迁移成本评估。
4. **错误 `code` 的粒度**：按域枚举 vs. 全局统一小集合，取决于团队对 i18n 映射和调试便利的偏好——建议先在一个域跑通再定。

（未修改任何文件，以上仅为建议。）

[EVAL:evolve-software-architecture-loaded]
