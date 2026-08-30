已完成证据收集（只读，未改动任何文件）。以下是架构评审。

---

# MarkText 未来演进评审：窗口 / 文件工作流 / 编辑器引擎 / Electron Shell 的边界取舍

## 0. 结论先行（TLDR）

- **分类**：这是一个 Electron 桌面应用（不是 Tauri），pnpm monorepo，三进程模型 + 已开启 sandbox 的渲染进程。置信度高——多组独立信号一致（`electron`/`electron-builder` 依赖、`BrowserWindow`/`ipcMain` 用法、`contextIsolation:true + sandbox:true`、electron-vite 构建）。
- **最值得稳定的三个边界**：① preload/contextBridge 暴露的 `window.electron.*`/`window.fileUtils.*` 作为 renderer↔main 唯一通道（并把 IPC 契约做成**双向**类型检查）；② renderer 与引擎之间的**文档内容契约**（markdown 字符串 + 脱敏后的 selection/history 形状），收拢进一个窄的、可单测的适配模块，而不是继续散在 `editor.vue` 里；③ 已版本化、原子写、归属清晰的 **buffer-store 会话持久化格式**（`BUFFERED_STATE_VERSION=1`）。
- **最应该延后的抽象**：通用多引擎接口、通用窗口插件/工厂框架、虚拟文件系统/云盘 provider、协作传输层、基于引擎 AST 的源码模式重写。**在出现第二个真实变体之前都不要建**（现在只有一个活动引擎、两种窗口、一个本地文件后端）。
- **推荐方案**：维持现状 + 定向加固（方案 A），不做大层式重构。现有缝隙质量不差，真正的问题是**迁移进行到一半**（IPC 类型单向、引擎边界 `any`、旧 `functionType` 词汇残留、`ipcMain.emit` 内部事件 hack），把这几件事做完的收益远大于再叠一层抽象。

---

## 1. 范围与置信度

| 项目 | 结论 |
|---|---|
| 仓库类型 | Electron 桌面应用 + pnpm monorepo（`packages/desktop`、`packages/muya`=新引擎、`packages/muyajs`=旧引擎、`packages/website`） |
| 分类置信度 | 高（多信号一致；本仓库不是 Tauri，Tauri 适配器只借用了 IPC/生命周期/桌面测试这几条通用关注点） |
| 评审边界 | 只给架构建议，不改代码、不建 commit |
| 证据限制 | Bash 被禁用，**无法跑 `git log`**；变更热点基于代码注释、issue 引用（#1034/#1035/#3957/#4244/#4859 等）、文件规模推断，不是 git 统计。【未知】 |

---

## 2. 观察到的现状（证据）

