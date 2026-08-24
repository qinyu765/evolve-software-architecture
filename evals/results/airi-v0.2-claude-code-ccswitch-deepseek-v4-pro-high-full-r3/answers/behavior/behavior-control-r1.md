勘察完成。以下是基于当前仓库真实代码（`apps/stage-tamagotchi` + `packages/plugin-sdk*` + `packages/plugin-protocol`）的架构评估。全程只读，未修改任何文件。

## 结论先行

这个仓库的现状比"未来要加插件/多窗口/后台"这句话所暗示的要**成熟得多**：第三方插件宿主、多窗口、后台服务三件事都已经有真实雏形，而且插件层的协议设计（`plugin-sdk`/`plugin-protocol`）质量相当高。因此**不建议重新设计，也不建议完全维持现状**，而应做"契约先行"：把已经存在、且第三方将来会依赖的少数边界固化下来，同时明确推迟"进程外宿主 / 远程协议 / 独立后台守护进程"这些尚未被验证的部分。

最该优先稳定的一件事是 **Eventa 的窗口级命名空间上下文**——它是"更多窗口"和"插件窗口"的共同地基，目前靠 12 处 `ipcMain.setMaxListeners(0/100)` 硬扛，越晚修，迁移成本越大。

---

## 一、现状勘察（基于代码证据）

**插件宿主已经相当完整**，不是 demo 级：

- 完整的扩展宿主 `ExtensionHost`，含会话、模块、绑定生命周期（`announced/active/degraded/withdrawn`）、kit、capability、resource、双层权限（扩展级 ceiling ∩ 模块级 grant）：`packages/plugin-sdk/src/plugin-host/core.ts:205-328`
- Manifest V1 契约（`apiVersion:'v1'`、`id`、`permissions`、`entrypoints.{default,electron,node,web}`）：`packages/plugin-sdk/src/plugin-host/shared/types.ts:233-253`
- 三个已注册的内置 kit：`kit.widget`、`kit.gamelet`、`kit.tool`：`apps/stage-tamagotchi/src/main/services/airi/plugins/kits/index.ts:95-116`
- 插件持久化（`extensions-v1.json`）、静态资源服务、自动重载：`plugins/host/index.ts:224-528`

**多窗口已经存在约 13 个窗口管理器**（main/widgets/chat/settings/spotlight/caption/about/notice/onboarding/devtools/dashboard/inlay/desktop-overlay/beat-sync），有两个可复用原语 `createReusableWindow`（`libs/electron/window-manager/reusable.ts:5-37`）和 `createReferencedWindowManager`（`windows/shared/referenced-window.ts:31-100`），每个窗口共享一套基础服务 `setupBaseWindowElectronInvokes`（`windows/shared/window.ts:134-149`）。

**后台能力有雏形**：`channel-server`（WebSocket/TLS/配对，挂在 `injeca` lifecycle 上，`services/airi/channel-server/index.ts:357-449`）、`airi-http-server`（`ServerManager` 生命周期契约 + 有序启停 + 互斥，`services/airi/http-server/server-manager/index.ts:19-51`）、`godot-stage`、`mcp-servers`、`tray`。

但存在几处**真实的结构性债**，直接决定哪些边界该现在稳定：

1. **Eventa 窗口命名空间缺失**。主进程用 `ipcMain.setMaxListeners(100)`（`src/main/index.ts:55-58`），其余 11 处 `setMaxListeners(0)` 都是同一句 TODO 注释的复制粘贴。每加一个窗口，这套 workaround 就再复制一遍。
2. **插件 SDK 未发布**。`packages/plugin-sdk/package.json:6` 是 `"private": true`——第三方目前根本无法 `npm install` 它。这直接堵死"第三方插件"。
3. **kit 版本兼容只声明、不执行**。`KitUnavailableReason` 有 `incompatible-version`（`plugin-sdk/src/kit/index.ts:44`），但 `resolveKitApi` 只检查 `missing-kit` 和 `permission-denied`（`plugin-sdk/src/plugin-host/core.ts:405-433`）。
4. **权限默认全放行**。`setupExtensionHost` 没传 `permissionResolver`，于是 `resolvedGrant = options.manifest.permissions`（`core.ts:249-255`）——插件声明什么就得到什么，没有用户同意环节。
5. **进程生命周期有两条线 + 一处手工清理**：bootkit 的 `emitAppBeforeQuit()`、`injeca.stop()`、以及插件宿主自己注册的 `app.once('before-quit', () => hostService.dispose())`（`plugins/index.ts:139-143`）混在一起，退出顺序脆弱，正是"独立后台"最怕的地方。
6. **渲染侧 IPC 类型手工复制**：`src/shared/eventa/plugin/capabilities.ts:42-45` 有 TODO 承认这些类型应从 SDK 再导出，避免漂移。
7. **窗口 bounds 持久化不统一**：main 用 `app/config.json` 的 `windows` 数组（`windows/main/index.ts:39-48`），widgets 用 `windows-widgets/config.json` 的单个 `bounds`（`windows/widgets/index.ts:190-208`），未来插件窗口会继续分叉。

