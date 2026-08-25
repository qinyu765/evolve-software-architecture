# packages/desktop 进程与模块边界评估（main / preload / renderer / shared）

## 1. 范围与置信度

**结论先行**：这次重构的方向是对的——sandbox 化的 renderer、一份类型化的 IPC 契约、单一的 preload 漏斗、集中的 sandbox handler 模块，这些都是面向未来扩展的正确骨架。但迁移目前只完成了**大约一半**，而且留了一半带来的不是"功能缺失"，而是**契约只在一侧生效、两套事件系统混用、注册点四处散落**这三类结构性债务。它们不会让今天的功能坏掉，但会让每一个新功能（新 IPC 通道、新窗口能力、新偏好项）的改动放大，并让 `shared/types/ipc.ts` 的"单一事实来源"名不副实。

**仓库分类（事实）**：Electron 桌面应用（三进程 + 沙箱 renderer）。可用的 desktop 适配器是 Tauri 专用，信号不匹配（无 `tauri.conf.json`/Rust），所以我采用核心评估流程，并把 Tauri 适配器里对 Electron 同样成立的部分（进程边界稳定性、IPC 契约、生命周期、可测试性、权限/能力面）平移过来。

**置信度**：源码/配置/测试层面的结论为**高**（直接逐文件阅读）。Git 历史的迁移阶段判断为**中**——本会话 Bash 被禁用，无法执行 `git log`，只能依据提示里的最近提交列表和代码内注释（"commits 5–8"、"pre-migration JS"、"Commit 5d"、"#4244 era"）推断。

## 2. 观察事实（证据）

