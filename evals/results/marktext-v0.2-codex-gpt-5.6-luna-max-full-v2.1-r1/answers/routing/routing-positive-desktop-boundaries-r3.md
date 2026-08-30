## 结论

当前 `packages/desktop` 的进程边界“安全上成立，演进上不够硬”。

- `main` 对文件、窗口、菜单、watcher、持久化和 native 能力的所有权基本清晰。
- `preload` 已经成为有效的安全隔离层，sandbox 配置和 E2E 都能证明这一点。
- 但 shared IPC contract 主要约束 renderer/preload 调用端，不能约束 main 的实际注册；main 内部还把 `ipcMain` 当作进程内事件总线使用。
- `renderer` 同时依赖 IPC、mitt bus、`window.marktext`、`window.DIRNAME` 和多个全局 bridge，导致功能扩展容易变成跨多层修改。
- 因此当前适合继续开发“内置、可信、Electron 专属”的功能；若未来目标包括插件、不可信内容、Web 端或多种宿主，现有边界会明显拖慢演进。

本评估基于当前 HEAD `e52106fd`、工作区只读检查、仓库说明、实现、配置、测试和 Git 历史；未执行测试或构建。

## 当前边界

| 区域 | 当前职责 | 判断 |
|---|---|---|
| main | 文件 IO、watcher、窗口生命周期、菜单、偏好、更新器、spellchecker、持久化 | 所有权合理，但内部耦合较重 |
| preload | `contextBridge`、IPC 包装、path/file/search/uploader 等能力 | 安全边界有效，但能力面偏宽 |
| renderer | Vue UI、Pinia、每窗口编辑器和 Muya 状态 | 职责合理，但状态和 IPC 入口集中在大 store |
| shared | IPC 类型、文件/偏好/菜单类型、部分事件类型 | 名义上跨进程，实际上混入 Node runtime 和大量开放类型 |
| common | 被 main/preload/renderer 共同引用的工具 | 通过 alias/shim 维持兼容，未形成真正的纯代码边界 |

根说明将 `main/preload/renderer/shared` 描述为主要分层：[CLAUDE.md](/evaluation-path/treatment/CLAUDE.md:76)。实际 Electron 配置中两个窗口均为 `contextIsolation: true`、`sandbox: true`、`nodeIntegration: false`：[config.ts](/evaluation-path/treatment/packages/desktop/src/main/config.ts:8)。

## 做得较好的部分

### 1. 安全进程边界已经是有效资产

renderer 不能直接访问 Node/Electron；E2E 明确检查了 `require`、`global`、`Buffer` 不存在，并验证 contextBridge 可用：[context-isolation.spec.ts](/evaluation-path/treatment/packages/desktop/test/e2e/context-isolation.spec.ts:24)。

这不是偶然结构，而是 `fa84fc00` 的有意迁移结果：renderer 的文件、ripgrep、上传、path 等能力被移到 main/preload。这个方向应继续保留，不建议为了简化调用重新开放 Node integration。

### 2. main/renderer 的主要数据所有权基本正确

文件加载发生在 main，结果通过 `mt::open-new-tab` 发送给 renderer；watcher 和窗口文件列表也由 main 管理：[ARCHITECTURE.md](/evaluation-path/treatment/packages/website/content/docs/dev/ARCHITECTURE.md:57)。

crash-recovery buffer 也由 main 原子持久化，renderer 只发送快照：[editorBufferStore/index.ts](/evaluation-path/treatment/packages/desktop/src/main/editorBufferStore/index.ts:187)。

### 3. Muya 已经有较好的包级拆分方向

monorepo 中 `packages/muya` 有自己的入口、测试、类型检查和循环依赖检查，renderer 当前主要消费 `@muyajs/core`：[packages/muya/CLAUDE.md](/evaluation-path/treatment/packages/muya/CLAUDE.md:5)。

这说明“可独立演进的核心包”是可行路径。不过 desktop 为了切断类型图，目前仍使用宽泛的手写声明，`Muya` 大量成员是 `any`：[muya-core.d.ts](/evaluation-path/treatment/packages/desktop/src/types/muya-core.d.ts:45)。

## 主要扩展性摩擦

### 1. IPC contract 还不是完整的双端合同

合同文件自己说明参数和返回值仍大量使用 `unknown`：[ipc.ts](/evaluation-path/treatment/packages/desktop/src/shared/types/ipc.ts:10)。

更重要的是：

- preload 调用通过泛型包装器获得类型；
- main 仍在 `App`、`AppMenu`、`WindowManager`、`Preferences`、`DataCenter`、`menu/actions/file.ts` 等位置直接调用 `ipcMain.on/handle`；
- 这些 handler 的 channel 字符串并未由同一个注册器绑定到 contract。

因此当前类型系统更像“调用端护栏”，不是运行时协议边界。

