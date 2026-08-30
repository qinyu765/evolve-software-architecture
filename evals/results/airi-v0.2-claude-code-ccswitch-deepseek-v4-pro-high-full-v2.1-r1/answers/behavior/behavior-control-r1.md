# 桌面端「第三方插件 / 更多窗口 / 独立后台」架构评估

**结论先行**：仓库里已经有这三个能力的“半成品”——插件宿主(`plugin-sdk` + `plugin-sdk-tamagotchi`)、按 key 复用的多窗口模式、以及单实例锁 + 本地服务器的后台形态。问题不在缺抽象，而在**边界没有固化**：Eventa 契约有类型重复、窗口管理器每个窗口手写一份、插件在进程内运行没有隔离、关闭全部窗口的行为跨平台不一致。因此我建议走**“维持现状 + 边界硬化”**（方案 A）：现在就固化 5 个低成本、高杠杆的契约，把“插件进程沙箱、通用后台宿主、插件顶层窗口 kit、权限审核分发”这些抽象**明确延后**，并用可触发条件（而不是时间表）决定何时启动。

---

## 1. 现状证据（基于代码，不是猜测）

**组合根是单主进程 + injeca DI**。`apps/stage-tamagotchi/src/main/index.ts:130-270` 用 `injeca.provide` 装配约 25 个 provider，每个窗口是一个 `windows:*` provider，返回一个 manager（`setupMainWindow`、`setupSettingsWindowReusableFunc`、`setupWidgetsWindowManager` 等）。依赖显式声明，这是目前最健康的部分。

**窗口**：所有窗口共用一份渲染 bundle（`electron.vite.config.ts:100-106` 只有 `main` 和 `beat-sync` 两个 HTML 入口），通过 `withHashRoute`（`libs/electron/location.ts:97`）加载不同 hash 路由。窗口复用靠 `createReusableWindow`（`libs/electron/window-manager/reusable.ts:5`），但真正的“按 key 多实例”只有 devtools 一处（`windows/devtools/index.ts:20-84` 的 `Map<key, reusable>`）。每个窗口各自手写：`BrowserWindow` 选项、bounds 持久化（main 用 `app/config.json`、widgets 用 `windows-widgets/config.json`，两份不同 schema）、导航保护 `protectPrivilegedWindowNavigation`、Eventa 上下文、RPC 装配。

**IPC**：契约集中在 `src/shared/eventa/`，字符串命名空间（`eventa:invoke:*` / `eventa:event:*`）。已经支持窗口级上下文 `createContext(ipcMain, window)`（`windows/main/index.ts:216`、`windows/widgets/index.ts:329` 都在用），但有三处 `ipcMain.setMaxListeners(0)` 的 TODO 说明“窗口命名空间”还没做完（`index.ts:55-58`、`preload/shared.ts:9-12`、`widgets/index.ts:322-325`）。另外 `shared/eventa/index.ts:218-247` 与 `shared/eventa/plugin/*.ts` 和 `@proj-airi/plugin-sdk` 之间有明显的手工类型重复（代码里自己写了 TODO，如 `plugin/capabilities.ts:42-44`）。

**插件**：已经有一个相当完整的宿主。`packages/plugin-sdk` 的 `ExtensionHost`（`plugin-host/core.ts:205-858`）管理会话、模块、kit、权限、资源、能力；manifest 是 valibot 校验的 V1（`plugin-host/shared/types.ts:233-253`）。但有两个关键事实：

1. **插件在主进程内运行**。`FileSystemLoader.loadExtensionFor` 直接 `import(entrypoint)`（`runtimes/node/loaders/fs.ts:72-76`）；`runtimes/node/index.ts:24-38` 里 `websocket`、`node-worker`、`electron` 三种 transport 全部 `throw new Error('… not implemented yet')`——即**没有进程/worker 隔离**，一个插件卡死或崩溃会带走整个主进程。
2. Electron 侧 `new ExtensionHost({ runtime: 'electron' })` **没有传 `permissionResolver`**（`services/airi/plugins/host/index.ts:236`），授权默认等于 manifest 声明，且 grants 只在内存里，不落盘、没有审核/撤销 UI。

