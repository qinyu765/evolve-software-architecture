# 范围与结论

本次仅做只读静态评估，未修改文件、创建提交或运行可能产生构建产物的测试。对代码边界的判断置信度较高；跨窗口运行时行为和性能预算仍属未知。

结论：建议保留当前 Electron 拓扑，进行“边界提取式演进”，不建议整体重写，也不建议把实时文档状态集中到主进程。

保留：

- Electron main 负责窗口、原生对话框、文件系统和 watcher。
- 每个编辑器窗口拥有独立 renderer。
- renderer store 负责标签页、脏状态、光标和恢复状态。
- Muya 保持浏览器/DOM 编辑引擎，CodeMirror 作为源码模式编辑器。

调整重点应放在“文档会话、路径身份、保存和监听”的所有权，而不是 Electron 与 renderer 的整体拆分。

## 可观察事实

- 文档已经将 main 定义为 IO/窗口控制层、renderer 定义为编辑器和数据同步层，每个窗口拥有独立 renderer。[ARCHITECTURE.md:30](/evaluation-path/treatment/packages/website/content/docs/dev/ARCHITECTURE.md:30)
- renderer 已经启用 `contextIsolation`、`sandbox`，并关闭 `nodeIntegration`；这一边界还有专门的 E2E canary。[config.ts:8](/evaluation-path/treatment/packages/desktop/src/main/config.ts:8)、[context-isolation.spec.ts:24](/evaluation-path/treatment/packages/desktop/test/e2e/context-isolation.spec.ts:24)
- `EditorWindow` 同时维护窗口文件列表、路径去重和 watcher 注册；`WindowManager` 又维护全局窗口活动顺序和 watcher 实例。[editor.ts:50](/evaluation-path/treatment/packages/desktop/src/main/windows/editor.ts:50)、[windowManager.ts:85](/evaluation-path/treatment/packages/desktop/src/main/app/windowManager.ts:85)
- 保存流程由 renderer store 发出原始 IPC payload，再由 `menu/actions/file.ts` 执行写盘，随后通过内部事件更新窗口路径和 watcher。该文件自身明确留下了“保存应移动到 editor window”的重构 TODO。[editor store:512](/evaluation-path/treatment/packages/desktop/src/renderer/src/store/editor.ts:512)、[file.ts:36](/evaluation-path/treatment/packages/desktop/src/main/menu/actions/file.ts:36)
- 文件保存本身已有较好的数据安全基础：编码、换行符和 BOM 在 main 处理，写盘使用原子且持久化的 `write-file-atomic`。[markdown.ts:90](/evaluation-path/treatment/packages/desktop/src/main/filesystem/markdown.ts:90)、[filesystem/index.ts:25](/evaluation-path/treatment/packages/desktop/src/main/filesystem/index.ts:25)
- watcher 每次 `watch()` 都创建一个独立的 chokidar 实例，并按窗口清理；同一物理文件在多个窗口打开时没有中央路径订阅表。[watcher.ts:197](/evaluation-path/treatment/packages/desktop/src/main/filesystem/watcher.ts:197)、[watcher.ts:355](/evaluation-path/treatment/packages/desktop/src/main/filesystem/watcher.ts:355)
- 路径身份存在多套规则：打开文件时会解析 symlink，renderer 使用 `isSamePathSync`，`EditorWindow` 的打开列表和 watcher 忽略逻辑仍有直接字符串比较。[filesystem/index.ts:12](/evaluation-path/treatment/packages/desktop/src/main/filesystem/index.ts:12)、[editor.ts:332](/evaluation-path/treatment/packages/desktop/src/main/windows/editor.ts:332)、[preload/index.ts:140](/evaluation-path/treatment/packages/desktop/src/preload/index.ts:140)
- Muya 已迁移到 `@muyajs/core`，renderer 中每个窗口创建一个 Muya 实例，标签页通过 store 与历史快照切换。[editor.vue:1785](/evaluation-path/treatment/packages/desktop/src/renderer/src/components/editorWithTabs/editor.vue:1785)
- 编辑器边界仍不稳定：桌面侧对 Muya 暴露了 `[key: string]: any`，本地声明文件解释为“包尚未提供构建后的类型”；同时 legacy `@marktext/muyajs` 依赖、旧 alias 和旧声明仍保留。[muya-core.d.ts:5](/evaluation-path/treatment/packages/desktop/src/types/muya-core.d.ts:5)、[desktop/package.json:62](/evaluation-path/treatment/packages/desktop/package.json:62)
- IPC 虽有统一类型表，但类型仍明确处于 `unknown` 迁移阶段，并且存在多套旧式/重复的窗口和文件 channel。[ipc.ts:10](/evaluation-path/treatment/packages/desktop/src/shared/types/ipc.ts:10)
- 近期历史连续处理了“保存前最后一个字符丢失”、原子写盘和 crash-recovery 持久化，说明数据安全是实际高频风险点，而不是纯理论问题。[flush-before-save.spec.ts:31](/evaluation-path/treatment/packages/desktop/test/unit/specs/flush-before-save.spec.ts:31)、[write-file-atomic.spec.ts:16](/evaluation-path/treatment/packages/desktop/test/unit/specs/write-file-atomic.spec.ts:16)

