# MarkText 架构演进边界评估

## 1. 范围与置信度

评估对象是四个长期演进边界的耦合结构：**多窗口、本地文件 IO、编辑器引擎、Electron shell**。问题不是“现在能不能跑”，而是“未来改动会扩散到哪里、验证要花多大代价”。

**仓库分类**：Electron 桌面应用（三进程 main/preload/renderer，沙箱 renderer），**置信度高**——多个独立信号一致（electron-vite 配置、`BrowserWindow`、`contextBridge` 预加载、electron-builder、`sandbox: true`）。注意技能库里的桌面适配器是 Tauri 版；我沿用其可泛化的桌面关注点（IPC 契约、进程所有权、生命周期、可测试性），并标注 Electron 特有差异。

结论先行：**不建议大重构，也不建议纯“维持现状”**。最划算的是收紧三个已经存在但被腐蚀的接缝（内部总线与 IPC 分家、文件 IO 收口、引擎退役收尾），按可逆顺序推进。下面先给证据，再比较。

## 2. 观察事实

| 论断 | 证据 | 类型/置信度 | 影响 |
|---|---|---|---|
| renderer 已切换到 `@muyajs/core`（packages/muya）作为编辑器引擎 | `editor.vue`、`markdownToHtml.ts`、`pdf.ts` 等 `import from '@muyajs/core'` | 事实/高 | 引擎迁移本身已完成，剩的是收尾 |
| 桌面源码已无 `muya/lib`/`@marktext/muyajs` 的静态运行时 import | `packages/desktop/src` 全文 grep 无匹配；残留仅 `.d.ts` 声明、注释、`package.json` 依赖、死 Vite alias | 事实/高 | legacy 包是“尸体”而非活跃依赖，可删除 |
| Vite 三处 `muya` alias 仍指向 `../muyajs`（legacy），但无消费者 | `electron.vite.config.ts:38,58,84` | 事实/高 | 死配置，误导后来者 |
| 引擎类型边界靠手写 ambient shim，`Muya` 实例为 `any` | `src/types/muya-core.d.ts:47-52`；`editor.vue:175` `type MuyaInstance = any` | 事实/高 | 引擎与桌面的编译期契约是“人工维护的 any” |
| 多窗口由 main 进程 `WindowManager` 注册表管理，含活跃窗口 MRU、跨窗口文件分配打分 | `windowManager.ts:85-305` | 事实/高 | 多窗口能力已存在且集中 |
| main 进程**镜像** renderer 的已打开文件列表（`_openedFiles`/`_openedRootDirectory`），用于“最佳窗口”打分与去重 | `windows/editor.ts:57-58,449-469` | 事实/高 | 同一知识两份，且跨进程同步靠事件 |
| 崩溃恢复是**每窗口**一份 JSON，键为稳定 UUID（`restoreBufferId`，用类型断言挂在 BrowserWindow 上） | `editorBufferStore/index.ts`；`editor.ts:139-145` | 事实/高 | 多窗口会话持久化是已知难点，已有 UUID 绕过 |
| 文件写有**两条**路径：文档保存走 `write-file-atomic`（fsync+rename 持久化）；文件树 CRUD/图片/导出走 `ipc/fs.ts` 的 `fs-extra` 直写，非原子 | `filesystem/index.ts:48` vs `ipc/fs.ts:40-65`；`renderer/util/fileSystem.ts` | 事实/高 | 一致性缺口：一部分写是崩溃/掉电安全的，一部分不是 |
| 文档保存编排逻辑住在 **menu 动作模块**里（800+ 行，混着菜单点击、对话框、watcher、最近文件） | `menu/actions/file.ts:180-225,285+` | 事实/高 | 文件 IO 没有独立 owner，改动容易扩散到菜单 |
| `ipcMain.emit` 被当作 main→main 内部总线，与 renderer↔main IPC 共用 `ipcMain.on` 命名空间 | `utils/internalIpc.ts`；`windowManager.ts:367-495`；`menu/actions/file.ts` 大量 `ipcMain.emit` | 事实/高 | 两件事共享一个通道命名空间 |
| 类型契约 `ipc.ts` 把**内部通道**（`watcher-watch-file`、`window-close-by-id`、`app-create-editor-window`、`broadcast-preferences-changed`…）与 renderer 通道混在 `IpcSendChannels` 里，preload 的 `send` 对整个接口开放 | `shared/types/ipc.ts:92-202`；`preload/index.ts:31-32` | 事实/高 | renderer 在类型层面被允许发送本不该发的内部通道 |
| 当前 renderer 实际上**没有**发这些未加 `mt::` 前缀的内部通道（grep 仅 `mt::set-user-preference`） | renderer 全文 grep | 事实/高 | 冲突是**潜伏**而非活跃；但类型系统不阻止未来的误用 |
| 编辑窗口与偏好窗口 `webSecurity: false` | `config.ts:19,40` | 事实/高 | 关闭同源策略；沙箱+contextIsolation 部分缓解，但属应收紧项 |
| `mt::fs::*` 透传对任意路径直接 `fs-extra`，无路径白名单/校验 | `ipc/fs.ts:40-65` | 事实/高 | 沙箱 renderer 可读写任意路径（见 §7 威胁模型讨论） |
| IPC 契约是**仅编译期**的 TypeScript 类型，参数/返回值大量仍是 `unknown`，无运行时校验 | `ipc.ts:1-14` | 事实/高 | 契约不会在运行时“报警” |
| 菜单/命令到编辑器的同一事件名同时走 Electron IPC 和 renderer 内部 mitt bus 两条通道 | `editor.ts:533-540` | 事实/高 | 跨进程与进程内事件命名再次混用 |

