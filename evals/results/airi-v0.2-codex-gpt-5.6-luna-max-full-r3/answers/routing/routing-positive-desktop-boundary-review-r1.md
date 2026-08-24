结论：当前 AIRI 桌面端的 main 与 renderer 已有基本物理边界，但 preload 和共享 package 仍然偏“通用桥接层”。面向插件和多窗口，建议逐步演进为：

```text
main：应用宿主、窗口注册表、插件宿主、权限与资源
  ↓ typed capability protocol
preload：最小化能力膜，不暴露原始 ipcRenderer
  ↓ per-window runtime profile
renderer：窗口 UI、Pinia 状态、显式窗口身份
shared：环境无关的协议、schema、纯业务逻辑
plugin UI：iframe/worker/独立进程，根据信任模型选择
```

## 范围与置信度

检查对象是 HEAD `5228f9412` 的 `stage-tamagotchi`、相关共享 packages 和 plugin-sdk。本轮只读，没有修改文件、提交或启动应用。

拓扑和静态依赖判断置信度高；Electron 运行时默认值、打包后的 CSP 和实际性能未启动验证，置信度中等。

## 可观察事实

| 事实 | 证据 | 判断 |
|---|---|---|
| main 是真正的组合根 | [`main/index.ts`](/evaluation-path/treatment/apps/stage-tamagotchi/src/main/index.ts:132) 注册 Injeca providers，窗口、插件、服务器和生命周期集中装配 | 这是良好的依赖注入接缝，但 fan-out 已较高 |
| main 没有直接依赖 renderer、stage-ui、stage-pages | 静态 `rg` 检查未发现这些反向 import | 进程层方向正确 |
| preload 暴露的是通用 Electron API | [`preload/shared.ts`](/evaluation-path/treatment/apps/stage-tamagotchi/src/preload/shared.ts:8) 暴露 `electronAPI`、`platform`，并设置 `ipcRenderer.setMaxListeners(0)` | 仍是低层 transport，不是领域能力膜 |
| renderer 负责大量运行时装配 | [`renderer/App.vue`](/evaluation-path/treatment/apps/stage-tamagotchi/src/renderer/App.vue:79) 初始化大量 store、插件桥和跨窗口同步；除 spotlight 外都创建 full runtime | 窗口差异主要由 route 判断隐含表达 |
| renderer Eventa context 是模块级单例 | [`use-electron-eventa-context.ts`](/evaluation-path/treatment/packages/electron-vueuse/src/composables/use-electron-eventa-context.ts:11) 缓存 `sharedContext` | 窗口身份没有成为显式 domain 对象 |
| 多窗口 context 管理存在重复与全局 listener 调整 | [`referenced-window.ts`](/evaluation-path/treatment/apps/stage-tamagotchi/src/main/windows/shared/referenced-window.ts:38) 按窗口创建 context；多个窗口模块重复 `setMaxListeners` | 未来窗口数量增加时，生命周期和隔离容易退化 |
| shared package 混合了环境边界 | [`stage-shared` 的 beat-sync detector](/evaluation-path/treatment/packages/stage-shared/src/beat-sync/detector.ts:159) 直接使用 Electron renderer context；[`shared/eventa/index.ts`](/evaluation-path/treatment/apps/stage-tamagotchi/src/shared/eventa/index.ts:218) 还包含重复的插件 capability 类型 | `stage-shared`、stage-ui、桌面协议的职责尚未完全分层 |
| 插件 UI 已有较好的局部边界 | main 中的插件 host、资源会话和权限模型；[`extension-ui-host.vue`](/evaluation-path/treatment/apps/stage-tamagotchi/src/renderer/widgets/extension-ui/components/extension-ui-host.vue:105) 使用 iframe sandbox；[`iframe-request-coordinator.ts`](/evaluation-path/treatment/apps/stage-tamagotchi/src/main/windows/widgets/iframe-request-coordinator.ts:37) 负责 requestId、超时和关闭清理 | 这是可复用的目标模式 |
| plugin-sdk 的多传输仍未完成 | [`plugin-sdk` node runtime](/evaluation-path/treatment/packages/plugin-sdk/src/plugin-host/runtimes/node/index.ts:24) 只有 in-memory，WebSocket、worker、Electron transport 会抛出未实现 | 现在不宜直接把插件 host 拆成远程/独立进程架构 |

## 当前主要摩擦

- preload 暴露了过宽的 `window.electron`；renderer 和部分共享逻辑可以直接取得 `window.electron.ipcRenderer`。
- `App.vue` 既是 UI 根组件，又是窗口 runtime、插件 host bridge、跨窗口同步和生命周期组合根。
- Eventa 与 `BroadcastChannel` 并存。后者明确会把同一请求发送给所有 Stage 窗口，目前依靠 role、实例 ID 和锁避免重复处理；它适合广播状态，不适合精确寻址的控制命令。
- `src/shared/eventa` 已开始按 domain 拆分，但仍是桌面专属的大 barrel。现有 [`domains.test.ts`](/evaluation-path/treatment/apps/stage-tamagotchi/src/shared/eventa/plugin/domains.test.ts:42) 证明了“拆分模块、保留单向 barrel 导出”是可行迁移方式。
- 多个窗口显式设置 `sandbox: false`，而 `contextIsolation` 没有在这些窗口配置中显式表达，例如 [`main/windows/main/index.ts`](/evaluation-path/treatment/apps/stage-tamagotchi/src/main/windows/main/index.ts:80)。这需要运行时安全审计，不能仅凭源码推断最终安全状态。
- 插件 host 当前由 main 进程承载。若插件代码不完全可信，它不具备独立崩溃、内存和系统权限隔离；这是信任模型问题，不只是 package 边界问题。

