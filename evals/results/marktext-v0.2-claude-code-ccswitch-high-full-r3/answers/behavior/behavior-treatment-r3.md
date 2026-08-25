I've completed the evidence-gathering pass. Here is the architecture review.

---

# MarkText 架构评审：应稳定的边界 vs 应延后的抽象

## 1. 范围与置信度

**决策问题**：在给 MarkText 增加窗口能力、文件工作流、编辑器引擎演进或 Electron shell 能力时，哪些边界应当冻结为稳定约定，哪些抽象应当等有第二个真实变体出现后再建。

**仓库分类**：Electron 桌面应用（非 Tauri），pnpm monorepo，三进程模型（main / preload / sandboxed renderer）+ 一个自包含编辑器引擎包（`@muyajs/core`）。skill 提供的 desktop 适配器是 Tauri 专属，因此本评审用核心工作流 + 桌面应用通用的进程边界关注点（IPC、生命周期、沙箱、持久化），并明确标注 Electron 特有事实。**置信度：高**（分类来自 package manifest、进程入口、打包配置、测试与代码注释多重信号，互相一致）。

方法说明：Bash 在本会话被禁用，Git 历史只有 clone/checkout 两条记录（`.git/logs/HEAD`），因此变更史主要来自代码注释、`test/PARITY_SCOREBOARD.md` 和 prompt 提供的 commit 快照。我无法运行 `git log`，凡依赖历史推断的地方已标注。

## 2. 观察到的关键事实（证据）

| 主张 | 证据 | 性质 | 置信度 | 对决策的影响 |
| --- | --- | --- | --- | --- |
| renderer 已完全沙箱化 | `src/main/config.ts:8-27,29-51`（`contextIsolation:true, sandbox:true, nodeIntegration:false`）；`test/e2e/context-isolation.spec.ts` 是显式金丝雀 | 事实 | 高 | 沙箱边界是硬不变式，不可回退 |
| preload 通过 `contextBridge` 暴露固定表面 | `src/preload/index.ts:286-299`（`electron/fileUtils/path/ripgrep/uploader/fonts/…`） | 事实 | 高 | 这就是 shell 能力扩展的稳定接缝 |
| IPC 契约已集中、类型化 | `src/shared/types/ipc.ts` 四类接口 + `preload/index.ts` 泛型收口 | 事实 | 高 | 已有良好接缝，应继续加固 |
| IPC 迁移仍在途，大量 payload 仍为 `unknown` | `ipc.ts` 注释「commits 5–8 逐步收紧」及数十个 `unknown` | 事实 | 高 | 边界已建但未完成 |
| 存在四套协调机制并存 | (a) `src/main/ipc/*` 类型化 handler；(b) `App/WindowManager/DataCenter/Preference/EditorBufferStore` 内联 `ipcMain.on/handle`；(c) `ipcMain.emit` + `onInternalChannel` 当进程内事件总线用（`utils/internalIpc.ts`、`windowManager.ts:421-461`）；(d) `webContents.send` 推送 | 事实 | 高 | 这是最大的变更放大源 |
| 文件保存/重命名/移动的编排散落多处 | `menu/actions/file.ts:494-564`（fs 写入 + `ipcMain.emit('window-change-file-path')` + `webContents.send('mt::set-pathname')`）、`windows/editor.ts:418-444`（更新 `_openedFiles` + watcher）、`filesystem/watcher.ts:399-457`（`ignoreChangedEvent` 时间窗抑制自身写入） | 事实 | 高 | 文件工作流是最高价值重构点 |
| 运行时引擎已是 `@muyajs/core`，旧 `@marktext/muyajs` 无运行时引用 | grep 排除 `.d.ts` 后零匹配；`editor.vue:113,140`、`sourceCode.vue:15`、`util/*` 均导入 `@muyajs/core` | 事实 | 高 | 引擎边界已切换，旧包只剩类型 shim 残留 |
| 引擎类型边界靠手写 shim + `any` | `src/types/muya-core.d.ts`（`Muya` 类 `[key:string]: any`） | 事实 | 高 | 引擎 API 演进靠测试而非 tsc 兜底 |
| 引擎迁移有严格的失败测试记分板 | `test/PARITY_SCOREBOARD.md`：15 个 parity 缺口，14 个已修，PG14 有意 defer 并附理由 | 事实 | 高 | 迁移纪律值得制度化 |
| 窗口抽象已成型 | `windows/base.ts`（`WindowType` BASE/EDITOR/SETTINGS、`WindowLifecycle`）；`app/windowManager.ts`（`Map<number,BaseWindow>`、active 跟踪、`findBestWindowToOpenIn` 评分） | 事实 | 高 | 加新窗口类型应走此抽象而非新建平行体系 |
| 窗口引导契约走 URL 参数 | `base.ts:110-150`（`_buildUrlWithSettings`）、`bootstrap.ts:26-55`（`parseUrlArgs`） | 事实 | 高 | windowId/type/theme 引导是稳定但非正式的接缝 |
| windowId 用 `BrowserWindow.id`，崩溃恢复另用 UUID | `editor.ts:139-145`（`restoreBufferId`，因 win.id 跨会话会复用） | 事实 | 高 | 窗口身份与持久化身份分离是正确的 |
| 文档已漂移 | CLAUDE.md「Three-Process」段称 editor/preferences 窗口用 `contextIsolation:false + nodeIntegration:true (config.js)`——与 `config.ts` 及同文件 overview、`IPC.md` 矛盾；`config.js` 已不存在；`ARCHITECTURE.md` 仍描述 pre-monorepo 布局和「Muya 仍是 JS」 | 事实 | 高 | 文档漂移让边界推理不可靠，需先修 |
| 单测直接 import main 进程模块 | `main_renderer` 别名被大量 spec 使用（`format-menu-state.spec.ts`、`watcher-await-write-finish.spec.ts`、`buffer-store-durable.spec.ts` 等），mock Electron | 事实 | 高 | 说明 main 模块纯度尚可、可测试性强——是宝贵接缝 |
| 偏好存储用 electron-store，有阻塞 I/O TODO | `preferences/index.ts:102-104` 注释 | 事实 | 高 | 目前非瓶颈，别过早替换 |
| `webSecurity: false` 被设置 | `config.ts:19,40` | 事实 | 高 | 沙箱边界上的一个例外，需确认原因 |

