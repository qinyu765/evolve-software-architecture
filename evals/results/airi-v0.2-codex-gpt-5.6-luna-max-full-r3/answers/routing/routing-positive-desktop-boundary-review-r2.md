## 结论

基于当前 HEAD `5228f9412`，工作区干净；本次仅做了只读检查，未修改文件或提交。

AIRI 桌面端已有可持续演进的骨架：main 使用 `injeca` 组合服务，窗口代码已经部分采用按窗口创建 Eventa context，插件也有 session、owner、资源撤销和生命周期测试。

但当前边界还不够严格。长期风险主要集中在：

1. 全局 IPC 与窗口级 IPC 混用。
2. preload 暴露了原始 `electronAPI/ipcRenderer`。
3. renderer 根组件承担了所有窗口的启动编排。
4. Electron 依赖和协议类型渗入共享 package。
5. 插件代码当前直接动态加载进 Electron main，尚未形成进程隔离。

因此不建议重写桌面应用；建议保留 Electron、Eventa 和 `injeca`，逐步增加明确的窗口会话、能力桥接和可替换的 Plugin Host。

## 当前边界评估

| 边界 | 可检查事实 | 评价 |
|---|---|---|
| main | 根入口通过 `injeca` 组装窗口、插件、server、MCP、Godot 等服务。[main/index.ts](/evaluation-path/treatment/apps/stage-tamagotchi/src/main/index.ts:130) | 模块化基础较好，但 composition root 仍知道过多业务和窗口依赖。 |
| IPC | 插件与 server channel 使用 `createContext(ipcMain)`，没有在调用点绑定 BrowserWindow。[plugins/index.ts](/evaluation-path/treatment/apps/stage-tamagotchi/src/main/services/airi/plugins/index.ts:47)、[channel-server/index.ts](/evaluation-path/treatment/apps/stage-tamagotchi/src/main/services/airi/channel-server/index.ts:451) | 应用侧没有显式区分 app-scoped 与 window-scoped API。 |
| 窗口 | widgets 等服务已检查 sender 是否属于目标窗口。[widgets service](/evaluation-path/treatment/apps/stage-tamagotchi/src/main/services/airi/widgets/index.ts:33) | 有正确方向，但安全/隔离策略分散在各个窗口服务中。 |
| preload | 标准 preload 暴露整个 `electronAPI`，其中包含 `ipcRenderer`。[preload/shared.ts](/evaluation-path/treatment/apps/stage-tamagotchi/src/preload/shared.ts:8) | 代码很薄，但权限面很宽；`exposeWithCustomAPI` 已存在却未成为默认入口。 |
| renderer | `App.vue` 根据 route 初始化插件、MCP、Godot、server channel、chat 等多个 runtime。[App.vue](/evaluation-path/treatment/apps/stage-tamagotchi/src/renderer/App.vue:79) | 多窗口目前是“同一 renderer + route 分支”，新增窗口类型会继续增加条件分支。 |
| shared package | `stage-ui` 的部分代码仍直接创建 Electron renderer Eventa context。[artistry-autonomous.ts](/evaluation-path/treatment/packages/stage-ui/src/stores/modules/artistry-autonomous.ts:34) | 共享 UI 并非完全 runtime-neutral；不过 plugin debug store 已采用注入 bridge，是值得推广的模式。[plugin-host-debug.ts](/evaluation-path/treatment/packages/stage-ui/src/stores/devtools/plugin-host-debug.ts:81) |
| 协议 | app-local `shared/eventa` 同时定义 Electron IPC、widget DTO 和插件 DTO，并明确存在重复类型 TODO。[shared/eventa/index.ts](/evaluation-path/treatment/apps/stage-tamagotchi/src/shared/eventa/index.ts:204) | 协议 ownership 分散，长期容易出现 SDK、stage-ui、desktop app 类型漂移。 |
| 插件 | Electron host 使用 `runtime: 'electron'`，entrypoint 由 `FileSystemLoader` 直接 `import()`。[plugin host](/evaluation-path/treatment/apps/stage-tamagotchi/src/main/services/airi/plugins/host/index.ts:234)、[FileSystemLoader](/evaluation-path/treatment/packages/plugin-sdk/src/plugin-host/runtimes/node/loaders/fs.ts:44) | 当前插件是 main 进程内的受信扩展，不是安全沙箱。 |

插件 SDK 文档已经提出“每个插件一个 Eventa context”和按 `hostId/instanceId` 隔离 capability，但 Node runtime 的 worker/WebSocket transport 目前仍未实现。[multi-transport.md](/evaluation-path/treatment/packages/plugin-sdk/docs/design/multi-transport.md:25)、[node runtime](/evaluation-path/treatment/packages/plugin-sdk/src/plugin-host/runtimes/node/index.ts:24)

## 建议的长期形态

