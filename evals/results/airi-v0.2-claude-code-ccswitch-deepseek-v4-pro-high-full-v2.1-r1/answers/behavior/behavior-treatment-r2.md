# AIRI 桌面端架构评审：第三方插件、多窗口、独立后台

## 1. 范围与置信度

**评审对象**：`apps/stage-tamagotchi`（Electron 桌面端）在未来要增加「第三方插件、更多窗口、独立后台能力」时，哪些边界应当被稳定下来、哪些抽象应当延后。

**仓库分类**：pnpm monorepo（`packages/**`、`plugins/**`、`services/**`、`apps/**`、`engines/**`）。桌面端是 **Electron**（electron-vite + electron-builder + Vue 3 渲染进程），**不是 Tauri**。本次加载的桌面适配器参考（`desktop-tauri.md`）假设的是「Rust 主进程 + web 视图」的 Tauri 模型，与本仓库的「Node 主进程 + Chromium 渲染进程」模型只有部分重叠（IPC 契约、生命周期、权限、升级器这些关切相通；Tauri 的 capability 清单模型不能直接套用）。因此我按核心流程评审，并把 Electron 特有的约束单独标注。

**置信度**：高。结论基于对主进程组装、插件 SDK、server-runtime、窗口模块和两个 sidecar 前例的直接阅读。有一处语义歧义会影响最终决策，已在第 8 节标注为待决问题。

**最重要的结论先说**：这个仓库**已经把正确的接缝“命名”出来了**——`PluginRuntime`/`PluginTransport`、server-channel 协议、`createReusableWindow` 窗口配方、Godot sidecar 生命周期——所以这不是「重新发明架构」的问题，而是「把已经声明但未落实的接缝变成可验证、有契约的边界，同时不要提前建通用框架」的问题。唯一的**结构性风险**是插件代码的信任边界，它应当驱动其余决策。

---

## 2. 已观察事实

