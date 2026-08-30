# MarkText `packages/desktop` 边界评估

## 1. 范围与置信度

评估对象是 `packages/desktop` 内 main / preload / renderer / shared（含 `common`）四条边界的现状与未来扩展性，并结合根 monorepo、配置、测试与可观察到的历史信号。仓库分类：**Electron 桌面应用**（三进程 + 工作区编辑器引擎），置信度**高**——`electron.vite.config.ts`、`main/config.ts` 的 `webPreferences`、preload 的 `contextBridge` 均一致指向该类型。

**置信度限制（未知）**：本会话 Bash 被禁用，无法运行 `git log`/`git blame`；历史结论仅来自会话提供的最近提交列表和源码注释中的迁移标记（如 `ipc.ts:11` 的 “commits 5–8”、`typedEmitter.ts:9` 的 “Commit 5d”、`#4244` sandbox 引用）。关于“谁在哪个提交改了什么”的具体热区证据未直接验证。

## 2. 观察到的现状（证据）

| 结论 | 证据 | 类型 | 置信度 | 对决策的影响 |
|---|---|---|---|---|
| IPC 契约是**单向类型**：renderer 侧有泛型约束，main 侧是裸字符串 | `shared/types/ipc.ts` 定义四类 channel；但 `main/ipc/*` 共 107 处 `ipcMain.handle/on` 用字符串字面量注册，无 `satisfies`/类型助手连接契约 | 事实 | 高 | drift 只能在 main 侧发生，正是已发生的地方 |
| 契约已与实现**漂移** | ① `files.ts:9-15` 的 `SerializedStat` 无 `ctimeMs`、`isSymbolicLink?`，而 `main/ipc/fs.ts:6-13` 本地另定义一份（含必填 `ctimeMs`、`isSymbolicLink`）；② `ipc.ts:247` 声明 `'mt::menu::click': [menuId: string]`，但 `main/ipc/window.ts:38` 实发 `{ windowId, id }` 对象；③ `ipc.ts:248` 声明 `'mt::menu::closed': []`，但 `window.ts:107` 实发 `{ windowId }` | 事实 | 高 | 契约文件不是运行时真相；继续沿用它会产生“类型说一套、运行做一套” |
| 存在契约**之外**的动态通道 | `main/menu/actions/edit.ts:17,34,38` 使用 `mt::response-of-image-path-${id}`，不在 `IpcMainEventChannels` 中 | 事实 | 高 | 契约覆盖不完整，动态通道完全无类型 |
| 无任何运行时校验 | 全库 grep 无 zod/validate/assert；`ipc.ts` 中大量 `args: unknown` / `ret: unknown`，注释自述“migration 期间故意宽松” | 事实 | 高 | renderer→main 的可信边界目前仅靠编译期单侧类型 |
| preload 暴露**双桥**：精选领域 API + 裸 `ipcRenderer` | `preload/index.ts:229-246` 同时暴露 `shell/clipboard/windowControl/fileUtils/…` 和 `electron.ipcRenderer`（send/invoke/on/once/sendSync）；renderer 26 个文件直接调 `window.electron.ipcRenderer.*` | 事实 | 高 | 两个入口做同一件事，未来收紧边界要动 26 个文件 |
| main→renderer 监听器**分散**，无单一 seam | `editor.ts` 约 45 处 `ipcRenderer.on`（文件约 1774+ 行），另有 preferences/project/layout/commandCenter/notification/autoUpdates/titleBar/sideBar/i18n 等各注册自己的监听；`listenForMain.ts` 只代理 4 个 channel | 事实 | 高 | 事件接入点随 store 分散，新增/修改事件要跨多处 |
| 命令系统**三处重复** | 命令 ID 在 `common/commands/constants.ts`、`renderer/src/commands/index.ts`（硬编码字符串字面量）、`main/menu/actions/*` 各存一份；renderer 有 `paragraph.reset-paragraph`、`file.zoom`、`window.change-theme`、`view.text-direction`、`docs.*` 等不在 constants 中，constants 里 `FILE_TOGGLE_AUTO_SAVE` 被注释而 renderer 用 `file.toggle-auto-save` | 事实 | 高 | 命令词汇三处易漂移 |
| renderer 事件总线**未使用** shared 的 `BusEvents` | `bus/index.ts:3-11` 明确用 `mitt` 的 `Record<string, unknown>`，注释说明为何不采用 `@shared/types/bus`；`shared/types/typedEmitter.ts` 仅 main 类使用 | 事实 | 高 | `shared` 与 renderer 运行时之间是断裂的 |
| `shared/` 是**纯类型**，运行时共享在 `common/` | `shared/` 下只有 `types/`；`common/` 被 main（约 30 处）和 renderer（`envPaths`/`encoding`/`keybinding`）同时 import | 事实 | 高 | “shared 类型”与“共享运行时代码”分居两处，命名易误导 |
| 引擎边界是 `any` | `@muyajs/core` 靠手写 `types/muya-core.d.ts` 遮蔽，`Muya` 类 `[key: string]: any`；该文件自述“待包发布 built .d.ts 后删除” | 事实 | 高 | 最大、变化最频繁的子系统以 `any` 穿越 renderer 边界 |
| 遗留 muyajs 已无调用点，但残留仍多 | 全库 src 与 test 均无 `muya/`、`@marktext/muyajs` import；但 `types/muya.d.ts`、`muya/*` 别名（3 处配置）、`@marktext/muyajs` workspace 依赖仍在 | 事实 | 高 | 迁移已完成，剩下的是可删除的死重 |
| `main_renderer/*` 别名只服务测试 | `tsconfig.base.json:32`、`vitest.config.ts:20` 有别名，`electron.vite.config.ts` 无；src 内零匹配；单测用它直接 import main 代码 | 事实 | 高 | 单测 seam 穿越进程边界、绕过 IPC |
| CLAUDE.md 自相矛盾 | Architecture 节写“editor/preferences 用 contextIsolation:false + nodeIntegration:true”，但 `main/config.ts:11-21,34-42` 实为 `contextIsolation:true, sandbox:true, nodeIntegration:false`（与 Code Style 节、preload 注释一致） | 事实 | 高 | 文档误导后来者，需修正 |
| `webSecurity: false` | `main/config.ts:19,40` 两个窗口均禁用 Chromium 同源策略 | 事实 | 高 | 安全相关，见 §4 |
| 两次引导通道 | 初始状态走 URL 参数（`bootstrap.ts:26-55`），完整配置走 `mt::bootstrap-editor`（`windows/editor.ts:174,491` → `editor.ts:890`），另有 `window.marktext` 全局（`bootstrap.ts:121` 写入、`main.ts:26` 重置） | 事实 | 中 | 引导协议不止一条，理解成本高 |

