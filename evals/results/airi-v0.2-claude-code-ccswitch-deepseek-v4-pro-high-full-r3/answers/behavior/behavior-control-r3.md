我已把仓库的关键路径读完（未做任何修改）。下面是基于可检查证据的架构评估。

## 结论先行

三条未来能力线——第三方插件、更多窗口、独立后台——**共享同一个底层事实**：Electron main 进程目前是所有运行时能力的唯一宿主，而仓库里已经存在三套“协议面”，只是还没有对齐：

1. **Eventa IPC**（窗口 ↔ main）：可用，但是全局作用域，靠 16 处 `ipcMain/ipcRenderer.setMaxListeners(0|100)` 变通撑着（`apps/stage-tamagotchi/src/main/index.ts:55-58`、`preload/shared.ts:9-12`、以及每个 window 的 `rpc/index.electron.ts`）。
2. **plugin-sdk 协议**（host ↔ 插件）：v1 manifest / 权限 / kit 契约已经成型，但目前只有**进程内**加载是真实的，`plugin/local.ts` 和 `plugin/remote.ts` 是空壳，remote websocket channel 还带 TODO。
3. **server-runtime WebSocket 协议**（host ↔ 远程 peer）：已经有 auth、握手、registry sync、consumer 路由、心跳，且**已经能独立跑**（`packages/server-runtime/src/bin/run.ts`），但今天只被当作 Electron 内嵌 channel 使用。

据此，我的判断是：**现在应该稳定 6 个边界、延后 5 个抽象**，推荐的方案是“渐进收敛三边界”（方案 B），而不是维持现状（A）或激进通用化（C）。

---

## 仓库现状的关键证据

- **插件系统已存在且是 v1**：`packages/plugin-sdk/src/plugin-host/shared/types.ts:233-253` 定义了 `ExtensionManifestV1`（`apiVersion: 'v1'`、`kind`、`id`、`permissions`、`entrypoints`）；`ExtensionHost` 在 `core.ts:205-233` 拥有 session/kit/binding/permission 生命周期。
- **插件目前只在进程内加载**：`plugin-host/runtimes/node/loaders/fs.ts:72-76` 用 `await import(entrypoint)` 动态导入；入口解析顺序 `runtime → default → electron` 已文档化（`fs.ts:48-52`）。
- **进程外/远程插件是空壳**：`plugin/local.ts`、`plugin/remote.ts` 都是 `export {}`；`channels/remote/websocket/index.ts:16-17、49-50` 有 “make sure to setup proper event handling” 的 TODO。
- **多窗口的地基是变通不是能力**：窗口有约 14 个 manager（main/chat/settings/widgets/spotlight/caption/notice/onboarding/about/beat-sync/devtools/desktop-overlay/inlay/dashboard），每个的 DI 接线手写在 `main/index.ts:132-270`；窗口复用有两套已有契约：`createReusableWindow`（单窗口复用，`window-manager/reusable.ts`）和 `createReferencedWindowManager`（多实例带 id，`windows/shared/referenced-window.ts`）。
- **两套“后台”并存的雏形**：一类是“隐藏窗口当后台”（`beat-sync`，`main/index.ts:185` 注释明确说 “create a background window”）；另一类是真正的 `server-runtime`（独立 `bin/run.ts` + `Server.start/stop/restart/updateConfig/getConnectionHost`，`server/index.ts:29-35`），但只被内嵌进 Electron。
- **两处显式的“所有权”技术债**：`plugins/host/index.ts:436-441` 的 REVIEW（tool registry 所有权藏在 built-in kit runtime 里）；`shared/eventa/index.ts:218-220` 的 TODO（IPC 类型与 plugin-sdk 的 `CapabilityDescriptor` 重复）。
- **server 协议正在迁移中**：`server-runtime/src/index.ts:230-232`（协议无关原语应下移到 better-ws）、`:323-340`（legacy 按 index 路由与按 identity 路由并存）、`:1052-1054`（`missedHeartbeats` 遗留字段）；`/ws` 路径字面量在 3 处重复（`channel-server/index.ts:103-105`）。

---

## 应该稳定的边界（现在定型，成本低、可回滚、未来不后悔）

