# 桌面端（stage-tamagotchi）未来三能力的架构评估

**TL;DR：** 现状已经把最难的部分做对了——`plugin-protocol`（扩展/模块事件协议）、`plugin-sdk` 的 `ExtensionHost` + Kit + 权限模型、`server-runtime`/`server-sdk` 的 WebSocket 后端核心，这三块已经是比较深的模块，值得当作稳定边界冻结。真正的摩擦在三处：第三方插件目前**在 Electron 主进程内 `import()` 运行**（`FileSystemLoader` 直接用 `await import(entrypoint)`），这是最大的安全边界问题；窗口创建是**逐窗口手写**的，新窗口要改 4 个地方；"独立后台"已经存在**两套并行但不统一的服务器生命周期**（`server-runtime.createServer` 固定端口 6121 vs `http-server.createH3Server` 随机端口）。建议是**冻结协议/身份/权限/Kit 契约 + 一个小型窗口契约 + 一个权限解析器**的渐进路线，**不要**现在一步到位做插件进程隔离、独立守护进程和通用窗口框架。

---

## 1. Scope and confidence

**评估对象**：`apps/stage-tamagotchi`（Electron 桌面端），面向未来三个能力：第三方插件、更多窗口、独立后台。

**仓库分类**：monorepo，含 Electron 桌面端、Web、移动端、共享 packages 与独立服务（`services/computer-use-mcp`）。本次聚焦桌面端主进程 + 与之相关的 `packages/plugin-*` 和 `packages/server-*`。分类置信度：**高**（AGENTS.md、目录结构、依赖方向均一致）。

**置信度说明**：以下结论基于只读检查源码（未运行测试/构建，因为本环境 Bash 被禁用）。引用的行号和符号来自当前 checkout，可能随分支漂移。

---

## 2. Observed facts（证据）

**插件宿主（第三方插件）——已具备较完整的纵深：**

- `apps/stage-tamagotchi/src/main/services/airi/plugins/host/index.ts`：`setupExtensionHostServiceInternal` 负责清单发现、加载/卸载、静态资源、自动重载。插件目录为 `<userData>/extensions/v1`，清单文件 `extension.airi.json`。
- `apps/stage-tamagotchi/src/main/services/airi/plugins/host/registry.ts`：`loadManifestsFrom` 用 Valibot `extensionManifestV1Schema` 校验清单，支持 symlink 解析、`package.json` 版本回退。
- `packages/plugin-sdk/src/plugin-host/core.ts`：`ExtensionHost` 拥有会话（session）、模块、Kit 注册、binding、权限、资源、能力。**权限是两层**（extension grant 为上限，module grant 取交集）。
- `packages/plugin-sdk/src/plugin-host/runtimes/node/loaders/fs.ts:74`：`await import(entrypoint)` —— **插件代码在主进程内加载执行**（事实）。
- `packages/plugin-sdk/src/plugin-host/runtimes/shared/services/permissions.ts`：`PermissionService` 已经实现请求∩授权、通配符 key 匹配、动作合并。**但宿主没接 `permissionResolver`**（`core.ts` 里 `permissionResolver?.(...) ?? options.manifest.permissions`，未传 resolver 时即默认全量授予）。
- `packages/plugin-protocol/src/types/events.ts`：完整协议——`extension:*`、`module:*`、`module:permissions:*`、`spark:*`、`input/output:gen-ai:*`、`DeliveryConfig`、`ExtensionIdentity`/`ModuleIdentity`/`ExtensionModuleIdentity`、五个权限域（apis/resources/capabilities/processors/pipelines）。

**Kit 与插件 UI（插件 → 窗口的桥）：**

- `apps/stage-tamagotchi/src/main/services/airi/plugins/kits/index.ts`：`createBuiltInExtensionKitRuntime` 注册 `kit.gamelet`、`kit.widget`、tool kit。
- `.../kits/gamelet/orchestration.ts`：gamelet 的 `open/close/request` 映射到 `widgetsManager.pushWidget/updateWidget/openWindow/requestWidgetIframe`。插件 UI 目前以 iframe widget 形式存在，而不是独立 BrowserWindow。
- `.../plugins/features/static-assets/index.ts`：插件 iframe 静态资源走本地回环 HTTP + cookie 会话鉴权，路径 `/_airi/extensions/**`，复用 `http-server/static-assets`。

