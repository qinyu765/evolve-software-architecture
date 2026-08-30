我已核对完仓库结构、关键实现、配置、测试与文档。先说结论，再给证据和逐域方案。有一点需要透明：本会话 `Bash`/`git` 不可用，因此 Git 历史的核对只能基于会话开始时的提交列表和代码注释/文档中**已入库**的 issue/PR 编号（#4244、#4406、#3786/#3828、#4859、#1034/#1035 等），不能重新跑 `git log`。下面所有结论都标注了可定位的 `文件:行号` 证据。

## 结论摘要

MarkText 已完成最大的一次边界重构：渲染进程沙箱化（`contextIsolation:true / sandbox:true / nodeIntegration:false`）、monorepo 化、`@muyajs/core`（TS 版 muya）落地。**现在最值得稳定的是四条已存在但"半成品"的边界；最应该延后的是一批没有现实驱动力的"彻底重构"。**

稳定（便宜、承重、风险低）：

1. **IPC 契约**（`src/shared/types/ipc.ts`）——把它真正收口成唯一事实源，补齐 `unknown` payload 类型，并**停止新增不经过它的通道**。
2. **窗口身份**（`win.id` + `restoreBufferId`）——消除 `as unknown as { restoreBufferId }` 的裸 cast。
3. **文档读写契约 + 保存协议**——统一 `MarkdownDocument` 双份形状，把保存/重命名从"send + push 无 ack"改成 `invoke` 有 ack。
4. **preload 门面**——移除/收紧对渲染器的裸 `ipcRenderer` 直通，只留命名门面。
5. **旧引擎退役**——删除已零运行时引用的 `@marktext/muyajs` 依赖、`muya` 别名和 `muya.d.ts`。

延后（等真实驱动力出现再做）：

1. 通用窗口注册表 / 按 windowId 路由的 IPC（#1034/#1035 终局）。
2. 带冲突解决的文档服务（OT/云同步）——muya 已有 OT 原语但无传输层。
3. 引擎内置 typings 采纳 + `ag-*`→`mu-*` 主题/DOM 迁移。
4. 完整最小权限/按来源的 IPC 授权模型——门面允许名单能拿到 90% 收益。
5. `webSecurity:false` 的翻转——要先做 spike，不能盲开。

---

## 一、证据核对：现状事实

**沙箱已完成，但 `webSecurity` 被关闭。** `packages/desktop/src/main/config.ts:11-20`（编辑器窗口）和 `:34-41`（偏好设置窗口）都是 `contextIsolation: true, sandbox: true, nodeIntegration: false`，但两处都写了 `webSecurity: false`（`config.ts:19`、`:40`），且没有任何注释说明原因。对一个渲染任意 HTML/图片/外链、还粘贴 Google Docs HTML（#4699）的 markdown 编辑器来说，这是有实义的安全面加宽。

**IPC 契约已经存在，但类型是"迁移中"状态。** `src/shared/types/ipc.ts` 定义了四类通道（invoke/send/sync/main-event），但大量 payload 仍是 `unknown`/`unknown[]`，文件头注释自己写着"concrete types tighten as each handler/caller converts in commits 5–8"。preload 暴露了两层东西：**命名门面**（`fileUtils`、`path`、`shell`、`clipboard`、`windowControl` 等，`preload/index.ts:70-227`）**和裸的 `ipcRenderer` 包装**（`preload/index.ts:38-68`），后者让渲染进程能直接 `send/invoke` 任意已注册通道。渲染层确实大量使用这个裸通道——`store/editor.ts` 一处就有几十个 `window.electron.ipcRenderer.send/on/invoke` 调用。

**窗口身份是双重的，且靠裸 cast 传递。** 窗口 ID 用 Electron 的 `win.id`，但会话缓冲持久化用独立的 UUID，因为 `win.id` 在窗口关闭后会被复用（`windows/editor.ts:139-145`）。这个 UUID 被塞进 `(win as unknown as { restoreBufferId: string })`，在 `editorBufferStore/index.ts:189` 和 `windowManager.ts:384` 重复出现。这是数据完整性关键不变量，却没有任何类型保护。

