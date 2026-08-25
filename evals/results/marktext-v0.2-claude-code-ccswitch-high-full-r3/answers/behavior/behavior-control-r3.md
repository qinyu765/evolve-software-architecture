我已核对完毕。下面给出评估结论与理由，所有论断都可回指到具体文件与行号。

先交代核实方法与一处局限：本会话 Bash 被禁用，我无法运行 `git log`/`git blame`。我通过三方面交叉验证历史状态——环境提供的 HEAD 快照（`e52106fd`，develop 分支）、代码注释里记录的迁移阶段（`ipc.ts` 头部的 "commits 5–8"、`files.ts` 的 "subsequent commits"、`muya-core.d.ts` 的删除条件、`typedEmitter.ts` 的 "Commit 5d"）、以及 `.git/HEAD`、`.git/packed-refs` 与 reflog 的实际内容（确认这是一个 develop 分支在 `e52106fd` 的单点检出，reflog 只有 clone/checkout 两条，无法走完整提交图）。因此 Git 历史的"点状证据"是充分的，但"线性历史走查"这一项我只能以代码内记录替代，这是本文唯一无法直接验证的部分。

## TL;DR

当前架构里最值得**稳定**的边界已经就位且质量不低：沙箱化的 preload→IPC 桥、`shared/types/ipc.ts` 四类通道契约、`@muyajs/core` 引擎入口、以及主进程的 `BaseWindow/WindowManager/WindowType` 窗口抽象。最值得**延后**的是"平台化"抽象——通用窗口注册表、DI 容器、进程内事件总线框架、引擎插件 API、统一命令注册中心。推荐路线是"先收口、再增量"：完成两件已经进行到一半的机械性迁移（引擎去 legacy 化、IPC 具体类型化），顺手消除 IPC 命名空间被进程内事件总线复用的混淆，然后任何新能力都沿既有缝继续加，不引入新抽象。不建议"先建平台"的大重构。

下面先列核实到的硬事实，再给判断。

## 一、核实到的关键事实

**1. 引擎迁移已到"只差删除"的程度，但 legacy 痕迹仍在。** 桌面渲染进程对引擎的全部消费只有 6 个 `@muyajs/core` 导入点（`editor.vue:82-113`、`sourceCode.vue:15`、`util/markdownToHtml.ts:1`、`util/pdf.ts:8`、`util/exportHtml.ts:12-13`）；对 legacy `muya/` 别名或 `@marktext/muyajs` 的**运行时导入为 0**。但 legacy 仍以四种形态残留：`packages/muyajs` 包本身、`desktop/package.json:62` 的 `@marktext/muyajs` workspace 依赖、`electron.vite.config.ts:38` 与 `tsconfig.base.json:29` 的 `muya/*` 别名、以及 `src/types/muya.d.ts` 里约 20 个 `muya/lib/*` 的 `any` 声明。

**2. 引擎边界目前靠两个"盾牌"挡着，而不是靠引擎自己的类型。** `src/types/muya-core.d.ts:1-18` 说明：`@muyajs/core` 的 `exports` 在开发期指向 `./src/index.ts`，且不发布编译好的 d.ts，所以 vue-tsc 会把整个 muya 树拉进 desktop 的类型程序里，产生大量假错误；于是用 tsconfig 的 `paths` 把 `@muyajs/core` 重定向到这份手写的、`any` 偏多的声明（`tsconfig.base.json:30`）。文件头部明说"一旦引擎发布 `lib/types/*.d.ts` 就删除本文件"。这既是正确的止损，也意味着边界类型是**桌面侧单方面维护的、随时可能与引擎漂移**的约定。

**3. IPC 契约是单一事实源，但尚未具体化，且命名空间被两个机制复用。** `shared/types/ipc.ts` 定义了四类通道并注释"迁移期间参数与返回故意宽松（`unknown`/`unknown[]`），commits 5–8 逐通道收紧"。更值得注意的混淆是：`IpcSendChannels` 把两类东西混在同一张表里——真正的 renderer→main 通道，和**主进程内部**经 `ipcMain.emit` + `onInternalChannel`（`main/utils/internalIpc.ts:8-14`）派发的事件总线通道。证据：`watcher-watch-file`、`watcher-unwatch-*`、`window-add-file-path`、`window-close-by-id` 等无 `mt::` 前缀的通道（`ipc.ts:183-201`）只在主进程内部 `ipcMain.emit`，从不由 renderer 发送；而 `windowManager.ts:367-495` 里同一个逻辑通道既用裸 `ipcMain.on('mt::window-add-file-path')` 注册、又用 `onInternalChannel('window-add-file-path')` 注册。

