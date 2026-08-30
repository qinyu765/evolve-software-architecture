我已完成对仓库的实地勘察（只读，未修改任何文件）。下面是基于证据的架构评审。

## 1. 范围与置信度

评审对象是桌面端 `apps/stage-tamagotchi`（Electron + Vue + TypeScript），并关联到它实际依赖的插件/服务端共享包：`packages/plugin-sdk`、`packages/plugin-protocol`、`packages/plugin-sdk-tamagotchi`、`packages/server-runtime`、`packages/server-sdk`、`packages/server-shared`，以及 `plugins/` 下的示例插件。

**分类置信度：高。** 依据：`electron-vite.config.ts`、`electron-builder` 配置、`src/main` + `src/preload` + `src/renderer` 三段式、`src/main/windows` 下 15 个窗口模块、tray/global-shortcut/auto-updater 等 OS 集成。这是一个成熟的多窗口桌面应用，而非从零开始的项目——这改变了问题的性质：不是"要不要建插件系统/后台"，而是"现有缝（seam）哪些值得冻结、哪些应延后"。

## 2. 观察事实

| 论断 | 证据（路径/符号） | 性质 | 置信度 | 对决策的影响 |
| --- | --- | --- | --- | --- |
| 已有 15 个窗口模块 | `apps/stage-tamagotchi/src/main/windows/**/index.ts` | 事实 | 高 | "更多窗口"是增量问题，不是从 0 到 1 |
| 但只有 2 个 renderer HTML 入口，其余窗口共享 `index.html` 走路由 | `electron.vite.config.ts:99-106`（`main` + `beat-sync`） | 事实 | 高 | 新窗口主要成本在 main 侧注册 + 路由，而非新 renderer 入口 |
| 组合根手工用 injeca 装配约 20 个 provider | `apps/stage-tamagotchi/src/main/index.ts:113-272` | 事实 | 高 | 加窗口/服务必须改这个 350 行文件 |
| 窗口创建机制已抽象 | `libs/electron/window-manager/reusable.ts:5-37`、`services/electron/window.ts:20-123` | 事实 | 高 | 窗口"机制"稳定，需稳定的是"注册"路径 |
| 已有通用窗口工厂 | `shared/eventa/index.ts:97-108` `createRequestWindowEventa` | 事实 | 高 | 部分窗口模式已泛化 |
| 插件系统已有进程内 host | `packages/plugin-sdk/src/plugin-host/core.ts` `ExtensionHost` | 事实 | 高 | 这是第三方插件最重要的稳定边界 |
| manifest v1 已 schema 校验，含权限区/入口 | `packages/plugin-sdk/src/plugin-host/shared/types.ts:233-253,264-300,322-328` | 事实 | 高 | 第三方直接依赖的契约已存在 |
| 权限模型是双层（扩展上限 ∩ 模块申请） | `plugin-host/core.ts:56-60,249-327` | 事实 | 高 | 进程内已执行，远程未执行（见下） |
| Kit 描述符含 `kitId/version/capabilities/runtimes` | `plugin-host/shared/kits.ts:45-65` | 事实 | 高 | 扩展点机制已定型 |
| 内置 kit：widget/gamelet/tool | `services/airi/plugins/kits/index.ts:95-116` | 事实 | 高 | 第三方 UI 能力目前受限在 widget/gamelet 通道 |
| 插件发现扫描 `userData/extensions/v1`，支持 symlink | `services/airi/plugins/host/index.ts:228`、`host/registry.ts:62-163` | 事实 | 高 | 分发目前是"目录 + 符号链接"，无签名/市场 |
| 存在第二套远程插件路径：WebSocket peer | `packages/server-sdk/src/extension-peer.ts`、`plugins/airi-plugin-claude-code`（依赖 `server-sdk`） | 事实 | 高 | 进程内与进程外两套模型并存 |
| 服务端已实现 registry/consumer/heartbeat/routing | `packages/server-runtime/src/index.ts` `setupApp` | 事实 | 高 | "后台"协议已相当完整 |
| 但服务端丢弃了远程 peer 声明的 permissions/config/dependencies | `server-runtime/src/index.ts:685-722`（`extension:announce` 不读 `permissions`）、`724-775`（`extension:module:announce` 只取 `name/identity`） | 事实 | 高 | 远程路径存在安全语义缺口 |
| 后台服务内嵌于主进程，随 app 生命周期启停 | `services/airi/channel-server/index.ts:357-449`（`appHooks.onStart/onStop`） | 事实 | 高 | "独立后台"目前不独立于 UI 生命周期 |
| 但已有独立运行入口 | `packages/server-runtime/package.json:29` `bin`、`src/bin/run.ts` | 事实 | 高 | 独立运行的原始能力存在，缺编排/打包故事 |
| HTTP server 组合壳当前为空 | `main/index.ts:160` `setupBuiltInServer({ servers: [] })` | 事实 | 高 | 一个"胚胎级"抽象，未承载负载 |
| 插件契约类型在两处重复且已漂移 | `shared/eventa/index.ts:204-247` vs `shared/eventa/plugin/host.ts:60-197`（`autoReload`、`kits`/`modules` 字段不一致） | 事实 | 高 | 契约漂移正是第三方会踩的坑 |
| 漂移被 TODO 承认 | `shared/eventa/plugin/capabilities.ts:42-44` | 事实 | 高 | 团队已知晓 |
| eventa 尚无按窗口命名空间分发，靠 `setMaxListeners(100)` 缓解 | `main/index.ts:55-58` | 事实 | 高 | 窗口数继续增长会触及此限制 |
| `/ws` 字面量在三处重复 | `channel-server/index.ts:103-105` TODO | 事实 | 高 | 协议端点没有单一归属 |

