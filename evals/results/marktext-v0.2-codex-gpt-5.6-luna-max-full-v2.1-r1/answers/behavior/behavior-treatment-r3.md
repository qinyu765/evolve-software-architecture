结论先行：MarkText 目前不需要“大爆炸”拆成窗口平台、文档仓库和通用编辑器框架。应立即稳定的是：

1. Electron 主进程 / preload / renderer 的权限边界。
2. 文件读取、编码、换行、原子保存、watcher 的数据不变量。
3. 窗口身份与生命周期。
4. `@muyajs/core` 作为浏览器编辑器引擎包的边界。

应延后的，是通用窗口插件注册表、引擎无关的“大一统编辑器接口”、事件溯源文档仓库，以及全量 IPC/RPC 重写。推荐“保持现有运行时拓扑 + 在真实高风险接缝处渐进加 adapter/port”。

## 1. 范围与置信度

本次基于当前 `HEAD e52106fd`、`develop` 同指向、干净工作树完成只读检查；未修改文件、未创建提交、未改变外部状态。检查了 monorepo 结构、desktop 实现、配置、开发文档、单测/E2E、CI workflow 和 Git 历史。测试源码已核对，但没有把静态检查冒充为本次实际运行结果。

对当前模块边界判断为高置信度；对未来产品需求（是否多窗口共享同一文档、是否接入远程文件）为未知。

## 2. 观察到的事实

| 事实 | 可检查证据 | 类型 / 置信度 | 架构含义 |
|---|---|---|---|
| 当前是 pnpm monorepo，desktop 同时声明 legacy 与新引擎依赖 | [`CLAUDE.md:35`](/evaluation-path/treatment/CLAUDE.md:35)、[`packages/desktop/package.json:62`](/evaluation-path/treatment/packages/desktop/package.json:62) | Fact / High | 包边界已经存在，但 legacy alias/dependency 仍是迁移债务 |
| renderer 的 sandbox 边界是真实运行时约束 | [`config.ts:8`](/evaluation-path/treatment/packages/desktop/src/main/config.ts:8)、[`context-isolation.spec.ts:5`](/evaluation-path/treatment/packages/desktop/test/e2e/context-isolation.spec.ts:5) | Fact / High | 这是最值得保留的稳定边界 |
| 窗口编排、窗口生命周期和文件路由分散在 `App`、`WindowManager`、`EditorWindow` | [`app/index.ts:477`](/evaluation-path/treatment/packages/desktop/src/main/app/index.ts:477)、[`windowManager.ts:85`](/evaluation-path/treatment/packages/desktop/src/main/app/windowManager.ts:85)、[`base.ts:15`](/evaluation-path/treatment/packages/desktop/src/main/windows/base.ts:15) | Fact / High | 当前两种窗口尚可，第三种窗口会放大耦合 |
| 文件工作流由 main、菜单、watcher 和 renderer store 共同拥有 | [`file.ts:157`](/evaluation-path/treatment/packages/desktop/src/main/menu/actions/file.ts:157)、[`markdown.ts:69`](/evaluation-path/treatment/packages/desktop/src/main/filesystem/markdown.ts:69)、[`editor.ts:512`](/evaluation-path/treatment/packages/desktop/src/renderer/src/store/editor.ts:512) | Fact / High | 不应把整个 `IFileState` 冻结为跨进程领域模型 |
| 新引擎实际使用 `@muyajs/core`，但 desktop 侧声明仍是宽松 `any` | [`editor.vue:172`](/evaluation-path/treatment/packages/desktop/src/renderer/src/components/editorWithTabs/editor.vue:172)、[`muya-core.d.ts:45`](/evaluation-path/treatment/packages/desktop/src/types/muya-core.d.ts:45) | Fact / High | 引擎边界概念上存在，物理上尚未封装 |
| IPC 只有部分类型化，仍有 `unknown`、位置参数和内部 `ipcMain.emit` | [`ipc.ts:10`](/evaluation-path/treatment/packages/desktop/src/shared/types/ipc.ts:10)、[`internalIpc.ts:4`](/evaluation-path/treatment/packages/desktop/src/main/utils/internalIpc.ts:4) | Fact / High | 不应把当前 channel 表误认为稳定领域协议 |
| Git 历史显示高风险修改集中在保存、恢复、引擎兼容和 source mode | `efcaf0c2`、`5d3d2819`、`f937b709`、`c907b29c`、`6c23b1ba`、`ac273f46` | Fact / High | 数据完整性应优先于抽象完整性 |
| CI 把 `packages/muya` 视为“不影响 desktop” | [`test.yml:6`](/evaluation-path/treatment/.github/workflows/test.yml:6)、[`build.yml:6`](/evaluation-path/treatment/.github/workflows/build.yml:6) | Fact / High | 这是当前最明确的集成验证缺口 |

