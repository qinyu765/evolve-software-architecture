## 结论先行

AIRI 桌面端在三条能力轴上（第三方插件、更多窗口、独立后台）**都已经存在相当成熟的雏形**，真正缺的不是新抽象，而是把三个已经存在但尚未"锁定"的边界固定下来，并且**刻意延后**沙箱运行时、通用窗口注册表、统一后台框架这些大件。最危险的一个事实：插件权限系统完整存在，但 `ExtensionHost` 在应用里被裸构造、没有接 `permissionResolver`，且插件代码通过 `import()` **直接加载进 Electron 主进程**——这对第一方/可信插件够用，对"第三方插件"是错误默认。

建议采用**方案 B（渐进式锁定边界）**：先冻结契约、后按真实需求引入隔离，而不是现在就去建"插件沙箱 + 窗口注册表 + 后台调度框架"。

---

## 一、基于仓库证据的现状地图

### 1. 第三方插件轴：已有完整主机，但信任模型是"全权同进程"

插件系统不是空壳，而是已经分层：

| 层 | 位置 | 现状 |
|---|---|---|
| 协议/权限语言 | `packages/plugin-protocol`、`packages/plugin-sdk/src/plugin-host/shared/types.ts` | 五类权限区（apis/resources/capabilities/processors/pipelines）+ key/action + 通配符 |
| 主机核心 | `packages/plugin-sdk/src/plugin-host/core.ts` | `ExtensionHost`：session、kit、binding、resource、capability、`PermissionService` |
| 内置 kit | `packages/plugin-sdk-tamagotchi` + `apps/stage-tamagotchi/src/main/services/airi/plugins/kits/` | gamelet / widget / tools 三类 |
| Electron 装配 | `apps/stage-tamagotchi/src/main/services/airi/plugins/host/index.ts` | 清单发现、启用/加载/卸载、静态资源、自动重载、inspect |

关键事实（全部有源码依据）：

1. **权限钩子存在但没接线。** `ExtensionHostOptions.permissionResolver` 在 `packages/plugin-sdk/src/plugin-host/shared/types.ts:365` 定义、在 `core.ts:250-260` 被消费，但应用侧是 `new ExtensionHost({ runtime: 'electron' })`（`apps/stage-tamagotchi/src/main/services/airi/plugins/host/index.ts:236`）——没有 resolver。于是清单里声明的权限被**默认全量授予**（`core.ts:255` 的 fallback 是 `options.manifest.permissions`）。

2. **插件逻辑运行在主进程，全权。** `FileSystemLoader.loadExtensionFor` 直接 `await import(entrypoint)`（`packages/plugin-sdk/src/plugin-host/runtimes/node/loaders/fs.ts:72-76`）。插件能碰到的不是受限 API，而是 Node + Electron 主进程能力（文件、网络、原生模块、`app`/`session`）。

3. **隔离雏形只在 UI 侧，不在逻辑侧。** 插件 UI 通过 loopback HTTP + cookie 会话 + iframe 挂载（`plugins/features/static-assets/index.ts`、`http-server/static-assets/`），渲染器侧有 origin 隔离；但插件**逻辑**仍在主进程。

4. **node/web 运行时和 worker/websocket 传输全是 stub。** `packages/plugin-sdk/src/plugin-host/runtimes/node/index.ts:24-39` 对 websocket / node-worker / electron 传输一律 `throw new Error('... not implemented yet.')`。清单 schema 里有 `entrypoints.node/web`（`shared/types.ts:243-252`），但应用里只有 electron 路径可用。

5. **无签名/信任/沙箱/allowlist 机制。** 在 plugin-sdk 全包搜索 `third-party / untrusted / sandbox / signature / integrity / allowlist` 零命中。清单只有 `id / kind / apiVersion / permissions / entrypoints`，没有来源、签名、哈希、最小权限审批。

6. **分发渠道缺失。** 只有本地 `extensions/v1` 目录 + `extensions-v1.json` 的 enable/known 记录（`plugins/host/config.ts`），没有安装器、市场、更新、卸载校验。

