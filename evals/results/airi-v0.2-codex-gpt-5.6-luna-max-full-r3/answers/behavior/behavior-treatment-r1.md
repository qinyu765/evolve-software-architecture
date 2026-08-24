结论：推荐“混合演进”方案。先稳定“主进程拥有特权、插件通过受控能力访问、窗口和后台服务由宿主拥有”的边界；可信插件暂时保留进程内运行，第三方插件或长时间后台任务再迁移到独立 runner。不要现在就做全量微内核、通用窗口管理器或完整多传输平台。

本次审查只读，未修改文件、创建提交或运行可能产生构建缓存的命令。

## 1. 范围与置信度

审查范围是 `apps/stage-tamagotchi` 的 Electron main/preload/renderer、插件 SDK/协议，以及现有本地服务、MCP 和 Godot 后台能力。

当前结构判断置信度高；未来插件是否“不受信任”、是否需要崩溃隔离、后台是否要独立于 UI 持续运行，仍是未知决策。

`evolve-software-architecture` 提供的适配器中没有 Electron 专用适配器，以下采用其核心的 evidence-first 流程，并明确区分事实、推断和未知。

## 2. 观察到的事实

| 事实 | 可检查证据 | 类型 |
|---|---|---|
| Electron 已明确分成 main、preload、renderer 三类入口；main 组合大量窗口和服务 | [`electron.vite.config.ts`](</evaluation-path/treatment/apps/stage-tamagotchi/electron.vite.config.ts>)、[`main/index.ts`](</evaluation-path/treatment/apps/stage-tamagotchi/src/main/index.ts>) | 事实 |
| 插件入口在 Electron main 进程内通过动态 `import` 加载 | [`plugin-host/core.ts`](</evaluation-path/treatment/packages/plugin-sdk/src/plugin-host/core.ts>)、[`fs.ts`](</evaluation-path/treatment/packages/plugin-sdk/src/plugin-host/runtimes/node/loaders/fs.ts>) | 事实 |
| 当前权限主要限制 SDK 能力；main 没有传入独立的 `permissionResolver`，SDK 默认可使用 manifest 声明的权限 | [`main/index.ts`](</evaluation-path/treatment/apps/stage-tamagotchi/src/main/index.ts>)、[`shared/types.ts`](</evaluation-path/treatment/packages/plugin-sdk/src/plugin-host/shared/types.ts>) | 事实 |
| 因为插件代码与 main 共享 Node 进程，当前权限模型不是 OS/进程级安全隔离 | 上述动态加载和 runtime 实现 | 推断，高置信 |
| 窗口不是同一种资源：有主窗口、可复用窗口、引用式窗口、widgets/iframe、overlay | [`windows/shared`](</evaluation-path/treatment/apps/stage-tamagotchi/src/main/windows/shared>)、[`widgets/index.ts`](</evaluation-path/treatment/apps/stage-tamagotchi/src/main/windows/widgets/index.ts>) | 事实 |
| Eventa 当前仍有 window namespace 不足的显式 TODO，并通过调整 listener 上限缓解 | [`main/index.ts`](</evaluation-path/treatment/apps/stage-tamagotchi/src/main/index.ts>)、[`referenced-window.ts`](</evaluation-path/treatment/apps/stage-tamagotchi/src/main/windows/shared/referenced-window.ts>) | 事实 |
| Server channel、MCP、Godot 已分别拥有启动、停止、状态或清理逻辑，但生命周期入口同时存在 `injeca`、bootkit hooks 和 Electron quit hooks | [`channel-server/index.ts`](</evaluation-path/treatment/apps/stage-tamagotchi/src/main/services/airi/channel-server/index.ts>)、[`mcp-servers/index.ts`](</evaluation-path/treatment/apps/stage-tamagotchi/src/main/services/airi/mcp-servers/index.ts>)、[`godot-stage/index.ts`](</evaluation-path/treatment/apps/stage-tamagotchi/src/main/services/airi/godot-stage/index.ts>) | 事实 |
| 插件协议和文档已经为 embedded、external、remote、多 transport 预留概念，但若干 runtime 仍是 TODO 或直接抛出未实现 | [`plugin-protocol/events.ts`](</evaluation-path/treatment/packages/plugin-protocol/src/types/events.ts>)、[`multi-transport.md`](</evaluation-path/treatment/packages/plugin-sdk/docs/design/multi-transport.md>)、[`plugin-host/runtimes/node`](</evaluation-path/treatment/packages/plugin-sdk/src/plugin-host/runtimes/node>) | 事实 |
| 插件 manifest、host、kits、identity 在 2026-04 至 2026-06 的多个提交中大幅重构 | `509c00d9a`、`0f975a4f7`、`668440a73` | 事实 |

