## 结论

建议采用“主进程内模块化、按需外置”的渐进方案：

1. 现在稳定窗口、生命周期、插件宿主、后台模块四类边界。
2. 保留当前 Electron 主进程内插件运行方式，但只把它视为“可信/开发插件模式”。
3. 暂不建设完整的通用多传输插件平台、动态窗口 DSL 或统一进程监管器。
4. 当第三方插件需要承受不信任代码、崩溃隔离、资源配额或独立升级时，再将插件执行外置到 Node 子进程。

如果“第三方插件”意味着可安装的任意外部代码，而不是可信开发插件，进程隔离应提前成为硬约束；当前权限模型不能替代进程级安全隔离。

## 现状证据

以下判断基于当前 HEAD `5228f9412`，`git status --short` 为空，本次未修改文件或提交。

- 桌面端是 Electron 应用。`main/index.ts` 在同一个组合根中创建 server channel、HTTP server、Godot、MCP、插件宿主、多个窗口和 tray，窗口依赖也在此集中组装。[main/index.ts](/evaluation-path/treatment/apps/stage-tamagotchi/src/main/index.ts:132)
- 窗口已经存在可复用的公共边界：`setupBaseWindowElectronInvokes`、导航保护和可复用窗口管理器。[window.ts](/evaluation-path/treatment/apps/stage-tamagotchi/src/main/windows/shared/window.ts:134)
- 但各窗口 RPC 仍重复创建 `createContext(ipcMain, window)`，并使用 `setMaxListeners(0)`；代码明确记录这是等待 Eventa 支持 window-namespaced context 的临时方案。[main RPC](/evaluation-path/treatment/apps/stage-tamagotchi/src/main/windows/main/rpc/index.electron.ts:44)、[referenced-window.ts](/evaluation-path/treatment/apps/stage-tamagotchi/src/main/windows/shared/referenced-window.ts:40)
- 插件宿主使用 `ExtensionHost({ runtime: 'electron' })`，最终通过动态 `import(entrypoint)` 加载插件；插件代码与 Electron 主进程处于同一故障域。[plugin host](/evaluation-path/treatment/apps/stage-tamagotchi/src/main/services/airi/plugins/host/index.ts:234)、[FileSystemLoader](/evaluation-path/treatment/packages/plugin-sdk/src/plugin-host/runtimes/node/loaders/fs.ts:72)
- 插件 SDK 已有较好的 manifest、session、permission、binding、cleanup 边界；但多传输设计仍标为 Planned，Node runtime 当前只有 in-memory，WebSocket、worker、Electron transport 仍抛出未实现错误。[multi-transport](/evaluation-path/treatment/packages/plugin-sdk/docs/design/multi-transport.md:150)、[node runtime](/evaluation-path/treatment/packages/plugin-sdk/src/plugin-host/runtimes/node/index.ts:24)
- 插件 UI 当前由宿主的固定 widget registry 加载，扩展 UI 通过 sandbox iframe 和资产服务进入，而不是由插件任意创建 BrowserWindow。[widgets.vue](/evaluation-path/treatment/apps/stage-tamagotchi/src/renderer/pages/widgets.vue:195)
- 后台能力已有三种真实模式：HTTP server 的有序 `start/stop` 管理器、Godot 子进程状态机、MCP stdio 子进程管理器。[server-manager](/evaluation-path/treatment/apps/stage-tamagotchi/src/main/services/airi/http-server/server-manager/types.ts:15)、[Godot](/evaluation-path/treatment/apps/stage-tamagotchi/src/main/services/airi/godot-stage/index.ts:699)
- 历史上，`8893ba81a` 一次修改触及 16 个窗口文件以加固本地服务边界；插件重构 `668440a73` 触及 66 个文件。这说明窗口和插件契约已经是变更放大热点。

## 应该稳定的边界

