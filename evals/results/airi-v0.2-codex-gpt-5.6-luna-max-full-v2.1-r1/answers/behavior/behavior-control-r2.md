## 结论

建议采用“混合式演进”：

- AIRI 自有窗口、Electron 服务和可信插件继续留在主进程。
- 第三方插件 UI 继续通过宿主管理的 iframe/资源会话呈现。
- 需要长期运行、可能崩溃或资源消耗不可控的插件，逐步迁移到独立进程，通过现有 `server-sdk`/WebSocket 协议接入。
- 暂不把本地 `ExtensionHost`、远程 WebSocket 插件、窗口注册表和权限系统强行统一成一个“大抽象”。

本次仅进行了只读检查，没有修改文件、创建提交或改变外部状态。

## 当前结构说明

1. 桌面主进程已经具备明确的 DI 组合根，但职责很多。`serverChannel`、`pluginHost`、`widgetsManager` 和多个窗口都在同一处组装，主窗口还依赖大量其他服务。[main/index.ts](/evaluation-path/control/apps/stage-tamagotchi/src/main/index.ts:154)

2. 窗口目前是“显式模块 + 少量复用管理器”的模式：已有 reusable window 和按 id 管理的 referenced window，而不是通用窗口注册表。[reusable.ts](/evaluation-path/control/apps/stage-tamagotchi/src/main/libs/electron/window-manager/reusable.ts:5)  
   其中窗口级 Eventa context 仍依赖 `ipcMain.setMaxListeners(0)`，代码也明确标记了未来的 window-namespaced context TODO。[referenced-window.ts](/evaluation-path/control/apps/stage-tamagotchi/src/main/windows/shared/referenced-window.ts:40)

3. 当前插件 host 是主进程内直接加载：桌面端构造 `ExtensionHost({ runtime: 'electron' })`，然后由 host 根据 manifest 启动会话。[host/index.ts](/evaluation-path/control/apps/stage-tamagotchi/src/main/services/airi/plugins/host/index.ts:224)  
   SDK 的 `FileSystemLoader` 最终直接 `import(entrypoint)`。[fs.ts](/evaluation-path/control/packages/plugin-sdk/src/plugin-host/runtimes/node/loaders/fs.ts:72)  
   因此，当前权限、会话和资源清理抽象并不等价于进程或 OS 隔离。

4. 插件 UI 已经有较清晰的宿主边界：静态资源通过带 cookie/session 校验的路由提供，renderer 侧通过 iframe 加载。[route.ts](/evaluation-path/control/apps/stage-tamagotchi/src/main/services/airi/http-server/static-assets/route.ts:42)  
   但默认 iframe sandbox 仍允许 `allow-scripts allow-same-origin allow-forms allow-popups`，所以这应视为 UI 内容边界，不应直接宣称为完整安全沙箱。[extension-ui-host.vue](/evaluation-path/control/apps/stage-tamagotchi/src/renderer/widgets/extension-ui/components/extension-ui-host.vue:105)

5. 独立后台所需的控制面其实已经存在：桌面主进程目前嵌入 `server-runtime` WebSocket server，[channel-server/index.ts](/evaluation-path/control/apps/stage-tamagotchi/src/main/services/airi/channel-server/index.ts:357)；`server-runtime` 已提供认证、模块注册、健康检查、心跳和路由。[server-runtime/index.ts](/evaluation-path/control/packages/server-runtime/src/index.ts:187)  
   `server-sdk` 也已有 token、announce、heartbeat 和 reconnect 能力。[client.ts](/evaluation-path/control/packages/server-sdk/src/client.ts:55)

## 应该稳定的边界

### 1. 身份与所有权

统一使用并严格区分：

- `extensionId`：插件持久身份；
- `sessionId`：一次运行实例；
- `moduleId`：插件模块；
- `windowId`：窗口实例；
- `processId/peerId`：外部进程或 WebSocket 对端；
- `requestId`：一次请求的相关性。

不要用 `moduleId` 代替 `windowId`，也不要把 WebSocket peer、插件 session 和 Electron window 混成一个概念。所有事件、资源 URL、工具调用和清理动作都应能够追溯到 owner/session。

### 2. 契约与传输分离