### 2. 更多窗口轴：手动但规整，窗口 = 路由 + 契约

- 每个窗口一个目录：`apps/stage-tamagotchi/src/main/windows/<name>/index.ts` + 同目录 `rpc/index.electron.ts`，公共基础在 `windows/shared/window.ts`（base invokes + 导航守卫 + 窗口配置工厂）。
- 渲染端是**单一 SPA 入口**：`electron.vite.config.ts:100-105` 只有 `main` 和 `beat-sync` 两个 input；其余窗口是 `main` 入口下的 hash 路由（`windows/chat/index.ts:47` 的 `withHashRoute(..., '/chat')`）。预加载是共享的 `index.mjs`，且所有窗口 `sandbox: false`。
- 窗口在 `apps/stage-tamagotchi/src/main/index.ts:171-258` 通过 injeca `provide('windows:<name>', ...)` 手动编排依赖图；唯一的复用基元是 `createReusableWindow`（`libs/electron/window-manager/reusable.ts`）——**没有窗口注册表/管理器抽象**。
- Eventa 已经支持 `createContext(ipcMain, window)` 的窗口命名上下文（`windows/chat/rpc/index.electron.ts:29`、`windows/desktop-overlay/rpc/index.electron.ts:39`），但目前靠 `ipcMain.setMaxListeners(0/100)` 打补丁，代码里三处 TODO 明说"等 eventa 真正支持 window-namespaced 分发后移除"。

结论：加窗口的成本是**线性、可预测、可回滚**的，模式已经事实上稳定，只是没有固化为契约。

### 3. 独立后台轴：两种形态并存，已经干净

- **进程内生命周期服务**：server-channel（WebSocket + TLS + QR 配对 + auth token，`services/airi/channel-server/index.ts:357-449`）和 http-server（H3，auth + static-assets 组合，`services/airi/http-server/index.ts:22-38`），都通过 injeca `lifecycle.appHooks.onStart/onStop` + mutex 管理。
- **子进程侧车**：MCP stdio 管理器（`services/airi/mcp-servers/index.ts`，spawn 配置的命令）和 Godot stage 侧车（外部进程）。

这两类没有统一成一个"后台框架"，但目前也没有统一的需求压力——各自的生命周期都已经写清楚。

### 4. 一个隐藏的边界债务：provider 注册表

`packages/stage-ui/src/stores/providers.ts` 是 3000+ 行的硬编码 `providerMetadata` 字典，没有动态注册入口。未来"第三方插件想带一个 provider"时，这里会变成第二条注册路径，需要提前想清楚它和"插件工具/MCP"的关系。

---

## 二、边界分类：现在稳定 vs 刻意延后

### 应稳定（先锁定契约，不需要新机制）

| # | 边界 | 为什么现在锁 | 锁定的方式 |
|---|---|---|---|
| S1 | **扩展身份与清单契约**（`ExtensionId`、`ExtensionManifestV1` 的 `kind/apiVersion/id/entrypoints`） | 它是唯一跨进程、跨版本、可校验的稳定锚点；schema 已被 Valibot 锁住（`registry.ts:20-22`） | 冻结 v1 schema；为"解析失败/缺 entrypoint/重复 id"补契约测试；明确"新增字段走 v2 还是向后兼容" |
| S2 | **权限声明语言**（`plugin-protocol` 五区 + key/action + `*` 通配 + 交集语义） | 纯类型 + 纯校验、无副作用；`PermissionService` 的交集/合并语义已有大量注释和测试。先锁"语言"，后做"授权执行" | 把交集/合并语义固化为 property 测试；不扩区（processors/pipelines 目前无生产/消费者，只保 schema 不动运行时） |
| S3 | **窗口身份 = hash 路由 + eventa 契约命名空间** | 已经事实标准化（`windows/<name>` + `createRequestWindowEventa(namespace)` 工厂）；这是"更多窗口"不腐烂的关键 | 把命名规范和"route ↔ preload ↔ rpc 契约"的关系写成契约文档 + 一个窗口级契约测试样例 |
| S4 | **后台生命周期契约**（injecta `dependsOn` + `onStart/onStop` + dispose 顺序） | server-channel / http-server / mcp 已经一致遵循；后台能力扩展会复用同一个顺序 | 把 start/stop/dispose 与"失败后如何恢复""重复 start 是否幂等"写清，补顺序断言测试 |
| S5 | **kit / host 注入面**（`ExtensionHostInstallContext`：registerKit / resources / capabilities / bindings） | 这是插件与宿主之间唯一的注入面，是第三方插件能"要什么"的清单 | 为 register/announce/bind/withdraw 的生命周期补契约测试；`bindings.ts` 已有测试可扩展 |
| S6 | **事件契约单一来源**（`shared/eventa` + plugin-sdk 协议事件名） | 已经出现两处重复：`shared/eventa/plugin/capabilities.ts:42-44` 的 TODO 和 `shared/eventa/index.ts:204-247` 手抄 `PluginManifestSummary` 等 | 清理重复 re-export；消除手抄类型，改为从 owning 包导入 |

