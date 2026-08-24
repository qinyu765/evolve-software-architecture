# AIRI 桌面应用（stage-tamagotchi）进程与 package 边界评估

## 1. 范围与结论置信度

评估对象是 `apps/stage-tamagotchi` 的四个运行时边界（main / preload / renderer / `src/shared`）与它依赖的 `packages/` 共享包，目标是回答：**未来插件能力与多窗口扩展应该把 seam 放在哪里、按什么顺序迁移、如何验证**。

- 仓库类型：**Electron 桌面应用**，且已是事实上的**多窗口应用**（13 个窗口类型），monorepo（pnpm workspace）。分类置信度：**高**（多信号一致：`electron-vite.config.ts`、`electron-builder.config.ts`、`src/main`/`src/preload`/`src/renderer` 三进程结构、原生模块 `uiohook-napi`/`electron-click-drag-plugin`）。
- 本评估只读、不改代码，结论只到"可决策"为止，不预设一个需要现在就买的昂贵抽象。

---

## 2. 观察到的现状（证据）

| 断言 | 证据 | 类型 | 置信度 | 对决策的影响 |
| --- | --- | --- | --- | --- |
| 已是 13 个窗口类型的多窗口应用 | `src/main/windows/` 下 about/beat-sync/caption/chat/dashboard/desktop-overlay/devtools/inlay/main/notice/onboarding/settings/spotlight/widgets | 事实 | 高 | "多窗口"不是未来需求，是已存在的、半手工实现的现状 |
| 每个窗口都有 `setupXxxWindow` + 可选 `rpc/index.electron.ts` | `src/main/windows/main/index.ts:52`、`windows/chat/index.ts:17`、`windows/widgets/index.ts:290` | 事实 | 高 | 窗口创建与 IPC 绑定已经局部化到 `windows/<name>/`，这是可复用的雏形 |
| 存在两种窗口管理抽象 | `createReusableWindow`（单例，`libs/electron/window-manager/reusable.ts:5`）vs `createReferencedWindowManager`（按 id 多实例，`windows/shared/referenced-window.ts:31`） | 事实 | 高 | 单例/多实例是两套手写逻辑，未统一为一个 seam |
| Eventa 缺少窗口级命名空间，用全局监听上限 + 逐 handler 守卫兜底 | 同一 TODO 注释出现在 `main/index.ts:55`、`preload/shared.ts:9`、`referenced-window.ts:41`、`main/index.ts:211`；`ipcMain.setMaxListeners(0)` 出现 15+ 处、根处 `setMaxListeners(100)`；`createWindowService` 每个 handler 都判 `sender.id === webContents.id`（`services/electron/window.ts:45-122`） | 事实 | 高 | 这是**最大的变更放大点**：每加一个窗口类型都要复制同一套守卫与 `setMaxListeners` |
| 插件宿主已经是"深模块"，有权限/kit/binding/capability/session/dispose 模型 | `packages/plugin-sdk/src/plugin-host/core.ts`（`ExtensionHost` 类、双层权限校验、`FileSystemLoader`、`channels/local` 与 `channels/remote/websocket`） | 事实 | 高 | 插件能力的地基已存在，**不需要重建**，只需把 Electron 集成与类型所有权对齐 |
| 插件 IPC 是全局上下文（不绑定窗口） | `services/airi/plugins/index.ts:49` 用 `createContext(ipcMain)`（无 window 参数） | 事实 | 高 | 插件生命周期/工具调用应保持全局；插件 UI 才需要窗口作用域，两者要分开 |
| 插件 UI 走 iframe 沙箱中继，而非直接暴露 ipcRenderer | `windows/widgets/iframe-request-coordinator.ts`、`kits/gamelet/orchestration.ts`；测试中 iframe `sandbox: 'allow-scripts allow-same-origin allow-forms allow-popups'`（`plugins/index.test.ts:796`） | 事实 | 高 | 这是值得保留并推广的隔离边界 |
| 渲染器侧 Eventa context 是模块级单例 | `packages/electron-vueuse/src/composables/use-electron-eventa-context.ts:27`（`sharedContext ??=`） | 事实 | 高 | 渲染器侧同样没有窗口作用域概念（各窗口 renderer 进程彼此独立，故"单例"是每窗口一个，但代码不区分） |
| preload 面过宽：所有窗口共用一份 preload，暴露整个 `electronAPI` | `preload/shared.ts:19` `contextBridge.exposeInMainWorld('electron', electronAPI)`；13 个窗口全部 `sandbox: false` | 事实 | 高 | 任意窗口 renderer 可 `ipcRenderer.send/invoke` 任意通道，是安全/契约面问题 |
| `src/shared/eventa/index.ts` 是 500+ 行的"契约大杂烩" | 该文件混装 window 命令、MCP、Godot、updater、shortcut、auth、i18n、widgets、plugin | 事实 | 高 | 变更局部性差，且是类型重复的宿主 |
| 插件渲染侧类型在**两个文件重复且形状冲突** | `shared/eventa/index.ts:204-247` 的 `PluginHostDebugSnapshot` 缺 `kits`/`modules`，`PluginManifestSummary` 缺 `autoReload`；而 `shared/eventa/plugin/host.ts:60/180` 是新版（带这些字段）。`index.ts` 又 `export * from './plugin/host'`，本地声明遮蔽 re-export | 事实 | 高 | 静默遮蔽，是潜在 bug 源；`plugins/host/*` 直接 import `plugin/host` 新类型，而根 barrel 导出旧类型 |
| 共享包已按职责分层 | `plugin-sdk`（运行时无关）/`plugin-sdk-tamagotchi`（Tamagotchi kit）/`plugin-protocol`（协议类型）；`electron-eventa`/`electron-vueuse`/`electron-screen-capture`（Electron 专属）；`stage-shared`（跨 surface） | 事实 | 高 | 分层方向正确，问题在于 app 内 `src/shared/eventa` 复制了应归 SDK 所有的类型 |
| 无 ADR 记录，`docs/solutions/` 仅 1 条 | Glob 无 `adr/`、无 `*.adr.md` | 事实 | 高 | 这类边界决策此前靠 TODO 注释传递，缺 ADR 支撑 |
| 组合根较大且手动接线 | `main/index.ts` 注册约 20 个 `injeca.provide`，含 desktop-overlay 的"单独 invoke 强制构建"workaround（`:251-257`） | 事实 | 高 | 加窗口要动组合根多处，是热点 |

