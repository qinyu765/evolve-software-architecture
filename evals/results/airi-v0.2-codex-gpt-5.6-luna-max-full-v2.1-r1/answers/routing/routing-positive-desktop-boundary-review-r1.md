## 结论

当前 AIRI 桌面端的 main / preload / renderer 三分结构清晰，足以支撑现有的本地可信插件和多个辅助窗口。长期瓶颈不在 Electron 进程划分，而在：

1. 窗口能力通过多个 RPC 文件手工拼装，缺少显式的 `window role + capability` 模型。
2. renderer 通过路由判断窗口角色，并初始化大量全局 runtime，窗口扩展会放大状态和生命周期耦合。
3. 插件运行时代码通过动态 `import()` 进入 main 进程，当前权限模型不是进程隔离模型。
4. 共享 IPC 契约仍集中在应用本地 barrel，且存在重复类型和宽泛 payload。

建议采用“main 宿主 + 显式窗口会话/能力 broker + side-effect-free 协议包”的方向；保留 Eventa，不立即重写成新的 RPC 或微服务。插件进程隔离应作为有明确非信任插件需求后的第二阶段。

## 范围与置信度

评估基于当前 checkout 的 `HEAD 5228f9412`，只读检查了 main、preload、renderer、窗口管理、Eventa 契约、插件 host/SDK、静态资源服务和 Electron 场景。代码路径判断置信度高；插件信任模型、生产窗口数量、实际性能和崩溃数据尚未从仓库中确认。

本轮未运行构建、lint 或测试，以避免只读任务产生缓存或构建产物；工作区未显示文件变更。

## 当前边界

| 层 | 当前职责 | 评价 |
|---|---|---|
| main | 通过 Injeca 组装全局服务、窗口、插件 host、server channel、MCP、Godot 等；也是插件运行时和外部 IO 的实际权威。[main 组装根](/evaluation-path/treatment/apps/stage-tamagotchi/src/main/index.ts:132) | [事实] 方向正确，但 composition root 已承担较多窗口与业务编排。 |
| preload | 主要暴露 Electron API、platform 和自定义 API；所有普通窗口复用同一个 preload。[preload bridge](/evaluation-path/treatment/apps/stage-tamagotchi/src/preload/shared.ts:8) | [事实] 很薄；但目前不是按窗口角色划分的能力面。 |
| renderer | 一个 renderer bundle 通过 hash route 服务 main、settings、chat、widgets 等窗口。[renderer 配置](/evaluation-path/treatment/apps/stage-tamagotchi/electron.vite.config.ts:94) | [推断] 适合复用 UI，但角色边界主要靠路由和条件分支表达。 |
| shared | 应用本地 `shared/eventa` 同时承载窗口、app、MCP、widgets、插件等契约。[shared Eventa barrel](/evaluation-path/treatment/apps/stage-tamagotchi/src/shared/eventa/index.ts:31) | [推断] 更像兼容性总入口，尚不是稳定的领域协议边界。 |
| plugin | main 中加载本地 extension entrypoint，host 管理 session、权限、binding、清理；UI 通过 widget renderer/iframe 展示。[plugin host bootstrap](/evaluation-path/treatment/apps/stage-tamagotchi/src/main/services/airi/plugins/host/index.ts:224) | [事实] 生命周期模型已有基础；[事实] 运行时代码仍在 main 进程内。 |

已有的好基础包括：

- 每个窗口可以创建绑定到具体 `BrowserWindow` 的 Eventa context。[referenced window](/evaluation-path/treatment/apps/stage-tamagotchi/src/main/windows/shared/referenced-window.ts:40)
- widgets、window、auth 等服务已有 sender 校验。[widgets sender check](/evaluation-path/treatment/apps/stage-tamagotchi/src/main/services/airi/widgets/index.ts:33)
- 插件 session、asset session、tool cleanup 已有 owner/session 维度。[plugin unload](/evaluation-path/treatment/apps/stage-tamagotchi/src/main/services/airi/plugins/host/index.ts:363)
- 静态资源服务有 cookie session、路径规范化、版本校验和撤销机制。[asset route](/evaluation-path/treatment/apps/stage-tamagotchi/src/main/services/airi/http-server/static-assets/route.ts:42)
- 已有插件 host、iframe 静态资源和 Worker 的 Electron 场景验证。[plugin worker scenario](/evaluation-path/treatment/packages/scenarios-stage-tamagotchi-electron/src/scenarios/plugin-chess-worker-smoke.ts:320)

