架构审查完成。以下结论全部基于对仓库文档、配置、实现与测试的直接核查（未修改任何文件）。

## 1. 范围与置信度

**决策对象**：在 MarkText 当前 pnpm monorepo + `packages/desktop` 结构下，为四类未来能力——新增窗口能力、文件工作流、编辑器引擎演进、Electron shell 能力——确定哪些边界应保持稳定、哪些抽象应延后，并给出渐进迁移路线。

**仓库分类**：Desktop/Electron（非 Tauri）。分类依据：Electron 42 外壳承载 WebView、三个进程（main/preload/renderer）、原生窗口/文件系统/菜单/托盘类集成、electron-builder 打包。Desktop/Tauri 适配器中与 Rust/`Cargo.toml`/Tauri 命令相关的内容不适用，但"进程边界稳定性、生命周期正确性、平台安全"这些桌面通用关切直接适用。置信度：**高**——多个信号一致，且本仓库自身的 `CLAUDE.md`、`IPC.md` 与代码互相印证。

## 2. 观察事实

| 主张 | 证据 | 类型 | 置信度 | 对决策的影响 |
| --- | --- | --- | --- | --- |
| 跨进程 IPC 契约是"单一事实源"，但迁移只做了一半：通道名已强类型，负载仍是 `unknown` | `src/shared/types/ipc.ts:12-13`（"permissive … during the migration … commits 5–8"）；`:83-85` | 事实 | 高 | 进程缝是四类能力的必经之路，但不完整 |
| IPC 存在三套并存机制：集中式 typed handlers、`App`/`WindowManager` 内联的旧 `ipcMain.on/handle`、以及 `ipcMain.emit` 驱动的"主进程内部总线" | `src/main/ipc/index.ts:12-23`；`src/main/app/index.ts:658-850`；`src/main/app/windowManager.ts:367-495`；`src/main/utils/internalIpc.ts:4-13` | 事实 | 高 | 新增能力的注册点不唯一，变更会扩散 |
| 内部总线是 `ipcMain.emit` + `onInternalChannel`，把 renderer 面向的 API 借作 main→main 事件机制；菜单动作与 App/WindowManager 靠字符串通道解耦 | `src/main/utils/internalIpc.ts:4-13`；`src/main/menu/actions/file.ts` 约 30 处 `ipcMain.emit` | 事实 | 高 | 这是文件工作流/窗口能力的核心缝，但无类型、不可发现、语义被包装注释掩盖 |
| 窗口身份有两种约定并存：sender 推导（`BrowserWindow.fromWebContents`）与显式 `windowId`；还存在成对重复通道 | `ipc.ts:83-85` vs `ipc.ts:95-97,196`；`mt::window-add-file-path`（`windowManager.ts:369`）与 `window-add-file-path`（`windowManager.ts:437`） | 事实 | 高 | 多窗口正确性是未来窗口能力的风险点 |
| 窗口会话恢复把 `restoreBufferId` 挂在 BrowserWindow 实例上，用类型断言读取 | `src/main/editorBufferStore/index.ts:187-197`；`windowManager.ts:383-387` | 事实 | 高 | 隐藏的窗口/缓冲身份通道，应显式化 |
| 主进程命令系统是字符串键 + `any` 回调的单例；渲染进程另有一套静态命令描述符 | `src/main/commands/index.ts:7-14`；`src/renderer/src/commands/index.ts:61-681` | 事实 | 高 | 命令双轨是文件工作流的主要承载点 |
| 窗口对象模型是 `BaseWindow`/`EditorWindow`/`SettingWindow` + 封闭枚举 `WindowType` | `src/main/windows/base.ts:16-20`；`windowManager.ts:85-115` | 事实 | 高 | 只有 2 种具体窗口；通用工作区抽象过早 |
| 引擎边界已切到 `@muyajs/core`（`packages/muya`），由手写环境声明 `muya-core.d.ts`（`[key: string]: any`）封边；遗留 `@marktext/muyajs` 与 `muya` 别名已无任何 import 调用点 | `src/types/muya-core.d.ts:1-18,47-52`；`electron.vite.config.ts:38,58,84`（别名仍在）；全包 grep 无 `from 'muya'`/`@marktext/muyajs` import（仅 `package.json:62` 依赖声明与注释） | 事实 | 高 | 引擎是稳定的适配点；遗留依赖可删但尚未删 |
| `@muyajs/core` 的 import 分散在 5 处：`editor.vue`、`sourceCode.vue`、`util/markdownToHtml.ts`、`util/pdf.ts`、`util/exportHtml.ts` | grep 结果 | 事实 | 高 | 引擎门面缺失，未来换引擎/删遗留会散弹式改动 |
| 会话/缓冲持久化是手写机制，单版本常量 `BUFFERED_STATE_VERSION = 1`，负载 `unknown` | `src/renderer/src/store/bufferedState.ts:7,21`；`editorBufferStore/index.ts:187-218` | 事实 | 高 | 窗口能力（多窗口恢复）会触及此机制，但目前单一版本够用 |
| 文档存在漂移：`ARCHITECTURE.md`/`TYPESCRIPT.md` 仍描述 monorepo 之前的 `src/`、`src/muya/`、`resources/` 布局；`CLAUDE.md` 的架构小节仍写 `contextIsolation:false + nodeIntegration:true` 并指向已改名的 `config.js` | `website/content/docs/dev/ARCHITECTURE.md:1-17`；`TYPESCRIPT.md:1-12`；`CLAUDE.md` 架构小节 vs 实际 `src/main/config.ts:11-20`（sandbox:true） | 事实 | 高 | 文档与代码不一致会误导后续边界决策 |
| `IPC.md` 与实际代码一致（sandboxed、typed contract） | `website/content/docs/dev/IPC.md` vs `config.ts` | 事实 | 高 | 至少有一份文档是准的 |
| 仓库没有 ADR 目录 | Glob `**/{ADR,adr,decisions}/**` 无结果 | 事实 | 中 | 负载决策没有记录载体；建议为关键缝补 ADR |
| 单测以纯函数/组件级为主，未见跨 IPC 桥的契约测试 | `packages/desktop/test/unit/specs/*.spec.ts`（buffer-store-durable、flush-before-save 等均针对具体 bug） | 事实 | 高 | 生命周期/IPC bug 是历史热点，但缺跨缝测试 |

