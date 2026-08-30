## 结论

建议采用“混合运行时”路线：

- 先稳定插件身份、能力协议、窗口语义和服务生命周期。
- 保留当前主进程内运行，作为可信插件和开发插件的默认路径。
- 为不可信或高风险第三方插件预留独立进程运行时，但暂不把所有插件一次性迁出。
- 窗口继续由桌面宿主管理，插件只请求声明式的窗口/组件能力。
- 后台能力按服务生命周期逐步拆分，不立即建设完整微服务体系。

核心原则是：稳定“语义和边界”，延后“具体进程拓扑和通用管理器”。

## 当前仓库真实形态

AIRI 桌面应用已经具备三个相对清晰的平面：

1. Electron 主进程与 `injeca` 组合根，统一编排 server channel、Godot、MCP、插件宿主和多个窗口管理器。[主进程组合根](</evaluation-path/control/apps/stage-tamagotchi/src/main/index.ts:260>)

2. 多个独立窗口管理器。`main`、`settings`、`chat`、`widgets` 等窗口仍分别创建 `BrowserWindow`，并为每个窗口建立 Eventa 上下文。[主窗口管理器](</evaluation-path/control/apps/stage-tamagotchi/src/main/windows/main/index.ts:80>)、[共享窗口服务](</evaluation-path/control/apps/stage-tamagotchi/src/main/windows/shared/window.ts:134>)

3. 插件宿主与 iframe UI。插件清单、权限、session、module、kit 和资源会话已经有模型；插件 UI 通过 sandbox iframe 和带 cookie 会话的本地静态资源服务加载。[插件宿主核心](</evaluation-path/control/packages/plugin-sdk/src/plugin-host/core.ts:183>)、[静态资源服务](</evaluation-path/control/apps/stage-tamagotchi/src/main/services/airi/http-server/static-assets/index.ts:40>)

关键限制是：当前 Electron 插件入口由文件系统 loader 直接 `import()`，因此插件代码运行在主进程 JavaScript 运行时内。[文件系统 loader](</evaluation-path/control/packages/plugin-sdk/src/plugin-host/runtimes/node/loaders/fs.ts:44>)。这不是操作系统级隔离；manifest 权限只能约束 AIRI 暴露的能力，不能等同于文件系统、网络或进程权限沙箱。

另外，`PluginTransport` 已声明 websocket、worker、Electron 等形态，但当前 Node/Web runtime 中除内存实现外，多数传输仍明确抛出“未实现”。[Node runtime transport](</evaluation-path/control/packages/plugin-sdk/src/plugin-host/runtimes/node/index.ts:12>)

## 应该稳定的边界

| 边界 | 建议稳定的内容 | 当前依据与原因 |
|---|---|---|
| 插件身份与生命周期 | `extensionId`、manifest 版本、`sessionId`、`moduleId`、加载阶段、停止和清理语义 | 当前宿主已经有 session、module、loaded/unloaded、reload 和 owner 资源清理模型。应保持传输无关。 |
| 能力与权限 | manifest 请求权限、宿主授予权限、kit/module 能力、资源和工具调用 | 权限应继续是“能力授权模型”，但要明确它不是 OS 隔离。 |
| 插件协议 | Eventa 事件契约、可序列化 payload、请求 ID、超时、取消、错误和版本协商 | `plugin-protocol` 和各类 shared Eventa contract 已经是未来本地/远程运行时的共同语言。 |
| 插件 UI | 插件 UI 与特权页面隔离，优先 iframe；资源通过会话化、路径受限的服务提供 | 现有 iframe、cookie 会话、路径穿越和 symlink 检查是可复用的安全边界。 |
| 窗口语义 | `windowId`、owner、surface/route、生命周期、可见性、关闭策略、持久化 key | 具体 `BrowserWindow` 应留在桌面宿主内部；插件不应获得 `BrowserWindow`、`webContents` 或原始 Electron IPC。 |
| 服务生命周期 | `start`、`stop`、`restart`、状态、健康、拥有者、关闭顺序和取消语义 | 当前 `server-manager` 已有串行启动、逆序关闭和并发保护；Godot、MCP 也已经体现了外部进程生命周期。 |
| 资源所有权 | session 关闭时撤销工具、资源 URL、iframe 请求、窗口上下文和待处理 RPC | widgets 的请求协调器已经按 `requestId` 和 widget ID 做隔离，是值得推广的模式。 |

尤其要稳定的是“插件只看到 capability/kit，不看到桌面实现”。`packages/plugin-sdk` README 已经明确了本地服务和远程 Eventa client 应保持相同的插件编写形状。[Plugin SDK 设计说明](</evaluation-path/control/packages/plugin-sdk/README.md:5>)

## 应该延后的抽象