## 3. 当前摩擦（变更放大、耦合、缺失的所有权）

**F1 — 一次文件操作横跨 5 个模块、3 种协调机制。** 保存/重命名/移动一个文件，逻辑上是一件事，实现上同时做四件事：写磁盘、更新窗口的 `_openedFiles`、抑制 watcher 的自写回事件、把新路径推回 renderer。这四件事分布在 `menu/actions/file.ts`、`windowManager.ts`、`windows/editor.ts`、`filesystem/watcher.ts`、`store/editor.ts`，并用 `ipcMain.emit` 进程内总线、`webContents.send` 跨进程推送、直接 fs 调用三种机制串起来。任何新的文件工作流（自动保存、批量关闭、workspace 目录、外部编辑器协作）都会在这里放大成本。

**F2 — `ipcMain.emit` 被当作进程内事件总线。** `internalIpc.ts` 自己注释了这是 #1034/#1035 的 workaround。它把「跨进程 IPC」和「进程内模块通信」混在一起，导致：(1) 类型契约（`ipc.ts`）只覆盖一部分真实流量；(2) 新贡献者分不清哪些事件过进程、哪些只在 main 内部；(3) 没有类型、没有可发现性、没有统一注册点。

**F3 — IPC 命名不一致、契约半类型化。** `IpcSendChannels` 里 `mt::` 前缀与无前缀名混排（`update-buffer-state`、`app-create-editor-window`、`watcher-*`、`window-*`、`screen-capture`、`set-image-folder-path`）。`IPC.md` 说「新通道必须用 `mt::`」，但契约里仍列着旧名。很多 payload 是 `unknown`。这削弱了「靠 `pnpm typecheck` 驱动迁移」这个现有优势。

**F4 — watcher 把「监听文件」「重载内容」「按窗口路由」「按时间窗抑制自写」耦合在一个类里。** `Watcher` 以 `win: BrowserWindow` 为键、按 `win.id` 路由，并用 `ignoreChangedEvent(windowId, pathname, duration)` 的时间窗口启发式（文档注明云端盘竞态 GH#3044）来区分「自己的保存」和「外部修改」。这是时序脆弱、且把窗口身份焊进文件层的设计。未来 workspace、非 editor 窗口、或目录级操作都会撞上它。

