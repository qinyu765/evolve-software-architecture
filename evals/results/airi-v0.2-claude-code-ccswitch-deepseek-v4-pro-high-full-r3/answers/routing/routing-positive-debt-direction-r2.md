# AIRI 桌面端 ↔ 共享 package 耦合治理建议（只读评估）

## 1. 范围与置信度

- **决策问题**：下一步最值得治理的架构边界，是「`stage-shared` 这个中立共享包正在承接桌面端（Electron）专属的契约与类型」，而不是把问题笼统归为「桌面端 imports 太多」。
- **仓库分类**：Electron 桌面 app（`stage-tamagotchi`）+ 多前端共享 monorepo。`crates/` 是旧 Tauri，当前桌面是 Electron（事实）。skills 里只有 Tauri adapter，所以我只用桌面/进程边界类通用关切（IPC 契约、类型隔离、环境检测），不套用 Tauri 具体机制。
- **置信度**：诊断 **高**（证据充分、一致）；「这是*下一条*边界 vs stage-ui 公共 API 表面」这个排序判断是 **中**（两个候选都真实存在，我按风险/杠杆选择，见第 5、8 节）。

## 2. 观察到的事实

| 声明 | 证据 | 类型 | 置信度 |
| --- | --- | --- | --- |
| `stage-shared` 的根 barrel 导出 Electron IPC 契约 | `packages/stage-shared/src/index.ts:1` 直接 `export * from './artistry'`；`src/artistry.ts:11-23` 定义 `defineInvokeEventa`，地址为 `eventa:invoke:electron:artistry:*` | 事实 | 高 |
| 同一文件还塞了 UI 内容（Replicate 预设、fabric/hair/eyes 预设组） | `packages/stage-shared/src/artistry.ts:25-200` | 事实 | 高 |
| `stage-shared` 根 barrel 导出 Electron 窗口类型 | `src/index.ts:9` → `src/window.ts:1-8` import `ElectronAPI` from `@electron-toolkit/preload` 与 `NodeJS.Platform`；`src/electron-renderer.d.ts:1-5` 全局 `Window extends ElectronWindow` | 事实 | 高 |
| 中立消费者却引入根 barrel | `apps/stage-web/src/main.ts:9`（`isEnvTruthy`）、`apps/stage-pocket/src/main.ts:8`、`apps/ui-server-auth/src/main.ts:7`、`packages/stage-layouts/*`、`packages/stage-ui-live2d/*` 都 import `@proj-airi/stage-shared` 根或子路径 | 事实 | 高 |
| 仓库里**已经存在**专门的 Electron 契约归宿 | `packages/electron-eventa/package.json:18-36`（"Shared Eventa contracts for Electron IPC"，`peerDependencies: electron`）；`apps/stage-tamagotchi/src/shared/eventa/index.ts:33-500` 是桌面 app 自己的集中契约 hub，已定义几十个 `eventa:invoke:electron:*` | 事实 | 高 |
| 桌面端自己都承认 hub 是契约中心，却反向 import stage-shared 的类型 | `apps/stage-tamagotchi/src/shared/eventa/index.ts:7-18` 从 `stage-shared/global-shortcut`、`godot-stage`、`server-channel-qr` 引入类型 | 事实 | 高 |
| `global-shortcut`、`godot-stage` 只有桌面端消费 | 全仓库 grep：仅 `apps/stage-tamagotchi/...`（main、renderer、spotlight、devtools、shared/eventa）；web/pocket 不用 | 事实 | 高 |
| `beat-sync`、`server-channel-qr` 是真正跨端共享 | `packages/stage-ui-live2d/src/components/scenes/live2d/Model.vue:6`（beat-sync）；`apps/stage-pocket/src/pages/settings/connection/server-channel-qr-scanner.vue:4`（QR） | 事实 | 高 |
| `stage-ui` 用通配符 subpath 把全部内部文件变成公共 API | `packages/stage-ui/package.json:24-25`（`./components/*: ./src/components/*.ts`）、`:45`（`./stores/*`）；桌面 `App.vue` import ~20 个 store 深路径 | 事实 | 高 |
| 桌面渲染层深耦合 stage-ui 内部 store 图 | `apps/stage-tamagotchi/src/renderer/App.vue:9-20`、`stores/chat-sync.ts:10-17` | 事实 | 高 |

「耦合*正在增加*」我没有 git 历史工具佐证（Bash 被禁用），所以这是**推断**：依据是 `artistry.ts` 这类 Electron IPC 契约被加进了中立包，而仓库里明明已有 `electron-eventa` 和 app 自己的 `src/shared/eventa` 两个正确归宿——新增代码没有走既有 seam，说明这条边界正在失守。

## 3. 当前摩擦（change amplification）

`stage-shared` 现在承担了两种互相冲突的责任：

1. **中立、跨三个 stage 表面的工具**：`error-message`、`env-vars`、`url`、`export-csv`、`perf/*`、`webgpu/*`、`auth/pkce`、`composables/local-storage`、`beat-sync`（live2d 用）、`server-channel-qr`（pocket 用）。
2. **Electron 专属表层**：IPC invoke 契约（`artistry.ts`）、`ElectronWindow`/`isElectronWindow` + 全局 `Window` 增强（`window.ts`、`electron-renderer.d.ts`）、OS 全局快捷键加速器（`global-shortcut`）、Godot sidecar 视图协议（`godot-stage`）。