| 抽象 | 建议 | 原因 |
|---|---|---|
| 全部插件“一插件一进程” | 延后，先做可替换 runner | 当前远程 transport 尚未落地；直接全面迁移会同时引入启动、认证、重连、打包、诊断和协议兼容问题。 |
| 通用 `WindowManager` | 延后大型统一抽象，只先统一窗口描述和上下文清理 | 当前窗口语义差异很大：主窗口、设置窗口、通知窗口、overlay、widgets 的复用和关闭策略并不相同。 |
| 全局后台服务总线或 service mesh | 延后 | 现有 server channel、HTTP server、Godot、MCP 已有不同边界，强行统一会制造浅层转发层。 |
| 完整 Electron/Node/Web runtime 矩阵 | 按需求实现 | 类型和 transport 名称存在，不代表这些运行时已经具备真实能力。 |
| 市场、签名、依赖求解、自动升级体系 | 延后 | 只有在第三方分发、信任模型和更新责任明确后才值得冻结。 |
| 零停机热更新 | 延后 | 当前 reload 是先 stop 再 start，测试中也明确存在短暂空窗；应先稳定清理和失败恢复。 |
| 将 Electron API 直接纳入插件 SDK | 不应建设 | 会把未来的窗口和进程重构成本转嫁给所有插件。 |

## 三种可行方案

| 方案 | 形态 | 质量属性权衡 | 成本与风险 | 回滚路径 |
|---|---|---|---|---|
| A. 维持现状 | 插件继续在主进程内动态加载；窗口维持各自 manager；后台服务继续由主进程或现有 sidecar 管理 | 延迟低、开发快、调试简单；但隔离和故障容忍弱，插件可能影响主进程，窗口越多 IPC 生命周期越难管理 | 成本最低。主要风险是第三方插件信任问题、主进程稳定性、listener 泄漏和资源清理 | 最简单，完全保留当前路径 |
| B. 混合运行时，推荐 | 可信插件使用 in-process runner；高风险插件使用 out-of-process runner；共享 manifest、session、kit、Eventa 协议；窗口和 UI 仍由宿主控制 | 兼容性、迁移速度和隔离性较平衡；代价是同时维护两种故障模型和两套 runner | 中等成本。主要风险是本地/远程行为不一致、协议版本管理和信任策略含糊 | 按插件或信任等级切换 runner；保留现有 manifest v1 和 in-process runner |
| C. 全部插件和后台能力进程化 | 主进程只做注册、授权、窗口监督和协议网关，插件全部在 worker/子进程/独立服务中运行 | 故障隔离、重启能力和长期扩展性最好；但延迟、内存、打包、调试、认证、重连和跨平台运维成本最高 | 高成本、高初始风险。当前 plugin-sdk 的远程 transport 还没有实现，不能直接视为可用基础 | 只有在保留旧 runner 和版本化协议的前提下可回滚；若先改写插件 API，回滚会很困难 |

### 对第三方插件的建议

按信任等级区分，而不是按“插件”一刀切：

- UI-only 插件：只提供 iframe UI 和声明式数据能力。
- AIRI 官方或本地开发插件：可暂时使用主进程 runner。
- 第三方 native/plugin runtime：默认独立进程；如果仍在主进程运行，必须明确标记为 trusted，而不是让 manifest 权限制造“已经沙箱化”的错觉。

### 对更多窗口的建议

不要立刻创建一个包办所有窗口行为的超级管理器。先形成一个窄边界：

```text
Window descriptor
  -> host-owned BrowserWindow
  -> per-window Eventa context
  -> disposable handlers
  -> owner-scoped lifecycle and cleanup
```

当前代码中已经出现 `createContext(ipcMain, window)`、窗口引用管理和 widget 请求隔离；下一步应统一这些语义，而不是统一所有窗口的 UI 行为。特别是主进程中已有关于“window-namespaced contexts”的 TODO，并使用 `setMaxListeners(0)` 规避监听器警告。[窗口生命周期实现](</evaluation-path/control/apps/stage-tamagotchi/src/main/windows/shared/referenced-window.ts:38>)、[widgets 请求协调器](</evaluation-path/control/apps/stage-tamagotchi/src/main/windows/widgets/iframe-request-coordinator.ts:1>)

### 对独立后台的建议

AIRI 已经有渐进拆分的基础：

- server channel 是可启动、停止、重启的 WebSocket 服务，但目前仍嵌在主进程生命周期中。[server channel](</evaluation-path/control/apps/stage-tamagotchi/src/main/services/airi/channel-server/index.ts:357>)
- Godot 已经作为外部进程管理。
- MCP 已经通过 stdio 子进程管理。
- `server-sdk` 已有 WebSocket extension peer，但它与 `plugin-sdk` 中尚未完成的 runtime transport 不是同一个完整实现。[WebSocket extension peer](</evaluation-path/control/packages/server-sdk/src/extension-peer.ts:66>)