**B1. 插件 manifest / 权限 / kit 的 v1 契约。**
第三方插件编译时唯一要依赖的公开契约就是 `ExtensionManifestV1` + `ModulePermissionDeclaration` + `KitDescriptor` + `ExtensionHost` 的 `start/stop/reload/announceBinding`。这是最不该在外部有消费者之后反悔的边界。做法：**冻结 v1 语义**，新能力一律走 `kits`/`capabilities`/`contributions`，不改 manifest 形状；固定入口解析顺序（`runtime → default → electron`）。安全边界也在这里：`apis/resources/capabilities/processors/pipelines` 的 area/action 权限模型（`shared/types.ts:264-300`）是第三方插件的闸门，必须稳定。

**B2. 插件与 Electron 主机的进程内服务面。**
`setupExtensionHost` / `ExtensionHostService` 以及它依赖的最小 `ExtensionHostGameletWidgetsManager`（`plugins/types.ts:45-56`）。现在把这条边界定清楚，未来做进程隔离时，进程外运行时才能复用同一个“host 契约”而只替换传输层。顺手修掉 `host/index.ts:436` 的 REVIEW——把 tool registry 所有权上移到 host service，方向是“host 拥有 registry，kit 注册进去”，而不是反过来。

**B3. injeca DI 的模块边界 + 生命周期。**
provider 命名空间（`configs:*`、`host:*`、`services:*`、`modules:*`、`windows:*`、`app:*`）和 `lifecycle.appHooks.onStart/onStop` 已经是事实上的模块边界。这是“独立后台”能否成立的前提：模块声明依赖和启停，main 进程只是其中一个宿主。要稳定的是**命名空间语义和 onStart/onStop 的清理顺序**（channel-server 里已有 mutex + 回滚的模式可作范本），不是把 `main/index.ts` 那个 355 行接线函数本身当契约——它恰好是下一步要拆的。

**B4. 窗口“句柄”契约，而不是窗口数量。**
`createReusableWindow`（单例复用）、`createReferencedWindowManager`（带 id 多实例，pageMounted/pageUnmounted 挂载语义）、`setupBaseWindowElectronInvokes`（每窗口基础 invoke）。稳定的是 “open/reuse/close/id/路由参数” 的语义。未来无论加多少窗口，都应该是给这个契约加实例，而不是加一套新窗口框架。

**B5. server-runtime 的 `Server` 接口 + WebSocket 协议面。**
`Server.start/stop/restart/updateConfig/getConnectionHost` 已经是“内嵌”和“独立”共用的同一接口，`bin/run.ts` 证明了独立部署可行。要稳定的是：`/ws` 路径去重（3 处字面量收敛到一处）、**完成 identity-based 路由迁移**（去掉 legacy 按 index 的 bucket，`index.ts:323-340`）、`peer:authenticate / extension:announce / extension:module:announce / registry:modules:sync / heartbeat` 这套握手语义。这是“独立后台能力”的门——不需要新抽象，只需要把现有的门修成整扇。

**B6. 每窗口的基础 IPC 服务注册。**
`setupBaseWindowElectronInvokes`（`windows/shared/window.ts:134-149`）已经把 screen/window/app/powerMonitor/systemPreferences/i18n/serverChannel 六个基础服务统一注册。这是每个新窗口（包括未来插件贡献的窗口）都要走的唯一入口，值得稳定。

---

## 应该延后的抽象（现在做会过度设计、锁死语义、没有消费者）

**D1. 通用插件进程隔离 / 沙箱运行时。**
`plugin/local.ts`、`plugin/remote.ts` 是空壳，remote websocket channel 带 TODO。在没有“不信任的第三方插件”或“插件崩溃影响主进程”的真实需求前，不要现在实现通用 utility-process / worker 池。原因：沙箱和传输语义一旦有外部插件依赖就极难反悔，而现在权限模型 + 进程内 host 已经覆盖当前信任假设。**先稳定 B1/B2 的 host 契约，隔离留在触发器之后。**

**D2. 把 Eventa 和 WebSocket 统一成“一条总线”。**
两套协议服务不同拓扑：Eventa 是窗口内/主进程内 IPC，WebSocket 是跨设备 peer 网络。强行统一会同时破坏两者的延迟/安全/生命周期假设。正确做法是**各自稳定契约，在显式适配器处桥接**（`server-sdk/src/extension-peer.ts` 已经是这种桥的雏形）。