**F5 — renderer 侧是一个大 Pinia store + 全宽松事件总线。** `store/editor.ts` 是 Muya 事件 ↔ tab ↔ IPC ↔ 缓冲状态的中枢单块；renderer 事件总线 `bus.ts` 是 `[key:string]: unknown[]`（注释明说「Stage 3/4/5」）。新增 renderer 侧窗口/文件能力的主要成本中心就在这里。

**F6 — 引擎类型边界是 `any`。** `muya-core.d.ts` 的 `Muya` 表面是 `[key:string]: any`。今天正确且务实，但意味着引擎 API 演进时，破坏由 parity 测试 + e2e 发现，而非 tsc。引擎一旦开始高频迭代，这会成为静默回归源。

**F7 — 旧引擎包是「已死但未拆」的残留。** `@marktext/muyajs` 仍是 desktop 依赖，`muya` 别名在三个配置里仍指向旧包，`muya.d.ts` 仍声明旧模块，但运行时零引用。【推断】这不是活的接缝，而是延迟清理；风险是误重新引入旧 import 或让贡献者误判当前引擎。

## 4. 质量属性优先级（有取舍）

按「哪个属性真正支配这个决策」排序：

1. **可维护性 / 局部性（change locality）** —— 支配性驱动。证据是 F1 的跨模块放大。目标：一次文件/窗口/引擎变更只落在一个模块 + 一个契约文件。
2. **进程边界稳定性** —— Electron 跨进程的 bug 几乎都长在 IPC、序列化、事件顺序、错误映射上；且这是三进程架构最不可逆的约定。目标：renderer↔main 只有一条类型化契约。
3. **可测试性（通过接缝验证）** —— 项目已具备 `main_renderer` 别名单测、`context-isolation.spec.ts` 金丝雀、parity 记分板三层验证；任何改动都不能牺牲它们。目标：行为能用「跨越预期接缝」的测试捕获，而不是靠 e2e 补漏。
4. **可扩展性（仅限已命名的变体）** —— 只针对真实命名的变体：第三类窗口、新文件工作流、引擎迭代、新 shell 能力。不为假想变体建抽象。
5. **安全** —— 不是可调节的旋钮而是不变式：沙箱 + contextBridge 是硬边界，`webSecurity: false` 是要单独审计的例外。
6. **性能 / 可移植性** —— 本次决策不主导；electron-store 阻塞 I/O 目前有 TODO 但非瓶颈。

明确取舍：**可维护性/局部性 与 进程边界稳定性 排在最前，代价是短期会触碰核心代码**；**可扩展性排在第四，代价是某些「未来换引擎/插窗口」的灵活性被刻意延后**。这正是本评审推荐「稳定接缝、延后抽象」的原因——用今天的少量重构，换未来变更不扩散；不为「也许会有」的第二个引擎消费者提前付费。

## 5. 方案对比

### 方案 A：维持现状（keep current shape）

- **边界与所有权**：四套 IPC/事件机制并存；文件 handler 住在 `menu/actions/file.ts`；`WindowManager` 兼管窗口与 watcher；引擎用 `any` shim；文档漂移保留。
- **它支撑的变更**：小型 bug 修复、已有能力的微调。
- **成本**：零迁移成本，动能最好，当前形状有测试覆盖、确实能发布。
- **风险**：每增加一种新窗口/新文件流程/新引擎能力，变更继续在 5+ 模块扩散；命名/类型漂移加剧；文档与实际越差越远；`ipcMain.emit` 总线对新贡献者是持续雷区。
- **回滚**：无需回滚（什么都没动）。
- **不改变的后果**：未来能力的边际成本单调上升，最终逼近「没人敢动文件路径和窗口身份」的僵化状态。
- **使本方案错误的证据**：本次评审问题本身——团队已经在计划窗口/文件/引擎/shell 能力。

### 方案 B：稳定三个真实接缝，其余延后（推荐）

分五步、全部可独立发布、可逆：

