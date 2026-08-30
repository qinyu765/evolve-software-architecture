已完成对桌面端 main / preload / renderer 与共享 package 边界的只读评估。下面是结论与建议，未修改任何代码。

## 1. 范围与置信度

- **范围**：`apps/stage-tamagotchi` 的 Electron 三进程边界、`src/shared` 与 `packages/*` 的契约归属、插件宿主与多窗口扩展的长期演进方向。
- **仓库分类**：Electron 桌面应用（ESM + electron-vite/rolldown），带 pnpm monorepo 与一套已经成型的插件 SDK。**置信度高**：入口、DI 图、窗口工厂、IPC 契约层、插件宿主都已读到源码。

## 2. 观察到的事实（带证据）

**进程与依赖注入**
- `src/main/index.ts` 是单一组合根（约 355 行），用 `injeca` 注册约 30 个 provider：`configs:*`、`services:*`、`modules:*`、`windows:*`，最后 `injecta.start()`（`src/main/index.ts:132-272`）。
- 14 种窗口：`src/main/windows/{about,beat-sync,caption,chat,dashboard,desktop-overlay,devtools,inlay,main,notice,onboarding,settings,spotlight,widgets}`。

**IPC 边界（关键）**
- 契约集中在 `src/shared/eventa/index.ts`（约 500 行，单一"契约枢纽"）+ `plugin/{assets,capabilities,host,tools}` 子模块。它既导入 `electron` 的 `Rectangle`（`index.ts:29`），也导入 `@proj-airi/server-runtime/server` 的 `ServerOptions`（`index.ts:6`）——即共享层同时承载 Electron 专用与 server 专用类型。
- 主进程侧：`createContext(ipcMain, window)`（按窗口）+ `defineInvokeHandler`；全局单例用 `createContext(ipcMain)` 并靠模块级布尔防重复注册（如 `services/airi/channel-server/index.ts:57,451-468` 的 `serverChannelServiceRegistered`）。
- 渲染进程侧：直接使用 `window.electron.ipcRenderer`（`@electron-toolkit/preload` 暴露的**裸 ipcRenderer**）创建 Eventa context；`@proj-airi/electron-vueuse` 的 `useElectronEventaContext` 只是对它的封装（`packages/electron-vueuse/src/composables/use-electron-eventa-context.ts:18`）。
- 大量重复 `ipcMain.setMaxListeners(0)` / `ipcRenderer.setMaxListeners(0)`（`src/main/windows/shared/window.ts`、`referenced-window.ts:44`、`widgets/index.ts:325`、`preload/shared.ts:12` 等），且伴随同一段 TODO："eventa 支持 window-namespaced contexts 后即可移除"。（推断：Eventa 当前**没有**窗口命名空间能力，事件/监听器挂在共享 `ipcMain` 总线上；确切路由语义需查 `@moeru/eventa` 源码确认，node_modules 在本环境未安装。）

**preload**
- `src/preload/index.ts` 与 `beat-sync.ts` 内容完全相同（都只调 `expose()`）；`electron.vite.config.ts:81-92` 构建两个入口。
- `src/preload/shared.ts:32` 定义了 `exposeWithCustomAPI<CustomAPI>`，但全仓库无调用点——是死代码。
- 所有窗口 `sandbox: false`（grep 全量命中 16 处），context isolation 依赖 Electron 默认开启。

**窗口管理**
- 已有两个局部抽象：`createReusableWindow`（惰性复用单个窗口，`libs/electron/window-manager/reusable.ts`）与 `createReferencedWindowManager`（按 id 多窗口，`windows/shared/referenced-window.ts`）。但没有统一的窗口描述符/注册表；每个 `windows/*/index.ts` 重复 `new BrowserWindow(...)`、preload 路径、`sandbox:false`、`protectPrivilegedWindowNavigation`、`setupBaseWindowElectronInvokes`、`load(...)` 样板。

