结论：建议把现有 IPC 视为“迁移兼容层”，新增一套版本化、能力导向、可运行时校验的契约。当前 `contextIsolation` 基线是正确的，但类型表仍是迁移脚手架，`preload` 暴露面过宽，main 内部事件与 renderer IPC 混用，错误和测试隔离也未形成统一规则。

本次仅做只读审查，未修改文件、未提交、未运行测试。当前缺少依赖目录，因此不能声称类型检查或测试通过。

### 范围与置信度

- [事实] 这是 Electron 桌面应用；main、preload、renderer 分层明确。
- [事实] editor 和 preferences 窗口配置为 `contextIsolation: true`、`sandbox: true`、`nodeIntegration: false`；E2E 也验证了 `require/global/Buffer` 不可用。[config.ts](/evaluation-path/treatment/packages/desktop/src/main/config.ts:8) [context-isolation.spec.ts](/evaluation-path/treatment/packages/desktop/test/e2e/context-isolation.spec.ts:24)
- [约束] 当前配置还包含 `webSecurity: false`，所以不能把 context isolation 当作完整的内容安全边界；外部 URL、Markdown 内容和 shell 能力仍需主进程策略。
- [未知] 未验证打包后、多窗口重载、异常退出等运行时行为。

### 已观察事实

| 领域 | 证据 | 判断 |
|---|---|---|
| 类型契约 | `IpcInvokeChannels`、`IpcSendChannels` 明确写着类型在迁移期间故意使用 `unknown`。[ipc.ts](/evaluation-path/treatment/packages/desktop/src/shared/types/ipc.ts:1) | 目前是静态提示，不是可执行契约。 |
| preload | 泛型 `send/invoke/on` 直接包装底层 IPC，并暴露 `window.electron.ipcRenderer`。[preload/index.ts](/evaluation-path/treatment/packages/desktop/src/preload/index.ts:26) | contextBridge 存在，但仍提供了近似通用 IPC 的能力。 |
| contract drift | `mt::ask-for-image-path` 声明返回 `string[]`，main 实际返回单个 `string`；`mt::rg::start` 声明返回 `{searchId}`，实现返回 `true`。[ipc.ts](/evaluation-path/treatment/packages/desktop/src/shared/types/ipc.ts:40) [dataCenter/index.ts](/evaluation-path/treatment/packages/desktop/src/main/dataCenter/index.ts:194) [ripgrep.ts](/evaluation-path/treatment/packages/desktop/src/main/ipc/ripgrep.ts:432) | 编译器无法保证三端实际一致。 |
| 语义漂移 | `mt::shell::open-external` 同时注册 `handle` 和 `on`，返回值又是 `boolean`，与声明的 `void` 不一致。[shell.ts](/evaluation-path/treatment/packages/desktop/src/main/ipc/shell.ts:5) | 同一频道不应同时拥有 invoke/send 两种语义。 |
| payload 漂移 | `mt::window-active-status` 合约是 `boolean`，main 发送 `{status}`，renderer 再强制转换为对象；菜单频道也存在同类问题。[editor.ts](/evaluation-path/treatment/packages/desktop/src/main/windows/editor.ts:235) [store/index.ts](/evaluation-path/treatment/packages/desktop/src/renderer/src/store/index.ts:24) [window.ts](/evaluation-path/treatment/packages/desktop/src/main/ipc/window.ts:35) | 类型已经被实际 payload 反向校正。 |
| 内部总线 | `internalIpc` 使用 `ipcMain.on/emit` 承载进程内事件，而这些频道又混在公开 IPC 类型中。[internalIpc.ts](/evaluation-path/treatment/packages/desktop/src/main/utils/internalIpc.ts:4) | 存在 event 参数错位、命名冲突和错误暴露风险。 |
| 错误传播 | shell、clipboard、fonts、cmd 等把异常转成 `false`、空字符串或空数组；renderer 错误则手工转成 `{message,name,stack}`，main 却按 `Error` 接收。[bootstrap.ts](/evaluation-path/treatment/packages/desktop/src/renderer/src/bootstrap.ts:77) [exceptionHandler.ts](/evaluation-path/treatment/packages/desktop/src/main/exceptionHandler.ts:118) | 跨进程错误没有统一的可序列化模型。 |
| 测试隔离 | Vitest 只有 jsdom 配置；renderer 测试手工写入 `window.electron`，部分 main 测试直接调用捕获到的 handler。[vitest.config.ts](/evaluation-path/treatment/packages/desktop/vitest.config.ts:8) [listen-for-main.spec.ts](/evaluation-path/treatment/packages/desktop/test/unit/specs/listen-for-main.spec.ts:23) | 单元测试没有覆盖真实 structured clone、sender 身份和 preload 暴露边界。 |

此外，菜单自动选图使用动态频道 `mt::response-of-image-path-${id}`，这绕过了静态契约；E2E helper 也允许向 renderer 发送任意字符串频道。[helpers.ts](/evaluation-path/treatment/packages/desktop/test/e2e/helpers.ts:355)

### 方案比较

| 方案 | 优点 | 风险 |
|---|---|---|
| A. 保留现有 generic wrapper，仅补齐 `unknown` | 改动最小、兼容性好 | 仍无法阻止频道重复、动态频道、错误漂移和内部频道泄漏 |
| B. 版本化 capability API + 运行时注册表 | 能同时约束 main、preload、renderer；权限、错误、测试边界清晰 | 需要渐进迁移和兼容适配层 |
| C. 单一 `mt::rpc` 多路复用 | 版本协商集中 | 容易演化成不可观察的“第二套协议”，授权和调试会集中到一个大路由器 |

