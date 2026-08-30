结论：AIRI 桌面端的 `main` 组合根和窗口服务已经成形，当前最需要治理的是“隐式边界”：

- preload 暴露过宽，renderer/shared package 可以接触原始 `ipcRenderer`。
- 多窗口角色主要由 route 判断，缺少显式的 `WindowSession/WindowRole`。
- Eventa 已有按窗口创建 context 的意图，但隔离仍依赖手工过滤及 `setMaxListeners` 临时措施。
- 插件生命周期和协议基础不错，但扩展代码目前直接运行在 main 进程，尚不具备进程级安全边界。

本次基于当前 HEAD 做了静态只读检查，未修改文件、未提交，也未运行可能产生缓存或启动外部进程的验证命令。静态边界判断可信度高；Eventa 底层 dispatch 细节和实际多窗口运行表现未验证。

## 1. 当前边界证据

| 区域 | 可观察事实 | 评价 |
|---|---|---|
| main | `main/index.ts` 用 injeca 组装配置、server、MCP、插件和多个窗口；窗口工厂再注册各自 RPC。[main/index.ts](/evaluation-path/treatment/apps/stage-tamagotchi/src/main/index.ts:132) | 组合根方向正确，但依赖图已较密集 |
| preload | `preload/shared.ts` 暴露 `electronAPI`、`platform`，并允许 renderer 通过 `window.electron.ipcRenderer` 建立任意 Eventa context。[shared.ts](/evaluation-path/treatment/apps/stage-tamagotchi/src/preload/shared.ts:8) | 这是目前最明显的权限边界泄漏 |
| renderer | 只有一个主 renderer bundle/router；`App.vue` 除 spotlight 外都会创建完整运行时，再用 route 条件关闭部分能力。[App.vue](/evaluation-path/treatment/apps/stage-tamagotchi/src/renderer/App.vue:79) | 多窗口扩展会增加重复初始化和条件分支 |
| Eventa | 多个窗口使用 `createContext(ipcMain, window)`，但源码多处明确依赖 `setMaxListeners(0)`，并标注等待 window-namespaced context。[referenced-window.ts](/evaluation-path/treatment/apps/stage-tamagotchi/src/main/windows/shared/referenced-window.ts:40) | 窗口隔离是目标，但不是完整的一等协议 |
| shared package | `stage-shared` 导出 Electron Eventa 地址；`stage-ui`、`stage-pages` 直接导入 Electron renderer adapter 或读取 `window.electron`。[artistry.ts](/evaluation-path/treatment/packages/stage-shared/src/artistry.ts:1)、[artistry-autonomous.ts](/evaluation-path/treatment/packages/stage-ui/src/stores/modules/artistry-autonomous.ts:1) | “共享 UI”与 Electron transport 尚未真正分离 |
| 插件 | manifest/session/kit/资产回收已有完整雏形；entrypoint 通过 dynamic import 加载，`extension.setup` 在 Electron host 内执行。[fs.ts](/evaluation-path/treatment/packages/plugin-sdk/src/plugin-host/runtimes/node/loaders/fs.ts:44) | 适合可信本地插件，不等于不可信插件隔离 |

## 2. 主要架构摩擦

1. `apps/stage-tamagotchi/src/shared/eventa/index.ts` 同时承载窗口、MCP、Godot、插件、widgets、认证、更新器和 UI trace；其中插件类型还在 `stage-ui`、app shared 和 SDK 之间重复定义。[eventa/index.ts](/evaluation-path/treatment/apps/stage-tamagotchi/src/shared/eventa/index.ts:204)

2. renderer 的业务 store 可以自行创建 Electron Eventa contract，例如 autonomous artistry 中直接创建 widgets IPC 地址。这会让“新增一个共享功能”同时改变业务包、Electron transport 和 app contract。

3. 多窗口事件的关联键有时是窗口 context，有时是 widget id、request id 或手工 route 判断。已有 widgets 的 correlation/cleanup 测试，但隔离规则没有统一的 `windowId + role + sessionId` 协议。

4. 插件 API 的逻辑 permission 很有价值，但桌面 host 创建 `ExtensionHost({ runtime: 'electron' })` 时没有传 `permissionResolver`；SDK 在没有 resolver 时默认采用 manifest 请求的权限。[host/index.ts](/evaluation-path/treatment/apps/stage-tamagotchi/src/main/services/airi/plugins/host/index.ts:234)、[core.ts](/evaluation-path/treatment/packages/plugin-sdk/src/plugin-host/core.ts:249)

5. 插件 iframe 有资产 session、cookie 和 owner revoke 机制，这是优点；但 iframe 配置允许外部 `src/srcdoc`，默认 sandbox 包含 `allow-scripts allow-same-origin allow-forms allow-popups`。这需要和未来插件信任模型一起重新定级。

## 3. 质量属性优先级

1. 最小权限与插件安全：最高优先级。共享 preload 和 `sandbox:false` 使 renderer/插件 UI 的权限面偏大。
2. 扩展局部性：新增窗口或插件能力应主要新增 role、contract、adapter 和测试，而不是修改 `App.vue`、巨大 Eventa barrel 和 main 组合根的多个位置。
3. 多窗口正确性：事件必须明确区分目标窗口、广播事件、请求发起者和插件 owner。
4. 可测试性与可观测性：窗口生命周期、插件 session、IPC request 应有统一的 correlation id 和 teardown。
5. 性能：先测量额外窗口带来的 renderer 内存、重复连接和启动时间，再决定是否拆 renderer bundle。

## 4. 方案比较

