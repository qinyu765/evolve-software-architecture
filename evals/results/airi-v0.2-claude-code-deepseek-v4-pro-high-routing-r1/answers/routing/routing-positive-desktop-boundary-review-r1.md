## 1. 范围与置信度

评估对象是 `apps/stage-tamagotchi`（Electron 桌面端）的 **main / preload / renderer** 进程边界，以及它们与共享 package（`stage-shared`、`stage-ui`、`stage-pages`、`electron-eventa`、`electron-vueuse`、`electron-screen-capture`、`plugin-sdk*`、`server-*`）之间的耦合。目标约束是未来两条主线：**插件能力**（已有雏形）与**多窗口扩展**（已有 14 个窗口）。

- **仓库类型**：pnpm monorepo + Electron + Vue3 + TypeScript（置信度高，已从 `package.json`、`electron.vite.config.ts`、`src/main/index.ts` 确认）。
- **置信度说明**：`node_modules` 未安装，`@moeru/eventa` 的 Electron 适配器内部实现无法直接查看（**未知**），因此关于“窗口命名空间为何失效”的部分是推理；其余结论来自源码直接观察。

---

## 2. 观察到的现状（证据）

### 进程边界与装配

- **组合根清晰**：`apps/stage-tamagotchi/src/main/index.ts`（约 355 行）用 `injeca` 声明式装配约 20 个 provider（configs、services、windows、tray），依赖关系显式、命名一致（`configs:*` / `services:*` / `modules:*` / `windows:*`）。这是一个健康的模式。
- **14 个窗口管理器**在 `src/main/windows/*`（main、settings、chat、spotlight、caption、notice、about、onboarding、devtools、widgets、beat-sync、inlay、dashboard、desktop-overlay），每个有 `setupXWindowManager`，部分带 `rpc/index.electron.ts`。
- **所有窗口统一配置**：`sandbox: false`、`contextIsolation` 默认开启、preload 指向同一份 `preload/index.mjs`（beat-sync 例外用 `beat-sync.mjs`）。见 `windows/main/index.ts:90`、`windows/widgets/index.ts:231` 等。

### IPC/RPC 层（Eventa）

- 契约集中定义在 `apps/stage-tamagotchi/src/shared/eventa/index.ts`（约 500 行）及 `plugin/*.ts`，用 `@moeru/eventa` 的 `defineInvokeEventa`/`defineEventa`。
- main 侧每个窗口 `createContext(ipcMain, window)` 后注册 handler（`windows/settings/rpc/index.electron.ts:52`），公共 handler 在 `windows/shared/window.ts:134` 的 `setupBaseWindowElectronInvokes` 里按窗口重复注册。
- renderer 侧在多处直接 `createContext(window.electron.ipcRenderer)`（`@moeru/eventa/adapters/electron/renderer`）；`packages/electron-vueuse/src/composables/use-electron-eventa-context.ts` 提供单例 context + `useElectronEventaInvoke`。
- **最突出的信号**：代码里出现 5 处几乎相同的 `ipcMain.setMaxListeners(0/100)` + `ipcRenderer.setMaxListeners(0)` 的 workaround，都带同一个 TODO：“等 eventa 支持 window-namespaced contexts 后删除”。见 `main/index.ts:55-58`、`preload/shared.ts:9-12`、`windows/settings/rpc/index.electron.ts:47-50`、`windows/main/index.ts:211-214`、`windows/widgets/index.ts:322-325`。

### preload 边界

- `preload/index.ts` 只调用 `expose()`（`preload/shared.ts`），暴露的是 `@electron-toolkit/preload` 的通用 `electronAPI`（宽泛的 `ipcRenderer`）+ `platform`。**没有**按窗口/按契约收窄的 typed bridge。

### 插件系统（已存在且相当成熟）