**历史证据**：`windowManager.ts:112`、`watcher.ts:14`、`editor.ts` 多处都有 `TODO(refactor): see #1034/#1035`，说明“watcher/window 经 `ipcMain.emit` 协作”这一块的耦合是长期已知的负债；最近提交则显示团队在持续做低风险的局部加固（原子写、flush-before-save、`contextIsolation` 测试）。

## 3. 当前摩擦（真正的痛点）

按“改动扩散”排：

1. **`ipcMain` 一物两用**。`ipcMain.emit` + `onInternalChannel` 用一次类型断言把 `IpcMainEvent` 抹掉。今天靠“内部通道不加 `mt::` 前缀”的口头约定隔离；但这个约定没有被契约文件执行，且 `broadcast-preferences-changed`/`broadcast-user-data-changed` 这些无前缀名字被写进了 renderer 可用的 `IpcSendChannels`。将来 renderer 误发一个同名字符串，监听器第一参数就会拿到 `IpcMainEvent` 而不是 payload——类型层面还发现不了。这是最便宜、最值得先拆的缝。

2. **本地文件 IO 没有统一 owner**。文档写（原子、持久）、文件树写（非原子、任意路径）、会话缓冲写（原子）三条路径由三个模块各自实现，持久性保证不一致；文档保存的编排又嵌在菜单模块里。要新增一种“保存语义”（比如自动备份、权限拒绝提示、只读文件检测）得同时摸多个地方。

3. **引擎边界是“any 手写盾”**。迁移到 `@muyajs/core` 是对的、且已基本完成，但桌面侧对引擎的类型契约是手写 shim + `any` 包装，legacy 包和死 alias 还留着。这降低了后续引擎 API 变化被编译期捕获的能力，也让新人误以为 legacy 仍被使用。

4. **main 与 renderer 的“打开文件”状态重复**。main 为跨窗口分配打分而镜像 `_openedFiles`，renderer 的 tab store 是真正权威。两处靠事件手工同步，属可接受但不该再扩大的耦合。

不把“多窗口本身”列为痛点——能力已经存在且集中在 `WindowManager`，需要的是把会话/缓冲/watcher 的所有权收拢，而不是重写。

## 4. 质量属性优先级

按本次决策的支配性排序：

1. **可维护性 / 改动局部性**（最高）——证据是上面四条摩擦：改文件 IO 会碰到菜单、watcher、窗口、缓冲四类模块。
2. **可测试性**——跨进程行为目前主要靠 60+ 个 Playwright E2E 和“抽出纯函数”的单测覆盖；类型契约是编译期的，运行时无校验。要能在不打包桌面运行时的情况下验证接缝。
3. **安全性**——`webSecurity: false` + 任意路径 `mt::fs::*` 透传是真实的信任边界松弛；不是紧急漏洞（有沙箱+contextIsolation、有 `xss.spec.ts`、`context-isolation.spec.ts`），但重构文件 IO 时应顺势收口。
4. **可扩展性/可移植性**——引擎解耦已大体达成；Electron shell 耦合不影响引擎独立性。不把“未来迁移 Tauri”当作决策依据（无证据驱动）。
5. **成本**——维护者规模小，命令式拒绝大爆炸式重构。

