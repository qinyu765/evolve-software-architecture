## 结论

建议采用渐进式混合方案：

> 保留 Eventa 作为 IPC 的传输、事件和流式能力；在其上增加按窗口角色管理的 `IpcSession`、版本化领域契约、主进程边界校验和统一错误映射；preload 只暴露窄能力面，renderer 不再直接接触 `ipcRenderer`。

不建议立即把现有约 133 个 Eventa 契约一次性迁移到另一套 `ipcMain.handle` 网关。这样能保留 AIRI 当前 Eventa 投资，同时逐步解决窗口隔离、错误不一致、测试耦合和长期演进问题。

## 范围与置信度

本次基于只读静态审查，基线为 HEAD `5228f9412`，没有修改文件、创建提交或改变外部状态，也没有运行构建和测试。

对当前文件结构和调用关系的判断置信度较高；Eventa 适配器内部的精确错误序列化和 disposer 行为因本地依赖源码不可用，仍需在实施前做一次小型技术验证。

## 当前可观察事实

| 观察 | 证据 | 设计影响 |
|---|---|---|
| Eventa 契约集中在共享 barrel，同时已经存在按领域拆分的插件契约 | [`shared/eventa/index.ts`](/evaluation-path/treatment/apps/stage-tamagotchi/src/shared/eventa/index.ts:31)、[`plugin/domains.test.ts`](/evaluation-path/treatment/apps/stage-tamagotchi/src/shared/eventa/plugin/domains.test.ts:42) | 可以渐进拆分，不需要一次性重写契约 |
| 多窗口同时使用窗口级和进程级 Eventa context | [`main/index.ts`](/evaluation-path/treatment/apps/stage-tamagotchi/src/main/index.ts:263)、[`main/rpc/index.electron.ts`](/evaluation-path/treatment/apps/stage-tamagotchi/src/main/windows/main/rpc/index.electron.ts:42) | 权限、生命周期和广播语义目前容易混在一起 |
| 多处调用 `ipcMain.setMaxListeners(0)`，preload 也有相同 workaround | [`preload/shared.ts`](/evaluation-path/treatment/apps/stage-tamagotchi/src/preload/shared.ts:8) | 暗示 context 命名空间或清理边界还不够明确 |
| sender 校验已在窗口、widgets、auth 等服务中重复出现 | [`main/services/electron/window.ts`](/evaluation-path/treatment/apps/stage-tamagotchi/src/main/services/electron/window.ts:45)、[`main/services/airi/widgets/index.ts`](/evaluation-path/treatment/apps/stage-tamagotchi/src/main/services/airi/widgets/index.ts:29) | 应将 sender、窗口角色和能力校验提升为统一边界 |
| preload 暴露 `electronAPI`，renderer 多处直接读取 `window.electron.ipcRenderer` | [`preload/shared.ts`](/evaluation-path/treatment/apps/stage-tamagotchi/src/preload/shared.ts:8)、[`use-electron-eventa-context.ts`](/evaluation-path/treatment/packages/electron-vueuse/src/composables/use-electron-eventa-context.ts:11) | renderer 依赖了底层 transport 形状，测试和安全边界都不够窄 |
| IPC 契约没有统一的 `protocolVersion` 或 `schemaVersion`；但 Godot、QR、MCP 已经有 schema/version 模式 | [`view-state.ts`](/evaluation-path/treatment/packages/stage-shared/src/godot-stage/view-state.ts:35)、[`mcp-config.ts`](/evaluation-path/treatment/apps/stage-tamagotchi/src/shared/mcp-config.ts:30) | 仓库已有可复用的运行时校验和版本化先例 |
| 错误传播语义不统一：既有 rejected `Error`，也有显式 `ok/error`、状态码和 degraded state | [`app.test.ts`](/evaluation-path/treatment/apps/stage-tamagotchi/src/main/services/electron/app.test.ts:32) | 不能把跨进程 `Error` 对象本身当作长期契约 |