**4. 窗口路由是"混合制"。** 约 30 个通道携带 `windowId: number`，但主进程有些 handler 用 `BrowserWindow.fromWebContents(e.sender)` 反查窗口（`windowManager.ts:369-399`），有些直接用传入的 `windowId` 查表（`windowManager.ts:437-455`）。`editor.ts:140-145` 还特意为持久化引入了一个独立的 `restoreBufferId`，理由是"`win.id` 可能与已关闭窗口的 id 冲突"。也就是说，`BrowserWindow.id` 不能稳定标识一个会话窗口——这是窗口能力扩展时必须先定死的一个事实。

**5. 沙箱与安全边界已经相当硬，但有一个显眼缺口。** `main/config.ts:11-27` 里 `contextIsolation: true`、`sandbox: true`、`nodeIntegration: false`，preload 只 `require('electron')` + `pathe`，且 `app/index.ts:132-143` 阻止了 webview、导航与 `window.open`。但 `webSecurity: false`（`config.ts:19,40`）被显式关掉了同源策略，这是一个需要"刻意决策并写明理由"的安全边界项，而不是能默默带过的默认值。

**6. 文档存在漂移。** `website/content/docs/dev/ARCHITECTURE.md:5-17` 与 `TYPESCRIPT.md` 仍描述**单仓库迁移前**的布局（根目录 `src/main`、`src/renderer`、`src/muya`、"上游 TS muya 将来会落地"），而实际结构已是 `packages/desktop/src/...` + `packages/muya` + `packages/muyajs`，且 TS muya 已经落地。`IPC.md` 与两份 `CLAUDE.md` 是新的。维护者若照 `TYPESCRIPT.md` 扩展引擎或 shell 能力，会被带进已经不存在的路径。

**7. 主进程的服务装配是手写 service locator，命令回调是显式 `any`。** `main/app/accessor.ts:12-42` 手工 `new` 出约 8 个服务；`main/commands/index.ts:7-14` 的 `CommandCallback = (...args: any[]) => any` 是文档化的逃生口。这两者当前**能用**，但都不是值得固化或扩展的抽象。

## 二、应该稳定（或收口）的边界

按价值从高到低：

1. **沙箱 preload 桥（最高优先）。** `preload/index.ts:286-296` 暴露的 `window.electron.* / fileUtils / path / ripgrep / uploader / fonts / commandExists / i18nUtils` 是唯一正确的 Node 入口。规则应是：新能力一律走"`ipc.ts` 加通道 → `main/ipc/*` 加 handler → preload 加 typed facade → `global.d.ts` 加类型"，禁止新增 `nodeIntegration` 或直接往 `window` 上挂裸 API。这条已经在 `IPC.md` 写成约定，值得继续当作不可违背的边界。

2. **`shared/types/ipc.ts` 的四类通道契约。** 它的**形状**（invoke/send/sync/main-event 四张表、`mt::` 前缀、typed preload 泛型）是对的、已经通过 typecheck 在 CI 里强制。要收口的是**内容**：把迁移遗留的 `unknown` 载荷具体化（ripgrep、uploader、menu、keybinding、`bootstrap-editor`、`update-buffer-state` 等仍宽泛）。

3. **主进程窗口抽象。** `BaseWindow` + `WindowType` 枚举 + `WindowManager`（`windows/base.ts:16-32`、`app/windowManager.ts`）是合理的扩展点。新增窗口类型 = 枚举加一项 + 子类 + `App._createXWindow` + 菜单接线，不需要新的抽象。要收口的是**窗口身份路由**：确定"窗口 id 到底是 `BrowserWindow.id` 还是独立会话 id"，并统一 handler 是"从 `event.sender` 反查"还是"显式传 id"二选一，而不是现在的混合制。

4. **文档状态形状。** `shared/types/files.ts` 的 `IFileState` + `MarkdownDocument` + `SaveOptions`，横跨 Pinia store、buffered-state 持久化与 IPC，已经是事实上的单一文档形状。文件工作流的任何扩展都应继续把它当作唯一形状，而不是再造一套。

5. **`@muyajs/core` 的公开入口。** 桌面只经 `src/index.ts`（Muya 类 + 17 个 UI 插件构造器 + `MarkdownToHtml` + 工具函数 + locale 对象）消费引擎。把"引擎 = 只有这一个入口"定死，是引擎演进最省心的边界。

