证据已足够。下面是完整的架构评审。

---

# 桌面端「第三方插件 / 多窗口 / 独立后台」的边界评审

## 一句话结论

这个仓库其实已经长出了三条高质量的**协议级边界**——插件 SDK（manifest + kit + permission）、Eventa 的 IPC 契约、server-channel 的 WebSocket 事件协议。它们就是三个未来能力的稳定锚点，应该现在用「版本化 + 契约测试 + 文档」钉住；而**进程隔离**（插件沙箱、独立后台进程）、**通用窗口框架**、**远程插件传输**这类进程级/框架级抽象应该延后，等出现真实的第三方分发、崩溃隔离或 headless 需求后，再用最小实验验证，而不是预先造框架。

---

## 1. 范围与置信度

- **仓库分类**：pnpm monorepo + Electron 桌面应用（`stage-tamagotchi`），同时含 web/mobile 与共享包。**事实**：`package.json` 声明 `electron@41`、`electron-vite`、`electron-builder`；`crates/` 是遗留 Tauri，当前桌面是 Electron（AGENTS.md 亦如此说明）。置信度**高**。
- **技能适配器说明**：本次加载的是 Desktop/Tauri 适配器，但其跨进程边界（IPC 版本化、生命周期、权限）适用；我**没有**套用 Tauri 专属假设（tauri.conf、capability 系统），仓库里不存在这些。
- **决策范围**：为三个能力判断「哪些边界现在稳定、哪些抽象延后」，不产出代码改动。

## 2. 观察到的事实

标记约定：**事实**=直接看到；**推断**=基于事实的推理；**未知**=尚未确认。

| 声明 | 证据 | 类型 | 置信度 | 对决策的影响 |
| --- | --- | --- | --- | --- |
| 组合根用 injeca DI 手动接线 ~15 个窗口/服务，settings 依赖 12 项、main 依赖 13 项 | `apps/stage-tamagotchi/src/main/index.ts:154-270` | 事实 | 高 | 新增窗口的接线是线性手写，无注册表 |
| Eventa 没有窗口命名空间上下文，全仓库用 `ipcMain.setMaxListeners(100/0)` 兜底 | `index.ts:55-58`，13+ 文件同款 TODO（`windows/*/rpc/index.electron.ts` 等） | 事实 | 高 | 这是「更多窗口」的硬天花板，也是明确欠账 |
| 插件在 Electron 主进程内以 `await import(entrypoint)` 加载，**无进程隔离** | `packages/plugin-sdk/src/plugin-host/runtimes/node/loaders/fs.ts:72-76`；全 `apps/stage-tamagotchi/src` 无 `worker_threads`/`utilityProcess`/`Worker(` 命中 | 事实+推断 | 高 | 「第三方=不可信代码」时这是信任边界缺口 |
| 插件 SDK 已是完整深度模块：manifest v1、`defineExtension({setup})`、kit/capability/permission/session/module/binding | `packages/plugin-sdk/src/plugin-host/core.ts:205-858`、`shared/types.ts:233-253` | 事实 | 高 | 这是现成的稳定锚点，不需要重造 |
| manifest 已是 `apiVersion: 'v1'`，权限含 apis/resources/capabilities/processors/pipelines 五类 | `shared/types.ts:264-300`；示例 `extension.airi.json` | 事实 | 高 | 版本化升级路径（v2）已预留 |
| `ExtensionHost` 支持 `permissionResolver` 钩子，但 Electron 宿主未用它做用户确认 | `shared/types.ts:365-372`；`apps/.../plugins/host/index.ts` 构造 `new ExtensionHost({ runtime: 'electron' })` 无 resolver | 事实 | 高 | 信任决策点已存在但未接入 |
| kit 通过直接对象句柄注入宿主能力（`widgetsManager`、`ExtensionHost` 实例） | `apps/.../plugins/kits/index.ts:18-116` | 事实 | 高 | 这正是「进程隔离」为何昂贵：隔离要先切这套句柄为消息协议 |
| 远程插件传输是空壳 | `packages/plugin-sdk/src/plugin/local.ts`、`remote.ts` 均为 `export {}` | 事实 | 高 | 远程插件传输尚未实现 |
| server-channel 的 WS 协议已支持远程扩展模块（announce/authenticate/module:announce） | `packages/server-runtime/src/index.ts:664-775` | 事实 | 高 | 「独立后台」的协议种子已存在 |
| server-runtime 里 legacy 索引路由与 identity 路由并存，有 REVIEW 注释；`/ws` 字面量三处重复 | `packages/server-runtime/src/index.ts:323-341`、`1051-1054`；`apps/.../channel-server/index.ts:103-106` | 事实 | 高 | 这是后台协议边界最不稳处，外部服务已依赖它 |
| server-runtime 有独立 CLI 入口 | `packages/server-runtime/src/bin/run.ts` | 事实 | 高 | 可用 headless smoke 验证「daemon 路径」而无需先提交到 daemon 拆分 |
| 聊天窗口 `sandbox: false` | `apps/stage-tamagotchi/src/main/windows/chat/index.ts:32` | 事实 | 高 | 渲染第三方内容时的安全面 |
| 仓库没有 ADR 目录；`docs/solutions` 仅 1 篇 | Glob 无 `docs/**/adr*/**` 命中 | 事实 | 高 | 关键边界决策目前没有书面记录，未来评审会重开 |