---

## 3. 当前摩擦（真正花钱的地方）

1. **窗口不是一等 seam。** "窗口"这一概念在 IPC 层没有统一载体，而是靠 `createReusableWindow` / `createReferencedWindowManager` / 每个 `windows/*/index.ts` 里手工 `new BrowserWindow` 三条路并存。后果：单例→多实例（未来多窗口）要重写，而不是改一个参数。

2. **Eventa 窗口路由是手工补偿。** 15+ 处 `setMaxListeners(0)` + 每个 handler 重复 `sender.id === window.webContents.id`。这是最清晰的变更放大证据：每新增一个窗口类型，这套补偿代码被复制一次。TODO 注释自己承认这是技术债。

3. **契约层两处重复。** 插件渲染侧快照类型在 `shared/eventa/index.ts` 与 `shared/eventa/plugin/host.ts` 里并存且形状不一致，靠 `export *` 的静默遮蔽暂时没爆。这是最便宜、最该先清掉的债。

4. **preload 面过宽 + `sandbox: false`。** 每个窗口（包括 overlay、widgets、beat-sync 这种工具窗口）都拿到完整 `electronAPI`。对插件能力而言，这意味着：如果插件 UI 未来拿到比 iframe 中继更宽的入口，攻击面会立即放大。

5. **类型所有权错位。** `@proj-airi/plugin-sdk` 已经定义了 `CapabilityDescriptor` 等类型，但 app 层因"担心耦合"而手工复制（`shared/eventa/plugin/capabilities.ts:42-44` 的 TODO）。这违背了 AGENTS.md 自己写的"从拥有契约的模块导入类型、必要时拆 side-effect-free 类型模块"原则。

---

## 4. 质量属性优先级（按本次决策排序）

| 优先级 | 属性 | 目标/预算 | 现状证据 | 会牺牲什么 |
| --- | --- | --- | --- | --- |
| 1 | **进程边界稳定性 / 可扩展性**（并列，同一 seam 服务两者） | 新增窗口类型或插件 UI 不再复制 IPC 守卫；契约可版本化 | `setMaxListeners` 15+ 处、逐 handler 守卫、契约大杂烩 | 一次性迁移成本 |
| 2 | **安全性** | 插件/第三方代码的最小权限入口；窗口级 preload 面最小化 | 13 窗口 `sandbox:false`、全量 `electronAPI` 暴露 | 部分 renderer 便利性 |
| 3 | **可测试性** | 不启动 Electron 就能测契约 | 已有 `*.test.ts` 覆盖 registry/window-contract，但 IPC 路由跨 seam 的测试少 | — |
| 4 | **可运维性** | 生命周期/dispose 显式、失败可诊断 | 已有 file-logger、lifecycle hook、`handleAppExit`；插件 `dispose` 齐全 | — |