## 3. 当前摩擦

摩擦不是"缺抽象"，而是**同一语义在多个机制里各有一份**，新增能力时需要在 4–6 个地方同步改动：

- **文件工作流**：一条"另存为/关闭窗口"链路会穿过 `menu/actions/file.ts`（`ipcMain.emit`）→ `App`/`WindowManager`（`onInternalChannel`）→ `EditorWindow`（`_openedFiles`/`openTab`）→ `webContents.send` → 渲染端 `editor.ts` store → `bus` → 组件。这是 5–6 跳，且前两跳是字符串通道。
- **窗口能力**：`WindowType` 封闭枚举本身没问题，但窗口身份有三种表达（sender 推导、显式 `windowId`、挂在 BrowserWindow 上的 `restoreBufferId`），并存在成对重复通道。
- **Electron shell 能力**：typed-IPC 迁移停在"通道名强类型、负载 `unknown`"，意味着新增 shell 能力时参数/返回值不会被编译器约束。
- **引擎演进**：`@muyajs/core` 封边（`muya-core.d.ts`）是正确方向，但 import 点分散、遗留 `@marktext/muyajs` 依赖与 `muya` 别名已成死配置，删除动作没人收口。

一句话：**当前架构不缺层，缺的是"把已存在的缝收拢并完成"**。风险不是未来加不进去，而是每次加都在把字符串通道和 `any` 面再扩大一点。

## 4. 质量属性优先级

按治理力排序（不是全部最大化）：

1. **进程边界稳定性**（目标：跨进程通道全部经 `ipc.ts` 单一契约，负载非 `unknown`）。证据：迁移进行中。改善项：方案 B。可能退化：无（性能不敏感）。验证：`pnpm typecheck` + 契约测试。
2. **局部性/可维护性**（目标：新文件/窗口能力每个进程改动 ≤2 个文件）。证据：当前 5–6 跳。改善项：方案 B（内部总线 + 命令统一）。退化风险：过度收拢可能把菜单动作变成大对象。验证：首个垂直切片的 diff 审查。
3. **可测试性**（目标：契约可在不打包 Electron 运行时下验证）。证据：单测全是纯函数，无跨桥契约测试；历史 bug 集中在生命周期（dropped keystroke、flush-before-save、buffer-store-durable）。改善项：方案 B 的 typed 内部总线天然可单测。退化风险：过度 mock。验证：新增一条端到端通道的契约测试。
4. **可移植性**（目标：mac/win/linux 分支继续留在 `config.ts` + window/menu/fs 模块内）。证据：`config.ts:4-6` 与条件块。保持现状即可；验证：各平台打包冒烟。
5. **成本/可逆性**（目标：每步可独立回滚）。约束：成熟应用、小团队、迁移进行中——不要为假设的未来造抽象。