---

## 二、应稳定的边界（现在固化，改动代价低）

| 边界 | 现状 | 为什么现在稳定 | 稳定到什么程度 |
|---|---|---|---|
| **Eventa 窗口命名空间上下文** | 靠 `setMaxListeners` 硬扛，12 处 TODO | 它是"更多窗口 + 插件窗口"的共同地基；每多一个窗口就多复制一次 workaround | `createContext` 按 `webContents.id` 隔离 handler/事件，`setMaxListeners` 全部消失 |
| **扩展 manifest 契约 v1** | 已成形，`extensionManifestV1Schema` | 第三方插件安装即依赖此格式；改了就要做迁移 | 冻结字段与校验，新增字段只允许可选，破坏性变更走 `apiVersion: 'v2'` |
| **kit 契约（`KitRef`/`KitDescriptor` + 版本）** | 结构完整，版本检查缺失 | 这是插件作者的 API 面，产品差异所在 | 落实 `kit.version` 的 semver 兼容检查（`incompatible-version` 分支真正生效） |
| **权限声明/授权模型** | 模型完整，默认全放行 | 第三方插件的信任边界；现在不建同意流程，以后补等于改契约 | 接入 `permissionResolver`，默认拒绝未授权项，`PermissionDeniedError` 成为稳定行为 |
| **后台服务生命周期契约（`ServerManager`）** | `key/start/stop` + 有序启停已存在 | "独立后台"就是把更多服务塞进这一个有序生命周期 | 统一所有后台能力（channel-server、插件静态资源、godot、mcp、未来插件服务）的启停顺序 |
| **`plugin-sdk` 包导出边界** | `exports` 已定义但 `private:true` | 第三方要 import 的正是这些导出 | 发布或在工作区外冻结 `exports`；`plugin-host` 的 node/web 双入口保持稳定 |

## 三、应延后的抽象（现在不做，等证据）

| 抽象 | 现状 | 为什么延后 |
|---|---|---|
| **进程外插件执行 / 远程宿主** | `node-worker`/`web-worker`/`websocket` 传输是抛出"未实现"的桩（`runtimes/web/index.ts:23-38`、`runtimes/node/index.ts:24-39`） | 在桩上固化协议会锁死未经验证的形态；先让进程内宿主跑满真实场景 |
| **`plugin-protocol` 的完整路由/投递语义** | `delivery` 模式、`RouteTargetExpression`、consumer-group 等已定义但未被桌面侧使用 | 与远程宿主同源，属于"超前设计"，等有真实消费者再定型 |
| **`ExposePolicy`（`local-only/remote-observable/remote-callable`）** | kit 上声明了，核心未执行 | 语义与远程传输绑定，现在固化是空承诺 |
| **通用插件 UI 扩展点（页面/工具栏/`ui.contributions`）** | `ModuleContribution.ui` 是 `Record<string, unknown>` | 现在只有 widget/gamelet 两个 kit 有真实消费方，UI 面应等第二个场景出现再定形 |
| **沙箱/进程隔离** | 全部 `sandbox:false`，插件进主进程 node runtime | 是大改，威胁模型明确前不动；但 manifest 契约不要写死"同进程"假设 |
| **插件分发/安装/市场** | 只扫 `userData/extensions/v1` 磁盘目录 | 属于外围能力，可后置；前提是 manifest `id`/`version`/`permissions` 已稳定 |
| **"独立后台守护进程/无窗口运行"** | 只有 macOS 的 `window-all-closed` 不退出 + tray | 先把生命周期顺序理清，让它"能加"即可，不必现在建守护进程 |

---

## 四、三个方案比较

### 方案 A：维持现状 + 局部补强

保持进程内宿主、`index.ts` 手工装配窗口、Eventa 现状；只修最高风险项（生命周期顺序、权限默认值）。

- **质量属性**：改动最小、风险最低、交付最快；但兼容性/可演化性不提升，每加一个窗口继续复制 workaround，第三方仍无法安装 SDK。
- **成本**：低。**风险**：低。**回滚**：逐 commit 回退即可。
- **不改变的后果**：多窗口的数量增长与 `setMaxListeners` 复制、Eventa 冲突风险线性同步增长；第三方插件因 SDK 未发布而无法落地。

### 方案 B：契约先行（推荐主路径）

把上述"应稳定的边界"固化为受测契约：发布/冻结 `plugin-sdk`、落实 kit 版本与权限、统一窗口管理器契约、统一后台生命周期、渲染侧类型改从 SDK 再导出。

