## 结论

建议采用“混合渐进方案”：

- Electron 主进程继续作为窗口、权限、生命周期和系统能力的监督者。
- 现有可信插件暂时保留进程内运行路径。
- 稳定插件、窗口、能力、后台任务的领域契约和身份模型。
- 对来源未知、耗时高或需要独立重启的插件，逐步迁移到子进程。
- 只有当后台必须在 UI 退出后继续运行、需要多客户端连接或跨设备连续运行时，再演进为独立 daemon。

现在不建议进行全量窗口框架、通用传输层或完整插件 daemon 重构。

## 当前结构与关键事实

AIRI 当前已经是“Electron 主进程装配多个窗口和后台模块”的结构。主进程通过 injeca 注册窗口、Server Channel、MCP、Godot、Widgets 和 Plugin Host 等模块。[主进程装配图](/evaluation-path/control/apps/stage-tamagotchi/src/main/index.ts:171)

几个事实决定了后续边界：

- Eventa 的窗口级隔离尚未成为统一机制。多个位置都有“window-namespaced contexts”待完成的 TODO，并通过 `setMaxListeners` 缓解监听器压力。[窗口引用管理器](/evaluation-path/control/apps/stage-tamagotchi/src/main/windows/shared/referenced-window.ts:40)
- 除 Spotlight 外，各个 renderer route 都会创建完整的 Stage runtime；增加窗口会增加 Store、订阅、IPC 和初始化成本。[renderer runtime 创建](/evaluation-path/control/apps/stage-tamagotchi/src/renderer/App.vue:79)[完整 runtime 条件](/evaluation-path/control/apps/stage-tamagotchi/src/renderer/App.vue:256)
- 当前插件宿主明确使用 `runtime: 'electron'`，并在主进程中动态加载插件 entrypoint。[插件宿主创建](/evaluation-path/control/apps/stage-tamagotchi/src/main/services/airi/plugins/host/index.ts:236)[插件加载](/evaluation-path/control/apps/stage-tamagotchi/src/main/services/airi/plugins/host/index.ts:357)
- 插件权限和 Host API 是能力边界，但不是操作系统级进程隔离。当前插件模块仍在宿主进程中执行。
- 插件 UI 已经有较清晰的 iframe 边界，并使用 sandbox 和基于 session 的静态资源服务。[插件 iframe](/evaluation-path/control/apps/stage-tamagotchi/src/renderer/widgets/extension-ui/components/extension-ui-host.vue:105)
- Godot、MCP 和 Server Channel 已有显式启动、停止或 app quit 生命周期，但仍由 Electron 主进程拥有；例如 Godot 会在 `onAppBeforeQuit` 中停止。[Godot 生命周期](/evaluation-path/control/apps/stage-tamagotchi/src/main/services/airi/godot-stage/index.ts:916)
- Plugin SDK 的多传输设计目前仍标记为 Planned；Node runtime 当前实际只实现 in-memory，WebSocket、worker 和 Electron transport 会抛出未实现错误。[Node transport 实现](/evaluation-path/control/packages/plugin-sdk/src/plugin-host/runtimes/node/index.ts:24)[设计状态](/evaluation-path/control/packages/plugin-sdk/docs/design/multi-transport.md:150)

## 应稳定的边界

| 边界 | 建议稳定的内容 |
|---|---|
| 主进程与窗口 | 主进程拥有 BrowserWindow、系统权限、单实例、托盘和退出流程；renderer 只能通过协议消费能力 |
| Eventa 合约 | 按 window、plugin、capability、widget、background 等领域组织共享事件；插件不得直接获得 `ipcMain`、`ipcRenderer` 或 `BrowserWindow` |
| 身份与作用域 | 固定使用 `extensionId`、`sessionId`、`moduleId`、`windowId`、`ownerId`、`requestId`、`instanceId` 等相关性字段 |
| 插件生命周期 | manifest → session → module/binding → capability → unload/dispose；加载、失败、重启、撤销必须可观察 |
| 权限与能力 | 权限由 Host 解释和授予，能力通过显式 API 暴露，默认拒绝；不要把“能调用 Host API”当成“拥有进程隔离” |
| 后台任务 | 统一表达 start、stop、restart、status、health、dispose、超时和取消；具体实现仍可分别使用 ServerManager、MCP 或 Godot 模式 |
| 控制面与数据面 | 生命周期、配置、能力协商属于控制面；音视频、流式数据、遥测等高频内容属于数据面。Plugin SDK 设计也明确采用这一划分。[控制/数据面设计](/evaluation-path/control/packages/plugin-sdk/docs/design/architecture.md:90) |