性能/资源此处不作为决策驱动（无证据表明是当前瓶颈）；可维护性被"进程边界稳定性"覆盖。

---

## 5. 方案对比

### 方案 A：维持现状，只做局部硬化
保留两套窗口管理器与手写守卫，只做：删重复插件类型、把 `sender.id` 守卫抽成一个 helper、拆分 `index.ts` 契约文件。
- **边界**：仍是"窗口创建/绑定/路由三件事分散"，不变。
- **收益**：立即止血，成本最低。
- **代价**：多窗口扩展的变更放大问题原样保留；每加窗口仍需复制补偿代码。
- **反证信号**：若确认未来只有少量固定窗口、无插件 UI 多实例需求，则 A 可长期成立。

### 方案 B（推荐）：把"窗口"提升为一等 seam
统一 `createReusableWindow` + `createReferencedWindowManager` + `setupXxxElectronInvokes` 为一个**窗口宿主（window host）**：负责创建、preload 绑定、**窗口作用域 eventa context**、基础 invokes、导航守卫、持久化、teardown。同时把窗口作用域路由推进到 `@moeru/eventa`（或本地 adapter），并迁移现有窗口逐个落到新 seam 上。
- **边界**：窗口宿主成为唯一的所有者；单例只是"固定 id 的实例集合"的特例。
- **收益**：新增窗口 = 声明 `{ id, entry, preload, binds }`；插件 UI 未来可通过 `window` kit 打开窗口，而不是绕过宿主直达 Electron。
- **代价**：一次渐进迁移（每个窗口独立可回滚）。
- **反证信号**：如果 `@moeru/eventa` 上游窗口命名空间迟迟不落地且本地 adapter 也做不动，则 B 的收益打折——但本地 adapter 包装是可控的。

### 方案 C：现在就把每个插件丢进 `utilityProcess` / 独立沙箱渲染进程
- **边界**：进程级隔离最强。
- **收益**：对不可信插件分发最安全。
- **代价**：过早。SDK 的 `channels/remote/websocket` 已经预留了这条路的 seam，**今天不需要**；在只有一个内部插件生态、没有"任意第三方分发"事实前，这是过度投入。
- **反证信号**：一旦决定公开分发不可信第三方插件，立即启用 C（复用已有 channel 抽象）。

---

## 6. 长期架构方向

**应保持稳定（invariant）：**
- `plugin-sdk` 的权限/kit/binding/capability/session 模型——这是正确的地基，别推倒。
- **窗口作用域 eventa seam**——这是未来多窗口与插件 UI 的共同地基。
- **gamelet iframe 沙箱中继**——插件 UI 的最小权限入口，别让插件 UI 拿到 `ipcRenderer`。

**允许变化（variation）：**
- 窗口类型与数量、插件 kit 种类、单例 vs 多实例（由窗口宿主统一表达）。

**仍未知、要最便宜地去验证（unknown）：**
1. 哪些窗口类型未来真的需要**多实例**？今天只有 notice/widgets 按 id 走多实例，而 widgets 实际又折叠回单个 reusable 窗口。在写通用多实例框架前，先用一个真实用例验证。
2. 是否要公开分发不可信第三方插件？决定是否启动方案 C。
3. `@moeru/eventa` 上游窗口命名空间何时落地？决定本地 adapter 的寿命。

**不建议现在建的东西：**
- 通用多实例窗口框架（在没有第二个真实多实例窗口前）。
- 插件 `utilityProcess` 强隔离（在不可信分发成为事实前）。
- 一个全新的"插件桥接总线"——现有的 eventa + kit 已经够用，缺的是窗口作用域而不是新总线。

---

## 7. 可逆迁移步骤与验证方法

每步独立可回滚、行为保持，先做最便宜、收益最高的一步。

**Step 0 — 先立回归网（这是安全网，先于任何改动）**
- 为"窗口作用域 invoke 只到达本窗口"写契约测试：两个 `BrowserWindow` stub + fake `webContents.id`，断言跨窗口调用不泄漏。
- 为插件工具 `list/invoke` 写带 fake `ExtensionHost` 的往返测试（现有 `plugins/index.test.ts` 已有雏形，可扩展）。

