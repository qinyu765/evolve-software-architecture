# AIRI 桌面端边界评估（main / preload / renderer / 共享 package）

## 1. 范围与置信度

评估对象是 `apps/stage-tamagotchi`（Electron 桌面端）与它依赖的共享 package 之间的边界，目标是回答两个问题：未来第三方插件如何扩展能力，以及如何支持多窗口（同类型多实例 + 插件自有窗口）。本次只读、不修改代码。

仓库分类：pnpm monorepo + Electron 桌面应用（非 Tauri、非 Web），置信度高。证据：`electron.vite.config.ts` 明确拆成 main/preload/renderer 三段构建，`package.json` 的 `main` 指向 `./out/main/index.js`，并依赖 `electron`、`electron-vite`、`electron-builder`。未运行应用或构建，涉及运行时的结论均为推断并已标注。

## 2. 观察到的事实

**构建/进程边界**（`electron.vite.config.ts`）
- 三个构建目标：main、preload、renderer。preload 有两个入口（`index`、`beat-sync`，见 81–92 行）；renderer 有两个 HTML 入口（`main`、`beat-sync`，见 99–106 行）。
- main 与 renderer 都把 `stage-ui`、`stage-shared`、`i18n` 等内部包直接 alias 到源码，编译期共享源码而非共享编译产物（74–77、137–149 行）。这意味着“共享 package”在这两个运行时里实际是同源代码，边界主要靠导入路径纪律维持。

**主进程组合**（`src/main/index.ts`）
- 用 `injeca` 做 DI 容器，约 25 个 provider：配置、服务、模块、窗口、托盘。窗口之间的依赖是显式手动列出的，例如 `windows:settings` 依赖 12 个其他 provider（215–222 行），`windows:main` 依赖 11 个（224–232 行）。
- 注册的窗口：about、beat-sync、caption、chat、desktop-overlay（环境变量门控）、devtools、main、notice、onboarding、settings、spotlight、widgets；inlay 由 tray 按需创建（`src/main/tray/index.ts`）。`src/main/windows/dashboard/` 存在但未被 `index.ts` 引用（事实，来自 grep），是一个疑似已脱线的窗口模块。

**preload 边界**（`src/preload/shared.ts`）
- 两个 preload 入口都只调用 `expose()`，把 `@electron-toolkit/preload` 的 `electronAPI`（含完整 `ipcRenderer`）和 `platform` 暴露到 `window.electron`。`exposeWithCustomAPI`（暴露 `window.api`）已定义但当前没有任何入口使用。
- 所有我检查过的窗口都以 `sandbox: false` 创建（main: `src/main/windows/main/index.ts:90`，widgets: `widgets/index.ts:231`，devtools: `devtools/index.ts:42`），preload 依赖 Node 能力。
- renderer 侧直接拿裸 `ipcRenderer` 建 Eventa context：`createContext(window.electron.ipcRenderer)`（`src/renderer/stores/tools/builtin/widgets.ts:76`、`packages/electron-vueuse/src/composables/use-electron-eventa-context.ts:18`）。也就是说，preload 暴露的是**全量 IPC 通道**，类型安全只存在于调用点（Eventa 契约），不在传输层。

**renderer 边界**
- 标准 Vue 3 应用：hash router + 自动路由（`vue-router/auto-routes`），页面来自 `packages/stage-pages` 和 `src/renderer/pages`，布局来自 `src/renderer/layouts` 和 `packages/stage-layouts`。
- Electron 访问没有统一的 typed 客户端门面，而是分散的：模块级共享 context（`electron-vueuse` 的 `getElectronEventaContext`）加上各 store 自己建 invoker（`widgets.ts` 的 `createInvokers`）。

**共享契约的位置（事实：存在三个家）**
- `apps/stage-tamagotchi/src/shared/eventa/index.ts`：约 500 行的中心契约桶，混装了窗口操作、widgets、MCP、auth、i18n、godot-stage、快捷键、three.js 追踪、插件 host 等全部 domain。
- `packages/electron-eventa`：`electron.*`（screen/window/systemPreferences/app/powerMonitor/auto-updater）的薄契约。
- `packages/stage-shared`：`global-shortcut`、`godot-stage`、`server-channel-qr`、`beat-sync`、`auth/pkce`、`window` 等类型。
- 同一类“Electron 契约”散落三处，没有一条清晰规则说清“某种契约该放哪个包”。

