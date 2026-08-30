# MarkText Electron IPC 契约评估与演进建议

## 1. 范围与置信度

评估对象是 `main ↔ preload ↔ renderer` 三进程之间的 IPC 契约设计，重点核对四个维度：contextBridge 暴露面、错误传播、类型约束、测试隔离。仓库分类为 **Electron + Vue 桌面应用（pnpm monorepo）**，三进程边界清晰、渲染进程已沙箱化（CLAUDE.md 明确 `contextIsolation: true, sandbox: true, nodeIntegration: false`）。

置信度：**高**。以下结论全部来自对源码的直接阅读，关键证据都附了 `file:line`；涉及 Electron 框架行为的个别点（如错误序列化）会单独标注为框架事实而非仓库事实。

---

## 2. 观察到的现状（事实）

### 2.1 契约表已存在，但只是"声明式"的

`packages/desktop/src/shared/types/ipc.ts` 用四个接口表声明了全部通道：`IpcInvokeChannels`（invoke）、`IpcSendChannels`（fire-and-forget）、`IpcSyncChannels`（sendSync）、`IpcMainEventChannels`（main→renderer 推送）。文件头注释明确说这是 "single source of truth"（ipc.ts:2）。

但它**只在 preload 和 renderer 侧被消费**。preload 的泛型包装（`packages/desktop/src/preload/index.ts:26-68`）用它约束 `invoke/send/sendSync/on/once` 的通道名和参数；renderer 的 `global.d.ts` 又手工重复声明了一遍。

**main 进程的 handler 完全不引用这张表**。每个 handler 各自内联声明参数类型，例如 `packages/desktop/src/main/ipc/fs.ts:41` 的 `ipcMain.handle('mt::fs::is-file', (_e, p: string) => ...)`。这意味着契约表与 main 侧实现之间没有任何编译期约束，漂移是必然的。

### 2.2 契约表已经有多处"说谎"

以下是已核实的不一致（全部可以复现）：

| 通道 | 契约声明 | main 实际行为 | 证据 |
|---|---|---|---|
| `mt::rg::start` | `ret: { searchId: string }` | `return true`（布尔） | ipc.ts:72 vs ripgrep.ts:433-439 |
| `mt::shell::open-external` (invoke) | `ret: void` | 返回 `true`/`false` | ipc.ts:73 vs shell.ts:6-13 |
| `mt::clipboard::guess-file-path` | `ret: string \| null` | 永不返回 null，错误时返回 `''` | ipc.ts:43 vs shell.ts:49-68 |
| `mt::menu::click` | `[menuId: string]` | 发送 `{ windowId, id }` | ipc.ts:246 vs window.ts:38 |
| `mt::menu::closed` | `[]` | 发送 `{ windowId }` | ipc.ts:247 vs window.ts:107 |
| `mt::handle-renderer-error` | `[error: unknown]` | main 标成 `Error`，而 renderer 发的是纯对象 `{message,name,stack}` | ipc.ts:124 vs exceptionHandler.ts:124 vs bootstrap.ts:85-95 |

其中 `mt::menu::click` 的谎言甚至在 renderer 侧被显式绕过：`popupMenu.ts:76-79` 用 cast 取 `{ id }`，并留了注释承认"main 实际发的是 `{ windowId, id }`，契约被故意收窄"。

`mt::rg::start` 的谎言目前"碰巧无害"：renderer 只 `.catch()` 从不读 resolve 值（`ripgrepSearcher.ts:108-119`），所以没人发现拿到的不是 `{ searchId }`。这是契约失去约束力后最危险的一类——**靠调用方恰好不读返回值才不炸**。

`SerializedStat` 还有一份**重复且不一致**的定义：`fs.ts:6-13` 本地版含 `ctimeMs` 且 `isSymbolicLink` 必填，而共享版 `files.ts:9-15` 没有 `ctimeMs`、`isSymbolicLink` 可选。契约引用的是共享版，运行时走的是本地版。

### 2.3 contextBridge：桥存在，但信任边界是"虚"的

preload 暴露了 10 个全局（`preload/index.ts:287-296`）：`electron`、`process`、`rgPath`、`fileUtils`、`path`、`commandExists`、`i18nUtils`、`ripgrep`、`uploader`、`fonts`。

