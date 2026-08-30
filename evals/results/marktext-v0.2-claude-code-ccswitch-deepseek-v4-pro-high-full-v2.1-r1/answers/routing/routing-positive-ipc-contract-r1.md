# MarkText 三进程 IPC 契约：现状核对与长期演进建议

## 1. 范围与结论信心

**目标**：为 `main ↔ preload ↔ renderer` 设计一份能长期演进的 IPC 契约，并核对 contextBridge 边界、错误传播、类型约束、测试隔离四件事。只给建议，不动代码。

**仓库分类**：Electron 三进程桌面应用 + pnpm monorepo（`main`/`preload`/`renderer` 都在 `packages/desktop/src/`）。**【事实】** 这是一个已经"半只脚迈入类型化 IPC"的迁移中期状态：契约文件存在、preload 已泛型化，但 main 侧和运行时载荷还没被同一份类型管住。我对"当前是迁移中期、契约只约束了一半"这个判断信心很高——代码里明确写着"commits 5–8 逐条收紧"（`src/shared/types/ipc.ts:11`）。

---

## 2. 观察到的事实（带证据）

### 2.1 契约结构本身是好的起点

`packages/desktop/src/shared/types/ipc.ts` 用四个接口分类通道，命名与形状集中在一处：

- `IpcInvokeChannels`（`{ args, ret }`，renderer→main 有返回值）
- `IpcSendChannels`（tuple，fire-and-forget）
- `IpcSyncChannels`（`{ args, ret }`，同步）
- `IpcMainEventChannels`（tuple，main→renderer 推送）

preload（`src/preload/index.ts:26-68`）把 `invoke/send/sendSync/on/once` 做成泛型包装，`on/once` 返回退订函数——这是正确的方向。**【事实】**

### 2.2 类型约束只覆盖了一侧，且是"半侧"

- **main 侧完全不受契约约束**。所有 handler 都是裸字符串字面量 `ipcMain.handle('mt::fs::copy', ...)`，参数和返回值没有与 `IpcInvokeChannels` 挂钩（`src/main/ipc/fs.ts:41-76`）。**【事实】** 也就是说"单一真相源"目前只对 preload 的**编译期**有效；main 的返回值、参数个数、通道名打错都不会在编译期暴露。
- **renderer 全局类型是手写复制的第二真相源**。`src/types/global.d.ts` 把 `ElectronIpcRenderer`、`ElectronShellAPI`、`FileUtilsAPI`、`RipgrepAPI` 等十几个接口手写了一遍（`global.d.ts:24-204`），与 preload 里真正 `exposeInMainWorld` 的对象靠人工保持一致。**【事实】** 两处任何一处改了形状，另一处不会报错，这是漂移的主要来源。
- **`sendSync` 泛型包装没人用**。`src/preload/index.ts:40-43` 定义的 `sendSync<K>` 在仓库里没有调用者；实际两处同步调用（`mt::boot-info` 第 36 行、`mt::paths::is-same-sync` 第 150 行）都绕过包装直接 `ipcRenderer.sendSync(...)`。**【事实】**
- **ripgrep 的事件订阅也绕过类型化 `on`**，直接 `ipcRenderer.on('mt::rg::match', sub)` 并声明 `payload: unknown`（`src/preload/index.ts:190-219`）。**【事实】**

### 2.3 契约与运行时已经有明显失配（契约"说谎"）

这是最值得注意的一组事实，说明编译期类型在没有运行时校验时会被绕过：

