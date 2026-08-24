## 1. 范围与结论

本评估基于当前只读快照 `HEAD 5228f9412`，重点检查：

- `apps/stage-tamagotchi` 的 main、preload、renderer
- `packages/stage-ui`、`stage-shared`、`stage-pages`
- `electron-eventa`、`plugin-sdk` 及插件宿主

结论：当前架构已经具备可演进的基础——`injeca` 负责 main 生命周期，Eventa 负责 IPC，`createReusableWindow` 管理部分窗口，插件 UI 也有 iframe 通道。但边界仍然容易穿透：

```text
renderer/window
  -> preload 暴露的原始 Electron API
  -> Eventa 全局或窗口上下文
  -> main services / window managers / plugin host
  -> Electron OS 能力、文件系统、服务器

plugin entrypoint
  -> 当前直接动态加载进 Electron main
plugin UI
  -> renderer iframe + postMessage
```

长期建议演进为：

> Electron main 模块化 Host Kernel  
> + 每窗口 Surface Registry  
> + 窄化且版本化的 preload bridge  
> + 中立的共享协议包  
> + Host 控制的插件 transport/runtime

不建议现在直接拆成微服务或一次性重写所有窗口。

## 2. 已观察事实

| 分类 | 证据 | 判断 |
|---|---|---|
| Fact | main 通过 `injeca` 集中注册配置、插件宿主、窗口、Godot、MCP 等，并在多个窗口之间显式传递依赖。[main/index.ts:132](/evaluation-path/treatment/apps/stage-tamagotchi/src/main/index.ts:132) | main 已是实际的应用组合根和生命周期协调器。 |
| Fact | preload 暴露完整 `electronAPI`，并允许 renderer 直接取得 `ipcRenderer`。[preload/shared.ts:8](/evaluation-path/treatment/apps/stage-tamagotchi/src/preload/shared.ts:8) | preload 当前主要是 transport bootstrap，不是最小权限边界。 |
| Fact | 所有窗口复用 renderer 应用，`App.vue` 根据路由决定是否建立完整运行时。[App.vue:79](/evaluation-path/treatment/apps/stage-tamagotchi/src/renderer/App.vue:79) | 新增窗口会增加全局 bootstrap 和路由分支的复杂度。 |
| Fact | 共享页面仍直接导入 Electron Eventa 并读取 `window.electron.ipcRenderer`。[comfyui.vue:4](/evaluation-path/treatment/packages/stage-pages/src/pages/settings/providers/artistry/comfyui.vue:4) | shared UI 与 desktop transport 存在穿透。 |
| Fact | `stage-ui` 已有通过 `setBridge()` 注入桌面能力的模式，并明确避免 Electron-only import。[plugin-host-debug.ts:81](/evaluation-path/treatment/packages/stage-ui/src/stores/devtools/plugin-host-debug.ts:81) | 这是应继续推广的正确边界。 |
| Fact | 插件文件入口由 `FileSystemLoader` 直接 `import(entrypoint)`。[fs.ts:72](/evaluation-path/treatment/packages/plugin-sdk/src/plugin-host/runtimes/node/loaders/fs.ts:72) | 当前插件代码与 main 进程同权运行；manifest permissions 不是进程级安全隔离。 |
| Fact | 插件 SDK 已规划“每个插件一个 Eventa context、由 Host 选择 transport”，但文档状态仍为 Planned。[multi-transport.md:25](/evaluation-path/treatment/packages/plugin-sdk/docs/design/multi-transport.md:25) | 未来插件方向与当前实现之间仍有迁移工作。 |
| Fact | main/preload 多处通过 `setMaxListeners` 兜底，代码注释明确希望未来采用 window-namespaced Eventa context。[main/index.ts:55](/evaluation-path/treatment/apps/stage-tamagotchi/src/main/index.ts:55) | 这是上下文和监听器生命周期尚未完全收敛的信号。 |

## 3. 当前主要摩擦

1. **preload 权限过宽**

   renderer 可以自行构造 Electron Eventa context。未来挂载插件 UI 或第三方 renderer 代码时，无法仅通过 preload 明确表达“这个窗口允许哪些能力”。

