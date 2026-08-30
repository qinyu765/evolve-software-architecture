我已核对完仓库里 IPC 契约的全链路（契约类型、preload 桥、main 侧 handler 注册、渲染侧消费、测试配置），下面是基于代码证据的设计建议，不改任何代码。

## 1. 范围与置信度

- **决策**：如何让 MarkText 的 main↔preload↔renderer IPC 契约能长期演进，重点是 contextBridge、错误传播、类型约束、测试隔离。
- **仓库分类**：Electron 桌面应用（Electron 42 + Vue 3 + Pinia，三进程模型），契约已从「无类型」向「单一类型文件」迁移了一半。置信度高——所有结论都来自源码直接观察。

## 2. 观察到的事实

**契约现状**
- 契约集中在 `packages/desktop/src/shared/types/ipc.ts:40-289`，按四个方向分类：`IpcInvokeChannels`（返回 Promise）、`IpcSendChannels`（单向）、`IpcSyncChannels`（同步）、`IpcMainEventChannels`（main→renderer 推送）。这个文件**不 import `electron`**（只 import 类型），因此它是纯类型层，天然可单测。【事实】
- preload 在 `packages/desktop/src/preload/index.ts:26-68` 用泛型包装了 `invoke/send/sendSync/on/once`，全部推导自上面的接口，这是目前唯一真正被编译检查的边界。
- 渲染侧全局类型在 `packages/desktop/src/types/global.d.ts:24-176` **手写重复**了同一套 API 面（`ElectronIpcRenderer`、`FileUtilsAPI`、`RipgrepAPI` 等十个对象）。契约、preload、global.d.ts 是**三份手写声明**，没有任何机制保证它们一致。【事实】

**main 侧 handler 注册是散落且无类型的**
- 集中注册只有 `packages/desktop/src/main/ipc/index.ts:12-23` 的 10 个模块（bootInfo/fs/paths/ripgrep/uploader/fonts/shell/window/cmd/i18n）。但大量契约里的频道实际注册在别处：`app/index.ts:663-847`、`app/windowManager.ts:369-411`、`dataCenter/index.ts:163-194`、`menu/index.ts:473-529`、`preferences/index.ts:177-186`、`editorBufferStore/index.ts:215`、`spellchecker/index.ts:59-84`、`keyboard/index.ts:87-90`。【事实】
- Electron 的 `ipcMain.handle(channel, handler)` 与 `webContents.send(channel, ...args)` 的 handler 参数是 `...args: any[]`、返回 `any`，**完全不参与契约类型检查**。契约目前只约束 preload/renderer 调用侧，不约束 main 侧。【事实】

**已经发生的静默漂移（契约 vs 运行时不一致）**
- `mt::menu::click`：契约是 `[menuId: string]`（`ipc.ts:246`），main 实际发 `{ windowId, id }`（`window.ts:38`），渲染侧只能 `as unknown as { id?: string }` 硬转（`popupMenu.ts:76-79`）。E2E 里还有发 `{ id }` 的变体（`test/e2e/new-file-collapsed-folder-3439.spec.ts:54`）。
- `mt::menu::closed`：契约是 `[]`（`ipc.ts:247`），main 实际发 `{ windowId }`（`window.ts:107`）。
- `mt::rg::start`：契约返回值 `{ searchId: string }`（`ipc.ts:72`），handler 实际返回 `true`（`ripgrep.ts:433-439`）。
- `mt::shell::open-external`：invoke 契约 `ret: void`（`ipc.ts:73`），handler 实际返回 `true|false`（`shell.ts:6-14`）；**且同一个频道名同时用 `handle` 和 `on` 注册了两遍**（`shell.ts:6` 与 `shell.ts:15`），契约里也同时出现在 invoke 和 send 两类。
- `mt::clipboard::guess-file-path`：契约 `ret: string | null`（`ipc.ts:43`），handler 失败时返回 `''` 而非 `null`（`shell.ts:49-67`）。
- `SerializedStat` 有两份定义：共享的 `files.ts:9-15`（`isSymbolicLink?`、无 `ctimeMs`）和 `fs.ts:6-13` 本地重定义的（`isSymbolicLink` 必填、含 `ctimeMs`），handler 返回的是本地形状而契约承诺共享形状（`ipc.ts:59` vs `fs.ts:53`）。
- `mt::boot-info` 在契约里属于 `IpcSyncChannels`（`ipc.ts:209`），但 preload **绕过了类型化 wrapper**，直接 `ipcRenderer.sendSync('mt::boot-info') as BootInfo | undefined`（`preload/index.ts:36`）；`mt::boot-info-async` 已注册（`bootInfo.ts:80`）但没有调用方。【事实】

