我已完成对仓库的证据采集。下面是基于代码事实（而非推断）的评估，覆盖多窗口、本地文件 IO、编辑器引擎与 Electron shell 四条边界，并对比“维持现状”与“结构调整”的代价、风险和验证方式。只给建议，不改代码。

---

## 1. 范围与信心

**被评估的决策**：在 MarkText 长期演进中，四条边界（多窗口、本地文件 IO、编辑器引擎、Electron shell）应当继续维持现状、做有界调整，还是大幅重构；每条边界的调整优先级与可逆的迁移路径。

**仓库分类**：Electron 桌面应用 + pnpm monorepo（`packages/desktop` 为 shell，`packages/muya` 为 TS 引擎，`packages/muyajs` 为退役中的 JS 引擎）。信心：**高**——由 `electron-vite.config.ts`、`packages/desktop/package.json`（electron 42 / electron-builder / electron-vite 5）、`src/main|preload|renderer` 三层进程目录、以及 `shared/types/ipc.ts` 的 IPC 契约共同证实。这是 Desktop/Electron 类型，不是 Web 应用；因此下文不使用服务器部署式建议。

评估基于代码只读检查，未运行构建或测试；涉及“未验证”的结论会明确标注。

---

## 2. 观察事实（证据表）

| 论断 | 证据 | 类型 | 信心 | 对决策的影响 |
| --- | --- | --- | --- | --- |
| 多窗口由 main 进程单例 `WindowManager` 持有 `Map<number, BaseWindow>`，按 `BrowserWindow.id` 索引 | `src/main/app/windowManager.ts:85-88` | 事实 | 高 | 窗口是显式一等对象，已有所有权模型 |
| 每个 `EditorWindow` 独立持有 `_openedFiles` / `_openedRootDirectory` 等“打开了什么”的真相 | `src/main/windows/editor.ts:50-79` | 事实 | 高 | main 侧与 renderer 侧（`store/editor.ts` 的 `tabs`）各存一份真相 |
| 会话恢复是**每窗口一份** JSON（UUID 命名），挂在 `BrowserWindow.restoreBufferId` 上 | `src/main/editorBufferStore/index.ts:137-161`、`windows/editor.ts:139-145` | 事实 | 高 | 多窗口恢复已结构化，但持久化耦合在窗口对象上 |
| 文件保存/另存/重命名/移动/导出**不在窗口模型内**，而在全局菜单动作模块里，靠 `BrowserWindow.fromWebContents(e.sender)` 反向解析窗口 | `src/main/menu/actions/file.ts:157-225, 494-564, 458` | 事实 | 高 | 这是 IO 边界最大的耦合点 |
| 代码自己承认该问题：TODO 明确说 save/save-as 应迁到 editor window | `src/main/menu/actions/file.ts:36-38` | 事实 | 高 | 结构调整有内生的方向依据 |
| 进程内通信用 `ipcMain.emit` + `onInternalChannel` 做“事件总线”，通道是裸字符串，不在类型契约里 | `src/main/utils/internalIpc.ts:8-14`、`windowManager.ts:367-495` | 事实 | 高 | 内部 main↔main 通道无编译期检查，发现性差 |
| renderer↔main 契约是强类型的（`ipc.ts` 四大类通道 + preload 泛型封装），但参数/返回类型刻意宽松（`unknown[]`/`unknown`） | `src/shared/types/ipc.ts:1-18, 40-333`、`src/preload/index.ts:26-68` | 事实 | 高 | shell 边界的“骨架”已就位，缺内部通道与具体类型 |
| 编辑器引擎运行时已全部切到 `@muyajs/core`（`packages/muya`）；遗留 `packages/muyajs` 在 src 中**零运行时引用** | renderer 内 `editor.vue:82-113`、`markdownToHtml.ts`、`exportHtml.ts`、`pdf.ts`、`sourceCode.vue` 均 import `@muyajs/core`；`grep from 'muya'` 无命中 | 事实 | 高 | 遗留引擎已是死重，是删除边界而非设计边界 |
| 引擎边界类型是手写的宽松声明（`class Muya { [key:string]: any }`、`MuyaInstance = any`），并注明“引擎发布内置类型后删除” | `src/types/muya-core.d.ts:45-52, 16-17`、`editor.vue:172-175` | 事实 | 高 | 引擎契约无类型护栏，API 变更对 typecheck 不可见 |
| Electron shell 已是沙箱化：`contextIsolation:true, sandbox:true, nodeIntegration:false`，但 `webSecurity:false` | `src/main/config.ts:8-27, 29-51` | 事实 | 高 | 沙箱方向正确，但 `webSecurity:false` 是安全负资产 |
| CLAUDE.md 架构章节称窗口用 `contextIsolation:false + nodeIntegration:true` 并指向 `config.js`，与 `config.ts` 事实相反 | CLAUDE.md “Three-Process Electron Model”段 vs `config.ts` | 事实（文档漂移） | 高 | 文档与代码矛盾，会误导后续结构决策 |
| 遗留 `muya` 别名仍存在于三处构建配置与 workspace 依赖中 | `electron.vite.config.ts:38, 58, 84`、`tsconfig.base.json:29`、`package.json:62` | 事实 | 高 | 删除遗留引擎的清单明确 |
| 单测通过 `main_renderer/*` 别名直接 import main 进程模块，并大量 `vi.mock` 内部模块 | `test/unit/specs/*.spec.ts`（如 `format-menu-state.spec.ts:22-34`） | 事实 | 高 | 测试目前“伸进实现”，没有穿过跨模块 seam |
| E2E 覆盖较全（保存、watcher、崩溃恢复、XSS、context-isolation），但多窗口并发的专门用例薄 | `test/e2e/*.spec.ts`（`tabs`、`external-reload-undo`、`crash-*`、`xss`、`context-isolation`） | 推断 | 中 | 结构调整后的回归网基本够用，需补多窗口用例 |