**共享 package 归属**
- `packages/stage-shared`：跨端（web+桌面）逻辑（`environment`、`url`、`error-message`、`perf`、`webgpu`、`export-csv` 等），但**也**混入了桌面专用契约：`global-shortcut`、`godot-stage`、`server-channel-qr`、`beat-sync`、`auth`、`electron-renderer.d.ts`、`window.ts`（`ElectronWindow`）。
- `packages/electron-eventa`：通用 Electron 窗口/屏幕/电源/系统偏好契约（`bounds`、`electron.window.*` 等）——是干净的通用层。
- `packages/plugin-sdk` + `plugin-sdk-tamagotchi`：插件宿主核心（`ExtensionHost`、kit、permission、capability、resource、node/web runtime、channels）与 tamagotchi 专属 kit（`gamelet`/`tool`/`widget`）。`plugin-sdk/src/plugin-host/core.ts` 是一个较深的模块，权限模型是"扩展授权 ∩ 模块授权"两层。
- 应用内 `src/shared`（非 eventa）：`mcp-config.ts`、`model-settings-runtime.ts`、`spotlight-shortcut.ts`、`desktop-overlay-heartbeat.ts`、`utils/electron/windows/window-size.ts`。

**插件宿主**
- `services/airi/plugins/index.ts` 是 IPC 门面；`host/index.ts` 是真正的 bootstrap：`ExtensionHost` + 注册表（`<userData>/extensions/v1`）+ config store + static-assets（loopback HTTP + cookie session）+ auto-reload + built-in kits。
- 已有明确的架构债信号：`host/index.ts:437-441` 的 `REVIEW:` 指出工具注册表所有权"藏在 built-in kit runtime 里"，而宿主服务又通过 IPC 暴露它。
- 插件宿主依赖 `widgetsManager`（一个具体窗口管理器），通过 `kits/gamelet/orchestration.ts` 编排 iframe 请求（main → widgets renderer → iframe 的带 `requestId` 关联中继，契约见 `shared/eventa/index.ts:153-208`）。

## 3. 当前摩擦

1. **契约枢纽单点膨胀**：所有窗口、插件、MCP、Godot、auth、桌面 overlay 的契约塞在一个 `src/shared/eventa/index.ts`。加窗口 = 改共享枢纽，main/renderer 两侧的边界感模糊。这直接放大"多窗口扩展"的改动成本。
2. **窗口命名空间缺失（代码自己承认的 TODO）**：事件路由靠 `ipcMain` 全局总线 + `sender.id` 手工校验（`services/electron/window.ts:45-48`、`59-63`），并用 `setMaxListeners(0)` 兜底。这是多窗口 + 插件两者共同的最深障碍——新增一种"谁的事件发给谁"的规则，当前无处安放。
3. **preload 不是能力边界，是装饰性传输桥**：`sandbox:false` + 裸 `ipcRenderer` 暴露给所有窗口，实际安全边界散落在各窗口注册了哪些 handler 上。插件能力的未来扩展需要一个**显式、可测试、可按窗口收窄**的边界，现在没有。
4. **窗口样板重复 + 抽象层级不齐**：`createReusableWindow` 管"复用"，`createReferencedWindowManager` 管"按 id 引用"，但没有一个回答"这个窗口是什么、走哪条路由、暴露哪些契约、如何复用/退出"的声明式描述。
5. **契约归属是隐式惯例**：哪些进 `electron-eventa`、哪些进 `stage-shared`、哪些留 `src/shared/eventa`，没有成文规则，靠人肉判断（stage-shared 已开始漂移进桌面专用契约）。
6. **组合根过重、依赖链深**：`settingsWindow` 依赖 12 项、`mainWindow` 依赖 11 项，窗口之间互相依赖（`settingsWindow` 依赖 `spotlightWindow`），插件宿主反向耦合到具体窗口管理器。

## 4. 质量属性优先级（对本决策）

