我已经完成了对仓库的证据核查（文档、实现、配置、测试、可用历史）。下面是架构评审结论。

---

# MarkText 架构演进评审：窗口能力、文件工作流、编辑器引擎与 Electron shell

## 1. 范围与置信度

**仓库分类**：Electron 桌面应用（pnpm monorepo）。判定依据是多信号一致：`electron` ~42 依赖、electron-vite 5 构建、electron-builder 26 打包、`main/preload/renderer` 三进程入口、`packages/desktop/electron-builder.yml` 打包配置。置信度：**高**。

本次评审不修改代码，只回答一个问题：未来在**窗口能力、文件工作流、编辑器引擎、Electron shell 能力**四个方向上演进时，哪些边界应当稳定、哪些抽象应当延后。

一个重要的证据限制（事实）：本 checkout 的 `.git/logs/HEAD` 只有一条 clone 记录（`clone: from .../marktext`），没有增量历史可查；Bash 工具在本会话被禁用，无法执行 `git log`。因此"变更热点"只能从 prompt 提供的近期提交、源码内引用的 PR 编号（#4244/#4673/#3957/#3509/#3786/#3828/#3575/#4874/#4699/#4859/#3791/#4860 等）以及注释中的迁移标记推断，而非从完整历史统计。

---

## 2. 观察事实

| 结论 | 证据 | 类型 | 置信度 | 对决策的影响 |
|---|---|---|---|---|
| 三进程模型已硬化：renderer 完全沙箱化，Node 访问只经 preload 桥 | `packages/desktop/src/main/config.ts:11-51`（`contextIsolation:true, sandbox:true, nodeIntegration:false, webSecurity:false`）；`preload/index.ts:286-296` 用 `contextBridge` 暴露 `window.electron/fileUtils/path/...` | 事实 | 高 | 一切"shell/窗口/文件"新能力必须过这条缝，这是必须稳定的边界 |
| IPC 契约是"单一事实来源"，但类型迁移**未完成** | `shared/types/ipc.ts:1-18` 注释"Concrete types tighten ... in commits 5–8"；`shared/types/files.ts:1-5` "populated as call-sites convert to TS in subsequent commits"；大量 payload 仍 `unknown` | 事实 | 高 | 契约本身该稳定，但尚未收敛，先收口再谈扩展 |
| 大量 IPC 处理仍绕过契约，散落在业务类里 | `main/app/windowManager.ts:367-495`、`main/app/index.ts:658-850`、`main/dataCenter/index.ts:162-213`、`main/editorBufferStore/index.ts:214-218`、`main/menu/actions/file.ts` 直接 `ipcMain.on/handle` | 事实 | 高 | 改一条通道要同时动 3-4 处，且这些裸 handler 不被契约类型检查 |
| 存在两套通道约定 + 一种进程内转发机制 | `mt::` 前缀通道（`main/ipc/*.ts` 注册）vs 无前缀遗留通道（`update-buffer-state`、`language-changed`、`app-open-file-by-id`、`watcher-*`）；`main/utils/internalIpc.ts` 用 `ipcMain.emit` 做 main→main 进程内调度 | 事实 | 高 | 主进程内模块间耦合走的是一条伪装成 IPC 的隐式总线，新增窗口能力时最容易出错 |
| 窗口身份传递不一致 | 有的通道显式传 `windowId`（`IpcSendChannels` 里 `app-open-file-by-id`），有的从 `e.sender` 反查（`windowManager.ts:369-417` 的 `BrowserWindow.fromWebContents`），有的走 `onInternalChannel` | 事实 | 高 | 新窗口类型/多窗口路由会踩到同一个窗口两种身份的坑 |
| EditorWindow 与 renderer tabs 存在"打开文件"双份真相 | `main/windows/editor.ts:52-58` 的 `_openedFiles/_openedRootDirectory` 影子状态，与 renderer 的 `tabs` 各自维护 | 事实 | 高 | 文件工作流的改动要在两处同步，是已知的耦合源 |
| 文件写盘路径已经durable且归口清晰 | `main/filesystem/index.ts:25-49`（write-file-atomic + fsync + rename，注释引 #3509/#3786/#3828） | 事实 | 高 | 这条路径已经是好边界，不要重做，只把它作为稳定模块 |
| 文件工作流"保存/另存/导出"逻辑在 menu 模块里，不在 EditorWindow | `main/menu/actions/file.ts` 共 758 行；文件顶部 TODO（`:36-38`）明确写"save/save as should be moved to the editor window；renderer 只和 editor window 谈文件" | 事实 | 高 | 这是一个官方自认的、已经识别出来的错位，方案里应把它落地 |
| 编辑器引擎按**源码级**消费，类型是手写 `any` shim | `packages/muya/package.json:10-13` exports `.` → `./src/index.ts`；`types/muya-core.d.ts:16-17` 注释"Delete this file once @muyajs/core ships built lib/types"；`editor.vue:175` `type MuyaInstance = any` | 事实 | 高 | 引擎边界今天不是稳定契约，**正确做法是继续延后**，等引擎发布类型后再固化 |
| 旧引擎 muyajs 已实质退役但包还在 | grep 无任何 `from 'muya/'` 导入；仅剩 `types/muya.d.ts` 环境 shim + `package.json` 里 `@marktext/muyajs: workspace:*` | 事实 | 高 | 可以进入删除旧包的清理阶段，风险低 |
| 路径谓词/扩展名清单在两个进程重复维护 | `common/filesystem/paths.ts:8-20,106-166`（Node `fs`/`minimatch`）vs `preload/index.ts:115-156`（pathe 重实现），`MARKDOWN_EXTENSIONS`、`hasMarkdownExtension`、`isChildOfDirectory`、`isSamePathSync` 两处硬编码 | 事实 | 高 | 加一个扩展名（如曾经的 `.mdx`）要改两处，是真实的变化放大点 |
| 文档与实现部分脱节 | `website/content/docs/dev/ARCHITECTURE.md` 仍是 monorepo 前的 `src/` 布局且称"Muya 是 JavaScript"；`IPC.md` 实质准确但路径写 `src/` 而非 `packages/desktop/src/` | 事实 | 高 | 评审/新人以文档为锚会得到错误结构图，需修正 |
| 测试已有跨缝验证，但无 IPC 契约一致性测试 | `test/e2e/context-isolation.spec.ts`、`launch.spec.ts`、`ripgrep-search.spec.ts` 跨进程；`test/unit/specs/` 主要测纯函数；未见断言"main 侧裸 handler 与契约一致"的测试 | 事实 | 高 | 给"契约唯一化"配一个可执行的架构检查是低成本高回报 |