**权衡声明**：选 1/2 会牺牲一点短期速度（拆总线、收口 IO 都是纯结构改动，无用户可见收益）；选 3 若过度会演变成“给 `mt::fs::*` 造通用权限系统”的过度设计——**两个真实 OS 变体出现前不要造通用抽象**（这是桌面适配器明确警告的坑）。

## 5. 方案比较

### 方案 A：维持现状（继续局部加固）

- **边界**：不变。`ipcMain.emit` 内部总线、双 IO 路径、`any` 引擎盾、legacy 包保留。
- **代价**：近乎零；团队现有节奏（原子写、flush、单点修复）继续有效。
- **风险**：摩擦 1 是潜伏 bug 类，随着 IPC 通道增多，踩雷概率单调上升；文件 IO 持久性不一致意味着“崩溃安全”只在文档路径成立，文件树/导出操作仍有掉电截断窗口；legacy 包长期占用心智和构建面。
- **验证**：维持现状，继续靠 E2E + 纯函数单测。
- **会让该方案被否定的证据**：一旦出现“renderer 误发内部通道”或“文件树操作损坏”类 bug，或团队要新增第三个窗口类型/同步协作，增量成本会跳升。

### 方案 B：三处定向收口（推荐，见 §6）

B1. 把 main→main 内部事件从 `ipcMain.emit` 迁到一个很小的类型化 `EventEmitter`（几十行），`ipc.ts` 只保留真正的 renderer↔main 通道，并加 lint 禁止 `ipcMain.emit`。
B2. 把本地文件 IO 收口到一个 main 侧 `FileService/DocumentStore`：文档保存、文件树 CRUD、会话缓冲都走它，统一原子写与路径策略；renderer 不再拿裸 `mt::fs::*` 透传，而是调窄口径、带意图的命令。
B3. 引擎退役收尾：删除 legacy `packages/muyajs`、死 alias、`muya.d.ts`，让 `@muyajs/core` 产出真实 `.d.ts`（其 `build` 已配置 `vite-plugin-dts`），把桌面侧 `muya-core.d.ts` 换成正式类型。
B4.（**暂不做**）抽 `WindowSession` 模块统一每窗口的 opened-files/buffer-id/watcher 所有权——等出现第三个窗口类型或真实同步需求再动。

- **边界**：B1 建立“跨进程消息 vs 进程内消息”两个不同命名空间；B2 建立“文件意图命令 vs 裸 fs 透传”；B3 建立“编译期可检查的引擎契约”。
- **使能**：新增保存语义、权限提示、自动备份只需改一个模块；引擎升级被类型捕获；内部事件重命名不会被 renderer 看到。
- **迁移/回滚成本**：B1、B3 基本是“等价替换 + 删代码”，每步可独立合入、可 git revert；B2 是行为相关，需契约测试与 E2E 兜底。
- **会让该方案被否定的证据**：若发现 `mt::fs::*` 被第三方/插件生态依赖，收口会破坏兼容（当前仓库内无此证据）。

### 方案 C：大重构（如整体迁移 Tauri / 重写为消息核心）

- **代价/风险**：极高，且无驱动信号。沙箱化、原子写、E2E 资产都要重做。
- **否决**：CLAUDE.md 与近期提交显示的是“在一个仍健康的 Electron 壳里逐步收紧”，不是“壳本身是问题”。引擎迁移反而证明小步替换可行。

## 6. 建议

**选 B，按 B1 → B3 → B2 → (B4 观望) 顺序推进**，每步都是可逆的独立切片。

- **B1 先做**：它最小、纯机械、消掉一整个潜在 bug 类，且是 B2 的前置（否则收口 IO 时仍会经内部总线广播）。
- **B3 与 B1 可并行**：删除 dead code，收益是负成本（减少维护面），风险最低。
- **B2 最后做**：唯一有用户可见行为风险的一步，放在前两步把结构理顺之后，用契约测试护住。
- **B4 不做**，直到出现“第三个窗口类型 / 每窗口同步 / 会话恢复重写”这类真实驱动。现在抽 `WindowSession` 只是把四个地方的名字挪到一个新文件，不减少知识重复。

需要写 ADR 的点：**“main 内部事件总线与 renderer↔main IPC 分家”** 和 **“文件 IO 单一 owner 与路径策略”**。前者是团队级约定，必须落文档；后者牵涉安全模型，值得留决策记录。

## 7. 迁移与验证