**窗口（更多窗口）：**

- `apps/stage-tamagotchi/src/main/index.ts`：injeca 组合根，约 13 个 `windows:*` provider；`settingsWindow.dependsOn` 已经 13 项、`mainWindow` 11 项、`tray` 10 项。`ipcMain.setMaxListeners(100)`（第 58 行）及注释中的 TODO 说明窗口级 Eventa 上下文还未就绪。
- `apps/stage-tamagotchi/src/main/libs/electron/window-manager/reusable.ts`：`createReusableWindow` 是一个**很薄**的「get-or-create + closed 后重建」助手，不含导航保护、bounds 持久化、IPC 作用域。
- `apps/stage-tamagotchi/src/main/windows/shared/window.ts`：`setupBaseWindowElectronInvokes`、`protectPrivilegedWindowNavigation`、`transparentWindowConfig` 等是当前实际共享的窗口约定。
- `apps/stage-tamagotchi/src/main/windows/main/index.ts`：主窗口手写 `BrowserWindow` 构造、`handleNewBounds` 持久化、`ipcMain.setMaxListeners(0)`（第 214 行）、`initScreenCaptureForWindow`。每个窗口有自己的 `rpc/index.electron.ts`。

**独立后台：**

- `packages/server-runtime/src/index.ts`：`setupApp` 是完整 WebSocket 运行时（peer/模块注册、consumer 路由、心跳、认证、权限/配置事件路由）。
- `packages/server-runtime/src/server/index.ts`：`createServer` 提供 `Server` 契约 `getConnectionHost/start/stop/restart/updateConfig`，默认 `127.0.0.1:6121`，支持 TLS。
- `packages/server-sdk/src/client.ts`：`Client` 支持重连、module/manual 握手、心跳；`packages/server-sdk/src/extension-peer.ts`：`WebSocketExtensionPeer` 已实现 `extension:announce` / `extension:module:announce` / `peer:authenticate` —— **远程插件协议面已经存在**。
- `apps/stage-tamagotchi/src/main/services/airi/channel-server/index.ts`：把 `server-runtime` 包装成桌面端长驻后台（TLS 证书、QR、配置持久化、IPC）。第 103 行有 TODO：`/ws` 路径字面量在 channel-server / server-runtime / server-sdk 三处重复。
- `apps/stage-tamagotchi/src/main/services/airi/http-server/`：`setupBuiltInServer` + `createHttpServerManager`（有序 start/stop）+ `createH3Server`（随机端口）。这是**另一套**生命周期，与 `Server` 契约语义相近但类型不同。
- `packages/plugin-sdk/src/plugin/remote.ts`、`plugin/local.ts`：目前是空文件（`export {}`）——本地/远程插件 SDK 的对外入口尚未落地。

---

## 3. Current friction（当前摩擦 / 变更放大）

1. **插件运行在主进程内，且权限门只挡 Kit 调用，不挡插件代码本身。** `FileSystemLoader.loadExtensionFor` 用 `await import(entrypoint)`（`fs.ts:74`）在主进程执行任意 JS；权限模型能约束插件**通过 Kit 做什么**，但拦不住插件直接 `import('electron')` / `node:fs` / `node:child_process`。对于"第三方插件"这是最尖锐的边界。这是**事实 + 推断**（推断部分：未验证 Electron 是否对所有动态 import 暴露全部主进程能力，但 `sandbox: false` 的 preload 与主进程运行位置支持这一风险判断）。

2. **两套插件执行模型共享协议、未共享实现。** 进程内 `ExtensionHost`（FileSystemLoader）和远程 `WebSocketExtensionPeer`（server-sdk）各自实现了 `extension:*` 握手，但 `plugin/remote.ts`、`local.ts` 是空的。结果是"插件跑在桌面主进程里"和"插件跑在别处（独立后台）"是两条 SDK 路径，而不是一次部署选择。

