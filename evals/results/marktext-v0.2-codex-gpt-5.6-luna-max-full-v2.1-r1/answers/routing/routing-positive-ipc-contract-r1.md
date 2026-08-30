## 范围与结论

这是 Electron 桌面应用架构评估，置信度较高。结论是：

MarkText 的 `contextBridge` 安全边界已经实际启用，但当前 IPC 类型仍处于迁移中。长期方向应是：

> 保留现有 `ipc.ts` 作为兼容层，新增版本化、按能力划分的 preload API；统一可序列化错误；将 main 内部事件与 Electron IPC 分离；逐步淘汰 renderer 直接使用通用 `ipcRenderer`。

本次只读检查未修改文件、未提交；`git diff` 为空。typecheck 未能执行：pnpm 尝试在 workspace 外创建缓存目录而被只读环境拒绝，且本地没有可直接调用的 `vue-tsc`。

## 观察到的事实

| 类型 | 证据 | 判断 |
|---|---|---|
| 事实 | [窗口配置](</evaluation-path/treatment/packages/desktop/src/main/config.ts:12>) 设置 `contextIsolation: true`、`sandbox: true`、`nodeIntegration: false` | contextBridge 是实际边界；E2E 也验证了 `require/global/Buffer` 不可用。 |
| 事实 | [preload bridge](</evaluation-path/treatment/packages/desktop/src/preload/index.ts:26>) 将通用 `send/invoke/on` 暴露给 renderer | 类型限制主要存在于 TypeScript，运行时仍是一个宽泛的 IPC 路由器。 |
| 事实 | [IPC 契约](</evaluation-path/treatment/packages/desktop/src/shared/types/ipc.ts:10>) 明确承认大量 `unknown` 是迁移暂态 | 当前契约不是完整的长期协议。 |
| 事实 | `mt::menu::click` 契约声明为字符串，但 main 发送 `{ windowId, id }`；`mt::window-active-status` 契约声明为布尔值，但 main 发送 `{ status }`。见 [契约](</evaluation-path/treatment/packages/desktop/src/shared/types/ipc.ts:246>)、[发送端](</evaluation-path/treatment/packages/desktop/src/main/ipc/window.ts:38>) | main → renderer 的发送没有被共享类型反向约束。 |
| 事实 | keybinding 保存契约返回 `void`，handler 实际返回布尔值，renderer 再通过 `as unknown as boolean` 修正。见 [handler](</evaluation-path/treatment/packages/desktop/src/main/app/index.ts:830>)、[caller](</evaluation-path/treatment/packages/desktop/src/renderer/src/prefComponents/keybindings/KeybindingConfigurator.ts:94>) | 类型契约与运行时行为已有可见漂移。 |
| 事实 | `ipcMain.emit` 被同时当作 main 内部事件总线，另有 `onInternalChannel` 适配器。见 [internalIpc.ts](</evaluation-path/treatment/packages/desktop/src/main/utils/internalIpc.ts:4>) | 外部 IPC、main 内部事件和 legacy channel 混在同一命名空间。 |
| 事实 | FS handler 直接传播异常；shell handler 又把失败转换成 `false`、错误字符串或空字符串。见 [fs.ts](</evaluation-path/treatment/packages/desktop/src/main/ipc/fs.ts:40>)、[shell.ts](</evaluation-path/treatment/packages/desktop/src/main/ipc/shell.ts:6>) | 错误传播语义不统一，调用方无法区分“合法空值”和“失败”。 |
| 事实 | preload 的 `on()` 返回 unsubscribe，但设置页调用按 channel 的 `removeAllListeners()`。见 [preload](</evaluation-path/treatment/packages/desktop/src/preload/index.ts:45>)、[设置页](</evaluation-path/treatment/packages/desktop/src/renderer/src/prefComponents/sideBar/index.vue:151>) | 组件间可能互相移除监听器。 |
| 事实 | 单测使用 jsdom 和逐文件手写 `window.electron` stub；E2E 的 `sendIpcToRenderer` 直接调用 `webContents.send`。见 [Vitest 配置](</evaluation-path/treatment/packages/desktop/vitest.config.ts:8>)、[E2E helper](</evaluation-path/treatment/packages/desktop/test/e2e/helpers.ts:355>) | 现有测试能覆盖 UI 行为，但不能完整证明 preload 契约。 |

