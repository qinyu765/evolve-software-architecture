结论：建议采用“边界先行的混合模式”，即方案 B。

可信的内建插件继续运行在 Electron 主进程；用户安装的第三方插件逐步迁移到独立 Node 进程。窗口 UI 继续通过 AIRI 管理的窗口和 sandbox iframe 暴露。现在不宜直接建设完整的远程插件平台或通用运行时内核。

## 1. 范围与置信度

审查基于当前仓库静态结构，桌面入口是 Electron 的 `apps/stage-tamagotchi`，不是旧 Tauri 路径。当前 HEAD 为 `5228f9412`。本次未修改文件、未创建提交，也未运行会产生构建产物的命令。

对现有结构的判断置信度高；对未来规模、威胁模型和插件分发方式的判断属于待确认前提。

## 2. 已观察到的事实

- 主进程已经是组合根：Injeca 注册窗口、插件宿主、Server、MCP、Godot 等模块，最后集中启动和退出。[主进程依赖图](</evaluation-path/treatment/apps/stage-tamagotchi/src/main/index.ts:132>) [退出流程](</evaluation-path/treatment/apps/stage-tamagotchi/src/main/index.ts:328>)

- 窗口已有两种复用模型：单例复用窗口和按 ID 管理的多实例窗口。[单例窗口](</evaluation-path/treatment/apps/stage-tamagotchi/src/main/libs/electron/window-manager/reusable.ts:5>) [按 ID 窗口](</evaluation-path/treatment/apps/stage-tamagotchi/src/main/windows/shared/referenced-window.ts:31>)

- 每个窗口通常创建自己的 Eventa context，但多个 RPC 模块仍需要 `ipcMain.setMaxListeners(0)`；代码明确等待 Eventa 支持 window-namespaced context。[窗口 context](</evaluation-path/treatment/apps/stage-tamagotchi/src/main/windows/shared/referenced-window.ts:40>)

- 当前插件宿主在 Electron 主进程中动态 `import` 插件入口。[插件加载](</evaluation-path/treatment/apps/stage-tamagotchi/src/main/services/airi/plugins/host/index.ts:343>) [文件系统加载器](</evaluation-path/treatment/packages/plugin-sdk/src/plugin-host/runtimes/node/loaders/fs.ts:72>)

- 插件有 manifest、session、module、permission 和 capability 等逻辑边界，但桌面宿主没有传入 `permissionResolver`，默认 grant 是 manifest 声明的权限。[权限解析](</evaluation-path/treatment/packages/plugin-sdk/src/plugin-host/core.ts:249>)

- 插件 UI 已有较清晰的渲染隔离：sandbox iframe、资源服务、按 module/session 关联的消息通道。[插件 iframe](</evaluation-path/treatment/apps/stage-tamagotchi/src/renderer/widgets/extension-ui/components/extension-ui-host.vue:170>) [iframe Eventa 通道](</evaluation-path/treatment/apps/stage-tamagotchi/src/renderer/widgets/extension-ui/composables/use-iframe-message-port.ts:107>)

- Server、MCP、Godot 都已有主进程拥有的生命周期管理器，但语义并不相同：HTTP 强调顺序启停，MCP 管理多个 stdio session，Godot 有进程、ready 握手、超时和 kill fallback。[HTTP manager](</evaluation-path/treatment/apps/stage-tamagotchi/src/main/services/airi/http-server/server-manager/index.ts:19>) [Godot manager](</evaluation-path/treatment/apps/stage-tamagotchi/src/main/services/airi/godot-stage/index.ts:699>)

- 插件 SDK 的多 transport 和 capability orchestration 仍标记为 Planned / Proposed；Node runtime 对 websocket、worker 等 transport 目前会抛出“未实现”。[多 transport 状态](</evaluation-path/treatment/packages/plugin-sdk/docs/design/multi-transport.md:150>) [当前 transport 实现](</evaluation-path/treatment/packages/plugin-sdk/src/plugin-host/runtimes/node/index.ts:24>)

## 3. 当前主要摩擦

1. **主进程依赖图会继续变密。** 新窗口和插件能力都容易直接进入 `main/index.ts` 的 Injeca graph，组合根逐渐知道过多业务细节。

2. **窗口隔离语义还没有成为统一约束。** 目前依靠每个窗口模块自行创建 context、注册 handler、校验 sender 和清理监听器；窗口增多后，跨窗口串 handler、遗漏 cleanup、监听器数量异常的风险会上升。

3. **逻辑权限不是安全边界。** 第三方入口直接加载在 Electron 主进程中，因此插件代码理论上可以使用 Node/Electron 能力。当前 manifest permission 只能约束 AIRI 暴露的 kit/API，不能阻止插件自身访问文件、网络或创建进程。