---

## 3. 当前摩擦（按影响排序）

1. **文件 IO 是最大的变更放大点。** 一次“保存标签页”横跨 renderer store → preload → `ipcMain.on('mt::response-file-save')`（在 `menu/actions/file.ts` 全局模块）→ `writeMarkdownFile` → `ipcMain.emit('window-file-saved')` → `WindowManager` 抑制 watcher 回读。保存逻辑没有窗口引用，靠 `fromWebContents` 反查窗口再发内部事件——`menu/actions/file.ts` 这个模块是全局单例，却被要求处理每窗口状态。新增任何窗口级文件能力（如“只读窗口”“预览窗口”）都要改这个不该知道窗口的模块。

2. **两套并行的 IPC 机制。** `ipcMain.on/handle`（真实 renderer→main，有类型契约）与 `ipcMain.emit` + `onInternalChannel`（main 进程内事件总线，裸字符串，无契约）混用。前者在 `ipc.ts` 里强类型，后者的通道名（`window-add-file-path`、`window-file-saved`、`app-open-file-by-id` 等）散布在 `windowManager.ts`、`app/index.ts`、`menu/actions/file.ts` 中，编译器无法发现“发射者/监听者签名不一致”。

3. **“打开了哪些文件”的真相在两处重复。** main 侧 `EditorWindow._openedFiles` 用于 watcher 管理与 `findBestWindowToOpenIn` 打分；renderer 侧 `editorStore.tabs` 用于脏状态与 UI。二者靠一串 `mt::window-add-file-path` / `window-change-file-path` / `window-file-saved` 事件手工同步，漂移风险与调试成本并存。

