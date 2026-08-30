只读评估完成：未修改文件、未创建提交、未改变外部状态。

## 范围与结论

MarkText 是 Electron 42 + Vue 3 + TypeScript 的桌面应用，main、preload、renderer 已有明确目录边界。当前 IPC 处于“迁移中的类型表 + raw `ipcRenderer` façade”阶段：

- contextBridge 安全基线是成立的；
- renderer 调用点有静态类型；
- 但 main 注册端、main→renderer 发送端、运行时错误和序列化尚未形成闭环契约；
- 建议保留现有 channel 兼容迁移，逐步引入按领域划分的 API、运行时校验和独立的 main 内部事件总线。

## 观察到的事实

| 事实 | 证据 | 判断 |
|---|---|---|
| 两类 BrowserWindow 都启用了 `contextIsolation`、sandbox，并关闭 `nodeIntegration` | [`config.ts:12`](/evaluation-path/treatment/packages/desktop/src/main/config.ts:12) | 事实，高置信度 |
| e2e 已验证 bridge 存在且 `require/global/Buffer` 不泄漏 | [`context-isolation.spec.ts:24`](/evaluation-path/treatment/packages/desktop/test/e2e/context-isolation.spec.ts:24) | 事实，高置信度 |
| preload 的 `send/invoke/on` 只是在 raw IPC 外包了一层泛型 | [`preload/index.ts:26`](/evaluation-path/treatment/packages/desktop/src/preload/index.ts:26) | 事实，高置信度 |
| main 端大量直接调用 `ipcMain.handle/on`，没有统一从共享契约注册 | [`main/index.ts:77`](/evaluation-path/treatment/packages/desktop/src/main/index.ts:77)、[`accessor.ts:32`](/evaluation-path/treatment/packages/desktop/src/main/app/accessor.ts:32) | 事实，高置信度 |
| 共享 IPC 类型仍明确允许大量 `unknown` | [`ipc.ts:10`](/evaluation-path/treatment/packages/desktop/src/shared/types/ipc.ts:10) | 迁移遗留 |
| contract 与运行时已有形状不一致 | `ask-for-image-path` 声明返回 `string[]`，实际返回单个字符串：[`ipc.ts:41`](/evaluation-path/treatment/packages/desktop/src/shared/types/ipc.ts:41)、[`dataCenter/index.ts:194`](/evaluation-path/treatment/packages/desktop/src/main/dataCenter/index.ts:194) | 事实，高置信度 |
| `mt::rg::start` 类型返回 `{searchId}`，main 实际返回 `true` | [`ripgrep.ts:433`](/evaluation-path/treatment/packages/desktop/src/main/ipc/ripgrep.ts:433) | 事实，高置信度 |
| `window-active-status` 类型声明为 boolean，main 发送 `{ status: boolean }` | [`editor.ts:237`](/evaluation-path/treatment/packages/desktop/src/main/windows/editor.ts:237) | 事实，高置信度 |
| menu click/closed 的声明与实际 `{windowId,id}` payload 也不一致 | [`window.ts:37`](/evaluation-path/treatment/packages/desktop/src/main/ipc/window.ts:37) | 事实，高置信度 |
| 错误语义不统一：有的 reject，有的返回 `false`、空字符串或错误文本 | [`shell.ts:6`](/evaluation-path/treatment/packages/desktop/src/main/ipc/shell.ts:6) | 事实，高置信度 |
| unit 测试使用 jsdom 和手工 window stub；Vitest 未配置统一 mock cleanup | [`vitest.config.ts:8`](/evaluation-path/treatment/packages/desktop/vitest.config.ts:8) | 事实，高置信度 |
| e2e 的 `sendIpcToRenderer` 使用裸 `string` 和 `unknown[]`，会绕过契约 | [`helpers.ts:355`](/evaluation-path/treatment/packages/desktop/test/e2e/helpers.ts:355) | 事实，高置信度 |