| 声明 | 证据 | 类型 | 置信度 | 对决策的影响 |
| --- | --- | --- | --- | --- |
| 桌面端是 Electron，非 Tauri | `apps/stage-tamagotchi/package.json`（electron/electron-builder）、`electron.vite.config.ts`，无 `src-tauri/` | 事实 | 高 | 边界是 Node 主进程/渲染进程，不是 Rust/Web |
| 已有 15 个窗口模块 | `src/main/windows/{about,beat-sync,caption,chat,dashboard,desktop-overlay,devtools,inlay,main,notice,onboarding,settings,spotlight,widgets}/index.ts` + `shared/` | 事实 | 高 | 「多窗口」已是常态，不是新能力 |
| 所有渲染窗口 `sandbox: false` | grep 命中 `main/chat/settings/widgets/caption/...` 各窗口 `webPreferences.sandbox: false` | 事实 | 高 | 渲染进程/预加载不受 OS 沙箱约束 |
| 插件主宿主**进程内**动态 import 加载 | `packages/plugin-sdk/src/plugin-host/core.ts:223-224,777-781`（`FileSystemLoader` + `runtime: 'electron'` 默认值） | 事实 | 高 | 插件代码与主进程同权限运行 |
| 插件传输抽象已声明但只有 `in-memory` 实现 | `packages/plugin-sdk/src/plugin-host/runtimes/node/index.ts:24-39`（websocket/node-worker/electron/web-worker 全部 `throw not implemented`）；`transports/index.ts` 已定义联合类型 | 事实 | 高 | 进程外插件的“正确接缝”已存在，未实现 |
| 插件权限模型存在（apis/resources/capabilities/processors/pipelines + actions，双层授权，`permissionResolver` 钩子） | `core.ts:250-259,292-315`、`shared/types.ts:264-300` | 事实 | 高 | 权限模型是「kit 级能力门禁」，不是进程隔离 |
| 插件 manifest v1 已含 electron/node/web 三运行时入口 | `shared/types.ts:243-253`；发现于 `<userData>/extensions/v1` | 事实 | 高 | 协议已预留多运行时 |
| 插件 UI（gamelet）iframe 沙箱为 `allow-scripts allow-same-origin allow-forms allow-popups` | `packages/plugin-sdk-tamagotchi/src/gamelet/index.ts:69` | 事实 | 高 | 对不受信内容，这是弱沙箱组合（`allow-scripts`+`allow-same-origin` 可被同源内容拆掉） |
| server channel = 主进程内 loopback WebSocket（`127.0.0.1:6121/ws`，token 认证，可选 mkcert CA 的 TLS） | `src/main/services/airi/channel-server/index.ts:77-79,367-378` | 事实 | 高 | 后台「服务」目前随主进程生死 |
| server-runtime 可独立跑（`bin/run.ts`）也可内嵌（`setupApp`） | `packages/server-runtime/src/bin/run.ts`、`src/index.ts:215` | 事实 | 高 | 拆成独立进程已有打包级前例 |
| `apps/server` 是托管后端（Hono，Railway 多实例，Postgres/Redis） | `apps/server/package.json`、`apps/server/CLAUDE.md` | 事实 | 高 | 桌面端 loopback 与云端后端是两条不同链路 |
| `services/*`（discord-bot 等）是独立 Node 进程，经 `@proj-airi/server-sdk` 连接 | `services/discord-bot/package.json` | 事实 | 高 | 「独立后台」已有进程级先例 |
| Godot sidecar：`spawn` + loopback WS（token）+ 生命周期 mutex + 状态/错误事件 + 就绪超时 + `before-quit` 清理 | `src/main/services/airi/godot-stage/index.ts` | 事实 | 高 | 这是进程外后台最完整的本地前例 |
| MCP stdio：子进程 + apply/restart + 状态跟踪 + 超时 | `src/main/services/airi/mcp-servers/index.ts` | 事实 | 高 | 第二个子进程管理前例 |
| 新窗口配方已模板化：`createReusableWindow` → `protectPrivilegedWindowNavigation` → `setupBaseWindowElectronInvokes` → `load(withHashRoute(...))` | `src/main/windows/chat/index.ts`、`src/main/windows/shared/window.ts` | 事实 | 高 | 加窗口便宜，但仍是手写样板 |
| 全局 IPC 监听器 workaround + window 命名空间 TODO | `src/main/index.ts:58`（`setMaxListeners(100)`）、`chat/rpc/index.electron.ts:27`（`setMaxListeners(0)`）、`services/electron/window.ts:45-46`（逐条 `webContents.id === sender.id`） | 事实 | 高 | 当前窗口数量增长的天花板在 eventa 分派 |

---

## 3. 当前摩擦

把「未来三个能力」映射到现有代码，摩擦不是“缺少模块”，而是**接缝没有被当作契约对待**：

1. **插件信任边界是错位的**（最严重）。`ExtensionHost` 的权限模型只门禁 kit 使用；插件入口本身被 `import()` 进 Electron 主进程，配合 `sandbox: false`，一个第三方插件在 `setup()` 里就能直接读 `userData`、调用任意 Electron API、拖垮主进程。*（推断，置信度高：`FileSystemLoader` 动态 import + 全窗口 `sandbox:false` + 权限只在 kit 层检查。）* 权限清单目前给的是「能力记账」而非「隔离」，对不受信代码会形成虚假安全感。

2. **进程外插件的接缝已命名、未实现**。`PluginTransport` 联合类型和 manifest 的 `node`/`electron`/`web` 入口都写好了，`createPluginContext` 却只有 `in-memory`。这意味着“把插件挪出主进程”这件事，SDK 作者已经预留了正确位置，现在只是没落地。

3. **窗口多 = 样板多 + 全局监听器膨胀**。14 个窗口模块各自重复「建窗 → 保护导航 → 装基础 RPC → 载入路由」，且 eventa 目前没有窗口命名空间，靠 `ipcMain.setMaxListeners(100/0)` 和逐条 `webContents.id` 比对兜底。*（推断，置信度中高：TODO 注释明确指向这个重构。）* 窗口数再往上走，跨窗口事件泄漏和监听器管理的成本会非线性上升。