4. **引擎契约是 `any`。** 桌面端把引擎的 `json-change` 事件重铸成自己的 markdown/字数/光标/历史/TOC/blocks 快照（`editor.vue:1862-1887`），并维护一套 `syntheticHistory.ts` 来映射引擎历史。这些类型都是 `any` 重铸，引擎 API 变化不会在 typecheck 暴露。`Muya.use` 插件注册还是进程级全局、靠模块级布尔守卫防重复（`editor.vue:164-170`），是脆弱的隐性约束。

5. **遗留引擎是死重。** `packages/muyajs`、`muya` 别名、`muya.d.ts` 环境声明、`@marktext/muyajs` workspace 依赖全部保留，但没有任何运行时 import。这是纯粹的删除机会，不涉及设计取舍。

6. **文档与配置漂移。** CLAUDE.md 架构章节与 `config.ts` 相矛盾（`config.js` 已不存在），`webSecurity:false` 未在任何地方被点名和解释。

---

## 4. 质量属性优先级（本决策的支配性属性）

| 排序 | 属性 | 目标 | 现状证据 | 改善它的选项 | 可能回退的属性 | 捕捉回退的验证 |
| --- | --- | --- | --- | --- | --- | --- |
| 1 | 可维护性/局部性 | 文件/窗口类改动保持局部、可理解 | 文件 IO 横跨全局模块（第 3.1 条） | 结构调整 B1（IO 移入窗口模型） | 短期改动面变大 | 现有 E2E 全绿 + 新增窗口级单测 |
| 2 | 可测试性 | 能穿过预期 seam 验证，而非伸进实现 | 单测大量 `vi.mock` 内部模块（`main_renderer/*`） | 类型化内部通道 + 窗口级方法 | 初期测试迁移成本 | 单测改为在 EditorWindow 层断言 save/rename 行为 |
| 3 | 进程边界稳定性 | IPC 契约完整、版本可控 | renderer 契约强类型；内部通道裸字符串 | 把内部 main↔main 通道纳入契约 | 契约样板增多 | 类型检查 + 契约穷举脚本 |
| 4 | 安全 | 沙箱不因演化回退 | `sandbox:true` 已落地；但 `webSecurity:false` | 审计/消除 `webSecurity:false` | 某些本地资源加载可能失效（未知） | `xss`、`context-isolation` E2E + 图片/导出用例 |
| 5 | 可移植性/升级成本 | Electron 大版本、原生模块可平滑升级 | ESM/CJS 分裂已用 `externalizeDeps` 处理；`keytar` 已弃维护 | 保持 shell 薄且具体 | — | 构建 + 原生模块重建 CI |
| 6 | 成本/风险 | 调整可逆、增量 | 四条边界均存在既有 seam | 分步、行为保持 | 过度抽象 | 每步 grep/typecheck/parity 记分牌不变 |

**明确的取舍**：可维护性与可测试性在这里优先于“彻底抽象出可替换 shell”。因为只有一个 shell 变体，没有任何证据表明会出现第二个（见第 6 节），为可移植性预付抽象成本不划算。

---

## 5. 选项对比

### 选项 A：维持现状（就地加固）

保留当前四层结构，只修复文档漂移、补测试、移除死重，不移动任何所有权。

- **边界与所有权**：不变。文件 IO 仍在 `menu/actions/file.ts`；打开文件真相仍双份；内部通道仍裸字符串。
- **代价**：最低（零迁移）。
- **风险**：摩擦 3.1–3.3 持续累积；每新增一个窗口级文件功能，变更继续跨全局模块；引擎 `any` 边界长期无护栏。
- **验证**：现有 E2E 已能守住现状行为。
- **何时被证伪**：只要出现“第二个窗口类型/第二个引擎消费者/引擎 API 升级”，现状的变更放大就立即显现。目前没有任何证据表明这不会发生——恰恰相反，`EditorWindow` 与 `SettingWindow` 已经构成了两个窗口类型，而引擎迁移刚刚完成，说明窗口类型与引擎都会继续变。

### 选项 B：有界结构调整（推荐，非大爆炸）

按优先级做三件事，每件独立、可逆、行为保持：