**错误传播现状——三种风格并存且无统一语义**
1. 透传 reject：fs 类 handler 直接 `return fs.readFile(...)` 等，异常会 reject，但被 Electron 包装成泛化的 `Error invoking remote method 'CHANNEL': Error: 原始信息`，**原始 message 之外的属性与 stack 丢失**（这是 Electron `invoke` 的既定行为）。【事实】
2. 吞掉并给默认值：`shell.ts`（`openExternal→false`、`readText→''`、`guess-file-path→''`）、`fonts.ts→[]`、`cmd.ts→false`、`paths.ts is-image` 也是布尔默认。
3. 把错误当返回值：`shell.ts:25-31` 的 `open-path` 失败时 `return String(err.message)`。
- 渲染侧消费端是逐处手写 `.catch`：`editor.ts:650`、`project.ts:224,256,301`、`bufferedState.ts:53`、`quickOpen.ts:187`，错误类型全是 `unknown`，各自 `console.error` 或 `notice.notify`，没有共享错误形状。
- 推送流的错误是另一种形状：ripgrep 用 `mt::rg::error` 发 `{ searchId, error: string }`（`ripgrep.ts:195-198`），而契约把它标成 `[payload: unknown]`（`ipc.ts:259`）。渲染侧上报主进程错误则用 `mt::handle-renderer-error: [error: unknown]`（`ipc.ts:124`）。

**测试隔离现状**
- 单元测试环境是 jsdom（`vitest.config.ts:9-12`），只收集 `test/unit/specs/**/*.spec.ts`。测试**手工 stub `window.electron`/`window.path`**（如 `listen-for-main.spec.ts:8-12, 23-39`），从不加载真实 preload——因为 preload import 了 `electron`，在 jsdom 下无法直接引进来。**preload 桥和 ipc.ts 契约目前零单元覆盖**。【事实】
- 唯一的运行时契约哨兵是 E2E `context-isolation.spec.ts:24-38`：只断言沙箱三开关（contextIsolation/sandbox/nodeIntegration）和 `typeof window.electron.ipcRenderer.invoke === 'function'`，不校验任何频道类型。

**contextBridge 相关约束（设计必须尊重）**
- 沙箱 preload 只能 `require('electron')` 和少量内建，所以 `pathe` 被内联进 preload（`electron.vite.config.ts:49-52`）。
- `contextBridge` 会冻结暴露的对象，含自引用（`pathe.posix.posix === pathe.posix`）的结构化克隆会炸，仓库已因此刻意不暴露 `path.posix/win32`（`preload/index.ts:264-267`）——这是桥接层真实的序列化约束。
- 目前暴露的是**整个 `ipcRenderer` 对象**（`window.electron.ipcRenderer`），不是逐频道的具名方法；`removeAllListeners(channel: keyof IpcMainEventChannels | string)` 还接受任意字符串。这保留了迁移便利，但意味着渲染侧（一旦被攻破）可触达契约内全部频道。【事实】
- 三个纯字符串判定（`isChildOfDirectory/hasMarkdownExtension/isSamePathSync`）刻意留在 preload 内以保持同步返回，其中 `isSamePathSync` 在大小写不敏感文件系统时退化为一次同步 IPC `mt::paths::is-same-sync`（`preload/index.ts:111-156`）。这印证了「有些 API 必须同步」是真实需求。【事实】

## 3. 当前摩擦（根因，不是症状）

契约骨架是对的（单文件、四方向、渲染侧泛型），真正的根因是三点：

1. **契约只约束渲染侧，不约束 main 侧。** `ipcMain.handle`/`webContents.send` 是 `any`，所以上面那批漂移不会被编译拦住，只能靠人眼和运行时发现。这是最主要的变化放大点：加一个频道要在 ipc.ts、preload、global.d.ts、某处 main 模块**四处**手工同步，其中两处无类型保障。
2. **三份手写声明（ipc.ts / preload / global.d.ts）没有可执行的连接。** 漂移不会报错，只会悄悄积累。
3. **错误语义未显式化。** 同一契约里「应该 reject 的失败」和「预期失败返回默认值」混在一起，返回类型撒谎（`void` 实际是 `boolean`），跨进程 `Error` 又丢失原始信息，导致渲染侧只能逐个 `.catch(unknown)` 猜测。

## 4. 质量属性优先级

按对本次决策的实际支配力排序：

