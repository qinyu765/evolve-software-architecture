我已核对完仓库。下面是基于证据（而非文档转述）的架构评估。**本次为只读分析，未修改任何文件、未创建提交。**

先给出最重要的发现，再按你列的四个能力方向给出「稳定哪些边界 / 延后哪些抽象」的判断、方案对比和迁移路线。

---

## 0. 结论摘要

**应当现在冻结（成为契约）的边界：**

1. 渲染进程沙箱边界（`config.ts` 中的 `contextIsolation/sandbox/nodeIntegration`）——它是安全与进程隔离的唯一根，且实现已正确，只是文档写错了。
2. IPC 通道**注册表纪律**（`shared/types/ipc.ts` 的四分类 + `mt::` 前缀 + preload 泛型桥）——这是新增任何窗口/文件/shell 能力的唯一通道入口。
3. `BaseWindow`/`WindowType`/`WindowLifecycle` 子类化接缝——新窗口类型的扩展点已经存在，不需要重造。
4. 「窗口双 ID」不变量（Electron `win.id` 与 `bufferStoreInfo.id` 分离）——会话恢复依赖它。
5. `@muyajs/core` 的 `src/index.ts` 作为引擎唯一导出枢纽——desktop 只从 `.` 导入，不碰 muya 内部。

**应当延后（现在不要建的抽象）：**

- 通用窗口工厂 / 工作区 / 分屏布局系统——当前需求不支撑，先按 `EditorWindow` 模式继续子类化。
- 统一进程内事件总线去替换 `ipcMain.emit` 内部通道——收益低、风险高，先把它**收口**在一个接缝里即可。
- IPC 载荷的全量严格类型化——逐通道按需收紧，不做大爆炸。
- 文件服务仓储层 / 领域层——当前 main 进程 `filesystem/` + `shared/types/files.ts` 足够。
- Electron shell 的 DI/接口抽象层——`window.electron.shell` + 独立 IPC 已隔离，属投机抽象。
- muya 的 OT 协同传输层——引擎已有 op 结构但无传输，属于远期 idea bank。

下面按证据、四个决策域、迁移路线展开。

---

## 1. 证据核对结果（先纠正一个文档错误）

### 1.1 CLAUDE.md 与实现冲突：沙箱边界文档是错的

根 `CLAUDE.md` 的 Architecture 一节写的是：

> "editor and preferences windows use contextIsolation: false + nodeIntegration: true (see packages/desktop/src/main/config.js)"

但实现（`packages/desktop/src/main/config.ts:11-20` 和 `:34-41`）明确是：

```ts
webPreferences: {
  contextIsolation: true,
  sandbox: true,
  nodeIntegration: false,
  webSecurity: false,
  ...
}
```

而且 `config.js` 已不存在（现为 `config.ts`）。同文件的目录结构一节又说 "sandbox: true since #4244"，CLAUDE.md 自身前后矛盾。**结论：实现是对的（沙箱已开启），文档是过时的。** 这本身就是一个信号——这个仓库里「文档 vs 实现」的漂移风险真实存在，任何架构决策都要以 `config.ts`/`preload/index.ts` 为准，而不是以 CLAUDE.md 为准。

另一个需要盯住的事实：两个窗口都保留了 `webSecurity: false`（`config.ts:19,39`）。在 sandbox+contextIsolation 全开的情况下，这是为本地 `file://` 相对路径图片等场景放宽的 Chromium 同源策略。**这是一个「先保持稳定、不要顺手改动」的边界**——它当前是已知接受的权衡，但任何新的 shell/web 能力都不应再扩大它；中长期可评估迁移到自定义协议（`app://`）来收窄。

### 1.2 引擎双轨：legacy muyajs 在运行时已完全解耦，只剩「接线」

关键证据：

- `packages/desktop/package.json:62-63` 同时依赖 `@marktext/muyajs`（workspace）和 `@muyajs/core`（workspace）——**双引擎依赖并存**。
- `electron.vite.config.ts:38` 仍有 `muya → ../muyajs` 别名，`tsconfig.base.json:29` 仍有 `muya/* → ../muyajs/*`。
- `packages/desktop/src/types/muya.d.ts` 仍为 `muya/lib/*` 声明了约 20 个模块。