## 5. 方案比较

**方案 A：维持现状，只继续 typed-IPC 迁移。**
边界不变：内部 `ipcMain.emit` 总线、双命令系统、`restoreBufferId` 挂实例、引擎 `any` 面都保留。
- 优点：零新概念，迁移已在轨，风险最低。
- 代价：新增能力的"扩散"和"字符串通道"继续累积，测试仍测不到跨缝 bug。
- 假设：未来能力节奏很慢，且愿意在每处重复实现。
- 使其失效的证据：出现第二个需要多窗口路由或跨进程命令的新能力时，成本曲线会变陡。

**方案 B（推荐）：收拢既有缝，不新增层。**
- 完成 typed-IPC，收编非 `mt::` 渲染通道与重复通道对。
- 用已有 `TypedEmitter`（`shared/types/typedEmitter.ts`）替换 `ipcMain.emit` 内部总线，保留"菜单动作与窗口管理解耦"的意图，换掉承载机制。
- 显式化窗口身份：跨进程窗口作用域操作带 `windowId`；`restoreBufferId` 变为 `BaseWindow` 上的显式字段而非 BrowserWindow 上的断言属性；删除重复通道。
- 统一命令为单一类型化注册表（main + renderer 共享 `@shared` 的 `CommandId`）。
- 引擎封边收拢为渲染端门面 + 收窄 `muya-core.d.ts`，删遗留依赖。
- 优点：四类能力各有唯一缝；每步可独立落地/回滚；typed 内部总线带来可测性。
- 代价：中等改动量（内部总线迁移 fan-out 大但机械）。
- 假设：`ipcMain.emit` 的"解耦菜单与窗口管理"意图值得保留，只是机制该换。
- 使其失效的证据：如果 `@muyajs/core` 很快发布自带稳定类型，引擎门面步骤可跳过直接删 shim。

**方案 C：一次性引入通用抽象层（窗口/工作区服务 + 引擎端口 + 版本化 IPC 协议）。**
- 优点：理论上最"面向未来"。
- 代价：只有 2 种窗口、1 种文件提供者、1 个引擎，抽象会先于真实变体出现；引入 speculativity 与回滚成本。
- 假设：未来同时出现多窗口工作区、远程文件、可插拔引擎。当前无证据支持。
- 使其失效的证据：出现第二个真实变体（如 split pane、远程同步、第二引擎）时再考虑，那时抽象有据可依。

## 6. 建议

选 **方案 B**。按四类能力，边界应"稳定"还是"延后"如下：

**应稳定的边界（现在收拢，低成本高杠杆）**

- **跨进程 IPC 契约**（Electron shell / 窗口 / 文件都过这里）：完成迁移，把所有 renderer↔main 通道收进 `ipc.ts`，收紧 `unknown`；删除非 `mt::` 的 renderer 通道与 `mt::window-add-file-path`/`window-add-file-path` 这类重复。
- **窗口身份约定**：显式 `windowId` 用于"针对特定窗口"（含所有 main 发起/跨窗口操作）；sender 推导仅用于"操作发起窗口自身"（`mt::win::*`）。把 `restoreBufferId` 提升为 `BaseWindow` 显式字段，停止用类型断言挂 BrowserWindow。
- **主进程内部事件缝**：`ipcMain.emit`/`onInternalChannel` 换成 `TypedEmitter` 内部总线（模块级单例或经 `Accessor` 注入），通道名与负载类型化。这直接服务"窗口能力"与"文件工作流"。
- **命令缝**：main 与 renderer 共享 `@shared` 的 `CommandId` 类型，替代 `CommandCallback = any` 与渲染端静态描述符双轨；菜单、快捷键、命令面板都通过同一 id 派发。
- **引擎封边**：保持 `@muyajs/core` 为唯一引擎依赖，但新增渲染端门面模块（如 `renderer/src/engine/` 或 `util/muya.ts`），把 5 处直接 import 收拢到一处；收窄 `muya-core.d.ts` 到实际使用面。这是"编辑器引擎演进"的稳定点。

**应延后的抽象（现在不建，等真实变体）**