### 应延后（有真实压力前不做）

| # | 抽象 | 为什么延后 | 什么时候再做 |
|---|---|---|---|
| D1 | **第三方插件进程隔离/沙箱**（utilityProcess / node worker transport / 签名校验 / 权限审批 UI） | 没有真实第三方插件之前，做隔离 = 猜威胁模型；而且它必须建立在 S1/S2 之上，顺序错了会返工 | 出现第一个**不可信**插件源，或要开放"用户安装任意目录插件"时。届时先做 node runtime 的 `node-worker` 传输（`runtimes/node/index.ts` 已留 stub） |
| D2 | **通用窗口注册表 / WindowManager 抽象** | 现状每窗口手动 DI 反而可读、可测、可回滚；过早统一会引入抽象泄漏（widgets 窗口有 iframe 协调、beat-sync 有音频、desktop-overlay 有输入隔离，差异远大于共性） | 当窗口数量/生命周期差异开始造成真实重复（如 3+ 个窗口都需要"按需创建 + 回收 + 状态持久化"的同一套逻辑）时 |
| D3 | **统一后台任务框架**（调度/重试/队列） | 现在只有两类后台且各自干净；统一是 YAGNI，反而会掩盖"进程内服务"与"子进程侧车"在故障域上的本质区别 | 当插件需要声明"常驻后台工作"且出现 3+ 个异构后台任务时，先只抽 S4 的公共生命周期，再做调度 |
| D4 | **第三方 provider 注入 providers store** | 3000 行硬编码注册表；但第三方插件更可能走 MCP/工具而不是自带 provider。现在做会造出两套注册机制 | 先确认插件确实要自带 provider（而不是暴露 MCP 工具），再决定是改造 `providers.ts` 为可注册集合，还是让插件走 MCP 桥 |
| D5 | **分发市场 / 插件自动更新 / 签名基础设施** | 依赖 S1/S2/D1 全部就位；顺序最后 | 在 D1 落地并验证后 |

**关键判断**：S2 的"权限语言"现在锁，但"权限**执行**（审批 UI、签名、强制最小权限）"延后。语言的稳定性收益是永久的，执行机制的错误成本很高且依赖威胁模型，二者不能绑在一起做。

---

## 三、方案对比

### 方案 A：维持现状（只修明显债务，不锁任何新边界）

**质量属性权衡**

- 交付速度：最高；安全：对第一方够用、对第三方是任意代码执行级别风险；演进性：契约继续隐式存在，靠人记忆；测试性：不变。
- 优点：不引入任何迁移成本。
- 成本：几乎为零（只清两处重复类型）。
- 风险：一旦有人开始以"第三方插件"名义分发，主进程全权 + 无签名 + 无审批 = 等价于给用户装一个任意代码执行入口。窗口/后台轴风险低。
- 回滚：无。
- **不改变的后果**：窗口继续手动加（成本线性但不坏）；后台两套并存（无立即风险）；插件轴在"第三方"这层是**不可发布**的默认值——权限系统成了摆设（声明即授予），未来补隔离时要先把现有插件重新审计一遍。

