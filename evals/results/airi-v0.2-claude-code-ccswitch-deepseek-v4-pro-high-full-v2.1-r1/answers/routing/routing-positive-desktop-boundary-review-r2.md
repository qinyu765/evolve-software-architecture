# AIRI 桌面端架构评估（main / preload / renderer / 共享 package 边界）

## 1. 范围与置信度

**评估对象**：`apps/stage-tamagotchi`（Electron 桌面端）的进程边界与共享 package 职责，面向「未来插件能力 + 多窗口扩展」这一长期方向。**仓库类型判定：Electron 多窗口桌面应用 + pnpm monorepo**，置信度高——`electron.vite.config.ts` 明确三目标（main/preload/renderer），`package.json` 的 `main` 指向 `./out/main/index.js`，`crates/` 是废弃的旧 Tauri 实现。

**结论先行**：当前架构的骨架（Eventa 契约 + injeca DI + 每窗口一个 manager + plugin-sdk 的 host/runtime/kit 分层）是健康的，不需要推倒。真正的高杠杆缺口只有一个：**窗口身份没有成为一等公民**。所有窗口共用一个全局 `ipcMain` 总线，靠 `setMaxListeners(0)` 和手写 sender 过滤来硬扛多窗口。长期方向是把「窗口身份 + 能力声明」做成一个注册表 seam，而不是继续在每个窗口里重复注册。

以下所有判断都以代码证据为基础，事实 / 推断 / 未知会分别标注。

## 2. 观察到的事实

### 进程边界

- **三进程 + 双入口**。`electron.vite.config.ts:81-106` 定义 preload 两个入口（`index`、`beat-sync`）、renderer 两个入口（`main`、`beat-sync`）。renderer 用 `base: './'`，生产走 `file:`、开发走 dev server。
- **preload 是传输层而非能力层**（事实）。`apps/stage-tamagotchi/src/preload/shared.ts:19-29` 只把 `electronAPI`（来自 `@electron-toolkit/preload`）和 `platform` 挂到 `window`，即向渲染进程暴露了原始 `ipcRenderer` 对象。
- **主窗口 `sandbox: false`**（事实）。`apps/stage-tamagotchi/src/main/windows/main/index.ts:88-91`，context isolation 仍开（默认），但 sandbox 关闭。renderer 通过 `createContext(window.electron.ipcRenderer)` 直接连 IPC（`packages/electron-vueuse/src/composables/use-electron-eventa-context.ts:18-24`）。**推断**：每个 renderer 实际可见的「API 面」等同于「所有已注册的 handler，减去手动 sender 过滤」，而不是按窗口声明的能力面。

### 组合根

- `apps/stage-tamagotchi/src/main/index.ts` 是唯一的组合根，约 355 行，用 `injeca.provide` 显式声明依赖图。约 14 个窗口管理器（main/chat/settings/widgets/notice/onboarding/spotlight/caption/about/devtools/beat-sync/dashboard/inlay/desktop-overlay，后者由 env 门控）。
- 依赖图很重：`settingsWindow` 依赖 16 项（`index.ts:216-222`），`mainWindow` 依赖 13 项（`index.ts:224-232`）。每个窗口 manager 的 `setupXxx` 都带一个长长的显式 params 对象（如 `main/index.ts:52-65`）。

### IPC 契约与作用域（核心摩擦区）

- **统一契约中心**：`apps/stage-tamagotchi/src/shared/eventa/index.ts` 定义数百个 `defineInvokeEventa` / `defineEventa` 契约，并 re-export `@proj-airi/electron-eventa`。个别窗口的契约放在窗口目录内（如 `windows/desktop-overlay/rpc/contracts.ts`）。
- **每个窗口重复注册同一批基础服务**：`windows/shared/window.ts:134-149` 的 `setupBaseWindowElectronInvokes` 给每个窗口注册 screen/window/app/powerMonitor/systemPreferences/i18n/server-channel 六类 handler。
- **`setMaxListeners(0)` 遍布 ~16 个文件**，伴随同一句注释：「once we refactored eventa to support window-namespaced contexts, we can remove the setMaxListeners call」——见 `main/index.ts:55`、`main/windows/main/index.ts:211`、`main/windows/shared/referenced-window.ts:41`、`main/services/airi/widgets/index.ts` 等。
- **手写 sender 过滤是窗口作用域的事实来源**：`main/services/airi/widgets/index.ts:33-38` 的 `isFromWindow` 用 `sender.id === window.webContents.id` 判断事件来源。**推断**：`createContext(ipcMain, window)` 的第二个 `window` 参数目前没有被 Eventa 强制用于按窗口分发，否则不需要这层手动过滤和 `setMaxListeners(0)`。