3. **窗口是逐窗口手写，新窗口变更放大。** 增加一个窗口需要：`main/index.ts` 新 provider、`windows/<name>/index.ts` 手写 `BrowserWindow` + bounds 持久化、`windows/<name>/rpc/index.electron.ts`、渲染层路由/布局/tray。`createReusableWindow` 太薄，没有承载"窗口契约"。

4. **两套服务器生命周期未统一。** `server-runtime.Server`（固定端口）和 `http-server` 的 `ServerManager`（随机端口 H3）语义重复；插件静态资源、OIDC 回环、channel server 各自绑定端口。`/ws` 路径已三处重复（channel-server TODO 自证）。

5. **组合根开始膨胀。** `main/index.ts` 是唯一的 injeca 组合根，`settingsWindow` 依赖已 13 项。再叠加"更多窗口 + 独立后台"会继续推高这里的耦合与启动顺序敏感度。窗口命名空间的 Eventa 重构（两处 TODO）是真正的解锁点，但目前被推迟。

---

## 4. Quality-attribute priorities（质量属性排序）

| 排序 | 属性 | 为什么在这个决策里排它 |
|---|---|---|
| 1 | **安全性 / 隔离** | 第三方插件若在主进程运行，一次恶意/缺陷插件就能拿到整个 Electron 主进程；这决定"第三方插件"是否可行，权重最高 |
| 2 | **可扩展性（插件的稳定契约）** | 插件生态的价值 = 契约稳定；`manifest v1`、身份、权限域、Kit 一旦被第三方依赖，改动的成本就从"内部重构"变成"破坏生态" |
| 3 | **可维护性 / 低变更放大** | "更多窗口"与"独立后台"最直接的痛点是每次变更要动 4 个地方；窗口契约与服务生命周期契约直接决定边际成本 |
| 4 | **可操作性（生命周期/可观测）** | 独立后台意味着 start/stop/dispose、有序关停、崩溃恢复、健康检查；`ServerManager` 和 `Server` 已经朝这个方向走 |
| 5 | **可测试性** | 协议 + 纯函数 + injeca 依赖注入已经很好；测试应走稳定公共行为（协议事件、窗口契约、权限交集），不要为 mock 私有实现开新出口 |
| 6 | **性能** | 对本决策非主导；窗口/插件属低频创建，远程插件延迟只在需要隔离时才考虑 |

**显式权衡**：把"安全性/隔离"排第一意味着**不优先**做"让插件任意用 Node API"的便利性；把"稳定契约"排第二意味着一旦冻结 `manifest v1`/协议事件，宁可新增版本也不静默改语义。这与 AGENTS.md"不加向后兼容 guard、必要时写迁移文档"一致——契约用**显式版本化**（`apiVersion: 'v1'`）承载，而不是散落兼容分支。

---

## 5. Options（至少两个可行方案）

### 方案 A：维持现状，仅补文档与契约标注

保留进程内 `ExtensionHost`、逐窗口手写、channel-server 作为唯一长驻后台。只做：把协议/身份/权限/Kit 契约写成 ADR、标注"稳定边界"、修复 `/ws` 路径重复。

- **边界/所有权**：不新增边界；现状的所有权维持（plugin host 在 app 内，服务器在 `server-runtime`）。
- **能支持**：第一方/受信任插件、少量窗口、单一本机后台。这些今天就能用。
- **成本**：极低（文档 + 极小去重）。
- **风险**：第三方插件的安全风险不消除（主进程执行）；窗口增长时变更放大不变；"独立后台"停在"本机回环 + 可选 TLS"，无法覆盖"退出后常驻/远程/崩溃隔离"。
- **回滚**：几乎为零（只有文档/去重）。
- **不改变的后果**：每加一个窗口继续改 4 处；每次想"插件跑在别处"都要另起一套 SDK 路径；一旦有第三方插件需求，主进程隔离是事后补救、迁移成本最高。