| 通道 | 契约声明 | 运行时实际 | 证据 |
|---|---|---|---|
| `mt::rg::start` | `ret: { searchId: string }` | `return true` | `ipc.ts:72` vs `src/main/ipc/ripgrep.ts:438` |
| `mt::menu::click` | `[menuId: string]` | `{ windowId, id }` 对象 | `ipc.ts:246` vs `src/main/ipc/window.ts:38` |
| `mt::menu::closed` | `[]` | `{ windowId }` | `ipc.ts:247` vs `window.ts:107` |
| `mt::rg::match/progress/done/error/cancelled` | `[payload: unknown]` | `{ searchId, payload/num/error }` 结构化对象 | `ipc.ts:257-261` vs `ripgrep.ts:195-217` |
| `mt::shell::open-external` | 同时注册了 `handle` 和 `on`；契约里也同时出现在 Invoke 和 Send | preload 只用 `invoke`，`on` 分支疑似死代码 | `ipc.ts:73,170` vs `shell.ts:6,15`；全仓 grep 无 `send('mt::shell::open-external')` 调用者 |
| `mt::keybinding-get-pref-keybindings` | `ret: Map<string,string>` | handler 确实原样返回 `Map` | `ipc.ts:66-69` vs `app/index.ts:823-828`；但相邻的 `mt::request-keybindings` 路径显式 `Object.fromEntries` 转对象（`app/index.ts:814-815`） |

`mt::menu::click` 的失配尤其说明问题：renderer 端靠 cast 绕过并在注释里写"契约 `[menuId: string]` 是故意在边界收窄的"（`src/renderer/src/contextMenu/popupMenu.ts:76-79`）——**契约名不副实，代码用类型断言兜底**，这正是长期演进里最贵的那类债。

### 2.4 错误传播不一致

`ipcMain.handle` 抛错时，renderer 的 Promise 会 reject，但 Electron 会把它包装成 "Error invoking remote method …"，**丢失 stack 和自定义字段**。而当前各 handler 各自为政，语义不可区分：**【事实】**

- 吞掉并返回业务假值：`fs::is-executable` 捕获 stat 错误返回 `false`（`fs.ts:65-76`）；`cmd::exists` 抛错返回 `false`（`cmd.ts:6-26`）；`clipboard::read-text` 返回 `''`（`shell.ts:41-47`）；`clipboard::guess-file-path` 返回 `''`（`shell.ts:49-68`）。
- 把错误变返回值：`shell::open-path` 返回错误字符串（`shell.ts:25-32`）；`shell::open-external` 返回 `true/false`（契约却写 `ret: void`，`ipc.ts:73`）。

调用方无法区分"结果是 no/空"与"操作失败了"。**【推断】** 这是历史遗留 + 无统一错误信封共同导致的，不是某个 handler 的孤立问题。

### 2.5 contextBridge 边界核对：代码是真的，CLAUDE.md 是错的

**【事实】** 实际窗口配置（`src/main/config.ts:8-27`，注意是 `config.ts` 不是 `config.js`）：

```
contextIsolation: true, sandbox: true, nodeIntegration: false,
spellcheck: true, webSecurity: false
```

两个窗口（editor 和 preferences）都是这个形状（`config.ts:29-51`）。

**【事实】** 但 `CLAUDE.md` 的 "Architecture: Three-Process Electron Model" 一节写的是"editor and preferences windows use **contextIsolation: false + nodeIntegration: true**（see packages/desktop/src/main/config.js）"——与代码相反，且文件路径也不存在。CLAUDE.md 内部自相矛盾（同文档别处又说 sandboxed）。建议把这一节改正，否则后续任何人都可能按错误前提做安全判断。

**【事实】** `test/e2e/context-isolation.spec.ts` 是这条边界的金丝雀：断言 `window.electron.ipcRenderer.invoke` 可用、`require/global/Buffer` 均 undefined、preload 作用域标识符未泄漏到 renderer。这是很好的防回归测试。

**【事实·安全相关，值得单列】** `webSecurity: false` 在启用 `contextIsolation` 的同时关闭了 renderer 的同源策略。它确实削弱了沙箱边界（允许跨源加载）。**【推断】** 这是历史遗留（可能为本地图片/字体加载），建议单独评估能否去掉——它不是本次契约设计的核心，但属于"核对 contextBridge"时应当报出的一项。

### 2.6 测试隔离现状