**D3. 通用窗口“路由/页面注册中心”框架。**
当前显式 `setupX` + DI 接线 + `createRequestWindowEventa` 工厂对 ~14 个窗口够用。通用窗口路由框架在窗口数量翻倍、或插件开始贡献窗口之前是负资产。到那时，先靠 B4 的句柄契约扩展，而不是先造框架。

**D4. 独立后台的通用进程编排器（supervisor/orchestrator）。**
http-server、mcp-stdio、godot-stage、beat-sync 各是各的 setup；现在抽通用 supervisor 属于 AGENTS.md 里警告的“无政策/无状态的 pass-through service”。**等有 ≥2–3 个真实 out-of-process 消费者共享 restart/backoff/health 需求时再抽**，并且抽的是具体策略（重试/退避/存活），不是空壳。

**D5. 把 Electron main 抽成“无头 AIRI 核心”跑在任意宿主。**
插件 host 目前强依赖 Electron（`app.getPath('userData')`、`session` cookie、widgets manager）。在 server-runtime 独立进程真正需要插件 host 之前，不要造一个“随处可跑的 host”抽象。投资应落在具体的缝上（`Server` 接口、DI、manifest），而不是一个新的 core 包。

---

## 方案比较

### 方案 A —— 维持现状

- **质量属性**：交付最快，当下复杂度最低；但可演进性差——每加一个窗口 = 手写一个 provider + 再加 2 处 `setMaxListeners(0)`；多窗口正确性有隐患（全局监听器上限 100，靠 `setMaxListeners(0)` 关掉上限，等于把“事件串台”的风险交给约定）；独立后台停留在“隐藏窗口”模式。
- **成本**：现在最低（几乎为零）。
- **风险**：当下低，但**线性累积**。窗口越多，`setMaxListeners` 变通和 `main/index.ts` 接线越长；插件一旦开始有第三方作者，进程内无隔离 + 权限模型未定型的组合会变成安全债。
- **回滚路径**：无变化，天然可回滚。
- **不改变的后果**：第三方插件上线时被迫在“信任所有插件”与“临时补隔离”之间二选一；更多窗口时 Eventa 的全局作用域问题先以 bug 形式爆发；独立后台永远绑在 Electron 主进程生命周期上。

### 方案 B —— 渐进收敛三边界（推荐）

- **内容**：① Eventa 支持 window-namespaced context，删掉 16 处变通；② 稳定插件 v1 契约 + 修掉 tool-registry/类型重复两处所有权债；③ 把 server-runtime 提升为一等独立后台（去重 `/ws`、完成 identity 路由、与 Electron 内嵌共用 `Server` 契约）。
- **质量属性**：三条能力线同时解锁，且不引入新框架。插件继续进程内（性能最好、模型最简单）；多窗口正确性从“约定”变成“机制”；后台从“隐藏窗口”变成“可独立部署运行时”。
- **成本**：中等，主要是重构 + 特征测试，**不新增包**。
- **风险**：中等。Eventa 改动触及所有窗口——用“行为保持 + 每窗口投递测试”缓解；server 协议迁移——用“迁移期双路由兼容”缓解（代码已经半途在做 identity 路由，正好收口）。
- **回滚路径**：三个边界分属不同包/层，可**逐条独立回滚**；Eventa 事件名不变，回滚只是恢复旧的全局分发。
- **不改变的后果**：会退化成方案 A 的所有后果，且两处 REVIEW/TODO 债继续被新代码踩。

### 方案 C —— 激进通用化（统一总线 + 进程隔离插件沙箱 + 通用窗口框架）

- **质量属性**：隔离性和一致性上限最高。
- **成本**：高，多个季度的新基础设施。
- **风险**：**最高**——沙箱与传输语义一旦被外部插件依赖就极难改；在能力模型还没被真实使用验证前就把抽象锁死，是典型的过早抽象。
- **回滚路径**：最差，因为外部依赖已经建立。
- **何时值得**：只有在 B 落地之后，且出现真实需求（不可信插件、主进程崩溃/内存隔离、无头 server 要跑同一套模块）时，把 C 里的单项按触发器逐个立项。

### 权衡汇总

| 维度 | A 维持现状 | B 渐进收敛（推荐） | C 激进通用化 |
|---|---|---|---|
| 可演进性 | 差（线性手写） | 好（三契约对齐） | 上限高，但过早 |
| 安全/隔离 | 低（信任模型） | 中（权限闸门稳定，隔离留待触发） | 高 |
| 性能 | 好 | 好（插件仍进程内） | 中（序列化/进程边界开销） |
| 崩溃隔离 | 无 | 无（明确延后） | 有 |
| 复杂度/维护 | 短期低、长期高 | 中等 | 高 |
| 回滚兼容 | 天然 | 逐条可回滚 | 困难 |
| 交付速度 | 快 | 中 | 慢 |