**结论**：作为"零风险起点"成立，但不回应题设的三个未来能力。

### 方案 B：冻结协议契约 + 窗口契约 + 权限解析器（渐进收敛，推荐）

把已经写对的东西显式冻结为稳定边界，只补三个小接缝，不引入新框架：

1. **稳定边界（冻结）**：`plugin-protocol` 的事件/身份/权限模型、`ExtensionManifestV1`（`apiVersion: 'v1'`）与发现根、Kit 契约、`ServerManager`/`Server` 生命周期、Eventa 的 `src/shared/eventa/*` 契约、injeca 的 provider 命名（`windows:*`/`modules:*`/`services:*`）。
2. **新增小接缝 ①——窗口契约**：把 `createReusableWindow` 升级为小的 `createWindow` 描述符，统一承载 `BrowserWindow` 默认构造、`protectPrivilegedWindowNavigation`、bounds 持久化、IPC 上下文（等窗口命名空间 Eventa 就绪后接入）。**不**做通用多窗口布局/动态路由框架。
3. **新增小接缝 ②——权限解析器**：给 `ExtensionHost` 接真实 `permissionResolver`（内置 Kit 白名单放行、第三方默认拒绝或按需确认），并把 `module:permissions:*` 协议事件接到 IPC 让设置页能做授权 UX。这是把"协议里的权限模型"变成"宿主真正执行的策略"。
4. **新增小接缝 ③——远程插件纵向切片**：用 `WebSocketExtensionPeer` 对一个 fixture 做端到端验证（见迁移），证明"插件跑在进程外"与"进程内"共享同一协议。**不**现在做隔离运行时。

- **边界/所有权**：协议拥有权集中在 `plugin-protocol`/`server-shared`；窗口契约拥有窗口的构造/保护/持久化；宿主拥有加载/权限/会话；后台拥有长驻服务器。
- **能支持**：受信任插件生态（契约稳定 + 权限可审计）、逐窗口增量迁移、远程插件作为一等目标、后台能力通过同一协议扩展。
- **成本**：中等；三个小接缝都是"提取 + 补接线"，每个都可独立合并/回滚。
- **风险**：冻结契约意味着后续改动要版本化（这是成本也是保护）；窗口契约若做太厚会退化成方案 C 的通用框架（要克制）；权限解析器需要一次产品决策（默认允许/拒绝）。
- **回滚**：每个接缝独立。窗口契约是行为保持的重构，可单测回归；权限解析器可用"默认全量授予"作为安全网切回；远程切片只是测试，不进入生产路径。
- **不改变的后果**：比方案 A 明显更安全、更可扩展，但仍不解决"不受信第三方插件"的主进程隔离；这是留给方案 C 或后续触发条件的部分。

### 方案 C：一步到位——插件进程隔离 + 独立后台进程 + 通用窗口框架

同时引入：utility process/worker 插件运行时、可独立存活的后台守护进程（或把 desktop 变成协议里的普通 peer）、通用窗口管理器（窗口注册表 + 动态路由 + 布局）。

- **边界/所有权**：新增进程边界与跨进程协议栈；这是对题设三个能力的"理想终态"。
- **成本**：高；三个大件同时做，需要进程生命周期、跨进程 IPC、崩溃恢复、升级/签名、窗口注册表等，远超当前需求。
- **风险**：过度设计——在没有任何一个能力有真实需求压力前建通用框架，违反 AGENTS.md"深模块优先、不要为假设的变点建层"；同时会重写现有逐窗口代码，回归面大。
- **回滚**：几乎不可行；一旦引入进程隔离和通用窗口框架，撤回等于重做。
- **不改变的后果**：如果三个能力**同时**、**近期**、**都要求不可信第三方**，这个方案才划算；否则是过早优化。

**为什么推荐 B 而不是 C**：协议层（`plugin-protocol` + `WebSocketExtensionPeer`）已经把"进程内 vs 进程外"变成**部署选择而非 SDK 选择**的潜力。B 先兑现这个潜力里的最小一步（远程切片验证），把昂贵的进程隔离和守护进程推迟到有具体触发条件（不受信插件、退出后常驻、崩溃/内存隔离需求）时再上。C 的每一项都应该是"被需求逼出来的增量"，而不是一次性的目标架构。