## 3. 当前摩擦

### 窗口边界

当前 `WindowManager` 管理所有窗口，同时拥有 watcher；`EditorWindow` 又拥有打开文件列表、目录、恢复状态和 renderer 消息；`App` 还负责启动、命令行路径分配、设置窗口和 IPC 路由。

内部流程大量通过 `ipcMain.emit` 传递 `BrowserWindow` 对象，例如 watcher 注册和文件路径变更。这说明 `BrowserWindow` 已经泄漏进应用领域逻辑。

建议稳定：

- `WindowId`、窗口类型、生命周期、活动窗口语义。
- main 进程拥有 `BrowserWindow`、菜单、窗口位置和 renderer 路由。

建议不要稳定：

- 把 `BaseWindow` 做成通用插件框架。
- 把所有未来窗口都强行抽象为同一个“窗口能力接口”。
- 把 `BrowserWindow` 作为跨模块或跨进程数据结构。

只有出现第三种持久窗口类型，或不同窗口需要重复的创建、恢复、权限和关闭策略时，才值得引入 `WindowDescriptor`/factory。

### 文件工作流边界

当前保存链路是：

```text
renderer editor store
  -> raw positional IPC
  -> main menu/actions/file.ts
  -> markdown encoding + atomic write
  -> WindowManager / watcher
  -> renderer tab state
```

这里有几个必须保留的不变量：

- 保存前 flush 当前编辑器，避免丢掉同一帧的按键；
- 编码、BOM、换行和末尾换行不能被抽象层吞掉；
- 文件保存和 crash-recovery buffer 都要原子且持久化；
- 外部修改要区分 clean / dirty / reload / undo；
- watcher 不能重复注册，也不能把应用自身写入误报为外部修改。

这些不变量已经被近期提交和测试反复修复，例如 `c907b29c`、`6c23b1ba`、`ac273f46`、`f937b709`。

不建议把当前 `IFileState` 作为长期跨进程模型。它同时包含文档内容、dirty/history、Muya cursor、block tree、scroll 状态和 renderer notification；甚至 [`files.ts:102`](/evaluation-path/treatment/packages/desktop/src/shared/types/files.ts:102) 的 notification 含函数。这是 renderer 状态，不是可稳定序列化的领域 DTO。

### 编辑器引擎边界

`@muyajs/core` 本身已有 public `Muya` API，例如 `getMarkdown`、`getState`、`setContent`、`replaceContent`、history 和事件接口；见 [`packages/muya/src/muya.ts:206`](/evaluation-path/treatment/packages/muya/src/muya.ts:206)。

但 desktop 直接在 `editor.vue` 中：

- 使用宽松 `any`；
- 调用 `replaceContent`、`getHistory`、`setHistory` 等引擎细节；
- 依赖 `.mu-*` DOM 结构；
- 与 CodeMirror source mode 通过 bus 和隐含 payload 互相协调。

`syntheticHistory.ts` 已经是一个实际存在的 anti-corruption seam：它把 Muya history 转换成 desktop dirty tracking 所需的 history。这个 seam 应该被扩大为明确的 editor adapter，而不是继续把 Muya 内部形状扩散到 store。

### IPC 与 Electron shell

preload 已经是正确的安全入口，但当前同时暴露：

- 通用 `ipcRenderer`；
- 低层任意路径 filesystem API；
- shell API；
- window control；
- process/path 等环境信息。

例如 filesystem handler 接受任意路径，[`fs.ts:40`](/evaluation-path/treatment/packages/desktop/src/main/ipc/fs.ts:40)，shell handler 直接把 URL 交给 Electron，[`shell.ts:6`](/evaluation-path/treatment/packages/desktop/src/main/ipc/shell.ts:6)。

这不等于当前一定存在可利用漏洞，但意味着新增 shell 能力应采用语义化 capability，例如 `openExternal`、`showItemInFolder`、`windowControl`，并在 main 侧做 URL scheme、sender 和路径策略校验。不要继续把通用 `ipcRenderer` 当作新代码的默认依赖。

## 4. 质量属性优先级

| 优先级 | 属性 | 当前证据 | 推荐权衡与验证 |
|---|---|---|---|
| 1 | 数据完整性 / 行为兼容 | 保存 flush、原子写、buffer durability、source dirty 都有近期修复和测试 | 保留 main 的文件 IO；任何 adapter 都必须通过保存、恢复、外部 reload、undo 测试 |
| 2 | 变更局部性 | `editor.ts` 2102 行、`editor.vue` 2133 行；Git 变更命中分别约 18、36 次 | 采用渐进 adapter；代价是短期双路径和少量胶水代码 |
| 3 | 测试性 / 可运维性 | renderer/engine 测试较多，但没有明确 WindowManager/EditorWindow 单测，IPC 合同也未完全收紧 | 增加纯函数策略测试、main service 测试和跨进程 contract tests |
| 4 | 安全 | sandbox E2E 是真实 canary，但 filesystem/shell capability 较宽 | 新能力必须经过 preload facade 和 main 校验；代价是 API 设计更慢 |
| 5 | 性能 / 可移植性 | 当前编辑在 renderer，本地多平台构建；未发现明确性能预算 | 不把每次编辑同步到 main；先测大文档启动、输入延迟、内存和 IPC payload |
| 6 | 成本 | 当前方案扩展便宜，中央协调器昂贵 | 只有出现共享文档或远程 provider 时才承担高成本 |

