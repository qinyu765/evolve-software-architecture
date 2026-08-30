结论先行：建议保留“Electron main + 每窗口 renderer + renderer 内 Muya/CodeMirror”的进程拓扑，但对“文件会话、路径身份、保存事务、watcher 订阅和窗口路由”做窄范围结构调整。不建议把 Muya 移到 main，也不建议现在改成单一共享 renderer。

## 范围与置信度

审查范围为 `packages/desktop`、`packages/muya`、遗留 `packages/muyajs`、相关测试与开发文档。

- 静态拓扑、依赖和调用关系：高置信度。
- 运行时竞态、性能和跨平台行为：中等置信度；本次未运行测试。
- “同一文件是否允许在多个窗口同时编辑”等产品策略：未知，且会直接影响最终边界。

本次只读检查，没有修改文件、提交或改变外部状态。

## 观察事实

| 边界 | 可检查事实 | 判断 |
|---|---|---|
| Electron shell | BrowserWindow 使用 `contextIsolation: true`、`sandbox: true`、`nodeIntegration: false`；renderer 通过 preload 暴露 API。[config.ts](/evaluation-path/treatment/packages/desktop/src/main/config.ts:8) [preload/index.ts](/evaluation-path/treatment/packages/desktop/src/preload/index.ts:1) | 这是应保留的安全边界。 |
| 多窗口 | `WindowManager` 管理窗口、活动窗口和 watcher；`EditorWindow` 又维护 opened files、目录和恢复状态。[windowManager.ts](/evaluation-path/treatment/packages/desktop/src/main/app/windowManager.ts:85) [editor.ts](/evaluation-path/treatment/packages/desktop/src/main/windows/editor.ts:50) | 窗口生命周期与文件会话已经部分重叠。 |
| 文件 IO | 打开、保存、重命名分别由 `EditorWindow`、菜单 action、filesystem 和 renderer store 协作完成；菜单文件中还明确留下了“保存应移动到 editor window”的重构 TODO。[file.ts](/evaluation-path/treatment/packages/desktop/src/main/menu/actions/file.ts:36) | 文件事务的 owner 不够集中。 |
| watcher | watcher 按窗口注册，并在变化时重新读取完整 Markdown 后通过 IPC 发送；存在基于时间的 ignore 机制和历史遗留 HACK。[watcher.ts](/evaluation-path/treatment/packages/desktop/src/main/filesystem/watcher.ts:14) | 多窗口同文件时，冲突和重复订阅需要明确策略。 |
| 编辑器引擎 | renderer 直接创建 Muya，并把 `json-change` 转换成 Markdown、history、TOC、selection 等桌面状态；代码注明 Muya history 与桌面 dirty/save 模型不兼容，因此使用 synthetic history。[editor.vue](/evaluation-path/treatment/packages/desktop/src/renderer/src/components/editorWithTabs/editor.vue:1702) | Muya 是浏览器编辑器引擎，不应承担 Electron 职责；但当前 adapter 过厚。 |
| 类型与迁移 | desktop 同时声明 legacy `@marktext/muyajs` 和 `@muyajs/core` 依赖；当前引擎使用手写声明，含较多 `any`，同时保留旧 `muya` alias。[package.json](/evaluation-path/treatment/packages/desktop/package.json:1) [muya-core.d.ts](/evaluation-path/treatment/packages/desktop/src/types/muya-core.d.ts:1) | 引擎升级和遗留清理仍有边界成本。 |
| 数据安全 | 普通保存和 crash-recovery buffer 都已使用原子、耐久写入。[filesystem/index.ts](/evaluation-path/treatment/packages/desktop/src/main/filesystem/index.ts:25) [editorBufferStore/index.ts](/evaluation-path/treatment/packages/desktop/src/main/editorBufferStore/index.ts:31) | 底层写入方向正确，但还没有完整的文件版本/冲突模型。 |

当前主要数据流大致是：

