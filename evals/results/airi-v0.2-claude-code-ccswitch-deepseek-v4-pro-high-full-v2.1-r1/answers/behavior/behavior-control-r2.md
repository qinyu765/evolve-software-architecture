调研完成。我通读了桌面端主进程组合根、插件宿主与 SDK、窗口管理器、服务端通道与 `services/`、`plugins/` 目录的真实代码。结论先行：

**AIRI 桌面端已经有一个设计良好的"插件宿主"抽象（`packages/plugin-sdk` 的 `ExtensionHost` + manifest + 权限 + kit + binding 模型），这是应当立即冻结并守护的边界；但"独立后台"所需的远程传输层只有脚手架没有实现，"更多窗口"目前靠手工在组合根接线，二者都还不该做成大一统框架。** 最稳健的路线是"冻结契约 + 维持进程内/进程外两轨"，把远程传输作为唯一受门控的下一步，声明式窗口注册表则应明确延后。

---

## 1. 现状地图（依据代码）

三条能力线今天各有一个"已经存在"的骨架，成熟度差异很大：

**第三方插件 — 骨架最完整。** `apps/stage-tamagotchi/src/main/services/airi/plugins/` 是一套真插件宿主：从 `extensions/v1` 发现 `extension.airi.json`（`host/registry.ts:62-165`），Valibot 校验 manifest，持久化 enabled/autoReload，静态资源托管 + auto-reload，并把 list/load/unload/inspect/tools/capabilities 桥接成 IPC（`plugins/index.ts`）。底层 `packages/plugin-sdk/src/plugin-host/core.ts` 实现了会话、模块、双层权限（扩展级权限 ∩ 模块级权限）、kit/binding/资源/能力生命周期。Manifest 契约在 `packages/plugin-sdk/src/plugin-host/shared/types.ts:233-253`：`apiVersion: 'v1'`、`kind`、`id`、`permissions`、`entrypoints{default,electron,node,web}`。

**独立后台 — 有一条"服务端通道"，但和插件宿主是两条平行协议。** `packages/server-runtime` 在 6121 端口起 WebSocket 服务（`server/index.ts:108-243`），`packages/server-sdk` 提供 announce/authenticate/registry-sync/heartbeat + 重连退避的客户端（`client.ts`）。它被内嵌进 Electron 主进程（`channel-server/index.ts:357-449`，含 TLS 证书、配对二维码、配置回滚）。`services/` 下的 6 个服务（discord-bot、telegram-bot、twitter、minecraft、satori、computer-use）和 `plugins/` 下的 5 个插件都是**独立进程**，通过 `server-sdk` 连这条通道。注意：这条通道与 `plugin-sdk` 的远程通道**没有接上** —— `plugin-sdk/src/plugin-host/runtimes/node/index.ts:24-38` 和 `web/index.ts:23-37` 里 `websocket`、`node-worker` 等 transport 全部 `throw 'not implemented'`，只有 `in-memory` 可用。

**更多窗口 — 目前是命令式、手工接线。** `apps/stage-tamagotchi/src/main/index.ts:132-270` 用 injeca 逐个 `provide('windows:*')`，14 个窗口模块各返回一个 manager。有 `createReusableWindow`（`window-manager/reusable.ts:5`）做单实例复用，widgets 窗口是唯一的"多表面通用窗口"。`desktop-overlay` 展示了环境变量门控（`AIRI_DESKTOP_OVERLAY=1`），也暴露了组合模型的别扭处：因为没别的 provider 依赖它，需要显式 `injeca.invoke({ dependsOn: { desktopOverlay } })` 强制构建（`index.ts:251-257`）。"后台"目前靠**隐藏窗口**实现（`windows/beat-sync/index.ts:10-25` 的 `show: false` 音频采集窗口），配托盘保活。

---

## 2. 应该冻结/稳定的边界

这四层是第三方开发者、外部进程和渲染层共同依赖的契约，一旦公开就属于"改变即破坏"：

