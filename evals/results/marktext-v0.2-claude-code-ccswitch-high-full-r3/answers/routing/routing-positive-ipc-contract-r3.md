我已完成对仓库 IPC 现状的 read-only 核查。结论先行：MarkText 已经把 IPC 契约推进到了**单向类型化**的较好状态——渲染器/预加载侧通过泛型桥和 `window` 环境声明得到了完整约束，但**主进程注册侧完全不受契约约束**，这已经造成了至少两处「契约说谎」；同时 contextBridge 暴露面与手写的 ambient 声明是两份平行真相、错误传播没有统一包络。下面按决策级建议展开，全部只给方案、不动代码。

## 1. 范围与置信度

- **决策对象**：Electron main / preload / renderer 三进程间 IPC 契约的长期演进设计，重点核对 contextBridge 暴露面、错误传播、类型约束、测试隔离。
- **仓库分类**：Electron + Vue 3 桌面编辑器（`contextIsolation: true, sandbox: true, nodeIntegration: false` 的沙箱渲染器），主/预加载编译为 CommonJS、渲染器 ESM-only。
- **置信度**：**高**。以下结论全部来自对 `packages/desktop` 源码与测试的直接阅读，关键推断已逐条标注。

## 2. 观察到的现状（事实，含证据）

- **契约单一来源已存在**：`packages/desktop/src/shared/types/ipc.ts:40-289` 定义四类通道（`IpcInvokeChannels` / `IpcSendChannels` / `IpcSyncChannels` / `IpcMainEventChannels`），注释明确这是迁移期的**宽松类型**（`unknown[]` / `unknown`，见 `ipc.ts:10-12`）。
- **预加载桥是类型化的**：`packages/desktop/src/preload/index.ts:26-68` 用泛型包了 `invoke/send/sendSync/on/once`，`on`/`once` 返回取消订阅函数（`ipc.ts:45-64`）。同步握手 `bootInfo` 在预加载里 `sendSync('mt::boot-info')`（`preload/index.ts:36`）。
- **contextBridge 暴露 10 个全局对象**：`preload/index.ts:286-296`（`electron`、`process`、`rgPath`、`fileUtils`、`path`、`commandExists`、`i18nUtils`、`ripgrep`、`uploader`、`fonts`），外层 `try/catch` **吞掉暴露失败**只 `console.error`（`:297-299`）。
- **ambient 类型是手写的第二份真相**：`packages/desktop/src/types/global.d.ts:24-205` 逐接口复述了预加载对象（`ElectronIpcRenderer`、`FileUtilsAPI`、`RipgrepAPI`…），但预加载实现**并不** `satisfies` 这些接口——两边可以各自漂移而 typecheck 不报。
- **主进程注册完全未受契约约束**：`ipcMain.handle/on` 全部用裸字符串字面量注册，例如 `fs.ts:41-64`、`window.ts:51-88`、`bootInfo.ts:76-84`、`ripgrep.ts:433-443`。全 `src/main` 中**只有 `bootInfo.ts:6` 导入了 `BootInfo` 类型**，没有任何文件导入 `IpcInvokeChannels` 等契约接口（grep 证实）。
- **已经存在两处契约谎言**（事实，且是单向约束的直接后果）：

| 通道 | 契约声明 | 主进程实际返回 |
|---|---|---|
| `mt::rg::start` | `ret: { searchId: string }`（`ipc.ts:72`） | `return true`（`ripgrep.ts:438`） |
| `mt::shell::open-external` | `ret: void`（`ipc.ts:73`） | `return true/false`（`shell.ts:6-14`） |

  目前侥幸不炸：渲染器对 `ripgrep.start` 的返回值是 fire-and-forget（`node/ripgrepSearcher.ts:108-119` 只 `.catch`）。但任何按契约写 `const { searchId } = await ripgrep.start(...)` 的新调用方都会拿到 `undefined`。
