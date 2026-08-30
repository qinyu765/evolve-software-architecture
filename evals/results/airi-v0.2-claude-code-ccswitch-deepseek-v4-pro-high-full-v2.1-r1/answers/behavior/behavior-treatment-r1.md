# AIRI 桌面端架构评审：第三方插件、多窗口、独立后台的边界取舍

## 1. 范围与置信度

本评审针对 `apps/stage-tamagotchi`（Electron 桌面应用）未来三个能力：**第三方插件、更多窗口、独立后台**。仓库分类为 **pnpm monorepo；Electron 主进程 + Vue 渲染进程；主进程用 injeca DI 组织，IPC 用 `@moeru/eventa`；已有一个可独立运行的 WebSocket 后端 `@proj-airi/server-runtime`**。置信度：**高**——以下结论都直接读自源码，而非推测。

一个重要前提：这三个能力**都不是绿地**。仓库里已经画好了大部分接缝——插件 SDK 与宿主、Eventa 契约中枢、injeca DI、可独立运行的 server-runtime。所以本评审的核心不是"要不要建抽象"，而是"**哪些已有接缝应该冻结为稳定边界，哪些只做补强，哪些延后**"。

## 2. 观察到的事实（含证据）

**插件系统已经相当完整，但隔离没做完。**
- 插件 SDK 在 `packages/plugin-sdk`（通用宿主）+ `packages/plugin-sdk-tamagotchi`（widget/gamelet/tool 三类 kit）+ `packages/plugin-protocol`（WS 共享类型与权限模型）。
- Electron 侧的插件宿主在 `apps/stage-tamagotchi/src/main/services/airi/plugins/`：从 `<userData>/extensions/v1` 发现 `extension.airi.json`（`host/registry.ts:18`），支持 enable / load / unload / auto-reload / inspect / dispose，以及带 cookie/session 隔离的静态资源服务（`host/index.ts`）。
- 清单 schema `ExtensionManifestV1` 已用 Valibot 冻结：`apiVersion: 'v1'`、`kind`、`id`、`permissions`、`entrypoints`（`packages/plugin-sdk/src/plugin-host/shared/types.ts:233`）。权限分五个区：apis / resources / capabilities / processors / pipelines，动作集有限（`types.ts:264`）。
- **关键事实（安全）**：Electron 宿主用 `new ExtensionHost({ runtime: 'electron' })` 构造，**没有传 `permissionResolver`**（`services/airi/plugins/host/index.ts:236`）。而宿主在无 resolver 时把**插件自己声明的 `permissions` 当作最终授权**（`plugin-sdk/src/plugin-host/core.ts:250-255`，`grant = manifest.permissions`）。也就是说：**插件自报权限即获得，且通配符 `*` 在 schema 与 `matchKey` 层面都被允许**（`permissions.ts:22`）。权限的"计算模型"（交集/合并）已实现且测试充分，但"授权策略"（谁来批准）没有接入。
- **关键事实（隔离）**：插件运行时只有 `in-memory` 传输可用；`node-worker`、`web-worker`、`websocket`、`electron` 四种传输全部 `throw 'not implemented yet'`（`plugin-sdk/src/plugin-host/runtimes/node/index.ts:24`、`web/index.ts:23`）。加载器直接 `await import(entrypoint)`（`runtimes/node/loaders/fs.ts:74`）。**结论：第三方插件代码目前运行在 Electron 主进程内，享有完整 Node + Electron 权限。** 这是三个能力里最危险、最该先处理的一点。

**多窗口是"手写接线"，不是"注册表"。**
- 组合根 `src/main/index.ts` 手工声明约 15 个窗口（main/chat/settings/spotlight/caption/notice/about/onboarding/widgets/devtools/beat-sync/desktop-overlay…），每个窗口在 DI 里显式列出依赖（如 settings 窗口 13 个依赖，`index.ts:216`）。
- 每个窗口是一个 `windows/*/index.ts` 工厂 + `windows/*/rpc/index.electron.ts` 处理器 + 在 `shared/eventa/index.ts` 里的契约 + `index.ts` 里的 wiring 块。**加一个新窗口要同时改 4~5 处。**
- 通用件已经存在但没收敛：`createReusableWindow`（`libs/electron/window-manager/reusable.ts`）和 devtools 的按 key 复用窗口工厂（`windows/devtools/index.ts:23`）是唯二的泛化。
- Eventa 契约中枢 `shared/eventa/index.ts` 是一个扁平大文件；窗口级隔离靠每处 `if (window.webContents.id === sender.id)` 手写守卫（`services/electron/window.ts:45`）。代码里已有两处 TODO 承认需要"window-namespaced contexts"来去掉 `ipcMain.setMaxListeners(100)`/`setMaxListeners(0)` 这两个 hack（`index.ts:55`、`windows/main/index.ts:211`）。

