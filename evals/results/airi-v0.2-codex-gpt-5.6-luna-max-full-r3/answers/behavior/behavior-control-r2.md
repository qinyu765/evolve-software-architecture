只读检查结果：工作树干净，当前 HEAD 为 `5228f9412`；以下判断基于仓库中可检查的调用关系，未修改文件、创建提交或改变外部状态。

## 结论

AIRI 已经具备一些值得保留的边界雏形，但当前桌面应用还不是可安全承载“不可信第三方代码”的插件平台。

建议采用：

- 近期：稳定“应用、窗口、插件会话、后台服务、协议”五个边界。
- 中期：内置插件继续嵌入主进程；第三方后台插件逐个支持外部进程运行。
- 长期：只有在出现真实的多运行时、多阶段依赖需求后，再实现完整的 transport 抽象和 capability orchestration。

如果未来插件来源包含任意第三方或市场分发，外部进程隔离应成为最终方向；如果只是可信的内置扩展，嵌入式方案仍可保留。

## 当前结构说明

桌面主进程已经是明显的组合根，统一装配窗口、服务器、Godot、MCP、插件等服务：[main/index.ts](</evaluation-path/control/apps/stage-tamagotchi/src/main/index.ts:154>)。

窗口侧已有按窗口创建 Eventa context、注册基础 RPC 和校验 sender 的模式：[main/rpc/index.electron.ts](</evaluation-path/control/apps/stage-tamagotchi/src/main/windows/main/rpc/index.electron.ts:48>)、[shared/window.ts](</evaluation-path/control/apps/stage-tamagotchi/src/main/windows/shared/window.ts:134>)。但多个位置仍以 `setMaxListeners(0)` 和 “window-namespaced contexts” TODO 作为过渡方案：[preload/shared.ts](</evaluation-path/control/apps/stage-tamagotchi/src/main/preload/shared.ts:9>)。

插件目前由主进程中的 `ExtensionHost({ runtime: 'electron' })` 管理：[plugin host](</evaluation-path/control/apps/stage-tamagotchi/src/main/services/airi/plugins/host/index.ts:236>)。启动路径最终由 `FileSystemLoader` 动态 `import(entrypoint)`：[plugin-host core](</evaluation-path/control/packages/plugin-sdk/src/plugin-host/core.ts:777>)、[filesystem loader](</evaluation-path/control/packages/plugin-sdk/src/plugin-host/runtimes/node/loaders/fs.ts:72>)。因此，当前第三方插件代码实际上与 Electron 主进程共享地址空间；权限模型是 API 访问控制，不是 OS 级隔离。

插件 UI 已有较好的宿主边界：插件通过 widget/gamelet 描述请求窗口和 iframe，窗口、资产会话、清理由 AIRI 管理：[plugin types](</evaluation-path/control/apps/stage-tamagotchi/src/main/services/airi/plugins/types.ts:45>)、[WidgetsWindowManager](</evaluation-path/control/apps/stage-tamagotchi/src/main/windows/widgets/index.ts:290>)。

后台能力也已有不同成熟度的实例：内嵌 server channel、HTTP server manager、MCP stdio 子进程、Godot 子进程：[channel-server](</evaluation-path/control/apps/stage-tamagotchi/src/main/services/airi/channel-server/index.ts:357>)、[MCP manager](</evaluation-path/control/apps/stage-tamagotchi/src/main/services/airi/mcp-servers/index.ts:166>)、[Godot manager](</evaluation-path/control/apps/stage-tamagotchi/src/main/services/airi/godot-stage/index.ts:699>)。

## 应稳定的边界

1. **应用级组合根**

   `main/index.ts` 可以继续负责装配和生命周期，但不应承载插件业务、窗口细节或后台进程协议。主进程应成为 supervisor/kernel，而不是所有功能的实现中心。

2. **窗口表面（Window Surface）**

   稳定的概念应包括：

   - `windowId` 或明确的窗口实例身份；
   - 每窗口 Eventa context；
   - sender/webContents 校验；
   - open/show/close/dispose 生命周期；
   - 关闭时清理 handlers、pending requests 和 context。

   暂时不要把所有窗口统一成一个“大而全”的 `WindowManager`。主窗口、设置窗口、overlay、widget 子窗口、隐藏工具窗口的生命周期语义并不相同。

3. **插件会话与资源所有权**

   继续以 `extensionId → sessionId → moduleId` 组织插件资源。插件加载、能力声明、工具、窗口、资产会话和事件订阅都应记录 owner，并能在 unload、崩溃、超时时统一撤销。

4. **后台服务/进程生命周期**

   稳定一个窄接口即可：

   `start → ready/running → degraded/error → stop → stopped`

   需要明确 readiness、停止超时、强制终止、重启、状态订阅和 owner。已有 Godot、MCP、server manager 是可复用的行为参考，但不应立即抽成一个包揽所有语义的 `Backend` 基类。

5. **控制面与数据面**

   插件控制、生命周期、能力、状态属于控制面；widget payload、音频、流式数据属于数据面。共享协议应保持类型化、可序列化、带身份和关联 ID。Eventa 的“按 transport 创建 context”方向是合理的，但目前多 transport 仍未完成：[node runtime](</evaluation-path/control/packages/plugin-sdk/src/plugin-host/runtimes/node/index.ts:24>)。

