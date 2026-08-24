# AIRI 桌面端架构评审：第三方插件、多窗口、独立后台的边界取舍

## 1. 范围与置信度

评审对象是 `apps/stage-tamagotchi`（Electron 桌面端）及其配套的 `packages/plugin-*`、`packages/server-*` 与 `plugins/`。结论基于对源码的直接阅读，**置信度：高**。

仓库分类说明：AGENTS.md 把桌面端标为 Electron，而本 skill 自带的适配器是 Tauri 专用的。Tauri 适配器里关于「进程边界、IPC 版本化、生命周期正确性、不依赖打包运行时的可测性」这几条**可迁移**，但「Rust/`src-tauri`/capability 清单」等识别信号不适用，故按 Desktop/Electron 处理，不套用 Tauri 假设。

三个未来能力在仓库里的**成熟度完全不同**，不能当作同一类决策：

- **第三方插件**：基础设施已存在且相当完整，但缺一个关键安全边界（进程隔离）。
- **更多窗口**：机制已存在（12+ 种窗口、单例/多实例两种复用器、每窗口 Eventa 上下文），缺的是收口和事件路由打磨。
- **独立后台**：包结构已拆好（`server-runtime` 独立进程 + 应用内 `channel-server` 复用同一 `createServer`），缺的是「何时真的拆进程」的证据。

因此核心架构决策只有一个：**第三方插件的信任/隔离边界**。多窗口和独立后台属于「稳定现有 seam、延后新抽象」，而不是「选方案」。

## 2. 观察到的事实

| 主张 | 证据（路径/符号） | 类型 | 置信度 | 对决策的影响 |
| --- | --- | --- | --- | --- |
| 主进程用 injeca DI 组合所有服务/窗口，是一个显式依赖图 | `src/main/index.ts:132-270`（`injeca.provide('windows:X', { dependsOn: … })`） | 事实 | 高 | 「加窗口」成本集中在组合根，seam 已经存在 |
| 插件入口通过 `await import(entrypoint)` **在主进程内直接执行** | `packages/plugin-sdk/src/plugin-host/runtimes/node/loaders/fs.ts:74`；`core.ts:777-790`（`start → loadExtensionFor → extension.setup(ctx)`） | 事实 | 高 | 这是第三方插件的信任边界缺口 |
| 权限模型是**逻辑能力授予**，不是沙箱 | `core.ts:62-74, 420, 493-511`；`runtimes/shared/services/permissions.ts`（交集/合并/`grantAllows`） | 事实 | 高 | 权限只管「宿主给哪些 kit」，拦不住插件直接 `import('node:fs')` |
| 多传输/隔离 seam 已声明但**未实现、未接线** | `plugin-host/transports/index.ts:14-19`（`node-worker`/`electron` 等）；`runtimes/node/index.ts:24-38` 全部 throw；`createPluginContext` 仅测试引用 | 事实 | 高 | 隔离是「填空」，不是重构 |
| Electron 装配时**没传 `permissionResolver`**，即请求权限默认全授予、无安装同意流程 | `services/airi/plugins/host/index.ts:236`（`new ExtensionHost({ runtime: 'electron' })`）；对比 `core.ts:250` | 事实 | 高 | 第三方插件缺「安装时授权」这一环 |
| 团队已有隔离设计文档，标注「Planned」 | `packages/plugin-sdk/docs/design/multi-transport.md`（状态 Planned；non-goals 明确延后生命周期/打包/新传输栈） | 事实 | 高 | 推荐方向应与团队既有设计语言一致 |
| 中性协议类型已独立成包 | `packages/plugin-protocol/src/types/`（被 `plugin-sdk/…/shared/types.ts:1-5` 引用） | 事实 | 高 | 作者侧契约已经是无副作用类型边界，应保持稳定 |
| 插件清单已带版本与判别符 | `shared/types.ts:322-328`（`apiVersion: 'v1'`、`kind: 'manifest.extension.airi.moeru.ai'`，Valibot schema） | 事实 | 高 | 版本化契约已在 |
| 每窗口有独立 Eventa 上下文 `createContext(ipcMain, window)` | `windows/{main,chat,dashboard,about,widgets,desktop-overlay}/rpc/index.electron.ts` | 事实 | 高 | 多窗口 seam 已在，但事件路由未收口 |
| 窗口模块形状已统一：`windows/X/index.ts`（生命周期）+ `windows/X/rpc/index.electron.ts`（RPC） | 目录结构与上述文件 | 事实 | 高 | 该形状应作为稳定 seam |
| 事件未按窗口命名空间分发，靠 `setMaxListeners` 兜底 | `src/main/index.ts:55-58`（`setMaxListeners(100)` + TODO）；`windows/shared/referenced-window.ts:44`（`setMaxListeners(0)`） | 事实 | 高 | 窗口越多监听器越多，是已知技术债 |
| 插件操作窗口走窄接口 `ExtensionHostGameletWidgetsManager`，不暴露 `BrowserWindow` | `services/airi/plugins/types.ts:45-56` | 事实 | 高 | 正确的深模块模式，应保持并推广 |
| 独立后台已拆包：`server-runtime`（`bin/run.ts` 独立进程）、`server-sdk`（`client`/`extension-peer`/`codec`）、`server-shared`（WebSocket 类型） | 各 `packages/server-*` | 事实 | 高 | 后台能力是「库 + 独立部署」，无需先拆进程 |
| 应用内后台是 WS 服务（6121 端口、TLS、token、QR 配对）+ 空 HTTP server manager | `services/airi/channel-server/index.ts`；`http-server/index.ts`（`setupBuiltInServer({ servers: [] })`） | 事实 | 高 | 后台生命周期 seam 已存在 |
| 远程插件目前只有**客户端侧** peer，宿主侧 WebSocket 通道是 stub | `server-sdk/src/extension-peer.ts`（客户端）；`plugin-sdk/src/channels/remote/websocket/index.ts`（TODO） | 事实 | 高 | 远程/独立进程宿主尚未成形 |
| `/ws` 字面量重复 3 处 | `channel-server/index.ts:104`（TODO 自述） | 事实 | 高 | 后台协议收口的一个小切入点 |