## 主要架构摩擦

1. 窗口能力重复拼装

main、settings、chat 等窗口分别执行 `createContext`、注册 base invokes，再追加自己的服务。[main RPC](/evaluation-path/treatment/apps/stage-tamagotchi/src/main/windows/main/rpc/index.electron.ts:43)

[推断] 新增窗口通常会同时修改窗口工厂、RPC 注册、路由、renderer 条件、共享契约和生命周期清理，变更放大较明显。

2. Eventa 的窗口隔离仍依赖约定

多个位置都有 `setMaxListeners` 和“等待 window-namespaced context”的 TODO。[window manager TODO](/evaluation-path/treatment/apps/stage-tamagotchi/src/main/windows/shared/referenced-window.ts:41)

[事实] 目前依靠 context 绑定和手工 sender 检查来保证隔离。[推断] 当窗口、广播事件、request/response 数量继续增加时，遗漏检查、清理或 correlation key 会成为主要风险。

3. renderer 角色边界隐式

`App.vue` 对多数路由创建 `createFullStageRuntime()`，其中包含 settings、analytics、MCP、插件工具、Godot、cursor、context bridge 等初始化。[renderer runtime](/evaluation-path/treatment/apps/stage-tamagotchi/src/renderer/App.vue:79)

[推断] settings/chat/widgets 等窗口的“进程本地状态”和“窗口本地状态”没有通过架构对象明确区分，未来多窗口并行运行时会增加重复订阅、重复初始化和销毁顺序问题。

4. 协议所有权不稳定

应用契约同时包含 plugin、widgets、MCP、window、Godot 等领域；插件能力类型还明确存在手工重复并计划重新导出。[重复类型 TODO](/evaluation-path/treatment/apps/stage-tamagotchi/src/shared/eventa/index.ts:218)

此外，部分 payload 仍是 `Record<string, any>`。[widget payload](/evaluation-path/treatment/apps/stage-tamagotchi/src/shared/eventa/index.ts:122)

5. 插件权限不等于插件隔离

插件 entrypoint 通过 `import()` 加载。[filesystem loader](/evaluation-path/treatment/packages/plugin-sdk/src/plugin-host/runtimes/node/loaders/fs.ts:72)

当前 node runtime 对 worker、WebSocket、Electron transport 仍明确抛出“未实现”。[plugin transport](/evaluation-path/treatment/packages/plugin-sdk/src/plugin-host/runtimes/node/index.ts:24)

[推断] 当前模型适合“可信本地扩展”；如果将来允许不受信任的第三方插件，权限检查无法阻止同一 main 进程中的崩溃、资源滥用或 Node/Electron 级影响。

## 长期目标形态

```text
Electron main
  AppRuntime：全局状态、外部 IO、插件权限与 session
  WindowRegistry
    └─ WindowSession(windowId, role, capabilities, disposer)
  PluginHost
    └─ PluginSurfaceAdapter -> widgets / tools / assets
    └─ 可选 Plugin Worker / Utility Process

preload
  仅提供最小 transport bootstrap 和平台信息

renderer window
  role boot -> window-local state -> Vue pages
  通过 capability-scoped Eventa 调用 main

shared
  desktop protocol / plugin protocol / domain contracts
  不依赖 Electron、Vue 或 main runtime
```

核心原则：

- main 是全局状态、权限、插件 session、窗口注册和外部 IO 的唯一权威。
- renderer 只拥有视图和窗口局部状态；跨窗口状态通过命令、查询、事件同步。
- 每个窗口显式声明 `role` 和 capability，例如 `widgets.read`、`plugin.inspect`、`global-shortcut.manage`，不要再默认给所有窗口同一套 base 能力。
- `WindowSession` 集中保存 `windowId`、BrowserWindow、Eventa context、capability 集和 disposer，统一 sender 校验、request correlation 和关闭清理。
- `shared/eventa` 逐步退化为 re-export façade。Electron IPC 契约优先评估放入现有 `@proj-airi/electron-eventa`；插件跨运行时契约继续由 `plugin-protocol` / SDK 所有。[plugin protocol](/evaluation-path/treatment/packages/plugin-protocol/README.md:1)
- 插件 host 核心只拥有 session、权限、binding、资源和生命周期；widgets、tools 等作为 adapter 注入。现有代码已经标记 tool registry ownership 需要调整。[ownership review](/evaluation-path/treatment/apps/stage-tamagotchi/src/main/services/airi/plugins/host/index.ts:435)
- 对可信插件保留 main 内运行；只有在“不信任第三方插件”或“插件崩溃不能影响主应用”成为硬需求时，才引入 worker/utility process。