---

## 3. 当前摩擦（变化放大点）

按"改一处会波及几处"排序：

1. **IPC 半迁移状态**。契约已经存在且类型安全，但一半 handler 仍在契约之外裸注册。结果是：加一个窗口/文件通道，需要在 `ipc.ts`、preload 桥、`global.d.ts`、某个业务类的裸 `ipcMain.on` 四处改动，而后两处不被契约约束，类型错误漏网。

2. **窗口身份双轨 + 影子状态**。`windowId` 显式传递、`event.sender` 反查、`ipcMain.emit` 进程内转发三种方式并存；`EditorWindow._openedFiles` 与 renderer `tabs` 各自维护"本窗口打开了哪些文件"。未来做"多窗口/窗口合并/拆分窗口"时，这是最容易产生状态不一致的地方。

3. **文件工作流的归属错位**。保存/另存/导出对话框与写盘逻辑在 758 行的 `menu/actions/file.ts`，而窗口生命周期、watcher、buffer store 分属 `EditorWindow`/`Watcher`/`EditorBufferStore` 三个 owner。代码里已有 TODO 承认这个错位，说明维护者已知，只是没腾出手。

4. **跨进程逻辑重复**。扩展名清单与路径谓词在 preload（pathe）和 common（Node fs）各写一遍，是"改了 A 忘了 B"的典型来源。