## 3. 当前摩擦

把症状和根因分开：

- **多窗口**：加一个窗口 = 新 `windows/<name>/index.ts` + 手写 RPC 注册 + 手写 DI 依赖。这不是大问题（每个窗口差异确实大），真正的耦合是**跨窗口协调与监听器膨胀**：所有窗口的 Eventa 上下文都挂在同一个 `ipcMain` 上，靠 `setMaxListeners(0)` 压掉告警，事件分派没有窗口命名空间，也没有统一的所有者/teardown 顺序。根因不是「缺框架」，而是「缺命名空间 + 缺生命周期注册表」。
- **插件**：SDK 本身质量很高，但当前定位偏「第一方」——kit 直接把 `widgetsManager`/`ExtensionHost` 句柄交给插件，且插件在主进程内运行。第三方插件要成立，缺的不是 SDK，而是：①把契约当**版本化公共 API** 对待（契约测试 + 文档 + 第三方 fixture）；②明确的信任策略（权限解析 + 未受信提示）；③隔离。前两者便宜、现在就能做；隔离昂贵、该延后。
- **独立后台**：WS 协议已经有身份化扩展模块路由，但和 legacy 索引路由并存，且有 `REVIEW`/`TODO` 表明处于迁移中途。外部 `services/*`（discord/telegram/minecraft 等）已经依赖这个协议，所以它必须比现在更稳，否则改动会反向破坏这些消费者。

## 4. 质量属性优先级（按重要性排序）

| 优先级 | 属性 | 目标/预算 | 当前证据 | 哪个方案改善 | 可能回退的属性 | 捕捉回退的验证 |
| --- | --- | --- | --- | --- | --- | --- |
| 1 | **进程/协议边界稳定性** | IPC 与 WS 契约可版本化、错误可映射、事件顺序可断言 | manifest 已有 v1；WS 信封存在但 legacy 路由并存 | 方案 B | 成本（需迁移） | 契约测试：错误形状、announce→announced、auth 失败映射 |
| 2 | **安全/信任边界** | 第三方代码不能无授权触达宿主能力 | `sandbox: false`；插件 in-process；权限模型已存在 | 方案 B（权限策略）→ 方案 C（隔离） | 性能/开发速度 | 未授权 kit 调用被拒；权限 resolver 流程测试 |
| 3 | **可维护性/局部性** | 加窗口/插件/后台不改组合根 | 组合根已 12-13 项依赖；13+ 文件 setMaxListeners | 方案 B | 无 | 加一个 fixture 窗口，diff 只落在新模块+注册 |
| 4 | **可运维性** | 单插件/单后台可诊断、可重启，不拖垮宿主 | 无隔离；日志用 `useLogg` 已较规范 | 方案 C | 复杂度 | 故障注入：一个坏插件不阻止其它插件加载（现有 `loadEnabledExtensions` 已 try/catch 单点失败，见 `host/index.ts:420-425`） |
| 5 | **成本/可逆性** | 每个抽象在出现第二个真实消费者前不预先建造 | `local.ts`/`remote.ts` 空壳即「过早抽象」信号 | 方案 B | 无 | 每次抽象前问：第二个真实用例是谁 |

## 5. 方案对比

### 方案 A：维持现状 + 只补契约测试

- **边界与所有权**：保持现有 seams 不动；只给插件 manifest/kit 与 WS 信封补一致性测试，不改变运行时拓扑。
- **能做什么**：提前发现契约漂移；不改生产行为。
- **成本/风险**：最低；但 `setMaxListeners` 天花板、legacy 路由、插件 in-process 三个债务原样保留。
- **回滚**：几乎无（只加测试）。
- **不改变的后果**：每加一个窗口继续往单 `ipcMain` 上堆监听器并靠 `setMaxListeners(0)` 硬压；第三方插件一旦出现，in-process 模型立刻变成安全负债；后台协议继续带着 legacy 路由，未来改动会破坏已接入的 bot 服务。
- **此方案被证明错误的证据**：当出现第一个真实第三方插件、或窗口数增长触发监听器/teardown 事故、或有外部服务因协议改动被破坏时，方案 A 不再成立。

