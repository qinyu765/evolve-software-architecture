结论：建议采用“Eventa 保留为契约/传输抽象 + 窄能力型 preload API + 每窗口独立注册与清理”的渐进方案。保留现有 channel ID，不做一次性 IPC 重写，也暂不为每条消息增加全局版本 envelope。

## 范围与信心

这是高置信度的 Electron 桌面架构评估，范围是 `apps/stage-tamagotchi` 的 main、preload、renderer 及共享 Electron 包。仓库文档也明确将 Eventa 用于跨进程 IPC/RPC。

## 观察事实

| 事实 | 证据 | 影响 |
| --- | --- | --- |
| 公共 Electron 契约已抽到 `@proj-airi/electron-eventa`，应用契约仍集中在约 500 行的 `shared/eventa/index.ts` | [electron-eventa README](</evaluation-path/treatment/packages/electron-eventa/README.md:1>)、[shared/eventa/index.ts](</evaluation-path/treatment/apps/stage-tamagotchi/src/shared/eventa/index.ts:1>) | 已有抽象基础，但应用契约仍混合窗口、插件、MCP、Godot、服务通道等领域 |
| preload 暴露了 `electronAPI`，renderer 再直接取得 `window.electron.ipcRenderer` | [preload/shared.ts](</evaluation-path/treatment/apps/stage-tamagotchi/src/preload/shared.ts:8>)、[electron-vueuse context](</evaluation-path/treatment/packages/electron-vueuse/src/composables/use-electron-eventa-context.ts:11>) | renderer 与 Electron transport、安全权限、测试全局状态耦合 |
| main 同时存在全局 `createContext(ipcMain)` 和按窗口绑定的 context；代码还依赖 `setMaxListeners` | [main/index.ts](</evaluation-path/treatment/apps/stage-tamagotchi/src/main/index.ts:55>) | 窗口隔离和 listener 生命周期是实际架构问题，不是理论问题 |
| 部分 handler 手工检查 `sender.id`，screen-capture 才显式使用 `onlySameWindow` | [main/services/electron/window.ts](</evaluation-path/treatment/apps/stage-tamagotchi/src/main/services/electron/window.ts:44>)、[screen-capture](</evaluation-path/treatment/packages/electron-screen-capture/src/main/index.ts:187>) | sender 授权逻辑分散，容易出现遗漏 |
| 测试已能使用内存 Eventa context 隔离 Electron；同时已有窗口来源校验测试 | [app.test.ts](</evaluation-path/treatment/apps/stage-tamagotchi/src/main/services/electron/app.test.ts:32>)、[widgets/index.test.ts](</evaluation-path/treatment/apps/stage-tamagotchi/src/main/services/airi/widgets/index.test.ts:36>) | 现有测试 seam 值得保留和扩展 |

## 主要摩擦

[推断] 当前最大问题不是 Eventa，而是同一 IPC 层同时承担：

- 公共平台 API；
- 单窗口 API；
- 全局服务 API；
- renderer 的通用 Electron transport。

另外，契约 ID 没有显式版本；类型中还存在 `Display`、`ReturnType<BrowserWindow>`、`Record<string, any>` 等跨边界耦合。Eventa 的类型安全也不能替代运行时校验。

## 方案比较

| 方案 | 优点 | 代价 |
| --- | --- | --- |
| A. 保持现状，仅约定命名和错误格式 | 迁移成本最低 | raw `ipcRenderer`、全局 context、sender 检查和 listener workaround 继续存在 |
| B. Eventa + 能力型 preload API + 每窗口注册 | 能隔离权限、收敛生命周期，仍复用现有 Eventa 和测试方式 | 需要逐个迁移 renderer 调用点 |
| C. 全量 schema-first versioned gateway | 适合独立发布的插件、远程 renderer、旧客户端共存 | 重复 Eventa 能力，增加 envelope、握手、代码量和高频事件开销 |

推荐 B。C 只有在插件或 renderer 真的独立发布时才值得引入。

## 推荐设计

### 1. 契约与版本