- `packages/plugin-sdk`：通用 `ExtensionHost`（`plugin-host/core.ts` 约 860 行），含 manifest 校验、session、module、两层权限、kit、kit-api binding、capability、resource、dependency、`FileSystemLoader`，以及 local/websocket 两种 channel 和 node/web 运行时。
- `packages/plugin-sdk-tamagotchi`：桌面端 DX（gamelet、widgets、kits、tools）。
- `packages/plugin-protocol`：插件协议事件与 websocket 类型。
- 桌面端接线：`services/airi/plugins/*` 从 `<userData>/extensions/v1` 加载 manifest、持久化 `extensions-v1.json`、提供 auto-reload / static-assets 特性、暴露 list/load/unload/enable/inspect/tools/capabilities 的 IPC 门面。
- 插件 UI：renderer `widgets/extension-ui/*` 用 iframe + eventa `window-message` 适配器；main 侧 `windows/widgets/iframe-request-coordinator.ts` 用 `requestId` + 超时做请求/响应关联。

### 共享 package 耦合

- `apps/stage-web` 与 `apps/stage-tamagotchi` **共用** `stage-ui`、`stage-pages`、`stage-shared`（`apps/stage-web/package.json` 依赖确认）。
- 但这些共享包里存在 Electron renderer 适配器引用：
  - `packages/stage-ui/src/stores/modules/artistry-autonomous.ts:4` 静态 import renderer 适配器，运行时用 `window.electron?.ipcRenderer` 兜底；
  - `packages/stage-pages/src/pages/settings/providers/artistry/comfyui.vue:5` 同上；
  - `packages/stage-shared/src/beat-sync/detector.ts:165` 动态 import（安全），有 `isElectronWindow(window)` 守卫。
- 类型耦合：`packages/stage-shared/src/electron-renderer.d.ts` 全局声明 `Window extends ElectronWindow`；应用级 `shared/eventa` 直接 import `electron` 的 `Rectangle` 类型。
- 契约重复：`shared/eventa/index.ts:218-247` 和 `shared/eventa/plugin/capabilities.ts:42-44` 有 TODO，承认手动复制了 `CapabilityDescriptor` / `PluginCapabilityPayload` 类型，等 `stage-ui` 与 eventa 层能安全依赖 SDK 后再改为 re-export。

---

## 3. 当前摩擦（哪类改动会被放大）

1. **窗口命名空间不完整（最高杠杆）**。新窗口 = 又一次全局 `ipcMain` 注册 + 又一次 `setMaxListeners` 兜底。窗口数量增长会线性放大监听器数量，且跨窗口事件隔离靠“传入 window 参数”的适配器行为兜底，而不是契约级保证（**推理**：5 处重复 TODO + workaround 是强证据）。
2. **preload 桥过宽**。renderer 拿到的是通用 `ipcRenderer`，任何窗口理论上可 invoke 任意 channel；安全边界靠“渲染层代码自觉”而不是 preload 白名单。`sandbox: false` 进一步放大了这个面。
3. **IPC 契约分散在 4 处**：应用级 `apps/.../shared/eventa`、可复用的 `packages/electron-eventa`、`packages/electron-screen-capture`、插件协议 `plugin-protocol`/`plugin-sdk`，且中间有重复类型。新增一个跨层能力时，开发者要同时知道该改哪里。
4. **共享 UI 包渗入 Electron**。`stage-ui`/`stage-pages` 是 web 与桌面共用包，却静态 import 了 Electron renderer 适配器，用运行时判断隐藏环境差异。今天 web 构建能通过（推断：适配器可能不顶层 import `electron`），但这是脆弱接缝——一旦适配器实现引入真实 Electron 依赖，web 构建会直接断。
5. **插件 node 逻辑跑在 main 进程**。插件崩溃/死循环影响整个主进程（尚无 crash 隔离）；同时插件 UI（renderer iframe）→ main 的往返靠 `requestId`+超时自建关联层，与 eventa 的窗口命名空间是同一根问题的两个表象。

不算危机的是：`main/index.ts` 的 DI 装配虽然 provider 很多，但可读性尚可；`settings` 窗口依赖 13 个东西、`main` 窗口依赖 10 个，属于“依赖网变密”，但还没到需要立刻拆的地步。

---

## 4. 质量属性优先级（明确取舍）

对“插件 + 多窗口”这个目标，真正主导决策的是两个属性：

| 优先级 | 属性 | 理由 |
|---|---|---|
| 1 | **可扩展性/演进性** | 插件 API 稳定性和窗口独立性直接决定未来新增成本 |
| 2 | **隔离/安全** | 插件是半可信代码；窄 preload + 权限模型是长期底线 |
| 3 | **可维护性** | 契约单一来源、无重复类型，降低跨层改动成本 |
| 4 | 可测试性 | 通过公开 seam 测试，而非 mock 内部实现 |