5. **引擎边界是 `any` 且按源码消费**。这不是当下要"修"的摩擦，而是当前引擎仍在快速迭代下的**有意取舍**：`any` shim 把类型检查代价隔离在边界外，代价是引擎 API 误用只能在构建/运行期暴露。它应在引擎稳定后收敛，而不是现在收敛。

---

## 4. 质量属性优先级（本决策的支配属性）

| 排名 | 属性 | 目标/预算 | 当前证据 | 取舍 |
|---|---|---|---|---|
| 1 | 可维护性（局部性） | 任一未来变更能在单一 owner 内完成 | 见上文摩擦 1-4 | 为它排第一，意味着**不做**过早的通用抽象 |
| 2 | 进程边界稳定性 | IPC 契约是唯一通道面，新增通道零歧义 | 契约存在但半迁移 | 收口契约会短暂抬高改动成本（每次都要过契约） |
| 3 | 可测试性 | 能通过预期接口验证，不依赖打包运行时 | e2e 已跨缝，但缺契约一致性测试 | 补一个架构检查，而非大量 UI 测试 |
| 4 | 可扩展性 | 命名的变化点（第三种窗口/第二文件后端）能低摩擦加入 | 目前只有 EDITOR/SETTINGS 两种窗口、单磁盘后端 | **显式降级**：变化点尚未出现，不为假设变化点买单 |
| 5 | 成本 | 迁移可逆、不阻塞功能 | 迁移已在途（"commits 5-8"） | 每步可独立回滚 |
| 6 | 可运维性 | 崩溃恢复、原子写不退化 | 写盘路径已 durable | 保持预算，不重做 |
| 7 | 安全性 | 沙箱保持、导航/弹窗已拦截 | `webSecurity:false` 是宽豁免 | 记录为 ADR，不在本评审内改 |
| 8 | 可移植性 | Win/macOS/Linux 三平台不回归 | watcher/窗口代码有大量平台分支 | 作为约束进入验收 |

关键权衡：**可维护性 > 可扩展性**。这意味着我们拒绝"为未来三种窗口/两个文件后端预先搭框架"，而选择"先把已经存在的、负载最重的缝收口"。

---

## 5. 方案对比

### 方案 A：维持现状（继续零散演进，不专门收口）

保留当前形状：类型化 IPC 迁移按功能需求顺带推进，窗口/文件/引擎边界维持现状，仅修文档。

- **边界与所有权**：不变。IPC 契约继续与裸 handler 并存。
- **它解锁的改变**：无新增能力；功能开发照旧。
- **迁移/回滚成本**：最低（什么都不做），但每次新功能都按摩擦 1-4 重复付费。
- **运维与测试后果**：契约漂移继续，类型错误继续漏网。
- **会证明它错（或对）的证据**：如果团队接下来半年只做编辑器 bug 修复、不加窗口/文件/引擎能力，A 是合理的——但它不解决"未来加能力"这个已被提出的问题，所以对本次评审的问题而言，A 是"不改变的后果"基线，不是推荐项。

### 方案 B：现在引入通用抽象（窗口能力注册表 + 文件服务层 + 引擎插件化）

一次性抽出：`WindowType` 工厂/注册表（按类型分发创建、菜单、IPC）、`FileService`（open/save/watch/buffer 统一 owner，接口可插拔后端）、引擎适配层（把 `@muyajs/core` 包进版本化适配器）。

- **边界与所有权**：新增两层抽象，各自成模块。
- **它解锁的改变**：新窗口类型"注册即用"、文件后端可替换。
- **假设**：未来确实会有第三种窗口、第二个文件后端、独立发布的引擎——**这些目前都只是假设，没有证据**。
- **迁移/回滚成本**：高。一次大重构跨主进程、renderer、preload、测试四处；回滚需要整体回退，无法按切片回滚。
- **运维与测试后果**：抽象层自身需要维护与测试；在只有一种/两种实现时，接口会被唯一实现塑形（"过早泛化"），往往猜错方向。
- **会证明它错（或对）的证据**：只有当 roadmap 上**已经排期**了第三种窗口类型或第二文件后端时，B 才值得；否则它在为一个不存在的变化点预支复杂度。

