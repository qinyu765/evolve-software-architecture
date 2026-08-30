结论：建议采用“保留 Eventa 作为传输层 + 引入类型化 IPC Port + 明确作用域 + 统一边界校验/错误”的渐进式方案。不要立即改成另一套 `ipcMain.handle` RPC，也不要给每个消息机械地加 `v1`。

本次仅做只读检查，未修改文件、创建提交或改变外部状态。

## 1. 范围与置信度

范围限定为 `apps/stage-tamagotchi` 的 Electron main、preload、renderer，以及 `packages/stage-shared`、`packages/electron-eventa`、`packages/electron-vueuse`。

对当前代码拓扑的判断置信度高；对 Eventa 底层序列化细节的判断以仓库用法和现有测试为准，未将缺失的 `node_modules` 当作证据。

## 2. 当前事实

| 事实 | 证据 | 影响 |
|---|---|---|
| 同时存在 app-global 与 window-local Eventa context | main 全局 context：[main/index.ts:260](/evaluation-path/treatment/apps/stage-tamagotchi/src/main/index.ts:260)；窗口 context：[main/rpc/index.electron.ts:48](/evaluation-path/treatment/apps/stage-tamagotchi/src/main/windows/main/rpc/index.electron.ts:48) | 作用域目前主要靠调用位置和人工约定表达 |
| preload 暴露了原始 `electronAPI`，renderer 可直接拿 `ipcRenderer` 创建 context | [preload/shared.ts:8](/evaluation-path/treatment/apps/stage-tamagotchi/src/preload/shared.ts:8)、[use-electron-eventa-context.ts:11](/evaluation-path/treatment/packages/electron-vueuse/src/composables/use-electron-eventa-context.ts:11) | renderer 可以绕过业务边界，测试也容易绑定具体 transport |
| 多处存在 `setMaxListeners` 与 window namespace TODO | [main/index.ts:55](/evaluation-path/treatment/apps/stage-tamagotchi/src/main/index.ts:55) | 暗示 context/监听器生命周期尚未形成统一抽象 |
| window 隔离依赖 Eventa context 加大量手动 sender 检查 | [window.ts:45](/evaluation-path/treatment/apps/stage-tamagotchi/src/main/services/electron/window.ts:45)；screen capture 已使用 `onlySameWindow`：[index.ts:187](/evaluation-path/treatment/packages/electron-screen-capture/src/main/index.ts:187) | 安全边界并非所有模块统一实现 |
| Eventa contract 已按 plugin 等领域拆分，但总 barrel 仍很大 | [shared/eventa/index.ts:31](/evaluation-path/treatment/apps/stage-tamagotchi/src/shared/eventa/index.ts:31) | 适合继续按领域迁移，并保留 barrel 作为兼容出口 |
| 没有统一的 IPC contract version 或 error envelope | 现有版本主要是 QR、Godot view state、shortcut schema：[server-channel-qr.ts:5](/evaluation-path/treatment/packages/stage-shared/src/server-channel-qr.ts:5)、[view-state.ts:35](/evaluation-path/treatment/packages/stage-shared/src/godot-stage/view-state.ts:35) | 当前版本策略是领域级的，不能直接推导出 IPC 全局版本 |
| 错误传播混合了 throw、Error message 和业务结果 | app service 测试：[app.test.ts:27](/evaluation-path/treatment/apps/stage-tamagotchi/src/main/services/electron/app.test.ts:27)；widgets 校验：[validation.ts:49](/evaluation-path/treatment/apps/stage-tamagotchi/src/main/services/airi/widgets/validation.ts:49)；Artistry 返回 `{error}` | renderer 难以稳定地区分可重试、权限、未就绪和内部错误 |
| 测试已有 in-memory Eventa seam，但也有按 generated event id 分支的 mock | [global-shortcut.test.ts:119](/evaluation-path/treatment/apps/stage-tamagotchi/src/main/services/electron/global-shortcut.test.ts:119)、[plugin-tools.test.ts:126](/evaluation-path/treatment/apps/stage-tamagotchi/src/renderer/stores/plugin-tools.test.ts:126) | 测试隔离存在，但与具体 Eventa 实现耦合 |