## 3. 当前摩擦（变化放大点）

1. **新增一个窗口要动 3~4 处**：`main/index.ts` 的 injeca provider + `dependsOn` 装配、`main/windows/<name>/index.ts`、`shared/eventa/index.ts` 的窗口契约（除非复用 `createRequestWindowEventa`）、以及 `stage-pages`/renderer 路由。窗口**创建机制**（`createReusableWindow`/`createWindowService`）已经稳定，但窗口**注册**每次都要侵入组合根。

2. **插件契约类型双写并漂移**（`shared/eventa/index.ts` 与 `shared/eventa/plugin/*`）。这恰好是第三方插件将依赖的那条边界，漂移代价最高，应当优先收敛为单一归属。

3. **两套插件运行时语义不齐**：进程内 `ExtensionHost` 有完整的权限执行（`PermissionService` + 双层授权）；远程 `server-runtime` 接收 `extension:announce`/`extension:module:announce` 时**丢弃了 permissions/configSchema/dependencies**，只做鉴权与路由。这使"第三方插件权限"只在进程内成立。

4. **"独立后台"目前既不独立也不统一**：WebSocket server 内嵌在主进程、随 app 退出而停；同时存在独立 `bin/run.mjs`、MCP stdio 子进程、Godot sidecar 子进程三种后台形态，但没有统一的进程生命周期/崩溃隔离/编排抽象。`setupBuiltInServer({ servers: [] })` 是空壳，说明有人已预埋一个抽象但尚未使用。

5. **组合根为手工装配 + 事件广播上限**：`ipcMain.setMaxListeners(100)` 是窗口数增长的隐性天花板；窗口命名空间化被 TODO 推迟。

## 4. 质量属性优先级（按权重排序）