## 当前结构性摩擦

1. 文档生命周期的所有权分散

保存、Save As、重命名、关闭确认、路径变更和 watcher 抑制分别落在 store、菜单 action、`EditorWindow`、`WindowManager` 和 preload 之间。功能修改容易形成跨层改动，且错误处理和状态回写不是单一事务。

2. 多窗口缺少明确的“同一文件”语义

当前有窗口路由和 `openFilesInNewWindow` 偏好，但没有中央文档身份或冲突策略。两个窗口打开同一文件时，是否同步、提示、覆盖或允许独立编辑并未形成明确契约。

3. watcher 资源与文档身份耦合

watcher 按窗口注册，路径比较又不完全统一。推断风险包括重复 watcher、保存抑制失配、跨窗口外部变更处理不一致；这些是结构风险，不等于当前必现缺陷。

4. IPC 能力面过宽

preload 暴露了任意路径的 `readFile/writeFile/copy/move/unlink` 等低级能力。[preload/index.ts:158](/evaluation-path/treatment/packages/desktop/src/preload/index.ts:158)  
sandbox 仍然有效，但长期维护上，renderer 调用“文档能力”与调用“任意文件系统能力”没有清晰区分。

5. 编辑器适配层泄漏

Muya 的低层 `json-change`、真实 history 和桌面自定义 synthetic history 都在 `editor.vue` 里拼接。[editor.vue:1857](/evaluation-path/treatment/packages/desktop/src/renderer/src/components/editorWithTabs/editor.vue:1857)  
这使引擎升级、源码模式切换和 dirty tracking 互相牵制。

## 质量属性优先级

| 优先级 | 属性 | 建议目标 |
|---|---|---|
| P0 | 数据安全 | 保存前编辑不丢失；原子写、编码、换行和恢复状态保持不变 |
| P0 | 生命周期一致性 | 每个打开文件只有明确的身份、订阅者和关闭行为 |
| P1 | 边界可测试性 | 文档命令有稳定 request/response 和可断言错误，不再依赖 `unknown` payload |
| P1 | 安全能力面 | preload 优先暴露文档/窗口能力，而不是通用任意路径 IO |
| P2 | 性能 | 通过测量决定大文件、watcher 数量和多窗口资源预算；目前仓库没有足够证据证明性能已是瓶颈 |

## 方案比较

