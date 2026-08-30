## 结论

建议采用“分层、双运行时”路线：

- 第一方和明确可信的第三方插件继续使用当前 Electron 主进程内的 `ExtensionHost`。
- 需要长期运行、可能不稳定或不应信任的插件，逐步改为独立进程，通过现有 Server Channel / `server-sdk` 通信。
- 插件 UI 继续由宿主控制，以 widget/gamelet/iframe 为主要呈现面。
- 暂不建设“万能插件运行时”“万能窗口注册表”或统一所有后台服务的抽象。

当前仓库已经具备这条路线的大部分基础，但当前插件逻辑仍然属于 Electron 主进程的同一故障与权限域。

## 当前结构证据

- 桌面主进程是一个清晰的 Injeca 组合根，显式组装 Server Channel、HTTP server、Godot、MCP、widgets、plugin host 和各类窗口管理器：[main/index.ts](</evaluation-path/control/apps/stage-tamagotchi/src/main/index.ts>)。
- 插件宿主从用户目录扫描 `extensions/v1`，维护 manifest、启用状态、session、module 和资源会话：[plugin host](</evaluation-path/control/apps/stage-tamagotchi/src/main/services/airi/plugins/host/index.ts>)。
- Electron 插件入口由 `FileSystemLoader` 动态 `import()`，因此当前插件代码是在主进程内执行，并非真正的进程或 JS 沙箱：[FileSystemLoader](</evaluation-path/control/packages/plugin-sdk/src/plugin-host/runtimes/node/loaders/fs.ts>)。
- 插件 UI 已有较好的宿主边界：iframe、sessionized 静态资源 URL、cookie 授权和 typed message bridge：[extension-ui-host.vue](</evaluation-path/control/apps/stage-tamagotchi/src/renderer/widgets/extension-ui/components/extension-ui-host.vue>)、[static-assets](</evaluation-path/control/apps/stage-tamagotchi/src/main/services/airi/plugins/features/static-assets/index.ts>)。
- 窗口目前同时存在 reusable window 和按 ID 管理的 referenced window 两种模式；共享窗口服务会为每个窗口安装多个 Electron/Eventa 服务：[shared window](</evaluation-path/control/apps/stage-tamagotchi/src/main/windows/shared/window.ts>)、[reusable window](</var/folders/fs/w5cbmbdn4zgc0sn_0t8kxc6h0000gn/T/air/airi-forward-eval-checkouts-1805fflf/control/apps/stage-tamagotchi/src/main/libs/electron/window-manager/reusable.ts>)。
- 多个 RPC/preload 文件设置 `setMaxListeners(0)`，而生命周期 hook 是模块级数组且没有注销接口：[lifecycle](</evaluation-path/control/apps/stage-tamagotchi/src/main/libs/bootkit/lifecycle.ts>)。这不等同于已经确认存在泄漏，但随着窗口增加，应优先验证重复创建、关闭、重开后的监听器和闭包数量。
- Server Channel 已经是本仓库的外部进程边界，具有认证、peer、心跳和路由能力：[channel-server](</evaluation-path/control/apps/stage-tamagotchi/src/main/services/airi/channel-server/index.ts>)、[server-runtime](</evaluation-path/control/packages/server-runtime/src/server/index.ts>)。Godot 和 MCP 也已经采用独立子进程模式，但各自有不同协议和生命周期：[Godot](</evaluation-path/control/apps/stage-tamagotchi/src/main/services/airi/godot-stage/index.ts>)、[MCP](</evaluation-path/control/apps/stage-tamagotchi/src/main/services/airi/mcp-servers/index.ts>)。

## 应该稳定的边界

### 1. 插件控制面

稳定以下概念，而不是冻结具体文件结构：

`extensionId → sessionId → moduleId → owner`

同时保持：

- manifest API version；
- 权限请求与授予；
- capability/module identity；
- start、stop、reload、dispose 生命周期；
- JSON/structured-clone 可传输的数据结构。

现有 `plugin-protocol` 和 `plugin-sdk` 已经在表达这些概念：[plugin host types](</evaluation-path/control/packages/plugin-sdk/src/plugin-host/shared/types.ts>)。