### 共享 package 边界

- `@proj-airi/electron-eventa`：electron 通用契约包，导出 `.`、`./electron`、`./electron-updater`（`packages/electron-eventa/package.json:18-23`）。
- `@proj-airi/stage-shared`：**源码直连消费**（exports 直接指向 `./src/*.ts`，无 build，`package.json:17-27`），内容是大杂烩：global-shortcut、godot view-state、server-channel-qr、beat-sync、webgpu、composables、window、url、export-csv，还含 `electron-renderer.d.ts` 且 devDep 了 `electron-screen-capture`。
- **类型重复**：`shared/eventa/index.ts:218-221` 手写复制了 `PluginCapabilityPayload/State`，TODO 注明本应从 `@proj-airi/plugin-sdk` re-export，但为避免 stage-ui/shared 对 SDK 的不必要耦合而保留。
- `@proj-airi/electron-vueuse`、`@proj-airi/electron-screen-capture`：桌面专用 helper 包，按 `main` 子路径导出（`electron-vueuse/package.json:18-22`）。

### 插件系统

- `@proj-airi/plugin-sdk` 已有 host/runtime 分层：`./plugin-host` 条件导出 `node` → `runtimes/node`、`default` → `runtimes/web`（`packages/plugin-sdk/package.json:18-28`），依赖 `@proj-airi/plugin-protocol`（wire 协议）。
- **权限模型已存在**：`packages/plugin-sdk/src/plugin-host/runtimes/shared/services/permissions.ts:356-367` 的 `PermissionService.isAllowed(extensionId, area, action, key)`，基于 apis/resources/capabilities/processors/pipelines 五个 area 的 key+action 匹配。
- Electron 侧 extension host 实现在 `apps/stage-tamagotchi/src/main/services/airi/plugins/`：磁盘 manifest 发现（`extensions/v1`，支持 symlink）、enablement 配置、static-assets（loopback HTTP + cookie session）、auto-reload、kit 编排（gamelet → widgets iframe）。
- **一个已标注的归属问题**：`plugins/host/index.ts:437-440` 的 `REVIEW` 注释——tool registry 所有权藏在 built-in kit runtime 里，但 host service 也通过 IPC 暴露它，建议把 registry 所有权上移到 host service。
- **一个健康的 seam**：`plugins/types.ts:45-56` 的 `ExtensionHostGameletWidgetsManager` 用窄接口描述插件 host 对 widgets 窗口管理器的依赖——这是插件与窗口层解耦的正确方向，值得延续。

### 多窗口

- 已有两种窗口生命周期抽象：`createReusableWindow`（每类一个、懒建复用，`libs/electron/window-manager/reusable.ts`）和 `createReferencedWindowManager`（按 id 多实例，`windows/shared/referenced-window.ts`）。多窗口的基础已存在，但作用域靠手写过滤。

## 3. 当前摩擦（按代价排序）

1. **单全局 IPC 总线 + 手动 sender 过滤**。这是最高的结构性摩擦：每加一个窗口，就要重复「注册基础 invokes + 注册窗口专属 invokes + 手动过滤来源 + `setMaxListeners(0)`」，且 handler 的清理只在少数窗口手动做（如 `main/index.ts:219-221` 的 `cleanUpWindowDraggingInvokeHandler`）。多窗口和插件窗口会线性放大这个成本，而且 `setMaxListeners(0)` 掩盖了监听器泄漏。

2. **组合根是一个大依赖图**。窗口间依赖只在 `src/main/index.ts` 一处显式化，但代价是：新增窗口或横切服务要同时改根文件和多个窗口签名（长 params 对象）。这不是错误，但没有把「窗口声明」和「依赖装配」分开。

3. **契约所有权分散**。契约散落在 `shared/eventa/index.ts`（几百行）、窗口目录内的 `rpc/contracts.ts`、`@proj-airi/electron-eventa` 三处，缺一个「窗口契约应放在哪」的规则。`shared/eventa` 与 `electron-eventa` 职责重叠。

4. **preload 无能力面**。所有窗口拿到同一份原始 `ipcRenderer`。对插件而言，iframe / 新窗口会继承「注册了就有」的宽面，能力收敛只能靠运行时过滤——这恰恰是插件隔离最需要收紧的地方。

