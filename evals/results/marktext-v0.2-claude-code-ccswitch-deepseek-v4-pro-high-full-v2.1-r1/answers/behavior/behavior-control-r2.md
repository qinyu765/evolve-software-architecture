# 结论先行

MarkText 现在已经不是"三进程 + 单一 muya"的旧格局了：`packages/desktop` 里 **sandbox 是真实开启的**（`config.ts` 里 `contextIsolation:true / sandbox:true / nodeIntegration:false`），窗口层已经具备**多窗口路由**（`WindowManager` + `BaseWindow` 生命周期 + `App._openPathList` 的"最佳窗口"分配），编辑器引擎已经切到 **`@muyajs/core`**（TypeScript 重写版），而旧 `@marktext/muyajs` 已经是**运行时无引用的僵尸依赖**。与此同时，IPC 契约、文件类型契约都带着"迁移进行中"的标记（`ipc.ts`、`files.ts` 里的 `unknown` 和 "commits 5–8 / subsequent commits" 注释），文档明显落后于实现。

据此，我的核心判断是：

**应该稳定（现在就固化成契约）的四条边界：**
1. 窗口的**生命周期 + 身份 + 路由**模型（`BaseWindow`/`WindowManager`/`App` 已存在，扩展它，不要替换它）；窗口身份从"sender 反查"改为**一等 `windowId`**。
2. IPC 的**命名空间纪律**：renderer↔main 的 `mt::` 请求/响应，与 main 内部事件（`app-*`/`window-*`/`watcher-*`/`broadcast-*`）**彻底分开**，停止把 `ipcMain.emit` 当进程内事件总线。
3. **文件/文档契约**（`shared/types/files.ts` 的 `IFileState`/`MarkdownDocument`/`UnsavedFile`）和**版本化的缓冲状态**（`BUFFERED_STATE_VERSION=1`）。
4. 编辑器引擎的**纯函数缝隙**（`markdownToHtml`/`wordCount`/`sanitize`/`escapeHTML` 等）和**不透明的 block tree**。

**应该延后（现在不要建）的抽象：**
1. 宿主侧的 `IEditorEngine` 反腐蚀层——引擎 API 还在 churn（v0.2.0、类型未随包发布、主题 DOM 迁移未完成），现在包一层只会得到第二套要维护的 API。
2. 平台可移植的 Electron shell 抽象（Tauri/浏览器第二目标）——纯投机，Electron 已锁定 42.1.0。
3. 中央 Session/Workspace 服务——"窗口即会话 + 每窗口 bufferStore"现在够用。
4. 新的命令/消息总线框架——已有 `CommandManager`。

下面先给证据，再按四个领域展开，最后是方案对比和可验证的迁移路线。

---

# 一、证据核对（实现 vs 文档 vs 测试 vs 历史）

我实际读到的关键事实（都可在仓库里复核）：

**1. 沙箱是开启的，但根 CLAUDE.md 自相矛盾、架构文档过时。**
- `packages/desktop/src/main/config.ts:11-21`：editor 窗口 `webPreferences = { contextIsolation: true, sandbox: true, nodeIntegration: false, webSecurity: false, preload: ... }`；`config.ts:34-42` settings 窗口同构。
- 根 `CLAUDE.md` 的"Directory Structure"段落说 `sandbox: true since #4244`（对），但"Architecture: Three-Process Electron Model"段落仍写"editor and preferences windows use `contextIsolation: false + nodeIntegration: true`，且指向一个已不存在的 `config.js`（错，实际是 `config.ts`）。
- `packages/website/content/docs/dev/ARCHITECTURE.md` 还在描述 monorepo 之前的 `src/{common,main,muya,renderer}` 布局，并写"Muya, the editor backend, is currently still JavaScript"——已过时两代（monorepo 化 + TS 重写）。

