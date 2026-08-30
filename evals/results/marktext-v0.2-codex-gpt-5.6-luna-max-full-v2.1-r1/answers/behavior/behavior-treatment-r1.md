## 结论

建议采用“窄 seam、渐进收敛”的方案 B：保留现有 Electron main/preload/renderer、Pinia 和 Muya renderer-local 模式，只在窗口、文件工作流、编辑器宿主、Electron 能力桥之间补充语义边界。暂不进行完整 Clean Architecture、VFS、通用窗口框架或主进程编辑器状态化。

本次只读检查了实现、配置、文档、测试定义和 Git 历史；未执行可能写入缓存/产物的测试。工作树当前为 clean detached HEAD。

## 当前真实结构与主要摩擦

[事实] monorepo 根目录主要是工作区编排，Electron 应用集中在 `packages/desktop`，编辑器引擎分别是遗留的 `packages/muyajs` 和当前的 `packages/muya` / `@muyajs/core`。[root package.json](/evaluation-path/treatment/package.json:1) [desktop package.json](/evaluation-path/treatment/packages/desktop/package.json:1)

当前文件流大致是：

```text
CLI/OS 文件事件
  → main App
  → WindowManager / EditorWindow
  → loadMarkdownFile
  → webContents IPC
  → renderer Pinia editor store
  → Muya 或 CodeMirror

保存：
renderer flush
  → mt::response-file-save
  → main/menu/actions/file.ts
  → writeMarkdownFile
  → atomic write
  → watcher 忽略自身事件
```

几个边界目前明显混合：

- `App`、`WindowManager`、`EditorWindow` 分别承担启动路由、窗口选择、文件加载、打开文件集合和 watcher 协调；`WindowManager` 直接持有 `Watcher`，并通过 `BrowserWindow.id` 关联 watcher。[windowManager.ts](/evaluation-path/treatment/packages/desktop/src/main/app/windowManager.ts:85) [watcher.ts](/evaluation-path/treatment/packages/desktop/src/main/filesystem/watcher.ts:35)
- 文件保存仍在菜单动作文件中处理，源码自己标注未来应迁移到 editor window。[file.ts](/evaluation-path/treatment/packages/desktop/src/main/menu/actions/file.ts:21)
- `IFileState` 同时包含路径、dirty 状态、游标、Muya block、history、通知回调等 renderer 状态，却又被定义为跨进程/缓冲状态的公共形状。[files.ts](/evaluation-path/treatment/packages/desktop/src/shared/types/files.ts:62)
- IPC 的 channel 名称已集中，但参数仍大量是 `unknown`；保存、关闭、重命名等操作仍以宽泛的 raw IPC 形式暴露。[ipc.ts](/evaluation-path/treatment/packages/desktop/src/shared/types/ipc.ts:1)
- renderer 的沙箱边界是真实存在的：`contextIsolation: true`、`sandbox: true`、`nodeIntegration: false`，且有 E2E canary。[config.ts](/evaluation-path/treatment/packages/desktop/src/main/config.ts:8) [context-isolation.spec.ts](/evaluation-path/treatment/packages/desktop/test/e2e/context-isolation.spec.ts:24)
- 但 preload 同时暴露了通用 `ipcRenderer`、大范围 `fileUtils`、`path`、shell 等能力；当前 filesystem IPC 直接接受任意路径。[preload/index.ts](/evaluation-path/treatment/packages/desktop/src/preload/index.ts:158) [fs.ts](/evaluation-path/treatment/packages/desktop/src/main/ipc/fs.ts:40)

[事实] Muya 已经有相对清晰的公共 facade：`Muya`、Markdown/state 类型、插件和 `replaceContent` 等 API；桌面 renderer 已切换到 `@muyajs/core`，但仍使用手写声明和大量 `any`。[muya.ts](/evaluation-path/treatment/packages/muya/src/muya.ts:272) [muya-core.d.ts](/evaluation-path/treatment/packages/desktop/src/types/muya-core.d.ts:45)