### 方案 B：稳定三条「协议级」边界，延后「进程级」抽象（推荐）

三条边界现在就钉住，其余明确延后：

- **应稳定**：
  1. **插件公共契约**：`extension.airi.json` v1 + `defineExtension` + kit/capability/permission + `plugin-protocol` 类型。做法：版本化、契约测试、作者文档、第三方 fixture 插件（从 userData 之外的 fixture 目录加载）。
  2. **Eventa 窗口命名空间 + IPC 契约**（`src/shared/eventa/**`）：做窗口命名空间上下文重构，删掉全部 `setMaxListeners` 兜底。这是插件与多窗口共用的横向 seam。
  3. **server-channel WS 事件信封 + 注册协议**：身份化路由收尾、信封版本化、去重 `/ws` 字面量。
  4. **窗口生命周期注册表**：在现有 `createReusableWindow`（`libs/electron/window-manager/reusable.ts:5-37`）与 `createReferencedWindowManager`（`windows/shared/referenced-window.ts:31-100`）之上加 open/get/close + 所有者 + teardown 顺序，**不**引入声明式路由 DSL。
  5. **信任策略（便宜的那半）**：接入 `permissionResolver` 做用户确认/未受信提示；把 manifest 权限当作信任上限。

- **应延后**：
  1. 插件进程隔离（sandbox/`utilityProcess`/`worker_threads`）——等真实第三方分发 + 一次可测的崩溃事件。
  2. 远程插件 SDK 传输（实现 `local.ts`/`remote.ts`）——协议侧已备好，等出现远程插件消费者。
  3. 通用窗口描述符框架（声明式 route/preload/权限）——窗口差异大，现在框架化会过度抽象。
  4. 独立后台 daemon 拆分——用 `server-runtime/bin/run.ts` 做 headless 实验验证，不提前提交拆分。
  5. 签名/市场/来源证明——等分发渠道存在再做机制。

- **成本/风险**：中低。步骤 1-4 是契约/测试/局部重构，行为保持；步骤 5 涉及安全 UX，需产品确认。
- **回滚**：每步可独立回滚；manifest 已是 v1，未来破坏性变更走 v2 不破坏 v1。
- **运维/测试后果**：契约测试先行，回归面小；窗口命名空间重构是唯一涉及面较广的改动。
- **此方案被证明错误的证据**：若评估发现插件崩溃/阻塞主进程已是现实问题（而不是假设），或 headless 后台需求已明确，则应提前推进方案 C 的对应部分。

### 方案 C：全面进程化/框架化

- **边界与所有权**：①插件跑在独立进程/utilityProcess，kit 从直接句柄改为消息协议；②声明式窗口框架（描述符驱动 route/preload/权限/生命周期）；③把 server-channel 拆成独立常驻 daemon。
- **能做什么**：真正的崩溃隔离、安全隔离、窗口规模化、UI 关闭后后台存活。
- **假设**：第三方插件量大且不可信、窗口类型趋于同质、存在 headless/多 app 场景。当前证据都不支持这些假设——kit 直接句柄、窗口彼此差异大、无 headless 需求记录。
- **成本/风险**：高。要重写 kit 注入面（`kits/index.ts`）、序列化所有跨进程调用、处理插件生命周期/调试/升级，风险集中在打包与更新流程。
- **回滚**：难——进程拓扑一变，回滚等于放弃已发布插件生态。
- **此方案被证明正确的证据**：第三方插件市场规模信号、或主进程因插件崩溃的可复现报告、或明确的「UI 关闭仍要后台运行」产品需求。

## 6. 建议

**选方案 B**。理由：三条协议边界已经存在且质量高，现在钉住它们的成本低、杠杆大（同时服务插件/窗口/后台三个方向）；而进程级隔离和框架化目前是「假设性变化点」，本仓库自己的规则也要求「第二个真实变体出现前不建泛化原生抽象」（skill 的 desktop 陷阱条目与 AGENTS 的深度模块原则一致）。方案 A 会让债务继续涨；方案 C 把昂贵的、可能永远不需要的隔离提前买单。

