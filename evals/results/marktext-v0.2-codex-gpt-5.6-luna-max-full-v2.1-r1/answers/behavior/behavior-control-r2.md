结论：建议采用“运行时维持现状 + 新能力增量加窄 façade/port”的路线。现在不宜把主进程改造成统一的文档、标签和编辑器状态中心；也不宜立即设计通用编辑器插件 ABI 或完整 IPC 重写。

这里的“稳定”指行为和责任边界稳定，不代表现有类名、目录或 IPC channel 永久不变。

## 审计得到的现状

- monorepo 目前主要是物理组织边界。`packages/desktop` 仍同时依赖旧 `@marktext/muyajs` 和新 `@muyajs/core`，[Vite 仍保留 `muya -> ../muyajs` alias](</evaluation-path/control/packages/desktop/electron.vite.config.ts:34>)。Git 提交 `565bfcdc` 主要是目录移动和 root script proxy，不应把 package 目录直接等同于领域边界。
- Electron 安全边界已经比较明确：`contextIsolation: true`、`sandbox: true`、`nodeIntegration: false`。[实际配置](</evaluation-path/control/packages/desktop/src/main/config.ts:8>)、[preload 说明](</evaluation-path/control/packages/desktop/src/preload/index.ts:1>)和 [context-isolation E2E](</evaluation-path/control/packages/desktop/test/e2e/context-isolation.spec.ts:24>)一致。但 preload 仍暴露通用 `ipcRenderer`、较宽的 `fileUtils` 和大量 `unknown`；[IPC contract 自己也明确写着仍在迁移](</evaluation-path/control/packages/desktop/src/shared/types/ipc.ts:10>)。`webSecurity: false` 应视为待收敛的安全债务，不应成为新能力的依赖。
- `WindowManager` 同时管理 BrowserWindow、活动窗口、菜单、watcher 和 buffer store，[职责已经较宽](</evaluation-path/control/packages/desktop/src/main/app/windowManager.ts:85>)。但标签、项目树和编辑器状态仍是每个 renderer 本地状态；`EditorWindow` 还额外使用稳定随机 UUID 保存 buffer，[说明 BrowserWindow.id 不能承担持久身份](</evaluation-path/control/packages/desktop/src/main/windows/editor.ts:139>)。
- 文件语义已经集中在 main：路径规范化、symlink 解析、编码/BOM、LF/CRLF、尾换行、原子且 fsync 的保存，以及 per-window chokidar watcher。[markdown 读写](</evaluation-path/control/packages/desktop/src/main/filesystem/markdown.ts:46>)、[原子写入](</evaluation-path/control/packages/desktop/src/main/filesystem/index.ts:25>)和 [watcher](</evaluation-path/control/packages/desktop/src/main/filesystem/watcher.ts:197>)不应被 renderer 或编辑器引擎绕过。
- renderer 的 `editor.ts` 是当前最大耦合点：它同时协调 Pinia、文件保存、watcher、buffer、TOC、Muya、CodeMirror、关闭确认和菜单。[`EditorState`](</evaluation-path/control/packages/desktop/src/renderer/src/store/editor.ts:139>)和 [文件变更处理](</evaluation-path/control/packages/desktop/src/renderer/src/store/editor.ts:1650>)都证明了这一点。`IFileState` 还混合了持久数据、光标、历史、DOM/block 状态和 UI notification，[并不是真正的跨进程 DTO](</evaluation-path/control/packages/desktop/src/shared/types/files.ts:62>)。
- Muya 迁移已经证明“兼容适配 + 行为测试”比一次性替换更可靠。当前 `editor.vue` 仍将 Muya 实例声明为 `any`，[使用 synthetic history、selection adapter 和 `replaceContent`](</evaluation-path/control/packages/desktop/src/renderer/src/components/editorWithTabs/editor.vue:172>)；CodeMirror 源码模式仍是独立编辑器，[靠事件和手工状态交接](</evaluation-path/control/packages/desktop/src/renderer/src/components/editorWithTabs/sourceCode.vue:97>)。
- 文档和测试追踪存在漂移：`ARCHITECTURE.md` 仍描述旧的 JS Muya 和“需要 core refactoring”[内容](</evaluation-path/control/packages/website/content/docs/dev/ARCHITECTURE.md:20>)；scoreboard 仍说 PG14 是 xfail，但当前 E2E 源码已是普通 `test` 并明确写“FIXED”[内容](</evaluation-path/control/packages/desktop/test/e2e/parity-source-undo-saved.spec.ts:73>)。因此架构判断应优先基于实现、测试源码和 Git 历史，而不是旧文档。

