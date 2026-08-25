# MarkText IPC 契约评估与演进建议

## 1. 范围与结论

**结论先行**：MarkText 已经有一个正确的骨架 —— `packages/desktop/src/shared/types/ipc.ts` 是单一事实来源，四类通道（invoke/send/sync/main-event）划分清晰，preload 用 `contextBridge` 暴露能力对象，渲染端通过 `global.d.ts` 全量类型约束。**但这个契约目前只约束了 preload/renderer 一端，main 端完全游离在契约之外**，而且仓库里已经出现了至少三处“契约与实现漂移后靠渲染端强制收窄来兜底”的实例。长期演进的关键不是重做类型系统，而是把同一份契约接到 main 端的注册与 `webContents.send` 上，让漂移在编译期就失败。

工作方式：只读核对，未修改任何文件、未创建提交。

---

## 2. 观察事实（带路径与行号）

### 契约文件与四类通道

- `packages/desktop/src/shared/types/ipc.ts:40-289` 定义了 `IpcInvokeChannels`、`IpcSendChannels`、`IpcSyncChannels`、`IpcMainEventChannels` 四张类型映射。
- 文件头注释（ipc.ts:1-18）明确说明：迁移期间 `args`/`ret` 刻意宽松（`unknown[]`/`unknown`），打算“在 commit 5–8 逐个收紧”。
- `ipc.ts:324-332` 导出了 `InvokeArgs/InvokeRet/SyncArgs/SyncRet/SendArgs/EventArgs` 六个辅助类型，**但全仓库除定义处外无任何引用**（grep 确认）——它们是休眠的种子，正好是 main 端 helper 的原料。

### contextBridge 暴露面

- `packages/desktop/src/preload/index.ts:286-296` 通过 `contextBridge.exposeInMainWorld` 暴露：`electron`、`process`（shim）、`rgPath`、`fileUtils`、`path`、`commandExists`、`i18nUtils`、`ripgrep`、`uploader`、`fonts`。
- 关键事实：`window.electron.ipcRenderer`（preload/index.ts:38-68）**不是窄门，而是一个类型化的通用直通** —— `send/invoke/on/once/sendSync/removeAllListeners` 可以触达任意通道。渲染端实际大量走这条路（`window.electron.ipcRenderer` 出现 **136 次 / 25 文件**），领域 facade（`shell`、`fileUtils` 等）只覆盖其中一小部分。
- 沙箱配置是 `contextIsolation: true, sandbox: true, nodeIntegration: false`（`src/main/config.ts:12-20, 35-41`；e2e 断言在 `test/e2e/context-isolation.spec.ts:24-38`）。**注意**：`CLAUDE.md` 架构段落仍写着 editor/preferences 用 `contextIsolation: false + nodeIntegration: true`，这是过时文档，与代码和 e2e 都矛盾。

### main 端：契约未接入

- main 端所有 handler 都是裸注册：`ipcMain.handle('mt::fs::is-file', (_e, p: string) => …)`（`src/main/ipc/fs.ts:41-77` 等），通道名是原始字符串字面量，参数是手写注解。
- grep 证实：**main 目录下没有任何文件 import `IpcInvokeChannels`/`IpcSendChannels`/`IpcSyncChannels`/`IpcMainEventChannels`**，唯一 import 的是 `BootInfo`（`src/main/ipc/bootInfo.ts:6`）。
- main→renderer 的推送全是不受类型约束的裸 `webContents.send('mt::…', …)`（约 80+ 处），其中还有模板字面量 `win.webContents.send(\`mt::window-${channel}\`)`（`src/main/windows/editor.ts:250`），连字符串检查都绕过了。

### 已发生的契约漂移（三处实证）