| 边界 | 建议稳定的内容 | 暂时不要扩大成 |
|---|---|---|
| 应用组合与生命周期 | `main` 只负责组装；每个长期模块明确 start、ready/status、stop、dispose；统一退出顺序 | 通用 service bus 或全局依赖容器重写 |
| 窗口 | 窗口身份、route、preload/security、每窗口 Eventa context、关闭清理 | 覆盖所有窗口差异的万能 WindowManager |
| 插件宿主 | manifest、session、权限、binding、资源会话、卸载清理 | 插件直接拥有 BrowserWindow、preload 或 Electron API |
| 后台模块 | 所有权、生命周期、状态快照、协议、失败和重启语义 | 立即统一 Godot、MCP、HTTP 为同一个大接口 |
| Eventa 契约 | 明确 global/window/plugin-session scope，并保留 `windowId`、`extensionId`、`sessionId`、`requestId` 等关联键 | 继续扩大无作用域的全局频道 |
| 状态 | 区分持久化配置、运行时状态、插件 session、窗口投影 | 跨 renderer 共享隐式 Pinia 状态 |

其中，窗口边界应优先稳定。当前公共窗口服务已经存在，但 RPC 注册和 listener 生命周期仍是重复热点。建议抽象一个只负责“创建窗口上下文、安装公共服务、绑定清理”的 WindowHost 边界，业务窗口管理器继续保留专门职责。

插件宿主也应保持“核心 SDK + Electron adapter”的分层。当前宿主已经有一个值得保留的深模块；但 `tools` 所有权仍隐藏在 built-in kit runtime 中，代码本身也标有 REVIEW，说明工具注册不宜现在继续向更大抽象扩散。[plugin host adapter](/evaluation-path/treatment/apps/stage-tamagotchi/src/main/services/airi/plugins/host/index.ts:435)

## 应该延后的抽象

- 完整的 `PluginTransport` 多运行时体系。设计文档已经存在，但实现尚未具备 WebSocket、worker 和可靠性语义。
- 动态插件窗口、插件自定义路由和菜单系统。先保持“宿主创建窗口，插件贡献受控 UI 模块”。
- 通用进程监管器。Godot 有 ready handshake 和状态机，MCP 更像配置驱动的 stdio 会话，HTTP server 又是有序子服务，过早统一会丢失真实差异。
- 完整 capability orchestration 状态机。当前 capability、resource、permission 已在 SDK 中分散存在，先验证两个以上真实用例再抽象。
- control plane/data plane 的全面拆分。只有出现远程插件、高吞吐流或资源隔离需求时才值得引入。

## 可行方案比较

| 方案 | 质量属性 | 成本与风险 | 回滚路径 |
|---|---|---|---|
| A. 维持现状，仅做局部修补 | 启动性能和短期交付最好；变更局部性、窗口扩展性、插件隔离性较弱 | 当前成本最低，但主进程组合根、重复 RPC、全局 listener 和插件故障域会持续扩大 | 最容易，基本无需迁移 |
| B. 主进程内模块化，按边界渐进迁移（推荐） | 在维护性、测试性、生命周期可靠性和性能之间最均衡；插件仍是可信模式 | 中等成本；需要改造 Eventa context 生命周期、窗口 bootstrap 和后台 ownership，存在短期双轨 | 保留现有 `setupXxx` 作为 adapter；按窗口、按后台逐个切换，可通过 DI/feature flag 恢复旧路径 |
| C. 外置 Plugin Host / 后台进程 | 隔离、崩溃恢复、独立升级和资源治理最好 | 成本最高；需要进程协议、版本协商、超时、取消、重连、日志、打包和跨平台测试。当前 SDK transport 尚未就绪 | 只有在保留 in-process runtime 和版本化 manifest 的前提下才可安全回退 |

### 对方案 A 的判断

适合近期只有少量可信插件、窗口数量增长不快、后台主要是已有服务的情况。

不改变的后果是：