---

## 6. Recommendation（建议）

**采用方案 B，冻结三块稳定边界，补三个小接缝。**

**应稳定的边界（冻结为契约，改动必须版本化）：**

| 边界 | 位置 | 为什么稳定 |
|---|---|---|
| 扩展/模块协议事件 + 身份 + 权限 + 投递 | `packages/plugin-protocol/src/types/events.ts` | 已被 `server-runtime`/`server-sdk`/`plugin-sdk`/app 共享，是插件生态与后台的共同语言 |
| 扩展清单与发现 | `extension.airi.json`（`apiVersion: 'v1'`）+ `<userData>/extensions/v1` | 第三方插件的安装/升级/权限声明的稳定入口 |
| Kit 契约 | `KitDescriptor`/`KitRef` + `kit.gamelet`/`kit.widget`/tool kit + 五个权限域 | 插件作者唯一应依赖的能力面，隔离 Electron/Node 内部 API |
| 服务器生命周期 | `ServerManager`（key/start/stop）、`Server`（getConnectionHost/start/stop/restart/updateConfig） | 独立后台能否优雅启停、有序关停的公共面 |
| 渲染↔主进程 IPC 契约 | `apps/stage-tamagotchi/src/shared/eventa/*` | 多窗口与插件 UI 都走这条类型安全边界 |
| injeca provider 命名 | `windows:*` / `modules:*` / `services:*` | 组合根的接缝；未来窗口/后台都挂在这套命名下 |

**应延后的抽象（现在不建，等触发条件）：**

1. **通用插件进程隔离框架**（utility process/worker 抽象）。现在只在主进程跑受信任插件；等"不受信第三方插件"成为明确需求时，再做进程隔离，且应**复用同一套协议 + Kit**，而不是新建 SDK。
2. **独立后台守护进程 / 独立进程拓扑**。现在 channel-server 已经是"本机长驻后台"；等出现"应用退出后仍需存活""远程多设备""崩溃/内存隔离"等具体需求再拆进程。
3. **通用窗口管理器**（窗口注册表 + 动态路由 + 任意布局）。现在只做**窗口契约**，不做通用框架；窗口命名空间 Eventa 重构（两处 TODO）是这个方向的真正解锁点，值得单独立项，但不必与窗口契约捆绑。
4. **插件市场/签名/安装 UI**。现有 registry 的 enable/disable + `known` 路径已够内部使用；签名与分发是产品/安全决策，不是代码边界。
5. **local/remote 插件 SDK 对等**。`plugin/remote.ts`/`local.ts` 仍是空壳；等远程切片证明需求后再填，避免现在造两个平行的 SDK。

---

## 7. Migration and verification（迁移与验证）

每步都可独立合并、独立回滚；第 0 步之后全是行为保持或纯增量。

**第 0 步 —— 写 ADR，冻结第 6 节三个稳定边界。** 记录：协议事件/身份/权限为版本化契约；`manifest v1` 是第三方契约；Kit 是插件唯一能力面；`ServerManager`/`Server` 为服务器生命周期契约。**验收**：ADR 被合入，后续对 `plugin-protocol` 的事件增删改必须带 `apiVersion` 或迁移说明。

**第 1 步 —— 窗口契约（先做，风险最低）。** 把 `createReusableWindow`（`reusable.ts`）扩展为 `createWindow` 描述符，收敛 `BrowserWindow` 默认构造、`protectPrivilegedWindowNavigation`、bounds 持久化、IPC 上下文注册。**先迁移一个新窗口验证，再逐窗口替换**，不要一次性重写 13 个窗口。
- **验证**：现有窗口单测（如 `windows/shared/display.test.ts`）+ 新增契约测试（导航被保护、bounds 持久化、closed 后重建、preload 与 IPC 作用域一致）；`pnpm -F @proj-airi/stage-tamagotchi typecheck` + `exec vitest run` 通过。
- **回滚**：纯提取，行为保持；单个窗口迁移可独立 revert。