插件目前能做的三件事：gamelet kit（在 widgets 窗口里开 iframe UI）、tool kit（给 agent 注册工具）、widget kit——**不能开顶层窗口，也没有后台任务/常驻 kit**。

**后台**：`app/single-instance.ts:45-56` 的单实例锁注释直接说明了不变量：“固定 localhost 服务不能绑两次”。server channel 是 6121 端口的 WebSocket（`services/airi/channel-server/index.ts:77-79`），还有 built-in HTTP server、MCP stdio 子进程、Godot 侧车进程、BeatSync 隐藏窗口。生命周期分散在两套机制里：`libs/bootkit/lifecycle.ts` 的全局数组，和 injeca `lifecycle.appHooks`；退出时 `emitAppBeforeQuit()` 与 `injeca.stop()` 在 `Promise.all` 里**并行**跑（`index.ts:328-331`），没有保证顺序。`window-all-closed` 只在非 macOS 退出（`index.ts:291-297`），所以“关窗后后台常驻”今天是 macOS-only 行为。

---

## 2. 三个目标能力与现状的差距

| 目标 | 已有 | 缺口 |
|---|---|---|
| 第三方插件 | 宿主、kit、权限、能力、静态资源、自动重载 | 进程隔离（崩溃/阻塞/CPU）；权限落盘与审核；顶层窗口 kit；后台/常驻 kit；第三方分发与签名 |
| 更多窗口 | 复用窗口、按 key 多实例、hash 路由、窗口级 Eventa | 没有统一的 WindowManager 契约；bounds 持久化三份实现；每个窗口重复装配 |
| 独立后台 | 单实例锁、本地服务器、子进程、隐藏窗口 | 没有独立后台宿主；生命周期顺序未固化；关窗行为跨平台不一致 |

---

## 3. 应该现在稳定的边界（低成本、高杠杆）

### 3.1 Eventa 契约的命名与所有权
这是未来窗口、插件、后台能力都要穿过的唯一传输边界。具体三件事：
- 把 `shared/eventa` 里与 plugin-sdk 重复的类型改成从 `@proj-airi/plugin-sdk` / `plugin-protocol` re-export（代码里已有多处 TODO 标记）。
- 固化契约命名约定和**增量为先**的兼容规则（新契约新增，不改既有 payload）。
- 完成窗口命名空间上下文，删掉三处 `setMaxListeners` hack。注意这一步会改变广播语义（例如 `electronPluginToolsChanged` 现在是全局广播），需要先明确“哪些事件是全局广播、哪些按窗口隔离”并写成契约，不能顺手改。

### 3.2 WindowManager 接口
把 devtools/widgets/settings/chat 已经隐含的形状提炼为一个稳定接口：`createWindow({ key, route, options, onCreated }) → { getWindow, openWindow, closeWindow }`，内部统一处理 bounds 持久化、每窗口 Eventa 上下文、导航保护、close/recreate 语义。这同时是“更多窗口”和未来插件 `windows` kit 的消费点。现在只有 `createReusableWindow` 一个最小实现，缺的是**接口 + 注册表**。

### 3.3 插件 kit/API 边界（对外契约）
manifest V1、`setup(ctx)`、kit 客户端、权限/能力/资源这套是仓库里最干净的抽象，**它才是第三方开发者面对的契约**，必须保持稳定：kit id（`gamelet`/`tool`/`widget`）、能力 key（`proj-airi:plugin-sdk:apis:protocol:resources:providers:list-providers`）、manifest 字段语义。除非真的需要新字段，否则升级为 V2 再动它。

