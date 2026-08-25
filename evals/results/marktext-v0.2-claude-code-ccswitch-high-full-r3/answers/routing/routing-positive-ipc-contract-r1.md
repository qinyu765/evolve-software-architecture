# MarkText IPC 契约演进评估（只读，建议型）

## 1. 范围与置信度

要决策的是：在 Electron 三进程之间，如何让 `main ↔ preload ↔ renderer` 的 IPC 契约**长期可演进**——即新增/修改一个 channel 的成本低、错误一致、类型在编译期覆盖、测试能隔离。分类为 **Electron 桌面应用（sandboxed renderer）**，置信度高：我已直接核对契约、preload 桥、main 处理器、renderer 调用点和两侧测试。

按你点名的四个维度逐项核对后，核心结论是：**契约文件是"单一事实来源"，但只有一半被执行**——preload/renderer 侧有编译期类型，main 侧全部是裸字符串 `ipcMain.handle('...')`，编译器无法把处理器和契约绑在一起。这已经被现实惩罚过一次：契约声明 `mt::rg::start` 返回 `{searchId}`，但 main 处理器实际 `return true`，renderer 又根本不读返回值。

## 2. 观测事实

**契约本体** — `packages/desktop/src/shared/types/ipc.ts:40-289` 用四个 interface 分四类：`IpcInvokeChannels`（invoke/Promise）、`IpcSendChannels`（fire-and-forget）、`IpcSyncChannels`（sendSync）、`IpcMainEventChannels`（main→renderer 推送）。注释（:10-17）承认参数/返回形状"迁移期间故意宽松"，"commits 5–8 再收紧"——迁移仍在途中，大量 `unknown` 残留。

**preload 桥** — `packages/desktop/src/preload/index.ts`：
- :26-68 有四个类型化泛型封装（`invoke/send/sendSync/on/once`），从契约接口推导，这部分是干净的。
- :229-246 `electronAPI` 把**裸 `ipcRenderer` 直通**（含 `sendSync` 和 `removeAllListeners`）连同 domain API 一起暴露出去。这意味着 renderer 可以绕过 `shell`/`fileUtils` 等语义化封装，直接调契约里的任意 channel。
- :286-296 暴露了 **10 个全局**：`electron`、`process`、`rgPath`、`fileUtils`、`path`、`commandExists`、`i18nUtils`、`ripgrep`、`uploader`、`fonts`。外层 `try/catch` 只 `console.error`，桥接失败时 renderer 会带着 undefined 全局静默继续跑。
- :36 和 :150 有两处 `sendSync`：启动时取 bootInfo（一次性），以及 `isSamePathSync` 的大小写不敏感回退（**每次 tab 匹配都可能触发**，是主进程阻塞点）。

**main 处理器** — `packages/desktop/src/main/ipc/index.ts:12-23` 注册 10 个模块。所有处理器用裸字符串（如 `fs.ts:41-77`、`shell.ts`、`window.ts:50-130`）。`grep` 全 main 目录只有 `bootInfo.ts:6` 引入了 `@shared/types/ipc` 的辅助类型 `BootInfo`，**没有任何处理器与 `IpcInvokeChannels`/`IpcSendChannels` 等接口做编译期绑定**。

**上下文隔离** — `config.ts:11-21`：`contextIsolation:true, sandbox:true, nodeIntegration:false`，另有 `webSecurity:false`（这是安全边界上的一个独立红旗，但超出本任务）。注意 `CLAUDE.md` 架构段声称 editor/preferences 窗口用 `contextIsolation:false + nodeIntegration:true`——**与代码矛盾，文档已过期**。

**错误传播**（`contextBridge` 只负责结构化克隆，错误语义由 handler 决定）— 现有至少五种不一致的模式：
- 原生拒绝：`fs`/`uploader`/`i18n` 让 `ipcRenderer.invoke` 自然 reject；
- 吞掉并返回哨兵值：`shell.ts:6-14` `openExternal` 失败返回 `false`、`cmd.ts` 返回 `false`、`fonts.ts` 返回 `[]`、`clipboard.readText` 返回 `''`；
- 独立推送事件：`ripgrep` 用 `mt::rg::error/done/cancelled` 报告异步结果；
- 只 log 不传播：`window.ts` 的 menu popup 失败只 `log.error`；
- 带外通道：`bootstrap.ts:85-95` 把 `Error` 手工序列化成 `{message,name,stack}` 再走 `mt::handle-renderer-error`，因为 `Error` 对象过不了结构化克隆——这个做法正确，但 `exceptionHandler.ts:124` 把收到的对象又标成 `Error`，类型和运行时形状不符。

