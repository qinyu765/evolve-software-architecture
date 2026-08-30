我已完成证据收集（文档、实现、配置、测试、Git 历史、构建配置）。以下是架构评审结论。核心判断：**当前仓库正处于“编辑器引擎迁移已基本完成、但迁移留下的临时边界尚未收口”的阶段，最高杠杆的动作是稳定已经承压的边界（沙箱/预加载桥、IPC 契约、引擎公共 API、文档状态所有权），而不是引入新的抽象层。**

---

## 1. 范围与置信度

**评审对象**：MarkText monorepo（`marktext-monorepo`）与 `packages/desktop`，评估未来四类能力——窗口能力、文件工作流、编辑器引擎演进、Electron shell 能力——下哪些边界应当稳定、哪些抽象应当延后。

**仓库分类**：Electron 桌面应用（三进程模型：main / preload / sandboxed renderer），pnpm workspace 单仓，含一个正在接管的编辑器引擎包 `@muyajs/core`。技能里的 Desktop/Tauri 适配器在“进程边界稳定性、平台安全、生命周期正确性、可测试性、资源行为”这些关切上适用，但 Tauri/Rust 识别信号不匹配（本仓库是 Electron + Node，非 Tauri）；我按核心流程 + 桌面进程边界的思路执行。

**置信度**：高。以下结论都来自可核对的源文件、配置、测试与 git 状态；仅有状态所有权等少数推理点已单独标注为“推断”。

---

## 2. 已核实的事实

