本轮仅做只读核对：未修改文件、未提交、未改变外部状态。

## 结论

建议采用“保留现有进程/package 分层 + 增量增加窄适配层”的方案。现在不宜一次性引入通用 `WindowService`、VFS/Repository、跨引擎 `EditorEngine`、统一 RPC/Event Bus 或 Electron 插件系统。

当前结构足以支持“本地 Markdown + 多标签 + editor/settings 两类窗口”，但未来功能应先稳定所有权与语义，再逐步收敛实现。

## 当前事实与主要风险

- 实际 monorepo 已包含 `desktop`、legacy `muyajs`、TS 版 `muya` 和 `website`；根目录脚本主要代理到 desktop。[pnpm-workspace.yaml](/evaluation-path/control/pnpm-workspace.yaml:1) [desktop/package.json](/evaluation-path/control/packages/desktop/package.json:55)

- Electron 安全边界实际是 `contextIsolation: true`、`sandbox: true`、`nodeIntegration: false`，并有对应 E2E canary；根文档后段仍写着相反的旧配置，开发文档也仍使用旧的 `src/` 目录描述。因此文档目前不能作为唯一架构事实来源。[config.ts](/evaluation-path/control/packages/desktop/src/main/config.ts:8) [context-isolation.spec.ts](/evaluation-path/control/packages/desktop/test/e2e/context-isolation.spec.ts:5) [CLAUDE.md](/evaluation-path/control/CLAUDE.md:241) [ARCHITECTURE.md](/evaluation-path/control/packages/website/content/docs/dev/ARCHITECTURE.md:1)

- `WindowManager` 同时管理窗口注册、活动窗口、菜单、watcher、buffer store 和打开文件评分；`EditorWindow` 又直接负责加载文件、维护路径列表和 watcher。它是可用的应用控制器，但还不是通用窗口平台。[windowManager.ts](/evaluation-path/control/packages/desktop/src/main/app/windowManager.ts:85) [editor.ts](/evaluation-path/control/packages/desktop/src/main/windows/editor.ts:50)

- 文件工作流横跨 main、preload 和 renderer：main 负责 Markdown 解析、保存和 watcher，但 sidebar 的创建、复制、移动、删除直接调用宽泛的 `window.fileUtils`。[project.ts](/evaluation-path/control/packages/desktop/src/renderer/src/store/project.ts:211) [preload/index.ts](/evaluation-path/control/packages/desktop/src/preload/index.ts:158)

- IPC 类型文件被设计为迁移期的“宽松契约”，并且仍混有 renderer→main 公共频道和 main 内部 `ipcMain.emit` 频道；例如 `window-file-saved` 的契约参数是 `tabId`，内部实现却按 pathname 处理。[ipc.ts](/evaluation-path/control/packages/desktop/src/shared/types/ipc.ts:1) [ipc.ts](/evaluation-path/control/packages/desktop/src/shared/types/ipc.ts:183) [windowManager.ts](/evaluation-path/control/packages/desktop/src/main/app/windowManager.ts:457)

- 编辑器迁移已基本完成，但消费边界仍有 `any`、手写声明、synthetic history，以及 Muya 与 CodeMirror 两套状态协调。[muya-core.d.ts](/evaluation-path/control/packages/desktop/src/types/muya-core.d.ts:5) [editor.vue](/evaluation-path/control/packages/desktop/src/renderer/src/components/editorWithTabs/editor.vue:172) [editor.vue](/evaluation-path/control/packages/desktop/src/renderer/src/components/editorWithTabs/editor.vue:289)

Git 历史也呈现出同一趋势：`565bfcdc` 先保留 legacy engine 并为 future muya-v2 留位置；`fa84fc00` 建立 sandbox 边界；`ab88a70a` 明确 IPC 类型先宽后紧；`efcaf0c2` 迁移引擎后又通过 parity scoreboard 和多个修复提交收敛行为。最近的 `c907b29c`、`6c23b1ba`、`ac273f46`、`af6d792f` 又分别修正了保存竞态、原子持久化和 watcher 误报。

## 应稳定的边界