### 方案 B：渐进式锁定边界（推荐）

先做 S1–S6 的契约冻结与契约测试，把 D1–D5 按触发条件延后；`permissionResolver` 只先"接线但保持现状语义"（默认授予已声明权限），使钩子成为可测试的真实边界。

**质量属性权衡**

- 安全：不立即改善运行时隔离，但把"声明了权限"和"未来谁能批准"的语言基础打好，消除"以后补隔离要重审一切"的隐形成本。
- 演进性：契约显式化后，加窗口/加 kit/加后台都有可验证的落点。
- 交付速度：只多出契约测试和文档成本，几乎不拖主线。
- 测试性：显著提高——契约测试集中在纯类型/纯校验层，不碰 Electron 运行时。
- 复杂度：基本不增（不引入新框架）。

**成本**：中低。主要是 1) 清理重复契约、2) 补一批 property/契约测试、3) 写 1 份 ADR + 1 份边界文档。

**风险**：低。所有改动行为不变或只做 re-export，可逐步合入。

**回滚路径**：每步独立可回滚——契约测试可删、re-export 可还原、resolver 接线可以再拔掉（回到默认授予）。

**不改变的后果（若也不选 B）**：契约继续靠人记忆，下一次加窗口/kit 时重复发明或漂移；权限钩子继续是死代码，未来做隔离时"先接线、再约束"的成本一次性转移到那时。

### 方案 C：一步到位（沙箱 + 窗口注册表 + 后台框架 + 市场）

**质量属性权衡**

- 安全：最高（如果做对）；演进性：有框架但可能过度设计；交付速度：最低；测试性：最高但测试面最大；复杂度：显著上升。
- 优点：一次性解决未来所有问题。

**成本**：高。至少四个大件：utilityProcess/worker 传输、通用窗口生命周期框架、后台调度框架、签名与分发。每个都是数周到数月级。

**风险**：最高。没有真实第三方插件来校准威胁模型，沙箱隔离边界（哪些 Electron API 可暴露、哪些 Node 能力可给）几乎必然猜错；窗口注册表会撞上 widgets/beat-sync/desktop-overlay 的真实差异；后台框架会掩盖进程内/进程外故障域差异。

**回滚路径**：难。框架一旦被多个窗口/服务采纳入侵，回滚等于重写；沙箱一旦有插件依赖，降级会破坏已发布插件。

**不改变的后果**：不适用——这是"过度改变"的后果。

### 汇总表

| 维度 | A 维持现状 | B 渐进锁定（推荐） | C 一步到位 |
|---|---|---|---|
| 交付速度 | ★★★★★ | ★★★★☆ | ★★☆☆☆ |
| 安全性 | ★★☆☆☆（对第三方不足） | ★★★☆☆（先语言后执行） | ★★★★★（若做对） |
| 演进性 | ★★☆☆☆ | ★★★★☆ | ★★★★★（可能过度） |
| 复杂度 | 不变 | 基本不变 | 显著上升 |
| 测试性 | 不变 | 明显提升 | 提升但测试面大 |
| 成本 | 近乎零 | 中低 | 高 |
| 风险 | 插件轴不可发布 | 低、可增量 | 高、难校准 |
| 回滚 | 无 | 每步独立可回滚 | 难 |

---

## 四、可验证的渐进迁移路线（对应方案 B）

每阶段都**只动契约/测试/文档，不改生产行为**（M1 的 resolver 接线保持现状语义），因此每一步都有明确的验证门和回滚点。

### M0 — 契约盘点与冻结（零行为风险）

**目标**：把 S1/S2/S3/S4 的现状写成文档与测试，先消除重复。

- 清理 `shared/eventa/index.ts:204-247` 与 `plugin/host.ts` 重复的 `PluginManifestSummary / PluginRegistrySnapshot / PluginCapabilityState`，统一从 owning 模块 re-export。
- 为 `extensionManifestV1Schema` 写契约测试：合法清单、缺 entrypoint、重复 id、非法 kind/apiVersion 的拒绝行为（`registry.ts` 已有实现，只补测试）。
- 为 `PermissionService.intersectGrant` 写 property 测试：请求 ⊓ 授予永远不宽于两者；通配符与 action 交集用例（`permissions.ts` 注释里已有完整示例，可直接转成断言）。