**2. IPC 契约是"单一事实源"，但处于迁移中途，且命名空间混叠。**
- `packages/desktop/src/shared/types/ipc.ts:10-12` 自己声明"argument and return shapes are intentionally permissive (`unknown[]`/`unknown`) during the migration… tighten as each handler/caller converts in commits 5–8"。
- `ipc.ts:92-202` 的 `IpcSendChannels`（名义上是 renderer→main）里混进了 `app-create-editor-window`、`app-open-file-by-id`、`watcher-watch-file`、`window-close-by-id`、`broadcast-preferences-changed` 等**纯 main 内部通道**。这些在 `WindowManager`、`App`、`DataCenter` 里是用 `ipcMain.emit(...)` 派发的（`windowManager.ts:369-495`、`app/index.ts:668-765`、`dataCenter/index.ts:107/117/136`），经 `utils/internalIpc.ts:8-13` 的 `onInternalChannel` 订阅。**后果**：renderer 理论上也能 `send('watcher-watch-file', ...)`，同一通道名承载两种语义，类型契约无法区分。
- IPC handler **散落五处**：`main/ipc/index.ts` 的 `registerSandboxIpcHandlers()`（集中注册 bootInfo/fs/paths/ripgrep/uploader/fonts/shell/window/cmd/i18n），加上 `WindowManager._listenForIpcMain`、`DataCenter._listenForIpcMain`、`EditorBufferStore._listenForIpcMain`、`App._listenForIpcMain`、`menu/actions/file.ts` 顶层 `ipcMain.on`。
- 窗口身份大量靠 `BrowserWindow.fromWebContents(e.sender)` 反查 + 断言（如 `windowManager.ts:369-372`、`file.ts:166`），`restoreBufferId` 通过 `(win as unknown as { restoreBufferId?: string })` 挂在 BrowserWindow 上（`editor.ts:145`、`editorBufferStore/index.ts:189`）。

**3. 编辑器引擎边界：直接 import，无宿主包装层。**
- `editor.vue:82-140` 从 `@muyajs/core` 一次性导入 `Muya`、约 15 个 UI 插件、locales、`ILocale`，并 `import '@muyajs/core'` 以副作用注入 CSS。
- 桌面侧类型靠手写 shim `src/types/muya-core.d.ts`：`Muya` 是 `[key: string]: any`，UI 插件全是 `any`（`muya-core.d.ts:47-51`）。原因写在 `muya-core.d.ts:5-17`：`@muyajs/core` 的 `exports` 在 workspace 安装时指向 `./src/index.ts`（`packages/muya/package.json:10-13`），安装期没有 `lib/types`，若让 vue-tsc 解析到源码会连带类型检查整个 muya 树。
- `packages/muya/package.json:16-17` 声明了 `types: ./lib/types/index.d.ts`，`publishConfig` 里也有正确的构建后导出——**说明一旦发布版/构建产物带类型，桌面 shim 即可删除**。
- 旧引擎：`packages/desktop/package.json:62-63` 同时声明 `@marktext/muyajs: workspace:*` 与 `@muyajs/core: workspace:*`；`electron.vite.config.ts` 三个 target 里都还保留 `muya → ../muyajs` alias；`src/types/muya.d.ts` 仍为旧 `muya/lib/*` 声明。但全仓搜索 `src` 找不到任何运行时 import（只有注释和 .d.ts 引用）。**旧引擎是声明了依赖、配了 alias、写了 ambient 声明、却没有任何活 import 的僵尸依赖。**
- 主题迁移未完成：`editor.vue:137-139` 注释"desktop themes still target the legacy `ag-*` DOM… minor visual differences against the new `mu-*` DOM expected"。

**4. 文件工作流：设计相当完整，但 save/export 放错了层。**
- renderer 侧 `store/editor.ts`（2000+ 行）持有 `tabs: IFileState[]`、`isSaved`、基于 undo 历史的脏检测（`lastSavedHistoryId`，`editor.ts:1442-1465`）、autosave 定时器、`FILE_SAVE`/`FILE_SAVE_AS` 通过 `mt::response-file-save(as)` 把 markdown+options 回传 main（`editor.ts:512-620`）。
- 缓冲状态：`store/bufferedState.ts:7` `BUFFERED_STATE_VERSION = 1`，debounce 1s，快照 editor+project+layout，`invoke('update-buffer-state')` → `EditorBufferStore` 原子写 JSON（`write-file-atomic.sync` + fsync，`editorBufferStore/index.ts:178-185`）。
- 磁盘写：`filesystem/index.ts:40-49` 用 `write-file-atomic`（fsync+rename）做崩溃+断电安全写。
- main 侧 save/export/rename/move 全部在 `menu/actions/file.ts`（`file.ts:157-456`），且 `file.ts:36-38` 有明确 TODO："save and save as should be moved to the editor window… renderer should communicate only with the editor window for file relevant stuff. E.g. `mt::save-tabs` → `mt::window-save-tabs$wid:<windowId>`"。这与我的判断一致。
- `shared/types/files.ts:3-5` 同样写着"Concrete fields are populated as call-sites convert to TS in subsequent commits"。