**主进程内部把 `ipcMain.emit` 当进程内事件总线用。** `windowManager.ts:367-419` 用裸 `ipcMain.on` 处理 `mt::window-add-file-path` 等，并标注 "HACK: Don't use this event! Please see #1034 and #1035"；同一份协调又通过 `utils/internalIpc.ts:8-13` 的 `onInternalChannel` 用 `ipcMain.emit(...)` 转发。文件保存成功后也是 `ipcMain.emit('window-add-file-path', ...)`、`ipcMain.emit('window-file-saved', ...)`（`menu/actions/file.ts:209-216`）。`ipcMain` 语义上是 renderer↔main 的，把它当 main 内部总线是 #1034/#1035 遗留的接缝。

**保存协议是"send + push"无确认。** 渲染器 `store/editor.ts:512-529` 用 `send('mt::response-file-save', …)` 发内容；main 侧 `menu/actions/file.ts:458` 用 `ipcMain.on` 接，写盘成功后 `webContents.send('mt::tab-saved'/'mt::set-pathname')` 推回，失败推 `mt::tab-save-failure`。请求/响应被拆在 `send` 与 `main-event` 两条通道上，没有 per-save 的 Promise/ack/顺序保证。最近的修复簇（#4859 flush-before-save、#3803、#3786 掉电持久化）都堆在这个接缝附近。写盘本身已经做得对：`filesystem/index.ts:25-49` 用 `write-file-atomic` 先 fsync 再 rename。

**引擎已切换到 `@muyajs/core`，但适配层散落在 editor.vue 里。** `components/editorWithTabs/editor.vue:82-113` 从 `@muyajs/core` 导入 Muya、插件、locale；`:355-362` 把新引擎的 `blockName` 映射回旧 `functionType`；`:390-426` 的 `adaptSelectionChange` 把新 selection payload 转成旧 `{start,end,affiliation}` 形状；`:289-340` 用 `SyntheticHistory` + `engineHistoryByTab` 桥接新旧历史形状。类型边界靠手写的 `types/muya-core.d.ts`（`Muya` 类 = `[key:string]: any`）切图，注释写明"等 `@muyajs/core` 发布 `lib/types` 后删除"。

**旧 `@marktext/muyajs` 已死但没删。** 桌面 `package.json:62` 仍声明 `"@marktext/muyajs": "workspace:*"`；`electron.vite.config.ts:38/58/85` 和 `tsconfig.base.json:29` 仍保留 `muya` → `../muyajs` 别名；`types/muya.d.ts` 整文件还在。但我 grep 了 `from 'muya`、`from "muya`、`import … muya/lib` 的运行时 import，**零命中**（剩下的都是注释）。`tsconfig.base.json:32` 的 `main_renderer/*` 别名也是零使用。

**文档漂移。** 根 `CLAUDE.md` 的架构小节仍写"editor and preferences windows use contextIsolation: false + nodeIntegration: true (see packages/desktop/src/main/config.js)"——`config.js` 已不存在，实际是 `config.ts` 且 `sandbox:true`。`packages/website/content/docs/dev/ARCHITECTURE.md:5-28` 还是 monorepo 之前的 `src/` 布局，且写"Muya … is currently still JavaScript … requires a core refactoring"。相比之下 `IPC.md:1-100` 是最新的。

**测试面足够做回滚护栏。** 桌面有 60+ e2e spec（含 `context-isolation.spec.ts`、`xss.spec.ts`、`buffer-store-durable.spec.ts`、`flush-before-save.spec.ts`、`dangerous-executable-file.spec.ts`）和 100+ unit spec（含 `synthetic-history.spec.ts`）；`packages/muya` 有自己的 70+ e2e + CommonMark/GFM 符合性套件。这意味着下面每条迁移路线都能挂到可执行验证上。

---

## 二、稳定 vs 延后的总判断