## 3. 当前结构性摩擦

1. **插件信任边界缺失。**  
   现在的插件宿主适合内置或开发插件，但不适合默认承载任意第三方代码。插件异常、无限循环、内存泄漏或直接使用 Node 能力，都可能扩大为 main 进程故障。

2. **main 组合根承担了过多变化传播。**  
   新增窗口或后台服务通常需要修改组合根、窗口间依赖、Eventa handlers 和共享 renderer runtime。`App.vue` 会为多个窗口初始化大量完整能力，这会放大窗口数量带来的耦合。

3. **“窗口”语义没有统一到足以抽象成一个通用管理器。**  
   主窗口、设置窗口、widgets iframe 和 desktop overlay 的生命周期、安全模型、持久化和通信方式不同。强行统一会把差异隐藏在复杂参数中。

4. **后台能力已有模式，但还没有统一的稳定协议。**  
   Server channel 的配置回滚、MCP 的子进程管理、Godot 的 sidecar 生命周期都值得复用其原则，但不代表现在就应抽象成通用 supervisor。

5. **协议方向超前于实现。**  
   `plugin-protocol` 可以作为未来稳定的语义合同，但目前不能把 remote/WebSocket/worker 支持当作已存在的架构能力。

6. **第三方分发模型尚未明确。**  
   当前示例插件仍是复制到用户目录后由 DevTools 刷新、启用、加载；没有足够证据表明签名、市场、自动更新和不受信任安装已经是当前产品约束。

## 4. 质量属性优先级

| 优先级 | 属性 | 建议目标 |
|---|---|---|
| 1 | 安全与故障隔离 | 不受信任插件不能直接获得 Electron、密钥或任意 main 资源；插件崩溃不应拖垮主界面 |
| 2 | 变更局部性 | 新增一个窗口、插件贡献或后台能力时，不应持续扩大 `main/index.ts` 和全局 renderer 的依赖列表 |
| 3 | 可运维与可恢复 | 插件/后台能力具备状态、健康、停止、重启、超时、日志和清理结果 |
| 4 | 合同兼容性与可测试性 | identity、session、module、capability、permission 和错误状态可序列化、可版本化、可独立测试 |
| 5 | 启动与资源成本 | 非必需窗口和后台能力保持惰性；独立进程成本必须用实测预算约束 |
| 6 | 实施成本 | 不为了尚未确认的 remote/marketplace 场景提前支付平台化成本 |

## 5. 可行方案

### 方案 A：维持当前 embedded main 模式

插件继续在 main 进程内运行；窗口维持各自 feature module；Server channel、MCP、Godot 继续分别管理。

- 优点：成本最低、延迟低、现有测试和开发体验最直接。
- 缺点：没有真正的进程隔离；main 组合根和 renderer runtime 会继续膨胀。
- 适用前提：插件只来自 AIRI 自身或可信开发者，且插件失败不要求保证桌面应用持续可用。
- 成本：低。
- 风险：对任意第三方插件而言高。
- 回滚：简单，逐项撤销新增能力即可。
- 被什么证据否定：出现用户安装的不受信任插件、插件需要独立重启、插件执行长任务或已发生 main 被插件拖垮。

