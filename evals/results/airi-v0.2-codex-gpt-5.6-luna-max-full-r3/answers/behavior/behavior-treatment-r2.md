## 1. 范围与置信度

评审范围是 `apps/stage-tamagotchi` Electron 桌面端，以及相关的 `plugin-sdk`、`plugin-protocol`、窗口和后台服务。基于当前 HEAD `5228f9412` 的源码、设计文档、测试文件和 Git 历史进行只读检查。

本轮未修改文件、未创建提交，也未运行测试或构建。当前结构判断置信度高；未来插件是否“不受信任”、后台是否要脱离 UI 持续运行，仍是未知决策。

## 2. 观察到的事实

| 事实 | 证据与含义 |
|---|---|
| 主进程是主要运行时编排者 | `main/index.ts` 通过 `injeca` 注册窗口、插件宿主、MCP、Godot、server channel、tray 等模块，并统一处理退出流程。[main/index.ts:132](/evaluation-path/treatment/apps/stage-tamagotchi/src/main/index.ts:132) |
| 窗口数量已经不少 | 当前有约 14 个具体窗口目录；共享基础 IPC、可复用窗口和按 ID 管理窗口已经存在。[window.ts:134](/evaluation-path/treatment/apps/stage-tamagotchi/src/main/windows/shared/window.ts:134)、[referenced-window.ts:31](/evaluation-path/treatment/apps/stage-tamagotchi/src/main/windows/shared/referenced-window.ts:31) |
| 窗口隔离仍有基础设施压力 | 多处通过 `ipcMain.setMaxListeners(0)` 绕过监听器上限，并注明等待 Eventa 支持 window-namespaced context。[referenced-window.ts:40](/evaluation-path/treatment/apps/stage-tamagotchi/src/main/windows/shared/referenced-window.ts:40) |
| Renderer 以路由决定窗口角色 | 非 spotlight 窗口都会创建较完整的 stage runtime，再通过 `/chat`、`/settings`、`/widgets` 等路由跳过部分初始化。[App.vue:79](/evaluation-path/treatment/apps/stage-tamagotchi/src/renderer/App.vue:79) |
| 当前插件宿主运行在 Electron 主进程 | 桌面端创建 `ExtensionHost({ runtime: 'electron' })`；文件加载器直接动态 `import` 扩展入口。[host/index.ts:224](/evaluation-path/treatment/apps/stage-tamagotchi/src/main/services/airi/plugins/host/index.ts:224)、[fs.ts:72](/evaluation-path/treatment/packages/plugin-sdk/src/plugin-host/runtimes/node/loaders/fs.ts:72) |
| 插件权限目前是能力控制，不是进程安全边界 | SDK 有 extension/session/module/permission/cleanup 模型，但动态导入的第三方主插件仍与主进程同进程。[core.ts:235](/evaluation-path/treatment/packages/plugin-sdk/src/plugin-host/core.ts:235) |
| UI 插件已有独立边界 | 插件 UI 通过 iframe、sandbox、loopback 静态资源服务和 cookie-backed asset session 加载。[extension-ui-host.vue:105](/evaluation-path/treatment/apps/stage-tamagotchi/src/renderer/widgets/extension-ui/components/extension-ui-host.vue:105) |
| 独立后台已有两个真实样本 | MCP 通过 stdio 管理外部进程；Godot 有 readiness、状态机、超时、停止和强制 kill。[mcp-servers/index.ts:151](/evaluation-path/treatment/apps/stage-tamagotchi/src/main/services/airi/mcp-servers/index.ts:151)、[godot-stage/index.ts:699](/evaluation-path/treatment/apps/stage-tamagotchi/src/main/services/airi/godot-stage/index.ts:699) |
| 多传输插件架构还不是可用事实 | `plugin-sdk` 当前 Node runtime 只实现 in-memory，WebSocket、worker、Electron transport 明确抛出未实现；设计文档状态为 Planned。[node/index.ts:24](/evaluation-path/treatment/packages/plugin-sdk/src/plugin-host/runtimes/node/index.ts:24)、[multi-transport.md:150](/evaluation-path/treatment/packages/plugin-sdk/docs/design/multi-transport.md:150) |

## 3. 当前主要摩擦

1. **插件信任边界不清晰。**  
   [推断] 如果未来第三方插件来自下载、市场或不受信任作者，当前主进程动态加载会让插件故障、任意 Node API 访问和主进程崩溃处于同一故障域。SDK 的 permission 不能替代 OS/process sandbox。