| 边界 | 状态 | 建议 | 理由 |
|---|---|---|---|
| IPC 契约 (`ipc.ts`) | 已存在、半类型化 | **稳定** | 已是唯一事实源，typecheck 即迁移清单 |
| 窗口身份 (`win.id`/`restoreBufferId`) | 裸 cast、无类型 | **稳定** | 缓冲持久化按它寻址，错了丢数据 |
| 文档读写契约 + 保存 ack | 双份形状、send+push | **稳定** | 数据完整性 + 可测试性 |
| preload 门面 / 裸 ipcRenderer | 门面已有、直通泄漏 | **稳定** | 安全面，低改动高收益 |
| 旧 muyajs 依赖/别名 | 零运行时引用 | **稳定（退役）** | 纯删除，消除"哪个引擎"的困惑 |
| `webSecurity:false` | 关闭、无注释 | **spike 后稳定** | 安全，但需实验验证再翻 |
| 通用窗口注册表 / scoped IPC | #1034/#1035 接缝 | **延后** | 无第三个窗口类型的现实驱动 |
| 文档服务（冲突解决/云同步） | 无 | **延后** | 要先塌缩 opened-files 双源 |
| 引擎内置 typings / 主题 DOM 迁移 | 手写 .d.ts 切图 | **延后** | 等 muya 发布 lib/types |
| 完整最小权限能力模型 | 无 | **延后** | 门面允许名单先拿到大头 |
| 文档 (CLAUDE.md/ARCHITECTURE.md) | 漂移 | **稳定（修正）** | 边界定义本身是契约的一部分 |

---

## 三、逐域方案比较

### A. 窗口能力

**现状。** `windows/base.ts:16-31` 定义 `WindowType`（BASE/EDITOR/SETTINGS）和生命周期；`BaseWindow._buildUrlWithSettings`（`base.ts:110-140`）用 URL query 参数（`wid/type/cff/cfs/hsb/theme/tbs`）做启动前引导；`EditorWindow` 混入了文件打开调度、opened-files 跟踪、watcher 接线、缓冲恢复、窗口打分（`getCandidateScores`）——窗口类和"文件会话"职责高度耦合。未来加第三个窗口类型（导出预览、查找面板、关于页）或标签页拖出新窗口时，要复制的面很大。

**方案 A（现在小步稳定）：** 引入类型化的 `WindowIdentity { id, type, restoreBufferId }`，把 `restoreBufferId` 从裸 cast 变成 `BaseWindow` 的真实字段；把 `findBestWindowToOpenIn` 的打分逻辑下放为 `EditorWindow` 的策略方法。成本低（纯类型重构 + 少量移动），风险低（编译期可见），回滚是单提交 revert。

**方案 B（维持现状）：** 只把现有不变量写进文档。零成本，但 `restoreBufferId` 的 cast 继续散布三处，新窗口类型出现时复制粘贴 `_buildUrlWithSettings` + bootstrap 协议。

**方案 C（彻底重构）：** 通用窗口注册表 + 所有通道按 `windowId` 显式路由（#1034/#1035 终局）。这是正确的终点，但当前只有两种窗口，没有第三个消费者来验证抽象，且改动触及 WindowManager/menu/App/CLI/renderer router 全链路，回归风险高。

**权衡。** A 换取可修改性与可靠性，几乎不损失性能与交付速度；C 换未来的可扩展性，但今天付费买不到回报。**推荐 A 做身份与策略解耦，C 延后到真有第三个窗口类型或 tab-tearing 需求时。**

**不改变的后果：** 加新窗口类型时，开发者会在 `_buildUrlWithSettings` 的 URL 协议和 `mt::bootstrap-editor` push 之间二选一、各写各的，bootstrap 协议继续无文档漂移；`restoreBufferId` 一旦被某处漏传，表现为"崩溃后标签页恢复错窗口/恢复失败"，且难排查。

### B. 文件工作流

**现状。** 读路径 `loadMarkdownFile`（`filesystem/markdown.ts:90-159`）做编码探测+换行归一+尾换行处理，内部有 `TODO: Use streams`（`:97-98`）；写路径已做到掉电持久化。但保存是"send + push 无 ack"（见上文），重命名/移动也是 `send('mt::rename')` + push 回 `mt::set-pathname`。opened-files 在渲染器 tabs 与 main `EditorWindow._openedFiles` **双源**维护，靠 `mt::window-add-file-path`/`window-change-file-path` 事件对同步。self-edit 抑制是时间窗 + mtime 启发式（`watcher.ts:399-458`），对云盘有专门注释（`:435-437`）。

