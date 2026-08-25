核对完成。以下是基于仓库实际实现、配置、测试与可读证据的架构评估（只给建议，未改任何代码）。

## 结论先行

MarkText 正处在一场**进行到中段的架构迁移**里，方向已经清晰且值得延续：renderer 完全沙箱化、IPC 收敛为一份类型化契约、编辑引擎已切到 `@muyajs/core`。未来要加窗口、文件工作流、引擎或 shell 能力时，**该稳定的是"机制/契约骨架"，该延后的是"框架化抽象"**。具体说：

- **应稳定**：沙箱三件套与 preload 唯一咽喉、四类 IPC 契约的注册机制与命名约定、`IFileState` 的"宿主字段 vs 引擎不透明字段"归属规则、每窗口稳定 buffer UUID（而非 `win.id`）作为崩溃恢复身份、`@muyajs/core` 的单一出口 API。
- **应延后**：给所有 IPC 负载做运行时 schema 校验、窗口 provider/停靠框架、跨进程文档服务与 OT/CRDT 传输层、以及把 legacy `muyajs` 一次性大删（应作为独立小步、在契约迁移落地后做）。
- **推荐路径**：延续现状的增量迁移（方案 A），把上面几条约法写进文档并补一个"契约漂移"测试；不推荐现在激进硬化（方案 B），更不推荐现在建文档服务层（方案 C）。

---

## 我核对了什么

- **文档**：根 `CLAUDE.md`、`packages/muya/CLAUDE.md`、各 `shared/types/*` 头注释。
- **实现**：`shared/types/ipc.ts`（契约）、`preload/index.ts`（桥）、`main/ipc/*`（handler）、`main/app/windowManager.ts`、`main/windows/{base,editor,setting}.ts`、`main/editorBufferStore`、`main/filesystem/{markdown,watcher}.ts`、`main/utils/internalIpc.ts`、`renderer/store/{editor,help,bufferedState,listenForMain}.ts`、`main/config.ts`、`electron.vite.config.ts`。
- **配置/依赖**：根与 desktop 的 `package.json`、`pnpm-workspace.yaml`、build 别名。
- **测试**：`test/unit/specs`（约 50 个）、`test/e2e`（约 60 个，含 `context-isolation.spec.ts` 沙箱金丝雀）、muya 的 conformance 锁（`expected-failures.json`）。
- **Git 历史**：如实说明——本次会话 Bash 被禁用，无法跑 `git log`；`.git/logs/HEAD` 只记录了一次 fresh clone，无增量历史可读。我关于"迁移阶段"的判断，依据的是**会话上下文给出的最近 5 条提交**与**代码内嵌的迁移标记**（`ipc.ts:12` 的"commits 5–8 收紧类型"、`#4244` 沙箱工作、`#1034/#1035` watcher 重构 TODO、muya CLAUDE.md 的"PR-6a 基线"）。这部分结论是"由仓库自述 + 提交列表推断"，不是逐条 `git log` 验证的结果。

---

## 现状判断：在途迁移，北星边界已经可见

几个关键证据拼起来看：

1. **安全边界已成硬约束并有金丝雀**。`config.ts:8-21` 对所有窗口 `contextIsolation: true, sandbox: true, nodeIntegration: false`；`test/e2e/context-isolation.spec.ts:5-8` 明说这是"单一金丝雀"，任何一处回退都会让桥不再承重。这是全仓库最不该动的边界。

2. **IPC 契约是"单一事实来源"，但只迁了一半**。`shared/types/ipc.ts:10-18` 把通道分四类，并承认负载"迁移期间故意用 `unknown`，commits 5–8 逐步收紧"。preload 侧已用泛型把 `send/invoke/on/sendSync` 绑定到契约（`preload/index.ts:26-67`），`global.d.ts:24-43` 也同步。但 **main handler 侧还没绑定**：`main/ipc/fs.ts`、`main/ipc/window.ts` 仍是裸 `ipcMain.handle/on` + 手写类型，`window.ts:82` 甚至有 `event as unknown as IpcMainEvent`。我找到一个**具体漂移证据**：`main/ipc/fs.ts:6-13` 本地 `SerializedStat` 带 `ctimeMs`，而共享契约 `shared/types/files.ts:9-15` 的 `SerializedStat` 没有——运行时多返回一个字段，类型上却不可见。