| 领域 | 应稳定的边界 | 当前不应冻结的内容 |
|---|---|---|
| package/process | `packages/desktop` 拥有 Electron、OS、窗口和文件策略；`packages/muya` 保持纯编辑器包，不依赖 Electron/Node shell；renderer 承载 UI、Pinia 和 live editor | 根目录共享“大而全”的应用层；legacy `muyajs` 兼容层的内部 API |
| 安全 | main 是 native capability 的权威；renderer 无 Node 直接访问；preload 只暴露显式能力 | 继续扩展通用 `ipcRenderer`、raw fs、raw shell；现有 `webSecurity:false` 应视为需审查的例外，而不是新默认 |
| 窗口 | BrowserWindow 创建、关闭、活动窗口和 OS open-file 路由归 main；每个窗口保留独立 renderer | 把 `BrowserWindow.id` 当作持久身份；建立通用窗口插件/布局平台 |
| 文件 | 保留绝对路径、本地文件 identity、编码/BOM、LF 内部表示、EOL/trailing newline 保存语义、watcher 稳定等待、原子持久化 | 把完整 `IFileState`、Muya block tree、history 直接冻结为跨层领域协议；这些类型仍明确处于开放迁移状态。[files.ts](/evaluation-path/control/packages/desktop/src/shared/types/files.ts:1) |
| 编辑器 | Muya 通过其公开 entrypoint 被 desktop 消费；Electron 能力通过 callbacks/options 注入；live engine 状态留在 renderer | 现在就定义可支持任意引擎的完整 `EditorEngine` 抽象；当前 Muya 与 CodeMirror 的 history/selection 语义尚未完全同构 |
| IPC/shell | 新能力使用领域化、可序列化、按 sender 绑定的 DTO；internal main 事件与 renderer IPC 分开 | 统一所有事件、命令和 IPC 为一个总线；当前 command callback 仍是 `any`，internal IPC 也有独立 helper。[commands/index.ts](/evaluation-path/control/packages/desktop/src/main/commands/index.ts:7) [internalIpc.ts](/evaluation-path/control/packages/desktop/src/main/utils/internalIpc.ts:4) |

文件层可以现在抽出一个很窄的 `DocumentIO` seam，但它应只是现有 `loadMarkdownFile`、保存选项、路径规范化和 watcher 事件的适配层，不应立即升级为 VFS、URI、Repository 或云端工作区。

## 可行方案比较

| 方案 | 质量属性 | 成本 | 风险与回滚 |
|---|---|---|---|
| 0. 维持现状 | 当前本地 Markdown 功能风险最低，开发最快；窗口和文件能力继续依赖已有路径 | 初始成本最低，但每个新功能都要改 main/preload/renderer 多处 | 没有迁移风险；代价是 IPC 漂移、桥接面扩大、测试和文档债务继续增长。适合短期没有新文件源/窗口类型的情况 |
| 1. 保留现有分层，增加窄 capability facade（推荐） | 安全、可回滚性和增量交付最佳；可逐步降低 raw fs/raw IPC 使用 | 中低：新增 facade、契约检查、少量适配测试，不迁移持久化数据 | 旧频道和旧 buffer schema 保留；新 facade 出问题可关闭或回退到旧实现 |
| 2. 引入 main-side application/domain core | `WindowSession`、`DocumentIO`、路由策略和保存策略可单测，复杂窗口/多文件源扩展性最好 | 高：会同时维护旧状态、新状态、协议、持久化兼容和大量集成测试 | 最大风险是双重状态和 save/reload 竞态；必须并行运行、feature flag 切换，且不能先改写旧恢复数据 |

推荐方案 1。方案 2 只有在出现以下任一触发条件时才值得启动：

- 第二种有独立 dirty/save/restore 策略的窗口；
- 第二种文件源，例如远程、归档、虚拟或数据库文档；
- 同一文档需要跨窗口共享；
- 新功能需要跨多个 renderer 协调而现有 main 路由已经难以维护。

## 可验证的渐进路线

1. **契约盘点**

   建立实际频道矩阵：renderer 公共 IPC、main→renderer push、main 内部事件分别列出；以实现和测试为准修正文档。新频道必须有精确参数/返回类型，且不能把内部 `ipcMain.emit` 频道加入 renderer bridge。

   验收：新增功能不再直接增加 raw fs/raw shell；公共频道注册、类型和调用点一致；文档不再同时描述相反的 sandbox 配置。