**5. 测试与 Git 历史。**
- Git 历史：本次 checkout 是 `develop` 分支的干净 clone（`e52106fd`），reflog 只有 clone/checkout 两条，没有更早历史可挖；迁移证据主要来自代码注释和提交列表。
- 单测覆盖了大量边界行为：`write-file-atomic.spec.ts`、`buffer-store-durable.spec.ts`、`watcher-await-write-finish.spec.ts`、`listen-for-main.spec.ts`、`flush-before-save.spec.ts`、`source-mode-dirty.spec.ts` 等（`test/unit/specs/`）。
- e2e 有 `context-isolation.spec.ts`、`tabs.spec.ts`、`export-pdf.spec.ts`、`launch.spec.ts` 等，可直接作为边界变更的回归门。
- muya 自己有独立 conformance 套件（CommonMark 87.7% / GFM 86.3%，锁在 `expected-failures.json`）。

---

# 二、四个领域：稳定什么、延后什么

## 2.1 窗口能力

**现状**：窗口层已经是一个不错的抽象——`BaseWindow` 有 `WindowType`（BASE/EDITOR/SETTINGS）和 `WindowLifecycle`（NONE/LOADING/READY/QUITTED）状态机 + 类型化事件（`base.ts:16-43`）；`WindowManager` 管多窗口 Map、active window、`findBestWindowToOpenIn`、per-window watcher（`windowManager.ts:85-495`）；`App` 负责创建窗口和把文件路由到"最佳窗口"（`app/index.ts:508-640`）。**加新窗口类型（如独立图片查看器、搜索面板、about 窗口）在结构上已经是"再写一个 `BaseWindow` 子类 + `WindowType` 加一项"的机械工作。**

**稳定**：
- `BaseWindow` 生命周期/事件/`WindowType` 模型——这是窗口扩展的骨架，不要推翻。
- 窗口**身份**：把 `windowId` 提升为一等公民，所有窗口相关通道显式携带 `windowId`，淘汰 `BrowserWindow.fromWebContents(e.sender)` 反查。这直接降低未来"跨窗口操作"（一个窗口触发另一个窗口的行为）的成本。
- **启动载荷走结构化通道**，不再走 URL query：现在 `_buildUrlWithSettings` 把 `udp/debug/wid/type/cff/cfs/hsb/theme/tbs` 塞进 URL（`base.ts:110-140`），而 `mt::bootstrap-editor` 又发一遍 `lineEnding/sideBarVisibility/tabBarVisibility/sourceCodeModeEnabled`（`editor.ts:174-198`）——**同一份启动信息两条路、且字段不一致**。合并到结构化 bootstrap 是低风险纯化。
- `restoreBufferId` 从 BrowserWindow 上的 ad-hoc cast 改为 `WindowManager` 持有的 `Map<windowId, WindowMeta>`（`editor.ts:145`、`editorBufferStore/index.ts:189` 两处 cast）。

**延后**：不要建"通用窗口框架/窗口工厂 DSL"。当前只有 2 种窗口，`App._createEditorWindow/_createSettingWindow` 显式工厂够用；抽象一个 `WindowFactory` + 配置化注册表是提前抽象。

## 2.2 文件工作流

**现状**：renderer 的脏检测/autosave/保存回传、main 的原子写、缓冲恢复，**本身是对的**，而且已有专门测试。真正的结构问题是：**文件生命周期操作（save/save-as/rename/move/export）住在 `menu/actions/file.ts`，而不是 `EditorWindow`**。这意味着窗口越权的地方有两套：菜单命令（menu/actions）和窗口对象（windows/editor.ts）都在对文件状态发号施令，靠 `ipcMain.emit('window-*')` 间接通信。

**稳定**：
- `shared/types/files.ts` 的 `IFileState` / `MarkdownDocument` / `UnsavedFile` / `SaveOptions` 作为跨进程文档契约；把仍在 `unknown` 的字段（`cursor`、`blocks`、`muyaIndexCursor`）**明确标注为"不透明、不参与序列化契约"**，而不是继续泛化。
- `bufferedState` 的 `version` 字段作为**持久化 schema 版本**，未来改结构必须 bump（现在 `=1`，这是正确的起点）。
- 磁盘写语义（原子写 + 编码/换行/EOL 归一化）已经是稳定行为，不要动。