## 3. 推荐的目标结构

```text
renderer domain code
        |
typed IpcPort / domain facade
        |
preload allowlist bridge
        |
Eventa Electron transport
        |
main scoped router
   |          |           |
window      app       broadcast
services   services   registry
```

建议把“业务调用什么”与“通过 Electron IPC 怎么传”分开：

- renderer 只依赖按领域定义的 `IpcPort` 或 composable。
- preload 只做 allowlist、参数转发、订阅和取消，不放业务逻辑。
- main 负责窗口身份、权限、schema 校验、错误归一化，再调用领域服务。
- Eventa 继续作为 transport；这样现有 Electron IPC、BroadcastChannel 等使用方式仍可渐进保留。

### 作用域模型

| 作用域 | 典型内容 | 建议 |
|---|---|---|
| window-local | window lifecycle、widgets、screen capture | 每窗口独立 context；优先使用 `onlySameWindow`；保留 sender 校验作为防线 |
| app-global | plugin registry、server channel、Artistry | app context；通过显式 capability 暴露，不能被任意 renderer 调用 |
| broadcast | auth callback、shortcut、updater、Godot 状态 | 注册窗口集合，窗口关闭时自动移除；明确“广播给全部窗口”语义 |
| high-frequency | cursor、bounds、beat-sync、trace | 独立事件模型，定义节流、丢弃、revision 或 snapshot，不套重型通用 envelope |

当前 plugin 和 server channel 已经体现 app-global 形态：[plugins/index.ts:47](/evaluation-path/treatment/apps/stage-tamagotchi/src/main/services/airi/plugins/index.ts:47)、[channel-server/index.ts:451](/evaluation-path/treatment/apps/stage-tamagotchi/src/main/services/airi/channel-server/index.ts:451)。

## 4. 契约版本策略

建议分三层处理：

1. 普通桌面内置调用：不增加每消息版本。main、preload、renderer 随同一个应用发布，过度协商只会增加复杂度。

2. 可兼容修改：保留原 Eventa ID。

   - 只新增可选字段；
   - reader 忽略未知字段；
   - 不改变既有字段语义；
   - 不静默改变枚举含义或必填性。

3. 破坏性修改：创建新的 contract object 和新 ID，例如 `...:v2`，并在短期内由 adapter 将 v1 转换到同一领域服务。

只有 plugin、sidecar、QR、持久化状态等可能跨版本存在的边界，才使用明确的 `schemaVersion`，并拒绝更新版本。仓库已有这种模式，例如 Godot view state 与 shortcut schema，应该复用而不是另造全局机制。

可以增加一个低频的 `getProtocolInfo` 或 capability 查询，用于诊断和功能门控，返回应用版本、协议版本和 capability 集合；不建议把协商字段塞进每次 IPC 调用。

## 5. 错误传播策略

定义统一的边界错误模型，例如：

```text
code
message       // 面向用户且不含敏感信息
retryable
details       // structured-clone-safe
requestId     // 用于 main/renderer 日志关联
```

建议错误类别至少覆盖：

- `invalid-request`
- `forbidden-window`
- `not-ready`
- `timeout`
- `cancelled`
- `unavailable`
- `conflict`
- `external-failure`
- `internal`

处理原则：

- 参数不合法、窗口不匹配、服务未就绪：在 main 边界拒绝。
- 网络、sidecar、MCP、模型等外部失败：保留稳定 `code`，由 renderer 决定重试或提示。
- 未预期异常：以 reject 传播，renderer 只得到安全错误；stack、路径、token 和内部对象只写 main 日志。
- 预期业务失败继续使用 typed result，不要把所有调用都包装成 `{ ok: boolean }`。现有的 shortcut `{ok:false, reason}`、overlay `degraded`、Godot error event、MCP `isError` 都属于合理模式。
- 长任务必须有 timeout、取消和窗口关闭清理。现有 plugin tools 测试已经记录了 handler 未就绪导致 Promise 长时间 pending 的问题：[plugin-tools.test.ts:126](/evaluation-path/treatment/apps/stage-tamagotchi/src/renderer/stores/plugin-tools.test.ts:126)。

