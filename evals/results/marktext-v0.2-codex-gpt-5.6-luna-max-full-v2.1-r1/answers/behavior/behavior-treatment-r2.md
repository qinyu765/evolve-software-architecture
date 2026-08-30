# 1. 范围与置信度

本次仅做只读审查，工作树保持干净，未修改文件、提交或执行可能产生缓存的构建/测试。核对了：

- 根目录与 `pnpm` workspace 配置、`packages/desktop` 和 `packages/muya`
- Electron main/preload/renderer 实现与配置
- 文件读写、watcher、窗口管理、恢复状态和 IPC 类型
- 单元测试、Playwright E2E、CI 配置
- `CLAUDE.md`、开发文档和 Git 历史

下文使用“事实”“推断”“未知”区分证据强度。事实主要来自当前代码和配置；历史事实来自 Git commit；推断是基于这些事实的架构判断。

# 2. 可观察事实

当前主链路可以概括为：

```text
CLI / OS / 菜单
    -> main App + WindowManager
    -> EditorWindow / 文件读写 / watcher / 恢复状态
    -> preload contextBridge + typed IPC
    -> renderer Pinia editor/project store
    -> Muya WYSIWYG 或 CodeMirror source mode
```

| 领域 | 可观察事实 | 架构含义 |
|---|---|---|
| 进程边界 | 当前窗口使用 `contextIsolation: true`、`sandbox: true`、`nodeIntegration: false`；preload 暴露受限 API。[config.ts](/evaluation-path/treatment/packages/desktop/src/main/config.ts:8)、[preload/index.ts](/evaluation-path/treatment/packages/desktop/src/preload/index.ts:1) | 这是已经验证过的安全边界，应视为长期不变量。 |
| 窗口 | `App` 负责打开路径和创建窗口；`WindowManager` 负责注册、活动窗口、关闭和 watcher 清理；当前主要是 `EditorWindow` 与 `SettingWindow`。[windowManager.ts](/evaluation-path/treatment/packages/desktop/src/main/app/windowManager.ts:85)、[app/index.ts](/evaluation-path/treatment/packages/desktop/src/main/app/index.ts:519) | 窗口生命周期已有明确 owner，但文件路由策略仍嵌在具体 EditorWindow 中。 |
| 文件工作流 | main 负责规范化路径、加载、原子写入和 watcher；renderer 负责 tab、编辑状态和保存前 flush。[markdown.ts](/evaluation-path/treatment/packages/desktop/src/main/filesystem/markdown.ts)、[watcher.ts](/evaluation-path/treatment/packages/desktop/src/main/filesystem/watcher.ts:14) | 权责方向基本正确，但缺少统一的文件领域接口。 |
| IPC | `ipc.ts` 被称为 single source of truth，但仍有大量 `unknown`、旧的未加前缀 channel、动态 response channel，以及 main 内部通过 `ipcMain.emit` 转发的路径。[ipc.ts](/evaluation-path/treatment/packages/desktop/src/shared/types/ipc.ts:1) | IPC 名称集中不等于领域契约已经稳定。 |
| 编辑器 | desktop 同时依赖 `@marktext/muyajs` 与 `@muyajs/core`；renderer 已使用新 Muya，但仍有 legacy alias、手写类型声明和兼容映射。[package.json](/evaluation-path/treatment/packages/desktop/package.json:62)、[muya-core.d.ts](/evaluation-path/treatment/packages/desktop/src/types/muya-core.d.ts:1) | package 边界是有价值的，但 engine API 尚未成为稳定的 desktop contract。 |
| 规模与测试 | `editor.ts` 约 2102 行、`editor.vue` 约 2133 行、`App` 约 853 行、`EditorWindow` 约 645 行。现有 E2E 覆盖较多，但 tabs 测试会访问 Pinia/Vue 内部状态；本次检索的 E2E 清单没有专门的多窗口路由测试。 | 主要风险不是缺少抽象数量，而是行为和状态集中在几个高耦合热点。 |

Git 历史也支持这一判断：