| 观察 | 证据 | 性质 | 置信度 | 对决策的影响 |
|---|---|---|---|---|
| 沙箱配置为 `contextIsolation:true, sandbox:true, nodeIntegration:false, webSecurity:false` | `src/main/config.ts:12-21, 35-41` | 事实 | 高 | 沙箱方向正确，但 `webSecurity:false` 是安全面的缺口 |
| CLAUDE.md 与实现矛盾：文档称 editor/preferences 窗口用 `contextIsolation:false + nodeIntegration:true`，还引用不存在的 `config.js` | CLAUDE.md "Architecture" 节 vs `src/main/config.ts` | 事实 | 高 | 文档漂移，评估/入职时会产生错误预期 |
| IPC 契约集中在 `shared/types/ipc.ts`，四类通道，但载荷**刻意**用 `unknown[]`/`unknown`（注释明说"migration 期间宽松"） | `src/shared/types/ipc.ts:10-12` 及全文 | 事实 | 高 | 契约目前只是通道名/参数元数层，不是载荷类型层 |
| preload 通过 10 个 contextBridge 全局暴露能力（`electron`、`process` shim、`rgPath`、`fileUtils`、`path`、`commandExists`、`i18nUtils`、`ripgrep`、`uploader`、`fonts`），用 `ipc.ts` 的泛型做类型检查 | `src/preload/index.ts:26-68, 229-299` | 事实 | 高 | renderer→main 的发送侧是类型安全的，这是最大亮点 |
| renderer 全局类型是**手写**的 `global.d.ts`，与 preload 实现是两份平行维护的副本，无编译链接 | `src/types/global.d.ts` 与 `src/preload/index.ts` | 事实 | 高 | 改能力要同时改两处，可漂移 |
| 主进程 sandbox handler 已集中到 `main/ipc/*`（10 个模块），由 `registerSandboxIpcHandlers()` 在启动时统一注册 | `src/main/ipc/index.ts`、`src/main/index.ts:83` | 事实 | 高 | 这是应保留并推广的模式 |
| 但仍有大量 `ipcMain.on/handle` 散落在 `app/index.ts`、`app/windowManager.ts`、`editorBufferStore/index.ts`、`menu/actions/file.ts`、`preferences/index.ts`、`menu/actions/marktext.ts` 等处；约 24 个文件共 133 处 `webContents.send / ipcMain.on / ipcMain.emit` | grep 统计 | 事实 | 高 | 注册点不集中，加通道容易漏 |
| `ipcMain.emit` 被当作**进程内事件总线**使用（配 `onInternalChannel` 用 `ipcMain.on` 接） | `src/main/utils/internalIpc.ts`、`src/main/windows/editor.ts:396-443`、`app/windowManager.ts:421-495` | 事实 | 高 | 两套事件系统（跨进程 IPC 与进程内总线）混用同一个 `ipcMain`，是最深的概念裂缝 |
| 契约漂移实例①：`mt::shell::open-external` 同时出现在 invoke（`ret: void`）与 send 两类里，主进程也同时 `handle`（返回 boolean）和 `on` 注册 | `ipc.ts:73,170`；`main/ipc/shell.ts:6-17` | 事实 | 高 | 契约与实现已不一致（void vs boolean） |
| 契约漂移实例②：`set-user-preference`（无 `mt::`）被列进 renderer→main 的 `IpcSendChannels`，实际只在进程内 `ipcMain.emit` 使用；真正的 renderer 通道是 `mt::set-user-preference` | `ipc.ts:169,190`；`menu/actions/theme.ts:4,8`；`preferences/index.ts:190` | 事实 | 高 | 进程内事件被错误地写进了跨进程契约 |
| 契约漂移实例③：`window-toggle-always-on-top` 契约声明 `[windowId: number]`，实际进程内 emit 传的是 `BrowserWindow`；另一条 `mt::window-toggle-always-on-top` 才是 renderer 通道 | `ipc.ts:186,201`；`menu/actions/window.ts:19` | 事实 | 高 | 载荷形状与契约直接矛盾 |
| 契约漂移实例④：`watcher-*` 五条通道列在 `IpcSendChannels`，但 renderer 侧零调用（grep 无匹配），纯属进程内通道 | `ipc.ts:191-195` | 事实 | 高 | 契约里混入了"不是 IPC"的东西 |
| 命名不一致：`mt::NEED_UPDATE` 全大写 | `ipc.ts:103` | 事实 | 中 | 小但反映契约无人整备 |
| 路径/谓词逻辑重复：`common/filesystem/paths.ts`（Node 版，`isSamePathSync` 用 inode）与 `preload/index.ts:115-156`（浏览器安全版，用 `pathe` + 同步 IPC 回退）各自实现一份 `MARKDOWN_EXTENSIONS/hasMarkdownExtension/isSamePathSync/isChildOfDirectory` | 两文件对比 | 事实 | 高 | "共享层"在沙箱边界上断了，被迫复制 |
| `common/` 混装 Node 耦合模块（`common/filesystem/*` 引 `fs`/`process`）与纯模块（`common/encoding`、`common/keybinding`、`common/commands/constants`）；renderer 只敢引纯的那 4 个 | `common/filesystem/index.ts:1-3`；renderer 侧 grep | 事实 | 高 | "common 可用于三进程"的文档承诺不准确，缺内部分层 |
| 双 bootstrap 路径：设置经 URL 查询参数 + `mt::bootstrap-editor` 事件两条路送进 renderer，renderer 还用 URL 参数构造遗留的 `window.marktext`；`window.DIRNAME` 仍存 | `windows/base.ts:126-138`、`windows/editor.ts:174-181`、`renderer/src/bootstrap.ts:26-55,109-121` | 事实 | 高 | 新窗口初始化信息有两条源，易不同步 |
| renderer 的"上帝 store"：`store/editor.ts` 1895 行，含 56 处 `window.electron.ipcRenderer.*` + 19 处 `window.*` + 11 处 `window.marktext/DIRNAME` | grep + 行数 | 事实 | 高 | 未来 renderer 侧改动的主要放大点 |
| 持久化状态方向干净：renderer 防抖快照 → `update-buffer-state` invoke → main 原子写盘；但载荷类型为 `unknown` | `store/bufferedState.ts:43-56`、`main/editorBufferStore/index.ts:215`、`ipc.ts:85` | 事实 | 高 | 这是最值得先收紧类型的通道 |
| 编辑器引擎边界：renderer 5 个文件引 `@muyajs/core`，经手写 ambient shim `types/muya-core.d.ts`；`Muya` 类 `[key:string]:any` | grep + `types/muya-core.d.ts:47-52` | 事实 | 高 | 引擎边界已切换但类型极薄 |
| 测试 seam：单元测试大量 `vi.stubGlobal` 手写 stub `window.electron`/`window.path`/`ipcMain`；e2e `context-isolation.spec.ts` 断言沙箱生效；**没有任何契约测试把 `ipc.ts` 的通道名与 main 的注册/发送端绑在一起** | `test/unit/specs/*`、`test/e2e/context-isolation.spec.ts` | 事实 | 高 | 契约漂移在 CI 里完全不可见 |
| main 内部已有类型化进程内事件工具 `TypedEmitter`（WindowManager/BaseWindow/DataCenter/Preferences/EditorBufferStore 在用） | `shared/types/typedEmitter.ts` | 事实 | 高 | 迁移 `ipcMain.emit` 总线的正确工具已经存在 |