但我在 `packages/desktop/src` 全量 grep `from 'muya/`、`muya/lib`、`require('muya`、`@marktext/muyajs`，**运行时导入为零**——命中的只有 `muya.d.ts` 声明和 3 处代码注释。渲染进程实际只从 `@muyajs/core` 导入（`editor.vue:82-113`、`sourceCode.vue:15`、`markdownToHtml.ts:1`、`exportHtml.ts:12-13`、`pdf.ts:8`）。

**含义**：legacy 引擎在运行时已经摘除干净，剩下的是「依赖声明 + 别名 + 类型声明」这类死接线。这是一个低成本、低风险、可验证的收尾项（见 §3.1）。

### 1.3 路径同一性逻辑存在三份实现

- main 侧：`common/filesystem/paths.ts:135-166` 用 Node `fs.statSync` 做 inode 兜底（`isSamePathSync`）。
- preload 侧：`preload/index.ts:111-156` 用 `pathe` 重写 `isSamePathSync`/`isChildOfDirectory`/`hasMarkdownExtension`，大小写相等时再走同步 IPC `mt::paths::is-same-sync` 兜底。
- renderer 侧：`window.path`（pathe 封装）+ `window.fileUtils.isSamePathSync` 同时暴露。

三个同名函数语义略有差异（一个用 inode 兜底，一个用同步 IPC 兜底）。这在文件工作流（重命名/移动/去重/最近文件）上是最容易踩的坑。

### 1.4 主进程内部用 `ipcMain.emit` 混用两条消息总线

`main/utils/internalIpc.ts` 用 `ipcMain.emit(channel, ...args)` 把主进程内部事件（`watcher-watch-file`、`window-close-by-id` 等）和真正的跨进程 IPC 通道共用同一个命名空间，`windowManager.ts:421-476` 大量依赖它。这在只有 editor/settings 两种窗口时够用，但新增窗口能力（背景窗口、非编辑器窗口、多窗口协调）时会把这个隐式耦合放大。

### 1.5 窗口双 ID 是会话恢复的承重墙

`EditorWindow` 同时持有：

- Electron 的 `win.id`（`windows/editor.ts:147`），用于 IPC 路由和菜单绑定；
- `bufferStoreInfo.id`（`windows/editor.ts:139-145`），一个不与已关闭窗口冲突的稳定 UUID，挂在 `win.restoreBufferId` 上，用于崩溃/会话缓冲恢复。

这条不变量很隐晦（注释里解释了「不能用 win.id，可能和已关闭窗口撞 ID」）。任何新的窗口能力都必须保留它。

### 1.6 IPC 契约「注册表已成型、载荷仍宽松」

`shared/types/ipc.ts` 已把通道分成 invoke/send/sync/event 四类，命名规范（`mt::` 前缀）和 preload 泛型桥（`preload/index.ts:26-68`）是稳定的。但载荷大量是 `unknown`（文件头注释明确说「迁移期间有意宽松，具体类型在 commits 5–8 逐步收紧」）。`shared/types/bus.ts` 更是整张 `unknown[]` 空表。

---

## 2. 四个能力方向：稳定 / 延后判断

### 2.1 窗口能力（window capabilities）

**稳定**：`BaseWindow` 子类化接缝（`windows/base.ts`）、`WindowType`/`WindowLifecycle`、`WindowManager` 的 `add/get/remove/forceClose` 生命周期、`BaseWindowEvents` 事件（`window-ready/focus/blur/close/closed`）、双 ID 不变量。

**延后**：通用「窗口工厂 + 布局/分屏 + 工作区」抽象。当前 `EditorWindow`/`SettingWindow` 两个子类就是足够的模式；在出现第三个、第四个有本质差异的窗口类型之前，工厂抽象是猜测性设计。真正要先做的是把 `WindowManager` 里与「编辑器专属」逻辑（`getActiveEditor`、`findBestWindowToOpenIn`、opened-files 评分）与「通用窗口管理」逻辑的边界在**语义上**分清，而不是立刻抽出新框架。

### 2.2 文件工作流（file workflows）