1. **可扩展性/可修改性**（插件 + 多窗口是明确未来）——首要。
2. **安全性**（插件宿主运行第三方代码；IPC 面就是插件能触达的面）——与 1 强耦合。
3. **可测试性**（本仓库测试文化很强，必须保住现有 seam）。
4. **可运维性**（窗口生命周期、事件路由可观测、cleanup 顺序明确）。
5. **成本/可逆性**（团队大、历史包袱多，拒绝大爆炸式重写）。

明确取舍：**不**追求"最小化 renderer 权限"的极端安全姿态作为第一步，因为那需要先有窗口描述符和命名空间；先做正确性/可扩展性，安全边界作为同一条 seam 的最终形态逐步收紧。

## 5. 方案对比

| 方案 | 边界与所有权 | 收益 | 主要成本/风险 | 什么证据会让它变错 |
|---|---|---|---|---|
| **A. 渐进深化现有 seam（推荐）** | 契约按域拆成 owned 模块；引入窗口描述符+注册表；给 Eventa 加窗口命名空间；preload 逐步收窄为能力白名单 | 每步可逆、行为不变、直接命中已承认的 TODO | 需要先做一次契约归属 ADR，否则拆分会引入新的隐式惯例 | 若 Eventa 上游无法加命名空间，或拆分后契约仍跨域互相引用 |
| **B. 大统一：所有 main 服务收敛到单一本地 RPC server（复用 server-runtime）**，renderer 变薄客户端、按 token 授权 | 一个协议、一个授权模型，与已有 server-channel/remote-plugin 方向一致 | 概念统一，插件本地/远程同构 | 大重写、与 Eventa 重复、迁移期双轨，风险高 | 若"插件远程化"确实是近中期刚需，则值得提前验证 |
| **C. 维持现状**（只做局部修复） | 继续靠团队纪律维持 | 零迁移成本 | 摩擦 1/2/3 会随每个新窗口/新插件线性放大 | 若窗口与插件数量停在当前规模，现状可防御 |

## 6. 建议方向（长期架构）

**稳态目标**：三条稳定的 deep seam，其余保持现状。

1. **契约归属规则（seam 1：契约所有权）**
   - `@proj-airi/electron-eventa`：只放可复用的通用 Electron 契约（窗口、屏幕、电源、系统偏好）。
   - `@proj-airi/plugin-sdk` / `plugin-sdk-tamagotchi`：插件协议与 tamagotchi kit 契约；渲染层与 main 只引用类型，不重复声明。
   - `@proj-airi/stage-shared`：跨端中性逻辑；把 `global-shortcut`、`godot-stage`、`server-channel-qr`、`beat-sync`、`ElectronWindow` 等桌面专用契约迁出，回到应用级或 `electron-eventa`/新建的 `stage-tamagotchi-shared`。
   - 应用内 `src/shared`：只留**不可复用**的 app 内部契约（如桌面 overlay、MCP stdio、widgets 窗口），且按域拆成模块，不再设单一 500 行枢纽。

2. **窗口描述符 + 注册表（seam 2：多窗口模型）**
   引入一个声明式描述符（`id`、`route`、`preload`、`reusePolicy`、`lifecycle`、`contracts`/capability 集、`capabilities`），由注册表统一建窗/复用/路由/清理。`createReusableWindow` 与 `createReferencedWindowManager` 降为实现细节。这是多窗口扩展的真正杠杆，也是 preload 白名单与事件命名空间的数据来源。

3. **能力边界 + 事件命名空间（seam 3：IPC/安全）**
   - 先给 Eventa（或其 electron adapter）加窗口命名空间，让事件按 owning window 路由，消除 `setMaxListeners(0)` 与手工 `sender.id` 校验。
   - 再把 preload 从"裸 ipcRenderer"收窄为按窗口描述符生成的**能力白名单**；非特权窗口逐步迁到 `sandbox:true`，只有需要原生模块的窗口保留 `sandbox:false`。
   - 插件宿主与窗口解耦：宿主依赖"窗口宿主能力接口"（如 `openWidgetWindow` 由注册表提供），不再直接持有 `widgetsManager`。