- **错误传播无统一契约**：`fs.ts` 让错误**裸 reject**（渲染器拿到的 Electron 序列化错误会丢失 `err.code/errno` 等自定义字段、`message` 被加前缀）；`shell.ts`、`cmd.ts` 把失败**吞成 `false`/`''`**；`uploader.ts` 又**裸 throw**。三种风格并存。
- **渲染器→主进程错误上报先被拍平**：`bootstrap.ts:85-95` 把 Error 拆成 `{message,name,stack}` 纯对象再 `send('mt::handle-renderer-error')`；而 `exceptionHandler.ts:124-126` 把入参当作 `Error` 用——契约与实际跨进程载荷不一致。
- **注册散落**：契约里的 `mt::fs-trash-item` 处理器不在 `ipc/fs.ts`，而在 legacy 模块 `app/index.ts:847`；`mt::shell::open-external` 同时注册了 `handle` 和 `on` 两个语义（`shell.ts:6-17`），`on` 版本经预加载桥永远走不到。安全配置本身是正确的：`config.ts:12-20` 明确 `contextIsolation: true, sandbox: true, nodeIntegration: false`。
- **CLAUDE.md 的架构段已过期**：它写「editor 和 preferences 窗口使用 `contextIsolation: false + nodeIntegration: true`（见 `src/main/config.js`）」，但实际文件是 `config.ts` 且值是 `true/sandbox/true`。这是文档漂移，会误导后续 IPC 工作。
- **测试隔离现状**：e2e 金丝雀 `test/e2e/context-isolation.spec.ts:24-38` 断言沙箱边界；单测 `test/unit/specs/listen-for-main.spec.ts:8-12` 必须在 `vi.hoisted` 里**预先打桩整个 window 表面**（`window.path.sep`、`window.electron.ipcRenderer`、`window.marktext.env`）才能让 store 图加载——说明 bridge 是「环境全局强耦合」，单测成本高。**没有任何针对 IPC 契约本身的单测**（`test/unit/**/*ipc*` 为空）。

## 3. 当前摩擦（变化放大点）

1. **约束是单向的**：渲染器侧改错通道名/参数会 typecheck 失败，主进程侧改错不会。契约声称是「单一事实来源」，但主进程根本不读它。两处谎言就是代价，且未来只会更多。
2. **两份手写表面会漂移**：预加载对象 ↔ `global.d.ts` 之间没有编译期连接，只在渲染器使用点被校验。预加载漏写/改错一个方法，渲染器用法照常通过、运行时才炸。
3. **错误无法分支**：渲染器拿不到 `err.code`，只能靠被加前缀的 `message` 字符串匹配（脆弱、跨平台不稳定）。文件不存在 vs 权限不足 vs 取消，三种语义被压成同一种「reject」或「false」。
4. **注册与契约脱钩**：`mt::fs-trash-item` 的处理器藏在 `app/index.ts`，无法从契约声明定位处理器，也无法发现「声明了但没注册」或「注册了但没声明」的通道。
5. **测试耦合到 window 全局**：想单测一个「监听主进程事件」的 store，必须重建整个 contextBridge 表面，且 `on` 返回的取消订阅函数全仓库无一处使用——HMR/重复初始化下监听器可能累积（**推断**，未实测复现）。

## 4. 质量属性优先级

按本决策的支配性排序：

| 优先级 | 属性 | 理由与取舍 |
|---|---|---|
| 1 | **可演进性（长期变更成本）** | 契约是跨三进程的稳定面，当前单向类型+双份表面会让每次加通道都产生隐性债务 |
| 2 | **可测试性/隔离** | 契约无法脱离 Electron 做往返测试，是「契约谎言」能存活至今的根因 |
| 3 | **安全边界** | `webSecurity: false`（`config.ts:19,40`）意味着渲染器一旦被 XSS 可利用 `window.electron.*` 调用任意通道，主进程侧入参校验变得更重要 |
| 4 | 性能 | `bootInfo` 同步握手、`isSamePathSync` 的同步回退已有意权衡过，无需动 |