**第 2 步 —— 权限解析器（安全关键，紧跟窗口契约之后）。** 给 `setupExtensionHostServiceInternal` 传入 `permissionResolver`：内置 Kit 放行，第三方默认拒绝或走确认流；把 `module:permissions:*` 事件接到 IPC，让设置页能展示/授权。
- **验证**：`PermissionService` 已有交集/通配符逻辑，补宿主级测试——声明了 `apis['kit.widget', 'invoke']` 的插件在 resolver 拒绝后 `resolveKitApi` 返回 `permission-denied`；grant 后可用。集成式测试加 env guard（按 AGENTS.md）。
- **回滚**：resolver 默认"全量授予"即回到现状行为，一行切换。

**第 3 步 —— 远程插件纵向切片（验证独立后台路径，不改变生产路径）。** 写一个 fixture：进程外用 `createWebSocketExtensionPeer` 连接桌面 `channel-server`，完成 `extension:authenticate → extension:announce → extension:module:announce`，收到 `registry:modules:sync`，再发一条 `spark:notify` 验证路由。
- **验证**：env-guarded 集成测试（启动 `server-runtime` 本地实例即可，不依赖真实 Electron）；断言握手与 registry sync 事件顺序。
- **价值**：这是"插件跑在别处"的最小可证伪切片；若它顺利，说明方案 B 的协议复用成立；若卡住，说明协议与桌面宿主之间还有未对齐的握手假设——**这正是现在最该花小成本学到的信息**。

**第 4 步（触发后）—— 进程隔离 / 独立守护进程。** 仅当出现"不受信第三方插件""退出后常驻""崩溃/内存隔离"任一明确需求时再启动，且以第 3 步的协议复用为地基，不另建 SDK。

**贯穿性检查：**
- **架构检查**：加一条依赖方向检查（或 lint）——`plugin-protocol` 不得依赖 Electron/`plugin-sdk` 的运行时；`plugin-sdk` 的 host 核心不得 import Electron（Electron 适配只留在 app 层）。已有证据是 `plugin-sdk` 内 Electron 相关适配通过 `runtimes/*` 隔离。
- **可观测**：插件用 `electronPluginInspect`（`host.ts` 的 snapshot）看 session/kit/module/权限状态；后台用 `channel-server` 的 start/restart 日志与 `Server.getConnectionHost()`；窗口用窗口契约统一日志。
- **回归**：每步结束跑 `pnpm -F @proj-airi/stage-tamagotchi typecheck`、目标 vitest、`pnpm lint`；根 `pnpm test:run` 收尾。

---

## 8. Open decisions（会改变建议的问题）

1. **第三方插件的威胁模型**：是"受信任的第一方/生态插件"还是"不可信、任意安装的第三方"？这决定进程隔离是第 2 步还是第 4 步。**未知**，目前只能从代码推断出"主进程执行"的事实，无法从仓库得知产品意图。最便宜的确认方式：看插件市场/分发计划或与产品确认。
2. **"独立后台"的确切含义**：退出后常驻（daemon）？远程多设备（远程）？崩溃/内存隔离（child process）？三者拓扑与成本完全不同。**未知**；建议先做第 3 步远程切片，用最小成本暴露真正的需求形状。
3. **权限默认策略**：第三方插件默认拒绝还是默认允许？这影响 `permissionResolver` 的形态与设置页 UX，是需要产品拍板的决策。
4. **窗口命名空间 Eventa 重构的排期**：两处 TODO（`main/index.ts:55`、`windows/main/index.ts:211`）是干净多窗口 IPC 的真正前提，但它与窗口契约、权限解析器是并行还是先后，尚未有 ADR 决定。
5. **插件分发/签名模型**：registry 目前按 `known.path` 记录，无签名、无来源校验；一旦做第三方插件，签名与更新源是安全边界，需在协议冻结之后单独立项。

[EVAL:evolve-software-architecture-loaded]