**稳定**：`shared/types/files.ts` 的 `IFileState` 作为跨进程文档契约的唯一归属地；main 侧 `filesystem/` 的原子写（`write-file-atomic` + fsync，`main/filesystem/index.ts:25-49`）和 watcher 的稳定性阈值语义；「已打开文件清单」由 `EditorWindow` 持有（`_openedFiles`/`_openedRootDirectory`）这一所有权。

**延后**：文件仓储/领域服务层、通用 VFS 抽象、路径服务接口化。当前风险不在「缺抽象」，而在**路径同一性三份实现**和 **watcher 通过 `ipcMain.emit` 的隐式耦合**——这是先修裂缝，不是先盖楼。

### 2.3 编辑器引擎演进（editor engine evolution）

**稳定**：`@muyajs/core` 的 `src/index.ts` 作为唯一导出枢纽；desktop 只允许 `import from '@muyajs/core'`；muya 自包含工具链（自己的 eslint/stylelint/madge/vitest/CommonMark+GFM conformance）边界；`renderToStaticHTML`/`MarkdownToHtml`/`Muya` 三个公开入口的语义。

**延后**：OT 协同传输（muya 已内建 ot-json1 操作但没有传输层，`BACKLOG.md:150-153` 列为 idea bank）；`focusMode` 的渲染路径（当前是 no-op，`BACKLOG.md:123`）；对引擎内部（`block/`、`state/`）做 desktop 侧的类型耦合——desktop 现在用手写 `muya-core.d.ts`（`types/muya-core.d.ts`）把类型图在边界处切断，这个「边界屏蔽」策略应当保留到 muya 真正发布 `lib/types`。

### 2.4 Electron shell 能力（Electron shell capabilities）

**稳定**：preload 的 `contextBridge` 暴露面（`window.electron.*`、`window.fileUtils.*`、`window.path` 等）作为 renderer 的唯一 Node/Electron 通道；`shared/types/ipc.ts` 通道注册表；`global.d.ts` 的类型镜像。

**延后**：shell/dialog/notification 的接口抽象层（DI）、通用「平台能力 provider」接口。当前按通道逐个暴露已经足够隔离；在没有第二个宿主（比如 Web 版、测试替身）之前，抽象层是纯成本。

---

## 3. 四个决策域：方案对比

每个领域给「维持现状」和一个「渐进改进」方案对比。回滚路径都写清楚。

### 3.1 决策 A：legacy muyajs 的收尾方式

| | 方案 A（维持现状） | 方案 B（渐进收尾，推荐） |
|---|---|---|
| 内容 | 保留 `@marktext/muyajs` 依赖、`muya/` 别名、`muya.d.ts`、`packages/muyajs` 包 | 分步：①先删 desktop 对 `@marktext/muyajs` 的依赖与别名；②删 `muya.d.ts`；③最后删 `packages/muyajs` 与 workspace 条目；④muya 发布 `lib/types` 后删手写 `muya-core.d.ts` |
| 质量属性 | 无构建收益；双引擎源仍在，任何新人/工具都会误判 | 单一引擎源；依赖图、别名、类型屏蔽三处全部收窄；降低认知负担 |
| 成本 | 0 | 低（②③④ 主要是删除 + 少量路径清理），但 ④ 依赖 muya 发布类型，属于「有时间依赖」的尾项 |
| 风险 | 累积风险：legacy 包仍在 CI 外的「灰色地带」被误用 | 很低——已证明零运行时导入；唯一风险是某个 CI/构建脚本仍引用 `packages/muyajs`，需在删包前用 workspace 级 grep 验证 |
| 回滚 | — | 每步独立可回滚（git 单提交；④ 可长期保留手写 d.ts 作 fallback） |
| 不改变的后果 | 引擎「演进」永远有两个名义来源，新人会问「到底用哪个」；monorepo 保持一个已死的包 | — |

**验证门**：删 ①② 后 `pnpm run typecheck && pnpm run lint && pnpm run build:unpack` 全绿；`grep -r 'muya/lib\|@marktext/muyajs' packages/desktop/src` 只剩零命中；`pnpm --filter marktext test` 通过。删 ③ 前 `grep -r 'packages/muyajs' .github scripts pnpm-workspace.yaml` 确认无引用。

### 3.2 决策 B：IPC 载荷类型化的节奏