### 2. 信任边界

必须明确区分：

- `trusted-in-process`：可信插件，允许进入当前主进程宿主；
- `isolated-external`：独立进程或远程 peer，通过协议访问宿主能力。

当前权限系统主要限制插件可调用的 kit/API，并不构成 JS 进程沙箱。因此，不能把当前 `ExtensionHost(runtime: electron)` 宣称为安全的“不可信第三方插件环境”。

### 3. 窗口会话边界

每个窗口最终应拥有独立的 Window Session，负责：

- `BrowserWindow`；
- Eventa context；
- sender 校验；
- route/navigation；
- 窗口级服务；
- 所有清理函数。

应用级服务，例如 plugin host、Server Channel、MCP、Godot、全局快捷键，不应随着每个窗口重复实例化。

这里需要稳定的是“所有权和清理责任”，不一定立即抽出一个通用 `WindowRegistry`。

### 4. 插件 UI 边界

继续优先使用宿主拥有的 widget/gamelet/iframe surface。插件提供：

- UI descriptor；
- 可序列化 props；
- message/event；
- tool/capability contribution。

插件不应直接获得 `BrowserWindow`、`ipcMain`、Pinia store 或 Electron 主进程对象。若未来确实需要原生窗口，应提供受限的宿主 broker，而不是暴露任意窗口创建 API。

### 5. 独立后台边界

Server Channel 应作为外部后台和跨进程模块的稳定协议边界；内部 Electron Eventa 不应成为第三方后台的公共协议。

后台能力至少要有：

- handshake/version；
- authentication；
- ready/health；
- start/stop/restart；
- heartbeat/reconnect；
- stale peer 清理；
- graceful shutdown。

不要因为 Godot、MCP、HTTP 都是“后台”，就立即统一成一个 `BackgroundManager`。它们目前的启动、协议、失败处理和资源模型并不相同。

## 应该延后的抽象

- “支持所有 transport”的统一插件运行时。当前 SDK 类型包含多种 transport，但 Node runtime 中仍有 WebSocket、worker、Electron transport 等未实现分支；类型集合不能视为完整能力。
- 通用 `WindowRegistry` 或“所有窗口都由一个 registry 管理”。现有 reusable window 和 referenced window 已覆盖不同场景，尚未证明需要第三种统一抽象。
- 通用 `AppKernel`、万能 service locator、所有服务统一生命周期基类。当前显式 Injeca 组合根仍然可读、可追踪。
- 任意第三方原生窗口能力。
- marketplace 的安装、签名、依赖解析、更新、版本冲突处理。除非产品明确要求不可信市场分发，否则这些会过早引入很高的安全和运维成本。
- 立即决定使用 worker、child process、Electron utility process 还是独立 daemon。应先确定威胁模型、延迟、崩溃隔离、打包和升级要求。
- 将所有重复的插件类型立刻集中到一个“大而全”的包。应在实际公共协议变更时，逐步以 `plugin-protocol` 为所有权来源。

## 方案比较

| 方案 | 质量属性 | 成本与风险 | 回滚路径 | 不改变的后果 |
|---|---|---|---|---|
| A. 维持现状，只增加约束 | 性能、调试体验和开发效率最好；隔离性、崩溃容错和安全性最弱 | 成本最低；插件可以阻塞或崩溃主进程，也可能访问超出预期的 Node/Electron 能力 | 保留 manifest v1，按插件禁用、unload；回滚最简单 | 只适合可信插件。无法安全支持不可信市场插件；后台能力仍会逐步变成主进程内的集中故障域 |
| B. 双运行时 + 宿主 broker，推荐 | 可信插件保留低延迟；独立插件获得崩溃隔离和独立重启；适合逐步扩展窗口和后台 | 中等成本；需要协议版本、认证、health、重连、日志和两种运行时的调试支持 | 每个插件单独选择 runtime；外部插件可关闭，可信插件路径继续保留；无需一次迁移全部插件 | 若不做，第三方逻辑仍会继续进入主进程，独立后台只能通过 MCP、Server SDK 等零散方式接入 |
| C. 所有插件逻辑迁移到独立 Plugin Host 进程 | 隔离、可用性、独立升级和重启能力最好，适合不可信市场 | 成本最高；涉及进程监督、协议兼容、崩溃恢复、跨平台打包签名、开发调试和 UI 重连 | 必须长期保留当前 in-process adapter，使用 feature flag 双轨运行；回滚代价较高 | 若不做，安全和故障隔离上限较低，但对可信插件并不一定构成实际问题 |