当前共享 Eventa 契约已经集中在 `src/shared/eventa`，这是应稳定的方向。[eventa/index.ts](/evaluation-path/control/apps/stage-tamagotchi/src/shared/eventa/index.ts:31)

建议稳定：

- 事件和 invoke 的语义；
- 结构化、可序列化的 payload；
- 版本、错误、超时、取消和 owner 信息；
- Eventa 作为本地 IPC 适配层；
- `server-runtime` 作为远程进程适配层。

不要再引入一个全局 event bus 来替代 Eventa，也不要让插件直接拿到 `ipcMain`、`BrowserWindow` 或任意 Electron API。

### 3. 生命周期与所有权

窗口、插件 session、iframe asset session、外部进程都应有明确的：

`start → ready/degraded → stop → disposed`

并且由拥有它们的 manager 负责清理。

当前退出流程把 `emitAppBeforeQuit()` 和 `injeca.stop()` 并行执行。[main/index.ts](/evaluation-path/control/apps/stage-tamagotchi/src/main/index.ts:328)  
未来有外部进程后，应明确为：

`停止新请求 → 标记插件停止接入 → 撤销资源 → drain/终止进程 → 清理窗口 context → 停止基础服务`

### 4. 插件 UI 与特权窗口分离

第三方插件不应复用 AIRI 自有窗口的通用 privileged preload。当前主窗口和 Widgets 窗口都使用 `sandbox: false`，共享 preload 还会暴露 Electron API。[main window](/evaluation-path/control/apps/stage-tamagotchi/src/main/windows/main/index.ts:80) [preload/shared.ts](/evaluation-path/control/apps/stage-tamagotchi/src/preload/shared.ts:8)

插件 UI 应保持：

`插件模块 → 宿主 widget → iframe → 受控消息端口`

如果未来确实需要插件独立窗口，应单独定义插件窗口 shell、最小 preload、导航白名单、CSP、sandbox 和权限策略。

### 5. 配置状态

当前 `enabled`、`loaded`、`autoReload` 已经是不同概念；尤其关闭 enabled 目前并不自动等于 unload。[host/index.ts](/evaluation-path/control/apps/stage-tamagotchi/src/main/services/airi/plugins/host/index.ts:447)

未来应明确区分：

`discovered → enabled → starting → ready/degraded → stopping → stopped/failed`

但不必现在就设计完整 marketplace、安装器或迁移所有配置。

## 应该延后的抽象

- 通用“所有插件都能在 local/node/worker/websocket 中运行”的统一 runtime。当前 node runtime 对 WebSocket、Node worker、Electron transport 仍明确抛出未实现错误。[node/index.ts](/evaluation-path/control/packages/plugin-sdk/src/plugin-host/runtimes/node/index.ts:24)

- 全局窗口注册表、窗口 manifest DSL 和统一窗口路由器。当前已有两个针对性管理器，先在真正出现“插件任意创建窗口”需求时做一个小范围试点。

- 远程 kit 的完全对称。`gameletKit` 和 `toolKit` 当前只允许 `local-only` 与 `remote-observable`，没有 `remote-callable`。[gamelet/index.ts](/evaluation-path/control/packages/plugin-sdk-tamagotchi/src/gamelet/index.ts:56) [tools/index.ts](/evaluation-path/control/packages/plugin-sdk-tamagotchi/src/tools/index.ts:281)  
  应一个 capability、一个 kit 地增加远程桥接，不要先造 universal bridge。

- 完整 marketplace、签名、自动更新和复杂权限 UI。安全信任模型应现在定义，但这些产品化能力应等第三方分发成为确定需求后再做。

- service mesh、进程池和通用 supervisor。现有 `McpStdioManager` 已提供可参考的进程生命周期模式，但它还不是通用插件平台。[mcp-servers/index.ts](/evaluation-path/control/apps/stage-tamagotchi/src/main/services/airi/mcp-servers/index.ts:151)

## 方案比较