### 方案 C（推荐）：选择性收口——稳定负载最重的缝，延后假设性抽象

不做新框架；做三件收敛 + 一处清理：

1. **把类型化 IPC 契约变成唯一通道面**（收口）：剩余裸 `ipcMain.on/handle` 全部迁入契约，废弃 `onInternalChannel`/`ipcMain.emit` 作为主进程内模块间调度（改为对 owner 类的直接类型化调用）。
2. **执行已有 TODO，把保存/另存/导出归入 `EditorWindow`**（文件工作流收口）：`menu/actions/file.ts` 退化为薄分发层。
3. **消除跨进程路径谓词重复**：抽一个唯一的 `markdown-extensions/path-predicates` 模块，主进程注入 Node `path`/`fs`，preload 注入 `pathe`（依赖注入路径库，而不是复制两份逻辑）。
4. **清理已退役的 `packages/muyajs`**：确认无 `muya/` 导入后删除旧包、`muya.d.ts`、`muya` 别名与 workspace 依赖。

- **边界与所有权**：IPC 契约、preload 桥、文件写盘模块、窗口注册表（WindowManager 已存在，只是收口身份约定）成为稳定边界；引擎源码级消费 + `any` shim 保持不变。
- **它解锁的改变**：任何未来的窗口/文件/引擎能力都在一个被类型检查、单一 owner 的面上进行。
- **假设**：引擎仍会继续快速演进（当前事实支持）；未来变化点是窗口/文件/引擎而非"需要可插拔后端"（尚无证据）。
- **迁移/回滚成本**：低到中。每步独立、可单 commit 回滚；无 schema/数据迁移（契约是加法式）。
- **运维与测试后果**：契约唯一化后可用一个架构检查（见第 7 节）持续防漂移；文件逻辑归口后 e2e 的 save/tab 用例继续兜底。
- **会证明它错（或对）的证据**：若 muya 近期发布内置 `lib/types`，则 shim 提前删除；若 roadmap 出现第二文件后端，则在**出现第二个实现时**才抽出 `FileService`，不是现在。

---

## 6. 建议：哪些边界稳定，哪些抽象延后

针对你点名的四个方向，逐条给出"稳定 / 延后"分类。

### 6.1 Electron shell 能力 —— **先稳定**（这是其余三者的地基）

**应当稳定：**
- **`shared/types/ipc.ts` 契约 = 唯一 renderer↔main 通道面**。四类通道（invoke/send/sync/main-event）已是对的抽象，不要再引入第五条路。把散落在 `windowManager.ts`、`app/index.ts`、`dataCenter`、`editorBufferStore`、`menu/actions/file.ts` 的裸 handler 全部收编，并弃用 `onInternalChannel`（它用 `ipcMain.emit` 做进程内调用，混淆了"进程边界"和"模块边界"两个概念——主进程内模块间应直接调用，不该伪装成 IPC）。
- **preload 桥是 renderer 的唯一 Node 出口**。保持"薄、显式、逐条暴露"的 facade 风格（现在的 `window.electron.* / window.fileUtils.* / window.path.*` 结构是对的），不泄漏 Electron 原始对象。
- **窗口身份只保留一种约定**：per-window 操作用 `event.sender` 反查；跨窗口操作用显式 `windowId`；两者由 `WindowManager` 这个已存在的注册表统一收口。消除 `EditorWindow._openedFiles` 与 renderer `tabs` 的"打开文件"双真相（二选一，建议以 renderer 为准、main 侧只做 watcher 生命周期）。

**应当延后：**
- 不要现在抽"窗口能力注册表/插件框架"（见 6.2）。
- 不要现在把 `webSecurity:false` 收紧——它是让本地 `file://` 图片/font/资源能加载的历史豁免，收紧需要单独的回归验证，不在本评审范围内；但**应补一条 ADR 记录这个安全取舍**。

### 6.2 窗口能力 —— **稳定 WindowManager 注册表，延后"窗口框架"**