| 主张 | 证据 | 类型 | 置信度 | 对决策的影响 |
| --- | --- | --- | --- | --- |
| 渲染器已完全沙箱化：`contextIsolation:true, sandbox:true, nodeIntegration:false` | `packages/desktop/src/main/config.ts:12-21,35-42` | 事实 | 高 | 这是安全边界与唯一 IPC 通道，任何新能力都必须走 `window.electron.*` |
| 但两个窗口都 `webSecurity:false` | 同上 `config.ts:19,40` | 事实 | 高 | 渲染进程 CORS/SOP 被放宽，是需要单独决策的残留风险 |
| CLAUDE.md 的架构章节与此矛盾：声称 `contextIsolation:false + nodeIntegration:true (see config.js)` | 根 `CLAUDE.md` “Architecture” 段 | 事实 | 高 | 文档漂移；`config.js` 已不存在（现为 `config.ts`） |
| 沙箱是“承压边界”，有金丝雀 E2E | `test/e2e/context-isolation.spec.ts:6-38` | 事实 | 高 | 回归会直接炸掉该测试 |
| 唯一预加载桥：`electron`/`fileUtils`/`path`/`ripgrep`/`uploader`/`fonts`/`commandExists`/`i18nUtils` 等挂在 contextBridge | `src/preload/index.ts:286-296` | 事实 | 高 | 新增 shell 能力的稳定 seam 在此 |
| IPC 契约在渲染侧是强类型、主进程侧是字符串字面量、大量 `unknown` | `src/shared/types/ipc.ts`（注释 “commits 5–8” 迁移期）；`src/main/ipc/fs.ts:40-77`、`window.ts`、`editorBufferStore/index.ts:214-218` | 事实 | 高 | “单一事实源”只对渲染侧成立；主进程 handler 无编译期校验 |
| 存在两套并行寻址：`ipcMain.emit` 内部事件总线 + 渲染侧 `mitt` bus + `ipcRenderer`；监听常同时注册两处 | `src/main/utils/internalIpc.ts`；`src/renderer/src/bus/index.ts`；`store/editor.ts` 的 `LISTEN_FOR_*` | 事实 | 高 | 加一条通知要改 ipc.ts + preload + main + renderer（+bus），变更放大 |
| 窗口模型：`BaseWindow` → `EditorWindow`(646 行)/`SettingWindow`；`WindowType` 是封闭枚举 | `src/main/windows/base.ts:16-20`；`editor.ts`；`setting.ts` | 事实 | 高 | 加窗口类型需改枚举 + 子类 + 菜单 + App + 多处 `as EditorWindow` 强转 |
| 文件打开的路由启发式集中在 `App._openPathList` + `WindowManager.findBestWindowToOpenIn` + `EditorWindow.getCandidateScores` | `src/main/app/index.ts:519-640`；`windowManager.ts:256-305`；`editor.ts:449-469` | 事实 | 高 | 文件工作流最易变、最难测的部分，目前无法单测 |
| 保存由渲染侧发起（Pinia 持有编辑真值），主进程 `writeMarkdownFile` 原子落盘 | `store/editor.ts:512-529`；`src/main/filesystem/markdown.ts:69-85` | 事实 | 高 | 编辑真值与崩溃恢复快照是两个所有者 |
| 崩溃恢复由主进程 `EditorBufferStore`（每窗口一个 JSON，原子写）+ 渲染侧 1s 防抖快照承担 | `src/main/editorBufferStore/index.ts`；`store/bufferedState.ts` | 事实 | 高 | 状态所有权需要在 ADR 里显式化 |
| 引擎迁移在源码层面已基本完成：desktop/src 只 import `@muyajs/core`，**无任何** `muya/` 或 `@marktext/muyajs` 源码 import | grep（`packages/desktop/src`，`.ts/.js/.vue`）：仅 5 个文件 import `@muyajs/core` | 事实 | 高 | 遗留引擎已与运行时代码脱钩，收尾是纯删除 |
| 但遗留物仍在：`muya.d.ts` 环境声明、`muya → ../muyajs` 别名（electron.vite.config 三处 + tsconfig.base）、`@marktext/muyajs` workspace 依赖 | `src/types/muya.d.ts`；`electron.vite.config.ts:38,58,84`；`tsconfig.base.json:29`；`packages/desktop/package.json:62` | 事实 | 高 | 删除是低风险、可回滚的清理 |
| 桌面以手写环境声明 `muya-core.d.ts` 屏蔽 `@muyajs/core` 类型；包 `exports["."]` 指向 `./src/index.ts`，安装时不带已构建 d.ts | `src/types/muya-core.d.ts`（注释“Delete this file once…”）；`packages/muya/package.json:10-16` | 事实 | 高 | 引擎边界的“临时接缝”，应替换为包的真实构建类型 |
| 引擎集成面是 `any`：`type MuyaInstance = any` | `src/renderer/src/components/editorWithTabs/editor.vue`（约 172-175 行） | 事实 | 高 | 引擎边界目前是诚实的弱类型，但不该就此固化 |
| 命令分发是两套并行系统：主进程 `CommandManager`（单例、字符串 id、`any` 回调）+ 渲染侧静态命令描述符 + `commandCenter` | `src/main/commands/index.ts`；`common/commands/constants.ts`；`src/renderer/src/commands/index.ts` | 事实 | 高 | 菜单/快捷键 → 主进程 → `mt::execute-command-by-id` → 渲染 |
| 主进程用 `Accessor` 服务定位器聚合 preferences/dataCenter/editorBufferStore/commandManager/keybindings/menu/windowManager | `src/main/app/accessor.ts:12-42` | 事实 | 高 | 新增能力会通过它或绕过它，边界松散 |
| 测试基建强：E2E 100+ 条（含 parity-*）、单测、muya 规范基线（CommonMark 87.7%/GFM 86.3% 锁定）、PARITY_QA/SCOREBOARD 手工清单 | `test/e2e/**`、`test/unit/specs/**`、`test/PARITY_QA.md`、`packages/muya/test/spec/` | 事实 | 高 | 已有可复用的验证手段，迁移步骤可据此设退出标准 |

---

## 3. 当前摩擦（变更放大与缺失的所有权）

按用户问的四个轴归纳：

**窗口能力** —— 加一个新窗口类型，目前要触碰 `WindowType` 枚举、新 `BaseWindow` 子类、`App._createXWindow`、`WindowManager` 的按类型遍历、应用菜单注册，以及散落在 `app/index.ts`/`windowManager.ts` 里大量 `as EditorWindow` 强转（`EditorWindow.openTab/openFolder/getCandidateScores/openedRootDirectory` 都靠强转访问）。多态很浅，`EditorWindow` 专属能力泄漏到了管理代码里。

**文件工作流** —— 打开文件“放到哪个窗口”的策略是 500 多行启发式（`_openPathList`），与窗口评分逻辑跨三个文件分布，且无法单测（强依赖 Electron `BrowserWindow`）。保存/移动/重命名/关闭/恢复的状态机集中在渲染侧 `store/editor.ts`（约 2100 行的 Pinia god store），把文档状态、IPC 监听、tab 生命周期、菜单状态推导、自动保存全部混在一起。

**编辑器引擎演进** —— 迁移在 import 层面已完成，但遗留了：手写类型 shim、`muya/` 别名、`@marktext/muyajs` 依赖、`muya.d.ts`。真正的问题是“临时接缝”正在变成长期接缝：`muya-core.d.ts` 明确说要删除，但依赖它才能 typecheck；集成面是 `any`。如果不收口，引擎边界会永久停留在弱类型。