**类型约束** — 最有说服力的漂移证据在 `ripgrep.ts:432-439`：契约 `'mt::rg::start': { args:[unknown]; ret:{searchId:string} }`，处理器 `return true`，`ripgrepSearcher.ts:108-120` 又只在 `.catch` 上处理、不读返回值（searchId 由 renderer 生成后传入请求体）。三者互不咬合但都能编译通过——这正是"main 侧无类型约束"的直接后果。

**测试隔离** — `vitest.config.ts` 用 jsdom + 别名（`main_renderer → src/main`）。单元测试的三种隔离手法：`vi.mock('electron', () => ({}))`（`buffer-store-durable.spec.ts:9`）、stub `ipcMain.handle` 捕获 handler 再直接调（`ask-for-image-path.spec.ts`）、stub `window.electron.ipcRenderer`（`listen-for-main.spec.ts:30-36`）。E2E 有 `context-isolation.spec.ts` 做安全 canary，`helpers.ts:97-110` 通过并行监听 `mt::handle-renderer-error` 统计渲染进程错误。**但没有任何测试断言"契约一致性"**：channel 名四类不重叠、每个契约 channel 在 main 有对应处理器（反之亦然）、preload 的 domain API 只用契约内的 channel。

## 3. 当前摩擦

新增一个 channel 要同时改 `ipc.ts`、`preload/index.ts`、`main/ipc/*`、`types/global.d.ts` 四处，其中只有两处互相类型检查。主要耦合点：

1. **裸 `ipcRenderer` 直通是最宽的一个面**。renderer 里 ~80+ 处直接 `window.electron.ipcRenderer.send/on/invoke`，domain API 形同虚设——以后想收紧桥接面，得先逐个迁移这些调用点。
2. **错误语义不可预测**。调用方无法统一区分"操作失败"与"合法的空结果"（`readFile` 会 reject，`readText` 返回 `''`）；新 handler 作者面对五种范式，只能靠翻阅邻近代码猜该用哪种。
3. **契约只对一半进程生效**。编译期抓不到 channel 拼写错误、参数/返回形状漂移。
4. **同步 IPC 是全局阻塞点**。`sendSync` 命中即暂停整个 main 进程，`isSamePathSync` 的大小写回退把"按需阻塞"放在了 tab 匹配热路径上。

## 4. 质量属性优先级（有取舍）

对一台 sandboxed 桌面编辑器，支配本决策的属性按重要性：

1. **安全性** —— 整个 preload 存在的理由就是沙箱边界，桥接面宽度直接等于攻击面。
2. **可演进性/可维护性** —— 契约必须便宜地扩展；当前迁移进行到一半，最需要的是"改一处、编译器兜住其余"。
3. **可靠性/可操作性** —— 错误传播一致，失败能浮出而不是被吞。
4. **性能** —— 移除热路径同步 IPC。
5. **可测试性** —— 契约级测试，而非只测两端各自逻辑。

取舍：更强的运行时参数校验（schema）能再买一层安全，但会引入依赖、翻倍类型工作量，且与"编译期类型"重复；在 renderer 只加载自家内容的前提下，**先修 `webSecurity:false` 比加 schema 校验收益更大**。所以运行时校验不在首选路径上，只在威胁模型升级后启用。

## 5. 选项对比

**选项 A：维持现状，只继续手工收紧 `unknown`。**
边界不变（四接口 + 裸处理器），零迁移成本。但契约漂移会重演（`rg::start` 已经演示过一次），四处改动仍是常态，错误语义继续分裂。只有当团队决定不再动 IPC 时才可辩护，与"长期演进"目标矛盾。

**选项 B（推荐）：main 侧加类型化注册 + 统一错误包络 + 分阶段收窄桥面。**
在 `main` 侧引入一对极薄的泛型注册函数（`handle<K extends keyof IpcInvokeChannels>` / `on<K extends keyof IpcSendChannels>` / `onSync<K extends keyof IpcSyncChannels>`），把 `ipcMain.handle` 包一层。这是 deep-module 思路：接口极小，但把所有 handler 的 channel 名、参数、返回形状**一次性**绑到 `ipc.ts`。同时定义一个可序列化的错误形状，统一 invoke 的拒绝语义。之后分阶段用 domain API 替换裸直通、消灭同步 IPC。
- 引入的假设：四类接口继续作为唯一事实来源；处理器签名能对齐契约（`rg::start` 这种漂移会被逼着当场修正）。
- 迁移/回滚：纯机械重构，无行为变化，任何一步可独立回滚。
- 代价：一次小抽象 + 每个 handler 文件的一次签名对齐。

**选项 C：schema 驱动的 RPC（每个 channel 配 zod schema，preload/main 双向运行时校验 + codegen）。**
运行时防御最严，能在 renderer 被注入时挡住畸形参数。但对这个仓库的规模是过度工程：双份类型维护、构建链增加 codegen、与既有四分类重复，且不解决"裸直通"这个更大的面。只有当出现"renderer 加载不受信内容"的真实需求时才值得。