**窗口模式（手写 + 已有抽象并存）**
- 每个窗口一个 `src/main/windows/<x>/index.ts`（可选再加 `rpc/index.electron.ts`），普遍重复：`new BrowserWindow` + 透明配置 + preload 路径 + `protectPrivilegedWindowNavigation` + `createContext(ipcMain, window)` + `setupBaseWindowElectronInvokes` + 窗口专属 `defineInvokeHandler`。
- 已抽出的抽象：`windows/shared/window.ts`（基础 invoke + 导航守卫 + 窗口配置）、`createReferencedWindowManager`（notice/widgets 式按 id 管理）、`createReusableWindow`（单例复用）、`windows/shared/display.ts`、`libs/electron/persistence.ts`（Valibot schema + autoHeal 配置持久化）。
- devtools 窗口已经实现“按 key 复用窗口 + 任意 route + bounds”的原型（`devtools/index.ts` 的 `reusableWindows: Map`）；widgets 窗口实现了更完整的模式：共享窗口 + 每 widget 的 `windowContexts` + iframe 请求关联 + TTL + always-on-top（`widgets/index.ts`）。

**插件架构（已相当完整）**
- `packages/plugin-sdk`：`ExtensionHost`（内存态、class 化）、`defineExtension/setup(ctx)` 创作 API、kit、权限（扩展级上限 ∩ 模块级授权两层）、capability（announced/ready/degraded/withdrawn）、resource、binding，以及 `electron|node|web` 三种运行时和 transport 判别联合（`in-memory|websocket|web-worker|node-worker|electron`）。
- `packages/plugin-sdk-tamagotchi`：两个 kit —— `kit.gamelet`（iframe 支撑的插件 UI：mount/open/configure/request/close）和 `kit.tool`（注册 xsai 工具 + toolset prompt）。
- Electron 接线：`services/airi/plugins/` 下有 IPC facade（list/load/unload/enable/inspect/tools/capabilities）、host 引导、manifest 发现（`<userData>/extensions/v1`）、静态资源服务、自动重载、kit 注册。插件 UI 表现为 widgets 窗口里的 `extension-ui` iframe（gamelet），通过 main → widgets renderer → iframe 的关联请求中继。
- **插件入口当前在主进程内以 `await import(entrypoint)` 执行**（`packages/plugin-sdk/src/plugin-host/runtimes/node/loaders/fs.ts:74`），host 在 main 里以 `runtime: 'electron'` 构造（`services/airi/plugins/host/index.ts:236`）。权限检查是 host 内的逻辑门（`PermissionService`、`assertExtensionPermission`），没有进程/隔离边界。
- SDK 已声明但**未实现**的隔离通道：node/web 运行时的 `createPluginContext` 对 websocket、node-worker、web-worker、electron 全部 throw，只有 `in-memory` 可用（`runtimes/node/index.ts:24-39`、`runtimes/web/index.ts:23-38`）。这说明隔离意图已写入类型，但还没有落地。

**窗口命名空间的既有信号**
- 多处 `ipcMain.setMaxListeners(0/100)` + 同一个 TODO：“once we refactored eventa to support window-namespaced contexts…”（`src/main/index.ts:55-58`、`windows/main/index.ts:211-214`、`windows/main/rpc/index.electron.ts:43-46`、`windows/shared/referenced-window.ts:41-44`、`windows/widgets/index.ts:322-325`）。推断：所有窗口共享同一个全局 `ipcMain` 事件总线，`createContext(ipcMain, window)` 目前用于把监听器生命周期绑定到窗口并做发送方过滤，尚不能做真正的窗口命名空间派发。

## 3. 当前摩擦