**Electron shell 能力** —— IPC 契约只在渲染侧强类型，主进程注册 handler 用字符串字面量，加一条 channel 要在 ipc.ts + preload + main 三处手工对齐，且无编译期检查防错位。`webSecurity:false` 是未决策的残留。CLAUDE.md 对沙箱的描述与实现相反（文档漂移）。

**贯穿性的两个根因（推断）**：
1. 文档/编辑状态有多个所有者（渲染 Pinia+muya 是编辑真值；主进程 `EditorBufferStore` 是崩溃恢复快照），但没有一份明确的所有权约定，导致保存/关闭/恢复逻辑反复在两进程间对拍。
2. 迁移期为了“先对齐 JS 行为”引入的宽松类型（`unknown` 载荷、`any` 回调、`any` Muya 实例、双 bus）正在变成结构性欠账，而不是被逐步收紧。

---

## 4. 质量属性优先级（刻意排序，含权衡）

| 优先级 | 属性 | 目标 | 现状证据 | 说明 |
| --- | --- | --- | --- | --- |
| 1 | 进程边界正确性/安全 | 新能力不破坏沙箱；channel 变更编译期可校验 | 沙箱金丝雀 E2E；主进程 handler 无类型校验 | 这是桌面应用的承压 seam，也是唯一不能回退的边界 |
| 2 | 可维护性（局部性） | 单点变更尽量留在单文件/纯函数 | `editor.ts` 2100 行、`app/index.ts` 853 行、`editor.ts`(window) 646 行 | 当前变更成本集中在三四个 god module |
| 3 | 可测试性 | 策略逻辑不依赖 Electron 即可验证 | 路由/菜单状态推导无单测；E2E 是唯一网 | 作为前两项的验证手段，而不是额外目标 |
| 4 | 可扩展性 | 只在真实变体出现处开 seam | 只有 1 个引擎、2 种窗口 | 刻意排最后：当前没有第二个引擎/窗口变体，过早抽象是投机 |
| 5 | 成本 | 每步可逆、可回滚 | 迁移进行中，git 是浅克隆 | 避免大爆炸式重构，优先纯删除 + 纯函数提取 |

**权衡**：把“进程边界正确性”排第一意味着不追求短期“快速加功能”的便利（比如重新打开 nodeIntegration 或绕过 preload）；把“可扩展性”排最后意味着在窗口/引擎/原生能力上**主动不建通用框架**，直到第二个真实变体出现。

---

## 5. 方案比较（含维持现状）

### 方案 A：维持现状（ad-hoc 演进）

**边界与所有权**：维持当前形状——新窗口加子类 + 强转；新文件能力加 channel + god store 逻辑；引擎边界继续靠手写 shim + `any`。

**能做的事**：单点功能最便宜；不与迁移收尾抢节奏。

**代价**：每次新增窗口/文件/channel 都在四个文件中放大；IPC 契约的“单一事实源”名不副实；引擎边界的临时接缝固化为长期债务。

**迁移/回滚成本**：零迁移成本（就是现状）；但未来每一步的纠错成本累加。

**运维/测试**：现状即可；但策略逻辑仍无法脱离 Electron 单测。

**什么证据会证明它错**：当第三个窗口类型或第二个引擎变体真正排期时，强转与弱类型会直接成为阻塞。

### 方案 B：稳定承压边界 + 渐进加固（推荐）

**边界与所有权**：把四个已经承压的 seam 显式固化为契约——(1) 沙箱/preload 桥不变；(2) IPC 契约对主进程 handler 也强制类型化；(3) `@muyajs/core` 公共 API 是唯一引擎 seam，删除遗留引擎；(4) 文档状态所有权写进 ADR。**不**引入新的抽象层。

**能做的事**：新 shell 能力、新文件工作流、新窗口都能在一个经过校验的 seam 上落地；引擎边界从 `any` 收敛到真实类型。

**代价**：一笔中等但分散的机械式投入（类型化 handler 注册、纯函数提取、shim 删除），每步可独立合并。

**迁移/回滚成本**：低——每步要么是纯删除（shim/别名/依赖），要么是可逐文件回退的类型加固，要么是“先抽纯函数、旧调用保留”的行为保真迁移。

**运维/测试**：新增编译期护栏 + 策略单测；E2E 作为行为保真网。