3. **存在两套路由机制，契约里混进了主进程内部总线**。`main/utils/internalIpc.ts:4-13` 用 `ipcMain.emit` 充当主进程内部事件总线；`editor.ts`/`menu/actions/*` 大量 `ipcMain.emit('watcher-*'/'window-*'…)`，`WindowManager` 用 `onInternalChannel` 订阅。但同一批名字（`watcher-watch-file`、`window-add-file-path`…）又出现在 `ipc.ts` 的 `IpcSendChannels` 里，声明成 renderer→main 且签名是 `[windowId, path]`。我 grep 过 renderer：**渲染器从未发送这些通道**，真实生产者只有主进程，且内部签名不统一（有的传 `win.id`，有的传 `BrowserWindow`）。也就是说：契约把"主进程内部通道"错标成了"跨进程通道"，且内部总线完全无类型。

4. **引擎切换在"导入层"已完成，在"数据层"刻意留了缝**。renderer 只从 `@muyajs/core` 导入（`editor.vue:113`、`muya/src/index.ts` 单一出口）；legacy `packages/muyajs` 只剩环境声明 `types/muya.d.ts`、几处注释，以及 `electron.vite.config.ts:38` 里已无运行时的 `muya` 别名和 `package.json` 里的 `@marktext/muyajs` 依赖。数据层上，`IFileState`（`shared/types/files.ts:68-91`）把 `history/cursor/muyaIndexCursor/blocks/searchMatches` 标成 `unknown`——这是**正确的**：宿主文件工作流不应知道引擎块树的内部结构。

5. **崩溃恢复的身份模型是对的**。`windows/editor.ts:139-145` 明确说不能用 `win.id`（关闭后可能撞号），所以每窗口分配稳定 UUID 写入 `restoreBufferId`，`EditorBufferStore` 按它持久化，`editorBufferStore/index.ts:178-185` 用 `write-file-atomic` 做原子落盘。这条注释本身就是一份已固化的架构决策。

---

## 四领域边界决策表

| 领域 | 应稳定（冻结并写进文档/测试） | 应延后（现在不做框架化） |
|---|---|---|
| **窗口能力** | `WindowType` 联合 + `BaseWindow` 子类机制；每窗口稳定 UUID 作为恢复身份；`WindowManager` 作为唯一注册表；preload `windowControl` 表面；每窗口 `appMenu.addDefaultMenu` | 窗口 provider 框架、停靠/分栏/任意 pane 树、`findBestWindowToOpenIn` 评分逻辑的泛化 |
| **文件工作流** | renderer 发起、main 执行的 RPC 分工（保存/重命名/移动是 renderer `send` + main 事件回执）；watcher 自我写入抑制接缝；`IFileState` 宿主字段；buffered-state 版本号 + 原子写 | 跨进程文档服务、OT/CRDT 传输、跨窗口文件锁、虚拟文件系统抽象 |
| **编辑器引擎演进** | `@muyajs/core` 公共 API（`src/index.ts` 单一出口）；外观契约（CSS 变量 + `muya.setOptions`）；`IFileState` 中引擎字段保持 opaque | 把引擎内部类型并入宿主；把 muya 并入 desktop；跨进程直接共享 Muya state |
| **Electron shell 能力** | 沙箱三件套 + `context-isolation` 金丝雀；preload 按能力分 namespace（shell/clipboard/webFrame/windowControl）；`mt::` 命名约定；`path`/`process` 兼容 shim 保持收窄 | 暴露裸 `ipcRenderer`；通用 `runNodeCode` 逃生门；扩大 `process` shim 到第三方包实际需要之外 |

下面是逐条的判断理由（结合质量属性）。

### 应该稳定的边界（及理由）

- **沙箱 + preload 单一咽喉**（安全性/可测试性）。任何新 shell 能力都必须走"preload 新 namespace + `global.d.ts` + 契约条目"三步，绝不能给 renderer 开裸 `ipcRenderer` 或 Node 直通。这条已经由金丝雀测试背书，未来每次改桥面都应扩展该测试。

- **四类 IPC 契约的"机制"与命名约定**（可修改性）。冻结的是通道分类、泛型包装器、`mt::` + 能力分段前缀（`mt::fs::`、`mt::win::`）。机制便宜且稳定；**负载类型则继续用 `unknown`**，不要冻结。

- **`IFileState` 的字段归属规则**（可修改性/演进能力）。宿主字段（`id/filename/pathname/isSaved/encoding/lineEnding/scrollTop/wordCount`）已类型化；引擎字段保持 opaque。这条规则让"引擎演进"和"文件工作流"可以独立演化，互不锁死。`BUFFERED_STATE_VERSION`（`bufferedState.ts:7`）是这条规则在持久化格式上的迁移闸门。