1. **新增一个窗口是多点改动**：新 `index.ts`（+可选 rpc）+ DI 注册 + preload 路径 + renderer 页面/路由 + `shared/eventa` 契约。样板代码虽有部分抽取，但没有一个“窗口注册表”统一拥有 window key → 工厂 → route → 契约命名空间的映射。
2. **全局 IPC 总线无命名空间**：所有窗口共享 `ipcMain`，靠 `setMaxListeners` 和 context 的发送方过滤硬扛。同类型多实例（比如两个 chat 窗口）或插件自有窗口会进一步放大这个冲突（事实 + 推断）。
3. **契约中心桶扁平且跨域**：500 行的 `eventa/index.ts` 把窗口、MCP、widgets、auth、插件全混在一起，还夹杂本地手抄类型（`PluginCapabilityPayload` 等，带“等 plugin-sdk 可依赖后改 re-export”的 TODO，218–221 行）。
4. **preload 是全量 IPC 桥**：renderer 拿到裸 `ipcRenderer`，可 invoke 任意通道。对可信 AIRI 代码够用，但对“插件 UI 与系统 UI 共享 renderer”的未来，缺少按能力的窄桥。
5. **插件在主进程内运行**：第三方插件一旦落地，一个同步阻塞/未捕获异常/越权调用 Electron API 的插件就能卡死或拖垮主进程。SDK 的类型层已经为隔离预留了位置，但当前没有任何运行时使用它。
6. **三套重叠的“窗口管理”抽象**（reusable / referenced / devtools keyed map / widgets windowContexts）各自编码了略微不同的复用与生命周期语义，缺少统一的窗口所有权模型。
7. **DI 图集中且线性增长**：`main/index.ts` 手动列出所有窗口与传递依赖。25 个节点尚可，但插件贡献的窗口/服务无法自然插入这个静态图。
8. **共享包边界漂移**：Electron 契约存在三处，`stage-shared` 里还混有 `electron-renderer.d.ts`；`stage-ui` 等以源码 alias 方式同时服务于 web 与桌面，包边界的实际约束弱。

## 4. 质量属性优先级

| 优先级 | 属性 | 说明 | 权衡 |
|---|---|---|---|
| 1 | 可扩展性 | 插件能加能力/UI/窗口而不改核心；既有窗口可多实例 | 先于其他属性，是本次决策的驱动目标 |
| 2 | 隔离/安全 | 插件不应拥有主进程全部权限 | 与简单性冲突：进程隔离增加复杂度与延迟，需分阶段 |
| 3 | 可演化性 | 消除 N 触点仪式；用深 seam 取代逐窗口样板 | 需要一次小重构，但收益随窗口数增长 |
| 4 | 可运维性 | 生命周期、dispose、错误遏制、按窗口/会话拆除 | 与“手写窗口”现状冲突最大 |
| 5 | 可测试性 | 契约与 host 不依赖真实 Electron 运行时即可测 | 目前已有较多 `.test.ts`，继续沿用 |
| 6 | 性能 | 不是主导因素；窗口很轻 | 唯一相关点：进程内插件崩溃 = 主进程崩溃 |

## 5. 选项

**选项 A —— 维持现状，做增量硬化。** 保留进程内 host、全局 Eventa 通道、手写窗口；等 eventa 支持命名空间后去掉 `setMaxListeners`；加插件权限确认 UI；适度收窄 preload。成本最低，但不移除结构耦合；chat/settings 多实例仍别扭；插件隔离停留在逻辑门。作为“什么都别做”的对照依然站得住脚，只是无法承载“未来插件 + 多窗口”的路线。

**选项 B —— 引入两个深 seam：窗口注册表 + 插件运行时隔离，分阶段推进。** 把窗口创建与契约命名空间收敛到一个 `WindowDefinition`/窗口注册表（devtools 的 keyed map、widgets 的 windowContexts、referenced-window 是现成原型），并用 SDK 已声明但未实现的 `node-worker`/`websocket` transport 把插件入口移出主进程。这是长期方向，但分两个可逆阶段落地。

**选项 C —— 现在就把插件游戏件（gamelet）升级为任意原生 Electron 窗口，给插件原生 preload。** 能力最强，但过早：在隔离尚未存在时扩大插件攻击面，且当前插件 UI 是更安全的 iframe gamelet。**先否决，待选项 B 的隔离落地后再重估。**

## 6. 建议

采用**选项 B**，按“窗口注册表 → 插件隔离 → 多实例/插件窗口”的顺序推进，每个阶段都是可逆的：

- **阶段 1（低成本、高杠杆、行为不变）：窗口注册表 + 契约拆桶。**
  - 把 `src/shared/eventa/index.ts` 按 domain 拆成多个模块（`windows/`、`plugins/`、`mcp/`、`system/`），原桶只做 re-export，纯移动、不改任何导入。
  - 定义 `WindowDefinition`（id、kind、route、preload、bounds 策略、生命周期语义 singleton/keyed/per-instance、契约命名空间），用一个 `windowRegistry` 统一 create/load/preload/base-invokes。先迁一个窗口做垂直切片（建议 devtools 或 about），其余窗口逐步迁移。
  - 等 eventa 支持窗口命名空间后（或自己补），用命名空间替代 `setMaxListeners(0/100)` 和手工 sender 过滤；在此之前把“context 绑定到 window”的相关性规则显式写进注释。