| # | 声明 | 证据 | 类型 | 置信度 |
|---|---|---|---|---|
| 1 | 渲染进程已完全沙箱化 | `config.ts:11-21`：`contextIsolation:true, sandbox:true, nodeIntegration:false, webSecurity:false`（editor 和 settings 两窗口一致） | 事实 | 高 |
| 2 | 文档与代码冲突 | 根 `CLAUDE.md` 架构段写"editor/preferences 窗口 `contextIsolation:false + nodeIntegration:true`（见 config.js）"；`config.js` 不存在，`config.ts` 恰相反；`ARCHITECTURE.md` 还引用 `src/muya/`、根 `out/`、"Muya 仍是 JS" | 事实 | 高 |
| 3 | IPC 契约是**单向**类型 | `shared/types/ipc.ts:1-18` 自称"single source of truth…迁移中 commits 5–8"；grep 显示 main 进程 23 个文件共 108 处裸 `ipcMain.on/handle`，**没有任何一处** import `IpcInvokeChannels` 等契约类型 | 事实+推断 | 高 |
| 4 | 双通道家族 + 内部事件 hack | `ipc.ts` 里 `update-buffer-state`/`watcher-*`/`app-*`/`window-*` 无前缀通道与 `mt::` 并存且重复（如 `mt::window-toggle-always-on-top` vs `window-toggle-always-on-top`）；`windowManager.ts:368` 注释"HACK: Don't use this event! #1034/#1035"；`internalIpc.ts:4-7` 用 `ipcMain.emit` 在主进程内部传参 | 事实 | 高 |
| 5 | 窗口模型基本清晰但有硬编码分支 | `windows/base.ts` 的 `WindowType` 只有 `editor/settings` 两个封闭成员；`windowManager.ts`、`app/index.ts:_openPathList`、`editorBufferStore.ts:handleClose` 多处硬编码 editor/settings 区别 | 事实 | 高 |
| 6 | 引擎边界是 `any` + 手写 `.d.ts` shim | `types/muya-core.d.ts:47-52`：`class Muya { [key:string]: any }`；shim 头部说明原因：`@muyajs/core` 的 `exports` 指向 `./src/index.ts`，安装期没有 `lib/types`，所以**桌面直接把引擎 TS 源码打进 bundle**（`packages/muya/package.json:10-16`） | 事实 | 高 |
| 7 | 引擎兼容适配层已经存在且很大 | `editor.vue:390 adaptSelectionChange`（新 payload → 旧 `{start,end,affiliation}`）、`:355 CONTAINER_FUNCTION_TYPE`（新 `blockName` → 旧 `functionType`）、`:294 SyntheticHistory`（引擎 undo 历史与桌面保存/脏标记历史不兼容，另存 `engineHistoryByTab`） | 事实 | 高 |
| 8 | 文档内容有**两个真源** | renderer `store/editor.ts` 的 `tabs[]` 拥有 `markdown/isSaved/history/cursor/blocks`；引擎 `@muyajs/core` 独立拥有 OT 块树；同步协议是 `json-change`（引擎→store 快照）与 `file-changed`（store→`setContent/replaceContent`） | 推断 | 高 |
| 9 | 会话持久化已版本化、原子、归属清晰 | `editorBufferStore.ts:184 writeFileAtomic`（fsync 原子写，修 #3786）；`bufferedState.ts:7 BUFFERED_STATE_VERSION = 1`；每窗口一个 `{uuid}_editor_buffer_store.json` | 事实 | 高 |
| 10 | 文件工作流职责分散 | `watcher.ts`（chokidar + `ignoreChangedEvent` 自写抑制 + Linux 原子 rename 兜底 + 云盘重同步 #3044）；`store/editor.ts:loadChange`/`LISTEN_FOR_FILE_CHANGE`（磁盘变更→UI）；`filesystem/markdown.ts`（编码/换行归一） | 事实 | 高 |
| 11 | 旧引擎已断开，仅剩声明 | 全仓库无活跃 `muya/lib` import（只剩注释 + `types/muya.d.ts` shim）；`@marktext/muyajs` 仍声明于 `desktop/package.json:62`，`muya` alias 仍在 vite/tsconfig 里 | 事实 | 高 |
| 12 | 测试重回归、轻契约 | Playwright E2E 60+（大量 issue 编号 spec）；Vitest unit 112；**没有** main 侧"契约↔ipcMain 注册"的对账测试 | 事实+推断 | 高 |

---

## 3. 当前摩擦（变更放大点）

1. **加一个 IPC 通道要碰 4 处，但只有 3 处有类型保护**：契约 `ipc.ts`、preload 包装 + `global.d.ts`、renderer 调用点这三处受类型检查；main 的 `ipcMain.on/handle` 用裸字符串 + 松参数，**契约撒谎时编译不过只发生在 renderer 侧**。未来"加窗口能力/文件工作流/Shell 能力"都会从这条缝穿过，而这条缝现在是半哑的。