`菜单/OS → App/WindowManager → EditorWindow → IPC → Pinia editor store → Muya/CodeMirror`

保存时又反向经过：

`Muya 延迟变更 → renderer flush → Pinia → menu action → filesystem → watcher ignore`

最近提交已经多次修补这个链路：保存前 flush、原子保存、耐久 buffer、外部文件变化和 TOC 恢复等。这说明问题不是单纯代码规模，而是跨边界时序较脆弱。[flush-before-save.spec.ts](/evaluation-path/treatment/packages/desktop/test/unit/specs/flush-before-save.spec.ts:1)

## 当前结构性摩擦

1. 窗口、文档和文件路径没有单一 owner。  
   main、renderer store、菜单 action、watcher 都持有部分文件状态；同一个路径可能同时表现为 main 的 opened file、renderer 的 tab、watcher 的订阅和 buffer store 的恢复对象。

2. 路径身份规则不统一。  
   部分 main 代码使用精确字符串比较，renderer 使用 `isSamePathSync`，filesystem 又会解析 symlink。大小写、UNC/WSL、symlink、重命名后可能出现“逻辑相同、系统认为不同”的情况。

3. 保存事务仍由 shell 菜单驱动。  
   renderer 必须先通过事件总线 flush 当前编辑器，再把内容交给 main 菜单处理。这个方向与文件生命周期 owner 分离，容易产生最后一个字符、关闭时序和 save-as 路径更新问题。

4. watcher 以窗口为中心，而不是以文件身份为中心。  
   同一文件若在多个窗口打开，当前模型是否允许最后写入覆盖、是否提示冲突、是否只 reload 未修改窗口，代码中没有看到统一的领域策略。

5. 编辑器 adapter 过厚。  
   `editor.vue` 和 `store/editor.ts` 同时处理引擎生命周期、tab、dirty、保存、外部 reload、undo、TOC、光标和 IPC。Muya 与 CodeMirror 还需要共享同一套桌面文档状态。

6. Electron API 仍偏底层。  
   preload 暴露了较宽的通用 fs/path API，IPC channel 的参数也有 `unknown[]`/`unknown` 过渡类型。[ipc.ts](/evaluation-path/treatment/packages/desktop/src/shared/types/ipc.ts:1) 这不立即构成运行时问题，但会让 renderer 逐渐了解 Node 文件系统细节。

## 质量属性优先级

1. 数据正确性与可恢复性：保存不丢字符、不静默覆盖外部修改、崩溃恢复一致。
2. 维护性：一个地方负责路径身份、文件事务和 watcher 订阅。
3. 可测试性与可观测性：多窗口、关闭、恢复、外部修改可以独立测试。
4. 安全与跨平台：继续保持 sandbox/preload，统一处理大小写、symlink、UNC、可执行文件和 watcher 差异。
5. 性能：避免多窗口重复读取大型文件、过多 watcher，以及 main 中同步 IO 扩散。
6. 迁移可逆性：结构调整期间可以逐步切流和回退。

## 方案比较

| 方案 | 成本 | 收益 | 主要风险 |
|---|---:|---|---|
| A. 维持现状，仅局部修补 | 低 | 交付快，行为变化小；适合继续修复保存和 watcher 边界 | ownership 继续分散；多窗口同文件、路径一致性和关闭竞态会反复出现 |
| B. 增加文件会话/文档 IO 协调层 | 中高 | 集中路径身份、open/save/rename/watch/close 事务；保留现有 renderer 和 Muya，迁移可分阶段 | 初期需要兼容旧 IPC；事件顺序和 close/save 迁移可能引入回归 |
| C. 把文档模型或编辑器集中到 main/共享 renderer | 很高 | 理论上可统一文档状态 | Muya 依赖 DOM 和 renderer 事件；会破坏窗口隔离、编辑器生命周期和 Electron 安全边界，收益与风险不成比例 |

建议选择 B。它解决的是文件系统和窗口会话的结构性问题，不改变 Muya 的运行位置。

