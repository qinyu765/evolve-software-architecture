评估完成。以下是基于代码、配置、测试与历史记录的证据式架构评估，只给建议，未改动任何文件。

## 1. 范围与置信度

评估对象是 `packages/desktop` 的 main / preload / renderer / shared 四个进程边界，以及它们在根 monorepo 中如何支撑未来的功能扩展。

- **仓库类型**：Electron 桌面应用（pnpm monorepo）。多路信号一致：`electron.vite.config.ts` 的三进程构建、`electron-builder.yml`、`package.json` 的 `main: ./out/main/index.js`、`BrowserWindow/ipcMain/contextBridge` 的使用、以及 CLAUDE.md 描述的三进程模型。**置信度：高**。
- **适配器说明**：技能库中只有 Desktop/Tauri 适配器。我借用了它的通用桌面关切（IPC 契约、生命周期、状态归属、跨进程测试），但**不套用** Tauri 专有的 Rust/capability 假设——本项目是 Electron + TypeScript。

## 2. 观察到的关键事实

| 声明 | 证据 | 类型 | 置信度 | 后果 |
| --- | --- | --- | --- | --- |
| 渲染器是真正沙箱化的 | `preload/index.ts:1-7`、`test/e2e/context-isolation.spec.ts`（自述为"canary"）断言 `contextIsolation:true`/`sandbox:true`/`nodeIntegration:false` | 事实 | 高 | 所有 Node 能力必须走 IPC，这是不可回退的安全边界 |
| IPC 契约在 `shared/types/ipc.ts`，四类频道名字强类型、**载荷故意放宽为 `unknown`** | `ipc.ts:1-18,40-289`，注释明说"迁移中，5–8 号 commit 逐步收紧" | 事实 | 高 | 契约目前是"频道名注册表"而非"载荷 schema"，改载荷要手改多处 |
| preload 暴露两套面：精选 API 对象 + **原始 `window.electron.ipcRenderer` 透传** | `preload/index.ts:38-68,229-246` | 事实 | 高 | 领域频道几乎全部走原始透传（见下），新代码有两套可选的调用方式 |
| 渲染器领域频道大量走原始 `ipcRenderer.send/on/invoke` | `store/editor.ts`（77 处）、`store/preferences.ts`、`store/layout.ts` 等，共 50 文件 269 处 bridge 引用 | 事实 | 高 | 领域 IPC 的实际"接口"是原始频道名 + 约定形状，未收敛进门面对象 |
| main 侧 handler 注册分**两层**：新沙箱原语集中在 `main/ipc/*`，旧领域 handler 散落各处 | `main/index.ts:83` 调 `registerSandboxIpcHandlers()`；`main/app/index.ts:658-850`、`main/menu/actions/file.ts`（模块顶层 `ipcMain.on`）等 | 事实 | 高 | 没有统一注册点，注册时机/幂等性不透明，存在重复注册隐患 |
| 存在**第三套**进程内命令分发：`CommandManager` 单例 | `main/commands/index.ts`，命令词汇在 `common/commands/constants.ts`（`edit.copy`、`file.save`…） | 事实 | 高 | 同一个"保存"概念同时是 `file.save` 命令与 `mt::response-file-save` 频道，无单一映射表 |
| `ipcMain.emit` 被当作**进程内事件总线**复用 | `main/utils/internalIpc.ts`、`main/app/index.ts:672,708…`、`editor.ts:396,415`（`watcher-*`、`screen-capture`、`app-open-file-by-id`） | 事实 | 高 | 内部事件与渲染器频道共用命名空间，`onInternalChannel` 靠类型断言遮丑 |
| 启动信息走**两条未打类型的通道**：URL query 参数 + `window.marktext` 遗留全局 | `main/windows/base.ts:110-140`（`udp/debug/wid/type/cff/cfs/hsb/theme/tbs`）；`renderer/bootstrap.ts:26-55,101-121` 解析并组装 `window.marktext` | 事实 | 高 | query 参数名没有共享类型，改名只会在运行时炸；`window.marktext` 仍有约 15 处读取（`env.windowId`、`initialState`、`paths.userDataPath` 等） |
| `common/` 是**纯度混杂**的一层 | `common/filesystem/*` import `fs`/`path`/`minimatch`（Node 专属）；渲染器只 import `common/encoding`、`common/keybinding`、`common/envPaths` | 事实 | 高 | CLAUDE.md 说 common"可用作 main/preload/renderer"，但 `common/filesystem` 在渲染器里不可用——分类名不准确 |
| `isSamePathSync` 有**三份实现** | `common/filesystem/paths.ts:135`（fs inode）、`preload/index.ts:140-156`（pathe + 同步 IPC 兜底）、`main/ipc/paths.ts`（转回 common） | 事实 | 高 | 知识重复，三处需同步维护 |
| 引擎迁移（muyajs→@muyajs/core）进行中，接近收尾但未结束 | `editor.vue` 等 import `@muyajs/core`；`muya` alias 与 `@marktext/muyajs` workspace 依赖仍在构建配置里；`test/PARITY_SCOREBOARD.md` 显示 14/15 缺口已修、PG14 仍 xfail | 事实 | 高 | 桌面源码已无活的 `from 'muya/…'` import（grep 零命中），但旧引擎仍在解析路径上 |
| 无 ADR；架构文档在 website 包内，但内容已跟上新契约 | 仓库无 `*ADR*`；`packages/website/content/docs/dev/IPC.md`、`TYPESCRIPT.md` 已描述 `shared/types/ipc.ts` 与 preload 桥 | 事实 | 高 | 文档当前准确，但不在 desktop 的构建/测试回路内，漂移无守卫 |
| 测试：单测 50 个（jsdom，经 `main_renderer` alias 直连 main）；E2E 约 70 个（真实启动 Electron） | `vitest.config.ts`、`test/unit/specs/*`、`test/e2e/*`、`helpers.ts` 用 `_electron.launch` | 事实 | 高 | 沙箱边界有 e2e canary，但**没有**运行时契约测试去断言"ipc.ts 声明的每个频道都有已注册 handler" |