**什么证据会证明它错**：如果 `@muyajs/core` 近期就要发布自己的 d.ts（则 shim 删除路径要调整）；如果团队计划立刻做协作编辑或第二个引擎（则需要重新评估是否值得先固化单一引擎 seam）。

### 方案 C：激进抽象（窗口服务 / 文档服务 / 编辑器适配器层）

**边界与所有权**：引入带 DI 的“窗口注册中心”“文档服务”“编辑器适配器接口”，主进程全面服务化，命令/事件总线统一。

**能做的事**：为多窗口、多引擎、协作编辑等未来形态预留扩展点。

**代价**：前期成本高；当前只有 1 个引擎、2 种窗口，多数抽象是投机性间接层；与迁移收尾并发，风险大。

**迁移/回滚成本**：高——大范围改写，回滚困难，行为保真难保证。

**运维/测试**：框架自身需要大量新测试；收益只有在真实变体出现后才兑现。

**什么证据会证明它错**：如果未来 12–24 个月只有 MarkText 这一个消费方、只有一个引擎、窗口类型不超过 2–3 种，那么这套框架就是纯负担（当前证据正指向这一点）。

---

## 6. 推荐

**采用方案 B。** 它把资源花在“已经承压的边界”上，而不是预测未来的抽象上。下面按用户问的四个轴，明确哪些**应当稳定**、哪些**应当延后**。

### 应当稳定（投资、加固、当作契约）

1. **渲染沙箱 + preload 桥**（`config.ts` webPreferences + `preload/index.ts`）。这是不可回退的安全边界，已有金丝雀测试。任何新能力都走 `window.electron.*` 的 typed surface；绝不重新打开 `nodeIntegration`。
2. **IPC 契约 `shared/types/ipc.ts` 对两侧生效**。把它从“渲染侧强类型、主进程字符串字面量”变成真正单一事实源：加一个类型化 handler 注册辅助函数，让主进程 `ipcMain.handle/on` 的 channel 名与参数从契约推导。这是未来“shell 能力 + 文件工作流”最高杠杆的一处收口。
3. **`@muyajs/core` 公共 API（`src/index.ts`）是唯一引擎 seam**。删除遗留引擎（`muya.d.ts`、`muya` 别名、`@marktext/muyajs` 依赖），并用包的真实构建类型替换手写 `muya-core.d.ts` shim。**不要**在桌面侧再包一层“编辑器适配器接口”。
4. **文档状态所有权**（写进 ADR）：渲染侧 Pinia+muya = 编辑真值；主进程 `EditorBufferStore` = 崩溃恢复快照；`filesystem/markdown.ts` = 唯一原子写入口。防止未来文件工作流引入第三个所有者。
5. **`BaseWindow` 生命周期/事件契约 + `WindowManager` 的 id/活动追踪**保持稳定但**窄**——它是可复用骨架，但不要扩展成框架。

### 应当延后（现在不建，附重新评估信号）

1. **通用“窗口插件/注册框架”**——当前只有 2 种窗口。延后；当第 3 种窗口类型（如差异/预览窗）真正排期时，再做最小的注册表。
2. **桌面侧“编辑器引擎适配器”**——遗留引擎已与源码脱钩，只剩一个引擎；适配器是投机性间接层。延后；只有当第二个引擎真实回归时才建。
3. **通用“原生能力抽象层”（把 Electron `shell/dialog/fs` 全部服务化 + fake seam）**——只在测试确实需要的缝上做假（如文件路由纯函数），不做全局服务层。延后；到第二个 OS 特化变体出现时再评估。
4. **协作编辑/OT 同步传输**——muya 状态层已为 OT 铺好路，但没有传输需求。延后；有真实同步需求时再评估。
5. **换壳（迁移 Tauri / 重写 main 为 Rust）**——无任何证据支持，超出范围。

---

## 7. 迁移与验证（可逆的渐进路线）

每步独立可合并、可回滚、有退出标准：

**步骤 0 — 文档与 ADR（成本最低，无行为变化）**
- 修正 CLAUDE.md 漂移：`config.js` → `config.ts`；沙箱值改为 `contextIsolation:true, sandbox:true, nodeIntegration:false`；补上 `webSecurity:false` 的说明。
- 写两份 ADR：IPC 契约（两侧强类型化）与文档状态所有权（渲染真值 vs 主进程恢复快照）。
- **退出**：文档与 `config.ts` 一致；ADR 合入。
- **回滚**：纯文档，直接 revert。