5. **共享边界模糊**。`stage-shared` 混合了中性逻辑（webgpu、url、export-csv）与 Electron 耦合类型（`electron-renderer.d.ts`）；`electron-eventa` 与 `apps/.../shared/eventa` 边界不清。

## 4. 质量属性优先级

面向「插件能力 + 多窗口」这一目标，按优先级排序：

1. **可扩展性 / 可修改性（首要）**——新增窗口、新增插件能力时，改动应局部化，而不是穿透组合根 + 每个窗口的 rpc 文件。
2. **隔离 / 安全**——插件代码是第三方代码。已有 `PermissionService` 说明这是产品既定方向，窗口能力面必须能和权限模型对齐。**权衡**：更强的隔离意味着更多间接层和启动期检查，会牺牲一点理解成本。
3. **可测试性**——窗口 manager 目前与 `ipcMain`/`BrowserWindow` 全局单例耦合，单测需要大量 mock。保留 injeca DI 是正确方向，应继续。
4. **可维护性 / 变更局部性**——收敛契约所有权、缩减组合根改动。
5. **可操作性**——多窗口的 dispose / 生命周期顺序目前依赖 `app.on('before-quit')` + `injeca.stop()`（`main/index.ts:328-331`），需要在窗口注册表里显式化。
6. **性能**——不是本决策的驱动因素（桌面陪伴应用，非吞吐型）。loopback HTTP 只在插件资产服务需要时保留。

明确不做「同时最大化全部」：安全隔离和启动期可读性存在张力，本文建议用「声明式能力 + 运行时强制」换「进程级隔离」，因为后者成本过高且当前需求未到。

## 5. 选项

### 选项 A：保持现状，就地加固

不引入新层。逐个完成 Eventa 窗口命名空间支持（或做一个 sender 过滤 helper），收敛契约归属，继续每窗口 manager 模式。

- **代价最低、风险最低**，能立即消除 `setMaxListeners(0)`。
- **但**：多窗口和插件能力授权仍是「每次手写」，没有把窗口身份变成可复用策略；组合根仍会随窗口数量增长。

### 选项 B（推荐）：引入「窗口 + 能力注册表」这一个 deep seam

核心是两件事：

1. **窗口身份一等公民化**：用一个 `createWindowContext(ipcMain, window)`（或 Eventa 原生支持）统一封装 sender 作用域、`setMaxListeners` 与 dispose-on-close，消除 ~16 处重复 TODO。
2. **能力声明式**：每个窗口用一个 descriptor 描述（preload 入口、route/loader、能力列表），一个注册表按 `webContents.id` 自动注册/作用域/清理 handler。组合根从「16 个 provider + 长 params」缩为「注册 app 服务 + 注册各窗口 descriptor」。

- **它解锁的能力**：多窗口 = 加一个 descriptor；插件能力授权 = 插件 manifest 请求 capability X，host 用已有的 `PermissionService` 判定后经同一注册表授予/拒绝。
- **假设**：窗口能力可以被离散枚举（从现有 `createXService` 列表看，成立）；Eventa 支持或允许按窗口作用域注册（**未知，需先验证**）。
- **迁移/回滚成本**：中等。每一步可独立回滚（见第 7 节）。

### 选项 C：插件进程级隔离（utility process / BrowserView / 独立 renderer）

- **现在不做**。当前插件 SDK 已在 widgets renderer 内用 iframe / extension session 隔离，`PermissionService` 也已存在。进程隔离只在插件面扩大或安全要求升级时重新评估。

## 6. 建议

选 **B**，但分阶段、可逆地走，第一阶段就是早已被 TODO 标记的「窗口命名空间上下文」，它本身独立有价值，也是后面所有步骤的地基。

**什么应当稳定（不推翻）**：

- Eventa 契约模型（`defineInvokeEventa` / `defineInvokeHandler` + 类型化 payload）。
- injeca 组合根（DI 保留，只是把窗口装配下沉到注册表）。
- 每窗口一个 manager 的目录布局。
- plugin-sdk 的 host/runtime/kit 分层 + `plugin-protocol` 权限模型。
- server-channel 作为「桌面 ↔ web/mobile」的跨面桥。

**什么应当变化**：

- 窗口作用域从「全局 ipcMain + 手动过滤」变为「窗口身份化上下文」。
- 每窗口的能力注册从「命令式 rpc/index.electron.ts」变为「descriptor 声明」。
- 契约归属：窗口专属契约放窗口目录，跨窗口/应用级契约留 `shared/eventa`，electron 通用契约归 `electron-eventa`。

