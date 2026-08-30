结论：建议保留 `@moeru/eventa` 作为底层传输与 RPC 原语，但在其上增加三层边界：

1. main：按窗口管理 `WindowIpcSession`，统一授权、生命周期和 handler 清理。
2. preload：只暴露按能力划分的类型化 `airiBridge`，不再暴露原始 `ipcRenderer`。
3. renderer：只依赖 bridge/facade，不直接接触 Electron adapter。

契约采用“现有 ID 视为 v1、破坏性变更新增 v2、主进程双注册过渡”的策略。这样可以控制迁移成本，同时为插件、iframe、Godot 等潜在独立参与者保留演进空间。

## 1. 范围与置信度

本结论基于当前工作区和 Git 历史的只读检查；未修改文件、未提交、未改变外部状态，也未执行构建或测试。

以下区分：

- “事实”：可以从仓库文件或历史直接定位。
- “推断”：基于当前打包和调用方式得出的判断。
- “待确认”：需要项目约束或运行时验证才能决定。

## 2. 可核验现状

| 观察 | 证据 | 影响 |
|---|---|---|
| preload 暴露了较宽的 Electron API，renderer 可以取得原始 `ipcRenderer` | [`preload/shared.ts`](/evaluation-path/treatment/apps/stage-tamagotchi/src/preload/shared.ts:8)、[`use-electron-eventa-context.ts`](/evaluation-path/treatment/packages/electron-vueuse/src/composables/use-electron-eventa-context.ts:1) | 能力边界主要依赖约定和 main 侧 sender 检查 |
| App 级 Eventa 合约很多，但 ID 没有显式版本 | [`shared/eventa/index.ts`](/evaluation-path/treatment/apps/stage-tamagotchi/src/shared/eventa/index.ts:31) | 目前适合锁步发布，不适合独立版本演进 |
| 每个窗口重复创建 context、注册基础 handler | [`windows/main/rpc/index.electron.ts`](/evaluation-path/treatment/apps/stage-tamagotchi/src/main/windows/main/rpc/index.electron.ts:43)、[`windows/shared/window.ts`](/evaluation-path/treatment/apps/stage-tamagotchi/src/main/windows/shared/window.ts:134) | scope、清理和重复注册容易不一致 |
| 全局服务和窗口服务使用两种 IPC scope | [`channel-server/index.ts`](/evaluation-path/treatment/apps/stage-tamagotchi/src/main/services/airi/channel-server/index.ts:457)、插件服务也创建全局 context | 需要明确哪些操作允许跨窗口 |
| sender 校验散落在 window、widgets、screen-capture 等服务中 | [`widgets/index.ts`](/evaluation-path/treatment/apps/stage-tamagotchi/src/main/services/airi/widgets/index.ts:33) | 授权规则难以统一测试 |
| handler disposer 通常没有被汇总；仓库多处使用 `setMaxListeners(0)` | 相关历史提交 `743c27685`，以及多个 main/preload 文件中的监听器 workaround | 更像生命周期设计缺口，而不是单纯监听器上限问题 |
| 测试大量使用内存 Eventa context 或 mock | [`app.test.ts`](/evaluation-path/treatment/apps/stage-tamagotchi/src/main/services/electron/app.test.ts:1)、[`widgets/index.test.ts`](/evaluation-path/treatment/apps/stage-tamagotchi/src/main/services/airi/widgets/index.test.ts:1) | 业务逻辑隔离较好，但实际 Electron adapter 边界覆盖不足 |
| `packages/electron-eventa` 的 peer 范围是 `<41`，应用锁定 Electron `41.2.1` | [`packages/electron-eventa/package.json`](/evaluation-path/treatment/packages/electron-eventa/package.json)、`pnpm-lock.yaml` | 不一定已经运行时失败，但支持矩阵需要明确 |

当前应用由 Electron builder 一起打包 main、preload、renderer，这是“锁步兼容”的推断；若插件、iframe、Godot 或外部 sidecar 独立发布，契约版本的重要性会显著上升。

## 3. 当前主要摩擦

### 契约版本

现有 `eventa:...` ID 都是隐式版本。直接把所有 ID 改成 `v1` 会带来大范围迁移，而且没有必要。