## 三、应该延后（现在不要建）的抽象

1. **通用窗口注册表 / 动态窗口插件系统。** 当前只有 editor/settings 两种窗口。第三个真实窗口出现时再子类化即可；现在就建 `WindowDescriptor` 注册表或"窗口即插件"是过度设计。

2. **DI 容器（Inversify/tsyringe 之类）。** `Accessor` 手写 service locator 有缺陷，但只有约 8 个服务、生命周期简单。替换成框架的收益远小于成本与认知负担。

3. **统一的跨进程命令注册中心。** 主进程 `CommandManager`（`any` 回调）与渲染进程 `cmd::register-command` 总线是两套。统一它们是真工作量、中低收益；除非出现"一个命令要在主/渲染两侧都可路由"的真实需求，否则延后。

4. **独立的进程内事件总线框架。** 当前的 `ipcMain.emit` 复用是坏味道，但**修法应该是机械迁移**（把内部事件挪到一个带 `TypedEmitter` 的内部命名空间，`internalIpc.ts` 已具雏形），而不是引入 EventEmitter2/消息框架。先做去混淆，不做新框架。

5. **引擎插件 API / 协作传输。** muya 的状态层虽已按 OT 设计（`packages/muya/CLAUDE.md`），但引擎自己的编译类型还没发布，桌面侧还靠 `any` 盾牌。此时冻结一个"稳定插件/协作 API"等于冻结一个还在动的目标。等引擎发布 d.ts 后再谈。

6. **VFS / 远程文件提供者 / 多根工作区。** 现有"每窗口一个根目录 + opened-files 列表 + chokidar watcher"模型够用。文件工作流的痛点是**通道太多、命名混乱**（见下），不是缺抽象。

## 四、按四个能力域的判断

**窗口能力：稳定 `BaseWindow/WindowManager`，延后"窗口平台化"。** 关键前置工作是定死窗口身份（见上），因为 `BrowserWindow.id` 复用会直接咬到多窗口、崩溃恢复、会话恢复这些未来功能。这条不解决，加任何窗口能力都是在流沙上加盖。

**文件工作流：稳定 `IFileState` + "主进程管 IO、渲染进程管编辑状态"的分工，延后 VFS。** 但当前保存/另存/重命名/移动的通道是散装且近重复的：`mt::response-file-save`、`mt::response-file-save-as`、`mt::save-tabs`、`mt::save-and-close-tabs`、`mt::rename`、`mt::response-file-move-to`、`mt::set-pathname`、`mt::tab-saved`、`mt::tab-save-failure`……这些是"fire-and-forget + 独立 ack 事件"的老模式。在加新文件能力前值得先收口成"请求/响应对 + 单一 ack 形状"，但这是**重构既有表面**，不是新抽象。

**引擎演进：稳定 `@muyajs/core` 入口 + 桌面侧 `muya-core.d.ts` 盾牌，延后"稳定插件 API"。** 最高价值的动作是**完成去 legacy 化**（删 `@marktext/muyajs` 依赖、`muya/*` 别名、`muya.d.ts`、`packages/muyajs` 包）。这一步是纯删除、可 grep 验证、可 git 回滚，且能把"两个引擎并存"的认知负担降为"一个引擎"。

**Electron shell 能力：稳定 `main/ipc/*`（registerSandboxIpcHandlers）作为新原生能力的落点，延后"原生能力注册中心"。** shell/clipboard/fonts/window/cmd/i18n 已经按此模式就位，新的原生能力照抄即可。需要单独处理的是 `webSecurity: false` 这个安全边界——要么写下"为什么必须关、风险已被什么缓解"，要么逐步收紧，而不是继续当作隐形默认值。

## 五、方案对比（含维持现状）

**方案 A：维持现状，只做增量。** 在新能力落地的同时不做任何收口。质量属性：交付速度最快、短期成本最低；可修改性与可维护性随每次新增而递减（每加一个文件工作流，散装通道和 `unknown` 载荷就多一份）；安全面保持现状。风险：`windowId` 复用、IPC 命名混淆、文档漂移三类问题继续累积，直到某次多窗口或崩溃恢复功能被迫在紧要关头返工。回滚：无（没有引入新东西，也就没有可回滚物）。不改变的后果：今天不痛，但下一个需要"窗口身份"或"引擎类型"的能力会付出更高复利。