| 通道 | 契约声明 | main 实际发送 | 渲染端处理 |
|---|---|---|---|
| `mt::window-active-status` | `[active: boolean]`（ipc.ts:282） | `{ status: true/false }`（editor.ts:237/243；setting.ts:78/84） | `(status as {status?:boolean})?.status` 收窄（store/index.ts:26-27） |
| `mt::menu::click` | `[menuId: string]`（ipc.ts:246） | `{ windowId, id }`（ipc/window.ts:38） | `(message as {id?:string})?.id` 收窄（contextMenu/popupMenu.ts:77-79） |
| `mt::menu::closed` | `[]`（ipc.ts:247） | `{ windowId: win.id }`（ipc/window.ts:107） | 渲染端直接忽略参数（popupMenu.ts:89） |

注意 `store/index.ts:26` 的注释写着“Main sends `{ status: boolean }` per IPC contract”，**与 ipc.ts 里声明的 `[active: boolean]` 直接矛盾**——这说明团队已经撞上了漂移并选择了在边界打补丁，而不是修契约或修实现。

### 错误传播现状

- **invoke 拒绝路径**：Electron 默认把 `ipcMain.handle` 抛出的 Error 跨进程序列化成 `{message}`（stack 丢失），渲染端拿到一个 rejected Promise。全渲染端只有零星 `.catch`（如 `store/project.ts:224-230` 删除失败转 notice）；大多数 invoke 未捕获，最终落入全局 `unhandledrejection`。
- **全局兜底**：`renderer/src/bootstrap.ts:101-104` 监听 `error`/`unhandledrejection` → 过滤 CodeMirror 竞态 → `mt::handle-renderer-error` 发往 main（bootstrap.ts:95）→ `main/exceptionHandler.ts:124-126` 弹错误对话框 + crashReporter。这条链路丢掉了“是哪个通道、什么参数形状”的上下文。
- **长任务例外**：ripgrep 用了更完整的推送式错误协议 `mt::rg::error/done/cancelled`，带 `searchId`（`main/ipc/ripgrep.ts:195-201, 345-357`），这是仓库里唯一的“异步作业错误信封”范式，可推广。

### 测试隔离现状

- 单测（vitest + jsdom）：每个 spec 手工 mock contextBridge 面，例见 `test/unit/specs/listen-for-main.spec.ts:8-45`——`vi.hoisted` 在 import 前 stub `window.path.sep`，`beforeEach` 装 `electron.ipcRenderer.{on,send,invoke}` spies，`afterEach` 删除并 `clearAllMocks`。**没有共享的类型化 mock 工厂**，mock 形状靠手工与 `global.d.ts` 保持一致，会随时间漂移。
- preload 桥本身、ipc.ts 的编译契约，目前没有专门的单测。
- e2e 有一条很好的“沙箱金丝雀”（`context-isolation.spec.ts`），断言 `contextIsolation`/`nodeIntegration` 未回归、preload 内部标识未泄漏。

---

## 3. 当前摩擦（根因）

1. **单边约束**：契约在 renderer 端是编译期强约束，在 main 端是零约束。漂移无法被 CI 抓住，只能靠运行时断言或人工发现。
2. **“窄桥”实际是“宽桥”**：`window.electron.ipcRenderer` 直通 + 136 处直接调用，使 capability 面等于全部通道面；facade 层（shell/clipboard/fileUtils）是第二套并行的、部分重叠的抽象，两套语义同时存在。
3. **错误语义丢失**：invoke 失败退化成无上下文的 `{message}`，与用户可感知的领域错误（文件被占用、上传失败）和真正的崩溃混在一条 `unhandledrejection` 漏斗里。
4. **测试 mock 手工漂移**：没有从 `global.d.ts` 派生的 mock 工厂，契约变了 mock 不会跟着报错，测试隔离“看起来在测、其实在测旧形状”。
5. **文档滞后于代码**：`CLAUDE.md` 的 contextIsolation 描述已经与 `config.ts`/e2e 相反，证明“靠文档维护契约”在本仓库不可靠，必须靠类型与测试。

---