建议：

- 把现有 ID 约定为 v1，不改名。
- 兼容性变更只能新增可选字段或新增 response 字段。
- 删除字段、改变字段含义、改变错误语义、收窄枚举时，新增 v2 ID。
- main 同时注册 v1/v2，两个版本都调用同一个领域服务，通过 adapter 转换 DTO。
- 增加轻量 `bridgeInfo` 或能力清单，用于诊断和独立参与者协商；锁步应用不必每次 invoke 都做握手。

### 错误传播

当前同时存在：

- 直接抛异常；
- `{ ok: false, error }`；
- `{ error?: string }`；
- `{ status: 'error' }`；
- 带 `lastError` 的状态对象。

Eventa 的远程错误序列化不应被当作业务错误协议；官方文档说明自定义 Error 属性不能稳定保留，业务 `code/details` 不应依赖 `throw new Error()` 传播。[Eventa errors 文档](https://github.com/moeru-ai/eventa/blob/main/_autodocs/errors.md)

建议区分：

- 传输/生命周期错误：reject/throw，例如 bridge 缺失、无 handler、renderer 已销毁、序列化失败。
- 预期业务失败：显式返回结果封装，例如 `ok + value` 或 `ok + { code, message, retryable, details }`。
- `code` 应稳定，UI 根据 code 做本地化；不要把 stack、密钥或内部路径返回给 renderer。
- 新接口和 v2 接口采用统一错误封装，旧接口按领域逐步迁移，不做一次性全量改造。

### 测试隔离

内存 Eventa 测试适合验证领域服务和 sender 隔离，但无法验证：

- Electron adapter 的序列化行为；
- preload 暴露面；
- BrowserWindow 关闭、reload、崩溃后的清理；
- 实际 main → preload → renderer 的版本兼容。

因此应保留三层测试，而不是全部改成 Electron 集成测试：

1. 纯 contract/DTO/schema 测试；
2. main session 的 fake window、fake sender 和 disposer 测试；
3. 少量真实 `BrowserWindow` 的 adapter smoke test。

### 迁移成本

不建议立即替换 Eventa 或建立一个新的万能 RPC 框架。AIRI 已经有大量 Eventa 合约和测试，替换会造成高迁移成本，并可能重复实现 Eventa 已经提供的事件、RPC、stream 和 transport 能力。

## 4. 方案比较

| 方案 | 兼容性 | 安全/授权 | 测试隔离 | 迁移成本 | 判断 |
|---|---|---|---|---|---|
| 保持现状，只补约定 | 低到中 | 较弱，raw `ipcRenderer` 仍暴露 | 中 | 最低 | 只能作为短期过渡 |
| Eventa + 类型化 preload bridge + window session | 高 | 强，能力和窗口 scope 明确 | 强 | 中 | 推荐 |
| 统一 `invoke(eventId, unknown)` 网关 | 理论上高 | 容易变成万能能力入口 | 中 | 高 | 当前不推荐 |

## 5. 推荐目标形态

### Shared contract

每个跨进程契约至少应有这些元信息：

- domain 和稳定 ID；
- major version；
- `invoke`、event 或 stream；
- `window`、`global` 或 `broadcast` scope；
- request/response runtime schema；
- 错误策略；
- cancellation 和窗口关闭语义。

共享 DTO 应优先使用结构化克隆友好的中立类型，避免在 shared contract 中直接暴露 `BrowserWindow`、`Display` 或 `Parameters<BrowserWindow[...]>` 这类 Electron 类型。现有 [`packages/electron-eventa/src/electron/window.ts`](/evaluation-path/treatment/packages/electron-eventa/src/electron/window.ts:1) 可作为需要逐步收窄的边界。

### Main

引入概念上的 `WindowIpcSession`：

- 每个 BrowserWindow 一个 session；
- Eventa main context 绑定目标窗口；
- 统一收集 `defineInvokeHandler` 和 `context.on` 的 disposer；
- 在 `closed`、`destroyed`、`render-process-gone`、`before-quit` 时清理 handler、订阅和 pending operation；
- sender 身份只从 Electron event 推导，不信任 payload 中的 `windowId`；
- global 服务通过显式 allowlist 接受窗口请求，不再让所有全局 handler 默认对所有窗口开放；
- `onlySameWindow` 可以作为辅助保护，但不能替代关键 handler 的授权测试。

等 session 生命周期稳定后，再逐步删除 `setMaxListeners(0)` workaround。现有 auto-updater 已经有保存 cleanup 的做法，可作为统一模式参考。

### Preload

最终只暴露类似 `airiBridge` 的能力接口：

- `window`
- `widgets`
- `mcp`
- `updater`
- `auth`
- `plugins`
- `subscriptions`

不要暴露原始 `ipcRenderer`、`send/invoke/on` 或任意 event ID 入口。当前的 [`exposeWithCustomAPI`](/evaluation-path/treatment/apps/stage-tamagotchi/src/preload/shared.ts:32) 可以作为迁移入口，但它目前先调用了宽泛的 `expose()`，不能直接视为最终安全边界。

### Renderer

`packages/electron-vueuse` 应成为 bridge 的唯一 renderer 适配层：

- stores、composables、页面只使用类型化 domain facade；
- renderer 不再直接导入 Electron Eventa adapter；
- 测试通过 fake bridge 或内存 transport 注入；
- beat-sync 当前使用 BroadcastChannel/内存 transport，应继续保持独立，不必强行转成 main IPC。

## 6. 渐进迁移与回滚

建议顺序：

1. 先建立契约清单、schema、错误码、scope 和版本规则；旧 ID 统一视为 v1。
2. 实现 `WindowIpcSession`，先迁移 window lifecycle 或 widgets 这类边界清晰的领域。
3. 为 preload 增加 typed bridge，先让 `electron-vueuse` 使用它；保留旧 raw bridge 作为临时兼容路径。
4. 按风险迁移 window/screen、widgets、MCP、Godot、updater、auth、plugins。
5. 对破坏性变更加 v2 ID，v1/v2 同时注册并转换到同一领域服务。
6. 静态检查确认 renderer 不再访问 `window.electron.ipcRenderer` 后，再移除宽泛 preload 暴露和旧 adapter。

回滚成本应保持低：

- 旧 v1 handler 在迁移完成前始终保留；
- v2 只做加法，不修改持久化格式；
- bridge 可切回旧实现；
- 删除旧 handler 必须等所有 renderer、插件和独立参与者完成迁移。

## 7. 验证标准

完成一个迁移阶段前，至少应具备：

- schema、结构化克隆和 v1/v2 DTO 兼容性测试；
- 不同窗口 sender 访问彼此 handler 的负向测试；
- duplicate registration、关闭窗口、reload、崩溃后的 disposer 测试；
- preload 只暴露 allowlist 能力的测试；
- 真实 Electron adapter 对错误传播、序列化、timeout、取消的 smoke test；
- 代表性 main → preload → renderer 集成测试；
- 静态规则禁止 renderer 直接使用 Electron IPC；
- 静态规则禁止新增未版本化 contract ID；
- listener 数量不再依赖无限制 workaround；
- 日志包含 operation、contract major、window kind、request id、latency 和 error code，但不记录敏感 payload。

## 8. 未决问题

这些问题会影响最终版本策略：

1. 所有 BrowserWindow 是否都只加载 AIRI 自己的受控内容？如果存在不可信或远程内容，typed preload bridge 应优先落地。
2. main、preload、renderer 是否永远锁步发布？若是，版本协商可保持轻量；若插件/sidecar 独立发布，则必须正式维护兼容矩阵。
3. `@proj-airi/electron-eventa` 是否应支持当前 Electron `41.2.1`？应先通过依赖和 adapter 测试明确支持范围。
4. bounds、cursor、beat-sync 等高频通道的性能预算是多少？应保留现有专用 transport 或批处理策略，不要统一套用重量级通用 envelope。

整体建议是：把 Eventa 留在内部作为稳定传输基础，把“授权、生命周期、版本和错误”提升为显式架构边界。这样既利用 AIRI 已有投资，也能逐步消除 raw IPC、重复 sender 检查和隐式兼容性。

[EVAL:evolve-software-architecture-loaded]