**"独立后台"已经是一个可运行的东西，只是被嵌在 Electron 里。**
- `@proj-airi/server-runtime` 有独立 CLI（`packages/server-runtime/src/bin/run.ts`，端口 6121）、完整的 WS 协议（peer/module 注册、consumer 路由、心跳、token 鉴权、路由策略中间件，`src/index.ts`）、生命周期控制器 `createServer({ start/stop/restart/updateConfig })`（`src/server/index.ts`）。
- Electron 通过 `channel-server` 内嵌它（`services/airi/channel-server/index.ts`），主要用于局域网 QR 配对，且随 Electron 生命周期启停。
- 已有 `server-sdk`（客户端）、`server-shared`、`core-agent`（依赖 server-sdk）、以及 `services/` 下一批独立服务（如 `services/computer-use-mcp`）使用同一套 server 包。HTTP 侧 `setupBuiltInServer({ servers: [] })` 目前是个空生命周期骨架（`services/airi/http-server/index.ts`）。
- **推断**："独立后台"最合理的落点是——把这套 server-runtime 从"内嵌的配对通道"提升为"域运行时的稳定后端边界"，而不是另起炉灶。

## 3. 当前摩擦

- **插件**：契约层和宿主层已经分离得很好，但**授权策略缺失 + 进程隔离缺失**，这两条直接把"开放第三方插件"变成高风险动作。
- **窗口**：加窗口是**变更放大**（4~5 处手工接线）；扁平 Eventa 中枢已经靠 `setMaxListeners` 撑着了，说明这个做法在接近它的容量上限。
- **后台**：server-runtime 与 Electron 生命周期耦合。UI 一关，服务就停；无法无头运行、无法让多个客户端在 UI 关闭后继续工作。但它已经具备独立运行的全部机制，缺的只是"把边界固定下来 + 一个部署形态决策"。

## 4. 质量属性优先级（按排序）

1. **安全/隔离**（最高）——第三方代码能拿到 Electron 主进程权限，是不可逆的破坏面。必须优先。
2. **可演化性/变更局部性**——"更多窗口""更多插件"要求新增能力只动一个局部，而不是每次动 5 处。
3. **可运维性/生命周期**——后台能否独立于 UI 启停、崩溃是否隔离、可观测性。
4. **可测试性**——仓库现有测试缝（injeca、Eventa、Vitest、契约测试）很好，任何方案不得破坏它。
5. **性能/延迟**——进程内最快，跨进程有 IPC 开销。对插件而言，隔离优先于微小的延迟损失；对窗口/后台，本方案不引入额外热路径成本。

这些属性相互竞争：进程隔离牺牲一点性能换安全；窗口命名空间要改一批文件换长期局部性。下面的取舍都围绕"先保安全与局部性，不追求完美终态"。

## 5. 方案对比

### 方案 A：维持现状 + 局部加固
保持插件进程内运行、窗口手工接线、后台内嵌。只做：给 Electron 宿主接一个**默认拒绝**的 `permissionResolver`，补契约测试。

- **边界与所有权**：不新增边界，沿用现有。
- **代价/风险**：最低、最快。回滚是删掉 resolver。
- **缺点**：没有解决第三方插件的**进程隔离**（权限模型只能限制 kit 调用，挡不住插件在 Electron 主进程里 `import('child_process')`）；多窗口变更放大依旧；后台生命周期依旧绑定 UI。
- **何时仍可辩护**：如果"第三方插件"只是内部可信插件、且未来 1~2 个窗口。**作为目标是站不住的，只能作为方案 B 的第 0~1 步。**

### 方案 B：完成已画好的接缝（推荐）
冻结三条稳定边界，做三处**定向补强**，不做新框架：

- **B1 插件边界**：冻结 `ExtensionManifestV1` + 权限模型为 v1 稳定契约；给宿主接**默认拒绝 + 显式授权 + 持久化授权**的 `permissionResolver`；实现 `node-worker`（先）与 `websocket`（后）传输，让插件入口跑出主进程。kit API 面保持现有 widget/gamelet/tool 三件套，不扩张。
- **B2 窗口/事件边界**：把 Eventa 的 window-namespaced context 从 TODO 落地（去掉每个处理器里的 `webContents.id` 手写守卫），并加一个**极薄的窗口注册表**（复用 `createReusableWindow` + devtools 的按 key 复用模式，把 bounds 持久化复用进来）。**不建**声明式窗口框架。
- **B3 后台边界**：冻结 `Server` 生命周期契约（`start/stop/restart/updateConfig`）+ Eventa 协议为后端边界；**暂时继续内嵌运行**（库模式），新服务一律走 `Server` + `server-sdk`。这样"独立后台"未来是一个**部署选择**（换成 `bin/run.ts` 子进程），而不是重写。

- **代价**：`node-worker` 传输是实打实的工程；权限授权 UX 需要产品输入；窗口命名空间化要渐进改一批文件。
- **风险**：中。每一步都可回滚（见第 7 节）。
- **会被证伪的证据**：如果需求明确要求"UI 关闭后 agent 必须继续跑"或"插件必须 OS 级沙箱（不能用 worker_threads）"，则 B3/B1 的"延后/先 worker"就不成立，需提前升级到方案 C 的对应部分。