## 应延后的抽象

- 通用 `WindowManager` / actor 模型：当前窗口类型差异足够大，过早统一会把特殊语义隐藏起来。
- 完整 transport-agnostic Plugin SDK：仓库设计文档仍标为 Planned，Node worker、WebSocket、Electron transport 目前有未实现分支：[multi-transport design](</evaluation-path/control/packages/plugin-sdk/docs/design/multi-transport.md:150>)。
- 全局 capability scheduler：当前 capability orchestration 文档仍是 Proposed；先稳定能力身份、状态和撤销，不要先引入复杂依赖图。
- 允许插件直接创建 `BrowserWindow`、访问 `ipcMain` 或控制任意 Electron API。插件应只能声明 widget、工具、服务和能力。
- 把 HTTP、MCP、Godot、server channel 全部包装成同一种“后台服务”。它们的启动、通信、失败和重启语义不同。

## 可行方案比较

| 方案 | 质量属性权衡 | 成本与风险 | 回滚路径 |
|---|---|---|---|
| A. 维持嵌入式 `ExtensionHost` | 启动快、延迟低、开发简单；但主进程崩溃、阻塞、内存泄漏和插件权限风险全部耦合到桌面应用 | 成本最低；随着插件和窗口增加，主进程组合根、全局 listener 和清理路径会持续复杂化 | 不需要协议或数据迁移，始终保留当前路径 |
| B. 独立 Plugin Host 进程 | 崩溃隔离、可重启、适合无 UI 后台插件和不可信代码；代价是 IPC 延迟、版本协商、打包、认证、进程管理复杂度上升 | 成本最高；当前 SDK 的远程/worker transport 还不能直接使用，需要实现 launcher、协议适配、心跳、重连和资产/UI桥接 | 按插件配置回退到嵌入式 host；保持相同 manifest 和 session 快照 |
| C. 混合方案：UI/宿主能力留在主进程，插件执行按需外置 | 兼顾渐进迁移和隔离：widget 仍由 AIRI 控制，后台逻辑可独立重启；但会产生两套执行模式和更多测试矩阵 | 成本中高；最大风险是嵌入式与外部模式行为不一致、诊断复杂 | 逐插件切换执行模式，外部插件失败时回到嵌入式实现 |

推荐采用 **C 作为迁移路径，B 作为不可信第三方插件的最终目标，A 作为内置/开发插件的长期兼容模式**。

## 如果不改变，后果是什么

- 更多窗口会继续放大 `setMaxListeners(0)`、全局 IPC handler 和 context 清理的复杂度；跨窗口同名事件的隔离会越来越依赖隐含约定。
- 更多第三方插件会让 Electron 主进程成为插件代码、窗口、服务器和本地权限的共同故障域。
- “自动重载”只能解决开发期 reload，不能解决插件死循环、主进程崩溃、CPU/内存失控或恶意系统调用。
- 独立后台功能会继续堆进 `main/index.ts` 和 app lifecycle；启动失败、退出超时、孤儿进程和重启策略会逐渐不一致。
- 未来若突然切换外部 host，可能同时遭遇协议、资产 URL、窗口生命周期、权限和版本兼容问题，回滚成本会显著增加。

## 可验证的渐进迁移路线

1. **先建立基线，不改变运行模式**

   固定测试对象：两个窗口同时使用同名事件、插件 load/unload、widget 资产撤销、MCP/Godot 启停。记录窗口 ID、插件 session ID、module ID、后台进程 ID 和状态变化。

2. **先修稳定的窗口边界**

   要求每个 RPC 请求都能关联到明确窗口实例；窗口关闭时必须清理 context、handler 和 pending request。增加“双窗口同事件名不串线”和“关闭后不能继续调用”的回归测试。

3. **统一后台生命周期语义**

   不急于抽象通用类，先让 server、MCP、Godot 的外部行为都能表达 ready、error、stop timeout、restart 和 owner。验证重复 start/stop、异常退出、应用退出时无残留进程。

4. **选择一个无 UI 的插件做外部 host 试点**

   保持现有 `ExtensionManifestV1`，由宿主策略决定 embedded 或 external，而不是立即修改插件公共 API。可复用 server-runtime/server-sdk 的身份、心跳和重连思路，但仍需补齐 plugin-sdk 的 transport adapter。

   验收条件：

   - 外部插件崩溃不影响主窗口、托盘和主进程；
   - 主进程能检测退出并撤销 session、能力和工具；
   - 重启后能恢复连接而不产生重复 module；
   - 切换回 embedded 不需要迁移用户配置。

5. **再迁移插件 UI**

   外部插件只能发送声明式 widget/module 数据；窗口、iframe、资产 URL 和权限仍由 `WidgetsWindowManager` 管理。插件退出、卸载或 session 失效时，窗口和资产会话必须全部关闭/撤销。

6. **最后再决定是否实现更大抽象**

   只有当仓库实际出现多个外部 transport、多个 stage host 或动态依赖等待需求时，才实现完整的 plugin context factory 和 capability orchestration。否则保留当前较窄、可验证的接口，风险更低。