2. **共享 package 语义混杂**

   `stage-shared` 同时包含中立状态、Electron renderer 类型、BeatSync 和 Electron transport；`stage-ui`、`stage-pages` 仍有直接 Electron 依赖。共享包并非一个清晰的“中立层”。

3. **窗口扩展成本会线性上升**

   main 中 settings、main、tray 等 provider 拥有较大的依赖扇入；窗口能力通过手写 `setupXWindow` 和 RPC 组合维护。窗口数量增加后，窗口身份、能力集合、销毁清理容易分散。

4. **renderer bootstrap 过重**

   非 spotlight 路由都会创建完整 stage runtime，再通过路由判断跳过部分初始化。多窗口扩展会放大启动耗时、状态重复初始化和监听器清理问题。

5. **插件权限不是安全边界**

   当前插件运行时代码进 main；iframe 只隔离插件 UI 和消息通道，不能限制插件入口本身调用 Node/Electron 能力。

## 4. 质量属性优先级

1. **Authority / Security**：main 保持 OS、持久化、插件生命周期的唯一权威；renderer 和插件只获得显式 capability。
2. **Extensibility / Locality**：新增窗口或插件不应修改多个既有窗口的全局初始化逻辑。
3. **Isolation / Correctness**：窗口、插件 session、请求 correlation ID 必须独立，禁止跨窗口或跨插件串线。
4. **Testability / Operability**：transport、window lifecycle、plugin lifecycle 都应可用 fake port 测试，并带 `windowId/surfaceId/pluginId/sessionId/requestId`。
5. **Performance**：当前未发现启动、内存和 IPC 延迟预算，属于 Unknown，应先测基线再定目标。

## 5. 方案比较

| 方案 | 优点 | 风险 |
|---|---|---|
| 继续当前模式 | 成本最低，短期开发最快 | preload 权限宽、窗口耦合、插件无法安全隔离 |
| **模块化 Host Kernel（推荐）** | 保留单一 Electron main、Eventa、injeca；逐步引入 typed bridge、窗口 registry、插件 transport seam | 需要一段过渡期，同时维护旧 adapter |
| 全面进程隔离插件 | 第三方插件安全边界最好，多插件故障隔离强 | worker/子进程通信、重启、打包、版本兼容、调试复杂度显著增加 |

## 6. 推荐目标架构

### Main：Host Kernel

main 只负责权威能力和生命周期：

- app lifecycle、配置、持久化
- window/surface registry
- plugin runtime、权限和 session
- OS 能力、网络服务、子进程
- capability registry 和事件观测

窗口不再互相持有大量具体依赖，而是声明：

```ts
SurfaceDefinition {
  surfaceId
  route
  reusePolicy
  requiredCapabilities
  lifecyclePolicy
}
```

保留现有 `createReusableWindow`，但逐步由一个真正拥有身份、创建、关闭、销毁和清理责任的 `SurfaceRegistry` 统一管理。

### Preload：窄化 DesktopBridge

最终只暴露：

- 版本信息和 platform
- 明确列出的 invoke/subscribe 方法
- 自动绑定的 `windowId/surfaceId`
- 经过 schema 校验的 DTO

不再向生产 renderer 暴露原始 `ipcRenderer` 或完整 `electronAPI`。现有 Eventa 可继续作为内部 transport；不需要替换 Eventa。

### Renderer：按 Surface 初始化

`App.vue` 只负责通用壳和 surface bootstrap。每个窗口根据 surface definition 注入独立的 runtime：

- main surface：stage runtime
- settings surface：settings runtime
- chat surface：chat runtime
- widgets surface：widget runtime
- devtools surface：debug runtime

这样可以消除“所有窗口先启动完整运行时，再按路由跳过”的模式。

### Shared packages：按语义拆分

建议保持现有包名，先按 subpath 和依赖方向治理：

1. 中立 domain/types：不得依赖 Electron、Node、Electron Eventa。
2. protocol/contracts：Eventa channel、Valibot schema、DTO、版本号。
3. desktop adapter：仅由 `apps/stage-tamagotchi` 使用。
4. plugin protocol/SDK：插件 manifest、capability、session、module、transport contract 的唯一来源。

`stage-ui` 继续通过 bridge 注入 desktop 能力；`stage-pages` 不应再自行创建 Electron Eventa context。