**一个要现在顺手的重构**：按 `plugins/host/index.ts:437` 的 REVIEW 提示，把 tool registry 所有权从 kit runtime 上移到 host service——它正好和「能力注册表」同构，早做能避免插件能力面出现两个真相源。

## 7. 迁移与验证

每一步都可回滚（行为保持 + 独立提交 + 单独验证）：

1. **先验证未知项（零风险）**：装依赖后读 `@moeru/eventa` 的 electron adapter 源码，确认 `createContext(ipcMain, window)` 第二个参数的真实语义；写一个「两个窗口注册同一契约、断言消息只路由到对应 sender」的回归测试。这决定第 2 步是「扩展 eventa」还是「在应用层封装」。
2. **封装窗口作用域上下文（纯重构）**：引入 `createWindowEventaContext(ipcMain, window)`，内部承担 `setMaxListeners`、sender 过滤、`closed` 时清理。逐窗口迁移（先 notice/about 这种最简窗口）。**回滚**：revert 文件。**验证**：无 `MaxListenersExceededWarning`，`window code` 中不再有 `setMaxListeners(0)`。
3. **垂直切片**：拿 `notice`（`createReferencedWindowManager` 多实例）做第一个 descriptor + 注册表迁移，端到端证明「声明式多实例窗口」可行。
4. **能力模块化**：把 `setupBaseWindowElectronInvokes` 里的六类服务 + widgets/mcp/godot/auth/updater 抽成命名能力 descriptor，窗口声明自己的列表。**验证**：现有窗口行为不变（typecheck + 现有 vitest + 手工冒烟）。
5. **缩减组合根**：`injeca.provide('windows:registry')` 持有窗口生命周期，各窗口改为 `registry.register(descriptor)`。**验证**：`pnpm -F @proj-airi/stage-tamagotchi typecheck` + `build`（electron-vite 三目标仍打包成功）。
6. **对齐插件授权**：注册表的「能力」与 `plugin-protocol` 的 `capabilities` area + `PermissionService.isAllowed` 对齐；插件请求窗口/能力时经同一路径授予。**验证**：插件权限测试覆盖「请求未授权能力被拒」。
7. **（条件性，暂缓）能力化 preload**：把每个窗口的 preload 从「暴露原始 ipcRenderer」改为「按 descriptor 生成类型化 API」。**触发条件**：插件窗口成为现实需求、或安全审查要求收紧 renderer 面。此步之前不提前做，因为它会波及所有 `window.electron.ipcRenderer` 调用点。

**每步统一验证手段**：

- 类型：`pnpm -F @proj-airi/stage-tamagotchi typecheck`；lint：`pnpm lint`。
- 单元：窗口 manager 用 `vi.mock` 模拟 `ipcMain`/`BrowserWindow`（现有测试已大量采用此模式）。
- 回归：双窗口作用域测试（同一契约、不同 handler、断言 sender 路由）+ 现有 `scripts/desktop-overlay-live-window-smoke.ts` 模式扩展到多窗口冒烟。
- 构建：`pnpm -F @proj-airi/stage-tamagotchi build` 确保 preload/renderer 双入口不受影响。

**完成判据（可观察）**：新增一个窗口不再需要改组合根的依赖图；`src/main` 中不再出现 `setMaxListeners(0)`；一个插件能通过「请求能力 → host 校验 → 注册表授予」的同一路径获得窗口能力。

**现在不做的**：不引入通用跨窗口事件总线、不拆分 `stage-shared` 成微包、不做进程级插件隔离。等「插件自建窗口」或「权限面扩大」成为真实需求时再评估。

## 8. 待决问题（答案会改变建议）

1. **Eventa 的 electron adapter 目前是否已支持窗口命名空间**，只是应用没用？还是需要改 eventa？——决定第 2 步的落点（**未知**，第 7 节第 1 步即为此验证）。
2. **插件是否会拥有独立窗口**，还是只活在 widgets renderer 的 iframe / extension session 内？——决定能力注册表要走多深、preload 能力化是否提前。
3. **「窗口能力」与 `plugin-protocol` 的 `capabilities` area 是否为同一分类体系**？若否，需先统一术语，避免两套权限真相源。
4. **`stage-shared` 是否应拆成中性核心（webgpu/url/export-csv）与 Electron 耦合两部分**，或改为 build 产物包而非源码直连？——影响共享边界，但不阻塞本建议的前五步。

[EVAL:evolve-software-architecture-loaded]