4. **插件退出路径需要优先审计。** 插件宿主在 `before-quit` 中以 `void hostService.dispose()` 触发异步清理；而 `ExtensionHost.stop()` 才明确清理 session/module。[插件退出注册](</evaluation-path/treatment/apps/stage-tamagotchi/src/main/services/airi/plugins/index.ts:139>) [宿主 dispose](</evaluation-path/treatment/apps/stage-tamagotchi/src/main/services/airi/plugins/host/index.ts:520>) [session cleanup](</evaluation-path/treatment/packages/plugin-sdk/src/plugin-host/core.ts:547>)  
   这不等于已经确认存在泄漏，但说明关闭顺序和所有权还没有完全统一。

5. **协议类型存在重复边界。** 桌面 shared Eventa 中仍手工复制插件 capability/session 类型，并留下了待替换注释。[重复类型](</evaluation-path/treatment/apps/stage-tamagotchi/src/shared/eventa/index.ts:218>)  
   wire-level 类型应有唯一的中立所有者，现有 `@proj-airi/plugin-protocol/types` 比 app-local 类型更适合承担这个角色。

## 4. 应优先保证的质量属性

排序建议：

1. 第三方插件的信任边界与故障隔离；
2. 窗口 IPC 不串线、后台进程不残留、退出顺序可证明；
3. 插件 API 和协议的可演进性；
4. 可观测性：extensionId、sessionId、moduleId、requestId、状态和退出原因；
5. 启动时间、内存和开发体验；
6. 改造成本与可回滚性。

需要明确的最低约束是：

- 一个插件崩溃不能拖垮主窗口；
- 一个窗口关闭不能留下它的 IPC handler；
- 一个插件 session 停止必须撤销其 module、asset、tool 和 UI binding；
- 应用退出必须等待实际拥有资源的 manager 完成 stop；
- 未授权的插件调用必须在 host boundary 被拒绝；
- 不允许通过“失败后静默切回主进程执行”绕过隔离策略。

## 5. 可行方案比较

| 方案 | 适用性与质量属性 | 成本与风险 | 回滚 |
|---|---|---|---|
| A. 维持现状：插件嵌入主进程，继续增加窗口 manager | 延迟低、开发简单、现有测试和调试路径稳定；但第三方安全性和故障隔离弱，扩展性逐渐下降 | 近期成本低；长期主进程耦合、IPC 重复和退出风险会非线性增加 | 最容易，完全保留当前路径 |
| B. 混合执行：可信插件嵌入，第三方插件使用独立 Node 进程 | 主进程故障隔离明显改善，插件可独立重启；保留现有 manifest、kit、session、iframe UI | 中等到偏高；需要进程生命周期、协议版本、超时、认证、资源撤销和打包支持。独立 Node 进程仍不是 OS 安全沙箱，不能单独满足恶意代码防护 | 按插件或运行模式回退到嵌入式路径；保留旧路径，不迁移已有状态 |
| C. 完整插件平台：所有第三方插件外置/远程，控制面、数据面、版本协商、签名、安装器、OS sandbox 一并建设 | 长期可扩展性和多宿主能力最好；若真正加入 OS sandbox，安全性最高 | 成本最高，且当前 transport、capability registry 和可靠性语义仍未完成；容易提前锁死协议和运维模型 | 困难，需要长期维护双协议和兼容宿主 |

方案 A 只适合“插件是可信的、开发者本地安装的、不会被当作安全边界”的产品阶段。只要第三方意味着用户下载的任意 JS，方案 A 不应继续作为最终架构。

## 6. 推荐的稳定边界

建议采用 B，但只先做它的窄化版本：

```text
Electron main
├─ 窗口生命周期与窗口级 Eventa adapter
├─ 可信插件 host，或外部插件进程 supervisor
└─ Server / MCP / Godot 等领域 manager

Renderer ── scoped IPC/Eventa ──> main
Plugin UI ── sandbox iframe / message transport ──> renderer host
```

现在应该稳定：

- **所有权边界**：主进程负责窗口、OS 资源和外部进程；插件 host 负责 manifest/session/module/capability；后台 manager 负责自己的协议和生命周期；renderer 不直接 spawn 进程或拥有 Electron 对象。

- **窗口身份边界**：统一表达 `windowKind + instanceId + webContentsId`，每个窗口 context 有明确创建、绑定、销毁语义。继续复用现有 `createReusableWindow` 和 `createReferencedWindowManager`，暂不建设一个全能动态 Window Kernel。

- **插件 wire contract**：稳定 `extensionId`、`sessionId`、`moduleId`、`requestId`、capability 状态和 owner 关系。中立的协议类型应集中到 `plugin-protocol`，桌面 shared Eventa 只保留桌面窗口特有 envelope。