| 方案 | 优点 | 代价与适用条件 |
|---|---|---|
| A. 保持现状并硬化 | 改动最小；适合可信本地插件、窗口数量有限的阶段 | route 条件、原始 IPC、Eventa listener 和 shared package 泄漏会继续扩大 |
| B. Host kernel + typed capability ports（推荐） | 保留 Electron、Eventa 和现有 renderer bundle；逐步引入显式窗口角色、能力清单和中性 contracts | 需要一段 adapter 迁移期；仍可暂时保留 main 内插件 |
| C. 插件/窗口严格进程隔离 | 第三方插件安全性、崩溃隔离最好 | 实现、调试、跨平台和性能成本高；当前 SDK 的 node-worker/Electron transport 仍未实现，不应直接假设可用 |

推荐 B。C 只在确认支持第三方市场插件、插件代码不可信，或插件稳定性成为产品要求后启动。

目标形态：

```text
Renderer(WindowRole)
  -> typed WindowClient
  -> minimal preload transport
  -> Eventa / IPC
  -> main WindowHost
  -> domain service / plugin supervisor / OS
```

职责建议：

- main：生命周期、持久化、窗口、跨窗口状态、插件 supervisor、OS 能力。
- preload：最小 transport 和 capability allowlist，不暴露业务级原始 `ipcRenderer`。
- neutral contracts：Eventa 定义、schema、版本、错误和 correlation 规则；不依赖 Electron、Vue 或 main 实现。
- renderer：窗口本地 UI 状态和 role profile；不直接创建 Electron transport。
- plugin：先通过 `ExtensionHostPort` 使用 host 能力；可信插件可继续 in-process，不可信插件再迁移 worker/utility process。

## 5. 可逆迁移步骤

1. 先建立窗口矩阵和 ADR：为 main、settings、chat、widgets、overlay、devtools、utility 定义 `WindowRole`、生命周期和能力清单。只增加类型/文档，不改变运行行为。

2. 引入一个 typed `WindowClient` adapter，把现有 Eventa context 包进去。先迁移 settings，再迁移 widgets；保留现有 Eventa 地址和 handler 作为临时 adapter，全部消费者迁移后删除。

3. 将 app-local Eventa barrel 拆成一个中性 contracts 包，按 `window`、`plugin`、`widgets`、`mcp`、`stage` 分 subpath。SDK 所有权明确后，删除 `stage-ui` 和 app shared 中的重复 plugin 类型。

4. 建立 `WindowHost`/window registry：窗口创建时一次性确定 `windowId`、`role`、protocol version、capabilities 和 context teardown。现有窗口工厂先作为 wrapper，settings/widgets 通过新入口运行，其余窗口保持旧入口，便于逐个回退。

5. 将 renderer `App.vue` 的 runtime 改成 role profile：main 才启动完整 stage；chat、settings、widgets、overlay 分别启动最小 runtime。route 继续负责页面导航，但不再负责决定 host 权限。

6. 为插件 host 增加显式 permission resolver、拒绝/撤销记录、超时和 owner-scoped cleanup；同时把 tool registry ownership 从 built-in kit runtime 收拢到 host。只有在不可信插件决策确定后，才设计进程隔离。

7. 对跨窗口状态做分类：插件 registry、工具清单、认证和 server 配置由 main 作为权威源；页面选择、动画和临时 UI 状态保留 renderer-local。跨窗口更新优先使用带 revision 的 snapshot/delta，而不是每个 renderer 自行刷新全部服务。

每一步都应保持现有持久化格式和 Eventa 地址不变；回退方式是恢复对应窗口的旧 factory/profile，而不是回滚整个架构。

## 6. 验证方法

静态边界：

- `stage-ui`、`stage-pages`、`stage-shared` 不应再 import Electron renderer adapter 或读取 `window.electron`。
- contracts 包不得依赖 Electron、Vue、Node runtime。
- renderer 不得 import `src/main` 实现。
- 每个 privileged invoke 必须属于明确 capability，并有 runtime schema 校验。

单元测试：

- 窗口 A 的 invoke/event 不会被窗口 B 消费。
- window close/unload 会移除 handler，并拒绝 pending request。
- 每种 `WindowRole` 只初始化一次 plugin/MCP/server listener。
- 插件 load failure、permission denied、unload、auto-reload、asset revoke 均可测试。
- 继续扩展现有测试：[plugin index tests](/evaluation-path/treatment/apps/stage-tamagotchi/src/main/services/airi/plugins/index.test.ts:336)、[widgets tests](/evaluation-path/treatment/apps/stage-tamagotchi/src/main/windows/widgets/index.test.ts:56)、[chat role tests](/evaluation-path/treatment/apps/stage-tamagotchi/src/renderer/stores/chat-sync-lifecycle.test.ts:18)。

集成验证：

- 同时打开 main、settings、chat、widgets、overlay、devtools，重复发送同名事件并验证目标窗口。
- 关闭并重新打开窗口，确认没有 stale handler、重复连接或 listener warning。
- 插件启停后验证所有 renderer 的工具 snapshot、iframe 请求和资产 session。
- 记录基线后比较额外窗口的启动时间、内存、CPU、IPC 延迟和重复网络连接。

建议的完成标准是：新增一个窗口只需注册 role、capabilities、route、window adapter 和测试；新增一个插件能力只需更新 plugin contract/kit/host adapter，不需要让共享业务 store 直接接触 Electron。

## 7. 尚待决策的问题

- 插件是仅面向可信本地开发者，还是未来允许任意第三方/市场分发？
- 支持的 Electron 版本和平台是否允许逐步启用 sandbox？
- 预计同时存在多少窗口，性能预算是多少？
- Eventa 的 window-namespaced context 何时可用、语义是否足够覆盖当前需求？
- chat、配置、插件 registry 等状态最终由 main 还是某个 renderer 负责权威维护？

[EVAL:evolve-software-architecture-loaded]