后果是：

- **web / pocket / ui 的 type 图被桌面类型污染**：只要 import 根 `@proj-airi/stage-shared`（web、pocket 都这么做），tsc 就会解析 `window.ts` 里的 `@electron-toolkit/preload` 类型和 `NodeJS.Platform`，形成一条隐式的 Node/Electron 类型传递链——正是 AGENTS.md 里点名要避免的「Node-only 与 browser-only 类型混入同一条 import 链」。
- **两个契约中心并存**：app 的 `src/shared/eventa/index.ts` 已经是集中 hub，但 `artistry` 契约绕过了它直接落在 `stage-shared`，未来改动会散落两处。
- **共享包被当成杂物间**：`artistry.ts` 一个文件同时承载 IPC 契约 + 提供商预设内容 + UI 预设组，职责三重，且归属错位。
- **桌面端改动反过来牵动中立包**：改一个 Electron 契约要改 `stage-shared`，而它的版本会被 web/pocket 一并消费，放大变更面。

对比：`stage-ui` 深 import 是**对称的**（web 和桌面都这么用，且 AGENTS.md 明确把 stage-ui 定位为「stage 工作的心脏」），它更像「公共 API 表面失控」，是更大的下一题，而不是「桌面↔共享」这个具体病灶。

## 4. 质量属性优先级

| 排名 | 属性 | 理由与取舍 |
| --- | --- | --- |
| 1 | **边界局部性 / 可维护性** | 桌面契约改动不应要求 web/pocket 重新解析桌面类型；反之亦然。这是本决策的支配属性 |
| 2 | **可测试性** | 契约集中到已有 hub 后可用 `vi.fn` 直接 mock；中立工具保持纯函数、无需 Electron 运行时即可测 |
| 3 | **构建/类型隔离** | web/pocket 不应有对 `@electron-toolkit/preload`、`NodeJS.Platform` 的隐藏传递依赖 |
| 4 | **成本 / 可逆性** | 优先小切口、每步可单独 revert；不为「未来第二个 Electron app」提前抽象 |

明确不追求：**最大复用**（把一切 Electron 契约硬塞进 `electron-eventa` 才算复用，反而会过度泛化）；**一次性消解 stage-ui 深耦合**（那是后续更大课题，见第 5/8 节）。

## 5. 方案比较

### 方案 A —— 维持现状（`stage-shared` 继续做杂物间）

- **边界**：无明确边界；Electron 契约、Electron 类型、中立工具、UI 预设内容同处一包、同出根 barrel。
- **优点**：今天零迁移成本；所有 stage 面都能 import 到任何东西，改动快。
- **代价/风险**：桌面↔共享耦合继续单向增长；web/pocket 类型图持续携带 Electron 类型；契约双中心漂移；`stage-shared` 每次发布都会牵动所有下游。
- **该方案被证伪的信号**：又有一个 Electron IPC 契约被加进 `stage-shared`；或 web/pocket 某次 typecheck 因 Electron 类型失败；或 `stage-shared` 开始依赖 `electron` 本体。

### 方案 B（推荐）—— 把 Electron 自有表层移出 `stage-shared`，立一条 surface-ownership 边界

- **边界**：`stage-shared` 只保留**环境*检测*（编译期标志）与真正跨 ≥2 表面的中立逻辑**；Electron **运行时表层**（IPC 契约、窗口/preload 类型、OS 快捷键、Godot 视图协议）归属桌面侧——一次性契约进 app 的 `src/shared/eventa` hub，可复用的进 `@proj-airi/electron-eventa`。
- **优点**：直接命中「桌面↔共享耦合」；复用仓库里**已存在**的契约归宿，不发明新抽象；每步可独立 revert；让 web/pocket 的类型图回归中立。
- **代价**：一次性的 import 迁移（调用点更新）；迁移期间有短暂的双 home 并存期（见第 7 节）。
- **假设**：`beat-sync`、`server-channel-qr` 确为跨端（已证实）；`isElectronWindow` 是共享 UI 分支所需的*能力检测*，可保留但需去 Electron 类型化（见第 7 节）。
- **该方案被证伪的信号**：出现第二个 Electron app 且契约需跨 app 复用（则强制全部走 `electron-eventa`，而非 app hub）；或团队决定 `stage-shared` 不再跨 bundler 中立。

### 方案 C（更大、应后置）—— 约束 `stage-ui` 的公共 API 表面

- **边界**：把 `stage-ui` 的通配符 subpath 收口成稳定的公共 barrel，把 `stores/chat/session-store`、`stores/mods/api/*` 这类内部深路径挡在公共 API 之外。
- **优点**：杠杆最高（web 和桌面同时受益），根治「改 stage-ui 内部就破坏桌面/Web 调用点」。
- **为什么不现在做**：改动面大、风险高、且它是对称问题而非桌面特有问题；现在做会把一个可快速见效的边界治理拖成大型重构。**触发信号**：stage-ui 内部 rename/拆分频繁导致桌面或 web 调用点破损；或需要发布阶段化 API 版本。