- **B1**：把类型化 IPC 契约（`ipc.ts` + `preload` + `src/main/ipc/*`）变成 renderer↔main 的**唯一**注册表：完成 `unknown`→具体类型收紧；把残留的内联 `ipcMain.on/handle` 迁到 feature 模块；renderer↔main 通道统一 `mt::` 命名。
- **B2**：用项目已有的 `TypedEmitter` 建一个**显式进程内事件总线**，替代 `ipcMain.emit`/`onInternalChannel`（完成 #1034/#1035 清理）。跨进程与进程内从此分属两套机制。
- **B3**：抽出一个**文件操作服务**（先做薄门面，再逐步收拢），独占「改磁盘 → 更新窗口打开文件列表 → 抑制 watcher → 推 renderer 状态」这套编排。保存/重命名/移动/关闭四个入口都改调它。
- **B4**：冻结桌面侧引擎 API 为一个小而显式的接口：把 `Muya` 的 `[key:string]: any` 替换为桌面实际使用的子集；保留 parity 记分板当行为护栏。
- **B5**：修文档漂移（CLAUDE.md 沙箱段、ARCHITECTURE.md），零代码、高杠杆。

- **边界与所有权**：IPC 契约、进程内总线、文件操作服务各有一个明确 owner；窗口身份（win.id）与持久化身份（restoreBufferId）保持分离。
- **它支撑的变更**：新文件工作流只需扩展文件操作服务；新窗口类型走 `BaseWindow/WindowManager/WindowType`；新 shell 能力走 preload 表面 + IPC 契约；引擎演进变成「编译期可见的接口变更」。
- **成本**：中——触及核心路径，但每步独立可逆，且全部复用现有接缝（`TypedEmitter`、类型化 IPC、`main_renderer` 单测、parity 记分板）。
- **风险**：过度抽象的风险——必须用 deep-module 判断：只在「一个文件操作确实横跨 5 模块」这类已被证据证明的杠杆点抽接口，不为「也许有第二个引擎」预先建适配层。
- **回滚**：每步单独可回退；B2 可保留薄 shim 过渡；B3 可从「纯门面调用现有函数」开始，回滚是机械的。
- **使本方案错误的证据**：若团队只做小修且无新能力计划（则 A 更省）；或出现「必须运行时热切换引擎」这类硬需求（则需升级为 C 的子集）。

### 方案 C：全面分层 / 领域化重构（建议拒绝，仅记录）

- 例子：完整 workspace/document 服务层、窗口类型插件注册表、可插拔引擎适配接口、IPC 绑定代码生成（tRPC 式）、preferences 迁移到 SQLite。
- **它支撑的变更**：未来任意能力插拔。
- **成本**：巨大；志愿者 OSS 团队难以持续；违反「两个真实变体之前不建通用抽象」的规则。
- **风险**：为了假想变体引入间接层，反而让当前变更更难定位；可能破坏刚完成的沙箱迁移。
- **回滚**：几乎不可逆（横切重写）。
- **结论**：现在不做。只有当具体证据出现时才摘取其中某个子项——例如第三个真实窗口类型落地时，才考虑窗口注册表；第二个真实引擎消费者出现时，才考虑引擎适配接口。

## 6. 建议

**选方案 B，按以下顺序推进。** 核心判断：MarkText 已有三条高质量接缝（沙箱/preload、类型化 IPC、`BaseWindow`/`WindowManager`），真正缺的不是新抽象，而是 (1) 消除四套机制并存造成的变更放大，(2) 给文件操作一个单一所有权，(3) 修正文档漂移让边界可推理。

**现在就该稳定下来的边界**（投入少量重构）：

1. **renderer↔main 的唯一类型化 IPC 契约**——已完成约七成，收尾性价比最高。
2. **显式进程内事件总线**——消除 `ipcMain.emit` 的跨进程/进程内混淆，这是文件编排痛苦的总根。
3. **单一文件操作服务**——文件工作流未来的落点，也是当前放大最严重的点。

**应当保护、但不要改的边界**（防止漂移即可）：

- 沙箱/preload 表面（有金丝雀测试守护）。
- `WindowType`/`BaseWindow`/`WindowManager` 形状（足够用，加窗口类型时走它）。
- 引擎包边界（类型 shim + parity 纪律，见 B4 的窄化而非重造）。