Electron 官方也说明：contextBridge 会复制参数和返回值，错误的自定义属性可能丢失；`ipcMain.handle` 抛出的错误默认只保证 message；同步 IPC 会阻塞 renderer。[contextBridge 文档](https://www.electronjs.org/docs/latest/api/context-bridge)、[ipcMain 文档](https://www.electronjs.org/docs/latest/api/ipc-main)、[ipcRenderer 文档](https://www.electronjs.org/docs/latest/api/ipc-renderer)

## 建议的长期契约

建议新增一个 `window.marktextAPI` 能力面。不要直接复用现有 `window.marktext`，因为它已经被 renderer 用作启动环境和路径状态。

```ts
type IpcError = {
  code:
    | 'INVALID_ARGUMENT'
    | 'NOT_FOUND'
    | 'PERMISSION_DENIED'
    | 'CONFLICT'
    | 'CANCELLED'
    | 'UNAVAILABLE'
    | 'INTERNAL'
  message: string
  retryable: boolean
  requestId?: string
  details?: Record<string, string | number | boolean | null>
}

type Reply<T> =
  | { ok: true; value: T }
  | { ok: false; error: IpcError }
```

规则如下：

- 新 channel 使用 `mt::v1::<domain>::<operation>`；旧 channel 保留兼容别名，不进行一次性重命名。
- renderer → main 的业务操作优先 `invoke`，统一返回 `Promise<Reply<T>>`。
- `send` 只用于无结果、失败也无需处理的通知；保存、重命名、上传、更新设置等操作应能返回结果。
- main → renderer 事件统一使用一个对象 payload，不再使用易漂移的位置参数。
- 所有跨进程数据必须是结构化克隆安全的 plain object、数组、字符串、数字、布尔值或明确允许的二进制类型；不要公开 `Error`、Vue Proxy、函数、Electron 对象或业务 `Map`。
- `Map<string, string>` 改为 `Record<string, string>` 或 `[key, value][]`。
- main 统一把已知异常映射为 `IpcError`，未知异常记录完整 stack 并返回 `INTERNAL + requestId`。
- transport 故障仍可 reject；业务失败走 `Reply.ok: false`，不能混用 `false`、空字符串和错误文本。
- preload 只暴露命名能力，例如 `fs.readFile`、`windowControl.maximize`、`keybindings.save`，不再长期暴露通用 `ipcRenderer.send/invoke`。
- 事件订阅只返回自己的 `off()`；renderer API 不应再暴露 `removeAllListeners()`。
- `sendSync` 不新增使用；`mt::boot-info` 和路径同步查询作为 legacy，逐步迁移到异步或 renderer 本地纯函数。

建议的结构是：

```text
renderer feature
    ↓
preload named capability
    ↓
typed IPC adapter
    ↓
main handler + runtime validation
    ↓
main service / native adapter
    ↑
Reply<T> or typed event
```

main 内部则使用独立的 typed event bus，不再用 `ipcMain.emit` 伪装内部消息。现有 `TypedEmitter` 可以承担这个 seam。

## 方案比较

| 方案 | 优点 | 代价与风险 |
|---|---|---|
| A. 继续收紧现有四张 channel map | 改动最小，兼容性最好 | 通用 `ipcRenderer`、内部/外部 channel 混用和事件生命周期问题仍然存在 |
| B. 能力型 preload + `v1` 契约 + 独立 main bus | 边界清晰，错误、测试、权限和多窗口路由都能局部演进 | 需要兼容层和逐批迁移 |
| C. 立即引入 schema/codegen 覆盖全部 IPC | 运行时校验最强 | 目前没有独立 renderer/plugin 版本需求证据，初期成本和抽象面偏大 |

推荐 B。它保留现有代码的渐进迁移空间，也不要求现在就为所有 channel 引入完整 schema 生成体系。

## 迁移顺序与验证

1. 先建立 channel inventory，把 `renderer↔main`、`main↔renderer`、`main internal` 三类分开；同时修正文档中仍称 `contextIsolation: false` 的过时描述，实际配置已经是 sandbox 模式。
2. 引入 `Reply<T>`、`IpcError`、结构化克隆安全类型和 typed `sendToRenderer()`；所有 main → renderer 发送必须经过该 helper。
3. 以 `mt::fs::stat`、`mt::fs::read-file` 作为第一个 vertical slice：同时验证参数、返回值、文件错误、preload facade、main handler fake 和 E2E。
4. 迁移 keybinding、窗口状态和菜单事件，消除已确认的 shape mismatch。
5. 迁移 ripgrep：由 main 统一拥有 operation ID，明确 `started/match/progress/done/error/cancelled` 且 terminal event 只出现一次。
6. 最后迁移保存、重命名、上传等复杂操作，删除 renderer 对通用 `ipcRenderer` 的直接调用。

完成标准：

- v1 契约中不再出现无说明的 `unknown`、`void` 哨兵或 `as unknown as`。
- 每个外部 channel 有且只有一份 request/response/event 定义。
- main handler 和 `webContents.send` 都由共享类型检查。
- 业务错误都能断言稳定的 `IpcError.code`。
- 单测不依赖真实 Electron；preload、handler、事件订阅分别有独立 contract test。
- E2E 继续保留 context isolation 哨兵，但另加真实 preload facade 测试；直接 `webContents.send` 的测试明确标注为绕过 preload 的行为测试。
- 每个 handler 注册函数可返回 disposer，测试不会污染全局 `ipcMain`。

## 尚待确认的决策

- 是否存在第三方插件或独立 renderer 客户端，决定 `v1/v2` 的实际兼容压力。
- `isSamePathSync` 的同步延迟是否有真实性能预算；否则应优先移除同步 IPC。
- 是否所有 invoke 都采用 `Reply<T>`，还是仅业务失败明显的 domain 使用 envelope。
- keybinding 是否必须保留 `Map` 作为 renderer 内部实现；即使保留，也不应直接作为跨进程协议。

[EVAL:evolve-software-architecture-loaded]