## 5. 可行方案

### 方案 A：维持现状，只加护栏

继续使用 `App`、`WindowManager`、`EditorWindow`、Pinia、raw IPC 和当前引擎接入，只补测试、文档和新 channel 的类型。

- 成本：低。
- 优点：改动最小，现有行为和回滚路径最简单。
- 风险：新增窗口、文件策略或引擎能力仍会同时修改多个大文件；事件顺序错误会继续以回归 bug 的形式出现。
- 回滚：单个提交即可回滚。
- 不改变的后果：短期没有问题；长期会继续扩大 `App`、`editor.ts`、`editor.vue` 的变更半径。
- 适用条件：未来仍只有 editor/settings 两类窗口、本地 Markdown、单一引擎。

### 方案 B：保留拓扑，在真实接缝增加渐进 ports/adapters（推荐）

不改变 Electron 三进程结构，不重写 Pinia；增加几个窄边界：

- `WindowHost`：封装窗口创建、生命周期、renderer 目标和窗口路由；
- `DocumentWorkflow`：封装 open/save/save-as/rename/reload/watch，main 侧继续使用现有 filesystem 实现；
- `EditorSessionAdapter`：封装 Muya、CodeMirror、cursor/history/TOC 和 source-mode handoff；
- `ShellCapabilities`：preload 的语义化能力 facade；
- shared 只保留可序列化的 `WindowId`、`DocumentId`、`TabId`、snapshot 和 request/result DTO。

旧 channel 和旧 store 先作为 adapter 保留。

- 成本：中等；会有一段时间的新旧协议并存。
- 优点：变更局部性、测试性和回滚能力明显改善；不增加每次编辑的 main IPC 成本。
- 风险：adapter 可能变成第二个“大 store”；必须规定单一状态所有者。
- 回滚：facade 退回旧 channel/旧实现即可；不改 buffer store 持久化格式，避免数据迁移。
- 不改变的后果：仍需逐步收敛旧路径，但未来新增功能不必继续直接依赖 `BrowserWindow`、Muya 内部对象或位置参数 IPC。

### 方案 C：由 main 统一持有 Workspace/DocumentSession

让 main 进程持有窗口、文档、dirty、版本和共享 session，renderer 只做视图，通过操作协议同步。

- 成本：高。
- 优点：适合同一文档在多个窗口共享、跨窗口协作、冲突解决、远程 provider 或未来协同编辑。
- 风险：每次内容变化都增加序列化和跨进程同步；renderer 崩溃恢复、操作顺序、undo 语义和回滚都会复杂很多。
- 回滚：困难，一旦状态所有权和持久化格式迁移，回到当前模型成本高。
- 不改变的后果：如果未来确实需要共享文档，会在方案 B 上再做一次较大的迁移。
- 适用条件：确认“同一文档多窗口同时编辑”或远程/协同需求，而不是仅仅增加一个设置窗口或预览窗口。

## 6. 建议

选择方案 B，但把方案 A 作为当前稳定基线：不做大规模重构，新功能只允许依赖新边界。

建议的所有权如下：

```text
main
  WindowManager / WindowHost
    BrowserWindow、窗口生命周期、窗口路由
  DocumentFileService
    读取、编码、换行、原子保存、watcher、恢复文件

preload
  Shell/File/Window capability facades

renderer
  Workspace/Editor session
    tabs、dirty、close/save intent、布局和 UI projection
  EditorSessionAdapter
    Muya、CodeMirror、history、cursor、TOC、source-mode handoff

shared
  仅可序列化 DTO、ID 和版本化 contract
```

四类未来能力的具体判断：

| 方向 | 应稳定 | 应延后 |
|---|---|---|
| 新窗口 | `WindowId`、window kind、lifecycle、sender 上下文 | 通用 WindowPlugin registry；至少等第三种持久窗口 |
| 文件工作流 | encoding/EOL/atomic save/watch/reload 语义 | 通用 `DocumentRepository`、虚拟文件系统、事件溯源 |
| 编辑器引擎 | `@muyajs/core` 包边界和 renderer adapter | 覆盖所有可能引擎的 universal interface；等第二个真实引擎 |
| Electron shell | preload/main capability 边界 | 全量替换 IPC、暴露更多通用 Electron 对象 |