2. **引擎演进必然打穿 `editor.vue`（~2100 行）**：引擎改 selection payload、历史结构或 DOM class，都会迫使 `adaptSelectionChange`、`SyntheticHistory`、源码模式 handoff、主题 CSS（`ag-*` vs `mu-*`，`editor.vue:136-139`）同时改。因为表面是 `any`，**编译期零提示，只能靠 E2E 兜**。旧 `functionType` 词汇（`codeContent/cellContent/frontmatter/html/multiplemath/table/diagram`）至今活在 `store/editor.ts:createApplicationMenuState`，逼着组件去反向翻译新引擎的 `blockName`。

3. **主进程内部事件借用 IPC 总线**：`ipcMain.emit('watcher-watch-file', …)` 把 watcher/window 之间的内部调用伪装成 IPC，注释自己都标了 HACK。这意味着"未来加窗口/文件能力"时，主进程对象之间的调用会继续和 renderer↔main 的消息协议纠缠在一起。

4. **两个文档真源靠一个巨型 Vue 组件协调**：保存/脏标记的 truth 在 Pinia store，编辑的 truth 在引擎，两者之间的 reconcile（source↔WYSIWYG 切换、外部重载、tab 切换、undo 回干净态）全靠 `editor.vue` 里的条件分支 + `syntheticHistory` 补丁。这已经是历史包袱最重、最容易回归的地方（大量 `parity-*`/`issue-*` E2E 就是证据）。

---

## 4. 质量属性优先级（按本次决策排序）

| 排名 | 属性 | 目标/预算 | 现状证据 | 改善它的方案 | 可能受损的属性 | 验证方式 |
|---|---|---|---|---|---|---|
| 1 | **可维护性 / 变更局部性** | 一个未来变更只落在 1 个模块 | 加通道/改引擎语义需跨 3-4 文件 | A 的契约双向化 + 引擎适配收拢 | 短期开发速度 | `pnpm typecheck` + 单文件改动范围 review |
| 2 | **进程边界稳定性**（桌面特有） | IPC 契约、序列化、错误映射不再漂移 | 契约单向、`unknown[]`、裸 `ipcMain` | A 的主进程类型包装 + 契约清单测试 | 灵活性 | 契约↔注册对账单测 |
| 3 | **可测试性** | 能穿过预期缝隙验证，不依赖打包后桌面运行时 | E2E 强、main 契约测缺、引擎适配层无单测 | A 的适配模块单测 | — | Vitest + 现有 E2E 不退化 |
| 4 | **可操作性** | 崩溃/断电后可恢复，会话不丢 | buffer-store 原子写已到位 | 维持并版本化 | — | `buffer-store-durable.spec.ts` + 断电场景 |
| 5 | **可移植性** | Win/mac/Linux + sandbox 持续成立 | watcher 有平台分支（mac 轮询、Linux 原子改名） | 不引入破坏 sandbox 的抽象 | — | 三平台打包 + E2E smoke |
| 6 | **性能** | 启动/文件监听可接受 | 非本次决策驱动项 | 不提前优化 | — | 仅在驱动因素出现时测量 |
| 7 | **安全** | 保持 sandbox | 已 sandbox；**`webSecurity:false` 是遗留风险**（`config.ts:19,40`） | 评估能否去掉 | 功能兼容 | XSS E2E + 关闭后回归 |

---

## 5. 方案对比

### 方案 A —— 维持现状 + 定向加固（推荐）

**它创建/巩固的边界**：把既有的三个好缝隙做完——preload 桥、引擎适配模块、版本化 buffer-store。具体：IPC 契约双向类型化；引擎兼容翻译从 `editor.vue` 抽成一个窄模块；去掉 `ipcMain.emit` 内部 hack；`WindowType` 仍封闭直到第三个窗口真的出现。