## 3. 当前摩擦（改动的放大与耦合）

**加一条新 IPC 通道今天要碰 4 个地方**：`ipc.ts`（契约）、`preload/index.ts`（包装）、`global.d.ts`（手写接口）、某个 main 文件（handler）。前两处有编译器兜底，后两处没有——`ipcMain.handle('mt::fs::…')` 和 `webContents.send('mt::…')` 都是裸字符串，Electron 的签名是 `string + any[]`。因此**契约只在 renderer 侧强制**，main 侧改错通道名、改错载荷，编译和测试都不会报。这是未来扩展性最直接的威胁：`ipc.ts` 给人"已经类型化"的安全感，实际只覆盖了一半。

**最深的概念裂缝是 `ipcMain.emit` 被当进程内总线**。`editor.ts` 用 `ipcMain.emit('watcher-watch-file', browserWindow, path)` 通知 watcher，`menu/actions/theme.ts` 用 `ipcMain.emit('set-user-preference', …)` 改偏好，`windowManager.ts` 用 `onInternalChannel` 接。这等于把"跨进程边界"和"主进程内部接线"两件事塞进同一个对象，而且这些内部通道被错误地写进了 renderer→main 的 `IpcSendChannels` 契约，载荷还写错了（`window-toggle-always-on-top` 声明 `[windowId:number]`，实际传 `BrowserWindow`）。主进程内部其实**已经有**正确工具：`TypedEmitter`（BaseWindow/WindowManager/DataCenter/Preferences 都在用）。

**共享层在沙箱边界处断了**。`common/` 的文档承诺是"三进程可用"，但 `common/filesystem/paths.ts` 引 `fs`/`process`，renderer 进不来，于是 preload 把 `MARKDOWN_EXTENSIONS`、`hasMarkdownExtension`、`isSamePathSync`、`isChildOfDirectory` 复制了一份浏览器安全版，且语义略有差异（main 用 inode 比较，preload 用同步 IPC 回退）。这是"想共享但没找到 seam"的典型症状，未来任何路径规则改动都要双写。

**renderer 侧是双表面 + 遗留全局**。新的 `window.electron.*`（类型化）与一组松散的命名全局（`window.fileUtils`、`window.path`、`window.ripgrep`、`window.uploader`、`window.fonts`…）并存，外加遗留的 `window.marktext`/`window.DIRNAME`。前者接口靠手写 `global.d.ts` 维护，后者靠运行时拼接。新增能力时这三套都要照顾。

**双 bootstrap**：窗口设置既走 URL 查询参数（`base.ts`），又走 `mt::bootstrap-editor` 事件（`editor.ts`），renderer 还据此拼出 `window.marktext`。同一份"启动信息"有三条表达。

**`shared` 类型是"诚实的占位"而非可扩展契约**：`IUserPreferences` 是 `schema.json` 的手工镜像（`preferences.ts:1-7` 自己承认要等机械生成），`BufferedState`/`BusEvents`/大量 `ipc` 载荷是 `unknown`。这在迁移期是合理的工程决策，但意味着当前类型层还接不住"新增字段/新通道"的扩展诉求。

**文档漂移**：CLAUDE.md 的 Architecture 节与 `config.ts` 直接矛盾，且引用已改名的 `config.js`。评估和新人 onboarding 会因此得出错误的边界结论。

