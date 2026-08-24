调查完成。以下是基于仓库证据的 IPC 演进方案建议（只读，未改任何文件）。

---

## 1. 范围与置信度

**决策对象**：`apps/stage-tamagotchi`（Electron 桌面端）main ↔ preload ↔ renderer 之间的 IPC 契约层，以及它未来如何在不破坏现有窗口的前提下演进。

**仓库分类**：高置信度判定为「Electron 多窗口桌面应用，用 `@moeru/eventa` 做传输无关的类型化 RPC/事件层」。核心证据是契约定义集中在 `apps/stage-tamagotchi/src/shared/eventa/`，主进程侧用 `createContext(ipcMain, window)` + `defineInvokeHandler`，渲染侧用 `getElectronEventaContext()` + `defineInvoke`。eventa 版本为 `1.0.0-beta.8`（`pnpm-workspace.yaml:110`）。

**置信度边界**：本方案对「eventa Electron 适配器如何序列化错误」这一点没有读到源码（`node_modules` 未安装），这条列为待验证的未知项，但不影响主结论。

---

## 2. 观察事实

**契约定义（单一 seam，这是当前架构里最值得保留的部分）**

- 契约是运行时值：`defineInvokeEventa<Res, Req>(name)` / `defineEventa<T>(name)`，channel 名是硬编码字符串（`eventa:invoke:...` / `eventa:event:...`），名字里没有版本号。见 `apps/stage-tamagotchi/src/shared/eventa/index.ts:31-34`。
- 契约注册表分三处：应用级 `apps/stage-tamagotchi/src/shared/eventa/index.ts`（约 500 行 + `plugin/` 子模块）、通用包 `packages/electron-eventa`（Electron `>=39 <41` peer dep，`package.json:30-32`）、特性包 `packages/electron-screen-capture`。
- 契约里已经出现对版本化的一个正面先例：`createServerChannelQrPayload({ ..., version: 1 })`（`main/services/airi/channel-server/index.ts:117-122`）——跨机器边界用显式 wire version。

**主进程侧（两种注册模式并存）**

- 每个窗口的 `rpc/index.electron.ts` 调 `createContext(ipcMain, window)` 注册窗口作用域 handler，再共享 `setupBaseWindowElectronInvokes`（`main/windows/main/rpc/index.electron.ts:48`、`main/windows/shared/window.ts:134-149`）。
- 全局作用域 handler 用 `createContext(ipcMain)` + 布尔守卫：`createServerChannelService` 里 `serverChannelServiceRegistered`（`channel-server/index.ts:451-457`）。
- **关键事实**：eventa 的 `onlySameWindow` 选项只过滤 main→renderer 的事件广播，**不过滤 renderer→main 的 invoke**。`electron-screen-capture/src/main/index.ts:187` 用了 `{ onlySameWindow: true }`，紧接着 `204-206` 手动比 `window.webContents.id !== sender.id` 补洞，并留有 FIXME。
- 因此代码里到处是 `ipcMain.setMaxListeners(0)`（`main/index.ts:55-58`、`windows/main/rpc/index.electron.ts:43-46`、`desktop-overlay/rpc/index.electron.ts:34-37`），且都带同一句 TODO：「等 eventa 支持 window-namespaced contexts 后可以删掉」。

**preload / renderer 侧**

- preload 是薄透传：`preload/shared.ts:8-29` 只通过 contextBridge 暴露 `electronAPI`（来自 `@electron-toolkit/preload`）和 `platform`，**没有收窄 API**。所有窗口 `webPreferences` 都是 `sandbox: false`（`windows/main/index.ts:88-90`、`desktop-overlay/window-contract.ts:35-37` 等），`contextIsolation` 未显式覆盖（保持 Electron 默认 true）。
- 渲染侧拿到的是**裸 `ipcRenderer`**：`packages/electron-vueuse/src/composables/use-electron-eventa-context.ts:18` 从 `window.electron.ipcRenderer` 取。模块级单例 `sharedContext` 懒创建、只在测试里 `resetElectronEventaContextForTesting()` 重置（`:26-41`）。

**错误传播与校验**