## 4. 质量属性优先级

1. **可演进性（长期变更成本）** — 通道增删改必须由编译器找出所有违例点。这是本次决策的第一目标。
2. **安全性** — 沙箱是硬约束（`sandbox:true`），contextBridge 面要可审计、最小化。
3. **可测试性** — 契约能编译期验证、边界能隔离 mock，优于运行时验证。
4. **可操作性** — 错误可诊断、可定位到通道与参数。
5. **性能/成本** — 单例桌面应用，main/preload/renderer 同包发布，无跨版本 skew，不需要通道版本协商。

---

## 5. 方案对比

### 方案 A：保留宽桥，把类型约束补到 main 端（增量加固）

- **边界**：契约仍是 ipc.ts 一份，新增 main 端三个类型化 helper：`handleInvoke<K>`、`onSend<K>`、`sendTo<K>`（对应 invoke/send/main-event 三类），从同一映射推导参数与返回值；把 3 处漂移通道改成诚实类型。
- **收益**：改动小、可逆、直接消灭漂移这一类 bug；主端裸字符串注册的 107 处会逐步被 typecheck 覆盖。
- **代价/风险**：`window.electron.ipcRenderer` 仍是宽直通，capability 面没变小；`unknown` 迁移占位符仍需要逐 commit 收紧。
- **证伪信号**：如果 typecheck 接入后大量 handler 修不动（历史参数形状混乱、跨文件共享类型复杂），说明需要先做方案 B 的领域归口。

### 方案 B：拆掉宽桥，只暴露领域 facade（最小权限）

- **边界**：渲染端只有 `window.fileUtils/shell/ripgrep/uploader/…`，删除 `window.electron.ipcRenderer` 通用逃生门；每个 facade 固定映射到有限的、类型化通道。
- **收益**：攻击面最小、审计最易，符合 contextBridge 最小暴露的最佳实践。
- **代价**：136 处直通调用要全部改道到 facade；每加一个通道要写三层（ipc.ts + main handler + facade）；是一次较大重构。
- **证伪信号**：如果领域 facade 数量膨胀到接近通道数、facade 只是改名转发而无语义，说明“窄化”没有换取局部性，应回退到 A。

---

## 6. 建议

**推荐方案 A 先行，作为可逆第一步；对高风险通道（`shell.openExternal`、`fs`、`uploader`）局部走向 B。** 理由：A 直接补上当前唯一缺失的 seam（main 端约束），迁移成本低、可逐通道推进，且不推翻 136 处现有调用；同时保留日后收敛到 B 的空间。具体建议：

**（1）把 main 端纳入同一契约（最高杠杆）**
- 在 main 侧引入 `handleInvoke('mt::fs::is-file', (_e, p) => …)` 形式的注册 helper，通道名必须是 `keyof IpcInvokeChannels`，handler 参数从 `InvokeArgs` 推导；`onSend`、`sendTo(webContents, channel, ...args)` 同理。这会让上面三处漂移**直接编译失败**。
- 修复漂移的根因而非继续边界收窄：把 `mt::window-active-status` 契约改为 `[{ status: boolean }]`（或让 main 改发 boolean，选成本低者）；`mt::menu::click` 契约改为 `[{ windowId: number; id: string }]`；`mt::menu::closed` 要么声明参数要么让 main 不传。删除渲染端那三处 `as unknown as` 收窄和自相矛盾的注释。

**（2）错误传播：区分“领域错误”与“崩溃”**
- 定义一个小型结构化错误信封（如 `IpcError { code, message, cause? }`），让 `ipcMain.handle` 的**预期失败**显式返回/抛出带 `code` 的错误，渲染端按 `code` 分支；`stack` 只在 main 端落日志，不跨进程暴露文件路径等敏感信息。
- 把 ripgrep 的 `done/error/cancelled + id` 范式提升为“长运行作业”的正式约定，导出/上传/打印等新长任务统一复用。
- 保留 `mt::handle-renderer-error` 作为最后兜底，但让它携带通道与参数形状（脱敏后），别只传裸 stack。