**Step 1 — 删重复插件类型（纯机械、类型检查可证）**
- 删除 `shared/eventa/index.ts:204-247` 的旧 `PluginManifestSummary`/`PluginRegistrySnapshot`/`PluginHostDebugSnapshot` 等，统一 re-export `./plugin/host`。
- 验证：`pnpm -F @proj-airi/stage-tamagotchi typecheck` + 全量 vitest。

**Step 2 — 拆契约大杂烩（纯移动、无行为变化）**
- 把 `shared/eventa/index.ts` 按域拆成 `window-open.ts`/`mcp.ts`/`godot.ts`/`updater.ts`/`shortcut.ts`/`auth.ts`/`i18n.ts`，index 仅作 barrel。沿用已有的 `plugin/` 子目录先例。
- 验证：typecheck + lint（`pnpm lint`）。

**Step 3 — 引入窗口作用域包装，先迁移重复最多的 `createWindowService`**
- 抽一个 `createScopedWindowContext(ipcMain, window)` 把 `sender.id === webContents.id` 守卫 + listener 管理收进一处；`createWindowService`（`services/electron/window.ts`）是最大重复者，先迁它。
- 验证：`services/electron` 相关单测 + 一个窗口的运行时冒烟（dev 模式手动验证多窗口同时开不串事件）。

**Step 4 — 逐个窗口迁移到统一窗口宿主**
- 从最简单的 `about` 或 `chat` 开始，把 `createReusableWindow` + `setupXxxInvokes` 换成宿主调用；跑通一个窗口后复制模式。每迁移一个窗口即可单独 revert。
- 验证：每个窗口的既有 `rpc/*.electron.test.ts`（若有）+ 打包冒烟。

**Step 5 — 插件 UI 走 `window` kit（在宿主存在之后）**
- 当窗口宿主稳定后，才把它以 kit 形式注册进插件宿主，插件通过权限申请打开窗口作用域 UI，而不是直接碰 Electron。
- 验证：用 fake kit 测权限拒绝/授予路径。

**Step 6（延后）— 上游 eventa 窗口命名空间落地后，删除 `setMaxListeners` 补偿**
- 这是唯一一个"等上游"的步骤；在那之前 Step 3 的本地包装已让补偿代码收敛到一处。

**通用验证清单（每步 + 收尾）：**
- `pnpm -F @proj-airi/stage-tamagotchi typecheck`、`pnpm lint`、目标 vitest（契约测试必须跨 seam）。
- 边界 lint：加 `no-restricted-imports` 阻止 renderer→main、renderer→Node builtins、以及 preload/eventa adapter 之外的裸 `ipcRenderer` 使用。这是防回退的架构闸。
- 打包冒烟：已有 `scripts/desktop-overlay-live-window-smoke.ts` 的模式可推广为"多窗口同时存活"冒烟。
- 观测点：startup/shutdown、`handleAppExit`、`single-instance` 已有日志与测试，迁移后确认无回归。

**完成判据：** 新增一个窗口类型不再需要写任何 `setMaxListeners` 或 `sender.id` 守卫；`shared/eventa/index.ts` 只剩 barrel re-export；插件渲染侧类型单一来源。

---

## 8. 待决问题（只有这些的答案能改变推荐）

1. **哪些窗口未来真要多实例？** → 决定 Step 4 里宿主是否现在就支持 N 实例，还是继续"单例=固定 id"。
2. **是否计划公开分发不可信第三方插件？** → 决定是否把方案 C（`utilityProcess`/独立沙箱）提前。
3. **`@moeru/eventa` 窗口命名空间是否在短期路线图上？** → 决定 Step 3 的本地包装是临时补偿还是长期形态。
4. **`sandbox: false` + 全量 `electronAPI` 是否有硬依赖？** → 决定 preload 面收窄能收多狠（需要查每个窗口 renderer 是否真的依赖裸 `ipcRenderer`）。

**建议立 ADR 的三个决策**（按 `decision-record.md` 模板）：① "窗口作为一等 seam / eventa 窗口命名空间方向"；② "preload 面收窄与 sandbox 策略"；③ "插件渲染侧契约类型所有权归属（SDK vs app）"。这三个的 rationale 对未来复审是承重的，不该继续只活在 TODO 注释里。

[EVAL:evolve-software-architecture-loaded]
