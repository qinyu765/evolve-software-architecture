## 结论

[推断] 当前 `packages/desktop` 的“进程安全边界”较强，但“模块职责边界”和“跨进程契约边界”仍偏弱：

- `main / preload / renderer` 的物理分层清晰，沙箱配置真实有效。
- `main` 内部仍是集中式应用控制器、窗口管理器和多套事件注册机制。
- `preload` 已是安全桥，但同时暴露了较宽的通用 IPC 和多个全局 API。
- `shared` 更像 TypeScript 类型集中区，不是严格的可序列化传输协议。
- renderer 的 Pinia store 和组件直接承担大量 IPC、文件系统、窗口与编辑器集成逻辑。

因此，未来继续增加普通编辑功能尚可；若扩展插件、协作编辑、多个编辑引擎、更多 OS 能力或替换前端，变更成本会明显上升。建议保留三进程模型，采用渐进式 capability facade 和严格 DTO 契约，不建议当前进行一次性“大重构”。

## 证据与边界判断

| 区域 | 当前事实 | 扩展性判断 |
|---|---|---|
| main | 启动入口先注册沙箱 IPC，再构造 `Accessor` 和 `App`。[main/index.ts](/evaluation-path/treatment/packages/desktop/src/main/index.ts:82) `Accessor` 持有 preferences、dataCenter、buffer store、menu、windowManager 等全部核心对象。[accessor.ts](/evaluation-path/treatment/packages/desktop/src/main/app/accessor.ts:12) | [推断] 这是有效的 composition root，但 `App`、`WindowManager` 和 `Accessor` 已成为高耦合中心。新能力通常会同时触及生命周期、窗口、菜单、IPC 和存储。 |
| main 内部通信 | 除 `main/ipc/*` 外，`App`、菜单、preferences、windowManager 等模块自行注册 IPC；内部还通过 `ipcMain.emit` 伪造进程内事件。[App](/evaluation-path/treatment/packages/desktop/src/main/app/index.ts:658) [internalIpc.ts](/evaluation-path/treatment/packages/desktop/src/main/utils/internalIpc.ts:4) | [推断] `main/ipc` 并不是完整的外部适配层；通道所有权和注册时机分散，测试、重载和未来拆分都会受影响。 |
| preload | 运行在 sandbox preload，只允许有限的 Electron 能力；提供泛化的 `send/invoke/on`，并暴露 `electron`、`fileUtils`、`path`、`ripgrep`、`uploader` 等多个全局面。[preload/index.ts](/evaluation-path/treatment/packages/desktop/src/preload/index.ts:1) [preload/index.ts](/evaluation-path/treatment/packages/desktop/src/preload/index.ts:286) | [事实] 安全边界成立；[推断] API 边界较宽，renderer 仍然了解大量 Electron 语义。它更像“受控的通用 RPC 层”，还不是稳定的领域能力层。 |
| renderer | editor store 直接操作 `window.fileUtils`、`window.path`、`window.electron.ipcRenderer`，并同时处理 tab、保存、菜单同步、编辑器引擎和文件状态。[editor.ts](/evaluation-path/treatment/packages/desktop/src/renderer/src/store/editor.ts:503) | [推断] renderer 的 UI、应用状态和平台适配尚未形成稳定内外层；大型 store 和 `editor.vue` 是主要变更热点。 |
| shared | IPC 文件明确允许大量 `unknown`，并说明类型正在迁移。[ipc.ts](/evaluation-path/treatment/packages/desktop/src/shared/types/ipc.ts:1) 文件类型也使用开放索引和 `unknown`。[files.ts](/evaluation-path/treatment/packages/desktop/src/shared/types/files.ts:1) | [推断] shared 目前主要提供编译期提示，没有形成可验证的运行时协议。`FileNotification.action` 甚至是函数，不能作为普通 structured-clone DTO。[files.ts](/evaluation-path/treatment/packages/desktop/src/shared/types/files.ts:97) |
| 测试边界 | 有可靠的沙箱 canary，验证 `require/global/Buffer` 不泄漏。[context-isolation.spec.ts](/evaluation-path/treatment/packages/desktop/test/e2e/context-isolation.spec.ts:24) 但 Vitest 主要是 jsdom 单测。[vitest.config.ts](/evaluation-path/treatment/packages/desktop/vitest.config.ts:8) | [推断] 行为回归覆盖较好，preload facade、IPC 序列化和主处理器之间的契约测试不足。多份单测通过 `main_renderer` alias 直接导入 main 实现，说明测试常绕过公开边界。 |