已有可观测漂移：contract 中仍有 `mt::file-saved`，实际代码使用的是 `mt::tab-saved`；静态检索只在 contract 中发现前者，而后者由 main 发送、renderer 接收：[ipc.ts](/evaluation-path/treatment/packages/desktop/src/shared/types/ipc.ts:241)、[editor.ts](/evaluation-path/treatment/packages/desktop/src/renderer/src/store/editor.ts:603)。

另外，`IpcSendChannels` 同时包含 renderer→main channel 和只在 main 内部使用的 `broadcast-*`、`watcher-*`、`window-*` channel：[ipc.ts](/evaluation-path/treatment/packages/desktop/src/shared/types/ipc.ts:92)。这会把两种完全不同的协议混在一个命名空间里。

### 2. `ipcMain` 同时承担外部 IPC 和内部事件总线

内部总线通过 `ipcMain.emit(...)` 实现，订阅端只能在一个 helper 中进行类型转换：[internalIpc.ts](/evaluation-path/treatment/packages/desktop/src/main/utils/internalIpc.ts:4)。

例如 EditorWindow 直接 emit watcher、window、menu 事件：[editor.ts](/evaluation-path/treatment/packages/desktop/src/main/windows/editor.ts:396)；WindowManager 再通过字符串注册这些内部事件：[windowManager.ts](/evaluation-path/treatment/packages/desktop/src/main/app/windowManager.ts:421)。

这会带来：

- channel 名称冲突；
- 监听注册顺序和构造函数副作用；
- 难以静态追踪“谁拥有事件、谁负责清理”；
- main 内部代码被迫知道窗口 ID、BrowserWindow 形态和全局事件名。

### 3. shared/common 不是严格的可复用边界

`shared/types` 的 barrel export 包含 `TypedEmitter`，而它运行时导入 `node:events`：[typedEmitter.ts](/evaluation-path/treatment/packages/desktop/src/shared/types/typedEmitter.ts:1)、[types/index.ts](/evaluation-path/treatment/packages/desktop/src/shared/types/index.ts:1)。

`common/filesystem` 直接依赖 `fs`、`fs/promises`、`path`：[filesystem/index.ts](/evaluation-path/treatment/packages/desktop/src/common/filesystem/index.ts:1)。renderer 之所以能复用部分 `common`，依赖的是 Vite 将 `path` 替换为 `pathe` 的构建技巧：[electron.vite.config.ts](/evaluation-path/treatment/packages/desktop/electron.vite.config.ts:64)。

这对当前 Electron renderer 可行，但会阻碍未来的 Web renderer、worker、插件宿主或独立测试环境。

### 4. renderer 存在多条状态和事件通道

启动状态先从 URL 解析，再写入 `window.marktext`：[bootstrap.ts](/evaluation-path/treatment/packages/desktop/src/renderer/src/bootstrap.ts:101)。

随后页面又从 `window.marktext.initialState` 初始化 Pinia，并注册大量 IPC listener：[app.vue](/evaluation-path/treatment/packages/desktop/src/renderer/src/pages/app.vue:158)。

同时存在：

- `window.electron.ipcRenderer`
- renderer 内部 mitt bus
- `window.marktext`
- `window.DIRNAME`
- `window.path`、`window.fileUtils`、`window.ripgrep` 等 sibling globals

例如编辑器状态同时发送 IPC、更新 `window.DIRNAME`、监听多个 main event。`editor.ts` 当前约 2100 行，是明显的变更热点。

这也是为什么单测需要在模块导入前通过 `vi.hoisted` 手动伪造 `window.path`、`window.electron` 和 `window.marktext`：[listen-for-main.spec.ts](/evaluation-path/treatment/packages/desktop/test/unit/specs/listen-for-main.spec.ts:4)。

### 5. preload 能力面足够宽，暂时适合可信内置 UI，不适合未来插件

preload 暴露的不只是少量业务 API，还包括通用 IPC、文件复制/移动/删除/读写、shell、uploader、ripgrep、path 和 process shim：[preload/index.ts](/evaluation-path/treatment/packages/desktop/src/preload/index.ts:287)。

文件 API 甚至接受任意路径字符串：[fs.ts](/evaluation-path/treatment/packages/desktop/src/main/ipc/fs.ts:40)；上传器还可以执行 PicGo 或用户配置的 CLI：[uploader.ts](/evaluation-path/treatment/packages/desktop/src/main/ipc/uploader.ts:175)。

这不是说当前内置 renderer 已存在直接漏洞，而是说明如果未来加载不可信 markdown、插件或远程 UI，必须先做 capability 分层。

### 6. 文档已有边界漂移

根 `CLAUDE.md` 的架构段仍写着 editor/preferences 使用 `contextIsolation: false` 和 `nodeIntegration: true`：[CLAUDE.md](/evaluation-path/treatment/CLAUDE.md:241)。

这与实际配置、IPC 文档和 E2E 相反。它不会立即改变运行时，但会直接误导后续维护者，是扩展性风险的一部分。

## Git 历史说明了什么