1. **插件 manifest 与作者入口。** `ExtensionManifestV1`（`apiVersion`、`id`、`permissions`、`entrypoints`）＋ `defineExtension({ setup })` ＋ 会话/模块身份（`extensionId` / `sessionId` / `moduleId`）。它已经版本化（`v1`）并有 schema 校验，是唯一该对外承诺兼容面的东西。冻结方式不是改代码，而是把 schema 一致性测试 + `apiVersion` 协商语义固定下来（见路线 Phase 0）。
2. **kit 与能力契约。** `KitDescriptor`/`KitRef`、`kit.gamelet`/`kit.widget`/`kit.tool` 的 id 与版本、能力的 `announced/ready/degraded/withdrawn` 生命周期、binding 的 announce/activate/update/withdraw。这是宿主给插件的 API 面，也是未来"远程插件"要复用的语义面。
3. **服务端通道线协议。** 模块 announce/authenticate/registry-sync/heartbeat、事件信封、superjson codec、端口/令牌/TLS。`services/` 和 `plugins/` 已经依赖它，是"独立后台"的事实边界。
4. **Eventa 的 IPC 命名空间约定。** `eventa:invoke:electron:…` / `eventa:event:electron:…`（`apps/stage-tamagotchi/src/shared/eventa`）。这是 renderer↔main 的稳定面。当前它有技术债：插件相关类型在 `shared/eventa/plugin/*` 里**手抄**了一份而不是 re-export `plugin-sdk`（代码里已有 TODO，`capabilities.ts:42-44`）——这属于"该稳定但先要做干净"的边界。

其中有一个**必须点名的事实**：`ExtensionHost` 的权限模型是好的，但 Electron 宿主构造时 `new ExtensionHost({ runtime: 'electron' })` **没有传 `permissionResolver`**（`host/index.ts:236`），于是 `core.ts:249-259` 里 `granted = permissionResolver?.() ?? manifest.permissions`，即**请求即授予**。模型可以冻结，但"授权策略（用户同意 UI / 签名 / 信任级别）"目前是缺口——在真正开放第三方安装前，这是要比远程传输更优先补的洞。

## 3. 应该延后的抽象

1. **"万物皆插件"的统一运行时。** 不要现在把进程内 `ExtensionHost` 和进程外 server-channel 合并成一个抽象。两者信任模型不同（见下），强行统一会在隔离、权限、生命周期上制造大量兼容负担，而收益（同一个 manifest 两处跑）目前只有理论价值。
2. **远程/`node-worker` 传输的完整实现。** 脚手架在，但没有任何插件在用。等有具体需求（比如第一个需要崩溃隔离的第三方插件）再实现，且只实现 websocket 一种、放实验门控。
3. **声明式窗口注册表 / 窗口 manifest。** 现在所有窗口都是一方、静态已知的。做一个"插件在 manifest 里声明 windows，组合根自动装配"的系统是投机性设计；正确做法是先把已有的 `createReusableWindow` + 窗口生命周期契约提取成小型类型化助手，保持显式接线。
4. **插件拥有原生 `BrowserWindow`（即 `kit.window`）。** widget/gamelet kit 已经给插件一个沙箱化 UI 面（iframe/widget 挂进 widgets 窗口）。给插件原生窗口权是巨大的权限/安全面，必须等隔离（进程边界）先成立。
5. **通用权限同意 UI 框架。** 同意 UI 是应用功能，不是要提前抽象的框架；先把 `permissionResolver` 接上、按领域列权限即可。

## 4. 方案比较

| 维度 | A. 基线：冻结契约 + 维持两轨（推荐） | B. 统一传输：把 websocket/worker 接入 `ExtensionHost` | C. 声明式窗口/能力注册表 |
|---|---|---|---|
| 隔离/安全 | 进程内=受信插件；进程外=server-channel。层次清楚 | 好：远程插件获得进程隔离 | 不变（窗口是 UI 面，不是隔离面） |
| 可扩展性 | 第三方插件走 v1 manifest；后台走 server-channel；新窗口显式接线 | 一套 session/permission/kit 模型覆盖两处，最强 | 新窗口零改动组合根，最强（但只对"窗口"有效） |
| 可靠性/崩溃隔离 | 后台进程崩溃不拖垮桌面；进程内插件崩溃仍会拖垮主进程 | 远程插件崩溃可隔离，提升最大 | 无提升 |
| 成本 | 低：主要是契约测试、类型 re-export、小型提取 | 中高：实现传输、握手、会话恢复、跨进程权限映射 | 中：注册表 + 装配器 + 迁移 14 个窗口 |
| 风险 | 低 | 中：与现有 server-channel 协议重叠，可能产生第二套握手语义 | 高：一次性迁移现有窗口，容易抽象过度 |
| 回滚 | 天然可逆（只加测试/门控） | 传输是叠加的，关 flag 即回退 | 已迁移窗口难回退，需双轨并存期 |
| 不做的后果 | 第三方"安装/隔离/同意"仍缺失；后台仍靠隐藏窗口 | 继续两套协议，长期语义漂移 | 窗口继续手工接线，`index.ts` 变长但可控 |