**拒绝方案 A**：`setMaxListeners` 已扩散到 13+ 文件，是明确的技术债信号，不能只加测试就停。
**拒绝方案 C（现在）**：没有证据支撑「第三方不可信 + 窗口同质 + headless」三个前提同时成立；`local.ts`/`remote.ts` 空壳恰恰说明过早抽象只会留空壳。

## 7. 迁移与验证（渐进、可回滚）

**步骤 0 —— 记录决策**：用 `docs/solutions`/新建 ADR 记录「稳定 vs 延后」的边界清单与再访条件（见第 8 节）。成本 1 篇文档，避免未来评审重开。

**步骤 1 —— 插件契约一致性测试（最便宜、信号最高）**：在 `packages/plugin-sdk` 增加一个「第三方风格」fixture（manifest + 越权调用 + 生命周期副作用），走 `ExtensionHost.start` 断言：session 就绪、无权限 kit 调用被拒、`unload` 清理副作用。现有 `core.test.ts`/`permissions.test.ts`/`kit-api-bindings.test.ts` 已覆盖大半，补齐即成。
- 完成标准：CI 绿 + 一份「第三方作者视角」的 manifest/权限文档。

**步骤 2 —— Eventa 窗口命名空间（移除 setMaxListeners）**：这是唯一面较广的改动，但行为等价。验证：新增测试「开 N 个 referenced 窗口，断言无跨窗口 handler 泄漏、监听器不线性增长」；删除/更新现有断言 `setMaxListeners(0)` 的测试（`desktop-overlay/rpc/index.electron.test.ts:71`）。
- 完成标准：全仓 `setMaxListeners` 兜底归零。

**步骤 3 —— 窗口生命周期注册表**：在 `windows/shared` 上提取 open/get/close + 所有者 + teardown 顺序，保留组合根 DI 接线，只让窗口有名字和生命周期。验证：`window-all-closed`/`before-quit` 仍正确 teardown；一个「关闭 referenced 窗口再重开」的测试。
- 完成标准：新增一个 fixture 窗口时，diff 只落在新模块 + 注册，不触碰 `index.ts` 之外的既有窗口。

**步骤 4 —— 后台协议收尾**：身份化路由收尾、信封版本化、去重 `/ws`。验证：现有 `consumers.test.ts`/`responses.test.ts` + 一个 env-guarded 的 `bin/run.ts` headless smoke（`extension:announce` → `extension:announced` + registry sync、auth 失败错误映射）。
- 完成标准：`server-runtime` 无 legacy 索引路由 REVIEW 注释残留。

**步骤 5 —— 信任策略（不建隔离）**：接入 `permissionResolver` 做权限确认与未受信安装提示，把 manifest 权限当信任上限。验证：一个「请求未声明权限被拒 + 提示流程」的测试。
- 完成标准：第三方插件首次安装有可观察的信任决策点。

**步骤 6 —— 延后门（deferred gate）**：仅在①出现真实第三方分发渠道、且②有可复现的主进程崩溃/阻塞事件后，做 `node:worker_threads` 或 Electron utilityProcess 的隔离 spike（本仓库测试规范本就建议用 `worker_threads` 做隔离实验）；远程插件传输与 daemon 拆分也只在出现对应消费者后再动。

**回滚路径**：步骤 0-5 均为契约/测试/局部重构，行为保持，可逐步回退；manifest 已是 `apiVersion: 'v1'`，破坏性变更走 v2 保留 v1 兼容。步骤 6 的 spike 可整体丢弃。

## 8. 待决问题（答案会改变建议）

1. **未知**：是否有第三方插件市场/分发的产品路线图？（仓库无 ADR/roadmap 证据；最便宜的求证方式：问产品负责人。）若「是且近期」，步骤 5-6 提前；若「否」，方案 B 完全成立。
2. **未知**：主进程被坏插件拖垮是否已有真实报告，还是只是理论风险？一个 10 分钟的 worker_threads spike 即可量化。
3. **未知**：`@moeru/eventa` 当前版本是否已支持窗口命名空间上下文（多份 TODO 说「once we refactored eventa to support…」）？这决定步骤 2 是纯调用方重构还是需要先改 eventa 依赖，需查依赖源码/版本确认。
4. **未知**：headless/多 app 后台是否在近期规划内？若是，daemon 拆分从步骤 6 提前到步骤 4 之后；否则保持延后。

---

综合来看：**钉住协议边界，延后进程边界**。仓库已经替你把最难的设计（插件权限模型、WS 事件协议、DI 组合根）做出来了，现在缺的不是更多抽象，而是把这些边界当成真正的公共契约来版本化、测试和记录。

[EVAL:evolve-software-architecture-loaded]