## 3. 当前摩擦

**插件（最严重）**：把「可信的一方插件」和「不可信的第三方插件」用同一条 in-process 执行路径处理。权限模型是给**守规矩的插件**用的能力白名单，不是给**恶意或出 bug 的插件**用的安全边界。一旦第三方插件落地，一个 `process.exit()`、读 `app.getPath('userData')`、或 `import('node:fs')` 的插件就能带走整个主进程（所有窗口 + 内置 server + 托盘一起死）。此外没有安装时授权（`permissionResolver` 未接线），也没有「插件崩溃后自动禁用/安全模式」。

**多窗口**：机制不缺，缺收口。每窗口的手写创建 + 组合根里的长 provider 列表意味着「加一个窗口」要同时碰 `main/index.ts`、`windows/X/index.ts`、`windows/X/rpc/index.electron.ts`、`shared/eventa/*` 四处。真正会随窗口数恶化的隐患是 `setMaxListeners` 兜底——事件路由没按窗口命名空间隔离，监听器数随窗口线性增长。

**独立后台**：结构已经很好，主要摩擦是**协议字面量重复**（`/ws` 三处）和**宿主侧远程通道缺失**，而不是边界不清。应用内后台与插件共享主进程，blast radius 大——但这与插件的隔离问题是同一个问题，不是独立的新问题。

## 4. 质量属性优先级

按对本次决策的支配力排序：