- `@proj-airi/electron-eventa` 保留为跨应用、平台级契约。
- `apps/stage-tamagotchi/src/shared/eventa` 按领域拆文件，再由 index 聚合；不要立即把应用专属契约全部搬进公共包。
- renderer-facing 类型使用 AIRI 自己的可序列化 DTO，由 main 映射 Electron 类型；screen-capture 的 `SerializableDesktopCapturerSource` 是可复用的现有范例。
- 非破坏变更：新增可选字段、新增事件、新增能力。
- 破坏变更：创建新 channel ID，例如原操作的 `:v2`，不要复用旧 ID 改变语义。
- 当前 main 和 renderer 随同桌面包发布，因此不建议现在为每条消息加入 `protocolVersion` 或握手。若未来插件/远程页面独立发布，再对该能力增加 `{ contractId, major, features }` 的能力协商。

### 2. main / preload / renderer ownership

- main 拥有状态、权限、窗口对象、文件系统和 OS 副作用。
- preload 只暴露能力，例如 `window.api.window.getLifecycleState()`、`window.api.screenCapture.getSources()`；不要继续新增 `window.electron.ipcRenderer` 的直接消费者。
- preload 内部可以继续使用 Eventa renderer adapter，但把 transport 隐藏在 preload 的闭包中。
- 每个窗口由一个 `registerWindowIpc({ window, context, services })` 负责注册、sender 限制、事件订阅和 cleanup。
- 全局服务明确标为 global capability；敏感操作仍在 main 校验 sender，而不是仅依赖 renderer 是否看得到按钮。
- 高频的 bounds、cursor、诊断数据继续使用事件/流，不强行包装成普通 RPC；需要时增加 revision 或 timestamp，明确丢弃旧事件的规则。

### 3. 错误传播

Eventa 的内存测试已经验证了 thrown error 的传播，但当前测试不能证明 Electron transport 会保留自定义错误对象的全部字段。

建议统一为：

- 预期业务失败：返回 typed `Result`，类似现有 `ShortcutRegistrationResult`；
- 未就绪、取消、权限拒绝、窗口关闭：稳定错误码，例如 `not-ready`、`cancelled`、`permission-denied`；
- 未预期异常：main 记录完整 stack，跨 IPC 只返回 `{ code, message, retryable, correlationId }`；
- 不跨边界传递 `Error`、stack、token、绝对路径或 Electron 对象；
- 长任务沿用现有 `requestId` 相关模式，支持取消和结果关联；
- 事件本身不依赖异常传播，状态型错误应进入明确的 error event 或状态快照。

## 迁移与验证

建议按以下顺序迁移，保持现有 channel ID 不变：

1. 按领域拆分契约，补充 DTO、错误码和必要的 Valibot 边界校验。
2. 以 `window lifecycle` 作为第一条 vertical slice：它同时包含 invoke、事件、窗口 sender 校验，且风险低。
3. 为该 slice 建立 preload typed API，renderer 改为注入 client；main handler 改由窗口注册器统一管理。
4. 逐步迁移 auth、plugin、MCP、server-channel、Godot 等有副作用的能力。
5. 最后删除直接使用 `window.electron.ipcRenderer` 的 renderer 调用，并评估是否可以移除 `setMaxListeners` workaround。

验收标准：

- renderer 业务代码不再直接接触 `ipcRenderer`；
- sender 校验集中在窗口注册/授权边界；
- 所有 mutation contract 有运行时输入校验；
- main service、contract、preload bridge、renderer behavior 都能脱离真实 Electron 分层测试；
- 至少有一个打包应用 smoke test 覆盖 main → preload → renderer；
- handler 必须在 `load()` 前注册。历史提交 `e86ee2f13` 已证明这是实际生命周期约束。

## 尚待确认的决策

- 插件、iframe、Godot 或远程 renderer 是否可能独立于桌面包发布？
- 是否存在不可信或可导航到远程内容的 renderer？这会决定移除 raw Electron API 的紧迫程度。
- Eventa 后续是否会提供可靠的 window-namespaced context 和统一 cleanup？若不会，应在 AIRI 内部保留一层窗口注册 adapter。

本次仅做只读检查，未修改文件、创建提交或改变外部状态。

[EVAL:evolve-software-architecture-loaded]