---

## 推荐：方案 B 的可验证渐进迁移路线

每一步都用“可观察的测试/命令”作为完成标准，且互不阻塞、可独立回滚。

**P0 — 基线锁定（characterization / 黄金测试）。**
把三个契约用测试钉死，防止后续重构破坏语义：
- 插件：`extensionManifestV1Schema` 往返 + 用 `plugin-sdk/src/plugin-host/testdata/` 里的 fixture 走一遍 `ExtensionHost.start/stop`；
- server：握手认证 + registry sync 的集成式测试（复用已有 `liveness/codec` 测试风格）；
- 窗口：`createReferencedWindowManager` 的同 id 复用 + `createReusableWindow` 复用行为测试。
验证：`pnpm -F @proj-airi/plugin-sdk exec vitest run`、`pnpm -F @proj-airi/server-runtime exec vitest run`，加窗口定向测试。

**P1 — Eventa window-namespaced context。**
在 eventa（或其 Electron adapter）实现按窗口命名空间分发，替换 16 处 `setMaxListeners`。完成标准：删除全局 `ipcMain.setMaxListeners`，新增测试“窗口 A 的事件不投递给窗口 B”，现有各 window 的 rpc 测试全绿，`pnpm typecheck` 通过。

**P2 — DI 接线图收口。**
把 `main/index.ts:132-270` 的 provider 图抽成带类型的模块（provider 本身不变，只挪接线），并加“依赖闭包校验”测试（含 `desktop-overlay` 那种需要 `injecta.invoke` 显式 eager build 的角落，`main/index.ts:244-258`）。完成标准：`injecta.start()` 无缺依赖，`pnpm -F @proj-airi/stage-tamagotchi typecheck` 通过。

**P3 — server-runtime 独立后台对等化。**
去重 `/ws`、完成 identity 路由迁移（`index.ts:323-340`）、修 `missedHeartbeats` 字段。完成标准：新增集成测试——子进程启动 `createServer`（或 `bin/run.ts`），用 `WebSocketExtensionPeer` 带 token 连接、announce 一个 module、断言收到 `registry:modules:sync` 且含该 module；Electron 内嵌与独立进程走同一 `Server` 契约。

**P4 — 插件契约稳定。**
修 tool registry 所有权 REVIEW（`host/index.ts:436`），从 plugin-sdk 重导出 `CapabilityDescriptor` 消除重复类型（`shared/eventa/index.ts:218-220`），冻结 manifest v1。完成标准：一个**只 import `@proj-airi/plugin-sdk` + `@proj-airi/plugin-sdk-tamagotchi`、不碰 `apps/stage-tamagotchi` 内部**的样例第三方插件，能通过 `setupExtensionHost` 加载并注册 kit/工具。

**P5 — 给延后项装触发器（把它们变成决策而非漂移）。**
把 D1–D4 的立项条件写进仓库文档（`docs/solutions/` 或 PRD）：
- D1 进程隔离：出现不可信第三方插件，或测得插件崩溃/内存影响主进程；
- D3 窗口路由框架：插件开始贡献窗口，或窗口数量翻倍；
- D4 supervisor：≥2 个 out-of-process 服务共享 restart/backoff/health 需求；
- D2 统一总线：某个能力需要在“窗口内”和“跨设备”之间无缝透明迁移（不只是桥接）。

---

## 回滚总纲

- **逐条回滚**：B 的三个边界落在不同包（eventa 适配层、plugin-sdk、server-runtime），任何一条失败不影响另外两条。
- **事件名与 `Server` 接口不变**：回滚成本是“改实现、不改调用方契约”。
- **迁移期双轨**：server 的 identity 路由已处于“legacy + identity 并存”状态，正好用来做向后兼容的灰度迁移，验证通过后再删 legacy，而不是一步到位。
- **先测后改**：P0 的黄金测试是回滚的安全网——任何重构若破坏协议语义，先在测试红掉，而不是在生产里暴露。

如果需要，我可以把 P0–P4 拆成具体的 issue/任务清单（每项带验收命令），但按当前约束我没有修改任何文件。