## 当前主要摩擦

1. **版本是隐含的。** 当前 Eventa ID 没有明确的 v1/v2 语义，应用版本也不应直接等同于 IPC 协议版本。

2. **窗口作用域和进程作用域混用。** `createContext(ipcMain)` 适合真正的进程级服务，但对插件、设置、widgets 等能力，单靠调用方记住权限边界不够清晰。

3. **生命周期清理不统一。** 有些服务在窗口关闭时清理监听器，有些只清理部分 handler；`setMaxListeners(0)` 掩盖了监听器管理问题。

4. **renderer 依赖底层桥接。** 当前 `useElectronEventaContext` 的模块级 singleton 和多个直接使用 `window.electron.ipcRenderer` 的调用点，使 renderer 测试难以只注入业务 API。

5. **测试已经有好基础，但层次还不完整。** widgets 测试能验证不同窗口 sender 被隔离，[`widgets/index.test.ts`](/evaluation-path/treatment/apps/stage-tamagotchi/src/main/services/airi/widgets/index.test.ts:36) 使用了内存 Eventa context；但 preload 暴露面、窗口角色权限、统一 dispose 仍缺少独立测试。

## 质量属性优先级

建议按以下顺序权衡：

1. sender 隔离、窗口角色权限和生命周期安全。
2. 契约可发现性、版本演进和错误可诊断性。
3. main service 与 renderer 的测试隔离。
4. 分阶段迁移和可回滚性。
5. IPC 性能。

当前更应该优化边界清晰度，而不是追求极少的 IPC 层数。对于大型截图、音频或流式数据，再单独评估传输性能和背压。

## 方案比较

| 方案 | 优点 | 代价 |
|---|---|---|
| 继续使用当前 Eventa，只补约定 | 成本最低，改动最少 | 不能根治 listener、preload 暴露面和作用域混用 |
| 全量改为统一 typed gateway / `ipcMain.handle` | API、权限、错误和测试边界最清楚 | 需要重写大量事件和流式场景，迁移成本最高，容易重复实现 Eventa |
| **Eventa + `IpcSession` + 能力 facade** | 保留现有 transport，逐域迁移，兼顾事件、流和测试 | 过渡期会同时存在旧桥和新 facade，需要明确清理条件 |

推荐第三种。

## 建议的目标结构

```text
renderer domain client
        ↓
preload capability facade
        ↓
window-scoped IpcSession(role, windowId)
        ↓
schema validation + error mapping
        ↓
pure main domain service
        ↓
Electron / filesystem / network / external runtime
```

### 1. 契约层

按领域拆分，例如：

```text
shared/eventa/window/v1
shared/eventa/widgets/v1
shared/eventa/updater/v1
shared/eventa/plugin/v1
```

每个领域契约应明确：

- operation ID；
- request/response DTO；
- runtime schema；
- 作用域：`window`、`process` 或 `broadcast`；
- 允许的窗口角色；
- 可预期错误；
- 是否支持流式事件；
- 版本和兼容规则。

现有 ID 不建议立即全部重命名。可以把当前语义视为隐含 v1，在契约注册表中记录版本；只有破坏性变化才创建 v2 ID。

建议规则：

- 增加可选字段：保持 v1；
- 改变字段含义、必填性、枚举语义或返回结构：创建 v2；
- 不依赖应用 package version 作为协议版本；
- 不使用“先尝试 v2，失败再尝试 v1”的永久 fallback；
- 如果插件或 iframe 独立发布，则使用独立的 `apiVersion` 和 capability handshake，不与内部 Electron IPC 版本混合。

契约中的类型应是结构化可序列化 DTO，不应直接暴露 `BrowserWindow`、Electron 对象或 `Record<string, any>`。main 层负责把 Electron 原生对象转换成 DTO。

### 2. main 层