## 3. 当前摩擦

按“改动会扩散到几个地方”衡量：

1. **加一个 IPC channel 至少要改 4 处，且只有 2 处被编译器约束**：`shared/types/ipc.ts`（契约）、`main/ipc/*` 或散落的 handler（裸字符串，无约束）、`preload/index.ts`（若走领域 API 则还要加方法）、`types/global.d.ts`（renderer 表面）。main 侧是唯一不被约束的一侧，而它恰好是 drift 的源头。这是当前最大的结构性摩擦。

2. **契约文件已不是运行时真相**。`mt::menu::click`/`mt::menu::closed`/`SerializedStat` 三处漂移说明：只要“契约”和“handler”之间没有编译器或测试强制一致，`ipc.ts` 会逐渐退化为一份不可信的声明。`ipc.ts:11` 注释自己写的“commits 5–8 逐步收紧”是正确方向，但目前停在单侧。

3. **命令身份三处重复 + 一个字符串动词子协议**。菜单动作经 `mt::editor-edit-action`（payload 是 `'undo'`/`'redo'`/`'copyAsRich'` 这类字符串，`edit.ts:44-104`）到达 `listenForMain.ts:20`，再 `bus.emit(type, type)` 原样转发。这条链上的每一环都是未类型化的字符串，且命令 ID 在三个文件各自维护。

4. **主进程状态所有权清晰，但 renderer 的 `editor.ts` 是巨对象**（~1774 行，状态 + 45 个 IPC 监听 + 菜单状态 + 导出/打印/搜索协作全在一个 Pinia store）。它不是边界问题本身，但放大了前三点：任何主进程事件的接线都要进这个巨文件。

5. **测试 seam 穿越进程边界**。单测通过 `main_renderer/*` 把 main 模块当 renderer 模块测（`application-menu-state.spec.ts:6-18` 手写 stub `window.electron`/`window.path`，再用 `spyOn(ipcRenderer,'send')` 断言 `mt::editor-selection-changed` 的 payload）。这能测逻辑，但测不到“契约是否一致、序列化是否成立”，且让 `main_renderer` 别名长期留在 tsconfig 里。