### 契约漂移已有具体迹象

[事实] shared 契约声明 `mt::shell::open-external` 返回 `void`，但 main handler 实际返回 `true/false`。[ipc.ts](/evaluation-path/treatment/packages/desktop/src/shared/types/ipc.ts:72) [shell.ts](/evaluation-path/treatment/packages/desktop/src/main/ipc/shell.ts:6)

[事实] `mt::window-active-status` 契约声明 payload 是 `boolean`，main 实际发送 `{ status: boolean }`，renderer 再通过 `unknown` 自行收窄。[ipc.ts](/evaluation-path/treatment/packages/desktop/src/shared/types/ipc.ts:282) [editor.ts](/evaluation-path/treatment/packages/desktop/src/main/windows/editor.ts:235) [store/index.ts](/evaluation-path/treatment/packages/desktop/src/renderer/src/store/index.ts:24)

这说明类型检查覆盖了 preload 调用点，但不能自动约束所有 `webContents.send` 和 `ipcMain.handle` 实现。

## Monorepo 与 Git 历史

[事实] 根仓库已经具备合理的 workspace 基础：根脚本代理 desktop，`packages/*` 是 workspace，Muya 有独立工具链。[package.json](/evaluation-path/treatment/package.json:12) [pnpm-workspace.yaml](/evaluation-path/treatment/pnpm-workspace.yaml:1)

但有三项结构性风险：

- desktop 同时声明 `@marktext/muyajs` 和 `@muyajs/core`，构建配置仍保留 `muya -> ../muyajs` alias。[package.json](/evaluation-path/treatment/packages/desktop/package.json:55) [electron.vite.config.ts](/evaluation-path/treatment/packages/desktop/electron.vite.config.ts:34)
- `@muyajs/core` 的 desktop 类型通过手写 shim 和 `any` 隔离依赖图。[muya-core.d.ts](/evaluation-path/treatment/packages/desktop/src/types/muya-core.d.ts:1)
- desktop CI 对 `packages/muya/**` 使用 `paths-ignore`，Muya 只在自身 workflow 检查；跨包消费者回归不一定同步执行。[test.yml](/evaluation-path/treatment/.github/workflows/test.yml:6) [muya-circular.yml](/evaluation-path/treatment/.github/workflows/muya-circular.yml:24)

Git 历史也显示边界仍处于演进期：

- `fa84fc00`：sandbox/contextBridge 安全迁移，建立了当前最重要的进程边界。
- `565bfcdc`：pnpm monorepo 拆分，主要是物理和工具链边界。
- `0d866412`、`0706ee59`：Muya TS rewrite 和 desktop consumer 迁移。
- `2c5353d2`：一次跨 main、renderer、shared、测试的大范围类型收紧。
- 近 100 个提交中，`editor.vue` 和 `store/editor.ts` 仍是明显热点，说明 renderer 集成层的变更局部性较差。

## 方案比较