2. **窗口边界已经重复实现，但身份模型还不够显式。**  
   当前依赖 route、`webContents.id`、请求 ID 和多个局部 manager。窗口继续增加后，跨窗口串消息、销毁后残留订阅、重复初始化会成为主要风险。

3. **主进程编排图会继续膨胀。**  
   `main/index.ts` 同时连接窗口、插件、后台服务和 tray；当前退出时还并行执行 app hooks 与 `injeca.stop()`。[main/index.ts:301](/evaluation-path/treatment/apps/stage-tamagotchi/src/main/index.ts:301)  
   [推断] 模块越多，启动顺序、停止顺序、失败可见性和依赖方向越容易依赖隐式约定。

4. **已有后台实现很有价值，但还不是统一抽象。**  
   Godot 是单个带 WebSocket readiness 的 sidecar，MCP 是多个 stdio session；它们可以验证生命周期设计，但现在直接抽象成“万能后台服务”会隐藏差异。

## 4. 质量属性优先级

| 优先级 | 质量属性 | 应达到的目标 |
|---|---|---|
| P0 | 信任与故障隔离 | 不受信任插件崩溃或超时不能拖垮主窗口和主进程 |
| P0 | 生命周期正确性 | 窗口销毁、插件卸载、应用退出、后台异常退出均可清理，不留孤儿进程或失效订阅 |
| P1 | 协议稳定性 | Eventa 请求、事件、错误、相关 ID、session/owner 身份可版本化 |
| P1 | 可扩展性与局部性 | 增加一个窗口或插件时，不需要修改大量无关主进程 wiring |
| P1 | 可测试性与可观测性 | 可用 fake runtime 测试超时、拒绝、重启和跨窗口隔离 |
| P2 | 性能与资源 | 能测量每个 renderer、iframe、插件进程的启动时间、内存和 CPU 成本 |

## 5. 可行方案比较

| 方案 | 结构 | 优点 | 成本与风险 | 回滚路径 |
|---|---|---|---|---|
| A. 维持现状并局部加固 | 主进程继续承载受信任插件；保留显式窗口 manager、`injeca`、Godot/MCP sidecar | 成本最低；贴合当前代码；调试路径短 | 不适合不受信任第三方插件；窗口和后台生命周期会继续分散；主进程仍是大故障域 | 最容易，基本无需迁移 |
| B. 分层演进，主进程作为控制平面（推荐） | 主进程保留 OS/窗口/生命周期所有权；插件协议、窗口实例、后台 runtime 先形成窄契约；仅将需要隔离的插件逐步移出进程 | 兼顾渐进性、可回滚性和未来隔离；复用现有 Eventa、Godot、MCP、iframe 边界 | 中等成本；需要协议版本、握手、超时、日志和 feature flag；短期会同时维护 trusted/external 两种 runtime | 保留 in-process adapter；按插件或配置关闭 external mode |
| C. 立即建设独立 Plugin Host/Daemon + 动态窗口平台 | Electron 仅做控制平面；插件默认独立进程/远程运行；窗口由插件动态贡献；多传输统一协议 | 隔离、后台独立运行、第三方生态扩展能力最好 | 成本最高；当前 SDK transport 尚未实现；需要升级、重连、权限、签名、崩溃恢复、诊断和兼容矩阵 | 困难；需要长期保留旧宿主或完成协议双栈 |

推荐 B。若“第三方”明确表示可下载且不受信任，则应把 B 的外置进程阶段视为安全前置条件，而不是可选优化。

## 6. 应稳定的边界

稳定的是所有权、身份和契约，不是现在就创建一套庞大的抽象类。

- **主进程边界**：主进程拥有 Electron、OS 权限、窗口、userData、子进程和应用生命周期。
- **窗口实例边界**：每个窗口至少有 `windowRole + windowInstanceId`，manager 负责创建、显示、焦点、销毁、持久化、Eventa context 和清理。
- **插件宿主边界**：宿主拥有 manifest、extension session、module、permission、capability、asset session 和卸载清理。插件 API 不应暴露 `BrowserWindow`、Pinia store 或 Electron 对象。
- **后台 runtime 边界**：统一生命周期语义即可：`start -> ready/running -> stopping/stopped/error`，并包含 owner、状态、健康、超时和资源清理；不要先统一内部协议。
- **协议边界**：共享 Eventa 契约应承载版本、请求 ID、来源身份、目标身份、结构化错误和取消/超时语义。
- **插件 UI 边界**：继续保持 iframe + 资源会话 + 结构化数据桥接；UI 和主进程插件逻辑应有不同信任等级。

