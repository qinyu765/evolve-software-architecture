核查完成。我没有修改任何文件；以下结论全部基于对实现、配置、测试、文档和迁移记分板的直接阅读。一个诚实的前提说明：本会话的工具集只有 Glob/Grep/Read（无 shell），所以我无法直接跑 `git log`；Git 历史的判断改用三条可查验证据交叉验证——系统提供的提交快照、代码注释中的 issue 锚点（#4244/#4406/#4408–4414/#1034/#1035/#3786 等）、以及 `PARITY_SCOREBOARD.md` 和两个 CLAUDE.md 里的迁移自述。

## TLDR

MarkText 当前的边界质量是**不均衡的**：安全边界（sandbox/contextBridge）已经做得很硬，引擎迁移有可量化的记分板兜底；但**文档与实现已经脱节**、**IPC 契约"名义上类型化、实际上宽松"**、**窗口/文件逻辑高度集中在 `EditorWindow` 和 `WindowManager`**。未来加窗口/文件/引擎/shell 能力，应当**现在稳定**的是：进程间契约的结构（不是载荷类型）、窗口生命周期/类型契约、文件文档契约与持久化格式、以及 desktop 对引擎的宿主侧窄接口；应当**延后**的是：IPC 载荷全量严格化、通用窗口框架、文件服务大重构、以及任何为"未来协作"预留的事件溯源/OT 传输抽象。

最重要的一个"先修文档"发现：**CLAUDE.md 自相矛盾且引用已失效**——"Architecture" 与 preload 段落仍写着 editor/preferences 窗口使用 `contextIsolation: false + nodeIntegration: true` 并引用 `config.js`；而 `config.ts:11-27` 和 `:34-51` 显示两类窗口都是 `contextIsolation: true, sandbox: true, nodeIntegration: false`（另注意 `webSecurity: false`），文件名也已变为 `config.ts`。同一份文档的 "Code Style"/"Directory Structure" 段落又正确写着 sandboxed。这意味着目前文档不可信，任何架构决策都不应建立在这份过时描述上。

---

## 1. 我实际核对到的事实（作为评估依据）

**窗口层**（`src/main/windows/` + `app/windowManager.ts`）
- `WindowType` 是硬编码闭集 `{BASE, EDITOR, SETTINGS}`（`base.ts:16-20`），`WindowLifecycle` 是 `{NONE, LOADING, READY, QUITTED}`（`base.ts:24-29`）。新窗口类型 = 改类型联合 + 写 `BaseWindow` 子类 + 在 `App._create*` 接线 + 菜单模板 + 通过 URL 的 `type` 查询参数让 renderer 分发。
- `EditorWindow` 643 行，混合了：窗口生命周期、`_openedFiles`/`_openedRootDirectory` 簿记、待打开文件队列、崩溃恢复（`_restoreAllState`）、以及"找到最佳窗口"的评分逻辑（`windowManager.ts:256-305`）。窗口越开越多，这个类会继续膨胀。

**IPC 层**（`shared/types/ipc.ts` + `preload/index.ts` + `main/ipc/*` + 各类的 `_listenForIpcMain`）
- 契约分了四类通道（invoke/send/sync/event），但注释自己写明："载荷形状故意宽松（`unknown[]`/`unknown`），随迁移逐提交收紧"（`ipc.ts:10-13`）。所以这是一个**结构 scaffold，不是严格的类型边界**。
- 注册点有三处并存：干净的 `main/ipc/*`（`registerSandboxIpcHandlers`，`ipc/index.ts`）；散落在 `WindowManager`/`EditorBufferStore`/`DataCenter`/`App` 的 `_listenForIpcMain()`；以及 renderer 侧直接 `window.electron.ipcRenderer.send(...)`。同一套 `mt::` 通道名、同一种 `BrowserWindow.fromWebContents(e.sender)` 派生约定，靠人工保持一致。
- 存在一条**主进程内部总线**：`ipcMain.emit(...)` + `onInternalChannel(...)`（`utils/internalIpc.ts`）。问题在于这些内部通道名被混进了面向 renderer 的 `IpcSendChannels`（`watcher-*`、`window-*`、`broadcast-*`、`screen-capture`、`set-user-preference`、`app-*`…见 `ipc.ts:191-201`），但又不是全部——`broadcast-web-image-added/removed` 被 emit（`dataCenter/index.ts:107,117`）却不在契约里；`screen-capture` 同时是 renderer 的 send 通道和内部 emit 通道（`app/index.ts:805-807`）。命名空间混用是一个真实的踩坑点。

