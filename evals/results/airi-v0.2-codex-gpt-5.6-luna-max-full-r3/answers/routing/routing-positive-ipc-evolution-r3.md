结论：建议保留 Eventa 作为传输层，但在其上补一层“窄化 preload + 中立契约 + main 端统一边界治理”。不建议现在把约 140 个 IPC handler 全部改成裸 `ipcMain.handle`，也不建议一开始为每个消息引入复杂版本协商。

## 范围与判断依据

范围是 `apps/stage-tamagotchi` 的 Electron main、preload、renderer，以及 `packages/electron-eventa`、`packages/electron-vueuse`、`packages/stage-shared`。以下判断来自仓库静态检查，未修改文件、未创建提交。

| 观察到的事实 | 证据 | 架构含义 |
|---|---|---|
| main、preload、renderer 分别构建 | [electron.vite.config.ts](/evaluation-path/treatment/apps/stage-tamagotchi/electron.vite.config.ts:1) | 三者虽同版本发布，但运行时仍是独立边界 |
| preload 暴露完整 `electronAPI`，包含 `ipcRenderer` | [preload/shared.ts](/evaluation-path/treatment/apps/stage-tamagotchi/src/preload/shared.ts:1) | renderer 可以绕过领域封装，契约边界较弱 |
| renderer Eventa context 使用全局单例 | [use-electron-eventa-context.ts](/evaluation-path/treatment/packages/electron-vueuse/src/composables/use-electron-eventa-context.ts:1) | 测试和多窗口隔离依赖 reset 或手工注入 |
| 大量契约集中在一个 app 文件 | [shared/eventa/index.ts](/evaluation-path/treatment/apps/stage-tamagotchi/src/shared/eventa/index.ts:1) | 已形成注册热点，且部分类型含 `Record<string, any>` |
| main 已按窗口创建 Eventa context，并且历史上修复过“先 load、后注册 handler”问题 | [main/rpc/index.electron.ts](/evaluation-path/treatment/apps/stage-tamagotchi/src/main/windows/main/rpc/index.electron.ts:1) | handler-before-load 应成为正式生命周期约束 |
| sender 校验分散在 widgets、window、screen capture 等模块 | [widgets service](/evaluation-path/treatment/apps/stage-tamagotchi/src/main/services/airi/widgets/index.ts:1)、[screen capture](/evaluation-path/treatment/packages/electron-screen-capture/src/main/index.ts:204) | 窗口作用域目前是“上下文绑定 + 手工检查”的混合模式 |
| 测试主要使用内存 Eventa context 和 mock，没有完整 Electron adapter 集成测试 | [app.test.ts](/evaluation-path/treatment/apps/stage-tamagotchi/src/main/services/electron/app.test.ts:1)、[widgets/index.test.ts](/evaluation-path/treatment/apps/stage-tamagotchi/src/main/services/airi/widgets/index.test.ts:1) | 纯业务测试隔离较好，但真实边界仍缺少少量烟测 |

## 推荐的目标结构

```text
renderer 领域 client
        ↓
注入式 typed IPC client
        ↓
preload: window.airi.ipc      // 仅暴露窄传输能力
        ↓
Eventa / Electron transport
        ↓
main: window/app IPC host      // 作用域、校验、错误、生命周期
        ↓
领域 service

共享的中立 contract/schema 同时被 main 与 renderer 使用
```

### 1. 契约版本

建议采用以下规则：

- Eventa 继续作为传输机制，稳定的 channel/event ID 作为协议标识。
- 不使用应用版本 `0.11.3` 直接代表 IPC 版本。
- 普通兼容变更采用新增字段、可选字段和忽略未知字段。
- 改变字段语义、请求结构或返回结构时，使用新的 `v2` channel/contract；不要让同一个 ID 隐式改变含义。
- 只做一次启动握手，例如报告 `protocolRevision`、应用构建版本和 capability 集合；不要为每个 invoke 都做版本协商。
- 插件、widget iframe、MCP 等独立扩展边界应拥有单独版本，因为它们更可能出现独立升级。

当前 main、preload、renderer 通常随同一 Electron 构建发布，因此对每条消息做运行时版本协商的收益不高。启动握手主要用于发现部分更新、旧 preload 或不完整安装。

契约应按领域拆分，而不是继续扩展单一 `shared/eventa/index.ts`。通用 Electron 契约继续归 `packages/electron-eventa`；stage-tamagotchi 专属契约可按 app/domain 模块组织，并由现有入口重新导出，降低迁移时的 import 改动。契约模块应尽量不携带 Electron、Node、server runtime 的运行时依赖。

### 2. preload

长期目标是：

- 只通过 `contextBridge` 暴露 `window.airi`；
- 不再暴露完整 `ipcRenderer`；
- preload 只负责桥接和最小参数处理，不承载业务逻辑；
- renderer 使用注入式 IPC client，而不是直接读取 `window.electron`。