### 3.4 服务生命周期与单实例/端口所有权
把 `onStart/onStop/onBeforeQuit/onWindowAllClosed` + injeca `lifecycle` 收敛成唯一生命周期契约；把“单实例锁 + 6121 端口只能由主运行实例持有”写成组合根处的显式不变量。当前 `emitAppBeforeQuit` 与 `injeca.stop` 并行、插件宿主还额外挂了 `app.once('before-quit')`（`plugins/index.ts:139-143`），退出顺序没有被定义——这正是未来加后台服务时会踩的坑。

### 3.5 preload 特权面保持最小
今天 preload 只暴露 `window.electron` + `window.platform`（`preload/shared.ts:8-29`），所有新能力都应走带类型的 Eventa 契约，而不是扩大原始 bridge。`sandbox: false` 是现有技术债，**记录但不要现在翻**。

---

## 4. 应该延后的抽象（现在不做）

1. **通用插件进程池/沙箱**：`node-worker`/`websocket` transport 的 stub 只是意图信号，不是需求。进程内宿主配 per-session cleanup 对 v1 够用。等出现真实的崩溃/阻塞型第三方插件再做。
2. **通用后台进程宿主 / daemon 化**：MCP stdio、Godot、本地服务器各自生命周期不同，现在抽象成一个“后台服务管理器”是投机。等再有 ≥2 个需要健康检查/重启语义的长驻子进程再做。
3. **插件顶层窗口 kit + 声明式窗口 manifest**：gamelet widgets 已覆盖插件 UI。应先提炼 WindowManager，再在它上面加一个薄薄的 `windows` kit。不要现在设计声明式窗口清单。
4. **权限商店 / 审核 UI / 签名分发**：两层授权模型已存在，接 `permissionResolver` + 落盘 + 审核是产品工作，等真正有第三方分发渠道再做。
5. **多 bundle / 独立沙箱 iframe / contextIsolation 翻转**：复用现有 widgets iframe + 静态资源服务即可。

**延后的理由不是“不重要”，而是“现在抽象会猜错”**——这些边界都依赖一个稳定的进程/窗口/契约底座，底座没固化之前，抽象的形态大概率会重做。

---

## 5. 方案对比

### 方案 A：维持现状 + 边界硬化（推荐）
保持“单主进程 + 进程内插件 + 每窗口 manager”的拓扑，只做 3.1–3.5 的契约固化 + 回归测试。

- **质量属性**：可靠性不变（插件仍能拖垮主进程，这是已知风险）；安全性不变（kit/权限是逻辑门，不是沙箱）；性能最好（无跨进程序列化、无冷启动）；可修改性显著提升（契约稳定后，未来三项目标的改动都是“加一个实现”而不是“改底座”）；可测试性提升。
- **成本**：低到中。主要是类型去重、窗口管理器提取、生命周期收敛和测试，几周到一个月量级。
- **风险**：低。每步可独立回滚，契约是增量式添加。
- **回滚路径**：逐步 git revert；因为不改变对外行为，回滚干净。
- **不改变后果**：契约继续漂移；每个新窗口/插件/后台功能继续 fork 一份模式；三处 TODO 继续存在。

### 方案 B：全量平台化（声明式窗口 + 插件进程池 + 通用后台宿主 + 插件窗口/后台 kit）
一次把三个目标能力全部抽象到位。

- **质量属性**：可靠性/安全性最好（崩溃与特权隔离）；性能最差（序列化开销、冷启动、内存上升）；短期可修改性最差（在需求未验证前冻结了大量投机抽象，改起来很贵）；可测试性更难（跨进程）。
- **成本**：高，数周以上，涉及打包、权限、传输、测试。
- **风险**：高。抽象猜错的代价大；阻塞其他工作；进程隔离在 mac/win/linux 有平台差异（`utilityProcess`、native module 加载）。
- **回滚路径**：难。一旦第三方插件依赖新 surface，契约无法轻易撤回。
- **不改变后果**：短期没有，这是纯前瞻投资，不是修问题。

