我已核对文档、实现、配置、测试与 Git 状态（Bash 不可用，故以源码与注释中的历史线索为准）。先给结论，再给证据与迁移路线。

# MarkText 架构演进评审：哪些边界该稳定、哪些抽象该延后

**一句话结论**：仓库正处在一场方向正确、但只做了一半的迁移中间——沙箱化 + 类型化 IPC 契约已经成形，却还有两条“半成品接缝”在拖累所有未来的窗口/文件/引擎/壳层改动：① `shared/types/ipc.ts` 的 channel 名严格、payload 大量是 `unknown`（注释自述“commits 5–8”才收紧）；② 主进程内部用 `ipcMain.emit` + 字符串 channel 充当未类型化的事件总线。**最该做的是“收口已有接缝”，而不是新建抽象**：把 IPC 契约收紧、把散落各处的 legacy handler 归一到一处注册、把内部总线类型化、把“哪些文件开在哪个窗口”的索引收敛到 `WindowManager`。通用窗口框架、工作区/会话模型、IPC 版本化、异步偏好存储，都应当**延后**，直到出现第二个真实变体或可测量的痛点。

## 1. 范围与置信度

- **决策对象**：在未来增加窗口能力、文件工作流、编辑器引擎演进、Electron 壳层能力时，MarkText 的哪些边界应当成为稳定契约，哪些抽象应当延后。
- **仓库分类**：Electron 桌面应用（三进程：main/preload/renderer）+ pnpm monorepo，处于沙箱迁移进行中。**置信度：高**。多路独立信号一致：`electron.vite.config.ts`（main/preload 编为 CJS、renderer 编为 ESM）、`packages/desktop/src/main/config.ts:11-39`（`contextIsolation:true, sandbox:true, nodeIntegration:false`）、`src/preload/index.ts:1-3` 的“Sandboxed preload”注释、`test/e2e/context-isolation.spec.ts` 的金丝雀测试。
- **已知未知**：`ipc.ts` 注释提到的“commits 5–8”迁移计划本身**不在仓库内**（grep 只找到引用它的注释，未找到计划文档）；该计划应挂到 issue/PR 链接。这不改变结论，但影响“迁移是否已立项”的判断。

## 2. 观察到的事实（证据表）

| 断言 | 证据 | 类型 | 置信度 | 后果 |
| --- | --- | --- | --- | --- |
| 根 package.json 只做代理，桌面逻辑在 `packages/desktop` | `package.json`、`pnpm-workspace.yaml` | 事实 | 高 | 变更集中在 desktop 包 |
| 三进程 + 渲染器完全沙箱化 | `config.ts:11-39`、`electron.vite.config.ts`、`context-isolation.spec.ts` | 事实 | 高 | 所有 Node 访问必须走 preload→IPC，是硬约束 |
| IPC 契约是“单一事实源”，但 payload 大量 `unknown` | `shared/types/ipc.ts:1-18, 40-202, 208-289` | 事实 | 高 | 契约已有形状，类型收紧是纯增量 |
| 两套 IPC 注册机制并存 | `main/ipc/index.ts`（新）vs `app/index.ts:658-850`、`windowManager.ts:367-495`、`dataCenter/index.ts:162-213`、`editorBufferStore/index.ts:214-218`、`preferences/index.ts:176-193`、`menu/actions/file.ts:285-677`（legacy 裸 `ipcMain.on/handle`） | 事实 | 高 | 新功能不知道在哪注册、用哪套 |
| `ipcMain.emit` 被当作主进程内部事件总线，channel 未类型化 | `utils/internalIpc.ts`；`windowManager.ts:421-495`、`app/index.ts:672-765`、`windows/editor.ts:396/415/430` | 事实 | 高 | 窗口/文件特性都跨这条总线，emit 与监听无编译期契约 |
| “哪些文件开在哪个窗口”有双份状态 | main `EditorWindow._openedFiles/_openedRootDirectory`（`windows/editor.ts:57-79, 411-469`）vs renderer `editor.ts:139-152` 的 `tabs: IFileState[]` | 事实 | 高 | watcher 挂接与“最优窗口路由”依赖影子状态 |
| 跨进程文档形状已在 `shared/types/files.ts` | `IFileState`、`MarkdownDocument`、`SaveOptions`、`UnsavedFile` | 事实 | 高 | 文件工作流的契约已有雏形 |
| `Accessor` 是主进程组合根 | `app/accessor.ts:12-42` | 事实 | 高 | 新服务有明确挂载点 |
| 引擎迁移在 import 层面已完成 | grep 到 0 处 `from 'muya/lib'`/`from 'muya'`，全部为 `@muyajs/core`；但 `@marktext/muyajs` 依赖与 `muya` alias 仍保留 | 事实 | 高 | 旧引擎的**配置**是死配置，可安全移除 |
| 路径谓词与扩展名列表在两处重复、语义不一致 | `common/filesystem/paths.ts:8-166`（用 node `fs`/`path`，`isSamePathSync` 用 inode）vs `preload/index.ts:115-156`（用 `pathe`，`isSamePathSync` 用字符串比较 + 同步 IPC 兜底） | 事实 | 高 | 改扩展名要改两处；两处“同路径”判定强弱不同 |
| 偏好存储为同步阻塞 I/O，已被标记 TODO | `preferences/index.ts:102-104` | 事实 | 高 | 与文件工作流（自动保存、最近目录）相关的写放大风险 |
| 文档与实现不一致 | 根 `CLAUDE.md` 架构图仍写“editor/settings 窗口用 contextIsolation:false + nodeIntegration:true”，与 `config.ts` 及金丝雀测试矛盾 | 事实 | 高 | 照文档实现会回退安全边界 |