| 属性 | 目标/预算 | 当前证据 | 哪个方案最受益 | 可能退化的属性 | 验证方式 |
| --- | --- | --- | --- | --- | --- |
| 可扩展性 / 进程边界稳定性（最高） | 第三方插件、新窗口不要求改宿主内部 | manifest v1、KitDescriptor、协议 envelope 已存在但契约双写 | B（冻结契约 + 单一归属） | 迁移期间类型耦合 | `pnpm -F @proj-airi/stage-tamagotchi typecheck` + 契约回归测试 |
| 安全 | 第三方代码不可信；权限在所有路径执行 | 进程内已执行，远程丢弃 permissions | B（补齐或明确豁免远程） | 运维便利性 | 恶意 manifest 的进程内 + 远程测试 |
| 可运维 / 生命周期 | 后台可启动/停止/崩溃恢复/回滚 | channel-server 有 mutex 与配置回滚，但随 UI 退出 | B（先做 spike，再定拓扑） | 复杂度 | 崩溃/退出/重启场景测试 |
| 可维护性 / 局部性 | 加窗口/插件不散落多处 | 组合根 350 行手工装配；契约双写 | B | 无 | "加一个窗口"的文件改动计数 |
| 可测试性 | 不经真实 Electron 运行时验证契约 | 大量 `*.test.ts` 已存在（registry、static-assets、channel-server config） | A/B 均受益 | 无 | 定向 vitest |

## 5. 方案对比

### 方案 A：维持现状（增量小修，不引入新抽象）

保留当前形态：窗口在 `index.ts` 手工装配；进程内 `ExtensionHost` 与远程 peer 都跑在主进程；契约在 `shared/eventa` 本地双写。

- **优点**：零迁移成本；现有缝（`ExtensionHost`、kits、`server-runtime`、`createReusableWindow`）已经真实可用，短期不阻塞功能。
- **质量权衡**：可维护性与契约稳定性继续恶化；每加一个窗口/插件都在组合根和契约层重复劳动；远程权限缺口继续存在。
- **成本**：短期最低，长期线性增长。
- **风险**：契约漂移一旦被第三方插件依赖，修复就从"内部重构"变成"破坏性 API 变更"。
- **回滚**：无需回滚。
- **不改变的后果**：窗口数继续增长时，`setMaxListeners(100)` 与手工装配会先成为真实瓶颈；插件生态一旦起步，契约双写会成为向后兼容的负债。

### 方案 B：冻结现有缝 + 轻量注册层（推荐）

分两步：

1. **收敛契约单一归属**：把插件契约类型（manifest、permission、kit、capability、plugin snapshot）统一由 `plugin-protocol`（side-effect-free 类型源）或 `plugin-sdk` 导出，`shared/eventa` 改为 re-export，删除本地双写。
2. **引入声明式窗口/后台注册清单**：把 `index.ts` 中每个窗口的 `{ key, dependsOn, setup }` 抽成一个窗口描述符表（`windows/registry.ts`），组合根只做迭代装配；后台服务同样用"生命周期契约（start/stop/dispose）+ 协议 envelope"接入，但**不**新建通用进程抽象。
3. **补齐或显式豁免远程权限**：对 `server-runtime` 的远程 peer 权限做明确决策（见待决问题），不静默丢弃。

- **优点**：直接消除当前两个最大摩擦（契约漂移、组合根侵入）；不引入宽泛的层；每一步行为保持等价、可逐步落地。
- **质量权衡**：可扩展性/可维护性/安全提升；迁移期需要一次类型收敛的协调。
- **成本**：中等，但分步、可逆；无新基础设施。
- **风险**：低。最坏情形是描述符表抽象过度，退回到手工装配即可。
- **回滚**：删除 registry/清单，恢复旧 `index.ts`；契约收敛是类型级重导出，行为不变。
- **不改变的后果**：继续承担契约双写与组合根手工装配；一旦第三方生态起步，成本翻倍。

### 方案 C：全面泛化（插件可声明窗口/后台 + 独立后台进程 + 签名/市场）

让第三方插件通过同一套 kit/capability 机制声明任意窗口、后台服务与系统能力；把 `server-runtime` 移入独立 `utilityProcess`/守护进程；引入插件签名、市场、自动更新。