## 3. 当前摩擦（改变会放大的地方）

- **F1 三套并行分发词汇**：功能开发者要在 `CommandManager`（菜单/快捷键）、`ipcMain.on/handle`（渲染器↔main）、`ipcMain.emit`（main 内部）之间选择。同一动作（保存）在三个体系里有三个名字，没有一张把 `CommandId ↔ IPC 频道 ↔ handler` 连起来的表。
- **F2 两层 handler 注册、生命周期不同**：`main/ipc/*` 启动时集中注册；旧领域 handler 靠 import 副作用（`menu/actions/file.ts` 顶层 `ipcMain.on`）或 `App._listenForIpcMain()` 注册。Electron 的 `ipcMain.on` 会叠加监听器、`ipcMain.handle` 重复会抛错——窗口 reload/重开时这是潜在的双注册隐患。
- **F3 `unknown` 载荷让强类型在最有价值处失效**：`mt::save-tabs`、`mt::response-export`、`mt::update-file`、`mt::load-state` 都以 `unknown`/开放结构跨边界。`store/editor.ts` 是最大热点（77 处 bridge 引用），按约定读写这些形状。改一个载荷要手改 handler + 共享类型 + store 三四处，靠约定对齐。
- **F4 `window.marktext` + URL query 是第二条未类型化的启动契约**：`windowId`（约 10 处窗口级 send 需要）、`initialState`、`paths.userDataPath` 走 query 参数和一个 `[key: string]: unknown` 全局。参数名只写在 `bootstrap.ts` 一侧，`main/windows/base.ts` 是另一侧，改一个名字运行时才暴露。
- **F5 `ipcMain.emit` 把 IPC 与进程内事件混在一起**：`watcher-*`、`screen-capture` 等名字既在 `IpcSendChannels`（渲染器侧）里，又被内部 emit。两侧共用一个命名空间，未来对任一侧收紧类型会悄悄影响另一侧。
- **F6 引擎替换仍未封口**：`muya` alias、`@marktext/muyajs` 依赖、`packages/muyajs` 仍在构建配置与依赖图里，`types/muya.d.ts` 与 `types/muya-core.d.ts` 双份 ambient shim 标记着这条缝。新代码仍可能误 import 旧引擎。
- **F7 契约文档在 desktop 包之外**：IPC/TypeScript 文档在 website 包（CLAUDE.md 明说"今天不进 desktop CI"）。目前准确，但没有机制防漂移。