**方案 A（推荐基线）**：把"进程内 `ExtensionHost`"作为唯一第三方插件面，把"server-channel"作为唯一独立后台面；新增窗口继续 `setup*` + injeca 显式接线，但把窗口生命周期契约提取成类型。风险最低，且它不排斥 B、C，是后两者的前置。

**方案 B（唯一值得受门控推进的下一步）**：实现 `createPluginContext` 的 websocket 分支，让远程插件复用同一套 manifest/session/permission/kit 语义。它解决的是今天最疼的点——`FileSystemLoader` 用 `await import(entrypoint)` 在**主进程内以完整权限执行第三方代码**（`runtimes/node/loaders/fs.ts:72-76`）。真正开放第三方安装，早晚要有进程隔离。但它和 server-channel 会短期重叠，所以必须先冻结 v1 契约再做。

**方案 C（明确延后）**：只在出现"第三方要贡献原生窗口"的真实需求时再启动，且应做成"能力 manifest 的子集"，而不是独立大系统。

## 5. 渐进迁移路线（可验证）

- **Phase 0 — 冻结契约（立即，零风险）。** 给 `extensionManifestV1Schema` 建立 conformance 测试（非法 manifest 拒载、`apiVersion` 不匹配拒载）；给 server-channel 的 codec/握手加 golden round-trip 测试（`server-runtime` 已有 codec/liveness 测试，补齐插件侧）；在 `shared/eventa` 把插件类型改为 re-export `plugin-sdk`（消掉 `capabilities.ts:42` 的 TODO），消除双源漂移。**验收**：`pnpm -F @proj-airi/plugin-sdk test`、`pnpm -F @proj-airi/server-runtime test` 全绿，且"手写 v1 manifest 的插件在未改动下继续加载"。
- **Phase 1 — 补授权缺口 + 窗口契约提取（低风险）。** 给 Electron 宿主接入 `permissionResolver`（先做"manifest 声明的权限打点/记录"级别的策略，再上同意 UI）；把 `createReusableWindow` 与窗口 manager 的公共形状（`getWindow/openWindow/close`）提取为类型化契约，但**不**自动注册。**验收**：一个集成测试证明插件请求了未授予的 kit 会被 `PermissionDeniedError` 拒绝。
- **Phase 2 — 受门控的远程传输（只有出现隔离需求时）。** 实现 websocket transport 一条路，复用 server-channel 的握手，把"进程外插件"作为 `ExtensionHost` 的一个 `runtime`/transport 选项，放环境变量门控。**验收**：一个 smoke 插件分别在 in-memory 和 websocket 下跑通同一个 v1 manifest，断言会话/权限/kit 行为一致；进程内路径回归不变。回滚 = 关闭门控。
- **Phase 3 — 声明式窗口/能力注册表（按需，非默认）。** 只有当插件确实要贡献原生窗口时才设计，且沿用能力模型（`capabilities` 声明 + 宿主裁决）而非另起炉灶。

**每条"不改变会怎样"已在上表"不做的后果"行；最应正视的是第一条：** 当前任何落到 `extensions/v1` 的插件都能在主进程执行任意 Node 代码，且没有用户同意、没有签名校验、没有安装流程。这不是"加功能"，而是开放第三方前的安全前置。

**回滚路径总结**：Phase 0/1 是纯增量（测试、re-export、授权策略），回退即删；Phase 2 传输是叠加路径，进程内宿主原样保留，关 flag 即回退；Phase 3 才需要双轨并存期。因此整条路线在任何阶段都可以停在"现状 + 已冻结的契约"而不会损失已有能力。

需要我把这份评估整理进 `docs/solutions/` 或展开某一相位（比如 `permissionResolver` 的接入策略、或 websocket transport 与 server-channel 的握手复用细节）吗？