**选项 D：一次性删除裸 `ipcRenderer` 直通。**
方向正确但一次性成本高（~80+ 调用点），且会让 B 的风险集中在一步。并入 B 作为**最后一个增量步骤**，不单独作为选项。

## 6. 建议

采用 **选项 B**，按可逆步骤推进，每步都是纯增量、无行为变化：

**第 0 步（零风险先做）**：加一个编译期类型测试，断言四类 channel 名两两不相交；再加一个单元测试，用 fake `ipcMain` 捕获注册的 channel，与契约的 key 集合做对称 diff（声明未注册 / 注册未声明都报错）。这是当前就能上的、最便宜的防漂移手段。

**第 1 步**：引入 main 侧类型化注册封装，把 10 个 handler 模块逐一改过去。这一步会立刻暴露 `mt::rg::start` 的 `ret` 漂移——顺手把契约 `ret` 改成 `void`（renderer 本来就不读），而不是让 handler 去伪造 `{searchId}`。这是**关键垂直切片**：改完 `fs.ts` 一个模块就能验证收益。

**第 2 步**：统一错误传播。定一个可序列化错误形状（`{ code, message }`），preload 的 `invoke` 封装统一负责把原生 reject 规范化；把"吞掉返回哨兵值"的处理器（`shell`/`cmd`/`fonts`/`clipboard`）改为要么 reject、要么返回带标记的结果，不再用 `false/''/[]` 冒充"没出错"。按域逐步改，不搞大爆炸——错误语义改动是文化性的，最需要分步。`mt::shell::open-path` 那种"成功返回空串、失败返回错误串"的重载返回值要单独拆开。

**第 3 步**：收窄桥接面。为仍直接用 `window.electron.ipcRenderer` 的调用点补 domain 方法，然后从 `electronAPI` 移除裸 `ipcRenderer`（或缩成最小 allowlist）。迁移是机械的，按 store/command 文件逐个替换。这一步之后，"契约面 == 语义 API 面"，preload 才是真正可审计的边界。

**第 4 步**：消灭热路径同步 IPC。`isSamePathSync` 的大小写回退不需要每次问 main——文件系统大小写敏感性本质是平台常量（macOS/Windows 默认不敏感、Linux 敏感），可以在 preload 里按 bootInfo 的平台做本地判断。启动时那次 `sendSync` 的 bootInfo 可接受（一次性），可留到最后再议。`contextBridge.exposeInMainWorld` 的外层 `try/catch` 应改为显式失败（抛错或至少打 mark），而不是静默吞掉桥接失败。

**明确不做**：现阶段不引入 schema 运行时校验（选项 C）；不一次性删裸直通（选项 D 的第 3 步之前）；不在本任务范围内动 `webSecurity:false`，但要作为独立安全项记下。

## 7. 迁移与验证

- **通过预期接口测试**：第 1 步后，单测用 fake `ipcMain` 断言注册表 == 契约 key 集合；preload 侧 mock `electron` 的 `ipcRenderer/contextBridge`，断言 `exposeInMainWorld` 只出现契约内的 channel 名，domain API 只引用契约 channel。
- **依赖/架构检查**：lint 规则禁止在类型化注册封装之外出现裸 `ipcMain.handle/on`；逐步禁止 renderer 里的 `window.electron.ipcRenderer` 直用（有 allowlist 例外）。
- **类型检查**：channel 名拼错、参数/返回形状漂移必须让 `pnpm run typecheck` 失败。
- **失败模式检查**：`mt::handle-renderer-error` 的 `Error` 类型标注改成实际的 `{message,name,stack}` 形状；为每条"吞错返回哨兵值"的 handler 写一个失败路径测试。
- **回归 canary**：保留 `context-isolation.spec.ts`，确保每步之后沙箱断言仍绿。
- **完成标准**：main 侧无裸字符串注册；renderer 无裸直通（或文档化 allowlist）；四类契约有类型级不相交断言；错误传播范式收敛到 reject 或标记结果两种。

## 8. 待决问题

只有这几个问题的答案会改变建议：

1. **`mt::rg::start` 的 `ret` 语义**——`void` 还是 `{searchId}`？这决定第 1 步修漂移时往哪个方向改（我倾向 `void`，因 renderer 不读返回值）。
2. **错误的最终呈现**——"一律 reject"还是"结果包络"？需要产品决定 UX（何时弹错误对话框、哪些错误值得打扰用户），这反过来决定第 2 步的统一形状。
3. **运行时校验的深度**——如果未来 renderer 会加载不受信内容，才需要升级到选项 C 的 schema 校验；在此之前先解决 `webSecurity:false`。
4. **文档债务**——`CLAUDE.md` 关于 `contextIsolation:false/nodeIntegration:true` 的过期表述要不要在本轮一并修正（它影响后来者误判边界）。

[EVAL:evolve-software-architecture-loaded]