| 排名 | 属性 | 目标/预算 | 当前证据 | 哪个方案改善 | 可能退化的属性 | 捕获退化的验证 |
| --- | --- | --- | --- | --- | --- | --- |
| 1 | 安全/信任边界 | 第三方插件拿不到未授予的文件/token/IPC，且不能崩溃主进程 | in-process `import()` + 纯逻辑权限 | 方案 1/2 | 性能（消息序列化开销）、作者体验 | 恶意插件测试：`process.exit()`/读 `userData` 被隔离 |
| 2 | 可运维性 | 单插件崩溃/挂起可检测、可重启、可回滚，不影响其它窗口与内置 server | `handleAppExit` 全局清理 + `auto-reload`，无 per-plugin 崩溃隔离 | 方案 1/2 | 复杂度（session 生命周期、超时） | 崩溃注入 + 宿主仍可 `stop/reload` 该 session |
| 3 | 可维护性/局部性 | 加窗口/加 kit 的改动留在少数文件 | injeca 依赖图显式但组合根长平铺 | 现状已够，靠收口而非新框架 | — | 加一个窗口的 diff 只触 4 个已知文件 |
| 4 | 成本 | 小团队 monorepo，不做最大架构 | 团队设计文档自标 Planned | 方案 1（先做薄片） | 方案 2 成本最高 | 每个方案的迁移步数与回滚路径 |

## 5. 方案

### 方案 0 — 维持现状：把第三方插件当可信代码，继续 in-process 执行

**边界与所有权**：不新增边界。信任落在「审核/分发渠道」，而不是运行时。把预算投到分发签名、崩溃自动禁用、权限同意 UI、`permissionResolver` 接线这些**非架构**工作上。

**它解锁什么 / 假设**：最快能上线第三方插件；假设第三方插件都是受信任的内部或已审核来源，且单一插件崩溃全崩是可接受的。

**迁移与回滚成本**：迁移成本最低；回滚成本为零（没有可回滚的东西）。

**运维与测试后果**：无需新测试基建，但「一个插件崩 → 全应用崩」的运维风险永远存在；测试只能覆盖「守规矩插件」。

**使方案失效的证据**：出现任何不可信/公开市场插件，或团队认为「单插件崩溃不应带走整个应用」。

### 方案 1 — 进程隔离宿主，复用已声明的 transport seam（推荐）

**边界与所有权**：把「插件**作者契约**」与「插件**执行位置**」拆开。作者契约保持稳定：`ExtensionManifestV1` + `plugin-protocol` 中性类型 + kit/capability/resource/binding/权限模型。执行位置成为宿主决策：在 `ExtensionHost` 里填上已经声明但未实现的 `node-worker` 或 Electron `utilityProcess` 传输，让 `setup(ctx)` 在隔离进程里跑，通过 Eventa 与宿主通信。宿主的权限门保持为**纵深防御**（进程内仍有 grant 检查），但真正的安全边界是进程隔离。

**它解锁什么 / 假设**：第三方插件安全落地、崩溃隔离、按插件启用隔离运行时（一方插件可继续 in-process）。假设：现有 SDK 的 `ctx` 作者侧 API 可以做到**源码兼容**地跨消息传递（即 `defineExtension({ setup(ctx) })` 不因隔离而重写）。

**迁移与回滚成本**：中等。要补的是 transport 实现 + session 生命周期（启动/停止/超时/部分消息/序列化）+ 崩溃处理，而不是重画架构——`PluginTransport`、`createPluginContext`、`channels/*`、`ExtensionHost` 的 `runtime` 字段都已在。回滚干净：按扩展加 `runtime` 特性开关，默认回 in-process，一方插件不动。

**运维与测试后果**：新增恶意插件/崩溃注入测试、超时测试；序列化性能有少量开销，可用「一方插件保持 in-process」规避。

**使方案失效的证据**：若第三方其实都是可信内部插件（方案 0 更省）；或插件的真实诉求必须直接触碰 Electron 渲染对象/主进程对象，消息边界做不出来；或 SDK 作者侧 API 无法做到源码兼容（那要先稳定 API 再做隔离）。

### 方案 2 — 远程/独立后台宿主：第三方插件跑在独立进程，走 server channel WebSocket

**边界与所有权**：把「插件宿主」整个挪到独立长生命周期进程（复用 `server-runtime` 或专用 daemon），通过已有的 `extension:announce` / `peer:authenticate` 握手 + `server-sdk` 的 `WebSocketExtensionPeer` 与宿主通信。隔离最强，且宿主可独立重启、可 headless 部署，与「独立后台」合并成一个能力。

**它解锁什么 / 假设**：插件宿主不随应用崩溃/升级，跨设备/后台常驻场景。假设：需要宿主比应用生命周期更长，或需要独立部署，且团队愿意承担双进程 + 协议运维成本。