**文件工作流**（`main/filesystem/*` + `editorBufferStore` + `dataCenter`）
- `loadMarkdownFile`/`writeMarkdownFile` 承载编码探测、BOM、行尾归一化（内部永远 LF）、持久原子写（`write-file-atomic` 的 fsync，`filesystem/index.ts:40-48`）。这是一组**跨进程、跨版本、落盘**的语义，最贵的是后期改。
- 崩溃恢复：`EditorBufferStore` 给每个窗口分配一个 UUID（`restoreBufferId`），并把它**挂在原生 `BrowserWindow` 实例上**（`editor.ts:145`、`editorBufferStore/index.ts:188-198`），通过非类型化的属性读回。这是一个隐式契约，靠 `(win as unknown as { restoreBufferId })` 硬转。
- `Watcher`（chokidar + 自身改动抑制时间窗 + macOS 轮询 + Linux 原子重命名 workaround）是历史 bug 密度最高的区域（注释引用 #1034/#1035/#1043/#3044/#3955），但对外事件契约是清晰的：`mt::update-file` / `mt::update-object-tree`。

**引擎层**（`@muyajs/core` = `packages/muya` 的 TS 重写）
- renderer 已全部改从 `@muyajs/core` 导入（grep `from 'muya/` 已无匹配；`editor.vue` 全套 `Muya`/插件/`MarkdownToHtml` 都来自它）。
- desktop 用一份**手写 ambient shim** `types/muya-core.d.ts` 把 `@muyajs/core` 的类型重定向到自己手里（`tsconfig.base.json:30`），`Muya` 实例和插件类型是 `any`。原因是引擎包 `exports` 指向 `./src/index.ts` 且安装时不带 `lib/types`。
- 遗留包 `@marktext/muyajs`（`packages/muyajs`）和 `muya/` 别名仍在依赖与构建配置里（`electron.vite.config.ts:38,58,84`、`tsconfig.base.json:29`），但**源码已零引用**——是死配置。
- 迁移质量有量化凭证：`test/PARITY_SCOREBOARD.md` 记录 15 个功能差距，14 个已关闭，仅 PG14（source-mode 切换后的单一撤销边界）以 xfail 形式 accept-defer。这是很好的"可验证迁移"范式。

**Electron shell 能力**
- preload 已把 shell/clipboard/webFrame/webUtils/windowControl/fs/path/ripgrep/uploader/fonts/i18n 全部走 `contextBridge` 暴露，`global.d.ts` 是类型化的 API 面。`context-isolation.spec.ts` 这类 e2e 已存在。**这条边界目前是最稳的**，不需要新抽象。

---

## 2. 边界地图：稳定什么、延后什么

| 层次 | 现状 | 建议 | 理由 |
|---|---|---|---|
| 进程隔离（sandbox/contextBridge） | 已稳定（#4244），但文档矛盾 | **稳定为硬性不变量**，修正文档 | 安全边界，已投入完成；只需让文档可信 |
| `webSecurity: false` | 两窗口都关（`config.ts:19,40`） | **稳定现状但要显式记录**，单独立项评估收窄 | 可能是加载本地图/iframe/mermaid 的必要条件；盲改会回归 |
| IPC 通道**结构**（四类 + `mt::` 命名 + sender 派生 + 单一注册点） | 结构 scaffold 存在，但注册点分散、内部总线混用命名 | **现在稳定** | 结构便宜、行为不变；是后续一切类型收紧的地基 |
| IPC 通道**载荷类型** | 大量 `unknown` | **延后** | 引擎还是 `any`，形状未定，过早严格化会钉死错误类型 |
| 窗口生命周期/类型契约 | 隐式存在，闭集 | **现在稳定**（开放字符串联合 + BASE 哨兵 + `type` 参数 + 每窗口稳定 id） | 新窗口能力最直接的接缝 |
| 通用窗口框架/注册表 | 无 | **延后** | 只有 2 种窗口，第三/四种出现再抽象 |
| 文件文档契约 + 落盘格式（`IFileState`/`MarkdownDocument`/编码行尾/持久写/buffer schema） | 隐式、跨进程、落盘 | **现在稳定 + 加 schema 版本号** | 落盘格式改起来最贵，且用户数据不可回滚 |
| 文件服务大重构（watcher/簿记抽离） | `EditorWindow` 混责 | **延后**（先加窄接缝，不重构） | watcher 是性能敏感+历史 bug 区，大动风险高 |
| 引擎宿主侧窄接口（desktop 消费的引擎面） | `any` + shim | **现在稳定**（desktop 侧拥有的接口，引擎在接口后面） | 让依赖显式化，未来换/收紧类型都便宜 |
| 引擎内置类型切换 / `lib/types` | 未产出 | **延后**（记入清单，产出即切换） | 被上游阻塞 |
| 主题 DOM 迁移（`ag-*`→`mu-*`） | 遗留（`editor.vue:136-139` 已注释） | **延后**（独立轨道） | 纯外观，不影响边界 |
| 死配置清理（`muya` 别名 + `@marktext/muyajs` 依赖） | 已零引用 | **现在做**（低成本清理） | 可验证，减少误导 |
| 协作/事件溯源/OT 传输 | 引擎有 OT 原语，无消费者 | **延后** | 无功能需求，过早抽象 |