明确**不**追求：全量运行时 schema 校验（见方案 C）、把所有 `unknown` 立刻收紧（一次性重写成本高、回报不均）。

## 5. 方案对比

**方案 A（推荐）：把契约变成「双向、可派生、带错误包络」的唯一真相源，分步推进。**
- 边界：`shared/types/ipc.ts` 仍是唯一来源；新增 main 端类型化注册包装器 + 由预加载对象派生的 `PreloadApi` 类型 + 统一 `IpcResult` 错误包络。
- 收益：两处谎言在编译期暴露；preload↔ambient 漂移被消除；渲染器可凭 `code` 分支；注册可被遍历/断言。
- 成本：低——纯类型+薄包装，逐个域迁移，每步可逆。引入的假设：Electron `ipcMain.handle` 的裸 reject 语义需要被业务代码显式选择（结果包络 vs 原始异常），这是一条要写进注释的约定。
- 会使方案失效的证据：若发现大量通道**必须**依赖 `handle` 抛错的原始行为且无法改（例如第三方消费），或团队决定整体迁离 Electron。

**方案 B（维持现状，单向类型 + 手写 ambient）。**
- 边界：与现在完全一致。
- 收益：零迁移成本，渲染器侧笔误已被捕获，主进程侧稳定期也够用。
- 成本：上面第 3 节全部摩擦继续累积；契约谎言的样本会随通道数线性增长。
- 这是**可辩护的短期选择**，但不是长期演进路径。

**方案 C（全量运行时校验：给每条消息上 zod/io-ts schema）。**
- 边界：main 端入参在进 handler 前先过运行时校验，防御渲染器被 XSS 后发送畸形载荷。
- 收益：对 `webSecurity:false` 是真正的安全增强。
- 成本：重——需要维护与 TS 类型平行的运行时 schema，性能有开销，且大部分通道接收的是受信本地渲染器。
- 结论：**不作为全局层**，退化为「危险通道定点校验」（文件路径、`shell::open-external/on`、`uploader` 的入参）。

## 6. 建议（选定方案 A 后的具体形态）

**（a）让契约双向生效。** 在 `src/main/ipc/` 提供类型化注册包装（形如 `handle<K extends keyof IpcInvokeChannels>(channel: K, fn: (event, ...args) => IpcInvokeChannels[K]['ret'])`，`on`/`sendSync` 同理），先只包住新的 `ipc/*` 集合，再逐域收编 legacy 模块。这样通道名、参数元组、返回类型在主进程端也进 typecheck。**第一步就会当场抓出 `mt::rg::start` 与 `mt::shell::open-external` 两处谎言**——这是该方案的第一个可验证收益。

**（b）让 contextBridge 表面只有一个来源。** 定义一个 `PreloadApi`（含 `electron`、`fileUtils`、`ripgrep` 等全部暴露键），预加载用 `satisfies` 约束各对象，`global.d.ts` 的 `declare global { interface Window }` 直接引用同一类型，而不是手写复述。`exposeInMainWorld` 包一层 `expose<K extends keyof PreloadApi>(key: K, api: PreloadApi[K])`。效果：预加载实现、ambient 声明、渲染器用法三者共享一个类型，任何一侧漂移都变编译错误。

**（c）统一错误传播契约，只分两类。**
- **可预期业务失败**（文件不存在、路径非法、ripgrep 非零退出、上传器缺失）：handler 返回 `{ ok: true, value } | { ok: false, code, message, cause? }` 结果包络，不裸 throw。原因：Electron `ipcMain.handle` 的 reject 序列化会丢 `err.code` 并给 `message` 加前缀（**事实**，Electron 既有行为），渲染器无法可靠分支。类型上把 `IpcInvokeChannels[K]['ret']` 允许声明为 `IpcResult<T, E>`，并引入共享错误码联合（`'ENOENT' | 'EACCES' | 'EPERM' | 'UPLOADER_NOT_FOUND' | ...`）。
- **编程错误**（主进程 bug）：保持裸 reject，走现有 `mt::handle-renderer-error` → 崩溃对话框路径。
- 顺手修两处不一致：`bootstrap.ts:85-95` 拍平 Error 上报与 `exceptionHandler.ts:124` 的 `Error` 类型之间的错位；`shell.ts:6-17` 删除 `mt::shell::open-external` 的双注册（`on` 版本经桥不可达）。