**明确取舍**：安全和插件能力在此冲突。当前设计优先插件能力（`sandbox: false`、node 运行时插件、宽 preload）。这不是错误，但要显式承认——**不应在未决定插件信任模型前，先把 `sandbox: false` 当永久事实**。性能（每窗口 context）和工程成本不是本决策的约束项。

---

## 5. 方案对比

### 方案 A：维持现状，只做局部修补
- **边界**：保持现有四层契约分散、宽 preload、全局 handler。
- **优点**：零迁移成本；今天已能跑通插件和多窗口。
- **缺点**：窗口和插件数量每增加一层，`setMaxListeners` 与类型重复问题继续累积；安全面随时间扩大。
- **证伪条件**：若团队确认未来窗口数稳定在个位数、插件保持“受信本地开发”定位，则此方案可辩护。

### 方案 B：渐进收敛为三个稳定 seam（推荐）
- **seam 1**：可窗口命名的 Eventa context（真正按窗口隔离 + 自动清理 handler），消除全局监听器膨胀。
- **seam 2**：从同一份契约生成的窄类型化 preload API（替代通用 `electronAPI`），保持 contextIsolation，`sandbox` 先不动、后按窗口分级收紧。
- **seam 3**：单一契约包 + 环境端口——应用级 eventa 契约与可复用 electron 契约合并/各归其位，插件类型改为从 `plugin-protocol`/`plugin-sdk` 类型入口 re-export；共享 UI 通过 `stage-shared` 声明的环境端口访问 Electron，而非直接 import 适配器。

### 方案 C：激进重构（独立插件进程 + 换 IPC 框架 / 引入窗口框架）
- **拒绝理由**：没有证据表明当前 Eventa/injeca 组合需要被替换；插件 host 已有清晰的 session/permission/kit 模型，缺的是隔离与契约收口，不是重写。把插件 node 运行时拆到 utility process 是**可选后期动作**，不应现在启动。

---

## 6. 建议方向

**采纳方案 B，按下面顺序做可逆的渐进迁移，不进行大爆炸重构。**

稳定下来的应是三件事：
1. **窗口是 IPC 的第一公民**——每窗口一个可清理的 context，跨窗口事件要么显式广播、要么按路由隔离。
2. **契约是唯一事实来源**——一个契约定义同时生成 main handler 类型、preload 桥、renderer invoke 类型；插件协议类型不复制。
3. **共享包不感知进程**——`stage-ui`/`stage-pages` 只依赖声明的环境端口，Electron 实现由桌面端注入。

暂不构建：
- 不要现在建通用插件消息框架或“多窗口微前端 host”，等窗口数量或插件 UI 形态真的逼出来再说。
- 不要现在把插件 node 运行时拆到独立进程，除非插件隔离成为明确需求（见待决问题）。

---

## 7. 可逆迁移与验证

每步都可独立回滚（保留旧路径并存一个版本，用特性开关切换）。

### 步骤 0 — 建立基线并锁住边界（先做，成本最低）
- 整理现有契约清单（`shared/eventa/*`、`packages/electron-eventa`、`electron-screen-capture`）。
- 加架构守卫：禁止 `stage-ui`/`stage-pages`/`stage-shared` 再新增对 `@moeru/eventa/adapters/electron/*` 的**静态** import（ESLint `no-restricted-imports` 或 dependency-cruiser 规则）。
- **验证**：`pnpm -F @proj-airi/stage-web build` 与 `pnpm -F @proj-airi/stage-tamagotchi build` 均通过，确认共享包不因守卫而改变构建行为。