Muya history 与桌面 dirty tracking 已经被迫分开：renderer 同时维护 `engineHistoryByTab` 和 synthetic history；CodeMirror 源码模式又有独立的 cursor/content handoff。[editor.vue](/evaluation-path/treatment/packages/desktop/src/renderer/src/components/editorWithTabs/editor.vue:294) [sourceCode.vue](/evaluation-path/treatment/packages/desktop/src/renderer/src/components/editorWithTabs/sourceCode.vue:1)

Git 历史验证了这是实际摩擦，而非静态代码印象：

- `565bfcdc`：monorepo 拆分；
- `efcaf0c2`：桌面迁移到 `@muyajs/core`；
- 随后的多个 parity 修复；
- `5d3d2819`：为源代码模式引入 `replaceContent`；
- `c907b29c`：修复保存前未 flush 导致最后一个字符丢失；
- `6c23b1ba`、`ac273f46`：文档保存和 crash-recovery buffer 的 atomic/durable write；
- `af6d792f`：忽略内容未变化的 watcher 事件。

这说明“文件安全、窗口生命周期、引擎历史”应视为高风险边界。

## 应稳定与应延后的边界

| 领域 | 现在应稳定 | 现在应延后 |
|---|---|---|
| 窗口 | 语义上的 `WindowId`、持久 `restoreBufferId`、生命周期、active/close handshake；明确 BrowserWindow id 只是运行时实现细节 | 通用窗口插件框架、复杂继承层级、统一 `WindowService` |
| 文件工作流 | 主进程负责路径规范化、编码/换行、atomic save、watcher、外部变更和冲突结果；renderer 负责用户意图和视图状态 | 完整 VFS、远程 provider、URI repository、event sourcing |
| 编辑器 | `@muyajs/core` 公共入口、renderer-local editor host、应用层只依赖 markdown/cursor/revision/dirty 等语义 | 把 Muya 和 CodeMirror 强行抽成同一个 editor engine；立即更换引擎 |
| Electron shell | sandbox、contextBridge、能力分组、主进程持有 Electron API；新功能使用窄的 typed facade | 扩大 raw `ipcRenderer`、通用跨进程 event bus、shell plugin marketplace |
| 持久化 | 缓冲状态有版本号、迁移和向后兼容；编辑器状态与恢复状态分离 | 把完整 renderer/engine state 直接当公共协议 |

特别建议稳定两个 ID：

```text
runtimeWindowId = BrowserWindow.id，短生命周期
windowSessionId = restoreBufferId，持久恢复身份
```

当前实现已经有这两个概念，但很多 watcher、IPC 和窗口逻辑仍偏向 runtime id。[editor.ts](/evaluation-path/treatment/packages/desktop/src/main/windows/editor.ts:139)

## 方案比较

### A. 维持现状，只加测试和约定

成本最低，短期性能和回滚性最好，适合只增加小型 UI 或单窗口能力。

代价是后续功能继续修改 `App`、`EditorWindow`、`WindowManager`、`editor` store、watcher 和菜单 IPC。跨边界事件顺序、窗口 id、dirty/history 仍会重复出现问题。回滚简单，但长期维护成本会累积。

### B. 窄 seam 渐进收敛（推荐）

保留当前运行时结构，只新增四个语义层：

- `WindowSession`：包装窗口生命周期、active 状态、runtime/session ID；
- `DocumentFileService`：包装 load/save/save-as/rename/move/watch/conflict；
- `EditorHost`：包装 Muya 的 flush、content、selection、replace、revision；CodeMirror 作为独立 source surface；
- capability-specific preload facade：文件、窗口、shell、clipboard 各自拥有窄 API。

优点是保留编辑器在 renderer 的本地性，避免每次输入都跨 IPC；同时让新窗口和新文件流程不再直接依赖 BrowserWindow、raw IPC 或 Muya block tree。

成本是迁移期间存在 adapter 和旧 channel 的双层结构。主要风险是新旧状态不同步，因此每个垂直切片必须只有一个实际写入者。回滚路径清晰：保留旧 IPC 作为兼容入口，将旧入口重新路由到旧实现即可。

### C. 完整拆分为 app-core / document-core / electron-shell

可将领域逻辑、文件 provider、Electron shell 和 renderer 完全分离，适合未来出现多 shell、远程文件、跨窗口共享同一文档、协作或插件沙箱的情况。