## 4. 质量属性优先级

就"main/preload/renderer/shared 边界的未来可扩展性"而言，起支配作用的属性按序为：

1. **可维护性 / 局部性（最高）**——目标：任何单点特性（如"新增 save-as 选项"）只碰 1 个频道定义 + 1 个 handler + 1 个调用点，而不是横跨 3 个目录 4 个文件。当前证据：F1–F4 的改动放大是主要成本。
2. **进程边界稳定性 / 安全（次之）**——沙箱是产品的安全姿态，不可回退。强类型契约 + `context-isolation.spec.ts` canary 是现有守卫。**取舍**：所有能力走 IPC 换来往返开销与样板代码，这是沙箱的代价，不能为了省事给渲染器开 Node 后门。
3. **可测试性（第三）**——契约目前靠编译期泛型检查 + e2e canary，但缺少"每个声明的频道都有运行时 handler"的契约测试；这是性价比最高的缺口。
4. **可移植性 / 生命周期正确性**——macOS/Windows/Linux 菜单与快捷键差异（native-keymap）、单实例、updater 天然是多变点。**取舍**：在只有单一产品、没有第二个 provider/运行时之前，为 OS 差异建泛化抽象属于过度设计（对应技能库的陷阱"在出现两个真实变体之前别建通用抽象"）。

未列为支配属性：性能（无证据表明边界是瓶颈）、成本（主要是重构工时）。

## 5. 选项

**选项 A —— 维持现状，只把已开始的迁移做完**：继续把 `ipc.ts`/`files.ts` 里的 `unknown` 收紧、退休 `window.marktext` 与旧引擎、补一个运行时契约测试。成本最低、风险最小，但**不去除**两层 handler 注册和 `ipcMain.emit` 内部总线这两个结构性摩擦点。

**选项 B —— 收敛为"一个类型化 IPC 注册表 + 一个类型化启动契约"，并把内部总线从 `ipcMain` 里拆出来**：
- 所有 `ipcMain.on/handle` 并入 `main/ipc/*` 的集中注册模式（单一 `registerAllIpcHandlers()`）；
- `ipcMain.emit`/`onInternalChannel` 换成真正的类型化进程内 emitter（`BaseWindow` 已经在用 `TypedEmitter`，可复用），内部事件名从 `IpcSendChannels` 中移除；
- URL query 启动改为共享的 `BootstrapPayload` 类型（或并入 `mt::boot-info`/`mt::bootstrap-editor` 模式），随后删掉 `window.marktext`；
- 领域频道逐个流（save/export/tab 等）从原始 `ipcRenderer.send('mt::…')` 收敛进小型类型化门面（像现有 `shell`/`clipboard` 门面那样），原始透传作为迁移期逃生口保留但不再新增调用。
- 边界与所有权清晰，行为不变，分步可回滚。

**选项 C —— 引入正式的分层/适配器抽象**（渲染器需求与 main 能力之间的"服务/端口"层、按 OS 适配器、DI 容器等）。对一个单一桌面产品、没有第二个 provider/变体、没有插件 API 的现状，这是过度设计。**仅当**出现真正的第二个运行时（如 Tauri/移动端移植）或第三方插件 API 时才值得，且到那时应以"真实变体"为准再抽象。