### Plugin Host：分层信任模型

- 内置和开发插件：允许当前 in-process runtime。
- 第三方或不可信插件：worker、utility process 或独立 Node 子进程。
- 远程插件：WebSocket/Eventa transport。
- 插件 UI：继续使用 iframe、资源 session 和 owner-based revoke。

transport 必须由 Host 选择，且每个 plugin instance 拥有独立 Eventa context。插件 SDK 的现有设计文档已经明确了这一方向。[multi-transport.md:37](/evaluation-path/treatment/packages/plugin-sdk/docs/design/multi-transport.md:37)

## 7. 可逆迁移步骤与验证

### 阶段一：建立边界基线

记录窗口、路由、IPC handler、owner、持久化和生命周期矩阵；补充 ADR，不改变行为。

退出条件：每个 handler 都能回答“属于 app、surface、window 还是 plugin session”。

### 阶段二：先迁移一个 typed bridge

优先选现有已有 bridge seam 的 plugin-host debug 页面：

- renderer 通过注入的 `DesktopBridge` 调用
- bridge 内部暂时仍适配现有 Eventa
- 保留旧路径，直到该页面的直接 `window.electron` 引用为零

可回滚：只切换该页面的 adapter，不影响其他页面。

### 阶段三：收敛共享协议

将 `stage-ui` 中手写的 plugin DTO 和 `apps/.../shared/eventa/plugin` 的重复类型统一到 `plugin-protocol` 或 SDK 所属包。现有 TODO 已指出这项重复。[plugin-host-debug.ts:20](/evaluation-path/treatment/packages/stage-ui/src/stores/devtools/plugin-host-debug.ts:20)

验证：

```bash
rg -n "window\.electron|@moeru/eventa/adapters/electron|from ['\"]electron['\"]|node:" \
  packages/stage-ui packages/stage-pages packages/stage-shared
```

中立包应无上述依赖，除非位于明确的 desktop adapter subpath。

### 阶段四：引入 Surface Registry

先迁移两个窗口，例如 settings + chat，其他窗口保持现有 factory。

验证：

- 创建、隐藏、关闭、重新打开无重复 handler
- A 窗口不能调用 B 窗口的操作
- renderer reload 后旧监听器被清理
- 一个旧窗口保留作为回滚路径

### 阶段五：引入插件 Runtime Adapter

先把当前 in-process dynamic import 包装成 `PluginRuntime` adapter，再增加一个 opt-in worker 插件。

验证：

- worker 崩溃不会导致 main 或其他插件退出
- session、asset、tool、widget 均能撤销
- 两个插件 context 不互相串线
- 权限拒绝、超时、重启、版本不兼容都有确定错误
- 日志包含 plugin/session/transport/request 信息

### 阶段六：移除原始 preload API

只有当生产 renderer 不再直接访问 raw Electron API 后，才删除旧暴露面。不要先盲目切换 `sandbox` 或大规模重写窗口；先完成 authority 和依赖清理，再单独验证安全配置。

最终验证建议包括：

- `pnpm typecheck`
- `pnpm lint`
- targeted Vitest contract tests
- Electron Playwright 多窗口场景
- packaged asar + userData 插件加载测试
- Windows/macOS/Linux smoke test
- 启动时间、窗口创建时间、内存和 IPC round-trip 基线

本次未执行这些验证命令，因为用户要求只评估、不改变工作区或外部状态。

## 8. 开放决策

以下问题会改变迁移优先级：

- 插件是否允许来自第三方或网络下载？若允许，进程隔离应提前。
- 多窗口是否共享同一个 stage session，还是每个窗口独立？这决定 capability scope。
- 是否需要跨 AIRI 版本的插件 API 兼容？若需要，应尽早加入版本协商。
- 是否存在明确的启动时间、内存和窗口数量目标？
- 插件 UI 是否永远只能 iframe，还是允许特权 renderer surface？

在这些决策明确前，建议默认策略是：**in-process 仅用于内置/可信插件；第三方插件不以 manifest permission 作为安全保证；所有 renderer 能力通过显式 bridge 注入。**

本次没有修改文件、创建提交或改变外部状态。

[EVAL:evolve-software-architecture-loaded]