4. **「后台」目前是三种互不通用的实现**。进程内 loopback server（channel-server）、spawn 子进程 + WS 桥（Godot）、stdio 子进程（MCP）各自手写生命周期/健康/清理，没有共享的「受管子进程」抽象。*（事实：三个文件各有一套 lifecycle mutex/状态机/超时。）* 同时 `/ws` 路径在至少三处重复（`channel-server/index.ts:104` 的 TODO 也承认了这点）。

5. **主进程是单点故障与性能汇聚点**。loopback 服务、插件、`@huggingface/transformers`/`onnxruntime-web` 等重负载都落在主进程或受信任渲染进程里。*（推断，置信度中高：依赖列表显示模型推理在应用内运行。）* 对单人本地应用这是有意设计；一旦要「应用关窗后仍持续服务」或「第三方插件做重活」，就会变成真问题。

---

## 4. 质量属性优先级

按本次决策的支配程度排序（不是把每项都最大化）：

| 优先级 | 属性 | 目标/预算 | 当前证据 | 改善它的方案 | 可能回退的属性 | 验证方式 |
| --- | --- | --- | --- | --- | --- | --- |
| 1 | **进程边界稳定性**（IPC/协议契约） | 跨进程、跨窗口的契约可版本化、可契约测试 | eventa 契约集中在 `src/shared/eventa`；server-channel 有 codec/auth 测试；插件协议有 schema | 方案 B | — | 契约测试 + 序列化/错误形状快照 |
| 2 | **安全/信任边界** | 第三方插件不获得主进程权限；UI 内容隔离 | 插件进程内加载；全窗口 `sandbox:false`；iframe 弱沙箱 | 方案 B（先 gate，后隔离） | 开发便利度 | 恶意插件崩溃隔离测试、权限清单审计 |
| 3 | **可运维/生命周期** | 崩溃隔离、重启、升级、清理可被诊断和恢复 | Godot/MCP 各有一套状态机；主进程退出统一走 `handleAppExit` | 方案 B | 初期复杂度 | 崩溃/超时/退出路径测试 |
| 4 | **可测试性** | 通过公开接口验证，不 mock 全局 | 已有大量单测（host、registry、server、window-contract） | 方案 B（契约测试） | — | 跨传输/跨进程测试 |
| 5 | **成本/速度** | 不为假设性变化建框架 | AGENTS.md 明确「deep modules」「两个真实变体之前别建通用抽象」 | 方案 B 优于 C | — | 复用现有 seam 的数量 |

**明确不优先**：可维护性/可扩展性在此决策里是次要项——因为当前加一个新窗口或插件已经相当便宜；真正的风险是信任边界和进程/生命周期正确性。

---

## 5. 方案比较

### 方案 A —— 维持现状（status quo）

保持：插件进程内加载（`in-memory` 传输），窗口手写样板 + 全局 IPC 监听器，后台 = 进程内 loopback + 两个各自为政的 sidecar。

- **边界与所有权**：主进程拥有全部状态与全部信任。插件 SDK 的权限清单是「记账」，不是「隔离」。
- **使能的变化**：现有的一等插件（`plugins/*`）、15 个窗口、Godot/MCP 子进程继续工作。
- **成本/风险**：几乎为零的迁移成本；**前提是**「第三方」意味着「受信任/已审查」。
- **回滚**：无需。
- **不改变的后果**：一旦第三方插件来自不受信来源，单个插件即可读 `userData`、任意调用 Electron API、崩溃整个应用（无崩溃隔离）；`allow-scripts allow-same-origin` 的插件 iframe 对不受信内容是弱边界；窗口继续增加时全局监听器和样板成本上升；后台工作随主进程生死并与其争抢资源。
- **使方案错误成立的证据**：出现「未审查的第三方插件分发渠道」或「插件崩溃可接受范围之外的失败报告」。在那之前，方案 A 对「受信插件 + 单人本地应用」其实是可辩护的。

### 方案 B —— 稳定既有接缝，小步渐进（推荐）

在现有接口后面落地三个已经“命名”的接缝，但**不建通用框架**：