**方案 B：先收口、再增量（推荐）。** 把上文的 2、4、5 三项收口工作做完（去 legacy、IPC 具体类型化、去内部/跨进程命名混淆、窗口身份定死、文档同步），然后新能力沿既有缝加。质量属性：可维护性/可修改性显著提升，测试性不变甚至更好（具体类型让 typecheck 成为更强护栏）；交付速度在收口期短暂放缓，之后反而更快。成本：中等、前置、且大部分是机械性工作。风险：低——每步都是纯删除或纯收紧，typecheck + 既有单测/e2e 就是护栏。回滚：天然按 commit 逐个回退，且每步可独立交付。不改变的后果：如果继续"先增量"，一年后你会带着现在的坏味道做多窗口和引擎升级，成本更高。

**方案 C：先建平台（大重构）。** 一次性引入 DI 容器 + 统一命令注册中心 + 窗口/工作区抽象 + 引擎插件 API + 进程内事件总线框架。质量属性：理想状态下可修改性最高、最"正规"；但这是把一次不确定性的重构打包成一次更大的、无法逐步验证的重构。成本：高，且需要同时重写主进程装配、命令、窗口、引擎边界。风险：高——五个耦合面一起动，任何一步出错都要整体回退，回滚粒度粗。测试性短期会倒退（大量既有 spec 要跟着重写）。不改变的后果：无（这是改变最多、最不需要证明其必要性的一条）。在"只有两种窗口、约 8 个服务、一个编辑器"的规模下，方案 C 的抽象高度与实际规模不匹配。

结论：选 B；把 C 里那些"平台化"项目明确记入延后清单，等真实规模信号（第三种窗口、第二个 shell 能力家族、或引擎发布稳定类型）出现后再评估。

## 六、可验证的渐进迁移路线（每步独立交付、可独立回滚）

**第 0 步：完成引擎去 legacy 化（机械、低风险、先做）。** 删除 `desktop/package.json:62` 的 `@marktext/muyajs` 依赖、`electron.vite.config.ts` 与 `tsconfig.base.json` 里的 `muya/*` 别名、`src/types/muya.d.ts`、以及 `packages/muyajs` 包。验证：`pnpm -C packages/desktop typecheck` 通过；`grep -r "muya/lib" packages/desktop/src` 返回 0；`pnpm -C packages/desktop exec vitest run` 与至少 `test/e2e/launch.spec.ts` 通过。回滚：单个 revert commit。

**第 1 步：收紧 IPC 载荷（延续 ipc.ts 头部的 commits 5–8）。** 把 ripgrep、uploader、menu、keybinding、`bootstrap-editor`、`update-buffer-state` 等 `unknown` 换成具体类型，每收紧一个通道，typecheck 即暴露所有不匹配的调用点。验证：typecheck 全绿 + 对应单测。回滚：按通道逐个 revert。

**第 2 步：去命名混淆。** 把 `IpcSendChannels` 里实际只在主进程内部 `ipcMain.emit` 的 `watcher-*`、`window-*` 无前缀通道从 renderer 契约中移除，改由 `internalIpc.ts` 管理的内部类型表承载；让 `ipcMain.on/handle` 只承载真正的 renderer→main 流量。验证：单测断言"内部通道名与 renderer 通道名零交集" + watcher 相关 e2e。回滚：分通道迁移，逐段 revert。

**第 3 步：定死窗口身份。** 二选一：要么所有 handler 一律 `event.sender` 反查（不传 `windowId`），要么给窗口一个稳定会话 id 并全程显式传递；并让 `restoreBufferId` 与窗口 id 的关系写进注释。验证：多窗口 e2e（第二窗口打开/关闭/重开）不串台。回滚：单一 commit。

**第 4 步：收口文件工作流通道。** 合并散装的 save/save-as/rename/move 为类型化的请求/响应对 + 单一 ack 形状。验证：既有 save/rename/move 单测与 e2e 全绿。回滚：通道级 revert。

**第 5 步：同步文档。** 更新 `ARCHITECTURE.md`、`TYPESCRIPT.md`、`INTERFACE.md` 到 monorepo 布局与"TS muya 已落地"的事实；为 `webSecurity: false` 补一段理由或收紧计划。验证：文档中的路径全部 `grep` 存在。回滚：无风险，纯文档。

顺序设计原则：把纯删除、纯收紧、无行为变化的机械步骤（0–2、5）排前面，把有行为语义争议的（3、4）排后面；每步都有客观验证手段，且都以"一次 commit 可整体回退"为粒度。

如果你希望，我可以把第 1 步里"哪些通道还停留在 `unknown`、每个应落到什么具体类型"整理成一张对照清单，作为下一份只读交付。