这里应稳定的是“协议和身份”，不是马上创建一个万能 `WindowManager` 或 `ServiceManager` 类。当前窗口类型差异很大：主窗口、Settings、Chat、Widget、Overlay 和动态引用窗口各有不同生命周期。

## 应延后的抽象

1. 通用窗口框架

   先稳定 `WindowId`、窗口种类、owner、生命周期和路由契约。只有当多个窗口确实重复相同的持久化、恢复、导航和关闭策略时，再抽取统一 registry。

2. 通用插件传输层

   不应先实现涵盖 Electron、WebSocket、Worker、Node Worker 的大一统抽象。当前 SDK 设计仍是 Planned，实际只有 in-memory 可用。先定义 transport-neutral 的 HostPort，再只实现一个真实需求对应的 adapter。

3. 完整能力编排状态机

   SDK 文档已经提出 `waiting-deps`、`ready`、`degraded` 等模型，但当前仍处于设计阶段。[能力编排设计](/evaluation-path/control/packages/plugin-sdk/docs/design/capability-orchestration.md:24)

   当前先补充明确的 owner、instance 和 readiness 事件即可。等出现多个独立 Host 或真实的晚到能力竞争，再引入完整状态机。

4. 独立 daemon 和远程插件平台

   SDK 设计已经列出嵌入 Electron、外部 Node、远程 server 三种模式，但这更适合作为演进方向，而不是当前默认架构。[插件 Host 部署模式](/evaluation-path/control/packages/plugin-sdk/docs/design/architecture.md:167)

5. Marketplace、签名和复杂安装系统

   当前 registry 主要从用户目录读取 manifest；现有 sample plugin 仍是手动放入 registry 目录。除非产品已经决定支持社区分发，否则先稳定 manifest、API 版本、runtime、权限和 entrypoint，不要提前设计完整市场协议。

## 可行方案比较

| 方案 | 质量属性 | 成本与风险 | 回滚 |
|---|---|---|---|
| A. 维持现状：插件进程内运行，窗口继续各自注册 Eventa | 延迟低、调试简单；进程隔离、安全性、主进程可用性较弱；多窗口会继续复制完整 runtime | 近期成本最低；第三方插件可能拖垮或影响主进程，监听器和跨窗口耦合继续增长 | 无需迁移，风险是继续累积结构性债务 |
| B. 混合方案：主进程监督 + 可信插件内嵌 + 不可信插件子进程 | 在兼容性、隔离、可重启性之间平衡；增加序列化和连接延迟，但窗口模型不必重写 | 中等成本：需要 handshake、版本协商、认证、session 恢复、子进程监控和打包 | 通过插件级 feature flag 保留内嵌路径；外部 Host 失败时只对可信插件允许回退，不能让未知插件静默回到主进程 |
| C. 完整 daemon：Electron 只是 viewer，插件和后台全部由独立 Node 服务承载 | 进程独立性、多客户端、UI 退出后继续运行能力最好 | 成本最高：安装、启动、升级、认证、端口、离线、跨版本和数据迁移都变复杂 | 保留 embedded 模式作为 fallback；daemon 只作为可选运行模式 |

推荐 B。目标形态可以概括为：

```text
renderer windows / plugin iframes
              │ shared Eventa contracts
Electron main supervisor
  window policy / permissions / lifecycle
  plugin host adapter ── embedded | child process
  background adapter   ── MCP / Godot / other workers
              │ control/data transport
external plugin host or background process
```

主进程仍是窗口和权限的权威来源，但不再必须是所有第三方代码和长期后台任务的执行场所。

## 如果暂时不改变，后果是什么

维持现状对“可信的本地开发插件、窗口数量有限、后台必须随桌面应用退出”的产品阶段是合理的，但需要明确接受这些后果：