- eventa 语义是「handler throw 就传播给调用方」（`.agents/skills/eventa/SKILL.md:227`），但仓库里没有结构化错误封装。错误消息统一靠 `errorMessageFrom`（`@moeru/std`）和 `errorMessageFromValue/Unknown`（`packages/stage-shared/src/error-message.ts`）。
- 主进程侧错误策略不统一：server-channel 抛 `new Error(errorMessageFrom(error) ?? '...')`（`channel-server/index.ts:504`）；screen-capture 抛普通 `Error`；desktop-overlay 不抛、改用 readiness 状态降级（`desktop-overlay/rpc/index.electron.ts:41-59`）。
- 校验不统一：server-channel 用 zod（`channel-server/index.ts:43-47`）、screen-capture 手动校验 timeout，但绝大多数契约只有编译期类型，没有运行时 schema。eventa 本身「forward whatever payload you emit，在边缘自行校验」（SKILL `:228`）。
- 已有明确的重复类型债务：`shared/eventa/index.ts:218-225` 的 TODO 承认 `PluginCapabilityPayload` 等是「manually duplicated IPC types」，等 stage-ui/shared-eventa 能依赖 SDK 后 re-export。

**测试隔离**

- 唯一看到的 IPC 单测范式是 `desktop-overlay/rpc/index.electron.test.ts:11-44`：`vi.hoisted` + `vi.mock` 掉 `@moeru/eventa`、`@moeru/eventa/adapters/electron/main`、`electron` 和兄弟模块，然后用 mock 的 `defineInvokeHandler` 捕获 handler 再断言其返回值。没有真正跑通适配器的端到端测试。

---

## 3. 当前摩擦（哪些地方变更会被放大）

1. **契约名字 = 身份 = 兼容性，但没有显式规则。** channel 名不随 shape 变化，主/渲染进程同捆发布时没问题，但一旦出现「主进程已更新、渲染页尚未 reload」的窗口期，或插件 SDK / server-channel 这种跨版本边界，就没有任何机制表达兼容性。

2. **preload 不是真正的边界。** 渲染侧拿到裸 `ipcRenderer`，理论上可调用任意 channel；`sandbox: false` 放大了这个面。类型安全靠「两端 import 同一个模块」维持，而不是靠 preload 收窄出的 API 维持——preload 几乎是无操作层。

3. **window 作用域是半成品，靠 `setMaxListeners(0)` + 手动 sender 校验兜底。** 这是全仓库重复最多的一句 TODO，也是最明确的「作者已识别的未来方向」。invoke 不过滤 sender 这一缺口（`electron-screen-capture` 的 FIXME）是根因。

4. **错误是字符串，不是类型。** 渲染侧 `catch` 只能 `errorMessageFrom` 后展示，无法可靠按 `E_TIMEOUT / E_AUTH / 校验失败 / 未知` 分支。`InvokeEventa<Res, Req, ResErr, ReqErr>` 的 `ResErr` 泛型参数存在但从未被用作结构化错误。

5. **测试断言的是接线而不是行为。** 现在单测捕获 mock handler 再调用，既脆弱（断言 `createContextMock` 调用次数）又绕过了真正需要验证的「错误跨进程序列化」「事件订阅生命周期」这些语义。

---

## 4. 质量属性优先级

| 优先级 | 属性 | 理由 |
|---|---|---|
| 1 | **可演进性 / 可维护性** | 本次决策的目的；契约层是长期边界 |
| 2 | **安全性** | 裸 `ipcRenderer` + `sandbox: false` 是真实攻击面，且与 IPC 方案直接耦合 |
| 3 | **可测试性** | 明确要求；当前只有 mock 接线，缺契约级/跨进程级测试 |
| 4 | **迁移成本** | 明确约束；必须在不停发版的前提下逐步做 |
| 5 | 性能 | 非主导；`setMaxListeners(0)` 和广播扇出是信号，但目前 invoke 频次低，不优化 |

显式取舍：**不为性能牺牲 preload 收窄**（每次 invoke 多一层 bridge 代理的开销可忽略）；**不为「完美版本协商」牺牲迁移成本**（主/渲染同捆，版本偏斜窗口很窄，详见第 6 节）。

---

## 5. 方案对比

### 方案 A：保持现状 + 加固契约层（最小迁移）

保留「eventa 契约 = 唯一 seam」这一正确结构，增量补三样东西：给契约挂 Valibot schema 做边缘校验；定义结构化 `IpcError`；加一个 capability/协议版本握手契约。

- 边界：契约注册表仍然是单一权威；校验/错误/版本都是契约层属性。
- 优点：迁移成本最低、完全可逆、不推翻已验证的 DI（injeca）+ 服务函数结构。
- 缺点：preload 仍然是透传，安全面不收窄；版本协商只是「建议性」，不强制。
- 什么证据会推翻它：如果出现主/渲染进程分开发版或第三方插件直接走 Electron IPC 的需求。

### 方案 B：preload 拥有传输绑定、暴露收窄的 `window.airi`（中期目标）

把渲染侧 `createContext(ipcRenderer)` 移进 preload，通过 contextBridge 只暴露 `window.airi.<namespace>.<method>()` 和 `onX(cb) => unsubscribe`；渲染侧不再 import `@moeru/eventa/adapters/electron/renderer`、不碰 `ipcRenderer`。