**应当稳定：**
- `WindowManager` 已经是一个窗口注册表（`Map<number, BaseWindow>` + 活动列表 + `findBestWindowToOpenIn`）。把它明确为**唯一**的窗口生命周期/路由 owner，新增窗口类型只做三件事：`WindowType` 加枚举值、`BaseWindow` 加子类、`App` 加一个 `_create*Window`。目前 `findBestWindowToOpenIn`/`getActiveEditor` 里对 `EDITOR` 的硬编码特判可以保留——它是**领域知识**（"编辑窗口才有打开文件的路由语义"），不是抽象缺失。

**应当延后：**
- 不要现在建"窗口类型工厂 + 按类型分发菜单/IPC/选项"的通用框架。当前只有 EDITOR/SETTINGS 两种类型；**当第三种窗口类型（例如独立导出/预览窗口）真实进入 roadmap 时**，再抽出工厂，那时有至少两个具体变体来塑造接口，而不是靠想象。

### 6.3 文件工作流 —— **稳定写盘路径，归口"保存"owner，延后"文件服务"**

**应当稳定：**
- `main/filesystem/index.ts` 的 `writeFile`（write-file-atomic + fsync + rename）与 `main/filesystem/markdown.ts` 的 `loadMarkdownFile/writeMarkdownFile` 已经是 durable、注释清晰、事故（#3509/#3786/#3828）驱动的成熟边界。**保持主进程独占写盘**，不要搬到 renderer。
- `MarkdownDocument` 形状（`shared/types/files.ts`）作为跨进程文档载体稳定下来。

**应当归口（收口而非新建）：**
- 执行 `menu/actions/file.ts:36-38` 的 TODO：把保存/另存/导出的对话框 + 写盘决策迁入 `EditorWindow`，让 renderer 只和它的 editor window 谈文件。这消解"文件逻辑散在 menu/window/watcher/buffer 四个 owner"的摩擦。

**应当延后：**
- 不要现在抽"可插拔 `FileService`（虚拟 FS / 云同步 / 远程后端）"。当前只有一个磁盘后端，没有第二个 provider；等真需要第二个后端时再抽接口。`EditorBufferStore`（崩溃恢复用的每窗口 JSON）也维持现状，它已经是独立 owner。

### 6.4 编辑器引擎演进 —— **这是唯一"保持现状即正确"的方向，明确延后**

**应当稳定（现状即稳定）：**
- **源码级消费 `@muyajs/core`**（workspace dep + `exports` 指向 `./src/index.ts`）在引擎同仓快速迭代期是正确的：改引擎立即反映到桌面，省去发布/版本对齐。**不要现在改成"构建产物 + 版本化"**。
- muya 自带的 conformance 锁（`expected-failures.json`，符合率只能升不能降）是引擎边界最好的回归网，保留并继续依赖它。

**应当延后：**
- **不要现在固化引擎类型边界**。`muya-core.d.ts` 手写 `any` shim 是引擎稳定前的有意隔离层，等 `@muyajs/core` 发布内置 `lib/types/*.d.ts` 时删除 shim + `paths` 映射即可（文件头注释已写明删除条件）。在此之前不要把"给 Muya 写完整类型"当成前置任务。
- 不要现在给 muya 的 OT 能力接传输/冲突解决（协同编辑）。OT 状态层已就位，但没有任何传输层或冲突产品需求；这是最大的"假设性抽象"，最该延后。

**应当清理（低成本收尾）：**
- 删除 `packages/muyajs` 旧包、`muya.d.ts`、`muya` 别名与 `@marktext/muyajs` workspace 依赖——grep 已确认桌面源码无任何 `muya/` 导入，风险极低。

---

## 7. 迁移路线与验证（可逆、按切片）

每个阶段独立可回滚（单 commit 回退），不改变可观测行为。