- **main handler 单测靠手写 mock**：`test/unit/specs/ask-for-image-path.spec.ts:17-26` 把整个 `electron` 模块 mock 掉，用 `Map` 捕获 `ipcMain.handle` 注册的 handler 再直接驱动。这个隔离模式是对的，但**每个 spec 各写一遍，没有共享 harness**，且只覆盖了一个通道。**【事实】**
- **renderer 侧隔离靠手打 `window.electron` spy**：`listen-for-main.spec.ts:23-45` 手工构造 `window.electron.ipcRenderer` 的 `on/send/invoke` mock，测的是 Pinia store 而非真实 preload 桥。**【事实】**
- **没有任何测试验证"契约 ↔ 实际"一致性**：没有 spec 断言"契约里的每个通道在 main 都有 handler、main 注册的每个通道都在契约里"，也没有运行时校验。`menu::click` 的失配因此能长期存活。**【事实】**
- e2e 有 `sendIpcToRenderer` 辅助函数（`test/e2e/helpers.ts:355-367`）可注入 main→renderer 事件，说明 e2e 层已经具备测事件通道的能力。**【事实】**

### 2.7 遗留通道与重复通道（迁移残留）

契约里保留了一批**无 `mt::` 前缀**的遗留通道（`update-buffer-state`、`set-image-folder-path`、`screen-capture`、`watcher-*`、`window-*`、`app-*` 等），还有**成对重复**：`set-user-preference` / `mt::set-user-preference`、`window-add-file-path` / `mt::window-add-file-path`、`window-toggle-always-on-top` / `mt::window-toggle-always-on-top`（`ipc.ts:92-202`）。**【事实】** 这与 CLAUDE.md 所述"legacy `muya/` alias 调用点仍在收敛"一致。

---

## 3. 当前摩擦

1. **改一条通道要动 3–4 个地方，且其中两处靠人工同步**：契约文件、main 注册、preload 暴露、global.d.ts。类型漂移没有编译期护栏。
2. **契约目前只是"半真"**：preload 编译期受约束，main 和运行时载荷都不受约束；`menu::click` 的 cast 绕行就是证据——契约失去权威后，开发者会开始"用断言纠正契约"而不是"修契约"。
3. **错误语义在边界上丢失**：`false`/`''` 既是合法结果又是失败信号，renderer 无法决策（重试？提示用户？静默降级？）。
4. **测试隔离能力存在但不成体系**：mock 手法正确、e2e 金丝雀到位，但没有可复用的契约一致性检查，所以失配只能靠人肉发现。

---

## 4. 质量属性优先级

对本决策真正起支配作用的是：

1. **可演进性 / 可维护性**（最高）——"新增一条通道只改一处、改形状编译器会喊"是这份契约的全部价值。
2. **可测试性**——契约一致性必须能被 CI 断言，否则再漂亮的类型也会重新漂移。
3. **安全性（沙箱边界完整性）**——`contextIsolation:true` 是硬约束，契约设计不能倒退回 `nodeIntegration`；顺带评估 `webSecurity:false`。
4. **运行性能**——同步 IPC 最小化（现状只有启动握手 + 罕见的大小写路径判断，是合理的；不新增同步通道）。

**明确取舍**：追求"类型完全覆盖 + 运行时完全校验"会引入 schema 库/代码生成的重度机制，与当前"迁移中期、渐进收紧"的节奏不符。我建议**以类型为唯一真相源、运行时校验只做 dev-only 的廉价断言**，而不是引入运行时 schema。

---

## 5. 方案对比

### 方案 A：维持现状，只修失配 + 补文档

- **边界与所有权**：继续以 `ipc.ts` 为参考文档，preload 泛型约束，main 自由。
- **好处**：零机制成本，最快止血。
- **代价**：类型约束永远只覆盖一侧；失配会再次出现（`menu::click` 已经证明人肉守护不可靠）；测试隔离继续各写各的。
- **何时该被证伪**：如果团队规模/改动频率低到"通道半年不新增一条"，这可能就够用。但当前仓库正在做 sandbox 迁移、通道大量变更，**【推断】** 不满足这个前提。

### 方案 B：类型驱动的注册辅助函数（推荐）