## 4. 质量属性优先级

按本项目证据排序，而非通用清单：

1. **进程边界稳定性（IPC 契约正确性）**——这是评估主题，也是未来每个功能的必经之路。现状：契约半强制、main 侧裸字符串、漂移已在。**改善者：选项 A**。
2. **可维护性 / 局部性（改动放大）**——新通道 4 处、上帝 store、双共享路径。现状：放大明显。**改善者：选项 A 的收口步骤**。
3. **安全性**——sandbox 是 #4244 的整个目的；`webSecurity:false`、遗留 `window.marktext`/`DIRNAME`、宽松的 contextBridge 全局面都在削弱它。**改善者：选项 A 的收尾步骤 + 一次 `webSecurity:true` 的 spike**。
4. **可测试性**——已有良好的单测/e2e 基础，但缺"契约一致性"检查。**改善者：架构 lint（见第 7 节）**。
5. **可移植性（mac/win/linux）**——已处理得不错（`isOsx/isWindows/isLinux`、平台分支），不是当前主要矛盾。

性能不是本决策的驱动因素（缓冲防抖、watcher 稳定性阈值都已就位）。每一项改善都要点名它可能牺牲的属性：收口类型会增加一次性改造成本；迁移 `ipcMain.emit` 总线若做错会短暂增加主进程内耦接面（用 e2e 兜底）。

## 5. 选项

### 选项 A：围绕现有 seam 完成迁移（推荐）

把已有的三样好东西——`ipc.ts` 泛型、preload 漏斗、`TypedEmitter`——补齐到两侧，而不是引入新架构：

- **给 main 侧也套上契约**：写一个约束到 `IpcInvokeChannels/IpcSendChannels/IpcMainEventChannels` 的 `handle/on/send` 包装（类似 preload 里已有的 `invoke/send/on`），替换裸 `ipcMain.handle` 和 `webContents.send`。这是**小而深**的一步：改动集中在一个工具文件 + 逐步替换调用点，却让契约真正成为单一事实来源。
- **拆开两套事件系统**：把进程内的 `watcher-*`/`window-*`/`broadcast-*`/内部 `set-user-preference` 从 `ipcMain.emit` 迁到 `TypedEmitter` 实例（watcher 本就挂在 WindowManager 上，Preferences 本就是 TypedEmitter），并从 `IpcSendChannels` 里删掉这些误入的条目。`ipcMain` 只留给跨进程。
- **集中注册**：把 `app/index.ts`、`windowManager.ts`、`menu/actions/file.ts`、`editorBufferStore/index.ts`、`preferences/index.ts` 里的散落 handler 收进 `main/ipc/`（或与领域模块 colocate，但统一从一处接线）。
- **单一 renderer 表面**：以 `window.electron.*` 为唯一类型化入口，逐步退役 `window.marktext`/`DIRNAME` 和松散命名全局；`global.d.ts` 的接口要么从 preload 实现推导，要么加一条一致性检查。
- **机械化偏好类型**：从 `schema.json` 生成 `IUserPreferences`，消灭手工镜像漂移。
- **先修已知漂移**：`mt::shell::open-external` 双重注册/返回类型、命名统一。

**假设**：团队会继续给这个应用加 IPC 通道（近期 ripgrep、uploader、menu、spellcheck 都在动，推断成立）。**代价**：一次性重构，需用 e2e 全程兜底。**回滚**：每步都是无行为变化的纯重构，可独立 revert。**会让它变错的信号**：若项目进入纯维护期、不再新增通道，则 A 的收益会缩水（但仍值得做，因为漂移已在）。

### 选项 B：维持现状，只在出 bug 时收紧

短期可辩护：迁移进行中，避免大动一个能跑的应用；省重构成本。但代价是：漂移已经存在且会随每个新功能累积；`ipc.ts` 的"单一事实来源"给的是虚假安全感。**证据若出现则选 B**：团队明确冻结 IPC 面、只做维护。

### 选项 C：引入正式 RPC/codegen（从 schema 生成 preload + handler）

