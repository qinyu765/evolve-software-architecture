# MarkText 四个演进边界的评估（只读，未改代码）

**结论先行**：四个边界目前都处于“迁移中途”而非“稳定边界”——渲染器沙箱化已落地但 IPC 契约只覆盖了一半，编辑器引擎已切到 `@muyajs/core` 但类型边界是 `any`，文件 IO 的所有权分散在 6 个主进程模块里，多窗口的“已打开文件”状态在主进程和渲染器各存一份。**不建议**做大规模结构调整或换壳（Tauri/Web），也**不建议**停在纯现状；建议一条“维持现状 + 定点收口”的路径：先删掉已经死透的旧引擎面，再完成 IPC 契约和内部事件总线的收口，最后才动文件 IO 与多窗口的所有权。这样每一步都可回滚、可验证。

---

## 1. 范围与置信度

评估对象是仓库当前形态下 MarkText 的四个长期演进边界：多窗口、本地文件 IO、编辑器引擎、Electron shell。仓库被分类为 **Electron 桌面应用（三进程）＋ pnpm 多包 monorepo**，置信度高——由 `electron-vite.config.ts`、`packages/desktop/package.json`（Electron 42）、三进程目录布局（`src/main`、`src/preload`、`src/renderer`）多信号一致确认。

置信度说明：对“现状是什么”置信度高（全部来自源码与配置直接观察）；对“未来需求是什么”置信度低——没有任何 roadmap/ADR 文件陈述下一步方向，所以建议刻意不做昂贵抽象，只做“去掉确定有害的耦合”的收口。

---

## 2. 观察事实