- **B1｜文件 IO 移入窗口模型**：把 `menu/actions/file.ts` 里的 save/save-as/rename/move/export 处理器迁到 `EditorWindow`（代码内 TODO 已指向此方向）。保持 IPC 通道名与参数形状不变（renderer 与 preload 零改动），只把“从 `fromWebContents` 反查窗口再 `ipcMain.emit('window-*')`”改为窗口对象的方法调用/窗口级事件。
- **B2｜彻底退役遗留引擎**：删除 `packages/muyajs`、三处 `muya` 别名、`muya.d.ts`、`@marktext/muyajs` workspace 依赖；`@muyajs/core` 发布内置类型后删除 `muya-core.d.ts` 与 `paths` 重定向。
- **B3｜补全类型契约与单一真相（低优先级，仅当触发条件出现）**：把内部 main↔main 通道纳入 `ipc.ts` 式契约；把“打开文件真相”收敛到一方（main 或 renderer）。**不要现在做**——只有出现第二个引擎消费者或第三个窗口类型时才值得。

**被否的选项 C（整层重构/换壳）**：把 Electron 换成 Tauri、或引入 DI 层、或做 shell-agnostic 抽象。**证据不支持**：仓库只有一个 shell 变体、一个引擎消费者；`contextIsolation+sandbox+typed IPC` 的骨架已经正确，问题在“契约不完整”而非“契约不存在”。这类重构是数量级更高的成本，且会打断已落地的引擎迁移。

---

## 6. 建议

**总体方向：选项 B，但严格按 B2 → B1 →（视触发条件）B3 的顺序，每步独立可回滚。** 这是把“结构调整”约束在既有 seam 上，而不是新建架构。

**按边界的具体建议：**

- **编辑器引擎**：优先级最高，但成本最低、风险最低。B2 是纯删除，不改变行为。引擎边界唯一要保留的“结构调整”是：推动 `@muyajs/core` 发布内置 `lib/types/*.d.ts`，删掉 `muya-core.d.ts` 的宽松 `any` 面，让 typecheck 重新覆盖这条边界。**不要**为了“引擎可替换”再包一层接口——只有一个引擎，现有 `editor.vue` 就是调用方。

- **本地文件 IO**：这是唯一需要真正移动所有权的边界。B1 把保存/重命名/移动/导出收敛进 `EditorWindow`，消除“全局菜单模块处理每窗口状态”的反模式。执行时要**保持通道名与参数形状不变**，这样 renderer/preload 与现有测试一行不改，属于行为保持的机械移动。watcher 与原子写（`write-file-atomic`）的耐用性逻辑已经独立且被单测覆盖，不要动它。

- **多窗口**：现状本身可辩护——`WindowManager` + 每窗口 `EditorWindow` 已经是合理的所有权模型，会话恢复也已按窗口分片。**不建议**现在做大改。唯一的低成本动作是：B3 的“单一真相”先只做**观察**（谁在改 `_openedFiles` 与 `tabs` 的同步事件链），暂不落地，等第二个窗口类型或第二个引擎消费者出现再收敛。多窗口打分启发式（`findBestWindowToOpenIn`）保持原样。

- **Electron shell**：**维持 Electron，维持沙箱方向，把 shell 边界做薄做具体，不做可替换抽象。** 具体三点：(a) 修正 CLAUDE.md 与 `config.ts` 的矛盾，并把 `webSecurity:false` 作为显式、有理由、有范围的例外写清楚；(b) 处理 `keytar`（已弃维护的原生模块）的替代（Electron `safeStorage` 是候选）；(c) 完成 B3 的类型契约后，内部通道才与 shell 边界对齐。`contextIsolation:true / sandbox:true / nodeIntegration:false` 是正确基底，不要回退。

**明确“不做什么”**：不引入 DI 容器；不做 shell-agnostic 抽象；不做 Electron→Tauri 换壳；不在只有一个引擎消费者时抽象引擎接口；不在只有一个窗口类型变化点时重构多窗口所有权。

