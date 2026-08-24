## 结论

建议采用“方案 A 过渡、方案 B 目标、方案 C 设门槛”的路线：

- 近期保留插件宿主在 Electron 主进程中的形态，但先稳定身份、权限、生命周期、窗口 IPC 和资源所有权边界。
- 一旦插件面向不完全信任的第三方，迁移到“主进程协调器 + 每插件独立进程”的方案 B。
- 只有在“窗口关闭后后台仍需持续运行、多个客户端连接或跨设备协同”成为明确需求时，再引入独立 AIRI 后台进程方案 C。
- 暂不构建统一窗口注册表、完整能力依赖图、全传输插件上下文或通用后台进程监管器。

本次检查只读，工作区没有文件变更或提交。

## 当前结构说明

AIRI 当前的桌面主进程已经承担较多全局职责：server channel、内置 HTTP server、Godot、MCP、widgets、plugin host 以及多个窗口都在 `injeca` 中组合和管理。[main/index.ts](/evaluation-path/control/apps/stage-tamagotchi/src/main/index.ts:154)

当前插件宿主位于 Electron main，并直接创建 `ExtensionHost({ runtime: 'electron' })`。[host/index.ts](/evaluation-path/control/apps/stage-tamagotchi/src/main/services/airi/plugins/host/index.ts:224) 入口文件通过动态 `import(entrypoint)` 加载。[fs.ts](/evaluation-path/control/packages/plugin-sdk/src/plugin-host/runtimes/node/loaders/fs.ts:72)

因此可以推断：当前插件入口代码属于主进程的信任域。Manifest permission 能约束 SDK kit/API，但不能替代 Node/Electron 的进程级隔离；而当前 host 没有传入 `permissionResolver`，未解析时直接以 manifest permissions 作为 grant。[core.ts](/evaluation-path/control/packages/plugin-sdk/src/plugin-host/core.ts:249)

窗口方面，已有共享的 per-window Eventa context 和 `ReferencedWindowManager`，但各类窗口仍高度专用化；代码也明确以 `setMaxListeners` 临时缓解窗口命名空间问题。[window.ts](/evaluation-path/control/apps/stage-tamagotchi/src/main/windows/shared/window.ts:134)、[referenced-window.ts](/evaluation-path/control/apps/stage-tamagotchi/src/main/windows/shared/referenced-window.ts:40)

插件 UI 已有 iframe、消息端口和带 cookie 授权的静态资源服务边界。[extension-ui-host.vue](/evaluation-path/control/apps/stage-tamagotchi/src/renderer/widgets/extension-ui/components/extension-ui-host.vue:105)、[route.ts](/evaluation-path/control/apps/stage-tamagotchi/src/main/services/airi/http-server/static-assets/route.ts:29)。这适合承载第三方 UI，但不应被误认为能隔离运行在 main 中的插件代码。

## 应该现在稳定的边界

1. **插件身份和所有权**

   稳定 `ExtensionManifestV1`、extension id、session id、module id，以及 binding/tool/asset 的 owner session。当前 host 已经以 session 为单位做绑定清理和静态资源撤销，这是正确的方向。[host/index.ts](/evaluation-path/control/apps/stage-tamagotchi/src/main/services/airi/plugins/host/index.ts:343)

2. **权限和能力由 Host 控制**

   插件只能通过 typed kit/API 访问能力，不应拿到 `ipcMain`、BrowserWindow 或任意 Electron service。稳定“请求权限、实际 grant、撤销、session 清理”的语义；暂不冻结完整能力依赖图。

3. **两类 IPC 边界分开**

   - 桌面窗口 IPC：由 app-local Eventa contract 管理，按窗口或实例隔离。
   - 插件跨进程/跨网络协议：由 `plugin-protocol`/SDK 管理。

   当前 `shared/eventa` 中已经出现手工复制的 capability 类型，并注明未来应从 SDK 重导出。[eventa/index.ts](/evaluation-path/control/apps/stage-tamagotchi/src/shared/eventa/index.ts:218) 这说明跨边界类型归属仍应整理，但不宜继续扩大 app-local 插件协议。

4. **UI 贡献使用 iframe，而不是直接创建特权窗口**

   iframe、消息端口、静态资源 session 和撤销机制可以作为 UI 插件边界。第三方若需要独立窗口，应经过显式的 window capability；不要让插件自行创建带共享 preload 的 `BrowserWindow`。当前主窗口仍使用 `sandbox: false`，[main/index.ts](/evaluation-path/control/apps/stage-tamagotchi/src/main/windows/main/index.ts:88)，而导航保护函数也假定内容是 AIRI 控制的 renderer。[window.ts](/evaluation-path/control/apps/stage-tamagotchi/src/main/windows/shared/window.ts:41)

5. **后台能力统一生命周期语义，不急于统一实现**

   Godot、MCP、server channel 都应至少具备：

   `start / stop / restart / status / health / subscribe / dispose`

   并携带 `ownerId`、`instanceId`、PID 或连接标识、错误原因和幂等行为。当前 Godot 已有较完整的 start/stop/status 接口，[godot-stage/index.ts](/evaluation-path/control/apps/stage-tamagotchi/src/main/services/airi/godot-stage/index.ts:123)，但 MCP 和 server channel 仍各自管理生命周期。

## 应该延后的抽象

- **完整的跨传输 `createPluginContext`**：设计文档已提出 per-plugin context，但状态仍是 Planned；Node runtime 目前只有 in-memory，WebSocket、node-worker、Electron transport 明确抛出未实现。[multi-transport.md](/evaluation-path/control/packages/plugin-sdk/docs/design/multi-transport.md:150)、[node/index.ts](/evaluation-path/control/packages/plugin-sdk/src/plugin-host/runtimes/node/index.ts:24)