| 方案 | 质量属性 | 成本与风险 | 回滚与不改变的后果 |
|---|---|---|---|
| A. 维持当前：可信插件留在主进程 | 集成和延迟最好；实现简单。对第三方代码的崩溃、CPU、内存和安全隔离最弱。 | 成本最低。风险是主进程与插件债务持续累积。 | 回滚最简单：disable/unload 即可。不改变的后果是不能可靠承诺“任意第三方插件不会影响桌面应用”，更多窗口也会继续扩大主进程和 IPC 复杂度。适合第一方或高度可信插件。 |
| B. 混合式：本地 host + 选择性外置进程 | 推荐。保留本地 UI 插件的低延迟；后台插件获得进程级崩溃隔离、重连和独立生命周期。安全仍需 OS sandbox，WebSocket 本身不是安全沙箱。 | 中等成本：新增窄 supervisor、进程状态、token、heartbeat 和一个远程 capability bridge。主要风险是 local/remote 两套运行模型并存。 | 每个插件独立选择 local/process，保留现有 manifest v1；process 模式失败时切回 local 或禁用该插件，不做全量迁移。代价是需要维护两套状态和契约。 |
| C. 全量隔离平台：所有第三方插件外置、统一远程 kit、插件窗口平台 | 隔离性、长期运行能力、可观测性和团队扩展性最好。跨进程延迟、协议复杂度和安全测试成本最高。 | 成本最高，涉及安装分发、权限代理、supervisor、协议兼容、窗口安全和大量测试。当前仓库没有足够证据证明现在就需要它。 | 可通过版本化远程协议保留 v1，但回滚复杂。若第三方不可信、插件需要长期后台运行或要开放生态，再考虑。 |

推荐 B，但实施顺序应是“先把边界稳定下来，再只外置一个真实需要后台能力的插件”。

## 渐进迁移路线与验收

### 阶段 0：确定信任等级

把插件分为：

- AIRI 内置/开发插件；
- 可信本地插件；
- 第三方 iframe UI 插件；
- 需要长期运行或可能不稳定的后台插件。

同时定义主进程启动、插件崩溃、窗口关闭、资源泄漏和重连的基线指标。若没有“非可信代码”或“长期后台”需求，暂时停留在方案 A 也合理。

### 阶段 1：冻结协议边界

继续使用现有共享 Eventa 文件定义本地契约，补齐：

- owner/session/module/window/request 标识；
- version、状态、错误和 timeout；
- structured-clone-safe payload；
- 明确的 stop/dispose 语义。

验收：旧的本地 v1 插件仍能 load/unload；窗口关闭后无 pending request；不同插件和窗口之间不能互相消费事件。

### 阶段 2：先做生命周期和窗口试点

不要迁移所有现有窗口。选择一个动态窗口或 Widgets 入口，验证窗口 context 的创建、关闭、重开和清理。

验收：

- 窗口关闭后 handler 数量不会持续增长；
- 不会向已销毁的 `webContents` 发送请求；
- 插件 unload 后 iframe asset session、module binding 和窗口全部清理；
- 应用退出时所有 session 都进入 stopped/disposed。

### 阶段 3：外置一个后台插件

新增窄范围 supervisor，职责只包括：

- 启动、停止、重启；
- stdout/stderr 和退出码；
- token/peer identity；
- heartbeat、健康状态和重连；
- 应用退出时的 drain/terminate。

外部插件通过 `server-sdk` 接入，不直接调用 Electron。先只支持一个明确的后台 module 或 observable capability，不尝试远程复刻全部 `ExtensionHost`。

验收：杀掉子进程时主窗口仍可用；peer 被健康检查移除；重启后不会出现重复 module；错误 token 无法注册；退出时子进程不会遗留。

### 阶段 4：增加一个远程 capability bridge

选择一个实际需求，例如只读状态、后台事件或一个受控工具调用。远程插件只返回协议数据，窗口仍由 AIRI 宿主和 iframe 管理。

验收：超时、取消、非法 payload、过期 session、错误 owner 都有明确结果；远程插件不能直接创建 `BrowserWindow` 或访问 privileged preload。

### 阶段 5：根据证据决定是否进入方案 C

只有在以下条件出现时，才引入完整隔离平台：

- 第三方代码不再可信；
- 插件需要持续运行、重启和资源配额；
- 插件数量足以让主进程维护成本成为主要问题；
- 已经有至少一个远程 capability 的稳定协议和测试矩阵。

每个阶段都应保留本地 host 和 manifest v1，采用显式版本化配置或 feature flag，避免一次性替换导致无法回滚。