- 边界：preload 成为真正的信任边界；渲染侧退化为「调用 `window.airi` + 只用 type-only 契约」。
- 优点：可逐步关掉 `sandbox: false`（或至少停止暴露裸 ipcRenderer）；渲染侧可在 web/Storybook 里跑（用 stub）；每个 namespace 独立迁移。
- 代价：contextBridge 有序列化规则（payload 必须 structured-cloneable——仓库已在用 `Uint8Array`，`shared/eventa/index.ts:405`，说明这条能成立；函数参数可跨桥，官方 `onUpdateCounter(cb)` 范式可用）；新增契约要手动在 preload 登记。
- 什么证据会推翻它：如果窗口数量/契约数量涨到手工登记不可维护，就推进到方案 C。

### 方案 C：schema 驱动的契约注册表 + 代码生成（暂不做）

集中式 Valibot schema + 契约元数据，生成 preload API、main handler 绑定、类型；channel 名带 `v1` 前缀 + 能力协商。

- 优点：版本、校验、测试生成全部系统化。
- 代价：迁移成本最高，且**对「同捆发布的主↔渲染」是过度设计**——版本协商在那里几乎不解决问题，只增加构建复杂度。
- 触发条件：真正出现跨发布/跨机器的契约面（插件 SDK、server-channel、自动更新通道）需要强协商时，再把「注册表 + 生成」用到那个面上，而不是全量套到 Electron IPC。

---

## 6. 建议

**采用「A 现在 → B 按 namespace 推进 → C 仅在真实跨发布边界出现时」的渐进路线。** 理由：当前 seam（共享 eventa 契约）是对的，问题不在框架选择，而在契约层的三个空缺——版本语义、错误结构、窗口作用域收口——以及 preload 的信任边界。逐条：

### 6.1 契约版本：分两条规则，别给 in-process 通道上 semver

- **主↔渲染（同捆发布）**：只做**增量演化 + 一次能力握手**，不做 per-channel 版本号。加一个 `electronGetIpcCapabilities`（或 `electronGetProtocolVersion`）invoke，返回单调递增的协议版本 + feature flags；渲染启动时握手，据此决定可用 API。命名规则固定为：**加可选字段 = 同名 channel 继续用；删除字段或改变既有字段语义 = 换 channel 名或加版本后缀**，绝不复用旧名表达新语义。这个窗口期（主进程已更新、旧渲染页未 reload）真实存在但很窄，握手足以覆盖。
- **跨发布边界（插件 SDK、server-channel、自动更新通道）**：payload 里显式带 wire version。仓库已有先例 `createServerChannelQrPayload({ version: 1 })`，顺着它把 server-channel 与 plugin-sdk 的协议版本显式化，这才是版本协商真正该花精力的地方。
- 推断依据：eventa 的 `defineInvokeEventa` 只接受 `name`，没有内建版本机制；主/渲染由同一个 `apps/stage-tamagotchi` 构建产物装载，版本偏斜只在「更新后未 reload」这一瞬间。

### 6.2 错误传播：用「抛类型化错误 + 渲染侧统一 unwrap」，保留 throw 语义

- 定义可序列化的 `IpcError`（`{ code, message, retryable?, details? }`），handler 统一抛它，`code` 用稳定枚举（`IPC_VALIDATION` / `IPC_AUTH` / `IPC_TIMEOUT` / `IPC_UNAVAILABLE` / `IPC_UNKNOWN`）。eventa 的 `InvokeEventa<Res, Req, ResErr, ReqErr>` 已经预留了 `ResErr` 位置（`use-electron-eventa-context.ts:35`），显式把它用成 `ResErr = IpcError`。
- 渲染侧加一个薄 `unwrapIpcError(error)` 帮助函数（复用 `errorMessageFrom`），替代现在散落的 `console.warn` + 字符串化。降级场景（如 desktop-overlay readiness）保留现有「不抛、返回状态」模式，因为它已经是仓库里错误语义最清晰的一处。
- **待验证（未知）**：eventa Electron 适配器跨进程时是保留 Error 的 `name/message` 还是折叠成泛型 Error，决定了 `IpcError` 是「类实例 + 序列化字段」还是「纯对象 code/message 结构」。最便宜的验证方式是跑一个两进程最小复现（main 抛、renderer 接），或在装上依赖后读 `@moeru/eventa/adapters/electron/*` 源码。

### 6.3 测试隔离：三层，从「mock 接线」升级为「mock 接线 + 契约级 + 跨进程级」