## 方案比较

| 方案 | 优点 | 局限 | 适用性 |
|---|---|---|---|
| 继续当前 per-window Eventa | 成本最低，已有实现和测试最多 | 能力漂移、手工隔离、renderer 角色耦合持续增长 | 当前可信插件、窗口数量有限 |
| 推荐：WindowSession + capability broker | 保留 Eventa，渐进迁移；新增窗口和插件能力有稳定接入点；更易测试 | 需要重组 RPC 注册和 renderer 启动 | AIRI 的长期默认方向 |
| 立即全面进程隔离插件 | 安全和崩溃隔离最强 | 当前 SDK transport 尚未具备，协议、调试、升级和性能成本高 | 仅当第三方插件信任边界已确定 |

## 可逆迁移步骤

1. 先写架构决策记录，不改行为：列出窗口角色、能力、状态所有权、插件信任等级和关闭清理责任。

2. 选择一个垂直契约切片，例如 window lifecycle 或 plugin tools。把 schema、错误 envelope、`requestId` 和 owner 字段放到稳定协议包；应用本地 barrel 只做静态 re-export。回滚只需恢复 import，不保留运行时双路径。

3. 引入内部 `WindowSession` façade，内部仍调用现有 `createContext(ipcMain, window)` 和 sender 检查。先迁移能力较窄的 chat，再迁移 settings；旧 RPC setup 暂作为 adapter 保留。

4. 将 `App.vue` 的 `createFullStageRuntime()` 拆成 role boot factories。先迁移 settings/chat，保持路由和页面不变；widgets 因 iframe relay 较复杂，后迁移。

5. 将 tool registry ownership 移入 plugin host，widgets/gamelet 通过窄接口接入；保留当前 in-process loader、asset session 和 iframe 协议。

6. 只有满足隔离条件时再增加 process adapter：先让一个 plugin kit 使用序列化 Eventa broker，验证超时、崩溃、重启、权限撤销和 session 清理，再扩大范围。旧 manifest 仍可回到 `electron` runtime。

## 验证方法

- 契约：验证 Eventa identity、序列化、非法 payload、错误 envelope、版本不匹配；协议包不得导入 Electron/Vue。
- 多窗口：同时打开 main/settings/chat/widgets，验证 sender 错误被拒绝、相同 request ID 不串窗、关闭后 handler/listener 被清理、重复打开/关闭可恢复。
- renderer：每种 role 的初始化只执行一次；窗口销毁后订阅、Pinia store bridge、工具列表都被释放。
- 插件：覆盖 manifest 校验、权限交集、binding ownership、load/unload/reload、asset revoke、iframe source/handshake、超时和异常。
- 现有回归入口：stage-tamagotchi typecheck、插件/static-assets/widgets/window 相关 Vitest，以及已有的 `plugin-chess-worker-smoke` 和 `plugin-widget-static-assets-local-address` 场景。后两者能证明插件 UI 资源与 Worker 流程可用，但不能证明 main 进程隔离。
- 操作性：日志和事件统一携带 `windowId`、`role`、`requestId`、`extensionId`、`sessionId`；测量窗口数量增加时的启动时间、内存和插件调用延迟。
- 安全决策：明确“本地可信插件”还是“第三方不可信插件”。后者必须额外验证 Electron `sandbox`、context isolation、Node 能力和崩溃边界，不能只依赖 SDK permission。

## 尚需确认的决策

- 插件是否允许来自不受信任的第三方市场？
- 插件是否必须在 renderer 崩溃后继续运行？
- 未来是否存在多个账号、profile 或独立 workspace？
- plugin SDK 是否需要独立版本、兼容矩阵和远程 transport？
- 目标窗口数量和平台范围是多少？

[EVAL:evolve-software-architecture-loaded]