**阶段 0 —— 先把漂移变成可见（零行为变化）**
- 枚举 `main/` 下所有 `ipcMain.on/handle/emit` 调用点，列出契约之外的通道清单。
- 加一个**架构检查脚本/CI 步骤**：扫描 main 进程源码，凡出现未登记进 `ipc.ts` 的 `ipcMain.handle/on` 通道名、或非 `mt::` 前缀的新通道，即失败。
- **验收**：`pnpm typecheck` + 该脚本在 CI 通过；得到一个"待迁入契约的通道"清单。

**阶段 1 —— 完成类型化 IPC 收口（逐通道、可回滚）**
- 把剩余裸 handler 逐条迁入契约：`ipc.ts` 加条目 → 在 `main/ipc/*.ts` 或对应 feature 模块用类型化 handler 实现 → 删除裸注册。
- 用 `onInternalChannel` 的调用改为对 owner 类的直接方法调用。
- **验收**：`pnpm typecheck` 全程通过（契约会标出每处不匹配的调用点，这正是 `IPC.md:98-99` 描述的用法）；`context-isolation.spec.ts`、`launch.spec.ts`、`ripgrep-search.spec.ts`、`tabs.spec.ts` 等跨缝 e2e 保持绿。

**阶段 2 —— 文件工作流归口 + 窗口身份收口**
- 把保存/另存/导出的对话框与写盘决策迁入 `EditorWindow`，`menu/actions/file.ts` 退化为薄分发。
- 统一窗口身份约定，消除 `_openedFiles` 与 renderer tabs 的双真相。
- **验收**：`save/tabs/export-pdf` 相关 e2e 绿；`menu/actions/file.ts` 行数显著下降且不再直接触碰窗口写盘。

**阶段 3 —— 清理旧引擎 + 去重**
- 删除 `packages/muyajs` 与 `muya` 别名；抽唯一路径谓词模块（Node `path` 注入 vs `pathe` 注入）。
- **验收**：`grep -r "from 'muya/'" packages/desktop/src` 无结果；`pnpm -C packages/desktop exec vitest run` + 全 e2e 绿；扩展名清单只在源码出现一次。

**阶段 4 —— 仅在证据出现后**
- 当**第三种窗口类型**或**第二文件后端**实际排期时，再抽窗口工厂 / `FileService` 接口；当 `@muyajs/core` 发布内置类型时删 `muya-core.d.ts`。这两个触发条件写进 ADR 的 revisit 条件。

**回滚路径**：阶段 1-3 的每一步都是加法式契约/纯重构，回滚 = 回退对应 commit；无数据 schema 迁移、无持久化格式变更。

**验证清单（贯穿）**：
- `pnpm typecheck`（契约一致性，编译期）
- 新增的架构检查脚本（防裸 `ipcMain` 漂移）
- 现有跨缝 e2e（进程边界行为）
- muya conformance 套件（引擎边界回归）
- 三平台打包冒烟（窗口/watcher 变更时，因为平台分支多）

---

## 8. 待决问题（答案会改变本建议）

1. **roadmap 上是否已有第三种窗口类型或第二文件后端？** 若已排期，6.2/6.3 的"延后"应立即翻转为"现在抽接口"（因为有了第二个真实实现可塑形）。
2. **`@muyajs/core` 是否会独立发布到 npm 并版本化？** 若会，源码级消费与 `any` shim 必须先于发布改变，6.4 的延后策略要重排。
3. **sandbox + `webSecurity:false` 是否继续作为长期取舍？** 这是一条值得 ADR 记录的安全边界；若未来要开 CORS/远程资源能力，它会成为关键约束。
4. **类型化 IPC 迁移的 owner 与带宽是否仍在？** 迁移已在途（注释 "commits 5-8"），若无人收尾，方案 C 的阶段 1 会长期悬置，A 的风险就会兑现。

---

**一句话结论**：把**类型化 IPC 契约、preload 桥、文件写盘路径、WindowManager 注册表**四条现有缝收敛为稳定边界并清理旧引擎，同时**明确延后**窗口插件框架、可插拔文件服务、引擎类型固化与协同传输——因为这些变化点目前都只有一个实现甚至没有实现，抽象会在被唯一实现塑形后猜错方向。

[EVAL:evolve-software-architecture-loaded]