另外，`CLAUDE.md` 仍保留 `contextIsolation: false + nodeIntegration: true` 的旧描述，与实际配置相反：[`CLAUDE.md:243`](/evaluation-path/treatment/CLAUDE.md:243)。

## 当前主要摩擦

1. `shared/types/ipc.ts` 只约束了 renderer→preload 的 TypeScript 调用点，不能约束 main 的 handler 和 `webContents.send`。
2. `IpcSendChannels` 同时混入 renderer→main IPC 与 `ipcMain.emit` 的 main 内部事件，边界被混淆。
3. `window.electron.ipcRenderer` 仍允许 renderer 直接选择 channel；`removeAllListeners(string)` 和动态 channel 还提供了逃生通道。
4. 类型中的 `unknown` 和运行时 `as unknown as` 让类型错误延迟到运行时。
5. `IFileState` 等状态类型与 IPC DTO 混用；例如 `FileNotification.action` 是函数，不能跨 structured clone 边界安全传输：[`files.ts:97`](/evaluation-path/treatment/packages/desktop/src/shared/types/files.ts:97)。
6. renderer 错误上报目前是裸对象发送给 main：[`bootstrap.ts:77`](/evaluation-path/treatment/packages/desktop/src/renderer/src/bootstrap.ts:77)，但 main 仍按 `Error` 接收，错误字段没有稳定协议。

## 建议的长期契约

### 1. 分离四种边界

```text
RendererCommandMap   renderer → main，请求/响应
RendererIntentMap    renderer → main，无需结果的意图
MainEventMap         main → renderer，单向事件
MainInternalEventMap main 内部模块之间，不经过 Electron IPC
```

不要再把 main 内部的 `ipcMain.emit('window-add-file-path', ...)` 放入 renderer-facing map。main 内部应使用 typed emitter 或直接调用服务方法。

### 2. 请求统一使用单一对象

不要继续扩展位置参数和动态 channel。推荐语义：

```ts
'files.selectImage':
  request  {} 
  response { path: string | null }

'fs.readFile':
  request  { path: string; encoding?: string }
  response { kind: 'text'; data: string }
         | { kind: 'bytes'; data: Uint8Array }

'window.activeChanged':
  event { active: boolean }

'menu.clicked':
  event { id: string }
```

`windowId` 默认由 main 从 `event.sender` 推导，不信任 renderer 自己传入的 windowId。

### 3. 采用 wire-level Result，区分业务错误和传输错误

建议 Electron 线上传输使用：

```ts
type WireResult<T> =
  | { ok: true; value: T; requestId: string }
  | {
      ok: false
      error: {
        code: string
        message: string
        retryable: boolean
        details?: unknown
      }
      requestId: string
    }
```

preload 将 `ok: false` 转换为本地 `IpcError`；renderer 继续使用 Promise，但不再依赖空字符串、`false` 或错误文本表示失败。

错误语义应固定为：

- 用户取消：成功返回 `null` 或明确的 `cancelled` 状态；
- 文件不存在、权限不足：稳定错误码；
- main/renderer 被销毁：`transport-unavailable`；
- 未预期异常：main 记录完整 stack，renderer 只收到通用错误；
- renderer 错误上报：独立的 `RendererErrorReport` DTO，不传 `Error` 实例。

### 4. preload 只暴露领域 API

`window.electron.ipcRenderer` 应作为兼容层逐步冻结，新代码不再直接调用它。由于 `window.marktext` 已被启动状态占用，建议使用独立命名空间，例如：

```ts
window.marktextApi.files.selectImage()
window.marktextApi.fs.readFile(...)
window.marktextApi.search.start(...)
window.marktextApi.events.on(...)
```

保留现有 `window.fileUtils`、`window.ripgrep` 等作为过渡 façade，但内部都应落到同一套契约。移除或限制 `removeAllListeners`，只返回精确的 unsubscribe 函数。

### 5. 对流式操作使用稳定事件而不是动态 channel