2. **增加兼容 facade**

   先为 `document`、`project`、`window`、`shell` 提供窄接口，内部仍可调用旧 bridge。按“打开/保存/关闭 → sidebar 文件操作 → shell/window control”的顺序迁移，保留旧全局作为兼容层。

   验收：context-isolation E2E 继续通过；新调用点不直接使用通用 `ipcRenderer` 或 raw `fileUtils`；旧路径可被 feature flag 恢复。

3. **收敛 DocumentIO**

   保持当前加载/保存语义：编码、BOM、混合换行、trailing newline、原子/耐久写入和 watcher 自写忽略都不能改变。[markdown.ts](/evaluation-path/control/packages/desktop/src/main/filesystem/markdown.ts:66) [filesystem/index.ts](/evaluation-path/control/packages/desktop/src/main/filesystem/index.ts:25)

   增加 golden tests：大文件、编码/EOL、重命名、外部相同内容、外部不同内容、保存失败、崩溃恢复和同帧最后一个字符保存。已有提交和测试说明这些路径确实发生过数据正确性问题。[editor.ts](/evaluation-path/control/packages/desktop/src/renderer/src/store/editor.ts:503) [file-change-content-check.spec.ts](/evaluation-path/control/packages/desktop/test/unit/specs/file-change-content-check.spec.ts:25)

4. **收敛窗口路由**

   先把 `App`/`WindowManager` 中的“文件列表 → 目标窗口”评分策略做成纯函数测试；实际 BrowserWindow 生命周期仍留在 main。保持三种身份分离：临时 `BrowserWindow.id`、恢复用 `restoreBufferId`、renderer tab id。[editor.ts](/evaluation-path/control/packages/desktop/src/main/windows/editor.ts:139)

   验收：单实例、`--new-window`、macOS `open-file`、多文件、打开目录偏好、恢复多个 buffer、关闭未保存窗口全部通过。

5. **编辑器边界收敛**

   先让 `@muyajs/core` 可靠产出 built declarations，再删除 desktop 的手写 shim。之后只定义 desktop 当前真正需要的最小 host 接口：创建/销毁、读写 Markdown、flush、selection、history、外部变更和图片/文件 callbacks。

   不要先把 Muya 的 block/OT/DOM 暴露给文件工作流，也不要把 Muya 移到 main。以 Muya 单测、CommonMark/GFM conformance、desktop parity E2E 和 source-mode/外部 reload/dirty tests 作为迁移门槛。

   当前 parity 文档本身存在漂移：scoreboard 仍称 PG14 为 xfail，而同一仓库的测试源码已标注 fixed 且没有 `test.fail()`；[PARITY_SCOREBOARD.md](/evaluation-path/control/packages/desktop/test/PARITY_SCOREBOARD.md:44) [parity-source-undo-saved.spec.ts](/evaluation-path/control/packages/desktop/test/e2e/parity-source-undo-saved.spec.ts:73) 这类状态必须先同步，否则无法作为可靠质量门禁。

6. **最后处理 shell**

   保留 `openExternal`、`openPath`、`showItemInFolder`、窗口控制等窄方法；增加 URL scheme、路径存在性、危险可执行文件和 sender 归属校验。新 shell 能力不得暴露任意 Electron API、任意命令执行或任意 menu object。

   每个 shell 能力都应有 context-isolation E2E 和失败路径测试；已有 renderer sandbox 测试适合作为不可回归的安全 canary。[context-isolation.spec.ts](/evaluation-path/control/packages/desktop/test/e2e/context-isolation.spec.ts:24)

不改变也不是错误：如果未来仍只有本地 Markdown、editor/settings 两类窗口，维持现状的收益可能高于重构。但一旦继续直接添加频道、raw fs 方法和跨层状态字段，窗口路由、文件一致性、引擎迁移和 shell 安全会以乘法方式增加回归面，且回滚会从“关闭一个 facade”变成同时回退 main、preload、renderer 和持久化数据。