- **边界与所有权**：`ipc.ts` 成为唯一真相源；main 通过泛型 `handleContract/onContract/sendContract` 注册，preload 通过泛型 `invoke/on` 暴露，renderer 全局类型**从 preload 对象推断**而非手写。运行时加一个 dev-only 校验器断言"契约通道 ↔ 已注册 handler 双向一致 + 载荷可结构化克隆"。
- **好处**：新增/修改通道时，main、preload、renderer 三侧同时被编译器约束；`global.d.ts` 手写复制消除；失配在 CI 里变成红测试而非运行时事故。
- **代价**：一次性的 helper 编写 + 全量 handler 签名替换（机械、可分批）；对"契约文件"的写法要求更严（载荷必须写准）。
- **假设**：团队接受"契约文件是权威，运行时偏差即 bug"。

### 方案 C：代码生成（contract → preload + d.ts + 校验器）

- **边界与所有权**：比 B 更进一步，把 preload 与 global 类型都生成出来。
- **代价**：引入生成步骤和构建顺序问题；对一个 ~90 通道的中型桌面应用**【推断】** 属于过度抽象，收益与 B 重叠。**暂不推荐**，等通道数或团队规模上一个量级再重议。

---

## 6. 建议（方案 B 的分阶段路径）

核心一句话：**让 `ipc.ts` 真正成为唯一真相源，三侧都从它派生，运行时只做 dev-only 断言。**

### 第 1 步：先让契约说真话（止血，不引入机制）

把 2.3 表里的失配全部纠正，让契约与实际一致，删掉 renderer 里的 cast 绕行：

- `mt::rg::start` → `ret: boolean`（或改成真正回传 `{ searchId }`，二选一，建议 `void`/`boolean` 更诚实）；
- `mt::menu::click` → `[{ windowId: number; id?: string }]`，`mt::menu::closed` → `[{ windowId: number }]`；
- `mt::rg::*` 五个事件 → 各自结构化载荷类型（`{ searchId, num }`、`{ searchId, payload }`、`{ searchId, error? }` …），不再 `unknown`；
- `mt::shell::open-external` 去掉 `on` 分支和 Send 里的重复条目，只保留 invoke；`ret` 从 `void` 改为真实返回的 `boolean`；
- `mt::keybinding-get-pref-keybindings` 的 `Map` → `Record<string,string>`（在 main 侧 `Object.fromEntries`，与 `mt::request-keybindings` 路径保持一致），**契约上明确禁止 `Map/Set/函数/类实例` 作为 wire 类型**——结构化克隆对它们是陷阱。

### 第 2 步：把 main 侧纳入同一份类型

在 `src/main/ipc/` 加一个薄 helper（不改变现有 handler 逻辑，只包一层注册）：

- `handleContract<K>(channel: K, fn: (e, ...args: InvokeArgs<K>) => InvokeRet<K> | Promise<InvokeRet<K>>)`；
- `onContract` 同理，`sendContract` 对 `webContents.send` 做 `SendArgs/EventArgs` 约束。

这样 main 侧参数个数、返回类型、通道名全部被 `IpcInvokeChannels` 编译期约束。这是把"单一真相源"从半侧变全侧的关键一步。

### 第 3 步：renderer 全局类型改为从 preload 推断

`global.d.ts` 里十几个手写接口改成一行方向：

```ts
type ExposedBridge = typeof import('../preload/index')  // 概念示意
```

即让 `Window.electron` / `Window.fileUtils` 等的类型**直接来自 preload 里传给 `exposeInMainWorld` 的对象**（TypeScript 的 `typeof`），而不是手写复制。手写复制删除后，preload 一改，renderer 调用点立刻获得正确的类型。

### 第 4 步：统一错误传播信封

- **invoke 失败 = reject**，且 main 侧统一包装成一个可序列化信封，而不是各 handler 吞掉：
  ```ts
  // 概念示意：业务"假值"与"系统错误"分开
  type IpcError = { code: string; message: string; cause?: string }
  ```
  Electron 会把 reject 的 `Error` 压成 "Error invoking remote method"，所以**在 main 侧捕获、把 `code/message/stack` 塞进一个普通对象再 reject**，renderer 拿到的是完整信封。
- 只有**语义上就是"查询结果"**的通道才允许返回 `false/''/null`（如 `cmd::exists`、`path-exists`）；凡是"操作失败"必须走 reject。
- 同步通道保持现状只有两个（启动握手 + 大小写路径判断），**不新增**；同步调用天然无法传递丰富错误，这本身就是约束。