## 3. 当前摩擦（变更放大与归属不清）

1. **内部总线未类型化且与传输层共用一个对象**。窗口/文件特性（`watcher-watch-file`、`window-add-file-path`、`app-open-*-by-id`、`broadcast-*-changed`）全走 `ipcMain.emit` 的字符串 channel，emit 端与监听端没有任何编译期约束，一个 channel 改名或参数变化只能在运行时炸。这是未来窗口/文件能力最大的摩擦源。
2. **IPC 契约半类型化 + 注册点分散**。契约方向正确（四类 channel、泛型 wrapper 已写好），但 `unknown` 未收口，且 legacy handler 散在 6 个文件里。新增一个壳层能力时，开发者要自己判断“该进 `src/main/ipc/*` 还是就地 `ipcMain.on`”。
3. **开文件索引双份**。main 用 `EditorWindow` 的影子状态做 watcher 挂接和 `findBestWindowToOpenIn` 路由，renderer 用 Pinia store 持有真正的文档状态。二者靠手工保持一致；文件工作流越复杂，这份影子状态越容易失同步。
4. **preload 与 main 重复实现路径谓词**，且 `isSamePathSync` 语义不同（main 用 inode，preload 用字符串 + 同步 IPC）。这是沙箱约束下“合理但危险”的重复——扩展名列表这种**纯数据**本可以共享。
5. **引导参数走 URL query**（`wid/type/cff/cfs/...`），且 `wid` 与 `window.marktext.env.windowId` 重复承载。窗口能力增多时，这条序列化面会很脆。
6. **文档滞后**（见上表最后一行），会误导后续改动。

## 4. 质量属性优先级（含权衡）

按对本次决策的支配力排序：

1. **可维护性 / 变更局部性**（最高）。目标是“未来的窗口/文件/引擎改动只落在一处”。证据：上面 6 个摩擦点全是“改动会扩散”的形态。
2. **进程边界稳定性**（桌面专属）。IPC 契约 + 内部总线是承重接缝；序列化、错误映射、事件顺序都要有编译期约束。
3. **可测试性**。类型化契约让测试能跨接缝断言（`context-isolation.spec.ts` 已经是范例）。
4. **可移植性**（Win/mac/Linux）。是**约束**而非驱动：watcher/window 代码已大量按平台分支（`watcher.ts` 的 Linux 原子重命名、`app/index.ts` 的 mac/windows 分支），新增能力不得破坏矩阵。
5. **性能**。启动与打字时延有预算；`electron-store` 的同步 I/O 是已标记风险，但不是架构接缝问题。
6. **安全性**。沙箱是硬约束（金丝雀测试锁死），未来壳层/窗口能力不得回退 `nodeIntegration`。

显式取舍：把内部总线类型化、把 IPC 收紧，会**暂时增加**每个 channel 的样板代码（成本），换来后续改动的局部性和可测试性（收益）。不做的代价是每个新特性都继续在运行时排错。

## 5. 方案比较

### 方案 A：维持现状（合理选项，但不推荐）