当前证据不足以证明需要它。代价包括序列化编辑状态、重新定义 undo/history、更多 IPC 延迟、持久化 schema 和进程故障恢复。大规模迁移的回滚困难，且可能重新引入刚通过 parity 修复的问题。

## 推荐路线

1. 先冻结不变量：atomic save、保存前 flush、外部变更处理、dirty baseline、窗口关闭确认、buffer recovery、sandbox。现有测试定义已经覆盖这些风险，包括 `flush-before-save`、atomic write、durable buffer、content-identical watcher、source undo/saved indicator。

2. 先做文件工作流垂直切片。用一个主进程 `DocumentFileService` 包装现有 `loadMarkdownFile`、`writeMarkdownFile` 和 `Watcher`，但暂时让旧的 `mt::response-file-save` 等 channel 作为兼容 adapter。新语义应返回明确的 `SaveResult`、`FileNotFound`、`ExternalConflict`、`PathChanged`，而不是只发送 tab id 和错误字符串。

3. 再抽取窗口 session。保留 `WindowManager` 的 BrowserWindow map，把 active、lifecycle、close policy 和 `restoreBufferId` 提升为独立元数据。新增窗口类型先复用这个协议，不要先设计通用窗口插件系统。验证 second-instance、`--new-window`、best-window routing、settings singleton、active menu 和 close-with-unsaved。

4. 在 renderer 内建立 `EditorHost` seam。Muya adapter 负责 Muya history/block/state；CodeMirror adapter 负责 source text/cursor。应用 store 只保存 `DocumentSnapshot`、`EditorViewState` 和 host-owned revision，不再把 raw engine history、block tree、通知函数放进跨进程类型。`IFileState` 可暂时兼容，但新协议不应继续扩大它。

5. 最后收窄 Electron 能力桥。新能力只通过专用 facade 暴露，例如 `fileWorkflow.save()`、`windowControl.close()`、`externalShell.openUrl()`；保留 raw `ipcRenderer` 供旧代码迁移。新增窗口必须复用 sandbox 和 navigation/webview 拦截策略。

6. 只有满足以下任一条件，才考虑方案 C：第二种文件 provider、跨窗口共享同一文档、协作/远程编辑、第二种 shell/runtime、或实测表明当前 renderer-local 模型无法达到大型文件性能目标。

每一步都应保留旧入口、使用 additive 的持久化 schema，并用 contract tests 验证新旧入口结果一致。不要双写文件或双重注册 watcher。

## 未决问题

[未知] 当前没有足够证据确定产品未来是否需要远程文件、同文档多窗口、协作或插件沙箱；这些需求会决定是否值得做 VFS 或主进程 document session。

[未知] `loadMarkdownFile` 是整文件读取，尚未看到明确的大文件性能目标；应先测量打开/保存 P95、renderer 内存、IPC payload 大小和 watcher 数量，再决定是否引入流式/worker。

[文档风险] `CLAUDE.md` 仍写着 editor/preferences 使用 `contextIsolation:false + nodeIntegration:true`，与实际配置和沙箱 E2E 相反；旧 `ARCHITECTURE.md` 也描述了迁移前的根目录结构。[CLAUDE.md](/evaluation-path/treatment/CLAUDE.md:241) [ARCHITECTURE.md](/evaluation-path/treatment/packages/website/content/docs/dev/ARCHITECTURE.md:1)

此外，`PARITY_SCOREBOARD.md` 仍写 PG14 是 xfail，但当前测试已去掉 `test.fail()`，且 Git 提交 `5d3d2819` 明确实现了 `replaceContent`。因此在未来迁移前，应先确定哪个测试/文档源是权威，不能仅依赖旧 scoreboard。[PARITY_SCOREBOARD.md](/evaluation-path/treatment/packages/desktop/test/PARITY_SCOREBOARD.md:69) [parity-source-undo-saved.spec.ts](/evaluation-path/treatment/packages/desktop/test/e2e/parity-source-undo-saved.spec.ts:73)

不改变现状不会立即导致架构失效，但会让每个新能力继续穿透多个中心模块；现在做小范围语义收敛，成本和回滚风险都明显低于未来一次性重构。

[EVAL:evolve-software-architecture-loaded]
