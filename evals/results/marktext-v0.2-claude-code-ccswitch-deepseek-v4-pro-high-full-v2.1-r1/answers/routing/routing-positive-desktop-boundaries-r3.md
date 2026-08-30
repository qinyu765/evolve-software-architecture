I've gathered enough evidence across the contract, preload, main handlers, renderer call sites, config, tests, and docs. Here's the assessment.

---

# MarkText `packages/desktop` 进程边界评估

## 1. 范围与置信度

评估对象是 `packages/desktop` 内 `main` / `preload` / `renderer` / `shared`（以及事实上承担共享职责的 `common`）之间的边界，判断它们对未来功能扩展的承载能力。**只做建议，未修改任何文件。**

分类置信度：**高**。这是一个 Electron 42 + electron-vite 5 的三进程桌面应用（`contextIsolation:true`、`nodeIntegration:false`、`sandbox:true`），与所加载的 desktop 适配器一致；适配器中 Tauri 特有项（`src-tauri`、Rust capability 文件）不适用，但其"进程边界稳定性、IPC 契约、平台安全"等关切直接适用。结论均来自可核查的源码、配置、测试与历史注释（迁移分阶段的注释散布在多个文件里）。

## 2. 观测到的事实

| 断言 | 证据 | 性质 | 置信度 | 影响 |
|---|---|---|---|---|
| `shared/` 只含类型，无运行时代码、无 Electron 依赖 | `src/shared/**` 仅 `index.ts` + `types/*`；`menu.ts:1-3` 明确"不把 Electron 类型拉进 renderer" | 事实 | 高 | 这是正确的契约栖息地，应保持 |
| IPC 契约集中在 `shared/types/ipc.ts`，约 200 个扁平通道（~43 invoke / ~90 send / 2 sync / ~70 event），大量 payload 为 `unknown` | `ipc.ts:40-289`；文件头注释 10-13 行称"迁移期有意宽松，提交 5–8 逐步收紧" | 事实 | 高 | 契约只防通道名，不防 payload 形状 |
| **契约是单边的**：`main` 进程零引用四个通道接口，只有 `preload/index.ts` 和 `types/global.d.ts` 引用 | grep `IpcInvokeChannels|IpcSendChannels|…` 在 `src/main` 无命中；`preload/index.ts:14-17`、`global.d.ts:6-12` 有 | 事实 | 高 | "单一真相源"目前只约束 renderer/preload 一侧 |
| main 侧 handler 用裸字符串字面量注册，无类型约束 | `main/ipc/fs.ts:41-64`、`bootInfo.ts:76-83`、`ripgrep.ts:433-443` | 事实 | 高 | 加/改通道要人工同步 3 处，仅 1–2 处被类型检查 |
| `ipcMain` 被**复用为 main 进程内部事件总线**（`ipcMain.emit` + `onInternalChannel`） | `main/utils/internalIpc.ts`、`app/windowManager.ts:421-476`、`app/index.ts:807`、`menu/actions/edit.ts:125` | 事实 | 高 | 跨进程 IPC 与进程内事件共用一个对象和一个命名空间 |
| 契约把**纯内部通道**错标为 renderer→main：`screen-capture` 在 `IpcSendChannels` 里，但 renderer 从不发它，只在 main 内部 emit | `ipc.ts:188`；`app/index.ts:672`（onInternalChannel）、`805-807`（由 `mt::make-screenshot` 内部 emit）、`edit.ts:125` | 事实 | 高 | 契约不再是"renderer 真相关"的精确清单 |
| main 进程内部有**两套事件系统**：`TypedEmitter`（typedEmitter.ts）与 `ipcMain.emit`/`onInternalChannel`；renderer 另有一套 mitt bus，且未采用 `shared/types/bus.ts` | `shared/types/typedEmitter.ts` 注释；`windowManager.ts`；`renderer/src/bus/index.ts:3-11` | 事实 | 高 | 三套 bus、三种类型化程度 |
| 命令 ID 有权威注册表 `common/commands/constants.ts`（main 复用），但 **renderer 命令列表把同样的 ID 硬编码为字符串字面量，不 import 该表** | `main/commands/index.ts:1-5`；`renderer/src/commands/index.ts:61-681`（`'file.new-tab'`、`'edit.undo'`…） | 事实 | 高 | 主→渲染 `mt::execute-command-by-id` 的匹配靠人工，失配时静默失效 |
| renderer 同时用两套桥接：具名门面（`fileUtils/shell/clipboard/windowControl/ripgrep/uploader/fonts/i18nUtils/commandExists/path`）与裸 `window.electron.ipcRenderer.send/invoke/on`；两者都被大量使用 | grep `window.fileUtils.*`（editor.ts/project.ts/util/fileSystem.ts 等数十处）；grep `window.electron.ipcRenderer`（store/*.ts 上百处） | 事实 | 高 | 无规则决定新能力走哪套风格 |
| preload 因沙箱**无法复用 `common/`**，遂把 markdown 扩展名表和路径谓词重实现了一份；该列表现存 3 份 | `preload/index.ts:115-156` vs `common/filesystem/paths.ts:8-20,106-166` vs `BootInfo.MARKDOWN_INCLUSIONS` | 事实 | 高 | 未来任何"纯工具"若要 preload+renderer 共用，都会被复制 |
| `common/` 是"纯"与"Node 污染"的混合体：`encoding.ts`/`commands/constants.ts` 纯；`filesystem/index.ts` 与 `filesystem/paths.ts` 顶部 import `fs` | `common/filesystem/index.ts:1-4`、`paths.ts:1-3` | 事实 | 高 | CLAUDE.md 声称"main/preload/renderer 都可用"，实际 preload 全不可用、renderer 仅纯子集可用，且该划分无结构约束 |
| 共享类型普遍带 `[key:string]:unknown` 与 `unknown` 字段，处于迁移中 | `files.ts:41,81-91,105-110`、`preferences.ts:71`、`bufferedState.ts:8-24`、`menu.ts:17` | 事实 | 高 | 形状漂移目前是运行时契约 |
| 两个窗口 `webSecurity:false` | `main/config.ts:19,40` | 事实 | 高 | 沙箱+contextIsolation 是主要安全边界，同源策略被放宽 |
| 无任何 import-boundary 强制规则（无 `no-restricted-imports` / dependency-cruiser）；tsconfig 还留有一个 `main_renderer/* → src/main` 的废弃别名（无使用） | `eslint.config.js`（仅风格规则）；`tsconfig.base.json:32` | 事实 | 高 | 越界 import 只能靠 build 报错兜底 |
| 文档/配置滞后：`ARCHITECTURE.md` 描述的是 monorepo 前的 `src/{common,main,muya,renderer}` 布局，未提 `shared/`、preload、typed 契约；eslint 的 i18n 校验路径 `src/shared/i18n/locales/*.json` 不存在（实际在 `static/locales/*.json`） | `website/content/docs/dev/ARCHITECTURE.md:5-17`；`eslint.config.js:201` vs `static/locales/*.json` | 事实 | 高 | 该 i18n 规则实际是死规则 |
| 没有针对 IPC 契约本身的测试；单测通过 `vi.fn()` 模拟 `window.electron.ipcRenderer`，不校验 main 侧是否注册了同名 handler | `test/unit/specs/listen-for-main.spec.ts:24-36`；无 `ipc-contract.spec.ts` | 事实 | 高 | 契约断裂在 CI 上不可见 |

## 3. 当前摩擦（按"改一处要碰几处"排序）

1. **IPC 契约只约束调用方，不约束实现方（最重）。** 加一个通道要同步 `ipc.ts`（契约）、`preload/index.ts`（可选门面）、`main/ipc/*`（裸字符串 handler）三处，其中 main 侧不受类型系统保护。这是当前最大的扩展成本来源。
2. **`ipcMain` 一身二任，且契约被"内部事件"污染。** `window-*`、`watcher-*`、`screen-capture`、`app-create-editor-window` 等内部总线通道被写进 renderer 契约，使契约不再是 renderer↔main 的精确接口。后续任何人看 `ipc.ts` 都会高估 renderer 能发什么。
3. **命令 ID 双写且无校验。** renderer 命令表与 `common/commands/constants.ts` 各自维护同一份字符串，靠约定一致；一个 ID 拼错 = 菜单/快捷键静默无响应，类型系统帮不上忙。
4. **两套 renderer 桥接风格并存。** 门面 API（`fileUtils` 等）和裸 `ipcRenderer` 混用，新增能力时没有既定入口，接口风格会继续漂移。
5. **`common/` 的"可共享"边界名不副实。** 纯/Node 的划分隐式存在于文件内容里，导致 preload 复制逻辑、renderer 只能靠运气避开 `fs` 污染文件。

**好的一面（应稳住，不要推倒）：** `shared/` 纯类型 + barrel 是对的形状；preload 是单一、内聚、注释清楚的 ~300 行文件；`invoke<K>/send<K>/sendSync<K>/on<K>` 泛型包装是真正的"深接口"——四个函数换来整个通道面的调用方类型安全；handler 归属在各 owner 类（`windowManager._listenForIpcMain` 等）而非巨型文件，局部性不错。

## 4. 质量属性优先级

| 优先级 | 属性 | 目标/预算 | 现状证据 | 改善它的选项 | 可能回退的属性 | 验证方式 |
|---|---|---|---|---|---|---|
| 1 | 进程边界稳定性（契约可维护性） | 加/改通道只动一处、两侧都被类型检查 | main 侧零类型约束、约 200 扁平通道 | B（双侧类型化 + 拆内部总线） | 一次性迁移成本 | `typecheck` + 契约对称测试 |
| 2 | 可测试性 | 契约断裂在 CI 可见 | 无契约测试；单测只 mock 调用方 | B 的对称测试 | 增加 fixture 维护 | vitest 遍历契约 key 断言 handler 存在 |
| 3 | 安全性 | 沙箱仍是承重墙；契约不误导信任边界 | `webSecurity:false`；内部总线混入 renderer 契约 | B（契约精确化） | 无 | 安全审查；grep 守卫禁止契约通道被 `ipcMain.emit` |
| 4 | 可扩展性 | 新能力有唯一入口与既有风格 | 门面/裸桥双轨、命令 ID 双写 | B/C | 迁移面大小 | 新功能 PR 的 diff 面收敛 |

（性能非本轮主导：`sendSync('mt::boot-info')` 阻塞 preload 启动是既有取舍，不影响边界演进结论。）

## 5. 备选方案

**方案 A —— 维持现状，只把迁移做完。** 继续收紧 `unknown` payload、靠纪律与 code review 维持三处同步。成本最低，但契约断裂仍不可机检、内部总线污染仍在、命令 ID 双写仍在。适合团队无余力时作为过渡，不宜作为长期形态。

**方案 B —— 把契约做成双侧，并把内部总线拆出去（推荐）。** 核心改动只有两个"深接口"：
- 在 main 侧增加一个绑定 `IpcInvokeChannels`/`IpcSendChannels`/`IpcSyncChannels` 的 `registerIpcHandlers` 包装，让 `ipcMain.handle/on` 的通道名和 payload 也走类型检查；
- 用 `TypedEmitter` 泛化出一个 main 内部总线，把 `onInternalChannel`/`ipcMain.emit` 的 `window-*`/`watcher-*`/`screen-capture` 等迁过去，同时从 `IpcSendChannels` 删除这些内部通道，让 `ipcMain` 回归"只做 renderer↔main"。
随后补一个契约对称测试。改动量中等、可逆、不新增层级。

**方案 C —— 全面门面化。** 让 renderer 只接触 `fileUtils/shell/windowControl` 这类具名 API，把裸 `window.electron.ipcRenderer` 从约 150 个调用点移除，契约降为实现细节。调用点最干净，但迁移面最大、风险最高，且对只用一个通道的能力是过度抽象。建议**只有**当出现第二个 renderer 消费者（如独立 settings preload）或通道数突破 ~250 时才升级到 C。

## 6. 建议

选 **B**，理由：它直接命中最大的扩展成本（main 侧无类型约束 + 内部总线污染契约），且复用仓库里已经存在的两个好工具（`shared/types/ipc.ts` 的分类模型、`TypedEmitter`），不引入新框架或新抽象层。A 只是推迟问题；C 在当前规模下投入产出比不划算。

**分步（可逆）：**

1. **第一刀（最有价值的纵向切片）：** 为 `main/ipc/*` 的沙箱子集（`fs/paths/shell/window/cmd/i18n/fonts/bootInfo`）引入绑定契约的注册包装，把这些 handler 从裸字符串改为类型化注册。这个目录本来就内聚，改动面可控，立即可让 main 侧受 `typecheck` 保护。
2. **拆内部总线：** 新增 `mainInternalBus`（基于 `TypedEmitter`），迁移 `onInternalChannel` 调用点与 `ipcMain.emit` 派发点；把 `window-*`/`watcher-*`/`screen-capture`/`app-create-editor-window` 等从 `IpcSendChannels` 移除。契约从此只描述 renderer↔main。
3. **契约对称测试：** 一个 vitest 遍历 `IpcInvokeChannels`/`IpcSendChannels`/`IpcSyncChannels` 的 key，断言每个通道都有注册的 handler（mock electron `ipcMain`），并用反向遍历断言"没有未声明的裸字符串通道"。这把"单边契约"升级为可机检的不变量，而不要求所有 payload 先完全类型化。
4. **renderer 命令 ID 去双写：** 让 `renderer/src/commands/index.ts` import `COMMANDS`/`CommandId`，`id` 字段用 `CommandId` 类型，消灭主→渲染静默失配。
5. **payload 收紧继续按既有节奏推进**（迁移注释里"提交 5–8"的既定路线），新增通道一律强类型，旧通道"触及才收紧"。
6. **结构卫生（低优先）：** 把 `common/` 的纯/Node 划分显式化（如 `common/node` 或仅注释约定），让 preload/renderer 可安全共享纯子集；顺手删掉 `tsconfig.base.json` 的 `main_renderer` 别名、修正 eslint 的 i18n 死路径、更新 `ARCHITECTURE.md` 为 monorepo 布局与真实边界。

**暂不构建的：** 不要做通用 plugin/host 抽象；不要强行合并三套 bus 为一套统一事件系统（renderer bus 与 main bus 有本质差异——跨进程序列化 vs 进程内对象同一性，分开但各自类型化即可）；不要现在就上 zod 之类运行时 schema 校验——迁移注释表明已选择"类型级收紧"路线，运行时校验是更大的承诺。

**重开决策的信号：** 出现第二个 renderer/preload 消费者、通道数突破 ~250 且 `unknown` payload 占比上升、或发生一次因通道/命令 ID 失配导致的线上 bug——满足任一即重新评估升级到 C 或引入运行时校验。

## 7. 迁移与验证

- **类型：** `pnpm run typecheck`（vue-tsc）目前就能抓 preload/renderer 的通道名拼错；步骤 1 之后同样能抓 main 侧。
- **契约：** 新增对称测试（步骤 3）作为 CI 门禁；再加一条 grep/ESLint 守卫，禁止"renderer 契约通道被 `ipcMain.emit` 派发"，防止内部总线回潮。
- **行为：** 现有单测（`listen-for-main`、`buffer-store-durable`、`watcher-await-write-finish`、`keybinding-menu-rebuild`、`application-menu-state` 等）与 Playwright e2e 全程保持绿色；总线拆分后重点回归菜单/键盘路由。
- **回滚：** 每步独立提交，步骤 1/2 只改注册与派发机制、不改行为，可单独 revert；对称测试先行落地后，任何回退都会被它拦住。
- **完成判据：** `src/main` 中不再有裸字符串 `ipcMain.handle/on`（至少沙箱子集清零）；`ipc.ts` 中不再含 `ipcMain.emit` 派发的通道；契约对称测试在 CI 通过。

## 8. 待定问题（答案会改变建议）

- 迁移注释里的"提交 5–8 / Stage 3/4/5 / Commit 5d"是同一项既定迁移计划吗？是否有人正在推进，以及目标完成时点？（**推断**为同一计划，但**未知**其当前负责人与节奏——这决定步骤 1 是"接手推进"还是"另起一行"。）
- `webSecurity:false` 是仅为本地文件/图片加载的历史遗留，还是有不可移除的硬依赖？（**未知**——决定安全优先级是否需要单独立项。）
- 是否计划让 settings 窗口拥有独立 preload/渲染入口？（**未知**——若为是，方案 C 的触发条件提前出现。）

最便宜的学习方式：在 `ipc.ts` 或 CLAUDE.md 里补一句迁移计划的状态标注，并让步骤 1 的 PR 描述记录"双侧类型化"这一决策（可用 ADR 形式，见下方）。

**值得记入 ADR 的一项决策：** "IPC 契约从'单边、仅调用方类型化'改为'双侧类型化 + main 内部总线与 renderer 契约分离'"——它承载了未来架构评审的核心推理，符合 ADR 标准（见 `decision-record` 格式）。

[EVAL:evolve-software-architecture-loaded]