### 方案 B：现在全面外置插件宿主

main 只保留控制面、权限和 Electron 能力代理；每个插件或一组插件在独立 runner 进程中加载，通过本地受认证的协议通信。

- 优点：隔离、重启、故障恢复和长时间后台能力最好。
- 缺点：需要同时解决 runner 打包、发现、升级、认证、协议版本、跨平台进程管理、调试和 IPC 性能。
- 风险：当前 transport 实现尚未完成，容易在真实需求出现前过度平台化。
- 成本：高。
- 回滚：如果一开始就取消 embedded 路径，回滚会涉及协议、打包和状态迁移；必须保留双路径才可安全回滚。
- 被什么证据否定：所有插件始终是内置可信代码，且不存在崩溃隔离和独立后台需求。

### 方案 C：混合运行时、渐进外置

保留当前 in-process runtime，但按插件信任等级和运行时长选择执行模式：

- 可信、内置、开发插件：继续 embedded。
- 用户安装的第三方插件、长时间后台任务、需要独立重启的插件：使用 isolated runner。
- 两种模式共享同一套插件身份、session、module、capability、permission、status 合同。
- 插件 UI 只能通过宿主拥有的 widget/panel/iframe 贡献进入窗口体系，不能直接创建任意 privileged `BrowserWindow`。
- 后台能力先沿用现有 Server/MCP/Godot 的生命周期原则，不立即建立万能后台框架。

这是推荐方案。

- 成本：中等，需要暂时维护两种运行模式和对应测试。
- 风险：两条路径可能产生语义漂移。
- 回滚：按插件逐个切回 embedded；新窗口保留旧 feature module；不先做不可逆配置迁移。
- 被什么证据否定：如果安全要求所有插件都必须硬隔离，应直接向方案 B 收敛；如果长期只有可信插件，则可停留在方案 A。

## 6. 推荐的稳定边界与延后抽象

建议现在稳定：

- **Electron 特权边界**：main 拥有 `BrowserWindow`、preload、导航策略、密钥、用户目录、托盘、快捷键和子进程生命周期。
- **插件控制面合同**：extension identity、session、module、kit、capability、permission、status、error 和 compatibility。语义应稳定，具体 transport 不必现在全部实现。
- **窗口 feature 边界**：每个窗口模块拥有自己的创建、显示、关闭、路由和 Eventa handlers；其他模块通过窗口句柄或命令访问，不直接依赖裸 `BrowserWindow`。
- **插件 UI 边界**：继续使用 owner/session 关联的 asset、widget、iframe 机制，并保证卸载时撤销资源和待处理请求。
- **后台生命周期边界**：至少统一表达 `start / stop / status / health / dispose`，并附带 owner、session 或 correlation ID。
- **组合根职责**：`main/index.ts` 只负责 wiring 和启动顺序；策略放在插件 host、窗口 feature 和后台服务内部。

建议延后：

- 一个覆盖所有窗口类型的 `WindowManager` 或全局 window registry。
- 完整的“插件微内核”或全局 event bus。
- 在没有真实 external vertical slice 前完成所有 WebSocket、worker、remote transport。
- 通用后台 supervisor、工作流引擎或任务调度器。
- marketplace、签名、自动更新和复杂权限 UX，除非分发和威胁模型已经确定。
- 把所有插件都强制迁移到独立进程。
- 一个包含窗口、插件、后台、权限、通信的巨型 `PluginPlatform` 抽象。

目标边界可以概括为：

```text
插件代码
  -> runtime adapter（embedded / isolated）
  -> plugin host（身份、权限、session、能力、状态）
  -> 宿主适配器（widget、窗口、工具、后台能力）

Electron main 继续拥有 BrowserWindow、preload、密钥和进程生命周期
```

## 7. 可验证的渐进迁移路线

### 阶段 0：建立基线

未来实施前先记录：