## 6. 推荐

**先立「surface-ownership」边界（方案 B），先做 `artistry.ts` 这个垂直切片，暂不动 stage-ui 公共 API。**

核心理由：

- 这是唯一**已有正确归宿却被绕过**的边界——`electron-eventa` 和 app 的 `src/shared/eventa` 都已存在，治理成本最低、证据最硬。
- 它直接回应「桌面↔共享耦合在增加」：新增的 Electron 契约正是不该进中立包的东西。
- 它把「环境检测」和「Electron 运行时表层」分开，这条 seam 小而深：桌面端可自由演进契约，中立包对 web/pocket/ui 保持纯净。

**治理规则（建议写成 ADR 固化）**：

1. `stage-shared` 是**环境中立**的共享面：可含编译期环境标志（`StageEnvironment`、`isStageWeb/Capacitor/Tamagotchi`、`IS_DEV`），但**不得** import `electron`、`@electron-toolkit/*`，**不得**定义 `eventa:invoke:electron:*` 契约。
2. Electron IPC/事件契约只进两处：**一次性** → `apps/stage-tamagotchi/src/shared/eventa`；**可复用** → `@proj-airi/electron-eventa`。
3. Electron 窗口/preload 类型不进中立 barrel；`isElectronWindow` 若被跨端模块（如 `beat-sync`）需要，改为结构化类型守卫，不再依赖 `@electron-toolkit/preload` 的类型。

## 7. 迁移与验证（渐进、可逆）

按 monorepo 政策「不加向后兼容 shim」执行干净切割，每步一个 commit、可单独 revert。

1. **记录规则**：写一份 ADR（或 `docs/solutions/` 下一条），固定第 6 节三条规则。无迁移风险，产出是决策文档。
2. **第一个垂直切片（最小完整切割）**：把 `stage-shared/src/artistry.ts` 的 IPC 契约迁到 `apps/stage-tamagotchi/src/shared/eventa`（或 `electron-eventa`，取决于第 8 节问题 1），把 `REPLICATE_*`/`ARTISTRY_PRESET_GROUPS` 内容迁到 stage-ui 的 artistry store；更新两个调用点——`src/main/services/airi/widgets/artistry-bridge.ts:15` 与 `src/renderer/App.vue:5`、`src/renderer/stores/tools/builtin/image-journal.ts:7`；删除根 barrel 的 `artistry` 导出。**验证**：三端 typecheck 通过、artistry 相关 vitest 通过。
3. **第二个切片**：处理 `window.ts`/`electron-renderer.d.ts`——把 `ElectronWindow` 结构化定义（不 import `@electron-toolkit/preload`），全局 `Window` 增强移到桌面侧 `.d.ts`；保留 `isStageTamagotchi`/`StageEnvironment` 于 `stage-shared`。**验证**：`stage-web`、`stage-pocket` 的 typecheck 不再解析 `@electron-toolkit/preload`。
4. **第三个切片**：把 `global-shortcut`、`godot-stage` 的契约类型与桌面专属逻辑迁到 `electron-eventa`（或 app shared）；更新 `src/shared/eventa/index.ts:7-18` 的 import。纯工具（如加速器字符串解析）随模块一起走，不在中立包留桌面专属域逻辑。
5. **上护栏（可观察的退出标准）**：加一条轻量检查——CI 脚本或 ESLint 规则，当 `stage-shared` import `electron`/`@electron-toolkit/*` 或定义 `electron:` 前缀 Eventa 契约时报错。这是这条边界的长期执法手段。
6. **回滚**：每步都是纯搬迁（同一改动内更新全部调用点），`git revert` 该 commit 即回滚；无运行时行为改变。

**完成判据**：`stage-web`/`stage-pocket`/`stage-tamagotchi`/`stage-ui` 全部 `pnpm -F <pkg> typecheck` 通过；`stage-shared` 源码中不再出现 `electron`/`@electron-toolkit` import 与 `electron:` Eventa 地址；护栏规则落位并能拦住回归。

## 8. 待定决策（会改变推荐的问题）

1. **近期是否会有第二个 Electron app？** 若无，一次性契约放 app 的 `src/shared/eventa` 更简单；若有，则统一走 `electron-eventa`。【未知】
2. **`beat-sync` 在 live2d 里的用途是否真的跨端？** 若其实只有桌面端用，`beat-sync` 也可整体下放到桌面侧，`stage-shared` 会更瘦。【未知】
3. **`stage-shared` 是否要求 bundler 中立？** `environment.ts`/`env-vars.ts` 用 `import.meta.env`，目前三个 stage 面都是 Vite 所以成立；若未来出现非 Vite 表面，需单独治理这条。【未知】
4. **`stage-ui` 公共 API 收口何时启动？** 作为方案 C 后置，触发信号见第 5 节；不在本次动工范围内。

[EVAL:evolve-software-architecture-loaded]