### 第 5 步：dev-only 运行时校验（防"契约说谎"复发）

- main 启动时（仅 `NODE_ENV === 'development'` 或 `PERF_TESTING`）断言：契约里每个 `IpcInvokeChannels/IpcSendChannels/IpcSyncChannels` 键都有已注册 handler，且每个已注册通道名都在契约里（双向，能同时抓"漏注册"和"写错通道名/死 handler"）。
- 事件载荷在 renderer 边界做**轻量 decoder**（不是完整 schema 库，只验证顶层形状并 fail-fast），把"main 发了对象、renderer 期待 string"这类 bug 从"运行时偶发 undefined"变成"开发期立刻报错"。

### 第 6 步：测试隔离体系化

- 抽一个共享 harness：mock `electron` → 捕获所有 `ipcMain.handle/on` 到一个 `Map`，`ask-for-image-path.spec.ts` 已经示范了正确手法，把它泛化到 `test/unit/helpers/`。
- 加一个**契约一致性 spec**：用契约文件的通道名列表去断言 main 的注册表（配合第 5 步的注册表导出，纯数据断言，不启动 Electron）。
- preload 桥本身用 fake `ipcRenderer` 做单测（断言 `invoke` 传的通道名/参数、`on` 返回退订函数）。
- e2e 保留 `context-isolation.spec.ts` 金丝雀，并用已有的 `sendIpcToRenderer` 补一两条事件通道往返的集成断言。

### 第 7 步：顺带把 CLAUDE.md 修掉

把 Three-Process 一节改成与 `config.ts` 一致的 `contextIsolation: true / sandbox: true / nodeIntegration: false`，并把 `config.js` 改成 `config.ts`。这是文档级建议，防止错误前提继续传播。

---

## 7. 迁移与验证

**每步可逆、先垂直切片**：第一步先拿"一组 fs 通道 + rg 一组通道"做垂直切片（改契约→改 main→改 preload→改调用点→加一致性 spec），跑通后再全量机械替换。

**退出准则（可观测）**：

- `pnpm run typecheck` 与 `pnpm run lint` 通过；
- 新增契约一致性 spec：改一个通道名会红、漏注册会红、写错返回类型会红；
- "新增一条通道只改一个文件"成为常态（main/preload/renderer 类型都从契约派生）；
- 删除 `global.d.ts` 中手写复制的接口后 renderer 零改动通过编译（证明推断类型等价）。

**回滚**：每一步都是"加 helper/改类型"级别，revert 单 commit 即可；不引入运行时 schema 库，所以没有运行时依赖回滚问题。

**验证建议**：对错误信封，专门写一个 handler 故意抛错的单测，断言 renderer 拿到的 reject 值含 `code/message`；对事件载荷，用 decoder 的 fail-fast 单测覆盖 `menu::click` 这类曾经失配的通道。

---

## 8. 开放决策（只有这些能改变建议）

1. **是否接受引入代码生成**（方案 C）——如果未来通道数翻倍或出现多窗口/多产品复用同一契约的需求，重议方案 C。
2. **`Map` 在 Electron 结构化克隆里到底可不可靠**——`keybinding-get-pref-keybindings` 目前真的在过 `Map`。**最便宜的验证**：dev 下 `console.log(await window.electron.ipcRenderer.invoke('mt::keybinding-get-pref-keybindings'))` 看是 Map 还是被转成了空对象/报错。这决定第 1 步那条是"必须改"还是"仅规范风格"。
3. **错误是否需要用户可见分级**（如"可重试/需上报/静默"）——决定信封里要不要加 `severity` 字段。
4. **遗留非 `mt::` 通道的退役时间线**——如果 muyajs 通道还要活很久，建议给它们一个独立的 `LegacyIpcChannels` 命名空间，避免和正式契约混在同一个接口里继续"宽容 unknown"。

---

（本次为只读审查，未修改任何文件。需要的话我可以把第 2 步的 `handleContract/onContract/sendContract` helper 和契约一致性 spec 写成具体草案供评审。）

[EVAL:evolve-software-architecture-loaded]