**方案 A（稳定契约 + 保存改 ack）：** 把"打开的 markdown 文档"和"保存结果"的规范形状收敛到 `shared/types/files.ts`（目前 `main/filesystem/markdown.ts` 的 `MarkdownDocumentRaw` 与 `shared/types/files.ts` 的 `MarkdownDocument` 是两套）；把 `response-file-save`/`save-as`/`rename` 从 `send` 升级为 `invoke`，`ret` 返回 ack（新 pathname、保存后 mtime），错误作为 reject 返回而非 push。保留 fire-and-forget 只给真正的通知。

**方案 B（维持现状）：** 继续 send+push，靠现有 flush-before-save 补丁。零成本，但每次新增"全部保存/多文件保存/外部变更冲突"都要重新推导事件顺序。

**方案 C（延后的大重构）：** 主进程文档注册表 + 冲突解决 + OT 传输。muya 已具备 OT 原语（`packages/muya/CLAUDE.md`），但 opened-files 双源还没塌缩，现在做会建在流沙上。

**权衡。** A 的核心质量属性是可靠性（保存结果可等待、可断言）与可测试性（`invoke` 的返回可以直接写进 unit/e2e），代价是一次协议迁移；但 `ipc.ts` 的类型系统会把所有 call site 变成 typecheck 清单，回滚只需保留旧 `send` 通道做过渡包装。**推荐 A，C 延后。**

**不改变的后果：** 数据完整性继续依赖"事件顺序 + flush hack"的口头约定；"保存到底成功没有"没有一手返回值，未来做 save-all、autosave 冲突提示、跨窗口同步时，每个特性都要重新发明一次确认机制。

### C. 编辑器引擎演进

**现状。** 引擎切换已完成，但代价是一层散落在 `editor.vue` 里的**旧形状模拟适配层**（functionType 映射、selection 适配、合成历史），类型边界是 `[key:string]: any` 的手写 `.d.ts`。旧 `@marktext/muyajs` 零运行时引用但未删。

**方案 A（退役旧引擎 + 抽出适配层）：** 删除 `@marktext/muyajs` 依赖、`muya` 别名、`muya.d.ts` 和死别名 `main_renderer/*`；把 `adaptSelectionChange`、`CONTAINER_FUNCTION_TYPE`、`SyntheticHistory` 搬进一个命名的 `engineAdapter` 模块，定义类型化的 `IEngineAdapter`，让桌面↔引擎接缝变成"markdown 字符串进出 + 类型化事件 payload"的单文件契约。成本低（无运行时 import 可删，别名删除由 typecheck + 60+ e2e 兜底），`synthetic-history.spec.ts` 已能锁行为。

**方案 B（维持现状）：** 保持适配层内联在 1800 行的 Vue 组件里，等 `@muyajs/core` 发布内置 typings 再一起动。

**方案 C（激进）：** 现在采纳 muya 内置 typings + 迁移 `ag-*`→`mu-*` 主题/DOM。主题迁移是一整个阶段，有大量视觉回归风险，注释里也写明"theme migration is a separate phase"，不该被这次决定绑架。

**权衡。** A 换可修改性与可测试性，几乎无风险；C 换长期类型卫生，但今天 `@muyajs/core` 还没发 `lib/types`，做了就是重复劳动。**推荐 A，C 延后。**

**不改变的后果：** 旧引擎包继续作为"第二个引擎"留在依赖树里误导后来者（CLAUDE.md 说 retiring，但别名还指向它）；下一次引擎升级时，接缝的反向工程（哪个字段是旧的、哪个是新的）要重新做一遍。

### D. Electron shell 能力

**现状。** 沙箱这 80% 已做完，但剩两处：`webSecurity:false`（无注释）；preload 把裸 `ipcRenderer` 直通给渲染器。后者意味着**任何**渲染进程代码（含被 DOMPurify 漏过的 XSS）都能驱动所有已注册特权通道——文件读写删、shell 打开、剪贴板、窗口控制。类型契约保护的是"调用正确性"，不是"授权"。`webSecurity:false` 又把同源/混合内容防护一并关掉。

**方案 A（收口桥面 + spike 后决定 webSecurity）：** 把 preload 从"暴露通用 ipcRenderer 包装"改成"只暴露命名门面"，裸 `ipcRenderer` 要么删除要么加 per-channel 允许名单；对 `webSecurity:false` 做 spike（先开 true，跑 `xss.spec.ts` 和图片加载相关 e2e，看本地 `file://` 图片/导出是否破损），有证据后再翻，并加 CSP。