- **阶段 2（插件隔离）：实现 SDK 里已声明的 transport。** 用 `node-worker` 把插件入口跑出主进程，kit/permission/binding 协议走既有 channel 抽象；内置/开发期插件保留进程内 `electron` 运行时作为默认回退（环境变量切换）。补一个 host 级权限确认 UI。这是安全属性从“逻辑门”到“进程边界”的关键一步，也是未来放开第三方插件的前置条件。

- **阶段 3（多窗口实例 + 插件窗口）：** 在注册表 + 命名空间就位后，允许 `openWindow(kind, { instanceId })` 支持 chat/settings/devtools 多实例；插件 gamelet 若需要额外窗口，只通过 host 门控的 window capability 申请，不直接拿到 `BrowserWindow`。

这条路径的“深模块”判断：窗口注册表和插件运行时是两个值得投资的 seam——它们各自隐藏了“什么是窗口、谁拥有生命周期、窗口暴露什么契约”和“插件在哪运行、如何被授权、如何被拆除”这两组决策。除此之外，不建议再铺一层泛化的“服务层”或给每个内部 helper 造依赖对象。

## 7. 迁移与验证

**可逆步骤与首个垂直切片**
1. 契约拆桶：`eventa/index.ts` 只留 re-export，domain 文件就地成立。回滚成本 ≈ 零（路径不变）。
2. 窗口注册表：先做 `devtools`（已有 keyed map）或 `about`（最简单）这一个窗口。验收：同一 route/bounds/preload 行为不变，typecheck + lint + 该窗口相关 Vitest 通过。
3. 插件隔离：实现 `node-worker` transport，跑一个样例插件出进程，保留进程内回退。验收：一个会同步阻塞/抛错/越权访问 Electron 的插件不再拖垮主进程。

**验证方法**
- **契约测试走 Eventa 接口**，不依赖真实 Electron：仓库已有大量 `*.test.ts` 与契约同放，继续沿用（如 `desktop-overlay/window-contract.test.ts`、`plugins/index.test.ts`、`plugin-sdk` 的 core/kits/permissions 测试）。
- **架构一致性测试**（把 N 触点仪式变成可失败的断言）：遍历 `src/main/windows/*`，断言每个窗口在注册表里恰好有一条定义、有匹配的 renderer route、preload 入口和契约命名空间；缺一项测试就点名缺哪步。同类地，可加一条依赖规则测试，禁止 renderer 直接 import main-only 模块。
- **插件隔离测试**：按 AGENTS.md 的偏好，用 `node:worker_threads` 加载插件并验证主进程不被阻塞/不被杀，而不是 `Object.defineProperty` 硬 mock 全局。
- **生命周期/dispose 测试**：开 N 个 keyed 窗口后退出，断言所有 context 已 dispose、监听器已移除（现有 `single-instance.test.ts`、`window-contract.test.ts` 是起点）。
- **常规门禁**：`pnpm -F @proj-airi/stage-tamagotchi typecheck`、`pnpm lint`、定向 `pnpm exec vitest run <path>`。阶段 1 只做纯重构，测试应全绿且行为不变，这是“可逆”的判据。

**完成判据**：新增一种窗口只改注册表 + 契约 + 页面（不再手写 `BrowserWindow`/导航守卫/基础 invoke）；插件默认在隔离运行时启动且失败被遏制；同类型窗口可开多实例且互不串事件。**尚不要做的**：给插件开放原生 `BrowserWindow`（先隔离）、给所有内部函数造 DI 对象、把 `stage-ui` 切成双份包——等有实际证据（发布第三方插件、出现两个 chat 窗口的真实需求）再触发。

## 8. 待决问题

这些问题的答案会直接改变建议的优先级，建议用 ADR 记录：

1. **第三方（不可信）插件是否在路线图上？** 若是，阶段 2 的进程隔离必须排在多窗口之前；若长期只有可信内置/开发者插件，隔离可延后。这是**未知**，SDK 目前标注 “working in progress”，插件示例仍是 devtools 样例。
2. **eventa 的窗口命名空间上游是否已支持，还是需要 AIRI 自己实现？** 这决定阶段 1 里去掉 `setMaxListeners` 的时机和成本。当前只是 TODO 引用，属**未知**。
3. **多窗口的真实形态是什么：同类型多实例（chat/settings），还是主要面向插件自有窗口？** 决定阶段 3 的投入规模，也决定窗口注册表里 per-instance 语义要设计得多完整。
4. **`src/main/windows/dashboard/` 是否已废弃？** 它未被 `main/index.ts` 注册。清理/接线会缩小窗口清单，也让窗口注册表的迁移清单更可信。

[EVAL:evolve-software-architecture-loaded]