- 当前插件加载、卸载、失败恢复耗时。
- 主窗口和辅助窗口打开耗时。
- main CPU、内存、事件循环阻塞情况。
- Server channel、MCP、Godot 的停止和重启行为。
- 当前插件和窗口测试覆盖范围。

同时记录一份 ADR：主进程是特权宿主，插件 UI 是宿主拥有的贡献，运行时可以按信任等级切换。

退出条件：现有行为和测试基线明确；没有引入运行时行为变化。

### 阶段 1：先收紧控制面

- 让 plugin host 的 lifecycle snapshot 成为唯一可观察状态。
- 明确 `extensionId`、`sessionId`、`moduleId`、owner 和 correlation 的关系。
- 为启动失败、卸载、资源撤销、工具撤销、重复 manifest ID 增加合同测试。
- 明确 trusted 与 third-party 两种策略，但暂不改变默认执行方式。

验证结果应包括：一个插件失败不会留下 stale module/tool/asset，也不会阻止其他插件继续工作。

### 阶段 2：先做一个窗口垂直切片

选择一个新的插件 panel/widget 和一个新的独立辅助窗口：

- 使用现有 widgets、iframe asset session 和窗口 feature module。
- 插件只能声明式请求 UI 贡献，不能持有 `BrowserWindow`。
- 测试多窗口同时打开、关闭、reload、Eventa source 隔离、待处理 iframe 请求清理和导航保护。

验收重点不是“抽象数量减少”，而是新增功能的改动是否局限在对应 feature、宿主注册和合同文件中。

### 阶段 3：只迁移一个第三方/长任务插件

- 第一个 isolated plugin 建议“一插件一 runner”，先换取清晰的故障归属和回滚路径。
- runner 负责加载插件代码；main 负责策略、窗口、权限和 Electron 能力代理。
- transport 选型应单独做小型决策，不要把尚未实现的 remote transport 直接视为现成基础设施。
- 通过 feature flag 或每插件执行模式保留 embedded 回退。

验收条件：

- runner 被杀或异常退出时，main 和其他插件仍可用。
- 插件状态变为 stopped/degraded，资源和 session 被清理。
- 重启后生成新的 session identity。
- 协议版本不兼容时明确 rejected/downgraded，而不是静默失败。
- 启动、内存和 IPC 延迟在阶段 0 的预算内。

### 阶段 4：验证一个独立后台能力

选择 MCP 或 Godot 这类已有外部生命周期模式中的一个，补齐统一的：

- owner；
- health/status；
- stop/restart；
- timeout；
- crash recovery；
- app quit cleanup；
- DevTools 可观察状态。

只有第二个、第三个后台能力出现重复策略后，才考虑抽取更通用的 supervisor。

### 阶段 5：按证据扩展

只有在确认以下需求后再扩大范围：

- 多个不受信任第三方插件；
- 多种 transport 混用；
- 插件需要跨 UI 重启继续运行；
- 用户需要安装、升级、签名和权限审批。

届时再决定 runner supervisor、remote WebSocket、兼容性协商和分发安全模型。

## 8. 开放决策

以下问题会直接改变推荐方案：

- “第三方插件”是否意味着任意用户可安装的不受信任代码，还是经过审核和签名的扩展？
- 是否有明确的“插件崩溃不能影响桌面应用”的可用性目标？
- 后台能力是否必须独立于 UI 窗口重启，甚至独立于应用生命周期运行？
- 预计同时运行多少插件、窗口和后台任务？启动与内存预算是多少？
- 插件是否必须支持非 Node/非 TypeScript 或远程部署？
- 新窗口主要是 AIRI 自己的辅助窗口，还是第三方插件可贡献的 UI surface？
- 是否需要用户可见的安装、升级、权限批准和撤销流程？

在这些决策明确前，最稳妥的路线是：稳定控制面和宿主拥有权，保持窗口类型的局部性，先用一个真实垂直切片验证 isolated runner，再决定是否平台化。

[EVAL:evolve-software-architecture-loaded]