**延后**：
- 不要建中央"文件服务/仓库模式"（`FileService` + `FileRepository`）。当前"窗口持有已打开文件清单 + main 持有 watcher + bufferStore 持久化"够用；过早切 repository 会把 watcher 生命周期、窗口归属、恢复路径搅在一起。
- 不要建 `Workspace`/多项目模型。现在 project 只是 buffer 状态里一个可选 `rootDirectory`（`editor.ts:576`）。

## 2.3 编辑器引擎演进

**现状**：桌面直接消费 `@muyajs/core` 的公共 API（`editor.vue`），边界由手写 `.d.ts` shim 承担。这是一个**诚实、低摩擦、但无隔离**的边界：引擎 API 一变，桌面多处直接受影响；但 shim 把类型检查图在 import 处切断，引擎内部 churn 不会拖垮桌面类型检查。

**稳定**：
- 引擎的**纯函数缝隙**：`MarkdownToHtml`、`wordCount`、`sanitize`、`escapeHTML/unescapeHTML`、`generateGithubSlug`、`getImageInfo`（`muya-core.d.ts:73-97` 已手写类型）。这些函数语义稳定、跨进程无副作用，是未来无论引擎怎么变都该保留的宿主侧契约。
- **block tree 不透明**：`IFileState.blocks?: unknown` 是对的——宿主不该理解引擎内部状态，只透传/持久化。保持这一点。
- **`@muyajs/core` 的 `src/index.ts` 作为唯一导出枢纽**（muya 自己的约定）——桌面永远只从根 import，不 deep-import `@muyajs/core/...` 子路径。

**延后**：
- **不要现在建 `IEditorEngine` 反腐蚀层**。理由：`@muyajs/core` 是 0.2.0，类型未随包发布（靠桌面 shim），主题 DOM 还在 `ag-*`→`mu-*` 迁移中。在 API 稳定前包一层，等于同时维护两套 API 且每次都改两处。**触发条件**：等 `@muyajs/core` 稳定发布 `lib/types`、且桌面 shim 删除后，如果引擎仍有频繁 breaking change 的需求，再在"纯函数缝隙"之上抽薄门面。
- 不要动 muya 内部（OT/协作、block tree 结构）——那是 muya 包自己的事，宿主不该参与。

**立刻该做的清理（不是抽象，是减债）**：删除 `@marktext/muyajs` 依赖 + 三个 vite config 里的 `muya` alias + `src/types/muya.d.ts`。这三样当前无运行时引用，留着制造"还有第二条引擎路径"的假象。

## 2.4 Electron shell 能力

**现状**：preload 已经把 Node 访问收口到 contextBridge（`preload/index.ts:286-299` 暴露 `electron`/`fileUtils`/`path`/`ripgrep`/`uploader`/`fonts`/`i18nUtils`/`commandExists`/`process`/`rgPath` 十个全局）。但：
- `window.electron.ipcRenderer` 是**裸的** `send/invoke/on/sendSync`（`preload/index.ts:38-68`），renderer 可直达任何已注册通道，绕过领域 API 封装。
- **`webSecurity: false`**（`config.ts:19,40`）在 sandbox 之外再关掉同源策略——这是 shell 安全边界上最值得收紧的一项（渲染的 markdown 若被 XSS，可达 `file://`/网络资源）。

**稳定**：
- contextBridge 的**领域 API 面**（`fileUtils`/`shell`/`clipboard`/`windowControl`/`path`…）：这是 renderer 唯一的 Node/系统能力入口，是 shell 边界的正确定位。
- `main/ipc/*` 的集中注册模式（`registerSandboxIpcHandlers`）：新能力继续往这注册，而不是像 `DataCenter`/`WindowManager` 那样各写各的 `_listenForIpcMain`。

**延后**：
- 不要建"平台无关 shell 抽象"（为 Tauri/浏览器第二目标做 port）。Electron 42 已锁定，没有第二目标需求，这是最典型的投机抽象。
- 不要为"未来可能换 shell"而把 `dialog`/`shell`/`nativeTheme` 包一层接口。

---

# 三、关键决策的方案对比

下面三条是真正需要"选路线"的决策，其余都是机械清理。

## 决策 A：IPC 契约与内部事件总线的边界