## 6. 测试隔离

建议固定为四层：

1. 契约测试：验证 ID、schema、兼容字段、未知版本处理。
2. main 领域测试：使用 in-memory Eventa 或 fake port，不启动 Electron。
3. transport 测试：验证 sender、window scope、序列化、handler 未就绪、窗口销毁和广播清理。
4. renderer 测试：注入 fake `IpcPort`，不再通过 `receiveEvent.id` 分支 mock。

`packages/electron-vueuse` 已有 `resetElectronEventaContextForTesting`，但长期更建议每个测试显式创建 port/context，避免共享 singleton。测试重点应包括：

- 错误 code 是否稳定；
- 错误是否不会泄露主进程内部信息；
- 错误窗口不能调用其他窗口 handler；
- window close 后 pending request 必须 reject；
- renderer reload、窗口重开、服务未启动时不会永久 pending；
- broadcast 是否只发送给仍存活的窗口。

## 7. 迁移方案与成本控制

建议按垂直切片迁移，而不是一次重写：

1. 先做 contract inventory：为每个调用记录 owner、scope、输入/输出 schema、错误策略和生命周期。
2. 选择 `desktop-overlay readiness` 或 window lifecycle 作为第一条切片。现有 readiness 已有 ready/degraded 测试：[index.electron.test.ts:45](/evaluation-path/treatment/apps/stage-tamagotchi/src/main/windows/desktop-overlay/rpc/index.electron.test.ts:45)。
3. 增加 typed port 和 preload allowlist，但保留现有 Eventa ID。
4. 将 renderer 的 `useElectronEventaInvoke`、settings/server-channel、plugin tools 等逐领域切换到 port。
5. 将 schema 与错误映射移到共享的中性 contract 模块；避免让共享模块引入 Electron runtime。
6. 统一 window/app/broadcast registry 和关闭清理后，再处理 `setMaxListeners`。它是症状缓解，不应作为隔离方案。
7. 最后迁移 `stage-ui` 中直接访问 `window.electron.ipcRenderer` 的调用，例如 Artistry 模块当前直接创建 context：[artistry-autonomous.ts:34](/evaluation-path/treatment/packages/stage-ui/src/stores/modules/artistry-autonomous.ts:34)。

每一阶段都保留旧 adapter，因此回滚只需回退 renderer/preload 的适配层，不需要数据迁移。完成标准是：新业务调用不再直接依赖原始 `ipcRenderer`，每个 contract 都有明确 scope/schema/error owner，窗口销毁不会遗留请求或监听器。

## 8. 方案权衡

| 方案 | 优点 | 代价 |
|---|---|---|
| 继续使用现状，只补约定 | 迁移成本最低 | scope、错误、测试隔离仍依赖人工纪律 |
| Eventa + typed port + scope registry（推荐） | 保留已有投资；改善 preload 安全边界、测试和演进能力；可渐进迁移 | 需要短期维护旧 adapter 与新 port |
| 全量替换为新 RPC/generated API | 契约形式统一 | 要重写现有 Eventa、广播、窗口 context、测试和多 transport；迁移风险最高 |

## 9. 尚需确认的决策

这些问题会影响版本和迁移优先级：

- plugin/sidecar 是否允许独立于 AIRI 发布？如果允许，协议 handshake 和严格版本拒绝应提前。
- 是否把“不能暴露原始 `ipcRenderer`”作为近期安全目标？如果是，typed preload facade 应优先于业务迁移。
- 是否承诺支持多版本 renderer 或旧插件？如果不支持，桌面内置调用不需要逐消息协商。
- cursor、beat-sync、trace 等高频事件是否有性能预算？需要单独压测，不能直接套通用错误/版本 envelope。
- `shared/eventa`、`packages/electron-eventa`、plugin SDK 三者的长期契约 owner 应明确，否则拆分后仍会回到大 barrel。

本次没有执行构建或测试，因此上述“验证”是建议的验收矩阵，不是已经通过的结果。

[EVAL:evolve-software-architecture-loaded]
