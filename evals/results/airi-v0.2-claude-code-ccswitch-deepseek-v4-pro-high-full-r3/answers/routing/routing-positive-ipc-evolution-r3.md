# Electron IPC 长期演进方案（只读评估，不改代码）

## 1. 范围与置信度

要回答的问题是：在 AIRI 现有 Electron 架构下，如何设计 main / preload / renderer 之间可长期演进的 IPC 契约，重点权衡**契约版本、错误传播、测试隔离、迁移成本**四个维度。

仓库分类置信度：**高**。这是一个 pnpm monorepo 里的 Electron 桌面端（`apps/stage-tamagotchi`），IPC 已经统一收敛到 `@moeru/eventa`（版本 `1.0.0-beta.8`，见 `pnpm-workspace.yaml:110`），并且已有明确的注入式测试接缝。结论基于源码与现有测试证据，`@moeru/eventa` 库本体未安装（`node_modules` 不存在），其 Electron 适配器内部的错误序列化细节属于「未知」，已在文中标注。

## 2. 观察到的现状

**契约是字符串命名、单一事实来源。** 所有契约集中在 `apps/stage-tamagotchi/src/shared/eventa/index.ts`（约 500 行）及其子模块 `shared/eventa/plugin/*.ts`，用 `defineInvokeEventa<Res, Req>(name)` / `defineEventa<Payload>(name)` 定义，名字是稳定字符串（如 `eventa:invoke:electron:windows:main:center`）。main 与 renderer 都 import 同一份契约定义。（事实）

**preload 是薄透传，不是真正边界。** `preload/shared.ts:17-29` 只把 `@electron-toolkit/preload` 的 `electronAPI` 暴露为 `window.electron`，外加 `platform`。它**没有**逐契约枚举方法。renderer 侧在 `packages/electron-vueuse/src/composables/use-electron-eventa-context.ts:26-28` 里拿 `window.electron.ipcRenderer` 自己 `createContext(...)`。也就是说，renderer 在运行期面对的是「整个 ipcRenderer」，而不是白名单化的类型化 API。（事实）

**main 按窗口注册 handler。** 每个窗口管理器 `createContext(ipcMain, window)`（如 `main/windows/main/rpc/index.electron.ts:48`），把 `context` 注入 `createXService({ context, ...deps })`，服务内部 `defineInvokeHandler(context, contract, handler)`。handler 通过 `options.raw.ipcMainEvent.sender.id` 与 `window.webContents.id` 比较来做「发送者隔离」（`main/services/electron/window.ts:44-122`）。另有全局单例 context：`createServerChannelService` 用 `createContext(ipcMain)`（不带 window，`channel-server/index.ts:457`）。（事实）

**renderer 调用层。** 通过 `useElectronEventaInvoke(contract)` → `defineInvoke(context, contract)`，或直接 `useElectronEventaContext()` + `defineInvoke`。（事实）

**契约没有任何版本机制。** 在 `shared/eventa/index.ts` 里 grep `version|compat|deprecat` 无匹配。演进只靠「新增名字」或「就地改 payload 类型」。（事实）

**错误传播是两种风格混用。** 一种是 throw 并依赖 eventa 透传（`app.test.ts:55` 断言 `rejects.toThrow('Failed to open path')`）；另一种是把错误编码进结果对象（`DesktopOverlayReadiness.error`、`ElectronMcpStdioTestResult.error`，`shared/eventa/index.ts:72,268-276`）。嵌套错误在 handler 边缘用 `errorMessageFrom` 拍平后再 throw。eventa 的调用类型带 `ResErr/ReqErr` 泛型（`use-electron-eventa-context.ts:35` 的 `InvokeEventa<Res, Req, ResErr, ReqErr>`），说明它有类型化错误通道；但跨 Electron IPC 究竟保留 `stack`、自定义 Error 类字段还是只剩 `message`，属于**未知**。（事实 + 未知）