- 通用"窗口/工作区服务"接口或分层：`WindowType` 封闭枚举 + `BaseWindow` 子类已够用（推断：只有 2 种具体窗口，`BASE` 是占位）。
- 虚拟文件系统 / 文件提供者抽象：目前只有本地磁盘，`common/filesystem` + `main/filesystem` 足够。
- 引擎插件协议：等 `@muyajs/core` 自带稳定类型与插件 API 后再设计，避免在 `any` 面上再搭一层。
- 版本化 buffered-state 迁移框架：单一 `BUFFERED_STATE_VERSION = 1` 现在够用；等第二个版本出现时再引入迁移钩子（这是唯一需要盯防的延后项——多窗口恢复一旦做就会触及它）。

**不改变的后果**：每新增一个窗口/文件/shell 能力，仍需在菜单动作、App/WindowManager 监听、IPC 契约、preload 门面、渲染 store 等 4–6 处手工同步；字符串内部通道与 `any` 面继续增长，生命周期类 bug 仍难被单测覆盖。功能不会立刻坏，但变更成本单调上升。

## 7. 迁移与验证

原则：**每步是可独立回滚的小 PR，行为保持不变；用 `pnpm lint && pnpm typecheck && pnpm test:unit`（相关处加 e2e）做门禁。**

1. **机械护栏**：加一个 grep/CI 检查——`ipcMain.on/handle` 只允许出现在 `src/main/ipc/*.ts`；`ipc.ts` 中 `unknown` 计数只降不升。这本身不改行为，先让漂移可度量。
2. **首个垂直切片**：挑一个未来能力（新增一种窗口类型，或多窗口会话恢复），**端到端穿过收拢后的缝**实现。用它证明"新能力每个进程改动 ≤2 文件"，并作为后续步骤的验收样本。
3. **内部总线替换（按族推进，fan-out 大但机械）**：先 `watcher-*`（最小），再 `window-*`，再 `app-*`；过渡期让旧 `onInternalChannel` 成为 typed 总线的薄委托；最后删 `internalIpc.ts`。
4. **窗口身份**：删重复通道对，`restoreBufferId` 显式化；契约里把 sender 推导通道与 windowId 通道标注清楚。
5. **命令统一**：`CommandId` 类型落地，`CommandCallback` 按命令族收紧。
6. **引擎收口**：建门面 → 重指 5 处 import → 删 `muya` 别名与 `@marktext/muyajs` 依赖。

**退出标准（全部可用 grep/typecheck 验证）**

- `ipc.ts` 中通道负载除确需异构者外均非 `unknown`；所有 renderer↔main 通道都在契约内。
- `ipcMain.emit` 调用点归零；`ipcMain.on/handle` 仅存在于 `src/main/ipc/`。
- 无重复窗口通道对；`restoreBufferId` 无类型断言读取。
- `from '@marktext/muyajs'` / `from 'muya'` import 归零，`muya` 别名从 `electron.vite.config.ts` 移除。
- 新增一条端到端通道的契约测试（跨 preload 门面 + main handler）。

**回滚路径**：内部总线替换是"并列机制 + 旧通道薄委托"，任一族可单独 revert；每步语义等价，无需数据迁移；buffered-state 未引入新版本，回滚不丢会话。

**风险与对策**：`menu/actions/file.ts` 约 30 处 `ipcMain.emit` 是最大 fan-out——按族迁移、每族一个 PR 即可控；收紧 `unknown` 负载可能暴露未建模的运行时形状——逐通道收紧 + e2e 兜底；文档漂移会持续误导——把第 6 节结论补进 `ARCHITECTURE.md`/`TYPESCRIPT.md`（或写成 ADR），否则"稳定缝"的共识没有落点。

## 8. 待定决策

以下问题会改变建议，建议用 ADR 记录（仓库目前没有 ADR 载体）：

1. **`@muyajs/core` 何时发布自带 `lib/types/*.d.ts`？** 若近期发布，第 6 节引擎门面可跳过、直接删 `muya-core.d.ts`。（未知，需查上游 `marktext/muya`）
2. **未来能力里第一个真实变体是什么？** 若是多窗口工作区，先做窗口身份显式化；若是远程文件，才值得重提文件提供者抽象。（未知，取决于路线图）
3. **主/渲染进程是否可能独立升级（进而需要 IPC 版本协商）？** 当前 Electron 42 同版本部署下不需要；若引入独立升级，需重开进程边界决策。
4. **内部总线的生命周期**：是经 `Accessor` 注入（可测、可替换）还是模块级单例（与现有 `CommandManager` 风格一致）？这是实现细节，但影响测试注入方式，值得在迁移前定。

审查过程未修改任何文件，仅做了只读核查。

[EVAL:evolve-software-architecture-loaded]
