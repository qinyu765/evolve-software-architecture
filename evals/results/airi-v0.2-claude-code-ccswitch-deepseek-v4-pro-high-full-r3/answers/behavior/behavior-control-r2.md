以下评估全部基于对当前仓库的实际阅读（Electron 主进程、Eventa 契约、插件 SDK、server-* 包、窗口管理器），不修改任何代码。结论先行：**仓库里已经有一个比预期成熟的插件协议栈和独立后台运行时，真正缺的不是新抽象，而是把三处已经显露裂缝的边界收口**——事件命名空间、IPC 类型唯一来源、以及"后台能力 = server-runtime"的复用纪律。建议走"先稳定契约、后做框架"的渐进路线，而不是一步到位地设计通用插件 API / 统一窗口框架 / 后台进程拆分。

---

## 一、现状（以可检查的证据为准）

**第三方插件方向：底座已经存在，且分层不错。**
- `packages/plugin-protocol` 定义了线级协议：扩展/模块/kit 身份（`ExtensionIdentity`、`ExtensionModuleIdentity`、`ExtensionKitIdentity`）、权限声明与授予（`ModulePermissionDeclaration/Grant`）、能力生命周期、以及完整的 `ProtocolEvents` 事件字典（`packages/plugin-protocol/src/types/events.ts`）。
- `packages/plugin-sdk` 提供运行时无关的 `ExtensionHost`（`packages/plugin-sdk/src/plugin-host/core.ts:205`），支持 `electron/node/web` 三种 runtime，`ExtensionManifestV1` 带 `apiVersion: 'v1'` 和 schema 校验（`packages/plugin-sdk/src/plugin-host/shared/types.ts:233`、`:322`）。
- `packages/plugin-sdk-tamagotchi` 提供桌面侧的 kit：`gamelet`、`tool`、`widget`。
- 桌面侧已经接好了 host 引导、磁盘发现（`<userData>/extensions/v1` + `extension.airi.json`）、enablement 配置（`extensions-v1.json`）、静态资源服务、auto-reload（`apps/stage-tamagotchi/src/main/services/airi/plugins/host/index.ts:224` 起）。

**更多窗口方向：窗口数量已经很大，但每个窗口都是独立 manager。**
- 主进程 composition root `apps/stage-tamagotchi/src/main/index.ts:130` 起手动用 injeca 装配了 14+ 个窗口（main、chat、settings、caption、notice、onboarding、about、spotlight、widgets、devtools、desktop-overlay、beat-sync、dashboard、inlay）。
- 已有两种复用模式：`createReusableWindow`（单例窗口，`apps/stage-tamagotchi/src/main/libs/electron/window-manager/reusable.ts`）和 `createReferencedWindowManager`（per-id 生命周期 + 页面挂载/卸载协议，`apps/stage-tamagotchi/src/main/windows/shared/referenced-window.ts`）。

**独立后台方向：运行时已经可以 headless 跑。**
- `packages/server-runtime` 提供 `setupApp`（H3 + better-ws，含认证、peer/module 注册、consumer 路由、心跳）和 `createServer`（`start/stop/restart/updateConfig`，`packages/server-runtime/src/server/index.ts:108`）。
- `packages/server-runtime/src/bin/run.ts` 就是独立进程入口；桌面内嵌的 `channel-server` 复用同一个 `createServer`（`apps/stage-tamagotchi/src/main/services/airi/channel-server/index.ts:367`）。

**三处已经写在代码里的裂缝（这是本次评估最重要的输入）：**

1. **Eventa 没有窗口命名空间，靠 `setMaxListeners` 硬扛。** 同样的 TODO 注释和 `ipcMain.setMaxListeners(0)` / `ipcRenderer.setMaxListeners(0)` 出现了 15+ 处（`main/index.ts:55`、`referenced-window.ts:41`、`preload/shared.ts:9`，以及 main/chat/settings/widgets/about/dashboard/inlay/onboarding/desktop-overlay/caption 等各自 rpc 文件）。每个窗口都在和同一个全局 `ipcMain` 建 context，这是"更多窗口"方向上最不稳定的地基。

2. **共享 IPC 契约层在抄类型，且已经漂移。** `apps/stage-tamagotchi/src/shared/eventa/index.ts:204` 手抄了 `PluginManifestSummary`（缺 `autoReload`），而 `apps/stage-tamagotchi/src/shared/eventa/plugin/host.ts:60` 又定义了一份带 `autoReload` 的同名类型；`capabilities.ts:42` 的 TODO 明确承认这些类型本应从 `@proj-airi/plugin-sdk` re-export。