| | A1 维持现状 | A2 拆分命名空间 + 类型化内部总线（推荐） | A3 引入消息框架/RPC |
|---|---|---|---|
| 做法 | 继续 `ipcMain.emit` 当内部总线、`unknown` 类型、`mt::`/内部通道混在 `IpcSendChannels` | `ipc.ts` 拆 `IpcSendChannels`（renderer→main）与 `MainInternalChannels`（main 内部）；内部事件改用类型化 `TypedEmitter`；窗口通道显式带 `windowId` | 引入 mediator/事件总线库或 protobuf/RPC 层 |
| 质量属性 | 可维护性差（通道语义混叠、renderer 可误发内部通道）；类型契约名存实亡 | 类型安全、通道语义清晰、可静态发现"renderer 误发内部通道"；迁移是机械替换 | 强类型/强契约，但引入新依赖和心智模型 |
| 成本 | 0 | 中（拆接口 + 逐点替换 `ipcMain.emit` 调用，约几十处） | 高 |
| 风险 | 低短期，长期持续累积 | 低——每步可由 typecheck + 现有测试把关 | 中高（新框架与 Electron IPC 生命周期契合度未知） |
| 回滚 | — | 单步 revert（每步独立 commit） | 需整体 revert，耦合面大 |
| 不改变的后果 | 每加一个窗口/文件能力，内部/外部通道继续互相污染，类型契约继续失去约束力 | — | — |

**推荐 A2**，且把 `MainInternalChannels` 的类型化内部总线落在已有的 `TypedEmitter`（`shared/types/typedEmitter.ts` 已存在）上，不引新依赖。

## 决策 B：编辑器引擎边界

| | B1 维持现状（直接 import + shim） | B2 清理 + 窄化门面（推荐） | B3 建完整 `IEditorEngine` 反腐蚀层 |
|---|---|---|---|
| 做法 | 保持 `editor.vue` 直连 `@muyajs/core`，保留 shim、僵尸 muyajs | 删旧依赖/alias/旧 d.ts；把引擎构造+插件注册收进一个 `engineFactory` 薄门面；纯函数继续走 shim 类型；`Muya` 实例保持 `any` 但限定在 editor.vue 内 | 定义宿主侧引擎接口，隔离所有引擎 API |
| 质量属性 | 少一层间接，但旧引擎假象 + 大面积直连 | 单一引擎路径、导入面收敛、仍低摩擦 | 隔离最好，但 API churn 时双重维护 |
| 成本 | 0 | 低（删死代码 + 一个薄文件） | 高 |
| 风险 | 低 | 低 | 中——抽象建立在未稳定 API 上，易腐化 |
| 回滚 | — | 删依赖可秒级回滚（重加 dep）；门面可整文件 revert | 需整体 revert |
| 不改变的后果 | 双引擎依赖长期误导；`@muyajs/core` 发类型后 shim 与新类型并存冲突 | — | — |

**推荐 B2**。B3 不是错的，只是**时机不对**：等 `@muyajs/core` 稳定发 `lib/types`（届时 `muya-core.d.ts` 可删、`tsconfig` paths 可撤）之后再评估是否需要完整隔离层。

## 决策 C：文件工作流的归属

| | C1 维持现状（save/export 在 menu/actions/file.ts） | C2 下沉到 EditorWindow + 窗口作用域通道（推荐） | C3 独立 FileService |
|---|---|---|---|
| 做法 | 保持现状 | 按 `file.ts:36-38` 的 TODO，把 save/save-as/rename/move/export 移到 `EditorWindow`，通道改窗口作用域 | 抽独立文件服务类 |
| 质量属性 | 文件逻辑与菜单耦合，靠 sender 反查窗口 | 文件生命周期与窗口生命周期一致（watcher/已打开清单/恢复本就住在窗口） | 单一职责，但与 watcher/窗口状态分家，需要再缝合 |
| 成本 | 0 | 中（移动 handler + 通道重命名 + e2e 回归） | 高 |
| 风险 | 低 | 中低——`tabs.spec.ts`/`export-pdf.spec.ts`/`flush-before-save.spec.ts` 可把关 | 中高 |
| 回滚 | — | 单文件 revert | 整体 revert |
| 不改变的后果 | 文件能力继续散在两处，越加越绕；`windowId` 化无法推进 | — | — |

**推荐 C2**，因为它与代码里已有的 TODO、以及"窗口已持有 openedFiles/watcher/bufferStore"的事实一致——文件状态天然属于窗口。

---

# 四、可验证的渐进迁移路线