每步的可观察完成标准与回滚：

**B1（总线分家）**
- 做法：新增 `main/events/` 小总线；`onInternalChannel`/`ipcMain.emit` 逐个替换；从 `IpcSendChannels` 删除所有内部通道名；`preload` 的 `send` 收窄后，renderer 误用会在 `vue-tsc` 直接报错。
- 验证：①lint 规则 `no-ipcMain-emit`；②grep 断言 `ipc.ts` 中所有 `IpcSendChannels` 键都以 `mt::`（或明确登记的 renderer 前缀）开头；③既有多窗口 E2E（`tabs.spec.ts`、`launch.spec.ts`、偏好广播相关）全绿；④加一个单测：内部事件到达所有窗口监听器时 payload 类型正确。
- 回滚：纯结构替换，revert 即回。
- 完成标准：`grep ipcMain.emit packages/desktop/src` 为空；`vue-tsc` 在 renderer 误发内部通道时失败。

**B3（引擎退役收尾）**
- 做法：`pnpm -C packages/muya build` 产出 `lib/types`；删 `packages/muyajs`、死 `muya` alias、`muya.d.ts`、`@marktext/muyajs` 依赖；把 `muya-core.d.ts` 的 `paths` 重定向改为正式 types 解析；`editor.vue` 的 `MuyaInstance = any` 换成 `Muya`/公开接口类型。
- 验证：①`vue-tsc --noEmit`；②grep 无 `from 'muya/`；③muya 侧 CommonMark/GFM 一致性分数不降（`test:spec`）；④桌面 E2E 编辑器回归（`editor-input`、`inline-format`、`parity-*`）全绿。
- 回滚：保留一个提交即可恢复 legacy 包。
- 完成标准：legacy 包从工作区消失；引擎类型由真实 `.d.ts` 驱动，`any` 只出现在确需宽容的插件注册点并写明原因。

**B2（文件 IO 收口）**
- 做法：main 侧定义窄命令（`saveDocument`、`createFile`、`movePath`、`writeExport`、`writeImage`…），全部走 `write-file-atomic`（或对不需要持久性的导出明确标注为何用普通写）；对 `mt::fs::*` 逐条替换为带意图命令，删除裸透传；路径策略只在 main 侧执行一次。
- 验证：①每个命令的契约测试（错误形状、编码、EOL、原子性）；②路径策略测试——renderer 不能写/读超出已打开根目录与 userData 白名单之外的路径；③文件树 E2E（`sidebar-create-conflict`、`move-image-to-folder`、`image-relative-path`、`export-pdf`）全绿；④掉电语义对比测试：文档保存与文件树写经过同一原子层。
- 回滚：按命令逐条替换，可分批合入；任一 E2E 失败即回退该批。
- 完成标准：`mt::fs::*` 裸透传从 `ipc/fs.ts` 移除；grep renderer 无 `window.fileUtils.writeFile/copy/move/unlink` 之外的绕过。

**贯穿性检查**：diff 评审重点看“是否把两件事塞进一个通道名”“是否有新的 `as unknown as` 抹类型”。重访条件：若引入第二个 OS 供应商或插件系统，再评估通用抽象；若出现 renderer 主动发内部通道的正当需求，说明 B1 边界需要重画。

## 8. 待决问题（会改变建议的才列）

1. **威胁模型**：`webSecurity: false` 是否有历史依赖（如本地图片预览加载 `file://`）？若可移除，应在 B2 一并处理；这决定文件 IO 路径策略的严格度。**未知**，最便宜的确认方式是 grep 是否有依赖跨源/`file://` 的 renderer 代码，或在关闭后跑一轮 E2E。
2. **`@muyajs/core` 的发布/类型产物**：`exports["."] = "./src/index.ts"` 是 dev 态。是否计划让 muya 单独发版？这决定 B3 是“切到内置 build 产物”还是“等上游发版”。**未知**，影响 B3 时间安排而非方向。
3. **文件树操作是否需要崩溃/掉电持久性**：若接受“文件树 CRUD 不需要 fsync”，B2 的统一原子层可降级为“仅文档与缓冲必须原子”。这是一个产品取舍，不是技术事实。

（结论：维持现状在短期可辩护，但三项收口——总线分家、引擎退役、文件 IO 单 owner——是低成本、可逆、且能系统性降低未来改动扩散的结构性调整，建议按 B1→B3→B2 的顺序小步推进。）

[EVAL:evolve-software-architecture-loaded]