- **质量属性**：可演化性、兼容性、安全性显著提升；可测试性靠契约测试保障；性能/资源无变化（仍是进程内）。
- **成本**：中等（一次性重构，约覆盖 12 处窗口装配 + 一处 SDK 发布 + 一处权限接线）。**风险**：中低——权限默认拒绝是唯一的行为变更，需 flag 门控。
- **回滚**：每步独立、行为基本不变（除权限），可单步回退；SDK 发布采用 additive 导出，旧消费者不破坏。
- **不改变的后果（若只做到 A 不做 B）**：第三方插件无法获得稳定的安装/权限/版本保证，窗口扩展继续依赖手工装配。

### 方案 C：进程外宿主 + 独立后台服务（大重构）

把插件迁到 utilityProcess/子进程，补全 `websocket/node-worker` 传输，跑通 `plugin-protocol` 远程语义，做无窗口后台。

- **质量属性**：隔离性/崩溃恢复/后台可用性上限最高；但今天传输全是桩，等于在未验证的协议上盖楼。
- **成本**：高（绿field + 协议定型）。**风险**：高——锁死错误的远程协议形态、引入进程间一致性问题、破坏现有进程内 kit 语义。
- **回滚**：难，一旦第三方插件按远程协议编写，回退即破坏兼容。
- **不改变的后果（若现在强行做 C）**：把未经真实负载验证的投递/路由/心跳语义冻结，将来返工代价最大。

**推荐**：以 B 为骨架，先做完 A 中的安全项（Eventa 命名空间、生命周期顺序、权限 flag），C 作为"被延后的决策"，等到有明确的多进程隔离或 headless 需求、且进程内宿主已跑满 1-2 个真实第三方插件后再启动。

---

## 五、可验证的渐进迁移路线（每步有入口、变更、退出门）

按依赖顺序排列，每步独立可回退、可用自动化测试验收：

1. **Eventa 窗口命名空间**（前提：无）。变更为 Eventa 支持按窗口隔离的上下文；逐个删除 `setMaxListeners(0)`。
   **退出门**：`grep -r setMaxListeners` 在 `windows/`、`preload/`、`index.ts` 中归零；新增"两个窗口同名 handler 不串台"的回归测试通过（GitHub/Linear 编号按仓库规范写入测试名）。
2. **统一窗口管理器契约**。抽一个 `WindowManager`（`open/close/getWindow/序列化 bounds`），先迁 `widgets`/`notice` 两个代表性窗口。
   **退出门**：迁移后的窗口通过同一套 `open→reuse→close→bounds 持久化` 测试；`app/config.json` 与 `windows-widgets/config.json` 的 bounds 路径收敛为一种。
3. **后台生命周期收敛**。把 channel-server、插件静态资源、godot、mcp 纳入单一有序生命周期，删除 `plugins/index.ts` 里独立的 `before-quit` dispose。
   **退出门**：启动顺序与"逆序停止"被断言（`createHttpServerManager` 已有此语义，扩展测试覆盖）；退出路径测试覆盖 `SIGINT` 与 `before-quit` 两条。
4. **SDK 发布/冻结**。`plugin-sdk` 去 `private`（或建立外置消费验证），导出面冻结；新增 manifest v1 → 未来 v2 的兼容性 golden 测试。
   **退出门**：一个空壳第三方包能从 `exports` 正确 import `defineExtension`/`defineKit` 并通过 typecheck；破坏性字段变更测试会失败。
5. **kit 版本 + 权限落地**。实现 `incompatible-version` 检查；接入 `permissionResolver`（默认拒绝 + 持久化 grant），用 env flag 门控默认行为变化。
   **退出门**：版本不匹配返回 `incompatible-version`；未授权 capability 抛 `PermissionDeniedError`；flag 关闭时行为与现状一致。
6. **渲染侧契约去重**。`src/shared/eventa/plugin/*` 改从 SDK 再导出，删除本地复制类型。
   **退出门**：`pnpm -F @proj-airi/stage-tamagotchi typecheck` 通过；新增断言"本地 Eventa 契约 id 与 SDK 契约 id 一致"的测试。

每步完成后 `pnpm typecheck` + `pnpm lint` + 定向 `vitest run` 作为统一验收。

---

## 六、不改变的直接后果（分能力看）

- **更多窗口**：每加一个窗口就是一次 `index.ts` 手工装配 + 一处 `setMaxListeners(0)` 复制 + 一种新的 bounds 持久化写法；Eventa 跨窗口事件串台的风险随窗口数上升，且这类 bug 只在多窗口同时运行时才暴露，难以本地复现。
- **第三方插件**：SDK 未发布使第三方无法编译；权限默认全放行使插件声明的权限即所得，缺同意界面；kit 版本声明形同虚设，未来升级内置 kit 会静默破坏第三方插件（而不是给出可诊断的 `incompatible-version`）。
- **独立后台**：进程退出顺序分散在 bootkit 钩子、`injeca.stop()`、插件宿主手工 dispose 三处，新增后台服务会继续放大资源泄漏与顺序 bug；`ServerManager` 契约已就绪却只有空壳（`http-server/index.ts:22-38` 的 `servers: []`），放着不用等于让每条后台能力各写各的启停。

以上评估只陈述架构建议，未对仓库做任何修改。