每一步都是**独立 commit、可单独 revert、有明确验证门**。顺序从"纯契约/低风险"到"行为迁移/中风险"。

1. **拆分 IPC 命名空间（纯类型 + 契约）**：`ipc.ts` 把 `IpcSendChannels` 里的内部通道（`app-*`/`window-*`/`watcher-*`/`broadcast-*`/`set-*`/`update-*`）移入 `MainInternalChannels`。
   - 门：`pnpm run typecheck` 应暴露出所有仍用 `window.electron.ipcRenderer.send(...)` 发内部通道的 renderer 调用（预期数量很少）；`pnpm run lint` 通过；`test/unit/specs/listen-for-main.spec.ts` 不变。

2. **用类型化内部总线替换 `ipcMain.emit`**：在 `WindowManager`/`App`/`DataCenter`/`menu/actions/*` 里逐点把 `ipcMain.emit(ch, ...)` + `onInternalChannel(ch, ...)` 换成基于 `TypedEmitter` 的 main 内部事件。
   - 门：`typecheck` + `lint`；`test/unit/specs/application-menu-state.spec.ts`、`watcher-await-write-finish.spec.ts` 通过（watcher 事件路径被覆盖）。

3. **窗口身份一等化**：新增 `WindowMeta`（`windowId`、`restoreBufferId`、`type`），由 `WindowManager` 持有；替换 `editor.ts:145` 与 `editorBufferStore/index.ts:189` 的两处 cast。
   - 门：`typecheck`；`test/unit/specs/buffer-store-durable.spec.ts` 通过（恢复路径）。

4. **启动载荷去 URL 化**：把 `base.ts:110-140` 的 query 参数并入 `mt::bootstrap-editor`，`_buildUrlWithSettings` 只保留 `wid`/`type`（或全部移除，由 bootstrap 结构化携带）。
   - 门：e2e `launch.spec.ts`、`context-isolation.spec.ts`、`i18n-shell.spec.ts` 通过。

5. **文件工作流下沉（C2）**：把 `menu/actions/file.ts` 的 save/save-as/rename/move/export handler 迁到 `EditorWindow`，通道改窗口作用域（`windowId` 显式传递或 `$wid:<id>` 命名）。
   - 门：e2e `tabs.spec.ts`、`export-pdf.spec.ts`、`source-mode-dirty.spec.ts`；unit `flush-before-save.spec.ts`、`write-file-atomic.spec.ts`。

6. **移除僵尸引擎依赖（B2 前半）**：删 `@marktext/muyajs` 依赖、三个 vite config 的 `muya` alias、`src/types/muya.d.ts`。
   - 门：`typecheck` + `lint` + 全量 e2e（尤其 `parity-*`、`crash-*` 回归）。

7. **窄化引擎门面（B2 后半）**：抽 `engineFactory`（构造 Muya + 注册 UI 插件 + 传 locale/主题），`editor.vue` 只消费门面 + 纯函数。**不做 `IEditorEngine` 接口**。
   - 门：`typecheck`；e2e `editor-input.spec.ts`、`inline-format.spec.ts`、`image-edit-tool.spec.ts`。

8. **（条件触发，暂不排期）删除 `muya-core.d.ts` shim**：当 `@muyajs/core` 发布版携带 `lib/types` 且桌面构建解析到它时执行；此前 shim 是必要的止血带。
   - 门：`typecheck` 在去掉 shim 后对全桌面树通过。

每步完成后都可以 `git revert` 单步回滚；1–4 是纯契约/重构，不改变运行时行为，回滚成本最低，建议先做。5–7 改变少量行为路径，靠既有单测/e2e 做回归锚。

**不改变的后果（若什么都不做）**：不是"不能加功能"，而是每加一个窗口/文件/引擎能力，都要在"renderer↔main 与 main 内部混叠的通道"、"sender 反查的窗口身份"、"双引擎假象"这三层债务上继续叠加；类型契约继续名存实亡，`unknown` 蔓延，未来任何一次引擎升级或窗口扩展都更难验证、更难回滚。反过来，先把上述边界固化，四个未来方向都能在这套骨架上做增量，而不是先做一次大的架构重写。

最后一句务实提醒：**这次不需要动任何代码**。上面 1–8 的每一步都是可独立评审的小 PR，而且 1、2、3、6 属于"删债/收紧契约"，风险最低、收益最确定，是建议优先进入 backlog 的部分。