**迁移与回滚成本**：最高。目前只有**客户端侧** peer 与 stub 通道；宿主侧的远程会话模型、发现/健康/监督、第二个分发产物都要新做，还要把 in-memory 的 `ExtensionSession` 模型对齐到远程 peer。回滚困难（涉及进程拓扑与协议）。

**运维与测试后果**：最完整的崩溃隔离与重启能力，但引入网络语义（重连、心跳、背压、版本协商）——设计文档把这些列为待定项。

**使方案失效的证据**：不需要宿主独立部署/常驻，或双进程 + 协议维护成本超出小团队预算（此时它是正确的长期形态，但错误的第一步）。

### 方案 0/1/2 速览

| | 方案 0 现状 | 方案 1 进程隔离（推荐） | 方案 2 远程宿主（延后） |
| --- | --- | --- | --- |
| 安全边界 | 无（信任分发渠道） | 进程隔离 + 逻辑权限 | 进程隔离 + 网络认证 |
| 崩溃隔离 | 无 | 单插件 | 整个插件宿主 |
| 首次成本 | 低 | 中 | 高 |
| 回滚 | 零 | 特性开关切回 in-process | 难（进程拓扑变化） |
| 何时错 | 出现不可信插件 | 插件都是可信的 | 无需独立部署/常驻 |

## 6. 推荐

**选方案 1，作为第一个垂直切片；方案 2 作为明确的 revisit 条件，不要现在做。**

应该**稳定**的边界（这些已经存在且质量高，别动它们的形状，只收口）：

1. **插件作者契约**：`ExtensionManifestV1`（已版本化）+ `plugin-protocol` 中性类型 + kit/capability/resource/binding + 权限（area/action/key、通配、交集）模型。这是第三方作者会长期写代码对着它的接口。
2. **每窗口 Eventa 上下文**：`windows/X/index.ts` + `windows/X/rpc/index.electron.ts` + `createContext(ipcMain, window)` 的模块形状。
3. **injeca provider 键**（`windows:X` / `modules:X` / `services:X`）：DI seam 已经清晰，加窗口时沿用它。
4. **`ServerManager` 的 `start/stop` 生命周期契约** + server channel 握手（`extension:announce`/`peer:authenticate`）。
5. **窄能力接口模式**：插件永远拿 `ExtensionHostGameletWidgetsManager` 这类窄接口，而不是 `BrowserWindow`/`ipcMain`——这是本仓库里最值得保持的深模块做法，新的插件能力都应照此办理。

应该**延后**的抽象（现在建是过度设计）：

1. **方案 2 的远程宿主**：客户端 peer 与 stub 通道已在，但没有「插件宿主需要独立部署/常驻」的证据。
2. **声明式窗口注册框架**：现有 `createReusableWindow`（单例）和 `createReferencedWindowManager`（多实例）已覆盖两种形态。只有当插件需要**注册新窗口类型**（而非往 widgets 窗口里塞 widget）时才引入。
3. **应用内独立后台进程**：`server-runtime` 独立 bin 已存在，应用内复用同一 `createServer`；没有测到内存/崩溃隔离压力前不要拆。
4. **完整生命周期状态机、协议版本协商、可靠 WS 帮助库、打包/分发格式**：设计文档自己列为 non-goals/待定。
5. **分发签名/市场**：这是产品+基础设施决策，不是仓库内抽象；但对「不可信第三方」它是**前置条件**，应当并行推进而不是延到隔离做完之后。

**被拒绝的替代**：方案 0 会在第一个不可信插件出现时被迫仓促补隔离（最贵时机）；方案 2 作为第一步对小团队过重且缺少证据。

**不改变的后果**（针对方案 0 的代价）：一旦第三方插件落地，主进程即成为单点——一个插件的崩溃/恶意行为带走所有窗口、托盘和内置 server；逻辑权限给用户「已授权」的错觉而实际上插件能绕过它直接读写文件与 token；`setMaxListeners` 技术债随窗口数持续累积。这些都不是「以后更好做」的债，而是会随时间变贵的债。