| 声明 | 证据 | 类型 | 置信度 | 后果 |
|---|---|---|---|---|
| 渲染器已真正沙箱化：`contextIsolation: true, sandbox: true, nodeIntegration: false`，编辑器与设置窗口都是 | `packages/desktop/src/main/config.ts:11-19, 34-41` | 事实 | 高 | 所有 Node 访问必须走 preload 桥；这决定了文件 IO 与 shell 的边界 |
| 但 `webSecurity: false` 仍开着 | `config.ts:18, 39` | 事实 | 高 | 同源策略被关掉，靠 `will-navigate`/`windowOpenHandler`/`will-attach-webview` 拒绝来兜底（`app/index.ts:133-143`），是一个未收口的信任面 |
| preload 是唯一桥，暴露 `window.electron/fileUtils/path/process/ripgrep/...` | `preload/index.ts:286-296` | 事实 | 高 | 桥面即契约面，渲染器所有跨进程访问都从这里过 |
| IPC 有单一类型契约 `shared/types/ipc.ts`，四类通道；但大量 `unknown`，注释写明“迁移期间故意宽松” | `shared/types/ipc.ts:1-18` | 事实 | 高 | 契约存在但只半成品，`unknown` 给的是“假安全” |
| 新沙箱 handler 集中在 `main/ipc/*` 经 `registerSandboxIpcHandlers` 注册 | `main/ipc/index.ts:12-23` | 事实 | 高 | 新面是集中的，旧面不是 |
| 旧 IPC 面仍散落：`ipcMain.on('mt::…')` 遍布 `windowManager.ts`、`app/index.ts`、`menu/actions/file.ts`、`dataCenter`、`editorBufferStore` | 各文件内联 | 事实 | 高 | 同一批 `mt::` 通道两套注册方式并存 |
| `ipcMain.emit(...)` 被当成主进程内部事件总线用，配 `onInternalChannel` | `main/utils/internalIpc.ts:8-13`；`windowManager.ts:421-435` | 事实 | 高 | 字符串通道的内部 pub/sub，无编译期检查；源码自己标了 HACK/TODO #1034/#1035（`windowManager.ts:112-116, 368`、`watcher.ts:14`） |
| 编辑器引擎已是 `@muyajs/core`（packages/muya 的 TS 重写），渲染器直接 import | `renderer/src/components/editorWithTabs/editor.vue:82-140`、`util/exportHtml.ts`、`util/pdf.ts`、`util/markdownToHtml.ts` | 事实 | 高 | 引擎换型已落地，旧引擎无运行时消费 |
| 引擎类型边界是手写 `.d.ts`，`Muya` 声明为 `[key: string]: any`，`editor.vue` 用 `MuyaInstance = any` | `types/muya-core.d.ts:47-52`、`editor.vue:172-175` | 事实 | 高 | 引擎边界现在是 `any`，API 变更只在运行时暴露 |
| `@muyajs/core` 的 `exports` 指向 `./src/index.ts`（源码），安装时不带构建好的 d.ts | `packages/muya/package.json:10-16` | 事实 | 高 | 引擎是“源码级 workspace 依赖”，不是版本化发布产物 |
| 旧引擎 `packages/muyajs`（`@marktext/muyajs`）在全仓库**零运行时 import**；只剩 `muya.d.ts` 死声明、`muya` 别名和 workspace 依赖 | 全仓 grep `from 'muya…'` 无命中；`types/muya.d.ts`、`electron.vite.config.ts:38/58/84`、`tsconfig.base.json:29` | 事实 | 高 | 旧引擎可以整包删除而不影响运行；现存的别名/依赖是纯噪声 |
| 文档读取/写入（编码猜测、换行归一、BOM、原子写）在主进程 `filesystem/markdown.ts`；通用 `mt::fs::*` 是 `main/ipc/fs.ts` 的薄封装；watcher（chokidar）在主进程推 `mt::update-file/update-object-tree` | `filesystem/markdown.ts:69-159`、`filesystem/index.ts:25-49`、`ipc/fs.ts`、`filesystem/watcher.ts` | 事实 | 高 | 文件 IO 有两条渲染器→主进程路径：文档路径（主进程驱动）与通用 fs 工具路径（渲染器驱动） |
| 崩溃恢复：每窗口一个 `{uuid}_editor_buffer_store.json`，渲染器 1s 去抖全量快照（editor+project+layout）写回主进程 | `editorBufferStore/index.ts:178-199`、`renderer/src/store/bufferedState.ts:6-7, 43-56` | 事实 | 高 | 窗口身份、快照格式、删除时机三件事耦合在一起 |
| 窗口身份 `restoreBufferId` 是通过 `as unknown as { restoreBufferId }` 挂在 BrowserWindow 上的 | `editor.ts:141-145`、`editorBufferStore/index.ts:189` | 事实 | 高 | 窗口身份没进类型模型，靠强转穿行 |
| 多窗口路由：`WindowManager` 维护 `Map<windowId, BaseWindow>`＋活动列表＋打分路由；`EditorWindow` 另存一份 `_openedFiles/_openedRootDirectory` 影子状态 | `windowManager.ts:256-305`、`editor.ts:449-468, 517-520` | 事实 | 高 | “已打开文件”在主进程和渲染器 Pinia store 双写，是漂移风险点 |
| 保存流程：渲染器发 `mt::response-file-save`，主进程 `menu/actions/file.ts:handleResponseForSave` 弹对话框并写文件；源文件自己 TODO 说要搬到 editor window 归属 | `menu/actions/file.ts:36-38, 157-225` | 事实 | 高 | 保存逻辑挂在“菜单动作”文件里，而不是某个文件/窗口服务 |
| 测试：112 个测试文件几乎全是渲染器单元 spec（Pinia 逻辑、PDF/导出纯函数），有 `buffer-store-durable`、`encoding`、`dangerous-executable-file`；E2E 覆盖编辑器行为与 `context-isolation`、`xss`；**没有**主进程 WindowManager/EditorWindow 生命周期、watcher、保存竞态的测试 | `test/unit/specs/*`、`test/e2e/*` 清单 | 事实 | 高 | 最脆的跨进程/多窗口路径恰好是测试盲区 |
| CLAUDE.md 的“架构”一节写的是 `contextIsolation: false + nodeIntegration: true`，还引用不存在的 `config.js`，与 `config.ts` 实测相反 | `CLAUDE.md` 架构节 vs `config.ts:11-19` | 事实 | 高 | 文档与实现漂移，可能误导后人改回不安全配置 |

---

## 3. 四个边界的现状与摩擦

### 3.1 多窗口

现状：`WindowManager` 是事实上的窗口注册表＋路由中心，`EditorWindow` 是窗口生命周期＋“该窗口打开了哪些文件”的持有者，`App._openPathList`（`app/index.ts:519-640`）做新窗口/复用窗口/新目录的三层路由决策。恢复场景按“每个 buffer store 文件一个窗口”重建（`app/index.ts:386-410`）。