在两条注册机制和未类型化内部总线上继续 ad hoc 加功能。

- **边界与归属**：维持现状——契约在 `shared/types/ipc.ts`，legacy handler 就地注册，内部总线用 `ipcMain.emit`。
- **能做什么**：什么都不做；新功能照现有模式堆。
- **成本/风险**：短期零成本。风险是变更放大持续累积，且“channel 名靠约定”在窗口/文件特性增多后最容易出错。
- **不改变的后果**：第 3 节 6 个摩擦点全部保留；每加一个窗口类型/文件操作，都要重复决定“在哪注册、参数是什么、emit 谁监听”。
- **使本方案失效的证据**：如果出现第二个真实的窗口类型或第二个文件来源（如 Git 仓库/云端/多根目录），影子状态和散落 handler 的成本会非线性上升。

### 方案 B：收口两条已有接缝（推荐）

不新建抽象，只把已经存在的接缝做“完成态”：① 收紧 IPC payload 类型（`unknown` → 具体类型）；② 把 legacy handler 全部归一到 `src/main/ipc/*` 的统一注册助手；③ 用类型化内部 channel 注册表替换 `ipcMain.emit` 总线（`onInternalChannel` 升级为带 channel map 的 `TypedEmitter`）；④ 把“开文件索引”收敛到 `WindowManager`；⑤ 抽取无 `path`/`fs` 依赖的纯数据常量（扩展名列表等）供三进程共享。

- **边界与归属**：进程边界 = 类型化 IPC 契约 + 类型化内部总线；窗口归属 = `WindowManager` 的 `windowId → {rootDirectory, openedFilePaths}` 索引；文件归属 = `shared/types/files.ts` 形状 + `@muyajs/core` 入口。
- **能做什么**：未来窗口能力在 `WindowManager` 一处路由；文件工作流在类型化 channel 一处扩展；引擎演进只动 `@muyajs/core` 入口；壳层能力在 `src/main/ipc/*` 一处注册。
- **假设**：channel 收紧不会暴露大量“main 实际发的形状与 renderer 期望不一致”的历史 bug（这正是收紧的目的，但会带来一次性噪音）。
- **成本/风险**：中等一次性成本，全机械、可逐 channel 提交。风险低：每一步都是薄包装、行为不变。
- **回滚**：逐 channel revert；内部总线包装委托给同一 emitter，可一行换回。
- **测试后果**：类型检查本身成为契约测试；可新增“channel 注册覆盖率”测试禁止 `src/main/ipc/*` 之外裸用 `ipcMain`。
- **使本方案失效的证据**：若收紧过程中发现 main/renderer 需要跨版本独立升级（in-place 更新导致两侧版本不同），才需要引入版本化——那是下一步 ADR，不是本方案推翻的理由。

### 方案 C：显式能力层 + 工作区/会话模型（更大重构，暂缓）

把 `window.electron.*` 命名空间提升为显式“能力层”，main 侧为每个能力建模块注册表（把**所有** channel 包括 file/menu/window 都纳入），并引入一等“工作区/会话”模型统一持有“每窗口打开了哪些文件”。

- **边界与归属**：进程边界 = 能力注册表；文档归属 = 工作区/会话模型。
- **能做什么**：最“干净”的目标态，适合未来多窗口、多项目、多引擎同时演进。
- **成本/风险**：**当前最高**。在只有 2 个窗口类型（editor/settings）、1 个项目模型（打开文件夹）的情况下，这是为尚未出现的变体买单。
- **使本方案失效的证据**：出现第三个真实窗口类型、第二个项目来源，或引擎需要运行时切换时，方案 C 的收益才会兑现。

## 6. 建议：稳定什么、延后什么

采用**方案 B**，并把方案 C 的部件拆成“触发条件”挂起。

**应当稳定（已经是承重接缝，只差完成）**：

1. **类型化 IPC 契约 + contextBridge preload 表面**（`shared/types/ipc.ts` + `preload/index.ts` + `types/global.d.ts`）。这是所有四类未来能力共同跨越的接缝，收紧它是最高杠杆动作。
2. **跨进程文档/文件形状**（`shared/types/files.ts`）。文件工作流的契约已经在这，稳定它。
3. **`Accessor` 组合根 + `BaseWindow` 生命周期事件 + `WindowManager` 注册表**。窗口能力扩展的归属点。
4. **`TypedEmitter` 模式**（`shared/types/typedEmitter.ts`）。主进程事件原语，用它类型化内部总线。
5. **`@muyajs/core` 的 `src/index.ts` 入口**作为唯一引擎接缝；同时把死掉的 `muya` alias 和 `@marktext/muyajs` 依赖移除（import 面已为零，属安全清理）。