- `fa84fc00`、`b9409bc9`：sandbox、typed preload 和窄化 bridge 是有意建立的边界。
- `ab88a70a`：IPC contract 明确采用了“先枚举、后逐步收紧”的迁移策略。
- `efcaf0c2`、`d2f0028e`：Muya 迁移仍靠 compatibility adapter 和 parity scoreboard 推进。
- `c907b29c`：曾出现保存时 deferred editor change 尚未提交，导致丢失最后一次输入。
- `6c23b1ba`、`ac273f46`：随后分别补充了原子文档写入和 durable crash-recovery buffer。

文档本身存在滞后：`CLAUDE.md` 和 `ARCHITECTURE.md` 仍有 `src/muya`、旧 engine 结构描述，且 `CLAUDE.md` 中部分 sandbox 描述与当前 `config.ts` 和 E2E canary 不一致。因此文档应作为辅助证据，不能替代实现和测试。

# 3. 当前摩擦

1. 窗口、文件路由和 watcher 互相知道太多。

`WindowManager` 不仅管理窗口，还持有 watcher；`EditorWindow` 又维护 `_openedRootDirectory`、`_openedFiles`，并直接触发 `watcher-watch-*`、`watcher-unwatch-*` 内部 channel。未来增加预览窗口、搜索窗口、项目窗口或跨窗口文档时，路由逻辑会继续扩散。

2. 文件状态的“事实来源”分散。

main 持有磁盘内容、路径、watcher 和恢复存储；renderer 持有 tab 与编辑状态；Muya 又持有自己的 history、selection 和 document state。当前 `IFileState` 还混有 `cursor`、`blocks`、`history`、函数和多个 `unknown` 字段，不适合作为跨进程或长期持久化模型。[files.ts](/evaluation-path/treatment/packages/desktop/src/shared/types/files.ts:58)

3. IPC 目前更像兼容层，而不是稳定领域 API。

直接 `ipcMain.emit` 的内部转发、动态 response channel、旧新命名混用和 `unknown` 结构会降低新能力的可测试性。增加一个文件操作或 shell 能力，容易同时修改 main、preload、shared types、renderer store 和组件。

4. engine 边界仍由 `editor.vue` 承担大量翻译工作。

当前组件维护 Muya history、旧 selection 形状、synthetic history、source mode 切换和 legacy DOM 兼容。Muya 的 desktop 类型声明仍较宽松，parity scoreboard 中 PG14 仍是 `test.fail()`。[editor.vue](/evaluation-path/treatment/packages/desktop/src/renderer/src/components/editorWithTabs/editor.vue:113)、[PARITY_SCOREBOARD.md](/evaluation-path/treatment/packages/desktop/test/PARITY_SCOREBOARD.md:69)

5. package 级测试与 desktop consumer 测试不是同一个闭环。

`packages/muya` 有自己的单元、spec、E2E 和 circular check，但 desktop 的部分 CI 对 `packages/muya/**` 使用 `paths-ignore`。因此 engine 通过自身测试，不代表 desktop 的集成行为一定被验证。

# 4. 质量属性优先级

| 优先级 | 属性 | 对未来设计的约束 |
|---|---|---|
| 1 | 数据安全与一致性 | 保存顺序、外部修改、编码/换行、恢复状态必须优先于抽象整洁。 |
| 2 | 进程安全与生命周期正确性 | 不恢复 `nodeIntegration` 或 raw Electron；窗口身份应由 main 根据 `event.sender` 推导。 |
| 3 | 变更局部性 | 新文件能力不应同时侵入所有 store；engine 细节不应继续进入通用 `IFileState`。 |
| 4 | 可测试性 | 领域服务要能用 fake filesystem、fake watcher、fake BrowserWindow 测试，不只依赖打包后的 Electron E2E。 |
| 5 | 跨平台与性能 | 保留现有 macOS/Windows/Linux 构建矩阵；在移动大文本、history 或内容到 main/worker 前先建立性能基线。 |

# 5. 方案比较

## 方案 A：维持现状，局部加固

继续使用 `App + WindowManager + EditorWindow`，只补测试、类型和少量 bug 修复。