## 应稳定的边界

| 边界 | 应稳定的责任 | 当前约束 |
|---|---|---|
| main / preload / renderer | main 负责 OS、文件、watcher、BrowserWindow、原生菜单；renderer 负责 UI、标签、DOM 编辑器 | 新能力不得直接在 renderer 引入 Electron/Node；只通过 typed、sender-scoped capability |
| 窗口身份与路由 | main 是窗口生命周期和打开路径路由的权威方 | 将 BrowserWindow.id 视为短期传输 ID；逐步明确 `WindowSessionId`，与 buffer UUID、TabId 分离 |
| 文件持久化 | canonical path、编码、BOM、换行、原子保存、外部变更和冲突语义 | 新流程必须复用 main 文件服务；不要向 renderer 或 Muya 增加通用文件写权限 |
| 文档状态 | 文件内容/文件元数据与视图状态、光标、撤销栈分离 | 不再把 `IFileState` 或 `blocks` 作为新的跨进程通用模型 |
| 编辑器引擎 | `@muyajs/core` 保持 DOM/浏览器侧、Electron-free，以 `src/index.ts` 为公共入口 | OT、block tree、DOM node、真实 engine history 不跨 IPC |
| 测试边界 | Muya package 测引擎，desktop unit/E2E 测宿主接线，跨边界行为两边都测 | 当前 CI 对 `packages/muya` 使用独立 workflow，未来 API 变化仍需触发 desktop integration 检查 |

Electron shell 能力建议按 `window`、`shell`、`file-dialog`、`filesystem/document`、`clipboard` 等能力分组。保留旧的通用 `mt::fs::*` 作为兼容面，但新代码不要继续扩大它；新 API 应使用明确 DTO、明确错误和明确的调用方窗口。

## 应延后的抽象

1. 主进程统一的 `DocumentManager`、全局 Workspace、跨窗口共享 Tab/Undo 栈。
2. 包含 Muya 和 CodeMirror 全部能力的通用 `IEditorEngine`。
3. 把 Muya plugin registry、OT 状态或 block tree 变成应用级插件 ABI。
4. 全量 IPC channel 重命名或一次性删除 legacy bridge。
5. 仅因为 monorepo 存在就把 desktop 拆成大量 service packages。
6. 协作/CRDT。Muya 的 OT 数据结构是潜在基础，不是当前产品的共享文档协议。

应优先做的是小而明确的契约：`DocumentRef`、`LoadResult`、`SaveRequest`、`FileRevision`、`ExternalChange`，以及 renderer 内部的 `MuyaEditorHost` / `SourceEditorHost`。不要把这些契约扩展成一个包含所有 UI、历史和插件的“大一统模型”。

## 方案比较