### 方案 C：一次性平台化（激进）
现在就抽出独立守护进程（server-runtime bin 做后台、Electron 退化为纯 UI 客户端），同时建声明式窗口注册表、插件进程监督器、插件安装/分发通道。

- **代价/风险**：最高。组合根重写、多进程生命周期与崩溃恢复、分发通道都叠加在一个没有验证过的需求上；回滚约等于再改回去。
- **优点**：终态最干净。
- **会被证伪的证据**：目前没有任何证据表明后台需要**在 UI 关闭后存活**、或需要**第二个独立客户端**，因此这是**投机性的架构**。

## 6. 建议

**采用方案 B。** 它把三件未来能力各自映射到一条"已画好、但没画完"的接缝上，用最小的新抽象换取最大的长期收益，且不重写现有组合根。

- 稳定下来的是：**插件清单 v1 + 权限模型**、**Eventa 契约与窗口命名空间**、**`Server` 生命周期与 WS 协议**。这三条一旦冻结，未来的插件/窗口/后台都在既有骨架上生长。
- 明确**延后**的是：独立守护进程、声明式窗口框架、插件进程监督器、插件分发/市场、`websocket` 远程插件传输。只有当出现"UI 关闭后台必须存活""需要第二客户端""插件必须 OS 级沙箱"这类**可验证的需求信号**时，再升级对应部分。

## 7. 迁移与验证（渐进、可回滚）

**Phase 0 —— 冻结边界，零行为变化**
- 写 ADR，记录上面三条稳定边界及延后项。
- 补契约测试：钉住 `extensionManifestV1Schema`、`PermissionService` 的交集语义、`Server` 生命周期、Eventa 契约名。
- 出口标准：`pnpm -F @proj-airi/plugin-sdk test`、`server-runtime` 相关测试全绿；ADR 合入。
- 回滚：无（未改行为）。

**Phase 1 —— 插件隔离垂直切片（先做，风险最高）**
- 实现 `plugin-sdk` 的 `node-worker` 传输；让宿主能在 worker 里启动**一个**内置插件，用环境变量 `AIRI_PLUGIN_ISOLATION=1` 门控。
- 给 Electron 宿主接默认拒绝的 `permissionResolver`（同样门控），授权写进既有 `extensionConfig` 持久化。
- 出口标准：开启门控后既有插件测试套件通过；新增回归测试证明"声明 `apis:*` 的插件仍无法调用未被授权的 kit"。
- 回滚：关掉门控即回到进程内路径（保留旧路径直到隔离稳定）。

**Phase 2 —— 窗口命名空间 + 薄注册表**
- 落地 window-namespaced Eventa context，先迁一个窗口（devtools 或 notice）端到端验证。
- 加一个按 key 的窗口注册表，复用 bounds 持久化。
- 出口标准：能删掉 `setMaxListeners(100/0)` hack；新增一个窗口只需改"自身模块 + 注册表一项"。
- 回滚：迁移期间保留旧的 sender 守卫作为兜底。

**Phase 3 —— 后台边界（延后，按需触发）**
- 出现明确需求时，用现有 `bin/run.ts` + `Server` 契约把 server-runtime 提升为受管子进程；协议不变，`server-sdk` 客户端对"内嵌/守护"两种模式无感。
- 出口标准：同一 `server-sdk` 客户端在内嵌与守护两种模式下通过同一套集成测试。
- 回滚：回到内嵌模式（协议未变）。

**不改变的后果**（如果不按 B 走）：
- 第三方插件继续在主进程运行且自授权 → 一个 buggy/恶意插件就能读 cookie、起子进程、控制窗口，**实际上封死了任何第三方插件分发的可能性**。
- 多窗口继续叠加 4~5 处手工接线，`setMaxListeners` 这类 hack 会越来越多。
- 后台与 UI 生命周期继续绑定，无头/远程场景做不了，且未来要拆时变成一次重写。

## 8. 待决问题（答案会改变建议）

1. **插件授权 UX**：第三方的授权提示/授权存储是产品形态（安装时一次性授权？运行时逐项授权？），需要产品与设计输入。
2. **隔离强度**：`node-worker`（worker_threads）是否足够，还是必须 Electron `utilityProcess` 或 OS 级沙箱？`PluginTransport` 已经同时预留了 `node-worker` 和 `electron`，这是一个真正要拍板的实现选择。
3. **稳定 kit 面**：哪些 kit 对第三方是稳定公开的（widget/gamelet/tool），哪些是内部专用（static-assets/cookie 会话），需要明确。
4. **"独立后台"的动机**：是"领域逻辑与 UI 解耦"还是"UI 关闭后继续服务"？这决定 Phase 3 是现在做还是继续延后。
5. **`/ws` 路径字面量**：`channel-server` 里已有 TODO 要消除三处 `/ws` 重复（`channel-server/index.ts:103`），应纳入 B3 冻结时一并收敛。

[EVAL:evolve-software-architecture-loaded]