- 成本最低，现有行为最稳定，回滚几乎只是 revert。
- 对新增菜单、单个 shell API、小型窗口改动仍然合适。
- 不引入双路径或迁移期复杂度。
- 代价是文件路由、watcher、renderer state 和 engine adapter 的耦合继续扩大。
- 一旦出现第三种窗口、跨窗口共享文档或第二个 WYSIWYG engine，改动仍会扩散到多个高热点文件。

## 方案 B：保留当前进程边界，增加窄领域外观（推荐）

稳定现有 owner，只增加三个有明确职责的边界：

1. main 内增加 `FileWorkflow`/`DocumentIO`，只负责 canonical path、load/save、rename/move、watch 和 revision/conflict 信息；不持有 renderer 的 tab、cursor 或 undo model。

2. renderer 内增加 `EditorEngineHost`，先只包装当前 Muya 的实际需求，把 engine selection、history、change payload 和 export 适配移出 store。CodeMirror source mode 先保持独立，不强行假设它和 Muya 是同一种可替换 engine。

3. Electron shell 继续通过 capability-specific preload facade 暴露，例如 `file`、`windowControl`、`shell`、`updater`；不建立全局 IPC broker，也不新增 raw Electron 全局变量。

优点：

- 能把未来文件工作流和 engine 演进限制在较小范围。
- 保留现有 sandbox、窗口生命周期和 renderer 交互模型。
- 可以通过旧 channel 兼容、feature flag 或 adapter 做渐进迁移。
- 适合当前“一个 Electron runtime、两个主要窗口类型、一个新 Muya consumer”的现实规模。

成本和风险：

- 中等，需要短期同时维护旧 channel 与新 facade。
- 如果 facade 只是改名而没有明确 owner，复杂度不会真正下降。
- 必须避免把完整 `IFileState` 直接变成 IPC DTO。

回滚：

- 保留旧 handler 和旧 channel。
- 新 facade 初期包裹现有 `loadMarkdownFile`、`writeMarkdownFile` 和 watcher。
- 不改变 buffer store 的磁盘 schema。
- 按操作逐个切换，单个操作失败时可切回旧路径。

## 方案 C：中心化 Workspace/Document 服务与通用窗口插件架构

让 main 持有全局 workspace、document session、可能包括 history；renderer 只做投影；同时建立通用 `WindowDescriptor`、插件注册和 engine provider。

优点：

- 适合真正的跨窗口共享文档、多 root workspace、后台索引、大文档 worker 或多个 editor provider。
- 长期可以统一窗口和文档生命周期。

代价和风险最高：

- 需要跨 IPC 传递更多内容、history、selection 和增量变更。
- 顺序、撤销、恢复、冲突和窗口关闭语义会显著复杂化。
- 迁移期间会有 main 与 renderer 双重状态，回滚困难。
- 当前仓库没有足够证据表明这些需求已经存在。

因此 C 应作为需求触发后的第二阶段架构，而不是当前的基础重构目标。

# 6. 建议

应稳定的是“责任边界”，不是当前所有类名：

- main：Electron lifecycle、窗口 identity/lifecycle、canonical path、文件 IO、watcher、持久化和恢复机制。
- preload：经过验证、可序列化、按 capability 划分的 bridge。
- renderer：tab、project、layout、用户交互和编辑器投影。
- Muya：纯编辑器/文档引擎，不依赖 Electron 或文件系统。
- IPC/shared types：只放跨进程 DTO，不放 renderer action、engine history 或 reactive store。
- WindowManager：继续是窗口注册和生命周期唯一 owner，但暂时不抽象成通用插件系统。

应延后的抽象：

- 通用窗口插件注册表、复杂 window factory：等第三种真实窗口类型出现后再做。
- 全局 `Workspace`/`Document` aggregate：等跨窗口共享文档或多 root 语义明确后再做。
- 可替换 engine provider/marketplace：当前只有一个 Muya WYSIWYG consumer；先做一个明确的 host adapter。
- 全局 shell port、IPC event bus 或 DI 容器：当前只有 Electron runtime，按 capability 增加 typed facade 即可。
- 把整个编辑器模型移动到 main、worker 或共享进程：先有性能基线和明确需求。