- **后台 manager 的最小契约**：按需提供 `start`、`stop`、`status`、`subscribe`；只有确实具备一致语义时才提供 `restart`。不要把 HTTP、MCP、Godot 强行塞进同一个通用抽象。

- **插件 UI 边界**：继续由 AIRI 创建 widget/iframe、资源 URL 和消息通道；暂不允许插件自行创建任意 privileged `BrowserWindow`。

## 7. 建议延后的抽象

- 完整的多 transport factory、远程插件目录和跨设备插件联邦；
- 所有后台能力共用的“运行时内核”或通用 supervisor；
- capability dependency graph、`waiting-deps` 全状态机；
- 统一的插件安装、签名、升级和 marketplace；
- 用 worker 代替进程作为安全隔离方案；
- 一次性重写所有窗口为新的动态注册中心。

原因是这些方向在仓库设计文档中仍处于 Planned / Proposed，当前实现还不足以证明协议、可靠性和运维语义。窗口级 context、session identity 和资源撤销是现在已有真实压力的边界；完整平台则应由实际插件数量、崩溃数据和分发需求驱动。

## 8. 可验证的渐进迁移路线

1. **建立决策前基线**

   明确第三方插件是“可信本地包”“用户安装包”还是“可能恶意的 marketplace 包”，并记录是否要求真正的机密性/文件访问隔离。建立窗口、插件 session、后台进程三张 ownership 表，以及启动耗时、插件失败、进程退出和 listener 数量基线。

   退出条件：每个现有窗口、插件资源和后台进程都能找到唯一 owner。

2. **先收敛窗口 IPC**

   先在一个已有多实例窗口族上引入窗口级生命周期 adapter；保留当前 Eventa 事件名，增加稳定窗口身份、sender 校验、handler cleanup 和关闭订阅。优先覆盖 referenced window 或 widgets，不要同时重写所有窗口。

   验证：

   - 两个窗口使用同名事件时不会互相处理；
   - 关闭窗口后 handler 和订阅全部消失；
   - 并发打开同一窗口只得到一个实例；
   - 重复打开/关闭不会造成 listener 数量增长。

3. **做一个外部插件垂直切片**

   为插件增加显式、版本化的执行策略：`embedded` 或 `external`。可信插件保持现状；第三方插件不能静默回退到 embedded。

   选一个现有 tool/gamelet 场景，验证外部 Node 进程、host-owned session、请求关联、超时、退出、资源撤销和 iframe UI，不先实现所有 transport。

   验证：

   - 杀死插件进程不会影响主窗口；
   - 插件只能调用已授予的 host capability；
   - session 停止后 tool、asset、widget binding 均不可用；
   - 协议版本不匹配能产生确定性失败；
   - 插件失败时主进程不自动以更高权限重试。

4. **统一后台退出语义**

   让插件 host、MCP、Godot 和其他真正拥有外部资源的 manager 都进入同一个可等待的退出协调路径。先修正所有权和顺序，再考虑抽取共享 process primitive；HTTP 的顺序启停仍保留自己的领域实现。

   验证：

   - app quit 等待所有外部进程停止；
   - ready 超时、异常退出和重复 start/stop 都有确定状态；
   - 窗口关闭只取消窗口订阅，不停止仍被其他窗口使用的后台能力；
   - 不留下 stale PID、socket 或 asset session。

5. **有规模证据后再扩展**

   当出现多个插件进程、多个 stage 实例、跨机器插件或真实第三方分发需求后，再引入 heartbeat/backpressure、版本协商、hostId/instanceId capability registry、签名和 OS sandbox。

每一步都应保留旧路径，使单个插件或单类窗口可以独立回滚，而不是进行一次全仓库迁移。

## 9. 不改变的后果

继续维持当前结构不会立即阻塞开发，且能保留低延迟和较低复杂度；但后果是：

- 第三方插件继续与主进程共享崩溃和高权限边界；
- 更多窗口会放大 context、listener 和 cleanup 的重复代码；
- 更多后台能力会形成不同的启动、重试和退出惯例；
- 主进程组合根会成为插件、窗口和后台能力的共同变更点；
- 未来若突然要求 marketplace 安全隔离，迁移成本会远高于现在保留双轨执行模式。

## 10. 仍需确认的决策

最影响方案选择的是：

- 第三方插件是否允许访问任意本地文件和网络；
- 是否必须抵抗恶意插件，而不只是隔离崩溃；
- 是否需要远程/跨设备插件；
- 预计同时运行多少插件、窗口和后台进程；
- 后台能力是否需要自动重启、持久 session 或 native dependency。

在这些问题明确前，B 是风险、成本和可回滚性最平衡的选择；C 应作为触发式演进目标，而不是当前默认架构。

[EVAL:evolve-software-architecture-loaded]