## 4. 质量属性优先级（权衡）

对这个处于迁移中段、以本地进程边界为核心的桌面应用，排序如下：

1. **可维护性 / 变更局部性**——目标：新增一个能力尽量只改一个模块。当前证据：四处扩散 + 三处命令重复 + 巨 store。
2. **进程边界稳定性（IPC 契约完整性）**——目标：契约文件与运行行为一致。当前证据：已漂移。这是桌面项目独有的最高杠杆 seam（对应 Tauri 适配器的 “process-boundary stability”）。
3. **可测试性**——目标：通过接口测行为，而不是手写 stub 穿越边界。当前证据：单测直达 main 实现、无契约测试。
4. **安全（作为约束而非主驱动）**——sandbox 化是近期正确的一步，但 `webSecurity:false` + `unknown` 载荷 + 无运行时校验意味着：renderer（sandbox 后实质是不可信边界）可无校验地驱动 `fs.write-file`、`shell.open-path`、`cmd::exists`、`uploader::upload`、`fs-trash-item` 等特权操作。若未来加载远程内容或启用 webSecurity，这会变成真实缺口。
5. **引擎可移植性**——`@muyajs/core` 的 `any` 边界是最大的**未知**，但它是已文档化的迁移状态，优先级低于 1–3。

取舍：把 1+2 做扎实会小幅增加样板（每个 handler 多一层类型助手），但换来的是编译器在 drift 发生处拦截；安全校验若全面铺开会显著增加成本，应只对少数特权通道做窄校验。

## 5. 方案对比

**方案 A：维持现状，只按 `ipc.ts` 注释继续“逐 commit 收紧 renderer 侧类型”。**
- 边界：不变；契约继续单侧。
- 收益：零迁移、可回滚。
- 成本：不解决 drift 源头（main 侧仍无约束）；每次收紧仍靠人工对齐。
- 何时证伪：当再次发现一处 renderer 侧与 main 侧的载荷漂移时，说明单侧收紧不够。

**方案 B（推荐）：把 IPC 契约变成双面——引入 main 侧类型化注册助手，并加一个“通道清单”测试。**
- 边界：`main/ipc/` 提供 `registerInvoke<K extends keyof IpcInvokeChannels>(channel: K, handler: ...)` / `registerOn` / `registerSync`，handler 参数与返回类型由 `K` 推断，注册即校验。契约文件成为唯一真相源。
- 收益：drift 在产生处被编译器拦截；顺带把现有 3 处漂移修回契约；可增量落地（先转 `main/ipc/*` 这 10 个已集中、干净的 sandbox handler，再转散落的 dataCenter/preferences/spellchecker/menu-actions/editorBufferStore）。
- 假设：main 侧 handler 愿意接受一个统一包裹（不改变运行时语义，只是注册调用变一个函数）。
- 迁移/回滚：纯编译期改动，逐文件转换，随时可停；无运行时行为变化。
- 测试后果：可加“清单测试”——遍历契约接口的 channel 名与 main 注册表做差集，CI 里把缺失/多出的通道变成失败（`ipcMain` 的私有注册表可读取，或用自建的注册表记录）。
- 何时证伪：若团队判定“main 侧大量 handler 形参异构、难以统一签名”为真，则助手泛型会成为负担；但目前证据（handler 都是 `(e, x: string)` 这种简单形参）不支持该假设。

**方案 C：删除 renderer 的裸 `ipcRenderer` 面，只留精选领域 API。**
- 收益：renderer 表面可审计、封装更好；消除双桥。
- 成本：要迁移 26 个文件 + ~50 个监听器；而裸面本身已是类型化的，功能收益有限。**现在不做**，等方案 B 稳定后、确有“renderer 只能走领域 API”的需求再评估。

**方案 D：把 `shared/types` + `common` 抽成独立 workspace 包（如 `@marktext/shared`）。**
- 收益：多消费者（website/muya）共享契约。
- 成本：目前只有 desktop 消费，muya 自包含、website 依赖 npm 版；属于“为假设的变点建抽象”。**现在不做**，等到第二个真实消费者出现。

## 6. 建议