为控制迁移成本，不建议一次性为所有现有 handler 手写大量 wrapper。可以先暴露一个受契约注册表约束的窄 transport，再逐步把高风险能力提升为领域 API，例如 window、auth、widgets、filesystem 等。

现有 `contextIsolated === false` 分支可以作为迁移期兼容路径，但目标应是将 context isolation 视为 Electron 应用不变量。

### 3. main 端

建议引入明确的 IPC host/registrar 约定：

- `app-scoped` 与 `window-scoped` context 分开注册；
- main 根据 `event.sender` 解析窗口，不信任 renderer 传入的 window ID；
- 每个 registrar 返回 `dispose()`；
- `window.closed`、`render-process-gone` 时统一清理 handler、监听器和 pending request；
- 继续保持“注册 handler 后再 load 页面”；
- 等统一 host 和 Eventa 窗口隔离成熟后，再移除各处的 `ipcMain.setMaxListeners(0)` workaround。

这会把目前分散在 widgets、window、screen-capture 等处的 sender 校验收拢为边界策略。领域 service 仍可以保留更严格的业务授权检查，但不应重复承担基础窗口路由职责。

## 错误传播建议

Eventa handler 抛出的错误可以传播到 renderer，但不应直接把原始 `Error` 当作长期协议。

建议统一为可结构化的错误信息：

```text
code
message       // 安全、可展示或可映射
retryable
requestId
details       // 经过约束的结构化数据
```

推荐采用混合策略：

- 参数错误、权限错误、窗口已销毁、服务未就绪、内部异常：统一 reject 为 IPC error；
- 业务上“失败但属于正常决策”的结果继续使用 typed result，例如冲突、降级、MCP 测试结果中的 `isError`；
- main 记录完整错误和 requestId，renderer 只接收安全信息；
- 错误文本提取继续使用仓库约定的 `errorMessageFrom`；
- 不跨进程传递 stack、原始 cause、服务端响应或敏感环境信息。

这样既保留现有 `try/catch` 调用习惯，也避免不同模块分别定义 `lastError`、`isError`、普通 `Error` 等多种协议。

## 测试隔离

建议分三层：

1. 契约测试：对序列化后的请求、响应、错误和非法 payload 做 fixture 测试，main 与 renderer 共用。
2. main handler 测试：继续使用内存 Eventa context，但把 fake window、sender、scope、dispose 作为显式 fixture。
3. 少量 Electron 集成烟测：覆盖启动握手、错误序列化、错误 sender、窗口销毁后的 pending request，以及 handler-before-load。

renderer 侧应把 IPC client 作为依赖注入。这样 `stage-ui`、`stage-pages` 和 composable 测试不需要伪造完整的 `window.electron.ipcRenderer`，也不需要依赖全局 singleton。现有 `resetElectronEventaContextForTesting()` 可以保留为过渡手段，但不宜成为长期测试架构。

## 方案取舍

| 方案 | 优点 | 代价与风险 |
|---|---|---|
| 保持现状 | 迁移成本最低，已有 Eventa 使用广泛 | raw `ipcRenderer`、契约热点、错误和作用域策略分散 |
| 推荐：窄 preload + 中立契约 + Eventa host | 演进性、测试隔离和边界安全明显改善；可渐进迁移 | 需要增加 host、错误模型和生命周期约定 |
| 全面改为裸 Electron IPC 或替换 Eventa | 表面结构简单 | 约 140 个 handler、跨窗口复用、screen capture 和现有测试都要重写，迁移风险最高 |

## 建议的迁移顺序

1. 先盘点并标记所有 contract 的 `app` / `window` / `extension` scope，冻结现有 channel ID。
2. 选一个小领域引入统一 error envelope、scope host 和 disposer，例如 app 或 window lifecycle。
3. 引入窄 preload transport，同时让现有 Eventa renderer adapter 通过它工作；暂时保留旧 raw API 作为明确的迁移适配层，并设定删除条件。
4. 按领域拆分共享契约，保留旧入口的 re-export，避免一次性修改所有调用方。
5. 迁移 screen capture、widgets、image journal、artistry 等直接访问 `window.electron.ipcRenderer` 的路径。
6. 补少量真实 Electron 边界测试后，再移除 raw API、全局 listener workaround 和测试 reset 依赖。

这一路径的关键是先保持现有 Eventa ID 和业务行为不变，把“边界治理”与“业务重构”分开，迁移成本和回退难度都较低。

尚需确认的决策包括：是否存在独立更新 main/preload/renderer 的发布流程、插件和 iframe 是否需要跨版本兼容、Eventa 当前 context 是否能可靠释放窗口级 handler，以及错误码是否需要由 renderer 统一本地化。

本次仅进行了 `git`、`rg`、文件阅读和历史查看等只读检查，未修改文件、未创建提交、未运行可能产生缓存或外部状态变化的构建和测试命令。

[EVAL:evolve-software-architecture-loaded]