3. **插件 host 直接依赖具体的 `widgetsManager`，后台与协议也有分叉信号。** `SetupExtensionHostOptions` 只有 `{ widgetsManager }`（`apps/stage-tamagotchi/src/main/services/airi/plugins/types.ts:71`），gamelet kit 通过 `componentName: 'extension-ui'` 把"插件 UI"和"widgets 窗口"焊死（`kits/gamelet/orchestration.ts:26`）；`server-runtime` 里 legacy indexed 路由和 identity-based 路由并存（`packages/server-runtime/src/index.ts:323` 的 REVIEW）、`/ws` 路径字面量在三处重复（`channel-server/index.ts:103` 的 TODO）。

---

## 二、应该稳定的边界（低实现成本、高未来收益）

这些是"契约"，不是"框架"。稳定它们不需要猜未来的抽象，只需要把已经在用的事实收口。

**B1. 插件线级协议作为唯一权威来源（`plugin-protocol` 已是正确归宿）。**
第三方插件的真正 ABI 是 `ExtensionManifestV1`、身份模型、权限模型、能力生命周期和 `ProtocolEvents`。桌面 `shared/eventa` 层只应该 re-export 类型、定义"invoke 通道名"，不再手抄 `PluginManifestSummary`/`PluginCapabilityPayload` 等结构。`plugins/host/registry.ts` 里的 `createPluginSummary` 已经证明这些快照类型可以从 SDK 类型派生。

**B2. 窗口作用域的事件上下文（这是多窗口的基础设施）。**
今天的 `createContext(ipcMain, window)` + `setMaxListeners(0)` 是"带补丁的窗口命名空间"。把它变成一等能力：要么在 Eventa 里支持 window-namespaced context，要么在桌面侧收敛成一个 `createWindowContext(window)` helper 并在内部统一处理 listener 上限和窗口关闭清理。这一步不改变任何协议语义，只改分发机制，因此风险最低、回滚最容易。

**B3. 每个窗口的最小 manager 契约（不是统一框架）。**
应稳定的是每个窗口 manager 的"外观"：`open/close` + 窗口句柄 + window-scoped context + `setupBaseWindowElectronInvokes`（已在 `windows/shared/window.ts:134`）。新窗口二选一：单例走 `createReusableWindow`，多实例/按 id 走 `createReferencedWindowManager`。这样"更多窗口"的边际成本是加一个 manager + 一个 injeca provider，而不是发明新机制。

**B4. 生命周期与资源所有权。**
单实例锁（端口/资源唯一性，`single-instance.ts:45`）、injeca 的 `start/stop`、插件 host 的 `dispose/stop`、server-channel 的幂等 `start/stop/restart` 已经是事实标准。任何"独立后台"都必须走 `server-runtime` 的 `createServer`（`start/stop/updateConfig`），不另起一套。这决定了桌面内嵌后台和 headless 后台共享同一份状态机。

**B5. 配置与持久化的 schema 入口。**
`createConfig`（Valibot schema + `autoHeal`）已经统一了窗口 bounds、插件 enablement、server-channel 配置。新增窗口/插件/后台的持久化都应沿用它，而不是各自写 JSON 文件。

---

## 三、应该延后的抽象（现在做会猜错）

**D1. 延后"把 Electron 全能力一次性暴露成插件 API"。**
现在 kits 只有 gamelet/tool/widget，能力面是字符串 key。不要急着把窗口、托盘、全局快捷键、屏幕捕获、MCP 都做成插件 kit。按需、按 kit 逐个暴露，每个 kit 配 permission + capability 生命周期（announced/ready/degraded/withdrawn）。

**D2. 延后"统一窗口框架/通用 window-manager 泛型"。**
14 个窗口形态差异很大（主窗 panel、透明 overlay、后台 beat-sync 窗、按 id 的通知窗）。现在收敛成一个泛型框架大概率猜错抽象。保留 per-window manager，只稳定 B3 的契约面。

**D3. 延后"把桌面主进程拆成独立后台守护进程"。**
这是"独立后台"方向最容易过度设计的地方。headless 能力已经有 `bin/run.ts`，桌面已经内嵌同一 `createServer`。进程拆分意味着要重新协调单实例锁、端口 6121 绑定、证书信任、配置并发写——复杂度爆炸。等有真实压力（崩溃隔离、升级不打断、多用户）再做。