- **插件**：把 `ExtensionHost` 的 host↔runtime 传输做成真正的一等边界——在现有 `createPluginContext`/`PluginTransport` 接口后实现 `node-worker`（或子进程 sidecar）传输，`in-memory` 保留为默认；权限清单成为该边界上的**策略**（默认第三方=受限/受信模式）。**延后** OS 级沙箱、代码签名/校验、插件商店。
- **窗口**：抽取最小的**窗口描述符 + 窗口命名空间 eventa 上下文**，替换 `setMaxListeners(100/0)` workaround；保留 `createReusableWindow` 配方。**延后** z-order/停靠/布局引擎等窗口管理框架。
- **后台**：把 Godot sidecar 的生命周期（spawn → ready 握手 → 健康/重启策略 → teardown）提炼为一个小型 `createManagedProcess`，先只给 Godot 和「未来把 channel-server 拆出」两处用；把 server-channel 的端口/路径/codec 收敛成单一归属契约。**延后**通用任务队列/调度/重试/持久化。
- **使能的变化**：第三方插件可退化为受限进程（崩溃隔离 + 权限策略），窗口可声明式注册，后台 worker 可被统一监管。
- **假设**：第三方插件的真实分发渠道尚未到来，现在只需把「可插拔点」做成真的，而不是把「隔离策略」做全。
- **成本/风险**：中等——每个接缝都要补契约测试；`node-worker` 传输需要设计序列化/错误映射/会话所有权（这是三块里最难的，见第 7 节第 1 步）。
- **回滚**：每个接缝都是加法且在既有联合类型/入口选择后——插件传输由 `runtime`/`transport` 选择（默认仍是 `in-memory`）、窗口命名空间在 eventa 重构期间保留兼容层、`createManagedProcess` 是纯重构（Godot 行为由现有测试保护）。逐项可回退。
- **使方案错误成立的证据**：现有单测已经覆盖当前行为、若迁移后出现事件泄漏/生命周期回归，说明提取的边界错了——立即回退该项。

### 方案 C —— 激进抽象（现在建完整框架）

一次性上：插件沙箱 + 签名/校验 + 独立插件进程 + 声明式窗口管理框架 + 通用后台 job 调度器 + 统一 IPC 总线。

- **边界与所有权**：一个通用的「插件运行时 + 窗口框架 + 后台调度」层。
- **使能的变化**：几乎任何未来形态都能容纳。
- **成本/风险**：最高——大量假设性接口，与 AGENTS.md「两个真实变体之前别建通用抽象」「deep modules over shallow」直接冲突；错误抽象的修复成本高于延后。
- **回滚**：几乎不可回滚（牵一发动全身）。
- **使方案错误成立的证据**：目前没有证据支持——没有两个真实变体需要它。

---

## 6. 建议

**选方案 B。** 一句话：**稳定「进程边界/插件协议/server-channel 契约/窗口生命周期」这四个已有接缝，延后「OS 沙箱与签名、窗口管理框架、后台任务调度器、跨端统一插件 SDK」这四个通用抽象。**

具体到「哪些边界稳定、哪些抽象延后」：

**现在就该稳定（把已有 seam 变成有契约、可测试的边界）：**

1. **Eventa IPC 契约层**（`src/shared/eventa`）。这是窗口与插件共同的横向接缝。集中所有权、补契约测试、落实已经写好的「window-namespaced context」TODO——它是窗口数继续增长的结构性前提。
2. **插件协议边界**（`@proj-airi/plugin-protocol` + `ExtensionHost`/`ExtensionManifestV1`/`PluginRuntime`/`PluginTransport`）。把 host 的 `start/stop/reload/session/permission` 语义当成**唯一**插件边界；让传输真正可插拔（先实现 `node-worker`）；manifest v1 只做加法演进。
3. **server-channel 契约**（`@proj-airi/server-runtime` 的 `/ws` + token 认证 + registry/consumer 协议）。它已经服务远程进程（`services/*`）和进程内 peer，是后台 worker 的天然总线。收敛端口/路径/codec 的单一归属。
4. **窗口↔渲染进程路由与生命周期契约**（`baseUrl/withHashRoute/createReusableWindow/protectPrivilegedWindowNavigation` + 每窗口生命周期）。保留配方，抽一个最小的声明式描述符 + 窗口命名空间。

**现在就该延后（保持为命名过的未知项，写明重新审视信号）：**