摩擦（事实＋推断）：
- **“已打开文件”双写**。渲染器 Pinia store 是 tab 的真相，主进程 `_openedFiles` 只为了 watcher 和路由再存一份。重命名、另存为、关闭 tab 都要靠 `mt::window-tab-closed` / `window-change-file-path` 这类字符串通道去同步两份状态。任何一条漏发，watcher 就跟文件脱钩。这是多窗口边界最确定的漂移源。
- **窗口身份不进类型**。`restoreBufferId` 靠强转挂在 BrowserWindow 上，`WindowManager` 里的 `handleClose` 还要再拿 `getWindowsByType('editor')` 反查。未来给窗口加“持久身份/崩溃恢复/会话分组”时，这个强转会变成连锁修改。
- 活动窗口用**数组**模拟 MRU（`windowManager.ts:16-59`），代码里自己注释“几个窗口不需要链表”——在“少数窗口”约束下是合理的，但它是隐式假设，窗口多了会退化。

### 3.2 本地文件 IO

现状：真正的“文档 IO”语义（编码猜测、换行归一、BOM、原子写、崩溃安全）集中在 `filesystem/markdown.ts`＋`filesystem/index.ts`，质量不错（`write-file-atomic` 带 fsync，注释解释了 #3786/#3828 的断电窗口）。但保存动作的编排（对话框、重命名、最近使用、watcher 联动）在 `menu/actions/file.ts`，恢复在 `editorBufferStore`，watcher 在 `filesystem/watcher.ts`，通用 fs 薄封装在 `ipc/fs.ts`，渲染器还有一条 `window.fileUtils` 通用路径。

摩擦：
- **所有权分散**。一个“保存”动作横跨渲染器 store → `mt::response-file-save` → `menu/actions/file.ts` → `filesystem/markdown.ts` → `ipcMain.emit`（通知 watcher/最近使用）→ 再回推渲染器 `mt::tab-saved`。`file.ts:36-38` 的 TODO 自己承认“save/save-as 应该搬到 editor window”。这是当前变更放大最明显的地方。
- **两条 fs 路径**（文档路径 vs `window.fileUtils` 通用路径）错误处理和“谁拥有路径”的语义不一致。
- 原子写已经做对了；这部分**不需要**结构调整，是四块里最不该动的。

### 3.3 编辑器引擎

现状：渲染器已直接消费 `@muyajs/core`，引擎自带 CommonMark/GFM 一致性锁定（`packages/muya/CLAUDE.md`），并有自己的 eslint/madge/vitest。桌面侧用 `muya-core.d.ts` 把 `vue-tsc` 挡在引擎源码之外（`muya-core.d.ts:1-18` 解释了原因：引擎的 `exports` 指向源码，没有安装期 d.ts）。

摩擦：
- 边界是 **`any`**（`Muya` 的 index signature、`editor.vue` 的 `MuyaInstance = any`）。引擎 API 演进时，桌面侧只有在运行时才能发现破坏——编译期保护只覆盖 `.d.ts` 里枚举过的那几个成员。
- 引擎是**源码级 workspace 依赖、不发布**。这意味着“引擎边界”目前只是 Vite 编译期的边界，没有版本化语义。对单仓内协同是合理的，但对“桌面端与引擎独立演进”不是真正的边界。
- 旧引擎 `packages/muyajs` 已经**完全死透**（全仓零 import），`muya` 别名、`muya.d.ts`、`@marktext/muyajs` 依赖都成了纯噪声——这是最便宜、最安全的一步清理。

### 3.4 Electron shell

现状：三进程模型清晰，preload 是唯一桥，`shared/types/ipc.ts` 是单一契约源。shell 边界的长期质量基本取决于“契约完成度”。

摩擦：
- **两套 IPC 面并存**。新面（`main/ipc/*`＋typed preload）是集中的；旧面（散落的 `ipcMain.on('mt::…')`＋`ipcMain.emit` 内部总线）是分散的、字符串化的。契约注释说“迁移到 5–8 步”，说明这是**已知的迁移中途**，不是稳定态。
- `ipcMain.emit` 被当内部 pub/sub 用，是 shell 边界里最隐蔽的耦合：它让主进程模块之间用“跨进程通道”的名义做“进程内调用”，既无类型也不可被 grep 简单审计。
- `webSecurity: false`（推断：为了让沙箱渲染器能加载任意本地 `file://` 图片）是用“关掉同源策略”来换取本地资源访问的粗糙手段；目前靠 `will-navigate`/`windowOpenHandler`/webview 拒绝兜底，但这是一个未收口的攻击面，长期应有 `marktext://` 自定义协议或 `protocol.handle` 取代。
- 文档漂移（CLAUDE.md 与 `config.ts` 相反）会让 shell 边界被后人无意破坏。

---

## 4. 质量属性优先级

