## 结论

建议采用“保留现状边界 + 渐进式 façade/adapter”的方案。现在应稳定安全边界、窗口/文档身份、文件语义和编辑器宿主边界；应延后通用窗口框架、VFS/URI、可插拔编辑器 SPI、全局 Workspace Kernel 和插件权限系统。

本次基于 HEAD `e52106fd` 静态检查了文档、实现、配置、测试和 Git 历史；未修改文件、未提交、未执行测试或构建。

## 当前真实结构

- 根目录确实是 pnpm monorepo，包含 `packages/desktop`、`packages/muya`、`packages/muyajs`、`packages/website`。[根 package.json](/evaluation-path/control/package.json:2) [workspace 配置](/evaluation-path/control/pnpm-workspace.yaml:1)
- `packages/desktop` 运行时已使用 `@muyajs/core`，但仍保留 `@marktext/muyajs` 依赖、`muya/*` alias 和旧 ambient declarations，说明引擎迁移仍有过渡层。[desktop package.json](/evaluation-path/control/packages/desktop/package.json:62) [editor.vue](/evaluation-path/control/packages/desktop/src/renderer/src/components/editorWithTabs/editor.vue:113)
- Electron 安全边界目前是正确方向：`contextIsolation: true`、`sandbox: true`、`nodeIntegration: false`，renderer 通过 preload bridge 访问主进程。[config.ts](/evaluation-path/control/packages/desktop/src/main/config.ts:12) [preload/index.ts](/evaluation-path/control/packages/desktop/src/preload/index.ts:26)
- 窗口层由 `App`、`WindowManager`、`BaseWindow`、`EditorWindow` 共同负责；`WindowManager` 同时持有窗口注册表、活动窗口、菜单、watcher 和 buffer store。[windowManager.ts](/evaluation-path/control/packages/desktop/src/main/app/windowManager.ts:85)
- 当前已经区分了临时 `BrowserWindow.id` 和用于崩溃恢复的持久 buffer id，这是未来扩展窗口能力时应保留的身份分离。[editor.ts](/evaluation-path/control/packages/desktop/src/main/windows/editor.ts:139)
- 文件工作流仍是跨层分布的：renderer store 读取完整 `currentFile` 并发送保存请求，main 的 menu action 处理 dialog、写盘、watcher 和回传；代码自身也明确标注 save/save-as 应迁移到 editor window。[file.ts](/evaluation-path/control/packages/desktop/src/main/menu/actions/file.ts:36) [editor store](/evaluation-path/control/packages/desktop/src/renderer/src/store/editor.ts:512)
- 文件底层语义相对成熟：路径归一化、编码、BOM、EOL、尾换行、fsync + atomic rename 和 watcher 写入等待均在 main 侧实现。[filesystem/index.ts](/evaluation-path/control/packages/desktop/src/main/filesystem/index.ts:40) [watcher.ts](/evaluation-path/control/packages/desktop/src/main/filesystem/watcher.ts:231)
- 编辑器适配逻辑目前集中在 `editor.vue`：engine history 与 desktop history 双轨、selection payload 转换、source mode handoff、Electron image/clipboard 回调都在组件内。[editor.vue](/evaluation-path/control/packages/desktop/src/renderer/src/components/editorWithTabs/editor.vue:289) [selection adapter](/evaluation-path/control/packages/desktop/src/renderer/src/components/editorWithTabs/editor.vue:390)
- `@muyajs/core` 自己声明仍处于 active development，且 desktop 使用手写、宽松的 engine declaration。[Muya README](/evaluation-path/control/packages/muya/README.md:5) [muya-core.d.ts](/evaluation-path/control/packages/desktop/src/types/muya-core.d.ts:5)
- IPC 类型化是目标而非完全事实：契约仍大量使用 `unknown`，存在动态 response channel；`update-buffer-state` 的契约声明返回 `void`，实际 handler 返回 `boolean`。[IPC types](/evaluation-path/control/packages/desktop/src/shared/types/ipc.ts:10) [dynamic channel](/evaluation-path/control/packages/desktop/src/renderer/src/store/editor.ts:450)

Git 历史也支持“不要立即大重构”的判断：`565bfcdc` 刚完成 monorepo 拆分；`efcaf0c2` 的引擎迁移修改了约 522 行 editor 代码；`d2f0028e` 记录了 15 个 parity gap；之后又有 `c907b29c`、`6c23b1ba`、`ac273f46` 分别修复保存竞态、原子写入和崩溃恢复可靠性问题。

## 应稳定的边界

### 1. Main / preload / renderer 的安全边界

稳定规则：