1. **OS 级插件沙箱、代码签名/校验、插件商店/安装器** —— 延后到「真实的不受信第三方分发渠道」出现。此前把第三方插件标为「受信任/高级」模式，并把信任假设写进文档。
2. **通用窗口管理框架**（z-order、停靠、布局持久化、多窗口编排）—— 延后到第三个需要同形状的窗口类型出现。
3. **通用后台任务调度器**（重试、退避、优先级、持久化）—— 延后；只提炼 `createManagedProcess` 给两个真实 sidecar 用例。
4. **跨端统一插件 SDK**（web/mobile 运行时）—— web/mobile 后端仍是 WIP，不要现在强推 `plugin-sdk` 过去。

---

## 7. 迁移与验证（可验证的渐进路线）

每步都是**可逆的加法**，都在既有接缝之后落地，且每步有可观察的退出标准。默认路径（`in-memory` 传输、旧 window 组装、Godot 现有实现）在每一步都保留。

- **第 0 步（纯测试，无行为变化）**：为四个接缝补契约测试——插件 host（`in-memory`）、server-channel（codec/auth/registry/consumer）、窗口生命周期 RPC（`window-contract`）、插件协议 schema。**退出标准**：现有行为被契约测试锁定，`pnpm -F @proj-airi/stage-tamagotchi exec vitest run` 全绿。
- **第 1 步（进程外插件垂直切片，最难）**：在 `createPluginContext`/`PluginTransport` 接口后实现 `node-worker` 传输，选一个现有**一等插件**（如 tool kit 插件）跑通，`in-memory` 仍为默认。**验证**：同一插件在两种传输下通过同一套契约测试；插件抛错/崩溃不拖垮主进程；会话所有权（`sessionId`）与清理在 worker 终止时正确释放。**回滚**：`runtime`/`transport` 选回 `in-memory`。
- **第 2 步（窗口命名空间）**：实现 window-namespaced eventa context，先迁移 `chat` 窗口，移除 `setMaxListeners(0)`。**验证**：窗口 A 的事件不泄漏到窗口 B；`setMaxListeners` workaround 删除后监听器计数不再增长。**回滚**：eventa 重构期间保留兼容层，切回全局 context。
- **第 3 步（后台监管提炼）**：把 Godot sidecar 生命周期提炼为 `createManagedProcess`（spawn → ready 握手 → 健康/重启策略 → teardown），Godot 改用之，行为由现有测试保护。**验证**：Godot 启动/就绪超时/异常退出路径不回归；`createManagedProcess` 只被 Godot 使用。**先不**把 channel-server 拆出去。
- **第 4 步（仅在触发信号出现时）**：当「不受信第三方分发」或「关窗后持续服务」成为真实需求时，再决定把插件宿主或 channel-server 移到独立进程（复用 `createManagedProcess` + server-channel 契约）。

**逐步的失败/回滚检查**：每步引入一个「旧路径开关」，若契约测试或 `pnpm typecheck`/`pnpm lint` 回归，立即回退该步，不进入下一步。

---

## 8. 待决问题（答案会改变建议）

1. **「第三方」是「不受信」还是「受审查」？** 若是前者，方案 B 的第 1 步优先级提到最高，且必须加权限策略 + 崩溃隔离；若是后者，方案 A 短期可接受，先把信任假设文档化即可。
2. **「独立后台能力」具体指什么？** 三个不同含义会导致不同路线：
   - (a) 关窗后应用仍常驻后台服务（现状：非 macOS 上 `window-all-closed` 会退出，见 `src/main/index.ts:291-297`；托盘已存在）——这需要先改生命周期语义；
   - (b) 把重活挪到独立进程以免阻塞主进程——走 `createManagedProcess` 路线；
   - (c) 一个可独立部署的本地 server daemon——`server-runtime/bin/run.ts` 已是雏形。
   请确认目标是 (a)/(b)/(c) 中的哪个或组合。
3. **后台工作的性能预算**（CPU/内存/电量）是多少？如果模型推理要常驻后台，进程拆分的收益才成立；否则维持进程内是更便宜的方案。

---

*本次评审只读，未修改任何文件、未创建提交。*

[EVAL:evolve-software-architecture-loaded]