1. **类型安全 / 防漂移**（最高）—— 上面已经证明漂移正在发生且不可见。
2. **可测试性** —— preload 与契约目前无法隔离测试，任何重构都缺安全网。
3. **可演进性** —— 频道的新增/改名/改签名应是单点、加性、可回滚的。
4. **安全** —— 沙箱边界是承重墙；桥接面要能随迁移完成后收窄，而不是永远暴露整个 `ipcRenderer`。
5. **性能** —— 次要；同步握手（`sendSync`、同步纯函数）是真实需求，设计不能为了「纯异步」而破坏它。

**权衡**：给 main 侧加一个类型化注册助手是微小抽象，但能消灭整类漂移；而把 10 个全局对象合并成一个 `window.api` 或逐频道绑定，属于大机械改动且不新增能力，现阶段收益为负。

## 5. 选项

**选项 A：保持现状，靠纪律 + 手工审阅维持契约。**
- 边界：延续「契约只约束渲染侧」。
- 代价：漂移已知存在且继续增长，无测试兜底。
- 只有在「IPC 频道几乎冻结」的前提下才可辩护，与本仓库仍在迁移的事实不符。不推荐。

**选项 B：把契约升级为 main 侧也参与编译的单一事实源（推荐方向）。**
- 边界：`ipc.ts` 继续是唯一频道/参数/返回/事件的真相；新增两个纯函数助手（例如 `register(channel, handler)` 和 `emitTo(win, channel, ...args)`），其签名从 `IpcInvokeChannels[K]['args']/['ret']`、`IpcMainEventChannels[K]` 推导。所有 `ipcMain.handle/on`、`webContents.send` 调用点改为经过助手。这样 `rg::start` 返回 `true` 这类漂移会直接变成编译错误。
- 变化能力：加频道从「四处手工改」降到「改 ipc.ts + 一处注册」，签名错配当场暴露。
- 迁移/回滚：纯加性、可增量替换（先覆盖 `ipc/` 目录的 10 个模块，再逐步收编散落在 app/menu/dataCenter 的注册）；助手只是类型层包装，行为不变，回滚即删除助手。
- 让它失效的证据：若 Electron 未来提供更强的 `handle` 类型（不太可能，`any` 是它的公开 API），或团队明确接受「main 侧不检查」。

**选项 C：进一步收窄 contextBridge 面（逐频道具名绑定，隐藏原始 `ipcRenderer`）。**
- 边界：preload 只暴露每个频道一个具名函数/订阅器，渲染侧拿不到通用 `invoke/send/on`。
- 收益：安全面最小化；损失：迁移期调用点全部要改，且失去了「渲染侧自由组合契约频道」的便利。
- 结论：**作为 B 之后的第二阶段**，等 `unknown` 占位收敛、频道稳定后再做，不是现在。

## 6. 建议

推荐 **选项 B**，分三步，全部可逆、行为保持：

**第 1 步：让 main 侧加入类型闭环（最小、收益最大的垂直切片）**
- 在 `ipc.ts` 旁边加两个纯类型助手：类型化的 `handle`（推导 handler 的 `(event, ...args) => ret`）和类型化的 `sendTo`/`emit`（推导推送参数）。先改造 `ipc/` 目录 10 个模块。
- 顺手修正已确认的漂移，让类型说真话：`mt::menu::click` 改成 `{ windowId, id }`（渲染侧 `popupMenu.ts` 那处硬转随之删掉）、`mt::menu::closed` 改成 `{ windowId }`、`mt::rg::start` 的 `ret` 改成 `true` 或显式 `{ accepted: boolean }`、`mt::shell::open-external` 的 `ret` 改成 `boolean`（并移除同一频道的 `handle`+`on` 双注册之一）、`guess-file-path` 的 `ret` 改成 `string`。这些都是**契约向运行时靠拢**的类型修正，不改行为。

**第 2 步：消灭三份手写声明，降到两份（或一份）**
- 让 `global.d.ts` 的 `Window` 接口引用 preload 模块导出的对象类型（`typeof` 导出），而不是手抄十个接口。这样契约改一处，preload 和渲染侧全局类型自动跟随。
- 把 `SerializedStat` 收敛为一份（删掉 `fs.ts` 本地副本，`import type { SerializedStat } from '@shared/types/files'` 并让 `serializeStat` 返回它）。这一步立刻消除「共享类型」名存实亡的问题。