**D4. 延后 `server-runtime` 的协议 cleanup（legacy 路由、`/ws` 去重、`missedHeartbeats` 命名）。**
这些是内聚重构，不阻塞桌面能力。在协议边界稳定前做，会在协议变动时重复返工。

**D5. 延后插件签名/市场/分发/权限 UI 全流程。**
第三方插件真正的难点是信任模型，不是加载机制。host 已有 `permissionResolver` 挂点（`plugin-host/core.ts:224`）。先稳定线级权限模型和 resolver seam，签名/审核/权限提示 UI 后置。

**一个必须提前点名的安全事实（影响 D5 的优先级）：** 当前插件运行在 **Electron 主进程里**，拥有主进程同等的文件系统、网络、userData 访问权；manifest 里的 permissions 是**应用层门禁**（host 内的 `PermissionService` 拒绝 kit API 调用），不是 OS/进程级隔离。所以"第三方插件"一旦面向不受信任的发行渠道，进程信任边界就是最优先的决策点。我的建议是：先稳定声明/授予模型（B1），把进程隔离（utilityProcess/sandbox）明确列为后续决策，而不是现在偷偷假定它会自动出现。

---

## 四、方案比较

**方案 0：维持现状** —— 继续 per-window manager + 手抄 IPC 类型 + `setMaxListeners` 补丁 + 插件 host 依赖具体 widgetsManager + 桌面/headless 各自演化。

**方案 1（推荐）：渐进稳定契约** —— 只做 B1–B5 的收口：消除手抄类型、收敛窗口上下文、稳定窗口 manager 契约、后台统一走 `server-runtime`、沿用 `createConfig`。不做新框架、不拆进程。

**方案 2：一步到位的大重构** —— 同时做通用插件 API 面、统一窗口框架、后台进程拆分。

| 维度 | 方案 0 维持现状 | 方案 1 渐进稳定契约（推荐） | 方案 2 大重构 |
|---|---|---|---|
| 可演化性（加一个窗口） | 每加一窗：手写 provider + 依赖列表 + 一处 `setMaxListeners(0)` | 每加一窗：一个 manager + 一个 provider，机制已固定 | 依赖框架成熟度，框架未定前无法并行 |
| 第三方插件安全边界 | 权限模型有雏形但类型漂移，信任边界不明 | 线级协议唯一来源 + 权限 seam 清晰，为进程隔离留出明确决策点 | 可能过早绑定沙箱方案，错配 |
| 后台能力复用 | 桌面 channel-server 与 headless 分叉风险 | 强制同源 `createServer`，桌面/headless 共享状态机 | 进程拆分引入新协调问题 |
| 隔离性/崩溃域 | 单主进程（现状） | 同现状，不改进程模型 | 更好，但需要重做单实例锁/端口/证书 |
| 实现成本 | 0（继续累积债务） | 中低（类型/契约收敛 + Eventa 窗口命名空间） | 高 |
| 风险 | 债务线性增长，类型继续漂移 | 低（每步独立、可测、可回滚） | 高（抽象猜错 + 跨进程跨包） |
| 回滚路径 | 无需 | 每步独立 revert | 难回滚（跨进程/跨包） |
| 不改变的后果 | 见下 | —— | —— |

**方案 1 的成本、风险、回滚：**
- 成本集中在两处：①`shared/eventa` 类型收敛（纯类型改动 + 少量快照构造函数调整）；②Eventa 窗口命名空间（若 Eventa 不支持就退化为桌面侧 helper 收敛）。其余是删除重复代码。
- 风险：窗口上下文收敛如果做得太激进（一次改所有 15 处），可能引入跨窗口事件串扰。缓解方式：先保留 `createContext(ipcMain, window)` 语义，只把 `setMaxListeners` 与清理逻辑收进 helper，逐个窗口迁移，用隔离性测试兜底。
- 回滚：每一小步都是独立 commit，可单独 revert；没有跨进程状态需要迁移。

**维持现状（方案 0）不改变的后果：**
- 手抄类型继续漂移（已经出现 `PluginManifestSummary` 两份定义、字段不一致），第三方插件开发者将拿到两个不一致的契约视图。
- 每加一个窗口，`setMaxListeners` 补丁多一处，listener 泄漏与跨窗串扰的排查成本上升。
- 插件 API 面碎片化，`host/index.ts:435` 的 REVIEW（tool registry 所有权藏在 kit runtime 里）这类欠账无人认领。
- 后台逻辑可能在桌面 channel-server 与 headless 之间分叉，`/ws` 字面量、路由语义各自演化。
- `main/index.ts` 装配继续线性膨胀，最终成为所有改动的冲突热点。