**步骤 1 — 引擎收尾（纯删除为主）**
- 让 `packages/muya` 的构建产出真实 `lib/types`（其 `vite-plugin-dts` 已在产出），把 `@muyajs/core` 的解析从 `muya-core.d.ts` 切到包自身类型；随后删除 `muya-core.d.ts` + `tsconfig.base.json:30` 的 paths、`muya.d.ts`、`electron.vite.config.ts` 三处 `muya` 别名、`packages/desktop/package.json:62` 的 `@marktext/muyajs`。
- **验证**：`pnpm -C packages/desktop typecheck` 通过；`pnpm -C packages/muya build` 产出类型；`pnpm -C packages/desktop exec vitest run` + `pnpm -C packages/desktop exec playwright test test/e2e`（重点 parity-*）通过。
- **回滚**：恢复被删文件/依赖即可。

**步骤 2 — IPC 契约两侧强类型**
- 新增 `registerHandler/registerSendHandler` 辅助函数，channel 与参数从 `IpcInvokeChannels/IpcSendChannels/IpcSyncChannels` 推导；先迁移已整形的 `src/main/ipc/*`，再迁 `editorBufferStore`、`windowManager`、`app/index.ts`，逐步收紧 `unknown`。
- **验证**：新增一条“契约里每个 channel 都有对应 handler”的静态表/单测；故意漏一个 handler 应 typecheck 失败。
- **回滚**：逐文件 revert。

**步骤 3 — 抽纯文件路由**
- 把 `_openPathList` + `findBestWindowToOpenIn` + `getCandidateScores` 的评分/分窗逻辑抽成无 Electron 依赖的纯模块 `main/windows/placement.ts`，旧调用点薄封装调用。
- **验证**：对“新文件/新目录/同窗口/新窗口/已打开跳过”写单测（无需打包运行）。
- **回滚**：保留薄封装，删除抽离。

**步骤 4 — 收窄渲染侧 god store**
- 把 `createApplicationMenuState`/`createSelectionFormatState` 抽成纯模块并单测；把 IPC 监听继续向 `store/listenForMain.ts` 收敛，减少 `store/editor.ts` 的 `LISTEN_FOR_*` 双注册。
- **验证**：菜单状态推导有单测；E2E parity-* 与 menu-sanity 通过。
- **回滚**：逐文件 revert。

**步骤 5 — 状态所有权与 `webSecurity` 决策（先测量再改）**
- 落地步骤 0 的状态所有权 ADR，逐步让保存/关闭/恢复都只经约定的所有者。
- 对 `webSecurity:false` 做一次面向功能的测量：暂时移除后跑 E2E（预览远程图片、导出 PDF/HTML 等），定位真正依赖它的功能，再决定“按功能收紧（如 `setWindowOpenHandler`+具体 CSP）”还是“保留并文档化残留风险”。**这一步只做评估和决策，不默认改安全配置。**

**整体验证网**：`pnpm -C packages/desktop typecheck` + `lint`、`vitest run`（含新增纯函数单测）、`playwright test test/e2e`（含 `context-isolation.spec.ts` 金丝雀）、`pnpm -C packages/muya test:spec`（规范基线只升不降）。任何一个 E2E 回归即视为该步骤行为保真失败。

---

## 8. 待决策问题（会改变上述推荐）

1. **`@muyajs/core` 是否近期从本仓库发布带 d.ts 的版本？** 若是，步骤 1 的切类型路径要按发布产物调整；若否，先在本仓库 `build` 产出 `lib/types` 供桌面消费。
2. **`webSecurity:false` 的原始动机是什么？** 需要一次功能定位才能安全收紧或文档化（步骤 5 前置）。
3. **未来 12–24 个月是否有第二个引擎或第三个窗口类型的真实计划？** 若“是”，方案 B 中“延后适配器/窗口框架”的判断需要提前重估；当前证据显示“否”。
4. **迁移“commits 5–8”的 `unknown` 收紧计划是否有明确顺序？** 这决定步骤 2 能多快收敛，以及是否值得为 handler 注册写一次性的契约测试。

**不改变的后果**：引擎临时接缝固化为永久 `any` 边界；IPC 契约继续“半强类型”，每条新 channel 都靠人工对齐；文件路由与菜单状态推导永久无法脱离 Electron 单测；下一次加窗口/文件能力时，变更继续在四五个 god module 里放大。

[EVAL:evolve-software-architecture-loaded]