特别建议不要让 renderer 传入的 `windowId` 成为权限依据。对于“当前窗口发起的操作”，main 应从 `event.sender` 解析窗口；只有应用级路由才允许显式 target window。

# 7. 渐进迁移与验证

1. 建立基线，不改变行为。

   记录当前打开、编辑、保存、外部修改、恢复、关闭和多窗口策略；补充一份真实架构文档，明确 `packages/muya`、sandbox 和状态 owner。现有文档中的旧 engine 与旧 sandbox 描述应先纠正。

2. 先引入可序列化文件 DTO。

   建议包含 `DocumentRef`、canonical path、encoding、line ending、disk revision、save result 和 structured error。不要包含 cursor、history、函数或整个 `IFileState`。新 contract 初期保留旧 channel 作为兼容入口。

3. 选一条纵向路径迁移。

   优先迁移“打开一个文件 → 输入最后一个字符 → 保存/另存为”。必须验证：

   - flush 顺序仍然保证最后一次输入被保存；
   - 原子写入、编码、换行和 trailing newline 不变；
   - 错误可恢复且不会覆盖错误文件；
   - 新旧路径产生相同的可观察结果。

4. 再统一 watcher、rename、move 和 external-change 事件。

   事件至少应带 document identity、path、change kind 和 revision。renderer 决定“自动 reload、提示冲突还是保留 dirty 状态”，main 不应承担 UI 决策。确认新路径覆盖后，再删除内部 `ipcMain.emit` watcher 兼容路径。

5. 建立 `EditorEngineHost`。

   先把 Muya 的 change、selection、history、export 和 set-content 适配从 `editor.vue`/store 中移出；补齐 `@muyajs/core` 的公开类型。保留 legacy engine 依赖，直到 `rg`、typecheck、build 和 E2E 都证明没有调用方。

6. 只有出现真实触发条件时扩展窗口抽象。

   若新增第三种窗口，才引入带类型和 capability 的 `WindowDescriptor`/factory；若只是新增一个 shell 菜单或 API，直接沿用现有 main → preload → renderer 路径。窗口能力变更必须先增加 multi-window E2E，覆盖 `--new-window`、`openFilesInNewWindow`、同一路径重复打开和关闭恢复。

7. 验证门槛。

   未来每个阶段至少应覆盖：

   - 静态：`pnpm --filter marktext typecheck`、lint、`build:unpack`；Muya 自身 test、build、circular check。
   - 单元：文件 DTO、路径规范化、编码/换行、原子保存、watcher coalescing、窗口路由和 IPC serialization。
   - E2E：context isolation、last-keystroke save、external reload、crash recovery、关闭未保存文件、多窗口路由、source/WYSIWYG undo。
   - CI：让 `packages/muya` 改动触发至少一组 desktop consumer integration test，而不是只运行 Muya package tests。
   - 性能：在把内容、history 或大型文档移入 main/worker 前测量启动时间、大文件加载、保存延迟、IPC payload 和恢复时间。

不改变的后果是：短期小功能仍然便宜，且现有行为风险较低；但未来窗口、文件和 engine 功能会继续同时修改多个高耦合文件，重复出现保存时序、外部修改、兼容映射和测试隔离问题。方案 B 能以中等成本降低这种扩散，同时保留可回滚路径。

# 8. 仍需决策的问题

这些需求无法从当前仓库可靠推断，但会决定是否升级到方案 C：

- 同一文档是否必须同时在多个窗口编辑？
- workspace 是窗口级，还是未来需要全局共享、多 root？
- 是否计划支持第二个 WYSIWYG engine、worker engine 或非 Electron runtime？
- 外部文件修改与保存冲突的产品语义是什么？
- 大文档、启动、恢复和 IPC payload 的性能预算是多少？
- Electron shell 能力是否需要权限模型、插件模型或跨 runtime 兼容？
- 多窗口行为是否需要跨平台完全一致？

本次未修改代码、未创建提交；结论基于当前实现、配置、测试、文档和 Git 历史证据。

[EVAL:evolve-software-architecture-loaded]