**测试隔离已经靠 DI 接缝实现，但有一块盲区。** 服务函数接收 `context` 参数，测试注入内存版 `createContext()`（来自 `@moeru/eventa`），在同一个 context 上注册 handler、再 `defineInvoke` 或 `context.emit` 驱动（`electron/app.test.ts:33-44`、`airi/widgets/index.test.ts:38-59`）。widgets 测试还伪造了 `raw.ipcMainEvent.sender` 来覆盖发送者隔离。但 `window.ts` 里那十几处 `sender.id` 守卫**没有**对应测试；electron 适配器本身只有一处用 `vi.mock('@moeru/eventa/adapters/electron/main')` 做了「接线」验证（`desktop-overlay/rpc/index.electron.test.ts:17-31`），没有做「跨进程往返」验证。（事实 + 推断）

**存在独立版本边界。** 插件 SDK（`@proj-airi/plugin-sdk`、`plugin-sdk-tamagotchi`）、插件 iframe gamelet 中继、server channel（`@proj-airi/server-runtime`）会跨独立发布版本。`packages/plugin-sdk-tamagotchi/src/gamelet/events.ts:23-34` 明确写着 "Stable invoke name shared by the host relay and mounted gamelet iframe handler"，契约名 `eventa:invoke:gamelet:iframe:request` 是**文档化的跨版本稳定串**。插件契约里还有 `proj-airi:plugin-sdk:...` 前缀（`capabilities.ts:40`），以及「手动复制 SDK 类型、待改 re-export」的 TODO（`capabilities.ts:42-44`）。（事实）

**已知摩擦信号。** `ipcMain.setMaxListeners(100)` / `setMaxListeners(0)` 出现在 `main/index.ts:55-58`、`main/windows/main/rpc/index.electron.ts:43-46`、`preload/shared.ts:9-12` 三处，都挂着同一个 TODO：等 eventa 支持「窗口命名空间 context」后移除。说明当前「多窗口共享同一批 IPC 通道 + 全局监听器」是个被承认的暂态。（事实）

## 3. 当前摩擦（变化放大点）

1. **preload 没有可供演进的白名单面。** 因为 preload 透传的是 raw `ipcRenderer`，类型契约只是 renderer 侧的编译期约定。任何窗口的 renderer 被攻破后都能 invoke 任意已注册 channel；同时「preload API 表面」这个概念不存在，未来想逐窗口收窄或迁移时没有抓手。
2. **窗口路由是手写且分散的。** `sender.id === webContents.id` 判断在每个服务里重复实现，而这段正是内存 context 测试覆盖不到的语义。
3. **错误策略不统一。** 调用方无法一致地区分「预期业务失败」和「handler/传输崩溃」，也无法知道跨 IPC 后哪些错误信息还保留。
4. **单一大文件 `shared/eventa/index.ts` 是高频热点。** 不同领域（window、widgets、MCP、Godot、auth、i18n、updater）都往里加，跨独立版本边界的契约和纯壳内契约混在一起，难以按域定版本策略。
5. **跨版本表面只有「稳定字符串」承诺，没有协商机制。** 插件/服务端与壳一旦版本错位，只会表现为「handler 没注册 / payload 形状不符」的隐性失败。

## 4. 质量属性优先级

针对本决策，按优先级排序（明确取舍）：

1. **测试隔离**（已是最强项，必须保住并补盲区）
2. **可演进性 / 契约版本化 + 增量迁移**（用户的核心诉求）
3. **错误传播保真度 / 可调试性**
4. **安全（preload 暴露面）**——桌面应用约束，虽不在四轴里但必须纳入
5. **迁移成本**——要求每步可回滚、可灰度
6. **性能**——Electron IPC 开销不是瓶颈，不参与本次权衡

## 5. 方案对比

### 方案 A：保留现有「共享契约 + DI context 接缝」，做四点定向加固（推荐）