**不要现在做**：不要立刻引入进程级插件沙箱/独立进程隔离（现有 permission service + iframe 隔离已够用）；不要立刻做"renderer 走 server-runtime 的薄客户端"（B 方案），等命名空间与窗口描述符落地后再评估；不要新增一层 DI 框架替代 injeca。

## 7. 迁移与验证（可逆、逐步）

每步保持行为不变、可单独回滚；按仓库偏好，倾向**原子化重构**而非保留兼容 shim（若需过渡别名，标记 `// NOTICE:` 并写清除条件）。

1. **先写 ADR**，固化三条 seam 的归属规则与稳态形状（这是唯一"不可逆性风险"最低但收益最大的第一步）。
2. **契约拆分的第一个垂直切片**：把 `src/shared/eventa/index.ts` 机械拆为 `windows/*`、`plugins/*`、`mcp`、`godot-stage` 等模块并改为桶式 re-export（一次原子变更重命名所有 import）。验证：`pnpm -F @proj-airi/stage-tamagotchi typecheck` + 全量测试；行为零变化。
3. **事件命名空间试点**：先确认 `@moeru/eventa` 上游能否加命名空间（未知，需先查）；选一对最简窗口（如 `notice`/`about`）试点，删除其 `setMaxListeners(0)`。验证：新增回归测试断言"窗口 A 发出的事件不会送达窗口 B"、`ipcMain.listenerCount` 有界。
4. **窗口描述符/注册表落地**：先迁移一个简单窗口（`notice` 或 `about`）为描述符驱动，再渐进迁移其余 13 个。验证：注册表测试断言每个描述符的 preload/route/契约集可解析、N 个窗口不泄漏监听器、cleanup 幂等。
5. **插件宿主解耦**：把 `widgetsManager` 注入替换为窗口宿主能力接口，先解决 `host/index.ts` 里的 `REVIEW:`（工具注册表所有权上移）。验证：插件宿主单元测试不依赖具体窗口管理器。
6. **preload 能力白名单**（最后一步，门槛高）：先做 devtools 诊断——记录每个窗口实际调用了哪些 channel，再由描述符生成 allowlist；非特权窗口迁 `sandbox:true`。验证：拦截测试断言"未授权 channel 从某窗口发出会被拒绝"；回滚即恢复旧 preload。

**全局验证清单**：
- `pnpm -F @proj-airi/stage-tamagotchi typecheck`、`lint`、`pnpm test:run`（每次步骤后）。
- 新增**契约边界测试**：在同一测试里分别以 main（Node）与 renderer（browser）环境 import 每个契约模块，断言无 `electron`/`server-runtime` 运行时值泄漏（只允许 type-only import）。
- 新增**事件路由测试**与**监听器计数测试**作为命名空间/注册表的回归护栏（仓库已有 `desktop-overlay`、`iframe-request` 中继测试可作范式）。
- 用 dependency 检查（如 ESLint no-restricted-imports 或自定义规则）把"renderer 不得 import main-only 模块""`src/shared/eventa` 不得 import electron 运行时"变成可执行约束，而不是文档。

## 8. 待定决策（答案会改变建议）

1. **Eventa 是否能在本仓库/上游加窗口命名空间**？这决定 seam 3 是"改 adapter"还是"换路由方案"。这是最该先探明的一个未知点。
2. **插件远程化（remote runtime/channel）是近中期刚需吗**？如果是，B 方案的部分（协议统一）值得提前，否则按 A 推进。
3. **是否有真实安全需求把插件与主进程隔离**？当前 permission service + iframe 是够用的推断；若产品上要运行完全不可信插件，需要重新排属性优先级。

[EVAL:evolve-software-architecture-loaded]