**验证门**：`pnpm -F @proj-airi/plugin-sdk exec vitest run`、`pnpm -F @proj-airi/stage-tamagotchi typecheck`、`pnpm lint` 全绿。
**回滚**：删除新增测试/re-export 即可，无行为变化。

### M1 — 把 `permissionResolver` 接成真实边界（行为不变）

**目标**：让"权限钩子"从死代码变成可测试边界，但**默认授予已声明权限**（维持现状语义），不改任何运行时隔离。

- 在 `setupExtensionHostServiceInternal` 构造 host 时传入一个 resolver，其语义 = `manifest.permissions`（等价于今天的 fallback），并加注释说明"这是未来第三方插件审批/签名校验的挂点"。
- 为 resolver 写测试：resolver 收紧某 key 时，kit 调用被 `PermissionDeniedError` 拒绝（`core.test.ts:312-439` 已有同型测试可参照）。

**验证门**：plugin-sdk vitest + 全量 typecheck/lint；手动 smoke：现有内置插件（devtools 示例扩展）加载/启用/工具调用不变。
**回滚**：删掉 resolver 参数即可回到裸构造。

### M2 — 窗口契约标准化

**目标**：把"窗口 = route + eventa 契约命名空间"从约定变成可验证的契约。

- 把 `createRequestWindowEventa(namespace)`（`shared/eventa/index.ts:97-105`）泛化为一个文档化的 `defineWindowContract(namespace)` 模板；新窗口强制走它，旧窗口渐进迁移。
- 为每个窗口补一个"契约清单"测试：声明 route、preload、所需 base services（window/screen/app/powerMonitor/systemPreferences/i18n/server-channel）和专属 rpc 事件名。
- 把三处 `setMaxListeners` TODO 转成真实 work item（修 eventa 的 window-namespaced 分发，或确认其已支持后移除补丁）。

**验证门**：契约测试 + `apps/stage-tamagotchi` vitest；typecheck/lint。
**回滚**：按窗口逐个迁移，未迁移窗口行为不变。

### M3 — 后台生命周期契约固化

**目标**：把 server-channel / http-server / mcp 已一致的 start/stop/dispose 顺序写清楚并锁住。

- 记录每个服务的 onStart/onStop 顺序、重复 start 是否幂等、stop 时 in-flight 请求如何处理（server-channel 已有 mutex，可作为范本）。
- 为生命周期顺序补测试（已有 `http-server/server-manager` 的顺序测试可扩展）。

**验证门**：相关包 vitest + typecheck/lint。
**回滚**：纯文档 + 测试，无行为变化。

### M4 — 按需引入隔离（只有真实第三方插件出现时）

**触发条件**：出现第一个不可信插件源，或开放"用户安装任意目录插件"。

- 先实现 `node` runtime 的 `node-worker` 传输（`runtimes/node/index.ts:30-31` 已有 stub），把插件**逻辑**移出主进程，UI 继续走现有 iframe + cookie 会话。
- 再在 `permissionResolver` 之上加审批/签名，而不是另起炉灶。
- 分发/市场（D5）最后做。

**验证门**：worker 传输的单测（`runtimes/node/loaders` 与 `channels` 已有测试基架）+ 一个不可信插件的端到端 smoke（越权调用被拒、主进程无插件符号）。

---

## 五、一句话总结

AIRI 现在缺的不是"插件/窗口/后台"的新框架，而是**把已经存在的三层契约（插件身份与权限语言、窗口身份与事件命名、后台生命周期）显式锁死，并明确"先锁语言、后做监狱"的顺序**。任何在真实第三方插件出现之前就上沙箱/注册表/调度框架的动作，都是在为尚未出现的威胁模型和尚未出现的重复付出高成本；而任何继续让权限系统"声明即授予、同进程全权"地面对"第三方"这个词汇，都是不可发布的安全默认。