**（d）测试隔离分层。**
- 保留并扩展 e2e 金丝雀 `context-isolation.spec.ts`：断言完整暴露键集合（`Object.keys(window.electron)` 等），防止 contextBridge 面增删被静默放过。
- 新增**纯 jsdom 契约往返测试**：用类型化 main 包装器注册 fake handler，再用预加载桥泛型调用，断言参数/返回/错误包络的往返一致。这不需要 Electron，是「契约可测试」的落点，也是方案 B 与 A 的分水岭。
- 给渲染器 store 引入一个**惰性 `ipc` 访问器模块**（读取 `window.electron.ipcRenderer` 的薄封装），让 `listen-for-main.spec.ts` 这类测试 mock 访问器而非 `vi.hoisted` 全量打桩 window。
- 补一条 `on` 返回取消订阅函数的单测，验证移除监听后不再投递（当前此能力零使用、零测试）。

## 7. 迁移与验证

可逆步骤（每步独立可回滚）：

1. 建类型化 main 注册包装器 + `IpcResult` 类型，**只把 `src/main/ipc/*` 换过去**，跑 `pnpm run typecheck` —— 预期编译失败暴露两处谎言，修正契约或实现使之一致。
2. 引入 `PreloadApi` 并让 `global.d.ts` 派生 —— typecheck 会暴露所有 preload↔ambient 的真实漂移。
3. 按流量排序收紧 `unknown`：优先 `update-buffer-state`（已有 `BufferedState` 类型可复用）、`mt::update-file`（已有 `FileChangeDetail`）、ripgrep 各 `mt::rg::*` 载荷、watcher 载荷。每个域单独一个 PR。
4. 错误包络逐域替换（先 fs，再 uploader/shell），并在渲染器把 `err.message` 字符串匹配改成 `code` 分支。
5. 最后收编 legacy 注册模块（`app/index.ts`、`dataCenter`、`editorBufferStore` 等）进类型化包装器，使「声明↔注册」可遍历断言。

**退出标准（可观测）**：`pnpm run typecheck` 在 main 端也纳入契约；`src/main` 中 `@shared/types/ipc` 的导入从「仅 BootInfo」扩展到每个注册模块；契约往返单测通过；e2e 金丝雀覆盖完整暴露面。**验证方式**：`pnpm run typecheck`、`pnpm run lint`、新增契约往返测试、e2e `context-isolation.spec.ts`，以及一次人工 diff 评审确认没有新增裸 `ipcMain.handle/on` 字符串注册。

**现在不要做**：全量运行时 schema 校验（方案 C）、一次性把所有 `unknown` 收紧、`mt::` 前缀全量改名。等前四步落地、调用点普查完成后，再评估命名去重（如 `window-add-file-path` 与 `mt::window-add-file-path` 并存）是否值得单独立项。

## 8. 待决问题（答案会改变建议）

1. `webSecurity: false` 是否仍必需、依赖它的功能有哪些？（**未知**——决定 main 端运行时入参校验的优先级高低；若可收敛为按需关闭，安全面会大幅缩小。）
2. 渲染器 XSS 威胁模型是否纳入本期？（决定是否提前做「危险通道定点校验」。）
3. 错误包络是否携带 `stack`？（跨进程泄栈与可诊断性之间的取舍，需要产品/安全口径。）
4. 是否还有走 `muya/` 别名（legacy `packages/muyajs`）绕过 `window.electron.*` 的 IPC 调用点？（**未知**——需要一次渲染器侧 `ipcRenderer`/legacy preload 调用点普查，决定契约收口的完整度。）

[EVAL:evolve-software-architecture-loaded]