- **完整 capability dependency graph**：现有 `DependencyService` 是按 key 的内存状态和等待器；支持 announce/ready/degraded/withdraw，却不是带 host、stage instance、predicate 的完整图。[dependencies.ts](/evaluation-path/control/packages/plugin-sdk/src/plugin-host/runtimes/shared/services/dependencies.ts:16) 对应设计文档状态仍为 Proposed。[capability-orchestration.md](/evaluation-path/control/packages/plugin-sdk/docs/design/capability-orchestration.md:182)

- **统一窗口注册表或通用插件窗口 DSL**：当前窗口包含透明 overlay、设置、聊天、隐藏音频窗口、devtools 等不同生命周期。应先稳定 manager/context/cleanup，不要用一个 descriptor 抹平所有差异。

- **通用后台进程 supervisor**：先保留 Godot、MCP、server channel 的适配器；只有当进程数量、重启策略和资源配额重复到足以形成稳定政策时，才抽取 supervisor。

- **Marketplace、安装、签名、更新协议**：第三方插件最终需要，但当前仓库证据主要是本地 `$userData/extensions/v1` 的发现、启用和加载，不足以证明分发模型已经确定。应先决定信任模型，再冻结安装和签名协议。

## 方案比较

| 方案 | 形态 | 质量属性 | 成本与风险 | 回滚 |
|---|---|---|---|---|
| A. 维持现状并加固 | 插件继续嵌入 Electron main；UI 使用 iframe | 延迟最低、调试最简单；主进程故障域最大，不能真正承载不可信第三方代码 | 成本最低；风险是插件阻塞/崩溃/内存泄漏影响整个桌面应用 | 直接禁用、unload、关闭 auto-reload；现有接口无需迁移 |
| B. 混合宿主，推荐目标 | main 保留 registry、权限、窗口和资源 broker；每个第三方插件运行在独立 Node child process，使用 Eventa/protocol 通信 | 隔离性、故障恢复和长期演进明显更好；有本地 RPC 延迟和连接管理成本 | 中高成本：进程启动、认证、heartbeat、版本协商、崩溃回收、打包和调试 | 每插件选择 `embedded/external`；外部 canary 失败可退回嵌入模式。对不可信插件不应自动降级到 main |
| C. 独立 AIRI 后台 daemon | 插件 Host/server runtime 独立运行，Electron 只是 viewer/control client | 最适合窗口关闭后继续运行、多窗口、多设备和后台任务；网络、认证、端口和升级复杂度最高 | 成本最高；需要 daemon 安装/启动、连接恢复、单实例租约、数据迁移 | 保留 B/A 作为本地 fallback；现有 server channel 已提供部分 WebSocket 和重启回滚基础 |

A、B、C 其实都与仓库设计文档中的 embedded、external Node、remote host 三种部署模式一致。[architecture.md](/evaluation-path/control/packages/plugin-sdk/docs/design/architecture.md:167) 但 B/C 所需的 transport 和可靠性语义目前还没有完整实现，因此不应直接大规模切换。

## 如果什么都不改变

继续增加窗口、插件和后台能力而不稳定边界，会产生四类后果：

- 第三方插件继续和 main 共处一个故障域，Manifest permission 会被误当成安全沙箱。
- 更多窗口会放大当前全局 listener、窗口 context 和 cleanup 问题；`setMaxListeners(0/100)` 只能掩盖泄漏，不能解决隔离。
- Godot、MCP、server runtime 各自拥有生命周期，未来难以统一展示“谁启动、谁拥有、谁重启、谁负责退出”。
- 一旦以后再引入独立 Host，会同时迁移插件 API、窗口 API、资源 URL、权限模型和调试工具，回滚成本显著增加。

## 可验证的渐进路线

1. **先做边界基线，不改变运行模式**

   用现有 plugin debug snapshot、load/unload/inspect、asset session 机制验证：

   - 插件 reload 后无残留 session、binding、tool、asset session。
   - 两个插件之间没有 Eventa invoke 串扰。
   - 重复打开/关闭同一窗口不会持续增加 listener。
   - app 退出时所有 sidecar 都能进入 stopped。

2. **稳定协议和所有权**

   冻结 manifest、extension/session/module identity、owner session、权限 grant/revoke、资源撤销和错误 envelope。窗口协议继续保持 app-local；跨进程协议统一使用 `plugin-protocol`。这一阶段不实现 worker 或 daemon。

3. **引入一个外部 canary**

   以现有 devtools sample plugin 为测试对象，新增外部进程宿主适配器，但不改变插件 API。必须验证：

   - child process 被杀死时 Electron 主窗口仍可用。
   - 仅该插件的 session、binding、asset session 被撤销。
   - 重复启动、超时、异常退出、重复消息都有确定结果。
   - 主进程记录 plugin id、session id、transport、phase、错误原因。

4. **按信任级别逐步切换**

   - 内置或明确可信插件：允许 embedded。
   - 第三方插件：默认 external process。
   - 不对不可信插件提供自动 embedded fallback。
   - 保留现有 enable/load/unload 路径作为运营回滚入口。

5. **满足后台独立条件后再推进 C**

   只有当“窗口关闭仍需运行”“多个 viewer”“跨设备连接”成为硬需求时，才把 Host/server runtime 提升为独立 daemon。迁移时复用现有协议事件中的认证、announce、兼容性协商和 capability 生命周期，而不是再造一套窗口专用协议。[events.ts](/evaluation-path/control/packages/plugin-protocol/src/types/events.ts:642)

此外，无论是否引入 daemon，都必须保留当前“单一进程拥有本地资源和固定端口”的约束；现有 single-instance guard 已明确说明这一点。[single-instance.ts](/evaluation-path/control/apps/stage-tamagotchi/src/main/app/single-instance.ts:33)