为每个 `BrowserWindow` 建立一个有生命周期的 `IpcSession`：

```text
createWindowIpcSession(window, role)
  ├─ create Eventa context
  ├─ register common handlers
  ├─ register role capabilities
  ├─ track handler/event disposers
  └─ dispose on window closed
```

它应集中负责：

- sender 是否属于目标窗口；
- sender 对应的窗口角色；
- 当前 contract 是否被该角色允许；
- handler、事件监听和 pending request 的清理；
- renderer 销毁后的 abort/reject；
- 统一日志上下文，如 contract、role、windowId、requestId。

业务 handler 不应自己重复做 sender 判断，而应接收已经验证过的调用上下文，再调用纯业务 service。

真正的进程级服务，例如 channel server 或插件宿主，应单独标记为 `process scope`，并明确哪些窗口角色可以调用。不要让“使用了 `createContext(ipcMain)`”自动意味着所有 renderer 都有相同权限。

现有“handler 在 `load()` 前注册”的顺序应保留；历史提交 `e86ee2f13` 已体现这一点。sender 限制也应继续保留，历史提交 `08bfb3069` 说明这已经是实际需要，而非抽象设计。

`setMaxListeners(0)` 不应作为长期方案。应先确认 Eventa context 是否能可靠返回 disposer；如果不能，就先集中封装 adapter/session 的清理能力，验证窗口关闭、重建和多窗口场景后，再逐步移除 listener 上限 workaround。

### 3. preload 层

目标是暴露能力，而不是暴露 transport：

```text
window.airi.window.getBounds()
window.airi.widgets.request(...)
window.airi.updater.subscribe(...)
```

具体形式可以是生成的领域方法，也可以先是受限的 Eventa transport facade。迁移成本角度，建议先采用窄 transport facade，再对高权限能力逐步生成领域方法。

preload 应做到：

- 只暴露当前窗口角色允许的 API；
- 不暴露原始 `ipcRenderer`；
- 事件订阅返回明确的取消函数；
- 所有参数和返回值都是结构化可克隆数据；
- beat-sync 等特殊 preload 只拥有专用能力；
- 保留旧 `window.electron` 仅作为迁移期兼容面，并设置明确删除条件。

当前 `exposeWithCustomAPI` 已提供了一个自然的扩展位置，但目前没有实际调用点，可作为后续 capability facade 的接入点。

安全配置方面，建议将 `contextIsolation: true`、`nodeIntegration: false` 显式写入目标配置。当前窗口普遍使用 `sandbox: false`，这可能与现有 preload/native 依赖有关，应作为独立安全迁移，不要和 IPC 契约迁移绑成一次大改动。

### 4. renderer 层

renderer 只依赖领域 client：

```text
useAiriIpc().window.getBounds()
useAiriIpc().serverChannel.apply(...)
useAiriIpc().widgets.subscribe(...)
```

建议：

- 在 renderer app root 注入 client；
- stores 和 composables 依赖 client，而不是 `window.electron.ipcRenderer`；
- client 接受可注入的 transport，测试中使用 fake client；
- 事件订阅绑定 renderer 生命周期；
- 保留 `@proj-airi/electron-vueuse` 作为便捷层，但让它依赖 facade，而不是暴露底层 transport；
- 避免把 module-level singleton 作为唯一生命周期管理方式。

## 错误传播策略

建议区分三类错误。

### 可预期的领域结果

例如快捷键冲突、MCP 配置无效、widgets 请求失败，应使用稳定的结果或错误码：

```text
code
message
details
retryable
requestId
```

renderer 只依赖 `code` 和 `retryable`，不要依赖 main 端的 Error 类、stack 或原始字符串。

### 输入和权限错误

在 main 边界进行 schema 校验和 sender/role 校验，返回稳定错误：

- `invalid-request`
- `forbidden`
- `not-found`
- `conflict`
- `unavailable`