---

## 五、可验证的渐进迁移路线

每步都有明确的验收判据（typecheck、grep 计数、指定测试），且可独立回滚。

**Step 0 — 基线（不改变行为）**
- 记录当前 `pnpm -F @proj-airi/stage-tamagotchi typecheck` 与相关 Vitest 全绿；记录 `setMaxListeners` 出现次数（当前 main+preload 共 15+ 处，来自上面的 grep）。
- 验收：测试基线可复现。

**Step 1 — IPC 类型唯一来源（对应 B1）**
- 删除 `shared/eventa/index.ts:204` 起的重复 `PluginManifestSummary/PluginRegistrySnapshot/PluginCapabilityPayload`，改为从 `@proj-airi/plugin-sdk`/`plugin-protocol` 的类型 re-export（按 `capabilities.ts:42` TODO 的思路）；`createPluginSummary` 返回类型随之改指 SDK 类型。
- 验收：`typecheck` 通过；`PluginManifestSummary` 全仓只剩一个权威定义（`grep -r "interface PluginManifestSummary"` 结果为 1 或 0）；现有插件 host tests 全绿。
- 回滚：revert 该 commit 即可，无运行期影响。

**Step 2 — 窗口上下文收敛（对应 B2）**
- 提取 `createWindowContext(ipcMain, window)`（或升级 Eventa 支持窗口命名空间），把 listener 上限与窗口关闭清理内聚到一处；按窗口逐个替换，每个窗口替换后跑对应测试。
- 验收：`grep -rn "setMaxListeners"` 在 main/preload 中归零（或只剩基座 1 处）；新增/已有的窗口隔离测试断言"同 event 不跨窗串扰"；所有窗口相关 tests 全绿。
- 回滚：逐窗口 revert，不影响协议。

**Step 3 — 插件 host 依赖收窄 + 权限/capability 显式化（对应 B1/D1）**
- 把 `SetupExtensionHostOptions.widgetsManager` 收窄为已有的 `ExtensionHostGameletWidgetsManager` 最小接口（事实上 `types.ts:45` 已经定义好），不再把整个 widgets window manager 传进去；顺手认领 `host/index.ts:435` 的 REVIEW——把 tool registry 所有权移到 host service。
- 验收：`inspect()` 快照中 kits/capabilities/modules 字段完整；一个第三方样例插件（复用 `devtools-sample-plugin`）通过 gamelet kit 打开/关闭 widget 的集成测试通过；权限拒绝路径有单测。
- 回滚：接口收窄与所有权调整分开提交。

**Step 4 — 后台能力同源（对应 B4/B5）**
- 规定：任何新增后台服务只通过 `packages/server-runtime` 的 `createServer`/`setupApp` 提供；新增一个 headless 冒烟测试，用 `bin/run.ts` 起独立进程并连 `server-sdk` 客户端（复用现有 `update-test:server` 模式）。
- 验收：`pnpm -F @proj-airi/server-runtime exec vitest run` 全绿；channel-server 既有 tests 全绿；headless 冒烟测试可重复通过。
- 回滚：无运行期变更，只是新增测试与约束文档。

**Step 5 — 新窗口模板落地（对应 B3）**
- 用 `createReferencedWindowManager`（或 `createReusableWindow`）作为新窗口的固定起点，在 `main/index.ts` 用同一模式注册；在 `apps/stage-tamagotchi/README.md` 记录窗口清单（名称、类型、生命周期、依赖）。
- 验收：新增一个最小窗口的 smoke test 通过，且不新增任何 `setMaxListeners` 调用。

**Step 6（可选、延后，等压力出现再做）**
- `server-runtime` 协议 cleanup（`index.ts:230` 的 TODO、`:323` 的 REVIEW、`/ws` 去重）；插件签名/分发；桌面进程拆分。三者都应在 Step 1–5 稳定后再评估，且各自单独立项。

---

**一句话总结**：现在最该做的是把 `plugin-protocol` 变成 IPC 类型的唯一权威、把窗口命名空间从 `setMaxListeners` 补丁变成一等能力、把"后台 = server-runtime"变成纪律；最不该做的是现在就去设计通用插件 API 面、统一窗口框架和后台守护进程——那些抽象在三条裂缝收口之前都会成为猜错方向的负担。