ripgrep 应改成：

```ts
search.start(request) -> { operationId }

search.event -> 
  | { operationId; kind: 'match'; ... }
  | { operationId; kind: 'progress'; count: number }
  | { operationId; kind: 'done' }
  | { operationId; kind: 'cancelled' }
  | { operationId; kind: 'error'; error: IpcError }

search.cancel({ operationId })
```

这样可以统一处理取消、renderer 销毁、事件清理和错误传播，也能去掉当前大量 `unknown`。

## 方案比较

| 方案 | 优点 | 代价与风险 |
|---|---|---|
| A. 保留现状，只继续补全 `ipc.ts` | 改动小，适合短期修错 | main 仍不受约束，raw channel、内部事件和运行时校验问题继续存在 |
| B. 保留旧 channel，增加 contract-first domain façade | 迁移可逆；能同时解决类型、错误、contextBridge 和测试边界 | 需要逐步迁移 renderer 调用点和测试 |
| C. 立即引入完整 schema/codegen RPC 框架 | 运行时校验和生成能力最强 | 当前 main/preload/renderer 同版本打包，没有外部 IPC 客户端；初期抽象成本过高 |

推荐 B。MarkText 当前最需要的是边界收敛，而不是一次性引入大型 RPC 框架。

## 分阶段迁移建议

1. 先建立实际 channel inventory，区分 renderer-facing、main event、main internal；同时修正文档中的旧 sandbox 描述。
2. 增加纯 TypeScript 的 `IpcError`、`WireResult`、可序列化 DTO 和 typed registration/send helper。
3. 以 ripgrep 作为第一个完整 vertical slice：它同时覆盖 invoke、事件流、取消、错误和 renderer 销毁。
4. 接着迁移 `ask-for-image-path`、window/menu 事件，先修复已确认的返回值和 payload 漂移。
5. 再迁移 filesystem、shell、clipboard、save/close 流程；对有用户可见失败的 `send` 改成可确认结果的 invoke。
6. renderer 新代码只依赖 `marktextApi`；旧 raw IPC 保留为 deprecated adapter，待调用点清空后移除。
7. 最后将 e2e 的 raw 注入 helper 限制为故障注入用途，并为普通事件注入提供基于 `MainEventMap` 的 typed helper。

## 测试隔离与验收标准

建议拆成三层：

- shared contract：验证 DTO、错误码、structured-clone 可序列化性；
- preload/main：mock `ipcRenderer`、`contextBridge`、`ipcMain`，验证注册、转发、错误映射和 unsubscribe；
- renderer：只注入 `MarkTextApi` fake，不再手工拼装 `window.electron.ipcRenderer`。

现有 unit 测试应逐步改为每个测试创建独立 API fake，并统一 `restoreMocks/clearMocks`；不要依赖 `window.electron ??=` 这种跨测试文件的隐式全局状态。

完成标准：

- main handler 和 main event sender 都必须引用共享 map；
- 同一个 channel 不同时承担 invoke 和 send 两种语义；
- 新 renderer 代码不出现 channel 字符串；
- 协议 DTO 不含函数、BrowserWindow、Vue Proxy 或 Node 专属对象；
- malformed request、权限失败、取消、renderer 销毁均有测试；
- context isolation e2e 继续验证 `require/global/Buffer` 不可用；
- 现有行为测试和 `pnpm typecheck` 均通过。

## 未决问题

这些问题会影响后续安全边界和版本策略：

- 是否需要支持插件、第三方 renderer 或不可信 Markdown 内容执行环境？
- 是否存在独立升级 renderer、热加载旧 renderer 或跨版本 main/renderer 通信的需求？
- filesystem/shell API 是否允许 renderer 访问任意绝对路径，还是应由 main 按当前窗口和项目根目录限制？

以上建议遵循了仓库实际运行时代码优先、区分事实与推断的评估方式；本次没有实施任何代码变更。

[EVAL:evolve-software-architecture-loaded]