- **边界**：eventa 契约仍是唯一事实来源；preload 从「raw ipcRenderer」变成「每窗口的契约名白名单转发器」；版本化只加到真正跨独立发布的边界；错误走统一 envelope；发送者隔离抽成可注入谓词。
- **代价**：改动是增量、可逆的，不推翻现有 DX。
- **假设**：eventa 的 `defineInvokeEventa` 人体工学值得保留，shell 内 main↔renderer 同版本发布，因此壳内契约不需要运行时版本协商。
- **风险**：如果团队确实需要「运行时 schema 校验 + 生成式 preload」级别的强保证，方案 A 只到「白名单 + 约定 + 测试」这一层，不够硬。

### 方案 B：schema 优先的生成式、版本化 RPC 层（大爆炸式）

- **边界**：为每个契约写 Valibot/JSON Schema，codegen 出「preload 桥 + 双侧运行时校验 + 版本化通道名 + 错误 envelope + 握手协商」。
- **好处**：边缘校验最强，兼容矩阵显式，安全面最小。
- **代价**：约 40 个契约全部重走流水线，替换 eventa 目前轻量的 `defineInvokeEventa` 体验，diff 巨大，且**在跨版本表面真正需要之前属于过度设计**——与仓库「渐进式重构、深模块、避免过度抽象」的既有准则冲突。
- **反证信号**：只有当插件/服务端频繁出现跨版本破坏、且编译期类型已无法兜住时，才值得把方案 B 的部分（schema + codegen）提上日程。

结论：**方案 A 为主，把方案 B 的元素（schema 校验、codegen）作为「当某个边界确实出过跨版本事故后」的升级手段，而不是第一步。**

## 6. 建议

### 6.1 契约版本：只给「跨独立发布边界」上版本，壳内保持无版本 + 增量改名

- **壳内 main↔renderer（同版本原子发布）**：不引入版本字段。破坏性变更用「新名字」而不是「就地改类型」，例如 `electronXyzV2`；类型系统在编译期就把两侧同时拦住，零运行时成本。就地改 payload 形状是当前唯一的危险源，写进准则即可。
- **插件 SDK / server channel / iframe gamelet 中继（跨独立发布）**：加显式版本。优先用**能力探测**（一个 `getProtocolInfo` 契约返回 `{ protocolVersion, features }`，双方据此协商），对 SDK 的事件串改用**版本后缀名**（编译期可见），二者可并存。
- **不要**把 `version` 字段塞进业务 payload 作为唯一机制——它容易被遗忘且失败是隐性的；如果要用版本字段，它属于**信封**而不是业务数据。
- 用一份 ADR 记录：哪些边界算「独立发布」、破坏性变更的改名前缀规则、旧名保留多久。仓库 `docs/` 目前没有 ADR 目录，这是第一个。

### 6.2 错误传播：先定一个显式政策，再补一个往返测试

- 定义统一 envelope：**预期/业务失败作为数据返回**（`{ ok: false, error: { code, message, cause?, retryable? } }`），**意外错误/传输错误才 throw**。
- 跨 IPC 只承诺 `message` 存活；`stack`、自定义 Error 类字段是否保留以「往返测试实测结果」为准，不要依赖 prototype 恒等或类名。
- handler 边缘继续用 `errorMessageFrom` 拍平，避免把不可序列化的原始错误直接抛过边界。
- 现有 `DesktopOverlayReadiness.error`、`ElectronMcpStdioTestResult.error` 这类已编码错误的契约，顺势统一到 envelope；throw 型契约（如 `createAppService`）保持 throw，但文档写明「跨 IPC 后只剩 message」。

### 6.3 测试隔离：把「发送者隔离」变成可注入谓词，补一条真实边界往返测试

- 保留现有「服务接收 `context` + 测试注入内存 context」的接缝——这是本仓库 IPC 测试隔离最值钱的设计，不要为它再包一层 service。
- 把 `window.ts` 里重复的 `options.raw.ipcMainEvent.sender.id === webContents.id` 抽成一个可注入的 `isFromSender(raw)` 谓词，让内存 context 测试能直接覆盖「来自其他窗口应被忽略」的语义（现在只有 widgets 一个用例伪造了 `raw`）。
- 增加一条**适配器往返测试**：用假的 ipcMain/ipcRenderer 对（或真实适配器在 node 环境）验证三件事——响应正常往返、`throw new Error(...)` 后 renderer 侧 rejection 的 message 保真度、未知 channel 的行为。这条测试是内存 context 测试**刻意跳过**的那层边界，专门用来把「未知」（stack/自定义字段是否存活）变成「事实」。