- **每窗口稳定 UUID 作为恢复身份**（可靠性）。这是现成的正确决策，未来任何多窗口/多 pane 能力都必须继续用它路由崩溃恢复，不能退回 `win.id`。

- **`@muyajs/core` 公共 API 单一出口 + 外观契约**（可维护性/可测试性）。muya 有自己的 conformance 锁（合规只能升不能降）和循环依赖检查，宿主只依赖 `src/index.ts`。

### 应该延后的抽象（及理由）

- **不要现在给 IPC 负载做运行时 schema 校验（zod 之类）**。诱惑很大，但负载还没收敛（`ctimeMs` 漂移就是反例），现在冻结 schema 会把不成熟的形状固化。等 handler 侧绑定契约、且有 fixture 测试后再评估。
- **不要现在建窗口/工作区框架**。当前 `WindowManager` + 两种窗口 + MRU 足够；第三个具体窗口类型尚不存在，泛化是投机。等真实需求出现，抽的是 `createWindow` 选项 + 每窗口类型 bootstrap 负载的接缝，而不是一个框架。
- **不要现在建跨进程文档服务或 OT/CRDT 传输**。muya 的 JSONState 有 OT 原语但"没有接传输"（muya CLAUDE.md 原话），文件持久化是每窗口一个 JSON 文件；没有实时多客户端需求。`IFileState` 的 opaque 字段已把门留着，现在建服务是提前优化。
- **不要现在一次性删掉 legacy `muyajs`**。运行时已零导入，删是低风险的；但 `muya` 别名仍在 build 配置里、`@marktext/muyajs` 仍在依赖里，动 build 配置的风险比看起来高。应在契约迁移落地后作为独立可回滚的一步做。
- **（低优先级、可延后）把主进程内部 `ipcMain.emit` 总线从 renderer IPC 契约中拆出来**。它今天能跑、不跨安全边界，但名字复用 + 无类型签名是未来加窗口/文件能力时的真实地雷。值得排进 backlog，不必现在动。

---

## 方案比较

### 方案 A —— 延续在途迁移 + 固化机制边界（推荐，近似维持现状但把决策显式化）

继续"commits 5–8"式的类型收紧，但明确：**冻结机制、不冻结负载**；把上面"应稳定"的几条写进 `IPC.md`/架构文档，补一个契约漂移测试，其余保持现状。

- **质量属性权衡**：安全性已由金丝雀兜底；可修改性随契约收紧单调改善；可测试性提升（漂移测试让 handler/preload 形状对齐可自动验证）；性能零影响；可靠性不受影响。
- **成本**：低。主要是文档 + 1 个测试 + 延续在途重构。
- **风险**：低。不锁 schema、不重写服务。
- **回滚**：每个阶段都是独立可 revert 的提交，无锁入。
- **不改变的后果**：漂移会继续累积（`unknown` 负载、内部总线无类型），未来新功能需要"契约考古"；但这些都被沙箱金丝雀和单一契约文件限定了爆炸半径。

### 方案 B —— 激进硬化：现在就绑定 handler + 运行时校验 + 提前做窗口注册抽象

把 `ipcMain.handle/on` 也绑定到契约泛型（消除 `event as unknown as IpcMainEvent`），给 save/rename/export/buffer-state 等高危通道加 zod 校验，并提前抽 `WindowRegistry`。

- **质量属性权衡**：类型安全收益更早；但**风险集中在"负载还没收敛就冻结"**——`ctimeMs` 这类漂移说明 handler 运行时形状与契约还不一致，强行收紧会先破后修。
- **成本**：中高。schema 库 + 校验层 + 窗口抽象三线并行。
- **风险**：中。冻结错误形状、以及窗口抽象在只有一个真实消费者（editor）时是凭空设计。
- **回滚**：校验是增量可拆，但 handler 绑定与窗口抽象一旦合并进各 save/open 路径，回滚面变大。
- **不采用的后果**：如果未来负载快速收敛，A 会少赚一点早期收益；但以当前漂移状态，B 的失败概率更高。

### 方案 C —— 现在建跨进程文档/工作区服务层（对比项，不建议）

把"渲染器发起、main 执行"的 RPC 改成中心化 Document Service + 版本化模型 + OT 传输。