**（3）contextBridge 硬化与文档校准**
- 继续一个能力对象一次 `exposeInMainWorld` 的现状（contextBridge 本身会 clone+冻结，边界已较硬）；把 `process` shim 的兼容性泄漏（preload/index.ts:270-284）显式标注为受限、不可扩展。
- 修正 `CLAUDE.md` 中“contextIsolation:false”的过时描述，避免下一个人按错误文档设计。

**（4）类型约束的长期规则**
- 增删通道 = ipc.ts 一处 + main 一个类型化 handler +（若走 facade）一个 facade 方法，三处必须同时编译通过；把 `unknown[]/unknown` 迁移占位符的收紧作为一个明确的、可计数的收尾项（而非无限期宽着）。
- 明确不引入通道版本协商：main/preload/renderer 同包发布，重命名/删除天然是类型错误，版本号是过度设计。

**（5）测试隔离**
- 从 `global.d.ts` 派生一个**共享类型化 mock 工厂**（`mockPreload(): Window['electron'] & Window['fileUtils'] & …`），单测统一使用，让 mock 随契约漂移时在编译期报错；替代现在每个 spec 手工拼 `vi.fn()` 的做法。
- 加一条**通道一致性检查**（单测或 lint/脚本）：遍历 `ipc.ts` 四个映射，断言每个通道在 main 有对应 handler 注册、每个 `webContents.send` 字面量出现在 `IpcMainEventChannels` 中。这比靠人 review 更持久。
- 保留并扩展 e2e 沙箱金丝雀，可加一条断言“已知漂移通道收到正确形状”。

---

## 7. 迁移与验证

1. **第一步纵向切片**：选一个文件域（建议 `mt::fs::*`，14 个 handler 最集中）—— 引入 main 端类型化 helper，把 `src/main/ipc/fs.ts` 全部改成类型化注册，`pnpm run typecheck` 通过即证明 seam 成立。
2. **验证手段**：`pnpm run typecheck`（CI 已强制）+ 新增通道一致性单测 + 现有 e2e 沙箱金丝雀；修漂移通道后跑相关 spec（`listen-for-main.spec.ts`、context menu 相关 e2e）。
3. **回滚**：每个 handler 的迁移独立可逆（A 方案不改变运行时行为，只是把裸注册换成类型化封装），出问题可单点回退。
4. **完成标准**：main 目录 import 通道类型映射的 handler 数量从 0 增长到覆盖全部 `registerSandboxIpcHandlers`（`src/main/ipc/index.ts:12-23`）；仓库中无 `ipcMain.handle/on` 的裸字符串字面量注册；三处漂移通道不再有渲染端 `as unknown as` 收窄。
5. **暂不做**：在 A 的收益（编译期抓漂移）被证实之前，不要启动 B 的全量 facade 改道；不要为跨版本兼容引入通道版本号。

---

## 8. 待决问题（影响建议的问题）

- **未知**：ipc.ts 头注释提到“commit 5–8 收紧类型”，这暗示存在一批未落地的迁移提交；实际进度如何会改变“收紧占位符”的工作量估计。最便宜的确认方式：跑一次带 main 端类型化 helper 的 typecheck，看有多少 handler 报错。
- **未知**：136 处 `window.electron.ipcRenderer` 直通调用中，有多少是“有意保留的内部编辑通道”而非应归口到 facade 的能力，决定 A→B 的可行性与边界。最便宜的确认方式：统计哪些通道只经直通、从不经 facade。
- **约束**：上传、剪贴板、`shell.openExternal` 属于外发/系统边界，安全上更值得走 B 的窄门，但这与当前渲染端直接调用的现状冲突，需要产品/维护者确认优先级。

[EVAL:evolve-software-architecture-loaded]