**采用方案 B，分可逆步骤推进；同时做三个低成本清理。** 理由：B 直接命中当前唯一的、已经发生 drift 的 seam（main 侧无约束），且是纯编译期、逐文件可回滚的改动，与仓库“commits 5–8 收紧 IPC”的既有方向一致。

具体路径（每步独立可合、可回滚）：

1. **先修契约，再转助手**：把已发现的漂移改回契约（`SerializedStat` 补 `ctimeMs` 并定 `isSymbolicLink` 必填、`mt::menu::click`/`mt::menu::closed` 改成对象载荷），并给动态通道 `mt::response-of-image-path-${id}` 在契约里建立一条显式条目或改走 `invoke` 返回值。
2. **在 `main/ipc/` 引入类型化注册助手**，先转换 `bootInfo/fs/paths/window/shell/cmd/i18n/ripgrep/uploader/fonts` 这 10 个集中模块；这是第一个“垂直切片”，能立刻证明助手形状可行。
3. **加通道清单测试**（`test/unit/specs/`）：契约声明的 channel 集合 vs 注册表集合求差，进 CI。这是观察性退出标准——一旦再有人裸字符串注册新通道或改错载荷，CI 红。
4. **窄化安全校验**：只对 `mt::fs::write-file`、`mt::fs-trash-item`、`mt::shell::open-path`、`mt::cmd::exists`、`mt::uploader::upload` 这几个特权/外发通道加最小运行时校验（类型 + 路径规范化），其余继续走类型。
5. **逐步收敛 main→renderer 监听面**：把各 store 的 `ipcRenderer.on` 按批次迁到 `listenForMain.ts`（或新建 `renderer/src/ipc/listeners.ts`），让 Pinia store 只保留状态所有权、不接触线上格式。中价值，可放在 B 之后。
6. **低成本清理（可立即做）**：删除 `types/muya.d.ts`、三处配置里的 `muya/*` 别名、`@marktext/muyajs` workspace 依赖（先确认 website/docs 无引用——当前 src/test 已零引用）；修正 `CLAUDE.md` Architecture 节与 `main/config.ts` 的矛盾；把 `shared/`（纯类型）与 `common/`（运行时代码）的定位在 CLAUDE.md 里写清楚。

**明确不做**：方案 C、D；不为 `@muyajs/core` 的 `any` 边界写永久适配层（等包发布 built `.d.ts` 后删除 shim，`muya-core.d.ts:16` 已写明该退出条件）。

## 7. 迁移与验证

- **行为保持**：方案 B 只改注册方式、不改运行时语义；每转一个模块跑一次 `pnpm -C packages/desktop exec vitest run`。
- **验证命令**：`pnpm run typecheck`、`pnpm run lint`（CI 已有）；新增清单测试后跑 `pnpm -C packages/desktop exec vitest run test/unit/specs/<ipc-inventory>.spec.ts`。
- **端到端观察点**：现有 `context-isolation.spec.ts`、`menu-sanity.spec.ts`、`launch.spec.ts` 应继续通过；建议给 `menu-sanity` 或 `context-isolation` 增加“右键菜单 payload 形状”断言，把 `mt::menu::click` 的漂移变成可测项。
- **完成标准**：① 契约文件与 `ipcMain` 注册表之间零差集；② `main/ipc/*` 全部走类型助手；③ 三处已知漂移在契约侧修正并有测试锁定；④ `muya.d.ts`/`muya` 别名/遗留依赖已删除且 CI 绿。
- **回滚**：任何一步都是单文件/单模块改动，git revert 即可；清单测试可先加 `skip` 再逐步启用。

## 8. 待定决策（仅这些会改变建议）

1. **renderer 是否仍被视为可信上下文？** 若未来加载远程内容或启用 `webSecurity`，第 4 步的运行时校验必须提前并扩大。**未知**——需产品侧确认 `webSecurity:false` 的用途边界。
2. **`@muyajs/core` 何时发布带 `.d.ts` 的构建？** 决定 `muya-core.d.ts` shim 的删除时机，以及是否值得现在投资一个真正的类型化引擎适配。**未知**。
3. **`@marktext/muyajs` 是否可整体移除？** 我验证了 desktop 的 src/test 零引用，但该包目录仍存在，移除是仓库级决定（需确认 CI/发布脚本/website 无隐含引用）。**未知**。

[EVAL:evolve-software-architecture-loaded]