- **优点**：理论上最"平台化"。
- **质量权衡**：牺牲可运维性与成本，换取想象中的扩展性；在只有一个真实第三方窗口变体之前，这是典型的"宽泛层方案"（broad layer scheme）。
- **成本**：高；需要安全模型、签名基础设施、进程编排、跨版本协议协商全部到位才能不返工。
- **风险**：高——提前冻结错误的东西；当前只有 widget/gamelet 这一条受约束的插件 UI 通道，泛化窗口会打开大得多的攻击面。
- **回滚**：高成本；已发布的插件契约难以回滚。
- **不改变的后果**：现在不做的机会成本有限，因为没有任何证据表明需要插件声明任意原生窗口。

**结论：选 B。** A 作为过渡期可接受但不应继续默认；C 应明确延后。

## 6. 建议：哪些边界稳定，哪些抽象延后

### 应当冻结（稳定边界）

这些都是第三方与未来窗口/后台会直接依赖、且已被现有代码实践过的缝：

1. **插件 manifest 契约**（`packages/plugin-protocol` + `plugin-sdk` 的 `ExtensionManifestV1`）：`apiVersion: 'v1'`、`kind`、`id`、`permissions` 的五个区（apis/resources/capabilities/processors/pipelines）× 动作、`entrypoints{default,electron,node,web}`。已 schema 校验；现在冻结成本最低。**永远不要自动改写用户的 manifest**，v2 演进用 apiVersion 显式迁移。
2. **Kit + capability + resource 契约**：`KitDescriptor`（`kitId/version/capabilities/runtimes`）、capability 生命周期（`announced/ready/degraded/withdrawn`）、resource key。新 kit 只做加法。
3. **窗口生命周期契约**：`createWindowService` 暴露的 bounds/lifecycle/alwaysOnTop/safeClose 语义。新窗口应复用而非重实现。
4. **后台协议 envelope**（`packages/server-shared`）：`WebSocketBaseEvent`（`type/data/metadata.source/event.id/parentId`、`route`）、registry sync、heartbeat。这是"独立后台"进程间通信的稳定面。
5. **权限声明形状**（areas × actions）。声明形状稳定；**执行**（见下）要补齐。
6. **插件发现目录 + symlink 模型**：`extensions/v1`。这是第三方本地安装的稳定入口。

### 应当延后（不要现在建）

1. **插件声明任意窗口 / 任意系统能力**：保持 widget/gamelet 为插件唯一的受约束 UI 通道，直到出现 ≥2 个真实第三方窗口变体。
2. **把 `server-runtime` 移出主进程做成守护/utilityProcess**：先用 `bin/run.mjs` 做打包/运维 spike，验证"UI 关闭后台仍存活/崩溃恢复/重启"是否真的是需求，再决定拓扑。
3. **插件签名、市场、自动更新**：分发是产品/运维问题，不是架构缝；先保留目录发现。
4. **统一两套 HTTP 服务路径**（`setupBuiltInServer({servers: []})` 空壳 vs 插件 `static-assets`）：`servers: []` 是尚未使用的预埋抽象，可先移除或只保留最小生命周期契约，不要泛化。
5. **eventa 按窗口命名空间化**：`setMaxListeners(100)` + TODO 是已记录的临时缓解；等窗口数真正触顶再重构。
6. **为窗口服务引入 `Dependencies`/`Deps` 对象**：继续用 injeca 作为装配机制，不为内部 helper 再造一套注入。

## 7. 迁移与验证（可逆、渐进）

**步骤 0 — 基线（可逆，纯测量）**
- 给 manifest v1 + permission 五区 + kit/capability 契约加一个回归测试/类型锁（`extensionManifestV1Schema` 已存在，可围绕它写 contract test）。
- 记录"加一个窗口"当前改动文件数（预期 3~4 个），作为后续局部性的对照指标。