**方案 B（维持现状）：** 保留裸包装 + `webSecurity:false`，依赖 DOMPurify + sandbox。零成本，但把防线押在"消毒器永远不出错"这个强假设上。

**方案 C（完整最小权限）：** per-window/per-origin IPC 授权、能力模型、安全评审门禁。收益最大，但改动全链路、且当前没有第二个可信源/不可信源窗口来验证威胁模型，属于过度工程。

**权衡。** A 的核心质量属性是安全性，成本是一次机械迁移（约 50 个 call site，typecheck + e2e 兜底）；门面模式已在 `fileUtils/windowControl` 上验证过。**推荐 A，C 延后；`webSecurity` 单独走 spike。**

**不改变的后果：** 沙箱保证渲染器不能 `require('node')`，但一次 XSS 仍可通过桥面读写/删除任意文件、读剪贴板、弹 shell；`webSecurity:false` 静默放大这个面。这是四个域里唯一的真安全姿态缺口，不只是整洁度问题。

---

## 四、可验证的渐进迁移路线

按"每步独立可回滚、每步有可执行验证"排序，先便宜后昂贵：

1. **删死代码（半天级）。** 删 `@marktext/muyajs` 依赖、`muya` 别名、`muya.d.ts`、`main_renderer/*` 别名。**验证：** `pnpm typecheck` 零错误 + `pnpm test:unit` + `pnpm test:e2e` 全绿（尤其 `context-isolation.spec.ts`、`synthetic-history.spec.ts`）。**回滚：** 单提交 revert。
2. **窗口身份类型化（半天级）。** 引入 `WindowIdentity`，替换三处 cast。**验证：** typecheck；`buffer-store-durable.spec.ts` 与崩溃恢复相关 e2e。**回滚：** revert。
3. **文档契约收敛 + 保存改 invoke（1–2 天）。** 统一 `MarkdownDocument` 到 `shared/types/files.ts`；`response-file-save`/`save-as`/`rename` 改 `invoke` 返回 ack，旧 `send` 通道保留为过渡包装直至渲染器全部迁移。**验证：** `flush-before-save.spec.ts`、`buffer-store-durable.spec.ts`、文件保存相关 e2e；可新增"保存返回 ack"的 unit 断言。**回滚：** 旧 send 通道仍在，逐步切。
4. **收口 preload 桥面（1–2 天）。** 移除裸 `ipcRenderer` 直通或加允许名单，渲染器改走命名门面。**验证：** typecheck（`global.d.ts` 里删掉 `ElectronIpcRenderer` 后，所有裸调用变编译错误，即迁移清单）+ `context-isolation.spec.ts` + `xss.spec.ts`。**回滚：** revert。
5. **`webSecurity` spike（半天实验，可能不改代码）。** 开 `webSecurity:true` 跑图片加载/导出/xss e2e，记录失败项。**验证/决策：** 有证据后决定是否翻 + 加 CSP；不确定就先留注释说明"为何为 false"。
6. **文档对齐（半天级）。** 修正根 `CLAUDE.md` 架构小节与 `ARCHITECTURE.md`，使其与 `config.ts`/`IPC.md` 一致。**验证：** 无行为影响，仅 review。
7. **延后项落地条件（明确触发点，不现在做）：** 第三个窗口类型/tab-tearing 出现 → 做通用窗口注册表；opened-files 双源塌缩完成 → 做文档服务；`@muyajs/core` 发布 `lib/types` → 采纳内置 typings、删 `muya-core.d.ts`、启动 `ag-*`→`mu-*` 主题迁移。

每一步都可独立合入 `develop`，互不阻塞；1–4 是"稳定边界"，5–6 是"消除漂移"，7 是"延后但有触发器"。

---

**总体判断：** 现在不是再做一轮大抽象的时候，而是把**已经存在但半成品**的四条边界收口（IPC 契约、窗口身份、保存 ack、preload 门面），并删掉旧引擎的死重。这四项都便宜、可回滚、有现成测试兜底，且直接降低未来加窗口/改文件流/换引擎/扩 shell 时的边际成本。大重构（窗口注册表、文档服务、主题迁移、能力模型）留到各自的现实驱动力出现。唯一需要尽快决策的安全项是 `webSecurity:false`——不是立刻翻，而是立刻做 spike 拿到证据。