---

## 3. 关键决策点与方案比较

### 决策点 1：IPC 契约怎么收敛（最优先）

- **方案 A（维持现状）**：scaffold 保持宽松，按需逐提交收紧。成本最低；但 `unknown` 载荷让类型检查给假安全感，跨进程破坏要等到 e2e 才暴露；内部总线与 renderer 通道混用、注册点分散，约定靠人记忆。
- **方案 B（先稳定结构，后收紧载荷）**：把"四类通道 + `mt::` 命名 + sender 派生 + 新通道单一注册点"固化为**可被单元测试检查的规则**；把 `ipcMain.emit` 内部总线从 renderer 契约里分到独立命名空间（如 `internal::`）；载荷类型继续逐提交收紧。成本低、行为不变、可增量；回滚就是删规则/删测试。
- **方案 C（一次全量严格类型化）**：被引擎 `any` 和 200+ 通道拖住，churn 巨大，且很多载荷形状本身未定——先做会把错误类型钉死。

**建议 B。** 它把现有的 scaffold 变成真正的注册表，是后续所有能力（窗口、文件、shell）安全扩展的前提。一个立即可写的验证手段：单元测试扫描 `src/main/**/*.ts` 里的通道字符串字面量，断言它们要么出现在 `ipc.ts` 契约、要么在显式豁免清单（`settings::change-tab`、`language-changed`、`update-buffer-state` 这三个非 `mt::` 例外），并且内部 emit 通道必须带 `internal::` 前缀。

### 决策点 2：窗口扩展路径

- **方案 A（维持现状，新增窗口继续 subclass + 闭集扩展 + 四处接线）**：偶发新增 OK，但每类窗口重复 createWindow/菜单/URL `type` 分发全套样板，且 `WindowType` 是闭集，加类型要改共享类型定义。
- **方案 B（稳定生命周期/类型契约，延后通用框架）**：把 `WindowLifecycle`、`WindowType`（改为开放字符串联合 + `BASE` 哨兵）、`type` 查询参数、每窗口稳定 id 作为公开契约固定并加单元测试；新窗口仍是 `BaseWindow` 子类，但样板收敛到基类。
- **方案 C（现在就建声明式窗口注册表/工厂）**：只有 2 种窗口，抽象过度；等第 3–4 种真实窗口（quick-open 面板、拆分视图、图片查看器）出现再评估。

**建议 B。** 质量属性权衡：可演化性大幅提升（新增窗口不必改共享类型），成本是一份契约测试，风险近零（不改变现有两类窗口行为），回滚是删测试。

### 决策点 3：文件工作流的组织方式

- **方案 A（维持现状，继续在 `EditorWindow` 上堆文件逻辑）**：`EditorWindow` 已 643 行混责（生命周期 + opened-files 簿记 + 缓冲恢复 + 打开路由），每加一个文件能力（重载体验、git 感知 diff、autosave 2.0、rename 流程）都在这里堆风险。
- **方案 B（稳定文档契约 + 窄 FileService 接缝）**：固化 `IFileState`/`MarkdownDocument`/编码行尾语义/持久原子写/buffer schema（**加版本号字段**）；抽出一个窄的 main 侧文件读写接缝；**暂不重构** watcher 和 opened-files 簿记。
- **方案 C（完整文件服务 + 文档事件溯源）**：为协作/实时同步预留，当前无消费者，过早。

**建议 B。** 理由：落盘格式和跨进程文档形状是最贵的后期改动，且用户数据不可回滚；但 watcher 是性能敏感、历史 bug 密集区，大重构的回归成本高于收益，所以只加接缝不动内脏。回滚：接缝是纯新增，删文件即可。

### 决策点 4：编辑器引擎边界

- **方案 A（维持现状：`any` + 手写 shim）**：已被 parity scoreboard 证明可用，但 desktop 对引擎内部没有显式依赖清单，每次引擎升级都靠 14/15 这种手工记分板兜底（已经很贵），未来换引擎或收紧类型都难。
- **方案 B（稳定 desktop 侧的 host adapter 接口）**：把 desktop 真正消费的引擎面（init/options/事件、`MarkdownToHtml`、`wordCount`、导出 helpers、locale/插件注册）收成一个 **desktop 侧拥有、类型在 desktop 侧定义**的窄接口，`any` 的 `Muya` 实例藏在接口后面；手写 shim 变成"临时契约"并附删除清单。
- **方案 C（现在就发布引擎内置类型并切换）**：被 `lib/types` 未产出阻塞，成本高、引擎仍在迁移。