历史呈现出“有计划的边界迁移，但迁移尚未收口”：

- `fa84fc00`：renderer sandbox 化；
- `ab88a70a`：建立 shared types 和 IPC contract；
- `b9409bc9`：preload contextBridge TypeScript 化；
- `0eb1eb24`：收紧部分 IPC 类型；
- `565bfcdc`：迁移到 pnpm monorepo。

近期修复又持续集中在跨边界热点：

- `c907b29c`：renderer flush 与 main save 的时序；
- `ac273f46`：main crash-recovery buffer 持久化；
- `6c23b1ba`：main 原子保存；
- `af6d792f`：renderer 过滤内容未变化的 watcher 事件。

这说明问题不是简单的“目录划分不好”，而是文件、watcher、编辑器状态、菜单和窗口生命周期确实形成了复杂的领域交互。因此不建议立即引入新的 IPC 框架或大规模拆进程。

## 方案比较

| 方案 | 收益 | 代价 | 判断 |
|---|---|---|---|
| 保持现状，只补文档和 `unknown` | 成本最低 | 内部总线、双事件轨道和大 store 仍在 | 不足以解决长期问题 |
| 保留三进程，增量建立 typed protocol + capability facade | 改善变更局部性，兼容现有运行时，可逐步回滚 | 需要维护 facade 和迁移期双轨 | 推荐 |
| 抽取多个 workspace package 或新增服务进程 | 未来可支持 Web、插件、worker | 迁移面和运行时复杂度都很高 | 暂缓，等产品目标明确 |

## 推荐方向

### 第一阶段：先收紧“协议”和“内部事件”

1. 将 shared 拆成纯数据合同和 main-only runtime 两部分：

   - `shared/contracts`：只放可序列化 DTO、IPC channel、错误结构；
   - `main/internal`：放 `TypedEmitter`、BrowserWindow 相关事件和 main-only 类型。

2. 将真实 renderer↔main IPC 与 main 内部事件使用不同命名空间和不同类型表。

3. 添加类型化注册 helper，让 main handler 的 channel、参数和返回值也绑定到 contract，而不是只让 preload 调用端有类型。

4. 把所有新 renderer 功能限制为调用领域 facade，例如 `window.documents`、`window.search`、`window.windowControl`；暂时保留 `window.electron.ipcRenderer` 作为迁移兼容层。

### 第二阶段：以 ripgrep 作为低风险试点

ripgrep 已经有独立 preload facade、流式事件和真实 E2E：[ripgrep-search.spec.ts](/evaluation-path/treatment/packages/desktop/test/e2e/ripgrep-search.spec.ts:6)。

可以先把：

- request；
- match/progress/done/error/cancelled envelope；
- error shape；
- search lifecycle；

全部从 `unknown` 收紧，并让 renderer 只依赖 `SearchService` 接口。验证通过后，再迁移文件 open/save/watch 这条最高价值链路。

### 第三阶段：处理状态和内部总线

逐步把：

- `window.marktext`；
- `window.DIRNAME`；
- URL 参数初始化；
- Pinia 初始化；
- renderer mitt bus；

收束为一个明确的 `RendererSession/Bootstrap` 对象和按领域划分的事件订阅。

main 内部则用独立的 typed domain event emitter 替代 `ipcMain.emit`。不要一次性改名所有旧 channel；可以先让旧 channel 适配到新服务，降低行为回归风险。

### 第四阶段：补齐架构护栏

建议增加：

- IPC contract 的序列化、错误和 handler 注册测试；
- sender window identity 测试，避免同时接受未经验证的 `windowId`；
- renderer reload、renderer crash、watcher race、save/reopen 的 E2E；
- packaged app 在 Windows/macOS 上的最小 smoke test；
- desktop 的依赖方向或循环依赖检查。当前只有 `packages/muya` 配置了 Madge 检查，desktop 没有：[muya-lint workflow](/evaluation-path/treatment/.github/workflows/muya-circular.yml:18)。

现有 CI 有 50 个 desktop unit spec 和 59 个 E2E spec，并执行 lint/typecheck；但 E2E 只在 Ubuntu 执行，而多平台 workflow 主要负责构建：[e2e.yml](/evaluation-path/treatment/.github/workflows/e2e.yml:15)、[build.yml](/evaluation-path/treatment/.github/workflows/build.yml:20)。

## 最终判断

建议保留当前 Electron 三进程拓扑和 sandbox 安全模型，不做大拆迁；重点把“目录边界”升级成真正的：

1. 类型化双端协议；
2. 领域级 preload capability；
3. 独立的 main 内部事件模型；
4. 纯类型 shared 层；
5. 明确的 renderer session/state 初始化。

如果未来明确要支持不可信插件、Web 宿主或多进程协作，再进一步抽取 `desktop-contracts`、`platform` 等 workspace package。当前最值得投入的是把已有边界收口，而不是增加新的运行时边界。

[EVAL:evolve-software-architecture-loaded]