新契约中，跨窗口请求不应静默返回 `undefined`；应拒绝并记录原因。旧契约可以保持既有行为，避免迁移时同时改变业务语义。

### 内部错误和传输错误

Unexpected error 在 main 记录原始错误，跨边界只返回通用错误，例如：

- `internal`
- `renderer-gone`
- `aborted`
- `timeout`
- `handler-unavailable`

日志应包含 contract、window role、window id 和 request id，但不能泄露 token、完整路径或敏感配置。仓库已有 `errorMessageFrom(error)` 约定，应统一用于日志和安全的错误文本提取。

## 测试隔离

建议形成五层测试边界：

1. **契约测试**：schema 的合法、非法、结构化克隆和 v1/v2 兼容性。
2. **业务 service 测试**：纯函数和外部依赖 mock，不加载 Electron。
3. **IpcSession 测试**：两个 fake windows 验证 sender 隔离、角色权限、重复注册、dispose、窗口关闭和 pending request。
4. **preload 测试**：验证暴露的 key、允许的 capability 和 raw `ipcRenderer` 不存在。
5. **renderer 测试**：注入 fake domain client，不 mock 全局 Electron；只为 context helper 单独测试 reset seam。

现有的内存 Eventa 测试和 widgets sender 测试可以直接作为基础。`desktop-overlay` 测试目前还耦合 `setMaxListeners(0)`，未来应改为验证 session 生命周期，而不是验证 workaround 本身。

## 迁移路线与成本

| 阶段 | 建议工作 | 成本 |
|---|---|---|
| 0 | 建立 IPC inventory：契约、作用域、角色、错误、schema、清理责任 | 低 |
| 1 | 按领域拆分契约，增加 schema 和版本登记；保留现有 ID | 低至中 |
| 2 | 引入 `IpcSession` 和统一 sender/dispose，先迁移一个窗口 | 中 |
| 3 | 为一个纵向切片统一错误，例如 desktop-overlay readiness + `window.getBounds` | 中 |
| 4 | 增加窄 preload facade，迁移 renderer 的直接 `ipcRenderer` 调用 | 中至高 |
| 5 | 迁移全局服务、广播事件和特殊 preload | 高 |
| 6 | 删除 raw bridge、`setMaxListeners(0)` 和旧 facade | 中 |

第一条纵向切片建议选择 desktop-overlay：它已有 degraded readiness 语义、专门测试和窗口 sender 相关调用，规模比全量迁移小，能够同时验证契约、错误、角色和生命周期设计。

每个阶段都应设置退出标准：

- 每个窗口只有一个明确的 `IpcSession`；
- 新迁移契约都有 schema、scope、role 和错误定义；
- 没有应用层直接读取 `window.electron.ipcRenderer`；
- 没有窗口级 `setMaxListeners(0)`；
- 跨窗口 sender 测试通过；
- renderer 销毁后不会留下 handler/listener/pending request。

## 尚需确认的决策

1. AIRI 是否要求 main、preload、renderer 支持独立版本错配？如果始终随同一个桌面包发布，不需要复杂的运行时协商。
2. 插件和 iframe 是否被视为独立 API 消费者？如果是，应单独维护 plugin API version。
3. 新 preload facade 先暴露受限 Eventa transport，还是直接暴露生成的领域方法？建议先 transport facade，安全敏感领域优先生成方法。
4. 当前 Eventa adapter 是否提供可靠的 per-context disposer？实施前需要直接检查依赖源码或写最小实验。
5. `contextIsolation`、`nodeIntegration`、`sandbox` 的安全迁移是否单独排期？

最终建议是：把 Eventa 从“应用各处直接创建和使用的 IPC 工具”提升为“受 `IpcSession`、契约注册表和 capability facade 管理的传输层”。这样能保留现有代码投资，同时把版本、错误、测试和迁移责任放到明确的边界上。

[EVAL:evolve-software-architecture-loaded]