| 方案 | 优点 | 风险 | 判断 |
|---|---|---|---|
| A. 保持现状，只补文档和少量类型 | 成本最低，短期稳定 | 不解决 App、WindowManager、renderer 直连和事件总线耦合 | 可作为短期保守方案，但不足以支撑明显扩展 |
| B. 保留三进程，逐步引入领域能力 facade | 不破坏 sandbox；可按文件、窗口、搜索、偏好逐条迁移；容易回滚 | 需要一段时间维护旧 bridge 和新 facade 并存 | 推荐 |
| C. 一次性引入完整 clean architecture / 多个 domain package | 理论边界最清晰 | 迁移面巨大，容易重复抽象；当前 Muya 和桌面边界仍在变化 | 暂不推荐，除非明确进入协作、插件或多后端阶段 |

## 推荐方向

[约束] 保留当前 `contextIsolation: true`、`sandbox: true`、`nodeIntegration: false` 配置。[config.ts](/evaluation-path/treatment/packages/desktop/src/main/config.ts:8)

建议逐步形成以下所有权：

- `main`：文件系统、OS、窗口、watcher、持久化、更新和原生能力。
- `preload`：只暴露命名明确的能力接口，不让业务模块依赖通用 IPC 细节。
- `renderer`：UI、编辑会话状态、选择区间、焦点、临时交互状态。
- `shared`：只放 JSON/structured-clone 安全的 DTO、错误结构和通道契约；不放函数、Electron 对象或 Node runtime helper。
- `Muya`：编辑器引擎能力和引擎 API；desktop 通过明确适配层消费。

第一条垂直迁移建议选择“文件打开/保存 + watcher 更新”，因为它同时穿过 main、preload、renderer、shared，且当前变更频繁。先建立 renderer 侧 `FilePort`/平台适配器，再把 main handler 收敛为显式文件能力；保留旧 IPC 作为兼容实现，待测试稳定后再清理。

不建议优先建设：

- 一个再次包装 `ipcRenderer` 的“大一统 IpcService”；
- 把整个 editor state 搬到 main 或 shared；
- 一次性给所有历史 channel 加 runtime schema；
- 在没有插件/协作需求前拆出大量小 package；
- 继续扩大 `shared` 的开放索引和 `unknown` 作为长期协议。

## 迁移与验收标准

1. 先建立 channel ownership 表，区分外部 renderer↔main、main↔main、renderer local bus，并标记所有 `unknown` 与旧通道。
2. 选择文件能力做第一条垂直切片，renderer store/component 不再直接调用该切片的 raw IPC。
3. 对该切片使用精确 DTO、显式错误结构和 structured-clone 测试；不再依赖实现方手工 `unknown` 收窄。
4. 为 preload facade、main handler 和 watcher 生命周期增加契约测试；保留现有 sandbox E2E 作为安全回归。
5. 对目标切片设置静态 guard：禁止 renderer 业务模块直接访问 `window.electron.ipcRenderer`，禁止使用 `ipcMain.emit` 作为该切片的内部总线。
6. 只有在 desktop typecheck、相关 unit、E2E 和 Muya consumer 回归都通过后，才删除旧 alias 或 legacy 依赖。

验收条件应包括：契约中没有目标切片的 `unknown`；主进程只存在一个明确注册入口；renderer 测试不再导入 main 实现；旧 bridge 可被单独切回；文件保存、外部修改、窗口销毁和 renderer reload 均有覆盖。

## 未决问题与置信度

- [未知] 是否有仓库外部消费者仍依赖 `@marktext/muyajs`；静态仓库搜索未发现 desktop 的实际运行时引用，但不能替代发布物和 CI 验证。
- [未知] 未来是否需要插件、协作编辑、多窗口编辑器或可替换引擎；这些需求会决定是否需要 bridge 版本化和更强的 domain package。
- [未知] 当前测试在该 checkout 是否全部运行通过；本次只读检查未执行测试。
- [约束] `webSecurity: false` 仍存在于窗口配置。[config.ts](/evaluation-path/treatment/packages/desktop/src/main/config.ts:18) 是否能移除需要单独的安全威胁模型，不应在本次架构建议中直接假设。

本次仅进行了只读检查，没有修改文件、创建提交或改变外部状态。

[EVAL:evolve-software-architecture-loaded]