关键事实：`electron.ipcRenderer` 暴露的是**完整的泛型表面**（`invoke/send/sendSync/on/once/removeAllListeners`，preload:38-68），而 renderer 大量绕过精心封装的 service API（`fileUtils`、`shell`、`windowControl` 等），直接调用原始通道。我数过：

- 原始 `window.electron.ipcRenderer.*` 调用：**131 处 / 25 个文件**
- 封装 service API 调用：**121 处 / 32 个文件**

也就是说，`shellAPI`/`fileUtilsAPI` 这类"能力面"目前只是**便利层，不是安全边界**——renderer 里任何代码（包括渲染不受信任 Markdown 时可能出现的 XSS）都能通过 `window.electron.ipcRenderer.invoke('mt::fs::read-file', 任意路径)` 或 `send('mt::shell::open-external', url)` 直接驱动 main 进程的任意文件读写、shell 打开、上传等能力。sandbox 挡住了 Node 直连，但桥又把整套 IPC 能力原样放回去了。

另外两点：

- `process` 全局暴露了两次且形状不一致：`electron.process.cwd` 是字符串，而 `processShim.cwd` 是函数（`global.d.ts:87-92` vs `global.d.ts:168-176`）。
- 整个 `contextBridge.exposeInMainWorld` 包在 `try/catch` 里只 `console.error`（preload:297-299）——桥整体暴露失败时静默，renderer 拿到的是一片 undefined，极难诊断。

### 2.4 错误传播：两套相反约定并存

- **约定 A（抛错 → reject）**：fs 系列 handler 基本让异常自然抛出（fs.ts:41-76）。Electron 的 `invoke` 会把 rejection 传回 renderer，但默认只保留 `message`（`name/stack/code/cause` 在 structured clone 中丢失）——这是 Electron 框架事实，仓库里没有任何显式序列化来恢复它们。
- **约定 B（吞错 → 哨兵值）**：`shell.ts` 出错返回 `false`/`''`（shell.ts:8-13、44-46、64-67）；`is-executable` 任何异常都返回 `false`（fs.ts:65-76），把"stat 出错"和"确实不可执行"合并成同一个值；`isSamePathSync` 的 sync 回退 catch 后返回 `false`（preload:149-154）；`update-buffer-state` 无 `restoreBufferId` 时返回 `false` + warn（editorBufferStore/index.ts:191-194）。
- ripgrep 又走了**第三条路**：错误不进 invoke rejection，而是单独推 `mt::rg::error` 事件，载荷是 `{ searchId, error: string }`（ripgrep.ts:194-198、350-354）。同一个功能里并存"reject"和"错误事件"两条通道。

后果：renderer 无法区分"操作失败"和"合法的空/否结果"，错误原因（errno、stack）基本丢失，定位问题只能靠 main 侧 `electron-log`。

### 2.5 动态通道打破静态键模型

`mt::response-of-image-path-${id}` 是唯一的模板化通道：main 用模板串发送（`menu/actions/edit.ts:17,34,38`），renderer 只能靠 cast 绕过类型系统去 `once`（`editor.ts:450-458`，注释原话 "Dynamic IPC channel — not part of the static IpcMainEventChannels contract"）。用"通道名字面量作为类型键"的模型**无法表达参数化通道**，这类通道只能裸奔。

### 2.6 测试隔离：手搓桩、契约零覆盖

- `vitest.config.ts`：jsdom、`globals: true`、alias 里有 `main_renderer → src/main`（可用 jsdom 测 main 代码）。
- 测试通过**覆盖 `window.electron`** 来隔离桥，每个 spec 手写 `{ ipcRenderer: { on/send/invoke } }` 的 `vi.fn`（`listen-for-main.spec.ts:29-39`）。没有共享的桥 mock 工厂；store 一旦多用一个桥方法，无关 spec 的桩就会漏。
- `vi.hoisted` 在模块加载前手工塞 `window.path.sep`（listen-for-main.spec.ts:8-12），说明 store 图在**模块加载期**就读桥数据，测试隔离不干净。
- **没有任何 spec 校验契约表本身**：`rg::start` 返回类型、`menu::click` 载荷、`SerializedStat` 漂移对测试套件完全不可见。契约的"single source of truth"没有对应的 conformance 检查。