## 7. 可验证的渐进迁移路线

### 阶段 0：先修正架构事实和验证入口

不改变运行时行为，先建立：

- 当前 channel、直接 engine import、`BrowserWindow` 泄漏点清单；
- 更新过时的 `ARCHITECTURE.md`。当前文档仍描述根目录 `src/muya` 和 legacy JS engine，[`ARCHITECTURE.md:12`](/evaluation-path/treatment/packages/website/content/docs/dev/ARCHITECTURE.md:12)；
- 对齐 parity 文档。`PARITY_SCOREBOARD.md:69` 仍称 PG14 为 xfail，但当前测试源码已按 `replaceContent` 修复路径编写，[`parity-source-undo-saved.spec.ts:74`](/evaluation-path/treatment/packages/desktop/test/e2e/parity-source-undo-saved.spec.ts:74)；
- 让 `packages/muya` 变更触发 desktop typecheck/build/E2E。当前 workflow 明确忽略它，而 desktop 实际依赖并 import `@muyajs/core`。

退出条件：文档、依赖图和 CI 触发条件一致。

### 阶段 1：先引入可序列化 DTO，不迁移全部状态

新增概念上的：

- `DocumentRef`
- `DocumentSnapshot`
- `SaveRequest` / `SaveResult`
- `FileChange`
- `WindowContext`

保留当前 `IFileState` 作为 renderer 内部兼容结构，但不再把它当作跨进程长期协议。新 IPC 使用对象 payload 和明确的异步结果；旧的 `mt::response-file-save` 等 channel 保留为兼容 adapter。

验证：

- contract 类型与运行时 payload 一致；
- 修正例如 `update-buffer-state` 实际返回 boolean、但 contract 声明 `void` 的漂移；
- 新代码不直接调用位置参数 save channel。

### 阶段 2：以 open/save/external reload 为第一条垂直切片

把现有 `loadMarkdownFile`、`writeMarkdownFile`、watcher 和 buffer store 包在 main 侧 document service 后面；renderer 通过 client facade 调用。

先迁移：

1. 保存和 Save As；
2. 关闭前保存；
3. 外部文件变更；
4. rename/move 后 watcher 更新。

退出条件：

- flush-before-save；
- 编码、BOM、LF/CRLF、末尾换行；
- atomic write 和 crash-recovery buffer；
- external reload 后的 clean/dirty/undo；
- watcher 不重复注册。

回滚方式：facade 切回旧 channel；不改变 buffer store version 1，不做持久化格式迁移。

### 阶段 3：建立 `EditorSessionAdapter`

把以下逻辑从 `editor.vue`/`sourceCode.vue` 的公共状态中收拢：

- Muya instance；
- CodeMirror instance；
- engine history；
- synthetic history；
- cursor 转换；
- source-mode handoff；
- TOC/block projection。

store 只消费规范化的 `ContentSnapshot` 和 `EditorEvent`，不再知道 Muya history 的具体形状。`@muyajs/core` 应先提供可被 desktop 正常解析的 built typings，再逐步删除 [`muya-core.d.ts:16`](/evaluation-path/treatment/packages/desktop/src/types/muya-core.d.ts:16) 所描述的 shim。

退出条件：

- `packages/muya` 单测、类型检查、circular check；
- desktop source-mode、external reload、tabs、saved indicator、all-blocks roundtrip；
- 任意 `packages/muya` 修改都运行 desktop consumer 验证。

回滚方式：保留当前 adapter 实现和旧引擎兼容依赖，按 feature flag 或 wiring 选择上一版 adapter；不要先迁移持久化状态。

### 阶段 4：出现真实需求后再扩展窗口和 shell

- 第三个持久窗口出现后，再引入窗口 descriptor/factory；
- 新 shell 能力只从 preload semantic facade 暴露；
- main 侧校验 sender、URL scheme、路径和窗口权限；
- 如果未来确认多个窗口共享同一文档，再启动方案 C，设计显式 `DocumentSessionId` 和 revision/operation protocol。

## 8. 待确认决策

以下问题会改变最终架构方向：

1. 新窗口是独立编辑 session，还是要与现有窗口共享同一文档和 undo 状态？
2. 文件来源是否始终是本地 Markdown，还是会加入 workspace、云盘、远程 provider？
3. 是否需要同时运行两个编辑器引擎，或做 engine A/B 与可回滚切换？
4. 是否会支持第三方插件或不可信文档触发 shell 能力？
5. 大文档、启动时间、输入延迟和内存是否已有明确预算？

在这些答案确定前，最稳妥的选择是：稳定现有进程和数据不变量，只为文件工作流和编辑器同步建立窄 adapter；不要提前冻结通用窗口、通用文档仓库或通用编辑器接口。

[EVAL:evolve-software-architecture-loaded]