---

## 7. 迁移与验证

**可逆性**：B2 是删除（git 可恢复）；B1 是移动方法（若 E2E 回归即可退回）；B3 是加类型（删除类型即可退回）。三者互不阻塞。

**分步与首条纵切**：

1. **B2（1–2 个 PR）**：删除遗留引擎面 → `grep -rn "muya/lib\|from 'muya'\|@marktext/muyajs" packages/desktop` 零命中；`pnpm typecheck`、`pnpm build`、`pnpm -C packages/desktop exec vitest run` 全绿；parity 记分牌（`test/PARITY_SCOREBOARD.md`）不变。
2. **B1（2–3 个 PR，行为保持）**：把 save/save-as/rename/move/export 迁入 `EditorWindow`，通道不变 → 回归网：现有 `tabs`、`crash-*`、`external-reload-undo`、`flush-before-save` E2E 全绿；新增 EditorWindow 层单测（伪造 dialog/fs，断言 save 后触发 watcher 抑制与 `mt::tab-saved`）。
3. **B3（仅当触发）**：内部通道类型化 → 一个穷举脚本断言所有 `ipcMain.on/handle/emit` 与 `webContents.send` 的通道都出现在契约中，纳入 `pnpm check`。

**验证清单（跨 seam 的检查，而非只测纯函数）**：

- **契约测试**：类型化后，编译器覆盖 renderer↔main 与 main↔main 两段。
- **窗口级单测**：把现在“`vi.mock` 内部模块”的测试，逐步改为在 `EditorWindow`/`WindowManager` 方法边界断言（如 save 后 `_openedFiles` 与 watcher 状态一致）。
- **多窗口 E2E**：补一个“两个窗口同时打开同一文件/分别保存/关一窗不丢另一窗缓冲”的用例——这是当前 E2E 的明显空白。
- **失败模式检查**：watcher 自抑制（`ignoreChangedEvent` 的稳定性阈值 + mtime 回查）、崩溃恢复缓冲（`buffer-store-durable`、`write-file-atomic`）已覆盖，保持不变即可。
- **安全回归**：`xss.spec.ts`、`context-isolation.spec.ts` 守住 shell 边界；`webSecurity:false` 的消除/保留以“图片加载、导出、字体、PDF”用例为验证。

**完成标准（可观测）**：B2 后遗留引擎引用为零；B1 后 `mt::response-file-save` 不再经 `fromWebContents` 反查窗口；B3 后所有通道在单一契约中穷举；整个过程 parity 记分牌与 E2E 结果不回退。

---

## 8. 待定决策（其答案会改变上述建议）

1. **`webSecurity:false` 为什么存在？**（未知）最便宜的求证：开发模式临时改为 `true`，跑图片/导出/字体/PDF 相关 E2E，看什么坏掉。若可消除，shell 安全评估显著改善；若不可消除，需把它写成带理由的作用域例外。
2. **是否有第二个编辑器窗口类型或第二个引擎消费者的计划？**（未知）若“是”，B3 的“单一真相 + 类型契约”应提前到 B1 之后立即做；若“否”，多窗口边界维持现状即可。
3. **`@muyajs/core` 何时发布内置类型？**（未知）这决定删除 `muya-core.d.ts` 的时机，也是引擎 `any` 边界能否被 typecheck 重新覆盖的前提。
4. **`keytar` 的替代方案是否接受 Electron `safeStorage` 的行为差异？**（未知）涉及加密数据的迁移与平台差异，是 shell 层独立的小决策。
5. **“打开文件真相”收敛到 main 还是 renderer？**（未知，设计选择）renderer 已拥有脏状态与 UI 状态，但 main 拥有 watcher 与磁盘真相；需要产品/维护者拍板，不是纯技术决定。

[EVAL:evolve-software-architecture-loaded]