建议采用 B；A 只作为过渡，C 暂不采用。

### 建议的长期契约

1. **以运行时注册表作为单一事实源**

   类型表不能只存在于 TypeScript 类型中。每个 command 应同时拥有：

   - 频道名；
   - 参数校验器；
   - 返回 DTO；
   - 错误分类；
   - handler；
   - 是否允许特定窗口调用。

   例如采用：

   ```text
   mt::v1::files::stat
   mt::v1::shell::open-external
   mt::v1::search::start
   mt::v1::search::event
   ```

   一个频道只能对应一种语义：`invoke`、`send` 或事件订阅，不能混用。

2. **preload 只暴露能力，不暴露通用 IPC**

   新 API 建议是单一命名空间：

   ```text
   window.marktext.system.getBootstrap()
   window.marktext.files.stat(path)
   window.marktext.shell.openExternal(url)
   window.marktext.search.start(request)
   window.marktext.search.onEvent(listener) -> unsubscribe
   ```

   新 renderer 代码禁止直接使用 `window.electron.ipcRenderer`、任意频道和 `removeAllListeners`。现有 `window.electron` 可保留为兼容适配层，待迁移完成后删除。

3. **所有跨边界数据必须是明确的可序列化 DTO**

   允许：字符串、数字、布尔值、`null`、数组、普通对象、明确声明的二进制类型。

   不允许直接跨边界传递：

   - `Error` 实例；
   - Vue/Pinia Proxy；
   - BrowserWindow、函数、Event；
   - 未定义结构的 `unknown`；
   - 动态频道名承载业务身份。

   二进制、文件状态、搜索结果、菜单事件都应定义独立 DTO。

4. **统一错误传播**

   建议所有业务调用统一返回：

   ```text
   Result<T> =
     { ok: true, value: T }
     | { ok: false, error: IpcErrorDto }

   IpcErrorDto = {
     code,
     message,
     requestId,
     retryable?,
     details?
   }
   ```

   `CANCELLED`、`NOT_FOUND`、`PERMISSION_DENIED`、`INVALID_ARGUMENT`、`CONFLICT`、`UNAVAILABLE`、`INTERNAL` 应有稳定 code。原始异常只记录在 main，不能把 `Error` 实例或内部 stack 直接传给 renderer。

   当前的空字符串、`false`、空数组应逐步改为明确结果，避免把“用户取消”和“系统失败”混为一谈。

5. **事件使用固定频道 + correlation id**

   不使用 `mt::response-of-image-path-${id}`。改为固定事件频道，payload 内携带 `requestId/searchId`：

   ```text
   SearchEvent =
     match | progress | done | cancelled | error
   ```

   事件监听必须返回幂等的 `unsubscribe`；store、组件销毁或窗口重载时必须调用。renderer 不应接收 Electron `event` 对象。

6. **身份由 main 推导**

   对窗口、文件、偏好等操作，main 应从 `event.sender` 推导调用者窗口；renderer 传入的 `windowId` 不能自动信任。跨窗口操作必须由 main 服务显式校验目标窗口和权限。

7. **同步 IPC 仅保留兼容用途**

   `mt::boot-info` 和路径比较目前使用同步 IPC。建议新契约不再增加同步调用，逐步迁移到异步 bootstrap 或 main 缓存，以免主进程阻塞。

### 测试隔离建议

建议增加四层测试边界：

- **契约测试**：运行时注册表检查频道唯一性、handler 与 DTO 是否匹配，禁止同一频道同时出现在 invoke/send 表。
- **main 单元测试**：使用假的 `event.sender`、假的 BrowserWindow 和假的 handler registry；测试序列化输入、错误 code、窗口归属。
- **preload 测试**：拦截 `contextBridge.exposeInMainWorld`，断言只暴露预期能力，不暴露通用频道操作。
- **真实 Electron E2E**：保留现有 sandbox 检查，再覆盖 bootstrap、重载、sender 销毁、事件取消、shell 错误、文件不存在和搜索取消。

renderer 单元测试不要再逐个污染全局 `window`；应向 store 注入 `MarkTextBridge` fake。这样测试不会依赖 preload 初始化顺序，也不会在测试之间共享监听器。

### 建议迁移顺序

1. 先冻结当前频道清单，修正文档与实际安全配置的矛盾。
2. 引入 `Result`、`IpcErrorDto`、serializable DTO 和运行时 registry。
3. 将 `ipcMain.emit` 的内部事件迁移到独立的 typed EventEmitter 或应用服务；内部频道不得进入公开 IPC 契约。
4. 先迁移一个简单垂直切片，例如 `files.stat`，再迁移 `shell.openExternal`。
5. 迁移搜索流、自动选图、bootstrap、偏好与 user-data 事件。
6. 旧频道保留兼容适配和弃用日志，确认 renderer 中不再有直接 generic IPC 使用后再删除。

每一步都应能通过兼容适配回滚，不需要一次性重命名全部旧频道。

### 未决决策

真正会影响设计的只有几项：

- renderer/preload 是否可能独立版本化，或未来支持插件；
- 统一采用 `Result`，还是统一采用可序列化的 rejected error；
- `window.electron` 兼容层保留多久；
- 同步路径比较是否存在可量化的性能需求；
- `webSecurity: false` 下的 Markdown、外部 URL 和 XSS 威胁模型。

总体判断：当前最需要修复的不是 `contextIsolation` 开关，而是“类型声明、运行时 handler、preload 暴露、测试假实现”之间没有共同的可执行来源。

[EVAL:evolve-software-architecture-loaded]