这是本地桌面编辑器，有真实信任边界（打开任意 .md → 渲染 → 可能加载本地图片 / 点击链接 → `shell.openPath`）。按对本决策的支配度排序：

1. **安全**——信任边界（文件内容、本地路径、`webSecurity:false`、链接打开）。验证：`context-isolation.spec.ts`、`xss.spec.ts` 已有；缺 `webSecurity:false` 的针对性回归。
2. **可维护性 / 变更局部性**——四块都“迁移中途”，未来改动会继续在双 IPC、双状态、`any` 边界上放大。验证：把 lint/grep 护栏加进 CI，禁止新 `ipcMain.emit` 和越界 `ipcMain.on`。
3. **可测试性**——最脆的多窗口/保存竞态路径恰好无主进程测试。验证：给 `WindowManager`/`EditorWindow` 补带 BrowserWindow 假件的主进程单测。
4. **可移植性 / 可操作性**——多平台 watcher 怪癖、原子写、升级器；现状处理得不错，是**次要**目标，不该为它做重抽象。
5. **性能**——启动恢复、watcher 规模；当前无证据是瓶颈，不作为决策驱动。
6. **扩展性**——muya 已经内置 OT 数据结构（协作编辑的潜在变化点），但没有任何落地需求信号，**不做**预先抽象。

关键取舍：**安全与可维护性优先，代价是暂时不动文件 IO 语义层和引擎内部**；扩展性最后，避免为一个假设的“协作编辑/多后端”提前建层。

---

## 5. 选项对比

### 选项 A：维持现状（只做收尾，不做结构调整）

即：继续当前的增量迁移，删除已死代码，补齐文档与护栏，但保留三进程模型、主进程文件 IO、直接消费 `@muyajs/core`、`ipcMain` 现有组织。

- **边界与所有权**：不变。
- **收益**：成本最低，风险最低，每步独立可回滚；不打断任何进行中的引擎/沙箱工作。
- **代价/风险**：双 IPC、双状态、`any` 引擎边界的长期变更成本仍在；只是不再恶化。
- **验证**：CI 护栏＋新增少量主进程测试。
- **何时判定此选项错误**：如果后续真的出现“第二引擎后端”或“多窗口协作”需求，`any` 边界和影子状态会立刻成为阻塞。

### 选项 B：结构调整（建立三条深缝，不换壳）

在 A 的基础上，建立三条有杠杆的缝：

- **B1 完成 IPC 契约收口**：所有通道进 `ipc.ts`；handler 集中注册（`main/ipc/*` 或一个注册 helper）；**废除 `ipcMain.emit` 内部总线**，改用已有的 `TypedEmitter` 或 `CommandManager` 做进程内类型化事件；lint 禁止越界注册。
- **B2 收口文件/窗口所有权**：把“保存/重命名/另存为/恢复”从 `menu/actions/file.ts` 迁到一个文档服务，渲染器只走类型化通道；“已打开文件”由主进程单一持有，渲染器通过 reconcile 协议同步（而不是双写）。
- **B3 形式化引擎边界**：等 `@muyajs/core` 产出构建版 d.ts 后，删除 `muya-core.d.ts`，用真实类型替换 `MuyaInstance = any`；在此之前**不**建 host 适配层。

- **收益**：未来改动局部化；契约可测试；引擎边界可编译期保护。
- **代价/风险**：迁移期有双轨并存风险；B1 范围大（约 150 个通道条目）；需要纪律避免“为抽象而抽象”。
- **验证**：契约测试（每个契约条目都有 handler 且反向成立）、进程内事件总线类型化、主进程假件单测、多窗口 E2E。

### 选项 C：换壳（Tauri / 纯 Web）—— 建议拒绝，不进入短期路线

- **证据**：当前所有 IO 语义（编码猜测、换行归一、BOM、watcher、崩溃恢复）都在主进程 Node 里，`@muyajs/core` 与桌面是 workspace 源码耦合；换 Tauri 意味着重写整个文件 IO 层和渲染器桥。
- **为什么拒绝**：成本极高、无用户可见收益、且 `webSecurity:false` 这类问题在 Tauri 下同样要解决（本地资源访问）。**保留为“重新审视条件”**：若未来出现“必须缩小安装包/内存、或需要 iOS/Android”的硬需求，再重开。当前没有证据支持。

---

## 6. 建议（演进路径，按优先级）

推荐 **选项 B 的“B1 前置、B2 随后、B3 等时机”**，但每一步都从 A 的可回滚步骤进入。排序依据：先做“确定有害、零风险”的清理，再做“耦合最高”的收口，最后才碰“需要外部条件成熟”的引擎边界。