### 步骤 1 — 修好窗口命名空间（第一个有价值的纵切）
- 确认 `@moeru/eventa` 适配器是否已支持按窗口注册/清理；若支持则切换调用方式并删除 5 处 `setMaxListeners`；若不支持，则在 `apps/stage-tamagotchi/src/main` 内加一层薄的 `createWindowContext(window)` 包装（注册时记录窗口、窗口 `closed` 时清理、事件按 sender 过滤），不改变契约定义。
- **回滚**：包装层是纯增量，删掉即回到现状。
- **验证**：
  - 现有窗口测试仍通过：`pnpm exec vitest run apps/stage-tamagotchi/src/main/windows`、`.../services/airi/plugins/index.test.ts`。
  - 运行时冒烟：`pnpm -F @proj-airi/stage-tamagotchi dev`，同时打开 main + settings + widgets + spotlight，确认各窗口 RPC 只命中自己、`closed` 后无泄漏（可加一条断言：窗口关闭后 context 不再响应）。
  - 退出条件：全局 `setMaxListeners` 的 5 处 workaround 全部删除，且无 `MaxListenersExceededWarning`。

### 步骤 2 — 收窄 preload 桥（保持 contextIsolation）
- 引入按契约白名单暴露的 typed preload（可先用脚本从 `shared/eventa` 生成 bridge 类型），窗口逐步从通用 `electronAPI` 迁移到窄 API；`sandbox: false` **本步不动**，用开关控制。
- **回滚**：保留 `electronAPI` 路径，逐窗口切回即可。
- **验证**：
  - `pnpm -F @proj-airi/stage-tamagotchi typecheck` 全绿（确保 renderer 不再能调用未声明的 channel）。
  - 冒烟调用：main/settings/widgets 各自的 invoke 均返回预期；未声明 channel 应报类型错误（这是架构验证，不是运行时测试）。

### 步骤 3 — 收敛契约来源
- 把插件能力类型改为从 `plugin-protocol`/`plugin-sdk` 的 type-only 入口 re-export，删除 `shared/eventa` 里的复制类型；评估把应用级 eventa 契约整体迁入一个专用 package（如 `packages/stage-tamagotchi-ipc`）或并入 `electron-eventa`。
- **回滚**：re-export 与复制类型并存一个版本，确认两边结构一致后删除旧复制。
- **验证**：`pnpm type-check` + `pnpm lint`；用 `tsc` 的“契约一处改动、全仓编译反馈”确认单一来源生效。

### 步骤 4 — 移除共享 UI 的 Electron import
- 在 `stage-shared` 定义环境端口接口（如 `stageBridge`），桌面端注入 Electron 实现，web 端提供空实现；`stage-ui`/`stage-pages` 只依赖端口。
- **回滚**：端口默认实现临时指向旧的 `window.electron` 路径，验证后移除。
- **验证**：`stage-web build` 产物中不再出现 `@moeru/eventa/adapters/electron/renderer`（bundle 检查或 grep dist）；`stage-tamagotchi` 桌面功能不变。

### 步骤 5 — 条件触发（暂不做，仅记录触发信号）
- 当出现“插件崩溃影响主进程”“需要给插件独立权限/profile”“第三方插件要沙箱运行”任一条时，再启动插件 node 运行时迁往 utility process 或启用沙箱分级的 ADR。

**通用验证手段**：`pnpm -F <pkg> typecheck`、`pnpm exec vitest run <path>`、`pnpm lint`；桌面端每次迁移后跑 `pnpm -F @proj-airi/stage-tamagotchi dev` 冒烟，重点覆盖单实例、退出流程（`handleAppExit`）、插件 load/unload（devtools 面板）和多窗口同开。

---

## 8. 待决问题（答案会改变推荐）

1. **插件的 node 运行时定位**：打算长期跑在 main，还是需要独立进程做 crash 隔离与资源配额？这决定步骤 5 是否提前、也决定 `sandbox` 分级策略。
2. **插件协议是否跨端统一**：`plugin-protocol` 的存在暗示 web 端未来也会跑同一插件 host；若属实，契约包必须成为“不依赖 Electron 类型”的中立层（现在 `shared/eventa` 仍 import `electron` 类型，需先拆）。
3. **`@moeru/eventa` 窗口命名空间的真实状态**：`node_modules` 未安装，无法确认适配器内部是否已支持按窗口清理；这是步骤 1 采用“升级适配器”还是“本地包装”的分叉点，下一步应优先查证。

总结：当前 main/preload/renderer 的装配与插件 host 骨架都健康，真正需要动手的是**窗口命名空间、preload 窄桥、契约单一来源、共享包去 Electron 化**这四个可逆步骤；不要提前做进程拆分或框架替换。

[EVAL:evolve-software-architecture-loaded]