## 建议的目标边界

保留：

- Electron main：窗口生命周期、OS 事件、对话框、文件系统、watcher、恢复存储。
- renderer：tab、选择区、undo/redo、Muya/CodeMirror、视图状态。
- Muya：纯浏览器编辑器引擎，不引入 Electron API。
- preload：窄而稳定的 typed domain API。

新增或逐步收敛：

- `FileIdentity/PathPolicy`：统一 canonical path、大小写、symlink 和目录关系。
- `Document/FileSessionCoordinator`：负责 `open/load/save/saveAs/rename/watch/close`，不持有 Muya DOM。
- renderer 内 `EditorEngineAdapter`：把 Muya 和 CodeMirror 都转换为统一的文档快照、flush、外部更新和选择区接口。
- 文件版本信息：保存和 watcher 事件携带 mtime/hash/version，而不是只依赖延迟和 ignore 时间窗口。
- 通用 fs API 与文档保存 API 分离。侧边栏仍可使用 workspace fs；编辑器保存应走文档事务 API。

## 可逆迁移顺序

1. 先写行为基线测试：多窗口打开、`--new-window`、second-instance、同一文件双窗口、save-as、rename、外部修改、未保存关闭、崩溃恢复。
2. 先抽取并复用路径身份规则，行为保持不变。
3. 抽取文件 IO 接口，底层继续复用现有原子写入实现。
4. 以一个垂直切片迁移：`打开 → 编辑 → flush → 保存 → watcher 回馈`，旧 IPC 暂时作为兼容适配器。
5. 再迁移 rename、move、close、restore 和冲突处理。
6. 新路径稳定后，再清理 legacy alias、`@marktext/muyajs` 依赖和手写 Muya 类型；不要提前删除。
7. 最后更新架构文档。目前文档与实际 sandbox 配置、monorepo 引擎状态存在不一致，应作为迁移收尾工作处理。[IPC.md](/evaluation-path/treatment/packages/website/content/docs/dev/IPC.md:1)

迁移期间应使用兼容路由或 feature flag；可以做 shadow observation，但不要新旧路径同时真实写文件。

## 验证方式

- 多窗口 E2E：不要只使用 `firstWindow()`；为每个 BrowserWindow 建立独立 page，并验证窗口数、目标窗口和 tab 状态。[helpers.ts](/evaluation-path/treatment/packages/desktop/test/e2e/helpers.ts:64)
- 文件一致性：大小写路径、symlink、UNC/WSL、重复 watcher、外部删除/修改、保存失败、rename 失败。
- 编辑器契约：Muya 和 CodeMirror 均验证 flush、undo、光标、TOC、source mode 与外部 reload。
- 数据安全：保留并扩展原子保存、buffer durable、保存前 flush 测试。
- 性能：1/5/20 窗口、多个大型 Markdown，测量打开/保存延迟、renderer 内存、main event-loop 延迟和 watcher 数量。
- 退出标准：同一文件的并发策略确定且可测试；路径只有一个身份实现；关闭后无 dangling watcher；保存没有静默覆盖；IPC domain payload 不再依赖无约束 `unknown`。

## 尚需决策的问题

这些问题应在结构调整前形成 ADR：

- 同一文件是否允许同时出现在多个窗口？
- 若允许，策略是阻止、只读、提示冲突、自动合并，还是明确采用最后写入？
- watcher 是按窗口独立订阅，还是按 canonical file 共享底层 watcher？
- buffer store、localStorage、electron-store 中哪些状态是窗口级，哪些是应用级？
- 当前 `@muyajs/core` 的源码导入和手写类型何时能由正式构建产物替代？

总体判断：维持现状适合短期修 bug；若 MarkText 要继续增强多窗口、恢复和本地文件可靠性，应优先建立“文件身份 + 文档会话 + typed renderer port”三条窄边界，避免一次性重写 Electron shell 或编辑器引擎。

[EVAL:evolve-software-architecture-loaded]