1. **立即：删除死透的旧引擎面**（最便宜的一步）。移除 `packages/muyajs`、`@marktext/muyajs` 依赖、`muya` 别名、`types/muya.d.ts`。全仓 grep 已证明零 import，回滚只是一次 revert。
2. **立即：修正文档漂移**。把 CLAUDE.md 架构节改为与 `config.ts` 一致的 `contextIsolation:true/sandbox:true`，并注明 `webSecurity:false` 的现状与原因。
3. **近期：收口 IPC 契约（B1）**。先拿**一条端到端流做垂直切片**（建议选 watcher 或保存流）：把它从 `ipcMain.emit` 内部总线迁到类型化 `TypedEmitter`，同时把对应通道在 `ipc.ts` 里收紧成具体类型。证明缝可用后，再以“禁止新增 `ipcMain.emit`/裸 `ipcMain.on`”的 CI 护栏逐步fan out。
4. **近期：把 `webSecurity:false` 换成 `marktext://` 自定义协议**（或至少把它的必要性用注释钉死）。这是安全优先级下的唯一硬改动，但要先用 `protocol.handle` 验证本地图片加载不回归。
5. **中期：收口文件/窗口所有权（B2）**。把 `menu/actions/file.ts` 里的保存/重命名/移动迁到文档服务；“已打开文件”单一持有＋reconcile。这一步**最后做**，因为它动的是用户最敏感的保存路径，且当前实现原子写已经正确。
6. **暂缓：引擎边界形式化（B3）**。等 `@muyajs/core` 产出构建 d.ts（`muya-core.d.ts` 注释自己写了删除条件），再删手写声明。**在此之前不要**给引擎套 host 适配层——那会在 `any` 之上再加一层 `any`。

明确**不要现在做**的事：换 Tauri/Web 壳、为协作编辑建 OT 传输层、给“第二引擎后端”建通用抽象、给多窗口建通用会话框架。这些的信号一旦出现（真实的第二后端需求、包体/内存硬预算、移动端目标），再按“重新审视条件”重开。

---

## 7. 迁移与验证

- **回滚**：每一步都是可独立 revert 的提交；删除死代码和文档修正本身是纯减法。
- **护栏（CI 可执行）**：grep/lint 规则禁止新 `ipcMain.emit(` 与越界 `ipcMain.on(`；契约一致性测试——遍历 `ipc.ts` 的四类通道，断言每个 `invoke/send/sync/event` 都有 handler、且每个 handler 都在契约里登记。
- **主进程单测**：用 BrowserWindow/`webContents` 假件直接测 `WindowManager`（窗口增删、活动窗口 MRU、`findBestWindowToOpenIn` 打分、`forceClose` 的 watcher 释放）和 `EditorWindow`（`_openedFiles` 在重命名/另存为/关闭 tab 后的收敛）。这是当前最大盲区。
- **E2E**：Playwright 已能驱动多窗口；补“第二个窗口打开同一文件 → 关闭 → watcher 是否正确释放”“外部修改文件 + autosave 竞态”的场景。
- **完成判据（可观察）**：`ipcMain.emit` 调用数为 0；契约一致性测试通过；`_openedFiles` 只在主进程一个 owner 内读写；`webSecurity:false` 消失或由自定义协议取代且图片回归通过；CLAUDE.md 与 `config.ts` 一致。
- **回归信号（推翻建议的条件）**：出现真实的第二引擎后端 / 移动端目标 / 协作编辑需求；或 `@muyajs/core` 长期不产出构建 d.ts 导致 `any` 边界开始造成实际故障。

---

## 8. 开放决策（只有这些问题的答案会改变建议）

1. `webSecurity:false` 具体是为了哪些本地资源路径？（未知，需最小实验确认——用 `protocol.handle` 替换后跑图片加载回归。）若它还被其他代码依赖，B1 之后的协议替换顺序要调。
2. `@muyajs/core` 是否计划在近期产出构建版 d.ts？（未知，决定 B3 的时机与是否值得先做局部类型收紧。）
3. 是否存在“协作编辑 / 多设备同步”的产品意图？（未知，决定要不要提前为 OT 状态留缝——目前建议不留。）
4. 旧 `@marktext/muyajs` 包删除是否会影响 website 或其他仓库外消费者？（当前仓库内零 import，但仓库外无证据，删除前需确认发布面。）

[EVAL:evolve-software-architecture-loaded]