推荐 B 的原因是：它复用现有 `ExtensionHost`、iframe UI、Server Channel 和 sidecar 经验，同时把“是否信任插件”和“是否需要独立后台”变成显式策略，而不是一次性重写桌面应用。

如果第三方仅指“用户手动安装且明确可信的开发者插件”，A 可以继续使用较长时间；如果目标是开放 marketplace、安装未知代码，则至少需要 B，最终可能需要 C。即使采用独立进程，也仍需要签名、权限和 OS 级策略，进程隔离本身不是完整安全方案。

## 可验证的渐进迁移路线

### 阶段 0：建立基线

先给每类插件标注：

- 信任级别；
- 运行时；
- 所有者；
- UI 贡献；
- 后台能力；
- 失败影响范围。

验证现有插件测试覆盖 start/stop/reload、权限、capability、tool/gamelet 清理、资源会话撤销。仓库已有相关测试，可作为基线：[plugin tests](</evaluation-path/control/apps/stage-tamagotchi/src/main/services/airi/plugins/index.test.ts>)、[SDK lifecycle tests](</evaluation-path/control/packages/plugin-sdk/src/plugin-host/core.test.ts>)。

### 阶段 1：先解决窗口生命周期

选择 widgets 或 settings 作为试点，验证：

- 多轮创建、关闭、重新打开后，Eventa listener 数量是否回到基线；
- lifecycle hook 是否重复注册；
- 已关闭窗口不能继续 invoke；
- 不同窗口不能互相使用 sender/context；
- plugin UI、tool、widget 绑定是否在窗口或插件关闭后清理。

只有这些验证通过后，再逐步把共享窗口服务整理为 Window Session。不要先创建全局窗口抽象。

### 阶段 2：稳定插件控制面

在不破坏 manifest v1 的前提下，统一：

- extension/session/module/owner identity；
- runtime kind；
- lifecycle state；
- permission/capability DTO；
- renderer 与 main 之间的只读 snapshot 和 invoke contract。

验证标准是：旧插件仍可加载，stop/reload 后不存在残留 tool、widget、asset session 或 capability。

### 阶段 3：试点一个独立后台插件

选一个不依赖原生窗口的后台能力，通过 Server Channel 运行：

- handshake 和协议版本；
- token/auth；
- ready/health；
- stop/restart；
- 网络断开后的 reconnect；
- 进程异常退出后的 stale peer 清理。

验收标准：该进程崩溃或重启时，Electron 主进程、其他插件和其他窗口不受影响。

### 阶段 4：形成双运行时策略

为插件逐个选择：

- 可信、低延迟、强宿主集成：当前 in-process；
- 长期后台、不稳定或不可信：external；
- UI：仍由宿主 widget/gamelet/iframe 承载。

新插件默认不应获得任意原生窗口权限；外部运行时先采用 opt-in 和 feature flag，不做一次性迁移。

### 阶段 5：按指标决定是否采用 C

只有出现以下需求时，才进入完整独立 Plugin Host 进程：

- marketplace 需要运行未知代码；
- 插件故障已经影响主进程稳定性；
- 插件需要独立升级、重启或资源配额；
- 多个长期后台插件使主进程成为明显瓶颈；
- 已有 Server Channel 协议和运行监控证明可承受迁移。

迁移期间保留旧 in-process adapter，按插件灰度；任何插件都可以通过配置退回旧路径。

## 最终建议

当前最值得稳定的是“协议、身份、信任域、窗口会话、UI surface、Server Channel、生命周期所有权”。最值得延后的，是“万能运行时、万能窗口管理器、万能后台抽象和完整市场系统”。

本次仅进行了只读检查，没有修改文件、创建提交或改变外部状态。