- renderer 不直接获得 Node/Electron 能力。
- 新 shell 能力只能经 preload 暴露。
- 每个请求由 main 根据 `event.sender` 推导窗口，不信任 renderer 自带的 window id。
- 新 API 应按领域命名，例如文件对话框、文档保存、外部打开、剪贴板、窗口控制，而不是继续扩张通用 raw `fs` 或 raw IPC。
- 保留当前禁止 webview、导航和任意新窗口的策略；当前配置还有 `webSecurity: false`，因此不能把 sandbox 等同于完整安全隔离。

现有 context-isolation e2e 已把这条边界当作安全 canary。[context-isolation.spec.ts](/evaluation-path/control/packages/desktop/test/e2e/context-isolation.spec.ts:24)

### 2. Window、session、tab、path identity

建议明确保持四种身份：

- `WindowId`：当前 Electron window，短生命周期。
- `SessionId`：当前 buffer store，跨崩溃恢复。
- `TabId`：renderer 中的逻辑 tab。
- `PathKey`：归一化、解析 symlink 后用于比较和 watcher 的路径身份。

不要让 `BrowserWindow.id`、buffer store id 和 tab id 互相替代。未来增加预览窗口、比较窗口、设置窗口或第二个 editor window 时，窗口路由只处理 `WindowId/SessionId`，文档工作流只处理 `TabId/PathKey`。

### 3. 文件工作流语义

应稳定的不是当前 IPC 名字，而是以下不变量：

- 读取返回 markdown、编码、BOM、EOL、尾换行等完整文档快照。
- 保存保持 atomic + fsync、父目录恢复、权限和 symlink 语义。
- watcher 区分目录树变化、文件内容变化和自身保存回声。
- 外部变更必须区分“内容相同”“未修改文档”“有未保存修改”。
- save-as、rename、move 必须同时更新 tab path、window opened-file 集合和 watcher。

未来新流程应围绕 `open / save / saveAs / rename / move / reload / close` 这类语义命令设计，输入包含 tab/session/path/revision，而不是继续传递完整且混合 UI、engine、文档状态的 `IFileState`。当前 `IFileState` 明确混合了 history、cursor、scroll、notifications 和 engine blocks。[files.ts](/evaluation-path/control/packages/desktop/src/shared/types/files.ts:62)

### 4. Editor host boundary

建议稳定一个很小的 renderer 内部宿主边界：

- 输入：markdown、序列化 cursor、偏好和能力回调。
- 输出：content changed、selection changed、history/saved-state signal、capability request。
- engine 的 block tree、OT operation、内部 history 和 DOM reference 不进入文件工作流协议。
- `editor.vue` 中的 `adaptSelectionChange`、synthetic history、source-mode handoff 和 `json-change` 转换最终应归入 adapter。

但这不等于现在就定义完整的通用 editor SPI。当前 Muya 和 CodeMirror 的行为仍通过大量兼容逻辑衔接。[editor.vue](/evaluation-path/control/packages/desktop/src/renderer/src/components/editorWithTabs/editor.vue:1857) [sourceCode.vue](/evaluation-path/control/packages/desktop/src/renderer/src/components/editorWithTabs/sourceCode.vue:101)

## 应延后的抽象

- 通用 `WindowPlugin`、可插拔窗口层级、跨窗口 docking/workspace 框架：目前只有 editor/settings 两类窗口，且 WindowManager 还耦合 menu、watcher 和 buffer store。
- 通用 VFS、URI、云文档 provider：当前产品语义是本地 Markdown 路径，先稳定本地文件协议；真正出现远程文档需求时，再在文件工作流边界引入 provider。
- 完整 editor engine SPI 或新的领域文档模型：当前只有一个实际 WYSIWYG engine，且 `@muyajs/core` API 仍在演进。先做 desktop adapter 和 conformance tests。
- 把所有文档状态搬到 main 的全局 Workspace Kernel：这会同时改动 renderer Pinia、buffer store、窗口恢复、IPC 和外部变更处理。只有共享 tab、跨窗口实时协作或云同步成为明确需求时才值得做。
- 插件权限/Capability Registry：当前还没有第三方插件生态。先提供窄而明确的 shell façade，避免建立一套未使用的权限模型。
- 立即新建 `packages/desktop-core` 等公共包：monorepo 不代表每个概念都应马上拆包；只有出现第二个真实消费者、Electron-free 测试需求或 web/desktop 共享需求时再抽取。

## 可行方案比较

| 方案 | 质量属性 | 成本 | 风险与回滚 |
|---|---|---|---|
| A. 维持现状，只加约束 | 即时成本最低，性能和现有行为最稳定；但可维护性、类型可靠性和跨窗口可扩展性持续下降 | 低 | 每个功能容易实现，但会继续增加 global bus、`unknown`、全量状态 payload 和全局 IPC；回滚简单 |
| B. 渐进式语义 façade/adapter，推荐 | 在不改变现有运行时的前提下提高可测试性、数据正确性和变更隔离；增加一次 DTO 转换成本，通常可忽略 | 中 | 最大风险是新旧路径并存导致漂移；保留旧 channel、旧 buffer schema 和 fallback，可按功能关闭新路径 |
| C. Main-owned Workspace Kernel / 大重构 | 长期可能更适合共享文档、跨窗口协作、云 provider 和多 editor；短期会显著增加序列化、启动、状态同步和回归复杂度 | 高 | 涉及持久化、IPC、窗口恢复和 renderer ownership，回滚最困难；不适合当前需求不明确的阶段 |