| 方案 | 当前代价 | 风险 | 长期结果 | 验证方式 |
|---|---:|---:|---|---|
| 维持现状 | 低 | 近期低，新增功能时累积风险高 | 继续依赖跨层事件和重复状态 | 继续增加回归测试，适合产品变化很少 |
| 增量提取边界（推荐） | 中 | 中，可逐步回滚 | 主进程保留 IO，但文档生命周期有单一服务；窗口只做路由 | 先迁移单一保存链路，再迁移 Save As/rename/watcher |
| 全量重写/集中式文档运行时 | 高 | 高 | 可支持协同编辑或强一致模型，但会重做窗口、恢复、编辑器适配 | 需要完整多窗口、崩溃、平台和性能矩阵；当前证据不足以支撑 |

## 推荐的目标边界

建议新增一个主进程 `DocumentService`，必要时再加一个只保存元数据和订阅关系的 `DocumentRegistry`：

- `DocumentService`：路径规范化、加载、保存、Save As、rename/move、编码/换行、错误映射。
- `DocumentRegistry`：canonical path、窗口/标签订阅、watcher 引用计数和外部变更分发。
- `WindowManager` / `EditorWindow`：窗口生命周期、焦点和命令路由；不再承载全部文件 IO。
- renderer store：标签页内容、dirty 状态、光标、编辑会话和恢复快照。
- renderer `EditorEngine` facade：屏蔽 Muya/CodeMirror 的低层事件和 history 差异。
- preload：逐步提供 `documents.*`、`windowControl.*`、`shell.*` 等能力 API，保留旧 `fileUtils` 作为迁移适配层。

不要简单地把现有文件 IO 全部塞进 `EditorWindow`；那会把菜单 God object 变成窗口 God object。应当把保存职责从菜单移出，但落到独立的文档服务。

## 迁移与验证

建议按以下顺序：

1. 先补齐当前行为基线：保存前 flush、编码/换行、原子保存、恢复、外部变更、关闭未保存标签。
2. 以“已有文件 Save”作为第一个垂直切片：保留 `mt::response-file-save` 作为兼容入口，但内部委托给 `DocumentService`。这是范围最小、数据安全收益最高的切片。
3. 再迁移 Save As、rename/move、关闭确认和 watcher 抑制。
4. 统一 canonical path，加入 symlink、大小写、相对/绝对路径测试，再决定跨窗口重复打开策略。
5. 将文档 channel 收紧为类型化 request/response，逐步移除 `ipcMain.emit` 式内部伪 IPC 和旧 channel。
6. Muya 包先提供正式构建类型，再用窄 facade 替代 `any`，最后删除 legacy 依赖和 alias。Parity scoreboard 中的 PG14 等未决语义应单独记录，不要借重构顺便改变行为。

验证矩阵应包含：

- 单元：路径身份、编码/BOM/EOL、错误映射、watcher 引用计数。
- 主进程集成：两个窗口打开同一文件、关闭窗口、第二实例 `--new-window`、外部修改、保存抑制。
- renderer：保存前 flush、dirty baseline、每标签 history、Muya/CodeMirror 切换。
- 打包 E2E：macOS/Windows/Linux 的文件关联、Save As、rename、崩溃恢复和权限错误。
- 性能：多窗口/多文件 watcher 数量、打开大文件内存和延迟；先测量再设预算。
- 回滚：旧 channel 只作为适配入口，迁移期间保持单一写盘路径；若新服务失败，回退入口绑定即可，避免新旧路径同时写文件。

## 待决策事项

- 同一文件跨窗口的产品语义：同步、独占、提示冲突，还是允许最后写入覆盖。
- 支持的最大文件大小与打开/保存延迟预算。
- symlink、大小写不敏感文件系统和网络盘的 canonical identity 规则。
- `@muyajs/core` 正式类型和 legacy `@marktext/muyajs` 的退出时间。
- 是否继续允许 renderer 使用任意路径的低级文件 API，以及 `webSecurity:false` 是否需要单独安全评估。

[EVAL:evolve-software-architecture-loaded]