- 未知来源插件仍然与 Electron 主进程共享故障边界；权限 API 不能替代 OS 级隔离。
- 增加窗口会继续创建完整 Stage runtime，而不是轻量窗口壳。
- `setMaxListeners` 只能缓解监听器告警，不能提供真正的窗口命名空间或事件归属。
- MCP、Godot、插件资源服务器等后台能力仍由当前应用生命周期拥有，不能在 UI 退出后独立存活。
- 已有 iframe UI 隔离可以继续复用，但它只隔离插件 UI，不隔离插件执行代码。

## 可验证的渐进迁移路线

### 1. 先定义不变量，不移动进程

建立现有契约基线：

- 同时打开多个窗口时，事件必须按 `windowId/ownerId` 定向。
- 多个插件 session 之间不能互相接收 invoke、tool、capability 或 widget 事件。
- 窗口关闭、插件 unload、后台 restart 后，监听器、binding、asset session 和 pending request 都必须清理。
- 记录 startup、窗口初始化、插件加载失败、后台重启和退出时残留进程等指标。

验收重点是“无串话、可重复关闭/重开、资源可回收”，而不是先追求抽象类数量。

### 2. 在现有进程内引入 HostPort

先不改变运行位置，把现有 `ExtensionHostService` 包装为一个稳定边界：

- `hello / protocolVersion`
- plugin/session/module 状态
- capability grant/revoke
- kit binding
- tool invoke
- asset session
- dispose/restart
- correlation id 和错误模型

让当前进程内 Host 先通过这个边界运行。这样可以先验证协议和生命周期，而不同时引入子进程故障。

### 3. 只选择一个外部 transport 做试点

针对一个现有 sample 或测试插件进行子进程试点。候选是：

- stdio：本机部署简单，适合单机插件；
- 本地认证 WebSocket：更容易复用未来 daemon 和重连模型；
- worker：适合同一运行时内的隔离，但不等于独立服务。

选择标准应是重连、热加载、调试、打包和未来复用，而不是先实现所有 transport。当前 SDK 的 transport 还未完成，因此这一步必须以协议 round-trip、版本不匹配和断线恢复测试为门槛。

验收条件：

- 外部插件崩溃不会导致 renderer 或 Electron 主进程退出。
- 只有对应 session 进入 degraded，其他插件不受影响。
- 权限拒绝、版本不兼容和请求超时都有确定错误。
- unload 后 binding、tool、capability、asset session 全部撤销。
- 子进程退出后没有 orphan process。

### 4. 再迁移独立后台能力

优先选择已有明确生命周期的能力，例如 Godot sidecar 或 MCP session。保留主进程 supervisor，统一暴露状态和重启接口；不要一次性把 Server Channel、所有 AI runtime 和窗口逻辑全部搬走。

验收条件：

- 后台可单独 restart。
- renderer 可断线重连并重新获取状态。
- 应用退出时能够优雅停止或明确转交 daemon。
- 配置应用失败可以恢复旧配置；现有 Server Channel 已有类似回滚处理。[Server Channel 生命周期](/evaluation-path/control/apps/stage-tamagotchi/src/main/services/airi/channel-server/index.ts:357)

### 5. 最后再收敛窗口抽象

当窗口数量和重复逻辑达到实际压力后，再抽取窗口 registry。registry 只负责：

- identity、owner、kind
- route/preload/security profile
- visibility、focus、bounds
- lifecycle 和 cleanup

主窗口、Settings、Widget、Overlay 仍可保留各自的策略函数，不要强行统一成同一种窗口。

### 6. 只有出现明确触发条件才升级 daemon

以下任一条件成立时，C 方案才值得启动：

- 后台必须在 Electron UI 退出后继续运行；
- 多个 Stage 或客户端需要共享同一 Host；
- 需要跨设备连续任务；
- 第三方插件必须获得独立崩溃和资源隔离；
- 需要远程插件或非 JavaScript 插件。

迁移时始终保留 embedded fallback、manifest 存储兼容和协议版本协商，确保 daemon 只是运行模式变化，不是一次性替换整个插件模型。

本轮仅做了只读静态检查，没有修改文件、创建 commit 或改变外部状态。