**步骤 1 — 收敛契约单一归属（可逆、低风险）**
- 让 `shared/eventa/index.ts` 与 `shared/eventa/plugin/*` 从 `@proj-airi/plugin-protocol/types`（side-effect-free 类型源）或 `@proj-airi/plugin-sdk` re-export，删除本地重复的 `PluginManifestSummary`/`PluginRegistrySnapshot`/`PluginHostDebugSnapshot`/`PluginCapability*`。
- 注意：`shared/eventa` 同时被 renderer 与 main 引用，只做**类型导入**（`import type`），避免把 Node/Electron 运行时引入 renderer——这符合仓库"类型走中性模块"的规则。
- 验证：`pnpm -F @proj-airi/stage-tamagotchi typecheck`、`pnpm lint`，以及 `shared/eventa/plugin/*.test.ts` 与相关 renderer 测试通过；grep 确认无第二处声明。

**步骤 2 — 窗口描述符清单（可逆、行为等价）**
- 先取一个已有窗口（建议 `notice`，它已经用 `createRequestWindowEventa` 泛化）做垂直切片：把 `{ key, dependsOn, setup }` 移入 `windows/registry.ts`，`index.ts` 改为迭代装配。行为完全不变。
- 验证：应用启动、该窗口能开、相关测试通过；"加一个窗口"的文件改动数从 3~4 降到 ≤2（描述符 + 路由）。

**步骤 3 — 远程权限决策（安全，需 ADR）**
- 二选一并写 ADR：a) 在 `server-runtime` 的路由中间件中真正执行远程 peer 声明的 permissions；b) 明确把远程路径定为"受信 LAN 配对"（有 authToken/TLS），只进程内执行权限，并记录豁免理由。
- 验证：a 路线加一个"恶意 permission 的远程模块被拒"的集成测试；b 路线加文档 + 注释。

**步骤 4 — 后台进程 spike（延后触发，可逆）**
- 仅当有具体驱动（例如"关闭 UI 后 bot 继续运行"）时：用 `server-runtime` 的 `bin` 作为子进程/utilityProcess 启动一次，测量启动/退出/崩溃恢复，再决定是否抽象"进程生命周期管理"。

**回滚路径**：每一步都是行为等价或纯增量；回滚即删除 registry/清单、恢复旧装配。契约收敛是 re-export 级别，插件不感知。
**完成判据**：
- 仓库内不存在第二处插件契约类型声明（grep/typecheck 可验证）；
- 加一个窗口的文件改动 ≤2 个；
- `typecheck` + `lint` + 定向 vitest 全绿；
- 一个契约回归测试锁住 manifest v1 与权限五区。

## 8. 待决问题（答案会改变建议）

1. **远程 peer 的信任模型**：`server-runtime` 连接的 bot/CLI 插件是可信还是不可信？（决定步骤 3 走 a 还是 b。）
2. **第三方插件的到达时间与分发方式**：近期是否有真实第三方插件？决定 `extensions/v1` + symlink 是否够用，以及签名/市场的优先级。
3. **"独立后台"的确切产品语义**：是"UI 关闭后台仍存活"、"无头运行"、还是"多设备连接"？决定是否值得把 server 移出主进程，以及用 utilityProcess 还是独立打包。
4. **契约版本化策略**：`apiVersion` 已为 `v1`，v2 的迁移规则是什么（拒绝 / 警告 / 迁移）？

---

**一句话结论**：AIRI 桌面端已经具备比大多数同类项目更成熟的插件与后台缝，问题不是"要不要建"，而是"哪些缝现在冻结、哪些抽象继续等"。建议冻结 `plugin-protocol`/manifest/kit/capability/window 生命周期/协议 envelope 这五条边界并收敛契约单一归属，同时明确延后"插件声明任意窗口、独立守护进程、插件签名市场、eventa 窗口命名空间化"四件事；走方案 B 的四步渐进迁移，每一步行为等价、可回滚。

[EVAL:evolve-software-architecture-loaded]