保证最强，但对约 150 条、大多是 fire-and-forget 的通道而言是过度设计，还会引入构建工具链；现有泛型包装已能拿到 80% 价值。**拒绝**——除非通道数量翻 2–3 倍，或出现第二个客户端（如 web 版）。

## 6. 建议

**选 A**。理由是：问题不在缺抽象，而在**现有抽象只覆盖了一半**——契约约束了 renderer 却漏了 main，`TypedEmitter` 存在却没接管进程内总线，`main/ipc/` 集中模式存在却没推广。补齐的成本低于重建，且每一步都可逆。

明确**不要现在做**的：

- 不要为 renderer 引入分层架构/领域层（这会和 muya 引擎迁移撞车，且上帝 store 目前是编辑器语义的锚点，应等引擎边界稳定后再拆）。
- 不要把 `common/` 拆成一个独立 workspace 包——先做包内分层（`common/node` vs `common/shared` 或等效 seam），独立包是之后的事。
- 不要急着给所有 `unknown` 载荷补全类型——从上往下的高频通道（`update-buffer-state`、ripgrep、menu、uploader）开始，其余等需求驱动。

## 7. 迁移与验证

按可逆的垂直切片推进，每片都不改行为：

1. **第一片（杠杆最大）**：加 main 侧类型化 `handle/on/send` 包装 + 一条**架构 lint**（静态检查：出现在 `ipcMain.on/handle/webContents.send` 里的通道字面量必须存在于 `ipc.ts`；`ipc.ts` 里不得有进程内通道）。此步零行为变化，先让漂移在 CI 可见。
2. **第二片**：把进程内总线（watcher/window/broadcast/内部偏好）迁到 `TypedEmitter`，从 `IpcSendChannels` 删除误入条目。用现有 e2e（tabs、watcher、菜单、偏好）验证。
3. **第三片**：把散落的 handler 收进 `main/ipc/` 注册点。
4. **第四片**：自上而下收紧高频通道的 `unknown` 载荷。
5. **第五片**：单一 bootstrap、退役 `window.marktext`/`DIRNAME`、合并 renderer 表面。
6. **最后**（独立决策）：`webSecurity:false` 的 spike、上帝 store 拆分、引擎类型 shim——仅在需求或安全审查驱动时做。

**验证标准**：

- 架构 lint 绿；`ipc.ts` 只含跨进程通道；`grep ipcMain.emit` 只剩专用总线（或零）。
- 新增一条通道的改动文件数 ≤ 2–3（契约 + 一处注册 + 可选 preload 包装），漏注册能被 lint 抓住。
- 单元测试继续走 `window.electron.*` stub（renderer 侧契约已覆盖），**新增**一个主进程侧的契约测试（用 mock 的 `ipcMain` 断言"契约里声明的每条 invoke/send 通道都恰有且仅有一个注册"，并断言 `IpcMainEventChannels` 的发送端都过类型化包装）。
- e2e `context-isolation.spec.ts` 保持绿（安全面不回退）。

## 8. 待决问题（只有这些答案会改变建议）

1. **`webSecurity:false` 是否 load-bearing？** 需要一次 spike：翻回 `true` 跑全量 e2e（PDF/图片/iframe/远程资源路径）。如果某项功能依赖它，安全建议要相应改写。
2. **进程内总线落到哪？** 是挂在 WindowManager/App 的 `TypedEmitter` 字段，还是引入一个独立类型化 bus？取决于事件是否必须跨类边界（当前 watcher 事件经 WindowManager 转发，一个 WindowManager/App 拥有的类型化 bus 大概率够用）。
3. **renderer 表面是否彻底合并到单一命名空间？** 会 break muya 内部读 `window.path` 的调用点，需要先盘点（`window.path`/`fileUtils` 等有 113 处引用）。
4. **引擎类型策略**：等 `@muyajs/core` 发布 `.d.ts` 再删 shim，还是先扩 shim？这与 muya 包的发布节奏绑定，不属于 desktop 单方面决策。

最后一句务实提醒：在动手重构前，先合并一次文档——CLAUDE.md 的 Architecture 节与 `config.ts` 的矛盾应改正，否则后续所有关于边界的讨论都会建立在错误前提上。

[EVAL:evolve-software-architecture-loaded]