- 每增加一个窗口，都可能继续修改 `main/index.ts`、新增一套 RPC bootstrap，并重复处理 Eventa listener。
- 插件权限仍然只是 API/resource 层面的授权，不能把同进程任意 JS 变成安全沙箱。
- `airiHttpServer` 当前注册的是空 server 列表，而插件资产服务在插件宿主内部单独启动，后台生命周期所有权会继续分散。[main/index.ts](/evaluation-path/treatment/apps/stage-tamagotchi/src/main/index.ts:159)
- 未来切换外置插件宿主时，容易形成一次性大迁移。

### 对方案 B 的判断

这是当前最合理的默认路径：

- 保留 Electron 主进程和 `injeca`。
- 先建立 WindowHost、BackendModule、PluginHost adapter 三个窄边界。
- 插件仍通过现有 manifest/session/permission/binding API 运行。
- 插件 UI 继续由宿主 widget + sandbox iframe 承载。
- 全局插件控制命令保留为 app-scoped；插件事件、窗口事件和 iframe 请求必须带 session/owner/window 作用域。

它不能解决不可信插件的进程级安全问题，但能显著降低更多窗口和后台能力带来的变更放大。

### 对方案 C 的判断

当出现以下任一条件时，应将它升级为目标架构：

- 插件来源不受信任或允许社区任意安装；
- 插件崩溃不能影响主 UI；
- 需要 CPU、内存、文件或网络资源配额；
- 插件需要独立升级、热替换或远程运行；
- 插件数量和运行时间使主进程内泄漏不可接受。

实现时应先做一个 Node 子进程 vertical slice，不要同时实现所有 transport。使用 manifest 的 `node` entrypoint、版本化本地 WebSocket 协议和宿主 adapter；协议必须覆盖 session、capability、requestId、timeout、cancel、degraded/withdrawn 和重启后的新 session identity。

## 建议的渐进迁移路线

| 阶段 | 建议动作 | 验证门槛 | 回滚 |
|---|---|---|---|
| 0. 明确信任模型 | 定义插件是可信开发插件、签名插件还是任意第三方插件；记录窗口数、后台数量、崩溃和内存预算 | 架构决策能明确选择 B 或 C 的触发条件 | 不改变运行时 |
| 1. 窗口 vertical slice | 先选择一个小窗口迁移到统一 WindowHost；公共层复用现有 `setupBaseWindowElectronInvokes` | settings/chat/notice 等两个窗口并行打开时事件不串线；关闭重开无旧 handler；导航保护仍有效 | 继续使用原窗口 setup |
| 2. 后台 vertical slice | 选择一个新增后台或插件资产服务，明确 owner、ready/status、stop 和失败清理 | 重复 start/stop、部分启动失败、应用退出后无残留端口/PID；已有 Godot/MCP 不同时重构 | 旧生命周期注册保留 |
| 3. 插件作用域 | 保留 in-process host，但分离 app-global 控制和 window/session 投影 | 插件 A/B 独立加载、卸载、自动重载；A 的 asset/tool/widget 不残留到 B；两个 renderer 不收到错误事件 | 保留当前全局插件 bridge |
| 4. 外置触发评估 | 若信任或资源要求达到阈值，只外置一种插件 runtime | 杀死插件进程不影响主进程；host 能标记 degraded、回收 session、超时请求并重启 | 按插件选择旧的 Electron runtime |
| 5. 提炼公共抽象 | 只有当两个以上窗口、两个以上后台都重复同一决策时，才把边界提炼为公共包/API | 抽象减少重复且不隐藏生命周期、权限或协议差异 | 删除新 adapter，恢复原模块 |

## 最终决策建议

- 仅增加更多窗口：选择 B 的 WindowHost 和 Eventa 生命周期治理，不需要立即多进程化。
- 增加可信的本地后台：选择 B 的 BackendModule 边界，复用现有 server/Godot/MCP 的生命周期经验。
- 增加不可信第三方插件：以 C 为安全目标；B 只能作为过渡或开发模式。
- 暂时没有明确的信任、资源和远程需求：不要先实现完整多传输插件平台，先用可验证 vertical slice 证明边界。

[EVAL:evolve-software-architecture-loaded]