- **接线层（保留现有范式，改断言目标）**：继续 `vi.mock` 掉 `createContext`/`defineInvokeHandler`/`electron`（`desktop-overlay/rpc/index.electron.test.ts` 的范式可用），但**不要通过 mock 捕获 handler 再调用**；把 handler 抽成普通函数（很多已经是，如 `createServerChannelService`），直接单测函数，mock 只断言「该注册的契约都注册了」。
- **契约级（新增，最便宜却最值）**：用 eventa 的**进程内 `createContext()`**（`@moeru/eventa` 主入口，不是 Electron 适配器）把 handler + 调用端配成对跑一遍。eventa 是传输无关的，这能零 Electron 验证错误传播、流式、abort 语义——当前代码完全没利用这个 seam。
- **跨进程级（一个守卫测试即可）**：一个最小 Electron main+renderer harness，验证两件事——错误跨 `ipcMain/ipcRenderer` 后的形态（顺带回答 6.2 的未知项）、以及能力握手。用 env guard 隔离。
- 渲染侧单例：优先改成「context 可注入」，少用 `resetElectronEventaContextForTesting()`（它是模块级可变状态的信号）。

### 6.4 preload 边界（方案 B 的实施顺序）

先收口窗口作用域，再收窄 preload：

1. **完成 eventa 的 window-namespaced 收口**：让 `onlySameWindow`（或等价能力）也过滤 renderer→main 的 invoke，从而删掉 `electron-screen-capture/src/main/index.ts:204-206` 的手动 sender 校验和所有 `setMaxListeners(0)`（`main/index.ts:55-58` 等四处 TODO）。这一步是纯债清除，不动契约。
2. **按 namespace 迁移 preload**：从最小面（window lifecycle：`electronWindowLifecycleChanged` + `electronGetWindowLifecycleState`）开始，把 context 建在 preload 里，暴露 `window.airi.window.getLifecycleState()` / `onLifecycleChanged(cb) => unsubscribe`；渲染侧只保留 type-only import。逐 namespace 推进，每个都可独立回滚。
3. 收窄完成后再评估是否能把 `sandbox: false` 关掉（与 preload 是否还暴露裸 `ipcRenderer` 强绑定，先收窄再动 sandbox）。

---

## 7. 迁移与验证

**顺序（每步可独立发布、可回滚）**：

1. `IpcError` + `unwrapIpcError` + 契约级（进程内 eventa）测试 —— 不改任何现有 handler 行为，先补错误结构。
2. 能力握手契约 + 命名规则写进 `docs/` 或 ADR。
3. window-namespaced 收口，删 `setMaxListeners(0)` 与手动 sender 校验。
4. preload 按 namespace 收窄（window lifecycle 先行）。
5. 仅当出现真实跨发布契约面，才把 C 的注册表/生成用到那个面上。

**退出标准（可观测）**：

- 每个新增契约都有 Valibot schema 且主进程注册点做边缘校验（对齐 AGENTS.md「Valibot + schema 靠近消费方」）。
- `IpcError` 的 `code` 在渲染侧能稳定分支，不再出现「字符串匹配错误」。
- 仓库里不再有裸 `ipcRenderer` 出现在渲染侧 import（`@moeru/eventa/adapters/electron/renderer` 只出现在 preload）。
- 跨进程守卫测试绿灯，回答 6.2 的未知项。
- `grep setMaxListeners` 归零。

**验证命令**（供未来落地时用，本轮未执行）：`pnpm -F @proj-airi/stage-tamagotchi exec vitest run`、`pnpm -F @proj-airi/stage-tamagotchi typecheck`、`pnpm lint`。

**什么信号会触发重审**：主/渲染分开发版；第三方插件直接走 Electron IPC；契约数量增长到 preload 手工登记成为明显摩擦。

---

## 8. 待决问题（答案会改变推荐）

1. **eventa Electron 适配器的错误序列化行为**——决定 `IpcError` 是类实例还是纯对象。建议先跑两进程复现（未知，最便宜的学习步骤）。
2. **是否愿意收紧 `sandbox: false`**——这超出纯 IPC 范畴，涉及渲染进程里对 Node API 的依赖（beat-sync 音频、屏幕捕获等）。若维持 `sandbox: false`，preload 收窄的安全收益有限，方案 B 的优先级会下降。
3. **插件 SDK 是否会在未来直接消费 Electron 进程内的 eventa context**——若会，契约注册表必须早于预期地成为跨包共享（现在 `PluginCapabilityPayload` 的重复已是先兆），方案 C 的触发条件会提前。

（本次为只读评估，未修改任何文件、未创建提交。）

[EVAL:evolve-software-architecture-loaded]