- **权衡/成本/风险**：会触碰所有 save/open/rename/移动路径，成本最大；没有多客户端需求做牵引，属于提前优化；风险是推翻刚稳定下来的恢复模型和 `IFileState` 归属规则。
- **不采用的后果**：未来若真要做实时协作，A/B 路径下也能从 opaque 引擎字段和 OT 原语出发再加传输，不必现在预付。

**建议**：以 A 为主干，把 B 中"handler 侧绑定契约 + 漂移测试"这一小块作为 A 的第 1 阶段吸收进来；B 的 schema 校验和窗口框架、以及整个 C，都挂到明确的"触发条件"上（见下）。

---

## 渐进迁移路线（可验证、每步可回滚）

每阶段独立合入、独立 revert，门禁用具体测试/构建命令表达。

- **阶段 0 —— 固化边界（文档 + 金丝雀扩展，不改运行行为）**：把"沙箱不变式、四类契约机制与命名约定、`IFileState` 字段归属、稳定 buffer UUID、muya 单一出口"写进 `packages/website/content/docs/dev/` 对应文档；给 `context-isolation.spec.ts` 增加"桥面新 namespace 必须 `typeof` 可见且不泄漏 preload 作用域变量"的断言。
  - 门禁：`pnpm run lint && pnpm run typecheck`、`pnpm -C packages/desktop exec playwright test test/e2e/context-isolation.spec.ts` 绿。
  - 回滚：revert 该文档/测试提交。

- **阶段 1 —— handler 侧绑定契约（吸收方案 B 的安全小块）**：在 `main/ipc` 里用与 preload 相同的泛型注册器包住 `ipcMain.handle/on/send`，让通道名和参数类型由 `IpcInvokeChannels`/`IpcSendChannels` 推导；清理 `window.ts` 的 `as unknown as IpcMainEvent`；顺手修掉 `SerializedStat` 的 `ctimeMs` 漂移（统一到共享契约）。
  - 门禁：`pnpm run typecheck` 无 `as unknown as IpcMainEvent`（可加 lint 规则禁止）；新增一个契约漂移测试，枚举 `IpcInvokeChannels` 的每个 key，断言 main 侧确有对应 handler 注册、且返回形状符合契约 fixture。
  - 回滚：单次 revert；不涉及运行时 schema。

- **阶段 2 —— 契约 fixture 测试（不加 schema 库）**：用一张"通道 → 代表性负载"的表，同时喂给 preload 的 `send/invoke` 与 main handler 的注册器，让类型漂移在单测层被抓住。
  - 门禁：`pnpm run test:unit` 绿。
  - 回滚：纯测试增量。

- **阶段 3 ——（触发条件）出现第二个真实窗口类型时，抽窗口接缝**：扩展 `WindowType` 与 `BootstrapEditorConfig` 式的"每类型 bootstrap 负载"联合类型，让新窗口类型在不改 `WindowManager` 内部、不改评分逻辑的前提下接入。**在需求出现前不做**。
  - 触发：确实要新增预览/差异/全部搜索结果等窗口。
  - 门禁：新窗口类型带 e2e 覆盖其 bootstrap + 关闭恢复路径。

- **阶段 4 ——（触发条件）引擎状态有至少两个真实宿主消费者后，再收窄 opaque 字段**：把 `IFileState` 里 `unknown` 的引擎 blob 逐步换成窄接口，但仍保持"宿主不可见引擎块树内部"。
  - 触发：例如"打印/导出"与"编辑器"都消费 blocks 后。
  - 门禁：muya conformance 不降（`expected-failures.json` 锁），宿主 `pnpm run typecheck`。

- **阶段 5 —— legacy 引擎清理（独立、可回滚的一小步）**：契约迁移落地后，删 `packages/muyajs`、`electron.vite.config.ts` 里的 `muya` 别名、`@marktext/muyajs` 依赖、`types/muya.d.ts` 环境声明。
  - 门禁：新增一个 grep 型测试，断言 `packages/desktop/src` 无 `muya/lib` 运行时导入；`pnpm run build:unpack` + e2e 冒烟（launch、tabs、export）绿。
  - 回滚：单独 revert；因为零运行时导入，风险面极小。

---

**一句话收尾**：这份代码库的"正确感"在于它已经选对了大方向——把安全边界做成金丝雀、把 IPC 做成单一契约、把引擎边界留在公共 API 和 opaque 数据上；接下来要做的不是造新框架，而是把这几个已经成立的机制边界**显式固化并补上防漂移测试**，让未来的窗口、文件、引擎、shell 能力都从这些缝上长出来，而不是绕过去。