| | 方案 A（维持现状） | 方案 B（大爆炸全量类型化） | 方案 C（逐通道收紧，推荐） |
|---|---|---|---|
| 内容 | 保持 `unknown`，按需顺手改 | 一次性给所有通道补精确类型 | 谁改哪个通道，就把该通道的 `args/ret` 从 `unknown` 收紧为具体类型，配合 preload/global.d.ts 同步 |
| 质量属性 | 类型安全停滞；新代码继续传播 `unknown` | 短期类型安全峰值；但 4 类通道 + ~150 条，跨 main/preload/renderer/shared 四处同步，review 面巨大 | 类型安全单调上升；每次提交范围小、可独立验证 |
| 成本 | 0（但持续支付隐形成本） | 高（一次大 PR 或多次强耦合提交） | 低，与日常改动同节奏 |
| 风险 | 契约漂移 | 高：大爆炸改动的正确性靠人眼，`unknown→具体` 若猜错形状，运行时不报错但类型撒谎 | 低：错误被限制在单通道内，`typecheck` 立刻抓到 |
| 回滚 | — | 大爆炸难回滚（要么全退） | 每通道一个提交，可独立 revert |
| 不改变的后果 | `bus.ts`、`send` 通道大量 `unknown` 会持续侵蚀「跨进程契约」这个最该稳定的边界 | — | — |

**关键判断**：这个领域「注册表纪律」比「载荷类型」重要得多。冻结的是**新通道必须先注册再接线**（`ipc.ts:14-17` 的三步流程），载荷收紧可以无限期渐进。方案 C 是唯一同时兼顾「边界稳定」和「低成本回滚」的。

### 3.3 决策 C：窗口能力的抽象层次

| | 方案 A（维持现状） | 方案 B（现在引入通用窗口工厂/工作区/分屏） | 方案 C（先做语义分层，后按需抽象，推荐） |
|---|---|---|---|
| 内容 | 继续 `EditorWindow` 模式逐个加子类 | 设计 WindowFactory、LayoutManager、SplitPane 等 | 先把 `WindowManager` 里编辑器专属逻辑与通用逻辑在语义上分开（不改结构，只整理职责），新增窗口仍走 `BaseWindow` 子类 |
| 质量属性 | 新增窗口类型时 `WindowManager` 里的 `getActiveEditor`/`findBestWindowToOpenIn` 等编辑器特判会持续膨胀 | 可扩展性好（假设猜对了未来的形状） | 每个新窗口类型成本恒定；特判集中、可读 |
| 成本 | 低（但复杂度向 `WindowManager` 累积） | 高（设计 + 迁移 + 回归） | 低-中 |
| 风险 | `WindowManager` 变成上帝对象 | 高：抽象猜错方向是最大风险（比如分屏可能永远不会来） | 低 |
| 回滚 | — | 抽象一旦落地并让 renderer 依赖，回滚很贵 | 纯重构 + 少量新子类，可逐步回滚 |
| 不改变的后果 | 若未来真的上多类型窗口，会先被一次「清理 WindowManager」挡住 | — | — |

**关键判断**：`WindowType` 目前只有 `BASE/EDITOR/SETTINGS`（`base.ts:16-20`）。在出现第 4 类窗口之前，「工厂」是 YAGNI。方案 C 的语义分层（把 `getActiveEditor` 这类「编辑器特判」从通用窗口管理里剥离成显式方法/模块）是唯一现在值得做的、且有验证门槛的窗口侧改进。

### 3.4 决策 D：文件工作流中的路径同一性

| | 方案 A（维持现状） | 方案 B（合并为单一纯路径模块，推荐） |
|---|---|---|
| 内容 | 保留 main(Node) / preload(pathe) / renderer(window.path) 三份 | 把 `isSamePathSync`/`isChildOfDirectory`/`hasMarkdownExtension`/`MARKDOWN_EXTENSIONS` 收敛到 `common/` 一个无 Node `fs` 依赖、仅用 `pathe` 的模块；main 侧需要 inode 兜底时再显式传入一个 `statResolver` 回调，preload/renderer 复用同一纯函数 |
| 质量属性 | 语义漂移（inode vs sync-IPC 兜底不同） | 单一事实源；main/preload 语义一致 |
| 成本 | 0 | 中（涉及 main/preload/renderer 三处调用点，但改动面收敛） |
| 风险 | 重命名/移动/最近文件在边界处出现「两个文件被判为不同」的隐性 bug | 低-中：回调注入要保证 preload 不拉入 `fs`（沙箱约束） |
| 回滚 | — | 模块化迁移，逐步切换调用点，可 revert |
| 不改变的后果 | 文件工作流越复杂（多窗口去重、目录重命名、符号链接），三份实现的偏差越可能变成真实 bug | — |