**建议 B，同时 PG14 维持 accept-defer 不阻塞。** 这样引擎依赖被显式化，desktop 侧可以单测这个 adapter，未来 `@muyajs/core` 产出内置类型时，只需替换一个 import 边界（`muya-core.d.ts` 注释里已写明删除条件）。

### 决策点 5：Electron shell 能力扩展

- **方案 A（维持现状：preload 按需手写暴露，`global.d.ts` 为 API 面）**：每个新能力在 preload + `global.d.ts` + main handler 三处加码，模式已固定、风险低，`context-isolation.spec.ts` 可作契约测试的雏形。
- **方案 B（现在就建 capability 注册表/插件系统）**：无第二消费者，过早抽象。

**建议 A。** 这条边界已经最稳，抽象纯属负担；唯一要做的是把 preload/`global.d.ts` 面纳入契约测试，防止有人绕过 contextBridge。

---

## 4. 质量属性、成本、风险、回滚、不改变的后果（汇总）

- **安全性**：sandbox 已稳定是最大资产；`webSecurity: false` 是唯一需要盯的例外——稳定现状、显式记录、单独立项评估收窄（收窄可能破坏本地图/iframe/mermaid 加载，需专项 e2e）。
- **可维护性**：收敛 IPC 注册/命名、收敛窗口样板后，新贡献者不再靠过时文档接线。
- **可演化性**：稳定文档/窗口/引擎接缝，使未来窗口/文件/引擎能力可局部演进，不牵一发动全身。
- **可测试性**：三个可写契约测试是"可验证"的关键——通道字面量扫描、buffer 落盘往返（含版本字段）、窗口生命周期状态机。
- **性能**：watcher 维持现状不动；只固化其对外事件契约。
- **成本/风险/回滚**：方案 B 系列全部是"新增契约/接缝 + 删规则"，无行为耦合；每一步回滚都是删文件或删测试。最大风险点是别在 Phase 里顺手重构 watcher 或一次全量类型化。
- **不改变的后果**：文档继续自相矛盾 → 新人可能按"contextIsolation: false"的错误描述接线，甚至误判 sandbox 可以回退；IPC 载荷继续漂移，跨进程破坏延后到 e2e 才暴露；窗口/文件逻辑继续在 `EditorWindow` 堆积，新增能力的回归面递增；引擎 `any` 继续意味着每次引擎升级都要重跑一次昂贵的 parity 手工记分板，且没有显式依赖清单可查。

---

## 5. 可验证的渐进迁移路线

每一阶段都有明确门禁（`pnpm lint` / `typecheck` / 对应 `vitest` 或 `playwright` spec），且后一阶段不依赖前一阶段的类型收紧。

- **Phase 0（纯清理，1 个 PR）**：修正 CLAUDE.md 的矛盾与 `config.js` 死引用；删除 `electron.vite.config.ts`/`tsconfig.base.json` 里的 `muya` 别名和 `@marktext/muyajs` 依赖。验证：`grep -rn "from 'muya/"` 与 `grep -rn "@marktext/muyajs"` 只命中文档；`typecheck` + `lint` + e2e `launch.spec.ts` 通过。这是让文档重新可信的零风险步骤。
- **Phase 1（IPC 结构契约，1–2 个 PR）**：引入"通道字面量必须注册/`mt::` 前缀/`internal::` 命名空间"的单元测试；把散落 `_listenForIpcMain` 的通道逐步并入单一注册点（行为不变）。验证：新增 `ipc-contract.spec.ts`；全量 `test:unit` + e2e 回归通过。
- **Phase 2（窗口 + 文件契约，2–3 个 PR）**：`WindowType` 改开放联合并加状态机测试；buffer store JSON 加 `schemaVersion` 字段并加往返 golden-file 测试（可复用现有 `buffer-store-durable.spec.ts`）；引入窄 FileService 接缝。验证：`buffer-store-durable`、`application-menu-state`、e2e `tabs`/`external-reload-undo` 通过。
- **Phase 3（引擎 host adapter，1–2 个 PR）**：在 renderer 建 `IEngineHost` 窄接口，`any` 实例收拢到接口后面；把 shim 的删除条件写进 `muya-core.d.ts` 的清单。验证：parity scoreboard 保持绿、e2e `parity-*` 通过、`typecheck` 通过。
- **Phase 4（仅在真实功能驱动时）**：出现第 3–4 种窗口或第二个 shell 能力消费者时，再评估通用窗口注册表 / capability 注册表 / 文件服务抽取——**现在不预先建设**。

这条路线的验收标准是可机械检查的：每阶段的"验证"都是具体命令，且 Phase 0–3 全部不改用户可见行为，只把"现在靠人记忆的约定"变成"测试可查的契约"；真正受阻塞的只有引擎内置类型（上游）和未来的协作/实时同步（无需求），这两项明确延后而不是现在动手。