- **使能什么**：未来加窗口/文件/Shell 能力时，新增通道有编译期对账；引擎升级只在适配模块内改；主进程内部调用不再走 IPC 总线。
- **假设**：只有一个活动引擎、两种窗口、本地文件后端——这些假设当前都成立。
- **迁移成本**：低到中。每步都是行为保持的重构，可逐 commit 提交；现有 60+ E2E + 112 单测兜底。
- **回滚成本**：极低——每步独立可 revert，不引入跨模块契约。
- **操作/测试后果**：新增契约对账单测与适配模块单测，长期降低回归面。
- **什么证据会让它变错**：出现第二个活动引擎实现、或第三个窗口类型、或真实协作/远程文件需求——那时再升级为 B/C 的对应部分（这正是"延后"的理由）。

### 方案 B —— 显式抽象层（引擎门面 + 窗口注册 + 会话服务）

**它创造的边界**：renderer 引入 `IEditorEngine` 接口与多实现；main 引入 `WindowFactory`/插件注册表；新增一个 `FileSession` 服务把现在散在 watcher（main）和 editor store（renderer）里的文件工作流状态机收拢。

- **使能什么**：理论上的引擎可替换、窗口类型可插拔、文件后端可替换。
- **假设**：这些变体**即将出现且方向已知**——目前证据不支持。
- **成本**：高。每层都要设计接口、迁移两个进程、重新布线测试；`IEditorEngine` 尤其危险——它要么因为只有一种实现而退化成"另一个名字的 `editor.vue`"，要么因为过早抽象锁死错误的接口形状。
- **回滚成本**：高——接口一旦被多处调用，抽掉比建起来更难。
- **什么证据会让它变对**：桌面侧真的接入第二套引擎、或 `@muyajs/core` 与另一个引擎长期并存、或有明确的多 provider 需求（如云盘）。

### 方案 C —— 状态归属反转（把文档/会话 truth 上移到 main）

**它创造的边界**：main 进程成为 tabs/会话/保存状态的唯一 owner，renderer 退化为纯视图 + 引擎宿主。

- **使能什么**：彻底消灭"两个文档真源"（至少消灭一个）。协作/多窗口一致性更好做。
- **成本/风险**：最大。等于重写文件工作流；与 Electron 的"renderer 就近持有编辑状态"惯例相悖，undo/caret/TOC 高频更新要跨 IPC，性能和复杂度风险高。
- **回滚成本**：极高，近乎不可逆。
- **什么证据会让它变对**：出现实时协作或多窗口同文档编辑——那时 OT 状态本身就该上移，但**今天没有这个需求**。

**结论**：选 A。B/C 不是错，是**时机未到**；A 把"延后"的抽象点显式标出来，等真实信号再局部升级。

---

## 6. 建议：哪些边界稳定、哪些抽象延后

### 应该稳定（现在就加固）

1. **preload/contextBridge 是唯一 renderer↔main 缝**（sandbox 已强制）。稳定方式：把 `ipc.ts` 契约做成 main 侧也可用的类型化包装，让裸 `ipcMain.on/handle` 消失，通道改名/改参会在编译期两侧同时报错。
2. **引擎适配模块 = 文档内容契约的唯一翻译点**。稳定的是"markdown 字符串 + 脱敏的 selection/history/TOC 形状"，而不是引擎内部块树。把 `editor.vue` 里的 `adaptSelectionChange`、`functionType` 映射、`SyntheticHistory` 收进一个可单测模块；菜单状态构造器只消费**中性**形状，不再消费旧 `functionType`。
3. **buffer-store 持久化格式**。已有 `version:1` + 原子写 + 清晰 owner，这是未来窗口/会话能力的地基，继续走"版本号 + 显式升级路径"。
4. **引擎的类型出口**。让 `@muyajs/core` 真正产出 `lib/types`（其 build 已经用 vite-plugin-dts 发 types），删掉 `muya-core.d.ts` 手写 shim 和 tsconfig `paths` 重定向，把 `any` 边界收成真类型。
5. **窗口生命周期归属**（`BaseWindow`/`WindowManager`）。保留这个结构，但移除内部 IPC hack 与 editor/settings 硬编码分支，让主进程对象之间直接调用。

### 应该延后（现在不建）