---

## 3. 当前摩擦的根因

一句话：**契约表被当作文档在用，而不是被当作类型/编译边界在用。** 具体展开：

1. main 侧不消费契约表 → 声明与现实漂移没有任何机制能拦住。
2. 桥暴露全量泛型 `ipcRenderer` → service API 变成装饰品，能力收窄和安全边界都无从谈起。
3. 错误约定不统一 → 每条通道的调用方必须单独猜"失败长什么样"。
4. 静态通道键模型 → 参数化通道被迫裸奔。
5. 测试没有契约级 seam → 漂移永远在 CI 之后才被发现（往往是通过用户 bug 报告）。

这些都是**偶发复杂度**，不是桌面编辑器领域的固有复杂度——桌面 IPC 本身就该有一个中心化、可编译期校验、可测试的 seam。

---

## 4. 质量属性优先级

对这个决策，真正起支配作用的属性按序是：

| 排名 | 属性 | 目标 | 当前证据 | 谁在取舍中让步 |
|---|---|---|---|---|
| 1 | **Security** | renderer 是沙箱，但桥不能把能力全放回去；特权通道要校验 sender 和参数 | 全量 `ipcRenderer` 暴露、131 处原始调用、fs/shell 通道接受 renderer 传来的任意路径/URL | 收窄会提高迁移成本 |
| 2 | **Maintainability** | 改一条通道只动一处，契约漂移被编译期拦住 | 表被 main 无视、`SerializedStat` 双定义、5+ 处契约说谎 | 引入更严格的类型层会增加少量样板 |
| 3 | **Testability** | 通过契约本身就能测，而不是手搓 `window.electron` 桩 | 无共享 mock、无 conformance 测试 | — |
| 4 | **Operability** | 失败可诊断、可区分"否"与"败" | 哨兵值吞错、错误丢失 stack/errno | 统一错误信封略增运行时成本 |
| 5 | **Performance** | 减少阻塞式 sync IPC | 启动期 `sendSync('mt::boot-info')`（preload:36）、路径比较回退 sync（preload:150） | 去掉 sync 需要改调用时序 |

**显式取舍**：安全（收窄桥）与成本（迁移 131 处调用）冲突；类型严格与样板代码量冲突。我的建议是**用阶段化方式同时拿到安全和类型约束，但把高成本步骤放到验证过威胁模型之后**，而不是一次性全做。

---

## 5. 方案对比

### 方案 A：保留现状形状，原地收紧（维持"单表 + 泛型桥"，但让 main 也消费这张表）

- 边界：`ipc.ts` 成为真正的编译期 seam，main 通过类型化的注册 helper（如 `registerInvoke('mt::fs::stat', handler)`）注册，handler 参数/返回类型从表推导；renderer 通过现有泛型包装调用。
- 同时：修掉已知契约谎言（或把契约改成与现实一致）、统一错误信封、加契约 conformance 测试。
- 迁移成本：**低**，不改 131 处调用点。
- 代价：安全边界仍然敞开（泛型 `ipcRenderer` 继续暴露），静态键模型仍表达不了动态通道。

### 方案 B：能力收窄（去掉原始 `ipcRenderer`，只暴露类型化 domain service）

- 边界：preload 只暴露 `fs / shell / window / search / i18n / menu / clipboard` 等能力面；renderer 拿不到任意通道。service API 已经存在，只需把 131 处原始调用迁移过去。
- 迁移成本：**高**，131 处调用、且部分跨切面通道（窗口生命周期、菜单/命令）不易塞进干净 domain service。
- 代价：安全收益真实但一次性改动大、回归风险集中在编辑/保存/关闭这些关键路径。

### 方案 C：验证式信封 + 运行时 schema（`Result<T,E>` 或 tagged union + zod/valibot 校验 + sender 校验）