### 方案 C：定向隔离（只把插件/后台移进 utilityProcess，窗口保持现状）
在方案 A 的基础上，给 plugin-sdk 补一个 `node-worker`/`utilityProcess` transport，把 `ExtensionHost` 挪到专用 utility 进程；窗口仍按现状，但先做 3.2 的 WindowManager。

- **质量属性**：可靠性/安全性在关键处（插件）改善，窗口保持便宜；成本中高；风险中（传输序列化、utilityProcess 里的 native 模块、Electron 版本支持）。
- **回滚路径**：中等——host core 不变，transport 可在 in-memory 与 worker 间切换，可回退。
- **不改变后果**：保留了“插件 UI 走 widgets iframe”的现状，不解决顶层窗口 kit。

**建议**：现在执行 A；把 C 作为 A 的**出口条件驱动**的下一步——当第一个真实第三方插件出现崩溃/阻塞风险时，用环境变量门控（如 `AIRI_PLUGIN_RUNTIME=utility`，默认仍 in-memory）渐进切到 C；B 只在多个长期后台子进程和多个插件窗口同时成为真实需求后，再考虑其声明式部分。

---

## 6. 可验证的渐进迁移路线（每步独立可回滚、保持绿色）

仓库已有的验证命令：`pnpm -F @proj-airi/stage-tamagotchi typecheck`、`pnpm exec vitest run <file>`、`pnpm lint`。

1. **契约去重（先做，纯类型）**：把 `shared/eventa` 里与 plugin-sdk 重复的插件类型改为 re-export，删除重复声明。验证：typecheck 通过 + `vitest run apps/stage-tamagotchi/src/shared/eventa/plugin/domains.test.ts`（已存在）。回滚：revert 单文件。
2. **提炼 WindowManager 接口 + 注册表**：把 devtools 的 `Map<key, reusable>` 模式提升为 `libs/electron/window-manager` 的稳定接口，先迁移一个低风险窗口（chat 或 settings），行为保持不变。验证：typecheck + lint + 一个 open/close 的窗口 smoke（仓库已有 `scripts/desktop-overlay-live-window-smoke.ts` 这类 smoke 先例可参照）。回滚：git revert。
3. **完成窗口命名空间 Eventa 上下文**：定义“全局广播 vs 窗口隔离”的规则并写成契约，删掉 `setMaxListeners(0)`/`setMaxListeners(100)` hack。这是“更多窗口”的使能重构。验证：全量桌面单测 + 确认 `electronPluginToolsChanged` 的投递语义有测试覆盖。回滚：revert，但注意要先明确广播语义，避免这一步骤引入隐藏回归。
4. **收敛生命周期**：把退出路径改为单一有序 stop 序列（现在 `emitAppBeforeQuit` 与 `injeca.stop` 并行，插件宿主还单独挂 `before-quit`），写一个断言释放顺序的单测。验证：新单测 + lint。回滚：revert。
5. **把单实例锁 + 端口所有权写成组合根处的不变量注释/文档**（无行为变更）。验证：lint + 文档审查。
6. **（门控的后续，非现在）utilityProcess 插件运行时**：以环境变量 `AIRI_PLUGIN_RUNTIME` 门控，默认保持 in-memory，跑通后再逐步默认。验证：插件 load/unload 测试在两种模式下都通过。

每一步都只动一个关注点、保持对外行为不变、有对应的类型检查/单测/smoke 信号，因此可以随时停下或回滚。第 6 步刻意放在最后且带开关，正是“延后但不放弃”的落地方式。

---

**一句话总结**：真正要现在投资的是把已经存在的契约（Eventa、WindowManager、插件 kit/API、生命周期与端口所有权）变成显式、有测试、增量为先的稳定边界；进程隔离、通用后台宿主、声明式窗口这些大抽象要压到有真实证据（崩溃插件、多个长驻子进程、多个插件窗口）之后再启动，而不是提前冻结一个大概率会重做的设计。