**应当延后（出现第二个真实变体或可测量痛点前不做）**：

1. **通用多窗口框架 / 抽象“工作区-项目”层**——等第三个窗口类型或第二个项目来源。
2. **IPC 序列化/版本化框架**——等 in-place 更新使 main/renderer 版本真正分叉。
3. **编辑器插件/扩展系统**——muya 内部已有 UI plugin 机制，先不向上泛化。
4. **异步偏好存储替换**——`electron-store` 是性能修复，不是架构接缝；等有测量数据再作为局部改造做。

## 7. 迁移与验证（渐进、可回滚、有退出标准）

**第 0 步（半天，可逆）**：写一份 ADR，把“接缝模型 + 完成标准 + 延后触发条件”固化（含 `#1034/#1035`、`#4244`、`commits 5–8` 的链接）；同时修正 `CLAUDE.md` 架构图里 `contextIsolation:false + nodeIntegration:true` 的过时描述。

**第 1 步——首个垂直切片（推荐从文件保存/移动/重命名域切入）**：把 `mt::response-file-save`、`mt::rename`、`mt::window::drop`、`mt::save-tabs` 以及内部 channel `window-add-file-path`/`window-change-file-path`/`window-file-saved` 全部收紧类型、归一到统一注册助手。这一域是未来文件工作流最会碰的地方，也是当前 legacy handler 最密集处。
- **验证**：`pnpm typecheck` 通过且 `IpcSendChannels` 该域无 `unknown`；现有 `application-menu-state.spec.ts`、`buffer-store-durable.spec.ts`、`flush-before-save.spec.ts` 保持绿。
- **回滚**：逐 channel revert；行为不变。

**第 2 步**：升级 `onInternalChannel` 为类型化内部总线（channel map + `TypedEmitter`），**先保持 channel 名不变**，只换类型约束。
- **验证**：emit/listen 签名漂移在编译期报错；watcher 与窗口相关单测/ e2e（`tabs.spec.ts`、`launch.spec.ts`）不回归。

**第 3 步**：把“开文件索引”收敛到 `WindowManager`（`windowId → {rootDirectory, openedFilePaths}`），`EditorWindow` 只更新索引、不再被 `App` 直接扫 `_openedFiles`。
- **验证**：`findBestWindowToOpenIn` 抽出纯函数单测；e2e 多窗口打开用例不回归。

**第 4 步**：抽取纯数据常量（`MARKDOWN_EXTENSIONS`、`IMAGE_EXTENSIONS` 等）为无 `fs`/`path` 依赖模块，让 main 与 preload 共享；`isSamePathSync` 语义差异写成显式注释或统一到“preload 兜底 + main 权威判定”。
- **验证**：一个断言两处扩展名列表恒等的单测。

**第 5 步**：为“延后抽象”各写一条 revisit 条件（触发即开 ADR）：第三个窗口类型 / 第二个项目来源 / 引擎运行时切换 / in-place 更新版本分叉。

**通用退出标准**：`src/main/ipc/*` 之外零裸 `ipcMain.on/handle/send`；内部总线 channel 全类型化；契约中无 `unknown`（或剩余 `unknown` 有明确 issue 跟踪）；沙箱金丝雀测试仍绿。

## 8. 待定决策（答案会改变建议的问题）

1. `commits 5–8` / `Stage 3/4/5` 的迁移计划文档在哪？如果它已定义与本文不同的收口顺序，应以它为准（**未知，需补**）。
2. 近期是否有具体的第二个窗口类型或第二个项目来源（Git 仓库/云端/多根）在路上？有则方案 C 的“工作区模型”应提前立项（**未知**）。
3. `isSamePathSync` 两处语义差异是否在某个平台造成了实际 bug？决定第 4 步是“统一”还是“仅记录”（**未知，最便宜的验证是读相关 issue**）。
4. 自动更新是否计划支持“下载后当前运行窗口直接切换版本”？决定 IPC 版本化是否值得提前做一条最小 ADR（**未知**）。

[EVAL:evolve-software-architecture-loaded]