- 边界：每条通道的输入输出都有运行时校验，main 侧对特权通道校验 `event.sender` 归属；错误统一为结构化信封（保留 name/message/code/stack/cause）。
- 迁移成本：**中高**，引入依赖、每通道需写 schema（或 schema 单源生成类型）。
- 代价：最健壮，但若对所有通道都做会过度工程化——大量内部通道根本不需要运行时校验。

---

## 6. 建议（推荐：A 起步，B/C 按威胁模型分级跟进）

**推荐路径是分阶段、可回退的，不一次性重写。** 目标不是"预测未来所有需求"，而是立一个中心化、编译期可校验、可测试的 seam，然后逐层收紧。

### 什么应当稳定 / 什么可以变化 / 什么还未知

- **应当稳定**：①通道方向+载荷表（契约即数据）；②统一错误信封形状；③四方向分类（invoke/send/event，sync 逐步淘汰）；④每个能力域一个桥入口。
- **可以变化**：通道名与载荷（这正是表存在的意义）、桥背后的实现、service 集合。
- **仍未知**：①renderer 是否渲染不可信 Markdown/HTML（决定 B 是"可选"还是"必须"）；②sync IPC 的实际启动/热路径开销（需一次 perf trace）；③能否接受在 sandbox preload + main 里引入运行时校验依赖（决定 C 的范围）。

### 阶段 1（现在做，最低风险、最高杠杆）：让契约表成为编译期事实

1. 给 main 侧加**类型化注册 helper**：`registerInvoke/registerSend/registerEvent` 从 `IpcInvokeChannels` 等表推导 handler 的 `(event, ...args) => ret` 签名。所有 `ipcMain.handle/on` 改走 helper 后，**channel 名打错、参数/返回类型不匹配都会在 typecheck 失败**。
2. 顺手修掉已核实的谎言，方向是"契约向现实靠拢"而非相反：
   - `mt::rg::start` 改成 `ret: void`（searchId 已经在请求里，返回 `{searchId}` 本就没被读）；
   - `mt::menu::click` 契约改成 `[{ windowId: number; id: string }]`，删掉 renderer 的 cast；
   - `mt::menu::closed` 改成 `[{ windowId: number }]`；
   - `mt::handle-renderer-error` 契约改成 `[error: { message: string; name: string; stack?: string }]`，与 bootstrap.ts 实际发送一致，并让 exceptionHandler 用这个类型；
   - 合并 `SerializedStat`，把 `ctimeMs`、`isSymbolicLink` 收进共享定义。
3. **消除动态通道**：把 `mt::ask-for-image-auto-path` 从"fire-and-forget + 模板化响应事件"改成普通 `invoke`（直接返回文件列表）。它本就是个请求-响应，用 `invoke` 顺理成章，模板通道这一整类问题随之消失。这是四条建议里收益最直接的一条。

### 阶段 2（统一错误传播）：一个信封，两种语义分开

1. 在 preload 的 `invoke` 包装和 main 的注册 helper 里加**显式错误序列化/反序列化**：handler 抛错时，把 `name/message/code/stack/cause` 装进结构化信封再 reject；renderer 侧 `invoke` 包装还原成 `Error`。这样 `await` 语法、现有 catch 逻辑全部保持不变，只是错误不再只剩 message。
2. **哨兵值只在"值域本身就含该值"时保留**：`is-executable` 对非文件返回 `false` 是合法结果，但对 stat 异常应 reject 而不是也返回 `false`；`guess-file-path` 没猜中返回 `''` 合法，但异常应 reject。规则一句话：**"失败"和"否/空"不能共用同一个返回值**。
3. ripgrep 的错误事件可以保留（它本质是流式推送的完成/错误信号），但把载荷从 `error: string` 升级成与 invoke 相同的错误信封，两条路共享一个形状。

### 阶段 3（收紧信任边界，先问威胁模型再定范围）

这是唯一需要先回答"未知 ①"的步骤：如果 renderer 会渲染用户打开的外部 Markdown/HTML（MarkText 的定位基本如此），那么**阶段 3 从"可选优化"升级为"必须做"**。