| 方案 | 质量属性与成本 | 风险、回滚 | 不采用它的后果 |
|---|---|---|---|
| A. 维持现状，只加强边界纪律 | 交付最快、性能最好、改动成本最低；保留现有测试和行为 | 低风险，回滚几乎不需要；但 `editor.ts`、WindowManager、raw IPC 会继续膨胀 | 新窗口、文件冲突和引擎替换会继续通过 path string、bus、`unknown` 拼接，长期正确性和可测试性下降 |
| B. 增量 façade/port，保留旧路径兼容 | 中等成本；提高安全性、可测试性和演进能力；会有短期双模型和序列化开销 | 每次只迁移一个流程，旧 channel 作为 adapter 保留，可按功能开关回滚；最大风险是 façade 重新变成 God Object | 不会立即失效，但每个新功能都会加深现有耦合 |
| C. 主进程统一窗口/文档/session authority | 跨窗口一致性、冲突控制和未来多视图能力最好 | 成本最高；每次编辑都增加 IPC/序列化，DOM、光标和撤销栈迁移困难；回滚最复杂 | 暂时不能支持同一文档跨窗口共享编辑或协作，但单窗口/多独立窗口模型仍然安全 |

推荐：现在采用 A 的责任约束，并在文件流程、窗口身份、编辑器宿主三个热点逐步采用 B。C 只有在明确需要“同一文档多窗口共享状态、分屏多视图或协作”时才启动。

## 可验证的渐进路线

1. **基线阶段**  
   建立 channel、Electron import、文件写入、引擎 import 和 `unknown` 的清单；先修正文档/scoreboard 漂移。基线测试包括 [sandbox E2E](</evaluation-path/control/packages/desktop/test/e2e/context-isolation.spec.ts:24>)、[外部 reload/undo](</evaluation-path/control/packages/desktop/test/e2e/external-reload-undo.spec.ts:44>)、原子写入、buffer durable 和 Muya parity。  
   验收标准是行为基线不变，而不是先改目录。

2. **传输和窗口身份阶段**  
   为新增 API 引入显式 `WindowSessionId` 和 sender-scoped routing；新 channel 禁止裸 `unknown` 和任意文件路径操作。旧 channel 通过兼容 adapter 保留。  
   验证 context isolation、typecheck、窗口关闭/恢复/菜单目标和多窗口打开路径；失败时只关闭新路由，回退到当前 `WindowManager`。

3. **文件流程阶段**  
   在 main 内包住现有 `loadMarkdownFile`、atomic write 和 watcher，形成窄的 `DocumentIO`/`FileRevision` 契约；renderer 的 Pinia 状态暂时不迁移。  
   验证 UTF-8/BOM、UTF-16、LF/CRLF、混合换行、symlink、父目录被删除后保存、同内容外部改写不告警、不同内容 reload/undo、未保存冲突和 buffer restore。新旧路径必须产生相同结果。

4. **引擎宿主阶段**  
   先让 `@muyajs/core` 发布真实 built typings，再在 renderer 内引入 `MuyaEditorHost`；`editor.ts` 不再直接依赖 Muya 内部 history/block 形状。CodeMirror 使用独立 `SourceEditorHost`，保留 source-mode 的单步 `replaceContent`、光标和 scroll 语义。  
   验证 `packages/muya` 单测/spec/E2E、desktop parity E2E、图片拖拽/剪贴板人工 QA；确认无 runtime legacy import 后，才按历史迁移计划删除 `@marktext/muyajs`、alias 和 ambient declarations。

5. **窗口能力阶段**  
   先迁移一个真实能力，例如“在指定窗口打开文件”或一个辅助窗口，验证活动窗口、菜单目标、未保存关闭、恢复和跨窗口路径路由。只有当该阶段稳定，才拆分 WindowManager 内部的 registry、routing、watcher ownership。

6. **可选的统一 authority 阶段**  
   若产品确实需要同一文档跨窗口共享，再引入 main-side document coordinator。它只应先负责文档 revision、保存串行化和冲突，不负责 Muya DOM、光标或撤销栈。必须保留按 feature flag 回退到当前 renderer-local tabs 的路径。

本次仅做了只读审计；未修改文件、创建提交或执行会产生构建/缓存的测试。收尾的 `git diff`、暂存区 diff 和工作树状态核验退出码为 0，未发现本次产生的差异。