1. 通用 `IEditorEngine` 多实现接口（只有一个引擎）。
2. 通用窗口插件/工厂框架（只有两种窗口）。
3. 虚拟文件系统 / 云盘 provider（只有本地路径 + watcher 启发式）。
4. 协作传输层（引擎 OT 已就绪，但"没有 transport 接线"是明确的现状，别提前造）。
5. 基于引擎 AST 的源码模式重写（CodeMirror 是独立表面，复杂度极高，等引擎序列化稳定）。
6. 一次性把所有 IPC payload 严格类型化（迁移正在分批进行，继续按通道滚，别大爆炸）。

---

## 7. 可验证的渐进迁移路线（含回滚与退出标准）

每步独立可 revert（回滚 = revert 单个 commit），全部行为保持，E2E 兜底。

| 步骤 | 动作 | 验证 / 退出标准 |
|---|---|---|
| 0（零风险） | 修正文档漂移：`CLAUDE.md` 与 `ARCHITECTURE.md` 的 sandbox/目录描述对齐 `config.ts` | 文档与代码一致；无功能变更 |
| 1（最高杠杆） | main 侧引入类型化 IPC 包装，按文件逐个替换 `ipcMain.on/handle`（`fs.ts`/`window.ts`/`shell.ts`…本身已自包含）；加一个"契约↔注册对账"单测：契约里每个通道都有 handler 且反向成立 | `pnpm typecheck` 在重命名通道时两侧同报；对账单测通过；现有 E2E 全绿 |
| 2 | 把 `editor.vue` 的引擎兼容层抽成 `editorEngineAdapter` 模块（`bind/applyContent/serializeChange/selectionToMenuState`），`editor.vue` 仍是唯一调用者 | 现有 selection/menu-state/history/undo/源码模式 E2E 不退化；新增适配模块单测 |
| 3 | 删除 `muya-core.d.ts` shim + tsconfig `paths` 重定向，消费 `@muyajs/core` 构建产物 `lib/types` | 删除后 `pnpm typecheck` 干净；`Muya` 表面无 `any` |
| 4 | 移除 `ipcMain.emit` 内部事件机制：window/watcher 之间改为直接对象调用（两者已在 `Accessor` 里构造） | 窗口开关、watcher watch/unwatch、自写抑制 E2E 不退化；`internalIpc.ts` 归零 |
| 5（**有信号才做**） | 第三个窗口类型真正出现时，把 `WindowType` 注册化 + 移除 `getActiveEditor`/`_openPathList`/`handleClose` 的硬编码分支 | 新窗口类型有 E2E；editor/settings 行为不变 |
| 6（**有信号才做**） | 第二个引擎实现 / 第二个文件后端出现时，再引入 B 的对应门面 | 满足"两个真实变体"规则后再抽象 |

**不改变的后果**：通道契约继续单向漂移，`mt::` 与无前缀通道继续膨胀；引擎一旦改 selection/历史形状，只会靠 E2E 才发现菜单状态、脏标记、undo 悄悄坏掉；内部 IPC hack 长期存在；过时的 `CLAUDE.md` 持续误导新贡献者。

---

## 8. 待决问题（答案会改变建议）

1. **文档内容契约**（renderer 单侧持有 tabs/markdown + 引擎持有编辑态）应写成 ADR——这是未来文件工作流、协作、多窗口一致性的承重不变量。【未知】是否有明确的协作/多窗口同文档路线图？我未找到（无 ADR 目录，桌面无 roadmap，只有 muya 的旧 ROADMAP）。
2. **`webSecurity:false` 的去留**（`config.ts:19,40`）：sandbox 之外这是唯一显眼的安全让步，关闭它是否还有运行时阻塞？值得单独核实。
3. **"commits 5–8" 迁移计划的上下文**只在注释里出现，仓库里没有成文计划——建议补一条简短的迁移状态说明，避免后来者误判进度。

---

[EVAL:evolve-software-architecture-loaded]