```text
Renderer surface
  -> typed preload capability API
  -> WindowSession
       windowId / surface / stageInstanceId / Eventa context / dispose
  -> Desktop Host Kernel
       app services / window services / plugin broker
  -> PluginHostAdapter
       embedded trusted host | external process | remote host
```

职责建议：

- main：拥有 BrowserWindow、OS API、持久化配置、插件生命周期和窗口注册表。
- preload：只暴露 allowlist 能力，不再暴露完整 `ipcRenderer`。
- renderer：只拥有视图状态和交互逻辑，通过注入的 capability bridge 访问桌面能力。
- shared packages：拥有纯业务模型、跨运行时协议和 UI；不直接依赖 Electron。
- Plugin Host：拥有插件 session、权限、capability、tool registry 和资源撤销。
- 插件 UI：继续使用 iframe/MessagePort，但由 host 统一决定 asset 来源、sandbox 策略和可用能力。

协议应明确划分为三类：

- app-scoped：更新器、server channel、插件 registry。
- window-scoped：窗口尺寸、导航、拖拽、窗口生命周期。
- plugin/module-scoped：`extensionId`、`sessionId`、`moduleId`、capability、tool call。

`windowId` 和 `stageInstanceId` 应由 main 创建并注入；现有 chat sync 的 renderer `instanceId` 可以作为局部同步机制，但不应继续承担全局窗口身份。

## 可逆迁移顺序

1. **先建立边界矩阵和 ADR**

   记录每个 Eventa contract 的 scope、owner、允许调用者和生命周期。先不改变运行时行为。

2. **引入 `WindowSession`/`WindowRegistry` 外壳**

   包装现有 `createContext(ipcMain, window)`、sender 校验和 cleanup。新窗口先采用新路径，旧窗口保留旧 factory，随时可回退。

3. **逐能力收窄 preload**

   先增加 typed `window.api`/capability bridge，内部仍由旧 Eventa/raw API 实现；迁移完成一个能力后再删除对应 raw 暴露。不要一次性重写所有 preload。

4. **把 renderer 启动改成 surface profile**

   将 main、settings、chat、widgets、spotlight 等初始化拆成显式 profile/runtime factory。短期仍可由 route 选择 profile，长期由 main 注入 surface descriptor，逐步删除 `App.vue` 中的 route 条件。

5. **收拢协议 ownership**

   - 插件 Host ↔ Plugin 的协议归 `plugin-protocol`/`plugin-sdk`。
   - Tamagotchi kit 协议归 `plugin-sdk-tamagotchi`。
   - Electron 窗口/OS IPC 归已有 `electron-eventa` 或一个窄的 desktop-contract package。
   - app-local `shared/eventa` 暂时只做 re-export/adapter，并设置明确删除节点。

6. **先做嵌入式 PluginHostAdapter**

   保留当前 main 内 host，实现统一的 owner scope、capability snapshot、权限拒绝、工具 registry 和 observability。现有 host 文件已经标注 tool registry ownership 仍隐藏在 built-in kit runtime，这是适合先整理的边界。[host/index.ts](/evaluation-path/treatment/apps/stage-tamagotchi/src/main/services/airi/plugins/host/index.ts:435)

7. **只有在插件不受信时再外置进程**

   如果未来支持下载型、市场型或第三方插件，应把 Plugin Host 放到受监管的 child process/worker，并通过版本化 Eventa transport 通信。当前 SDK 的 worker/WebSocket 仍是设计目标，不应在迁移计划中假设它们已经可用。

## 验证方法

- 静态依赖检查：renderer/shared package 禁止直接导入 Electron adapter 或访问 `window.electron.ipcRenderer`；preload 只能导出 allowlist API。
- 类型和构建：`pnpm typecheck`、`pnpm -F @proj-airi/stage-tamagotchi typecheck`、`pnpm lint`、桌面 build。
- IPC contract tests：
  - 两个 BrowserWindow 调用同一 contract 不得串窗。
  - app-scoped API 可从允许窗口调用，window-scoped API 必须拒绝错误 sender。
  - 关闭、重开、renderer crash 后不得残留 handler/listener。
- Plugin tests：
  - 权限拒绝、插件异常、load/unload/reload。
  - tool、widget、asset session 按 `extensionId/sessionId/moduleId` 隔离。
  - capability snapshot 可处理迟到 ready/degraded/withdrawn。
  - 外置 host 崩溃不能拖垮 main。
- 打包 smoke test：主窗口、settings/chat/widgets/spotlight、托盘、第二实例、更新器、离线和 renderer 重启。
- 先建立基线再设预算：启动耗时、IPC p95、每窗口内存、插件加载耗时、插件 host 重启时间。本次未测量这些数值，不应预先假定性能结果。

最终的产品决策只有一个会显著改变路线：插件是否被视为“不受信代码”。若始终是本地、人工安装的受信插件，嵌入式 host 可以长期保留；若存在下载、分发或第三方插件，main 进程内动态导入必须视为过渡形态。

[EVAL:evolve-software-architecture-loaded]