**关键判断**：这比 3.1 的引擎收尾优先级更高——因为它是**正在被使用**的逻辑，且已经存在语义差异。但同样要遵守沙箱约束：`common/` 里能进 renderer 的只能是纯 `pathe` 版本，Node `fs` 版本只能留在 main。

---

## 4. 统一渐进迁移路线（带验证门槛）

按「先修裂缝、再定契约、最后才谈扩展」排序。每一步都是独立可回滚的提交，且都能被现有工具链验证（`typecheck` / `lint` / `test` / `test:e2e` / muya conformance）。

**阶段 0：把「稳定边界」写成可执行的守则（零代码风险）**
- 修正 CLAUDE.md 里沙箱一节的错误（`contextIsolation: true, sandbox: true, nodeIntegration: false, webSecurity: false`，指向 `config.ts`）。
- 在 `shared/types/ipc.ts` 头部把「新通道必须先注册再接线」升级为带验证的约定（typecheck 会在未注册通道上失败，因为 preload 泛型只接受注册表键）。
- 验证门：`pnpm run typecheck` 绿；文档与 `config.ts` 逐字一致。

**阶段 1：引擎单源化（决策 A，高 ROI 低风险）**
- 删除 `@marktext/muyajs` 依赖、`muya/` 别名、`muya.d.ts`；保留 `muya-core.d.ts` 直到 muya 发布类型。
- 验证门：`grep -rE "muya/lib|@marktext/muyajs" packages/desktop/src` 零命中；`build:unpack` 绿；e2e 冒烟通过。
- 删除 `packages/muyajs` 包放在最后一步（先全局 grep 无引用）。

**阶段 2：路径同一性单源化（决策 D）**
- 抽出纯 `pathe` 的 `common/filesystem/pathIdentity.ts`；main 用注入 `statResolver` 保留 inode 兜底；preload 复用。
- 验证门：单测覆盖大小写不敏感文件系统 / 子目录 / 符号链接；现有 `tabs.find(isSamePathSync)` 行为不变（e2e 的 rename/move 用例不回归）。

**阶段 3：IPC 载荷按通道收紧（决策 C）**
- 每改一个通道就收紧一个；优先级选「文件工作流」相关通道（`mt::response-file-save*`、`mt::update-file`、`mt::open-new-tab` 等），因为它们是下一步的依赖。
- 验证门：`typecheck` 在 preload/global.d.ts/main handler 三处同步收紧后绿；无 `as unknown` 逃逸到非边界处。

**阶段 4：窗口职责语义分层（决策 C）**
- 把 `WindowManager` 中 `getActiveEditor`/`findBestWindowToOpenIn` 等编辑器特判显式模块化，不改行为。
- 验证门：现有多窗口 e2e（`window` 相关 spec）不回归。

**阶段 5：前瞻性评估（不要提前做）**
- 只有出现真实需求信号（第二个非编辑器窗口类型、真正的分屏需求、第二个宿主）时才启动 §2 里「延后」的抽象。

---

## 5. 一句话总结

**该稳定的边界是「已经正确、且所有未来能力都要穿过」的那些**：沙箱/contextBridge、IPC 通道注册表、`BaseWindow` 子类化接缝、窗口双 ID、`@muyajs/core` 的单一导出枢纽、`IFileState` 的契约归属。**该延后的是「现在只有一两个实例、未来形状未知」的抽象**：窗口工厂/分屏、shell DI 层、文件仓储层、OT 传输、IPC 全量类型化。当前真正的技术债不在「缺抽象」，而在三处「同义异现」——引擎双轨（已死接线）、路径三份实现（有语义差异）、内部 `ipcMain.emit` 与 IPC 混用——以及一份把沙箱写反了的文档。先修这些裂缝，比新建任何抽象都更接近「边界稳定」。