1. 先把**特权写/删通道**做 sender 校验和参数校验：`mt::fs::write-file / unlink / move / output-file`、`mt::shell::open-external`、`mt::uploader::upload` 不接受 renderer 传来的任意路径/URL，至少要校验 `event.sender` 属于已知窗口、路径落在合理范围。这是 B/C 的"高价值子集"，不必等全量收窄。
2. 全量去掉 `window.electron.ipcRenderer` 的原始暴露，让 131 处调用迁移到 domain service。**用 eslint `no-restricted-syntax` 逐步封禁**原始调用，让暴露面只缩不增；未迁移的通道走白名单过渡。

### 阶段 4（测试 seam）：契约本身要能被测

1. 从契约表**生成类型化 mock 工厂**（`createIpcMock()`），替代各 spec 手写 `window.electron = {...}` 桩。新增桥方法时 mock 自动跟上，不会再有"子集桩漏了"的脆弱性。
2. 加一个 **conformance 测试**：借助 `main_renderer` alias，在 jsdom 里用假 `ipcMain` 逐通道驱动注册 helper，断言每个 `handle` 通道的返回形状与契约一致、错误信封形状一致。这样 `rg::start` 这类谎言会在 CI 里炸，而不是靠用户报告。
3. 把模块加载期读桥数据（`window.path.sep`、`window.marktext.env`）收敛到可注入的 config 模块或统一 setup 文件，让 store 测试不再需要 `vi.hoisted` 手塞全局。

### 明确不做的事

- **不要**引入通用 RPC/消息框架，不要为所有通道上 zod/valibot——这是把"契约漂移"换成"schema 漂移"，成本翻倍。运行时校验只用于特权通道。
- **不要**一次迁移全部 131 处调用——用 eslint 封禁 + 白名单做单调收缩。
- **不要**把 `sendSync` 的启动握手急着删——先做一次 perf trace 拿到数据再说（未知 ②）。

---

## 7. 迁移与验证

- **回退性**：每个阶段独立可回退。阶段 1 是纯类型层 + 少量签名修正，`git revert` 即回退；阶段 2 错误信封向后兼容（`await`/`catch` 语义不变）；阶段 3 的 eslint 封禁是渐进收紧，可随时放宽白名单。
- **首个垂直切片**：挑一条特权通道（建议 `mt::fs::write-file`）走完整条链——契约表 → 类型化注册 → 错误信封 → sender/参数校验 → conformance 测试。跑通后其余通道复制模式。
- **验证手段**：
  - `pnpm run typecheck`：阶段 1 的注册 helper 让通道漂移变成编译错误。
  - conformance 测试：逐通道断言返回/错误形状。
  - CI 的 eslint 规则：原始 `ipcRenderer.*` 调用只减不增。
  - perf trace：`bootInfo` sendSync 与 `isSamePathSync` 的实际开销。
  - 安全复查：确认特权通道不再接受未校验的任意路径/URL。
- **完成标准**：契约表与 main/renderer 双侧实现零漂移（typecheck + conformance 双保险）；错误信封统一；特权通道有 sender/参数校验；动态通道清零；原始 `ipcRenderer` 调用数单调下降并最终归零。

---

## 8. 待定决策（答案会改变建议）

1. **威胁模型**：renderer 是否渲染用户打开的不可信 Markdown/HTML？——决定阶段 3 是"必须"还是"可选"，这是最该先拍板的一项。
2. **运行时校验依赖**：能否接受在 sandbox preload + main 引入 zod/valibot？——决定 C 的范围是"特权通道"还是"全量"。
3. **sync IPC 去留**：`sendSync('mt::boot-info')` 和 `isSamePathSync` 回退在启动/热路径上的真实开销？——需要一次 perf trace，而不是拍脑袋删。
4. **泛型桥的长期位置**：内部非特权通道是否永久保留一个受控的泛型 `ipcRenderer`，还是彻底走能力面？——影响阶段 3 的最终形态，但不影响阶段 1/2 立即开工。

---

**一句话总结**：契约表已经是正确的 seam，只是没有"牙齿"——先让 main 侧消费它、修掉谎言、消灭动态通道、统一错误信封，这是低风险高收益的现在动作；是否进一步收窄桥的安全边界，取决于"renderer 是否渲染不可信内容"这个威胁模型的答案。

[EVAL:evolve-software-architecture-loaded]