## 7. 迁移与验证（可验证的渐进路线）

每一步都可逆、可独立合并：

**第 1 步（首个垂直切片，方案 1）**：把一个一方插件经 `node-worker`（或 `utilityProcess`）传输跑通，**作者 API 不变**。完成标准：
- 契约测试：`defineExtension({ setup(ctx) })` 的同一份插件代码，在 in-process 与隔离运行时下行为一致（源码兼容）。
- 安全测试：隔离插件 `import('node:fs')` / `process.exit()` / 读 `app.getPath('userData')` 均被隔离或拒绝（deny-by-default），并验证逻辑权限门仍作为第二层在起作用。
- 崩溃/挂起测试：插件 throw 或死循环不带走主窗口与内置 server；宿主能 `stop/reload` 该 session；超时与部分消息有确定行为。
- 回滚：特性开关 `runtime: 'electron'`（in-process）↔ `runtime: 'node-worker'`，一方插件默认保持 in-process。

**第 2 步（多窗口收口，与第 1 步并行）**：完成 Eventa 窗口命名空间路由，移除 `main/index.ts:58` 与 `referenced-window.ts:44` 的两处 `setMaxListeners` 兜底。完成标准：
- N 个窗口各持上下文，断言无跨窗口 invoke/handler 泄漏，监听器数有上界、不随窗口数线性增长。
- 回滚：这是纯收口，行为不变，可独立回退。

**第 3 步（安全/运维补全，第三方上线前置）**：接线 `permissionResolver`（安装时同意 + 持久化 grant），加「插件崩溃自动禁用/安全模式」，接插件签名校验。完成标准：权限授予/撤销在运行时生效，撤销能终止活跃 session；崩溃阈值触发自动禁用。

**第 4 步（后台协议收口）**：去重 `/ws` 字面量（`channel-server/index.ts:104` 已自述 TODO），把 server channel 路径收敛到单一来源；保持 `ServerManager` 生命周期不变。完成标准：改路径只动一处，现有配对/认证测试全绿。

**回滚总原则**：每一步都以「特性开关/独立合并」为单位，第 1 步的隔离运行时可整体切回 in-process；第 2–4 步是行为不变的收口。

**验证清单（依赖/架构检查）**：
- 类型检查 + lint（仓库既有 `pnpm typecheck` / `pnpm lint`）。
- 契约测试穿过**作者侧接口**（`plugin-protocol` + `defineExtension`），而不是穿过内部实现。
- 安全与崩溃测试用真实进程隔离 + 恶意插件样本，不 mock 平台能力。
- 多窗口测试断言「无跨窗口泄漏 + 监听器有界」。
- 后台测试覆盖 start/stop/restart、token 轮换、证书信任、路径去重。

## 8. 开放决策（答案会改变推荐）

1. **「第三方」到底指什么**：公开市场的不可信插件，还是受信任的内部/已审核分发？若是后者，方案 0 可能就够，方案 1 的优先级应下调。（未知）
2. **「独立后台」要求的是 OS 级崩溃隔离，还是只是逻辑分离**？若要 OS 级隔离或 headless 部署，方案 2 会提前进入视野。（未知）
3. **插件是否需要定义新的窗口类型**，还是只往现有 widgets 窗口塞内容？现有证据是后者（`ExtensionHostGameletWidgetsManager` 只有 push/update/remove widget）。若出现前者，声明式窗口注册才值得建。（推断，需产品确认）
4. **隔离运行时的平台取舍**：Electron `utilityProcess` 与 `node:worker_threads` 在能力（能否用 Electron API、崩溃语义、内存上限）上不同，需要一次原型验证再定默认值。（未知，最便宜的验证是第 1 步跑两个 spike）
5. **签名/分发渠道的归属与时间表**：它是第三方插件的前置条件，但不在仓库内架构决策里；需要单独定。（未知）

建议把「插件信任边界：in-process 可信 / 隔离运行时不信任 / 远程宿主」写成一条 ADR，因为它会决定未来第三方插件的安全模型，且后人会反复重开这个讨论。

[EVAL:evolve-software-architecture-loaded]