A 适合只增加少量桌面功能。B 适合未来数个迭代持续增加窗口、文件流程和 shell 能力。C 应以明确的共享文档、协作或多引擎需求作为触发条件，而不是提前建设。

## 建议的渐进路线

1. **建立基线**

   先把当前行为列成不可破坏的合同：context isolation、窗口路由、tab 隔离、flush-before-save、atomic save、buffer durable、watcher external change、source-mode handoff。现有测试已经覆盖不少关键行为，例如保存刷新、原子写入、崩溃恢复、tab history 和外部 reload。[flush-before-save.spec.ts](/evaluation-path/control/packages/desktop/test/unit/specs/flush-before-save.spec.ts:99) [tabs.spec.ts](/evaluation-path/control/packages/desktop/test/e2e/tabs.spec.ts:226)

2. **先收紧新 IPC 和 shell 能力**

   保留旧 IPC 作为兼容层；新功能只使用窄 façade、严格 payload、明确错误/取消结果。动态 response channel 改为静态 channel + request id。不要一次性清理所有旧 `unknown`，只要求新增边界不再扩大它。

   验证重点：context isolation、sender-derived window routing、非法路径/外部打开、危险可执行文件链接、窗口控制和 clipboard capability。

3. **隔离文件工作流**

   在现有 `writeMarkdownFile`、`loadMarkdownFile`、watcher 和 menu handler 外包一层语义服务；旧 `mt::response-file-save` 等 channel 作为 adapter 继续工作。renderer 仍可保留 Pinia `IFileState`，但新流程不要直接依赖它。

   验证 save/save-as、untitled、rename/move、编码/EOL、外部修改、自动保存、同内容 mtime 变化和 watcher 清理。回滚时切回旧 handler，不改变现有 buffer store schema。

4. **隔离窗口路由**

   把当前 `_openPathList`、MRU scoring、`openFilesInNewWindow` 和 second-instance 处理归入一个明确的 `WindowRoute` 概念，但保留 `WindowManager` 和 `EditorWindow` 实现。不要先做通用窗口插件系统。

   当前测试树中没有专门的多窗口 e2e，应新增并验证：多窗口打开同一路径、重复 tab、目录归属、关闭 watcher、settings window、崩溃恢复和 second-instance。回滚时切回旧 `_openPathList`。

5. **最后抽出 editor adapter**

   在不切换 engine 的情况下，把当前 inline compatibility code 收拢到 adapter；`@muyajs/core` 仍是唯一运行时 engine。adapter 稳定后，再考虑移除旧 alias、旧依赖和手写 declaration。

   engine 迁移本身曾留下 15 个 parity gap，说明“换 engine”和“建立通用 SPI”不应放在同一次变更中。当前 parity 文档还声称 PG14 仍是 xfail，而现有测试注释已标记为 fixed，说明 parity 文档也应先恢复为单一事实来源。[PARITY_SCOREBOARD.md](/evaluation-path/control/packages/desktop/test/PARITY_SCOREBOARD.md:3) [parity-source-undo-saved.spec.ts](/evaluation-path/control/packages/desktop/test/e2e/parity-source-undo-saved.spec.ts:73)

## 不改变的后果

短期维持现状能最大程度保持当前行为，尤其是已经覆盖的保存、watcher、引擎 parity 和安全测试。

但继续不收敛会导致：

- 新窗口类型继续修改 `App`、`WindowManager`、menu、watcher、buffer restore 和 URL bootstrap。
- 文件操作继续在 renderer store、main menu、EditorWindow、watcher 之间传递完整可变状态，保存竞态和外部变更竞态会反复出现。
- Muya 演进继续把兼容逻辑堆在单个 Vue 组件中，并扩大 `any`、双 history 和 source-mode 特判。
- shell 能力继续依赖宽泛 raw fs、`unknown` payload 和动态 channel；sandbox 仍在，但 capability surface 会越来越难审计。
- 旧架构文档仍描述根目录 `src/` 和 JavaScript Muya，与实际 monorepo/TS engine 不一致。[ARCHITECTURE.md](/evaluation-path/control/packages/website/content/docs/dev/ARCHITECTURE.md:12)

因此，最合适的顺序是：先冻结安全与身份边界，再收敛文件工作流，随后隔离窗口路由，最后才抽取编辑器 adapter；完整的通用抽象等真实需求出现后再引入。