## 质量属性优先级

1. 契约与所有权：每条调用都能识别 `windowId`、`pluginId`、`sessionId`、`requestId`。
2. 安全隔离：preload 最小暴露、插件权限 deny-by-default、资源和 iframe 按 owner 隔离。
3. 生命周期可控：窗口关闭、renderer 崩溃、插件 reload、app shutdown 都能清理 handler、pending request 和资源 session。
4. 可测试性：协议测试、双窗口隔离测试、双插件隔离测试和打包 Electron smoke。
5. 性能：在控制面稳定后，再为音频、流式 token、trace 等高频数据设计独立 data plane 和背压。

## 选项

| 方案 | 评价 |
|---|---|
| 继续当前形态，仅增加局部 handler | 成本最低，但窗口身份、preload 权限和共享层耦合继续隐含 |
| 显式 WindowSession/Capability Port，main 作为 host kernel | 推荐。能复用当前 Injeca、Eventa、插件 host 和 widget coordinator，迁移可按窗口/领域逐步进行 |
| 现在立即把插件或每个窗口拆成独立进程 | 隔离最强，但 transport、重连、打包、调试和资源成本高；当前 SDK 尚未具备所需 transport |

## 推荐方向

采用“显式窗口会话 + capability-oriented preload + host-centered plugin runtime”。

- main 维护 `WindowRegistry` 和 `WindowSession`：包含 `windowId`、role、生命周期、能力集合和可销毁的 context。
- preload 逐步提供 typed `airi.*` capability façade；renderer 不再直接依赖原始 `ipcRenderer`。
- renderer 按 `main/settings/chat/widgets/spotlight` 等 profile 装配运行时，而不是所有窗口默认启动 full stage runtime。
- `stage-ui` 依赖抽象的 `WindowPort`、`PluginPort`、`ServerPort`，不直接检查 Electron 环境或读取 `window.electron`。
- 将协议拆成环境无关的 contract/schema package；Electron adapter、main service、renderer adapter 分别位于边界侧。
- plugin host 初期继续留在 main，但每个插件使用独立 context、session、权限和资源 owner。
- 仅当插件被定义为不可信代码、需要崩溃隔离或远程插件成为近期需求时，再引入 worker/child process/WebSocket transport。
- `BroadcastChannel` 保留给明确的广播或高频数据同步；窗口控制、插件管理和一次性请求统一走带 owner 的定向协议。

## 可逆迁移步骤与验证

1. 先建立窗口、协议、权限和状态所有权矩阵，并记录 ADR；不改变运行时行为。
2. 从一个垂直切片开始，建议先做 settings，再做 widgets/plugin iframe。定义带 `protocolVersion`、`requestId`、`windowId`、`ownerId` 的 envelope 和结构化错误。
3. 在现有 `main/windows/shared` 中引入概念性的 `WindowSession`，只迁移一个窗口；关闭时集中销毁 context 和 handler。
4. 为同一个切片增加 typed preload façade。旧的 `shared/eventa` 只作为单向 re-export 迁移桥，不在业务代码中增加多版本分支。
5. 在 renderer 引入 window profile，逐步减少 `App.vue` 的全量初始化；把 raw Electron 调用收敛到 adapter。
6. 将插件 capability 类型的权威来源移到 SDK/协议层，继续利用现有 barrel identity 测试；为每个插件建立 context/session owner。
7. 最后再评估 worker、独立进程或远程 transport，保留 Injeca provider 选择作为回滚点，不做数据迁移。

验证应包括：

- 静态依赖检查：main 不得反向 import renderer；preload 只依赖 Electron adapter 和 protocol；stage-ui 不新增 raw Electron 依赖。
- Vitest 契约测试：两个窗口、两个插件、同名 module、过期 request、错误窗口结果不得串线。
- 生命周期测试：窗口关闭/reopen、renderer 不可用、插件 load failure、reload、permission revoke、asset session revoke。
- 现有测试基线：桌面 app 当前可发现约 52 个 `.test.ts`，已有 plugin host、static assets、widget iframe 和 Eventa runtime 测试；应继续扩展而不是另建平行测试体系。
- Electron smoke：复用 `desktop-overlay-live-window-smoke`、Vishot Electron 场景和 plugin chess worker smoke，补充 main/settings/chat/widgets/spotlight 多窗口矩阵。
- 安全验证：在打包应用中确认 `contextIsolation`、`nodeIntegration`、sandbox、导航拦截、CSP、插件资源 cookie scope 和 iframe sandbox；当前 renderer HTML 的 CSP 仍需单独审计，可见 [`renderer/index.html`](/evaluation-path/treatment/apps/stage-tamagotchi/src/renderer/index.html:6)。
- 性能验证：以当前版本为基线测启动时间、每窗口内存、IPC p95、插件 reload 延迟、pending request 数量和 listener 数量。

## 待决策项

以下问题会改变推荐的落地顺序：

- 插件是否允许加载第三方或不完全可信的本地代码？
- 远程插件/WebSocket 是否是近期产品需求，还是仅长期设计目标？
- 多窗口是否要求独立生命周期和独立状态，还是只需要多个视觉窗口？
- 是否有严格的启动时间、内存、音频处理预算？
- Eventa 的 window-namespaced context 何时可用；若长期不可用，应由 AIRI 自己的 `WindowSession` adapter 承担隔离。

本轮工作区复核为无文件改动、无提交。

[EVAL:evolve-software-architecture-loaded]