## 6. 建议

**选 B，并把 A 的"完成迁移"作为第一批垂直切片。** 理由：B 直接消除 F1/F2/F5/F4 这些会放大改动成本的结构问题，同时保持行为不变、可逐步回滚；C 在目前证据下属于提前投资。

**明确不做的**：不建通用 native 抽象、不引入 DI 容器、不预先设计频道版本号/序列化层——在出现真实第二消费者或 provider 之前，这些都是过度抽象。

## 7. 迁移与验证

按此顺序（每步行为不变、可回滚）：

1. **先补运行时契约测试**（最便宜）：把 handler 注册收进注册表后，用一个 vitest 断言"`ipc.ts` 声明的每个 invoke/send/sync 频道都有对应注册"。这会立即暴露"声明了但没注册/注册了但没声明"的漂移。目前的 `context-isolation.spec.ts` 继续作为安全 canary。
2. **集中 handler 注册**：把 `App._listenForIpcMain()` 与 `menu/actions/file.ts` 顶层注册搬进命名的 `register*Handlers()` 模块，复用现有 `main/ipc/*` 模式。这消除 import 副作用与双注册隐患，并提供测试缝。
3. **拆出内部总线**：用类型化 emitter 替代 `ipcMain.emit`，内部事件名移出 `IpcSendChannels`。
4. **逐流收敛 preload 两面**：先处理 `store/editor.ts` 的 save/export/tab 频道，改成类型化门面；`window.electron.ipcRenderer` 保留为逃生口，但停止新增原始调用。
5. **按流收紧载荷类型**：沿用 `ipc.ts` 注释里已规划的"5–8 号 commit"收紧，但改成**按端到端流**（如保存流）推进，每收紧一次都有对应 e2e 保行为。
6. **替换 URL query 启动**：要么把 6 个设置项放进类型化对象经 `mt::boot-info`/`mt::bootstrap-editor` 传递，要么至少把 `UrlArgs`/`_buildUrlWithSettings` 的参数名抽到共享的 `shared/types/bootstrap.ts`，两侧共用。**退出标准**：`grep -rn "window.marktext"` 归零。
7. **退休旧引擎**：关闭 PG14 后移除 `muya` alias、`@marktext/muyajs` 依赖与 `muya.d.ts` shim。**退出标准**：`grep -rn "from 'muya"` 保持零命中（现在已是零）+ `@marktext/muyajs` 从 package.json 移除。

**每步验证**：运行时契约测试（未注册即失败）；`context-isolation.spec.ts` 常绿；约 70 个真实启动 Electron 的 e2e 在每步后保持通过；`vue-tsc --noEmit` 在类型收紧时捕获载荷不匹配；`pnpm run lint`。

## 8. 待决问题（答案会改变建议）

- 是否有**插件/扩展 API** 的路线图？若有，建议会向选项 C（真正的 port 层）倾斜。
- 是否有**第二个运行时**（Tauri/移动端/Web）的规划？若有，应更早建适配器缝。
- `@muyajs/core` 会继续是 workspace 内引擎，还是会**对外发布/被外部消费**？这决定要不要把 `INTERFACE.md` 描述为稳定的引擎↔渲染器接口。
- 多窗口并发模型：现在是 `windowId` 临时寻址，将来是否会引入**会话/上下文对象**？这决定启动契约是否应该携带类型化的窗口上下文。

**结论一句话**：边界的安全基础（沙箱 + 类型化频道名 + e2e canary）已经打好了，可扩展性的主要成本不在"缺少边界"，而在"边界有太多条、且载荷类型还没收紧"——收敛注册与启动契约、逐流收紧类型，比引入新抽象更能降低未来的改动成本。

[EVAL:evolve-software-architecture-loaded]