**第 3 步：显式化错误模型并写进契约**
- 给 invoke 频道定两条规则并写进 `ipc.ts` 头注释：
  - **可预期失败** → 返回类型本身就是结果（如 `boolean`/`''`/`[]`），handler 内部吞掉并记日志，正如 `shell.ts`/`fonts.ts`/`cmd.ts` 现在做的。这些频道的 `ret` 必须写真实类型（不能再是 `void` 谎报）。
  - **意外失败** → 让 reject 传播，但在 preload 的 `invoke` wrapper 里统一把 Electron 的 `Error invoking remote method ...` 解包/归一化成一个小而序列化的形状（`{ code?, message, channel }`），这样渲染侧的 `.catch` 拿到的是稳定结构而非 `unknown`，且原始 message 不再被前缀吞掉。
- 推送流的错误沿用 ripgrep 已有的 `{ searchId, error }` 模式，把 `mt::rg::*` 的 `[payload: unknown]` 收紧成具体类型；`mt::handle-renderer-error` 同理。

**不要现在做的（避免过度设计）**：
- 不要上代码生成 / RPC 框架 / 逐频道类；内部主↔渲染不需要。
- 不要一次性收编散落在 `app/menu/dataCenter` 的所有注册——先证明第 1 步在 `ipc/` 目录内有效，再逐步蔓延。
- 不要为内部频道引入带版本的线协议或协商握手——当前没有外部/插件消费者。
- 不要在频道还有大量 `unknown` 时做选项 C（收窄桥接面）。

## 7. 迁移与验证

**迁移切片**：先 `ipc/` 目录 10 个模块（一条 PR 的规模），用类型助手替换裸 `ipcMain.handle/on`；同 PR 修掉上面列的漂移。散落注册（app/menu/dataCenter/spellchecker/keyboard）作为后续独立 PR 逐个收编。

**可观测的完成标准**：
- `pnpm run typecheck` 在「main 侧 handler 返回类型与契约不符」时**必须失败**——可以用一个故意写错的临时频道验证这条确实成立，再删掉。
- 一个「契约完整性」单测：用一个 fake `ipcMain`（普通对象，记录注册）跑所有 `register*`，断言①契约里每个频道恰好注册一次、②注册的频道名都在契约里。这个测试不需要 Electron，纯 Node/jsdom 都能跑，能立刻抓住「注册了但没进契约 / 进了契约但没注册」两类漏网。

**测试隔离落点**：
- `ipc.ts` 已是 Electron-free 的纯类型层 → 加纯类型断言测试（`assertType`/`expectTypeOf` 抽查关键频道），跑在 vitest 里不需要 jsdom。
- 把 preload 桥重构成「接收注入的 `ipcRenderer/contextBridge`」的薄函数（依赖注入），用 fake 在 vitest 里测 `invoke/on/once` 的转发、退订、错误归一化。这是目前完全空白的一块，也是重构安全网。
- 保留 `context-isolation.spec.ts` 作为运行时边界哨兵，并在其中增加「契约抽查」：随机/固定几个频道，`page.evaluate` 里 `invoke` 一个只读频道（如 `mt::boot-info-async`）断言返回形状，作为类型断言之外的真实运行时校验。

**回滚**：类型助手是纯编译期包装，删除即回滚；错误归一化若担心影响行为，可先以「透传 + 日志」模式上线，再渐进收紧。

## 8. 待决问题（答案会改变建议）

1. **团队是否接受 main 侧也受类型约束**？若明确接受「main 不检查、靠审阅」，选项 B 的收益会打折——但从现有漂移看，我判断应接受。
2. **「可预期失败」频道的最终语义**：是统一 `Result<T>` 信封，还是「失败返回哨兵值」？两种都能表达现状，但会决定渲染侧 `.catch` 的最终形态；建议先按哨兵值（与现有 `boolean/''/[]` 一致）定案，避免引入新抽象。
3. **是否要在契约里区分「公开频道 vs 内部频道」（如 `watcher-*`、`window-*`、`app-*` 与 `mt::`）**？这决定未来能否安全收窄桥接面，值得单独写一条 ADR。
4. **同步 IPC 的去留**：`mt::boot-info` 的 `sendSync` 和 `isSamePathSync` 的同步回退是真实需求，但也阻塞 preload；是否长期保留需要一次明确的性能/维护权衡决定。

我建议把「IPC 契约是单一事实源 + main 侧类型化注册 + 错误模型」写成一条 ADR 固化下来（频道命名、方向分类、错误规则、注册助手约定），否则这些规则会随人员流动再次变回「手写四处同步」。

[EVAL:evolve-software-architecture-loaded]