**明确延后、以及重启条件**：

- **引擎适配/可插拔接口**：等第二个真实引擎消费者、或运行时热切换需求出现。
- **窗口类型插件注册表**：等第三个真实窗口类型落地。
- **IPC 代码生成器**：等通道数量或团队规模让手写契约成为瓶颈。
- **替换 electron-store**：等实测偏好写入延迟成为问题。
- **workspace/项目域模型**：等「打开多根目录/项目文件」成为被用户验证的需求。

## 7. 迁移与验证（渐进、可逆、可观察）

| 步骤 | 内容 | 验证 / 退出标准 | 回滚 |
| --- | --- | --- | --- |
| 1. 文档对齐 | 修正 CLAUDE.md 沙箱段（`config.ts` 为真）、ARCHITECTURE.md 布局与引擎现状 | `grep -rn "contextIsolation: false" packages/desktop/src` 无误导结果；文档与 `config.ts`/`IPC.md` 一致 | 纯文档，revert 即可 |
| 2. 完成 IPC 类型收紧 | 把高频通道 `unknown`→具体类型，仅类型改动 | `pnpm typecheck` 通过；`ipc.ts` 中 `unknown` 计数下降；行为零变化 | git revert |
| 3. 引入进程内总线 | `TypedEmitter` 总线替换 `ipcMain.emit`/`onInternalChannel`，按 feature 逐个迁移（先 watcher/文件路径簇） | 现有单测（`watcher-await-write-finish`、`keybinding-menu-rebuild` 等）+ e2e 全绿；grep 显示 `ipcMain.emit` 只剩总线适配器或已移除 | 过渡期保留薄 shim |
| 4. 抽取文件操作服务 | 把保存/重命名/移动/关闭的编排从 `menu/actions/file.ts` 收拢到一个模块，先薄门面后收拢 | 保存/重命名/移动相关 e2e + 新增用 fake 验证编排的单测；parity/e2e 套件绿 | 服务从门面起步，回滚是机械的 |
| 5. 窄化引擎表面 | `Muya` 的 `any` 换成桌面实际使用子集；保留 parity 记分板 | `pnpm -C packages/muya test` + desktop parity e2e + `pnpm typecheck` | 恢复 shim |

**建议先做第 1 步 + 第 3 步的第一个 feature 垂直切片**：修文档 + 把 watcher/文件路径这一簇从 `ipcMain.emit` 迁到显式总线。这一刀就消除了 F1/F2 的最大痛感，且完全可逆、有现成测试兜底。

**不做的清单与重启信号**见第 6 节。每一项都对应「先观察到一个真实变体，再建抽象」。

**决策记录（ADR）候选**：以下决策值得按 `decision-record.md` 格式落 ADR，因为未来评审会重开它们而没有理由：①「renderer↔main 以 `ipc.ts` 为唯一契约 + `mt::` 命名」；②「进程内事件总线与跨进程 IPC 分离（#1034/#1035 收口）」；③「引擎类型边界用 shim 截断依赖图，直到 `@muyajs/core` 发布内置 `.d.ts`」。

## 8. 待决问题（答案可能改变建议）

1. **能力优先级是否已有路线图？** 下一个真实变体是「第三类窗口」还是「workspace 目录」还是「引擎迭代」，会改变第 3/4 步的先后。【未知】
2. **旧 `@marktext/muyajs` 是否计划彻底移除？** 它仍是 workspace 依赖和三个配置的别名目标，虽然运行时零引用。若不移除，是否需要把「muya 别名已退役」写进文档防止误 import？【未知】
3. **`webSecurity: false` 是否仍必要、服务于什么？** 这决定沙箱边界能否进一步收紧，是安全属性上唯一未解释的例外。【未知】
4. **Electron 生命周期预期？** CLAUDE.md 写 Electron 42；若近期还有大版本跳变，进程边界契约的版本化策略需要同步考虑。【未知】

核心结论一句话：**MarkText 已经建好了三条关键接缝（沙箱、类型化 IPC、窗口抽象），现在该做的是把它们变成唯一真相源——收口四套并存机制、给文件操作一个 owner、修文档漂移——而不是为假想的未来建新抽象层。**

[EVAL:evolve-software-architecture-loaded]