因此不应一次性把所有主进程逻辑搬走。应先选择一个状态简单、可重启、协议边界明确的后台能力做试点。

## 可验证的渐进迁移路线

### 阶段 0：建立基线

记录当前行为和指标：

- 插件加载、卸载、reload、权限拒绝和资源撤销。
- 窗口反复打开/关闭后的 handler、pending request 和上下文数量。
- 主进程启动时间、内存、插件加载延迟。
- server channel、Godot、MCP 的启动、重启和退出行为。

现有测试可作为基线入口，包括插件宿主测试、widgets 请求相关测试、静态资源鉴权测试和 server-manager 生命周期测试；此处不应把“已有测试文件”误认为已覆盖所有进程隔离问题。

### 阶段 1：冻结语义契约，不改运行方式

形成 ADR 和契约测试，明确：

- manifest v1 的身份和版本规则。
- session/module/kit/owner 的关系。
- 权限、能力和资源的授权边界。
- Eventa payload 必须可序列化。
- RPC 必须具备 request ID、deadline、取消、错误和关闭后的 pending 清理。
- 执行模式属于宿主信任策略，不由插件自行提升权限。

验收标准：现有插件在不改变运行方式的情况下，快照和事件契约保持不变。

### 阶段 2：先治理窗口边界

按现有窗口逐个建立语义描述：

`main`、`settings`、`chat`、`about`、`onboarding`、`notice`、`spotlight`、`caption`、`widgets`、`devtools`、`inlay`、`overlay` 等。

先选择一个窗口族，例如 referenced windows 或 widgets，验证：

- 重复打开不会创建重复上下文。
- 窗口关闭会移除 handler、Eventa context 和 pending request。
- 一个窗口的事件不能被另一个窗口接收。
- 监听器数量不会随打开/关闭单调增长。
- 旧的窗口 manager 仍可作为回退实现。

### 阶段 3：引入 runner 边界

抽象的不是“进程”，而是插件运行器能力：

```text
Plugin host
  -> runner.start(manifest)
  -> runner.stop(session)
  -> runner.reload(session)
  -> runner.snapshot()
```

当前 runner 只是包装现有的 `ExtensionHost`；返回的 session、module、kit 和资源语义保持不变。这样不会迫使现有插件立即迁移，也能让后续子进程 runner 复用同一协议。

### 阶段 4：做一个独立进程 spike

先选择无 UI 或低风险的开发插件，不要一开始迁移双向 gamelet。必须验证：

- 握手、协议版本和认证。
- 权限拒绝是否发生在宿主侧。
- 超时、取消、断开和重连。
- 子进程崩溃后是否能清理 session、工具和资源。
- 子进程不能取得 Electron 对象。
- 主进程和插件进程能分别诊断、停止和重启。
- macOS、Windows、Linux 的打包和启动路径。

由于现有 plugin-sdk transport 仍有未实现分支，这个 spike 应被视为技术验证，不应提前承诺全面进程化。

### 阶段 5：按风险逐步迁移

迁移顺序建议：

1. 低风险、无 UI 插件。
2. 工具型插件。
3. 需要 iframe UI 的插件。
4. 最后才是需要持续双向通信的 gamelet 或复杂后台插件。

对不可信插件，远程 runner 失败时应“禁用并报告”，不能静默退回主进程运行；否则隔离策略会被回退路径绕过。

### 阶段 6：选择性拆分后台

选择一个后台能力，使其具备：

- 独立启动和停止。
- 明确 owner 和健康状态。
- loopback 地址、独立 token/audience。
- 断线重连和主进程重启后的恢复。
- 不依赖 renderer 存活。
- 正常关闭和异常退出清理。

现有可 LAN 绑定的 server channel 不应直接等同于内部插件控制通道；内部服务应有单独的 loopback 和认证策略。

## 如果暂时什么都不改变

维持现状并非立即不可行。对于官方插件、开发插件和 iframe UI，它能提供最低成本和最快迭代速度。

但随着第三方 native 插件、窗口数量和后台服务增加，后果会逐渐明确：

- 主进程成为所有插件的共同故障域。
- manifest 权限容易被误解为真正的安全隔离。
- 每个窗口重复注册基础 IPC，`setMaxListeners(0)` 会掩盖生命周期问题。
- 插件 reload、窗口关闭和后台重启更容易留下孤儿资源或短暂不可用状态。
- 后续若直接切换到进程化架构，插件 API、打包方式和数据布局可能同时破坏，回滚成本显著增加。

因此推荐现在就冻结协议、资源所有权和窗口语义；把“所有插件进程化”“通用窗口管理器”“完整后台服务网格”留到有实际隔离、稳定性或独立部署需求时再做。

本次仅进行了只读仓库检查，没有修改文件、创建提交或改变外部状态。