### 6.4 preload：从 raw `ipcRenderer` 收敛到「每窗口契约白名单」

- 保持 eventa 适配器接口不变，preload 传入一个**过滤后的 `ipcRenderer` 门面**：`invoke/send/on` 先按「该窗口注册的契约名集合」校验 channel。白名单可以直接从窗口管理器已经在构建的 contract 集合推导，避免双写。
- 这样既缩窄安全暴露面，又给了「preload 表面」一个真实可演进的抓手，同时不破坏 renderer 侧 `getElectronEventaContext()` 的现有用法。首步可用开发开关灰度。
- 顺带的好处：窗口路由问题（`setMaxListeners(0)` 的 TODO）可以在白名单/窗口命名空间落地时一并消化；若 eventa 1.0 已提供 window-namespaced context，则应等待上游能力，**不要自己再造一套窗口路由**。

### 6.5 配套小重构

- 把 `shared/eventa/index.ts` 继续按域拆成 `windows/`、`mcp/`、`godot-stage/`、`widgets/` 等模块，index 保留 re-export 兼容旧 import 路径。低风险，且为「按域上版本」铺路。
- 清理 `Record<string, any>` 到 `Record<string, unknown>`（widgets 的 `componentProps`、`payload` 等），把「JSON 结构化克隆安全」这一约束显式化；真正的插件/MCP 动态数据可留在 `unknown`，但不要留 `any`。

## 7. 迁移与验证

按可回滚的增量步骤推进，每步单独可合：

1. **拆契约模块**（无行为变化）：`index.ts` 保留 re-export。验证：`pnpm -F @proj-airi/stage-tamagotchi typecheck`、`pnpm -F @proj-airi/stage-tamagotchi exec vitest run`、`pnpm lint` 全绿。
2. **统一错误 envelope**：先只改那几个已返回 `{ error }` 的契约并写文档，不动调用方。
3. **抽取 `isFromSender` 谓词** + 补内存 context 下的忽略用例。
4. **加适配器往返测试**，把错误保真度从「未知」变「事实」。
5. **preload 白名单**：开发开关灰度 → 默认开启。验证无 renderer 调用回归（现有测试 + 一次手动 smoke）。
6. **跨版本协商**：仅在插件/服务端确实发生过版本错位事故后，为那一个边界加 `getProtocolInfo` 探测或版本后缀名。

回滚：每步都是加法；index re-export 保住旧路径；preload 白名单可关。完成标准：上面每步的测试命令全绿，且往返测试给出「哪些错误字段能跨 IPC 存活」的明确答案。

## 8. 待决问题（答案会影响建议）

1. **插件/服务端与壳是否真的独立发布？** 若插件永远随壳一起打包，跨版本版本化可以整体推迟。最便宜的确认方式：看插件分发路径——`devtools-sample-plugin` 表明插件是**运行时动态加载**的，推断为「是，独立发布」，需实机确认插件市场/安装源。
2. **eventa 的 Electron 适配器跨 invoke 到底保留 `stack` 还是只剩 `message`？** 需安装依赖读适配器源码，或直接写第 6.3 节的往返测试实测。
3. **团队接受「手维护的每窗口契约注册表」，还是需要生成式 preload？** 前者 DX 轻、够用；后者安全面最硬但引入 codegen。建议先用前者，出过事故再升后者。
4. **eventa 1.0 的 window-namespaced context 是否已在 roadmap 上？** 若在，`setMaxListeners` 三处 hack 应等上游，不自己实现窗口路由。

一句话结论：**当前「共享契约 + DI context 接缝」的骨架是对的，不要推翻；要补的是四个定点缝——跨独立发布边界才上版本、错误走统一 envelope、发送者隔离变成可测谓词、preload 从 raw ipcRenderer 收窄为每窗口白名单。**

[EVAL:evolve-software-architecture-loaded]