## 7. 应延后的抽象

- 全局 `ApplicationKernel`、第二套 service container 或万能 registry；当前 `injeca` 已经承担组合职责。
- 完整多传输插件平台；当前文档仍是 Planned，实际 runtime 只有 in-memory。
- 通用动态窗口注册中心；至少等两个真实的、独立开发的插件窗口贡献证明共同生命周期确实稳定。
- “万能 sidecar supervisor”；先围绕 Godot 或 MCP 做一个窄 adapter，等第三种 runtime 出现再决定抽象范围。
- Marketplace、安装器、签名、自动升级和远程联邦；除非产品确定要分发不受信任插件。
- 把所有 renderer 状态迁移到后台中心；当前 Pinia、BroadcastChannel、main service 各自有合理局部性。

## 8. 可验证的渐进迁移路线

1. **建立基线与决策记录**  
   明确 trusted / untrusted 插件、窗口关闭后后台是否继续运行、支持的 OS 和资源预算。记录当前窗口启动时间、内存、插件加载时间和退出耗时。  
   验收：每种运行时都有明确 owner、生命周期和故障矩阵。

2. **先稳定协议，不移动运行位置**  
   在现有 `shared/eventa` 和插件 SDK 边界上补齐版本、请求 ID、窗口/插件/session 身份和结构化错误。  
   验收：测试两个窗口无串话、错误来源窗口被拒绝、旧请求在销毁后被丢弃、权限拒绝可观察。现有 `plugin-sdk`、`stage-window-lifecycle`、`iframe-request` 测试可作为边界测试入口。

3. **选择一个窗口做实例化试点**  
   优先选择已有 ID、iframe 请求和重建逻辑的 widgets，或选择 settings 这种可复用窗口。保持 BrowserWindow 和路由不变，只明确 `WindowRole/WindowInstance` 生命周期。  
   验收：重复打开、关闭重建、两个实例同时存在、renderer 崩溃后重新绑定均不产生跨实例事件。失败时删除该 facade 即可回到现有 manager。

4. **选择一个后台实现做 lifecycle adapter**  
   先包裹 Godot 或 MCP，不改变其内部实现。用 fake process/socket 覆盖启动超时、异常退出、停止超时、重启、应用退出和无孤儿进程。  
   验收：失败不会卡住主进程退出；状态、PID、runtime ID 和错误可观测；adapter 关闭后仍可回退到原 manager。

5. **做一个外置插件的垂直切片**  
   选择不依赖 Electron API 的非关键插件。保留现有 in-process 路径，通过配置或 feature flag 启用 child-process runtime；协议只实现这一条真实路径，不提前承诺所有 transport。  
   验收：插件进程崩溃不影响主进程；请求超时可回收；权限拒绝有效；插件可单独重启；UI iframe 的 session 会随插件 session 撤销。任何失败都能切回 in-process adapter。

6. **只有证据充分时再建设独立 Daemon 和动态窗口平台**  
   触发条件应包括：不受信任插件成为正式需求、需要无窗口后台运行、需要独立发布/升级、已有多个不同 runtime、或测量显示主进程资源和崩溃隔离已成为瓶颈。此时再落实 WebSocket/worker transport、协议协商、心跳、背压、重连和版本兼容。

## 9. 不改变的后果

如果长期维持当前形态：

- 不受信任插件会与主进程共享故障和权限边界，现有 permission UI 容易造成“看似安全”的错觉。
- 更多窗口会放大 route-based runtime 分支、重复 renderer 初始化、Eventa listener 管理和跨窗口串话风险。
- 更多后台能力会继续各自注册退出 hook、状态机和清理逻辑，最终形成难以验证的启动/停止顺序。
- 若现在不固定协议身份和错误语义，未来外置插件或远程后台会被迫重新定义一套兼容协议。

## 10. 需要产品先决定的问题

这些问题会直接改变推荐方案：

- 第三方插件是“用户自行安装的受信任代码”，还是“市场/网络下载的不受信任代码”？
- 所有窗口关闭后，后台是否仍必须运行？
- “更多窗口”是固定的 AIRI 窗口，还是插件可任意创建的窗口？
- 是否需要插件独立升级、跨版本兼容、签名和回滚？
- 可接受的插件启动时间、内存、CPU 和主进程崩溃隔离目标是多少？

[EVAL:evolve-software-architecture-loaded]
