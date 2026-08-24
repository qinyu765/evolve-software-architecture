## 1. 范围与置信度

要做的决策是：**下一条最值得治理的架构边界**，针对「桌面端 `stage-tamagotchi` 与共享 packages 耦合在增加」这一现象。仓库类型判断为 **Electron 桌面 + 三个 Vue 前端（Web / Capacitor / Electron）+ 共享 packages 的 pnpm monorepo**，分类置信度高（依据 `apps/stage-tamagotchi/package.json` 的 `electron-vite`/`electron-builder`、三端 `stage-*` apps 依赖同一批 `@proj-airi/stage-*` packages、`@moeru/eventa` 作为 IPC 契约层）。技能里的 Desktop 参考是 Tauri 专用，因此我**没有**套用 Tauri 假设，只借用其「先映射 IPC / 进程边界」的检查思路。

一句话结论：**最值得治理的边界是 `stage-shared` 这个包本身 —— 它把「跨端通用基元」和「桌面自有契约」混在同一个包里，并且从根 barrel 把 Electron 类型与 Electron IPC 地址泄漏进了 Web / 移动端 / 服务端。** 这不是唯一的问题，但它是根因；`stage-ui` 里嵌入的桌面专属场景是它的下游表现。

---

## 2. 已观察事实（带证据）

| 声明 | 证据 | 类型 | 置信度 | 影响 |
| --- | --- | --- | --- | --- |
| `stage-shared` 根入口重导出 Electron 相关代码 | `packages/stage-shared/src/index.ts:1-9` 重导出 `./artistry`（`eventa:invoke:electron:artistry:*` 契约）和 `./window`（定义 `ElectronWindow`） | 事实 | 高 | 任何从根入口导入的消费者都被拉进 Electron 类型图 |
| 根入口的 `window.ts` 依赖 Electron 与 Node 类型 | `window.ts:1,5-9` 从 `@electron-toolkit/preload` 导入 `ElectronAPI`，并用 `NodeJS.Platform` | 事实 | 高 | Web/Pocket/服务端的 TS 程序被注入 Electron/Node 全局类型 |
| `stage-shared` 用子路径暴露桌面专属模块 | `package.json` exports：`./electron-renderer`、`./global-shortcut`、`./godot-stage`；`beat-sync/eventa.ts` 含 `eventa:invoke:electron:beat-sync:*` 且分支 `isElectronWindow` | 事实 | 高 | 桌面契约以「共享包」身份对外发布 |
| 非桌面端也在消费 `stage-shared` | `stage-web`、`stage-pocket` 均为运行时依赖；`apps/ui-server-auth/src/main.ts` 导入 `isEnvTruthy`；`stage-pocket/src/main.ts`、`stage-web/src/main.ts` 同理 | 事实 | 高 | 桌面类型泄漏有真实受害面，不是理论风险 |
| 共享 UI 包 `stage-ui` 内含桌面专属场景 | `stage-ui/src/components/scenarios/settings/model-settings/{godot.vue,runtime.ts,panel.vue}` 导入 `stage-shared/godot-stage`；`stage-ui/src/stores/modules/artistry-autonomous.ts` 直接用 `@moeru/eventa/adapters/electron/renderer` 和 `window.electron.ipcRenderer` | 事实 | 高 | Web/Pocket 的依赖图里带着 Godot 设置 UI 和 Electron 适配器代码 |
| 桌面端已有契约中枢 | `apps/stage-tamagotchi/src/shared/eventa/index.ts` 集中定义 `eventa:invoke:electron:*` 契约，并从 `stage-shared/{global-shortcut,godot-stage,server-channel-qr}` 导入 payload 类型 | 事实 | 高 | 已经存在正确的「归属方向」雏形：桌面契约中枢 → 依赖共享的纯 payload 类型 |
| `stage-shared` 依赖声明与运行时不一致 | `artistry.ts`/`beat-sync/eventa.ts` 运行时 `import { defineInvokeEventa } from '@moeru/eventa'`，但 `@moeru/eventa` 只在 `stage-shared` 的 `devDependencies` | 事实 | 高 | 包边界已开始出现「运行时依赖藏进 dev 依赖」的松动 |
| `stage-ui` 大量按 surface 身份分支 | `context-bridge.ts`、`channel-server.ts`、`providers.ts`、`analytics`、`auth.ts`、`plugin-host-capabilities.ts` 等导入 `isStageTamagotchi/isStageWeb/isStageCapacitor` | 事实 | 高 | 这是二级耦合，需要治理，但不是第一步 |

推断（inference）：耦合「在增加」的机制是 —— 桌面新功能（Godot stage、artistry 小组件、全局快捷键、MCP stdio）的 payload 类型和 IPC 契约被持续塞进 `stage-shared`/`stage-ui`，而不是放进已有的 `apps/stage-tamagotchi/src/shared` 契约中枢。无法从 reflog 直接验证历史增速（本地 `.git/logs` 只有一条 clone 记录），但当前结构与该趋势一致。

未知（unknown）：`beat-sync` 的**领域**部分（detector state/settings/types）是否三端都真正需要 —— 它被 `stage-ui`/`stage-pages`/`stage-ui-live2d` 引用，看起来是跨端的，但其 `eventa.ts` 的 Electron 地址是桌面专属。这个需要产品确认，会影响拆分粒度。

---

## 3. 当前摩擦：变化放大的位置

- **一处桌面契约改动波及三端类型检查**：`godot-stage` 的 schema、`global-shortcut` 的类型、`window.ts` 的 `ElectronWindow` 都在 `stage-shared` 里，而 `stage-web`/`stage-pocket` 的 `typecheck` 会解析到它们（根 barrel 全量重导出）。桌面改个快捷键 payload，Web 端 TS 程序也要跟着重新解析 Electron 类型。
- **根 barrel 是泄漏的放大器**：`stage-shared/src/index.ts` 把 `artistry`（含 Electron 地址字符串）和 `window`（含 `ElectronWindow`）重导出，导致 `import { isEnvTruthy } from '@proj-airi/stage-shared'` 这种纯函数导入，也把 Electron/Node 类型图带进模块图。
- **共享 UI 反向认识桌面传输**：`stage-ui` 的 `artistry-autonomous.ts` 直接 `createContext(win.electron.ipcRenderer)`，Godot 设置面板直接 import `godot-stage`。方向反了 —— 应该是桌面端把适配器注入共享 UI 的中性 seam，而不是共享 UI 伸手去拿桌面的 `ipcRenderer`。

这些是**意外复杂度**，不是领域复杂度：领域本身需要三端差异，但当前用「共享包知道自己跑在哪个端」的方式表达差异，而不是「每个端注入自己的适配器」。

---

## 4. 质量属性优先级（有取舍）

按本次决策的权重排序：

1. **可维护性 / 局部性**（最高）：让桌面契约的改动不再扩散到 Web/Pocket/服务端的类型检查与构建图。目标：一个桌面 payload 的改动，只触碰桌面契约中枢 + 桌面 app。
2. **可移植性**（次高）：Web / Capacitor / 服务端不应在类型层面依赖 `electron`、`@electron-toolkit/preload`、`NodeJS`。这是三端并存的前提。
3. **可测试性**：`stage-shared` 的纯类型/工具应能在无 Electron 运行时下测试；桌面 IPC 契约应能靠 `vi.mock` 独立测。
4. **成本**（约束）：这是一个已经存在 `src/shared` 契约中枢的仓库，重构成本应当以「文件迁移 + 改 import」为主，不引入新框架抽象。

**取舍**：为了局部性和可移植性，需要付出一次性的移动成本，并且短期内会多一个「桌面专属包/目录」。刻意**不**优先做通用 capability 注入抽象（会提高灵活性，但当前证据不足以证明它值得）。

---

## 5. 选项对比

### 选项 A：维持现状

- **边界**：`stage-shared` 继续作为「桌面 + 三端杂烩」包；桌面契约随功能增长继续往共享包堆。
- **收益**：零迁移成本；桌面与共享类型同处一包，改起来「近」。
- **成本**：Web/Pocket/服务端的类型图持续被 Electron/Node 污染；每次桌面契约变更都在扩大三端耦合面；依赖方向会越来越难逆转。
- **证伪条件**：如果桌面契约此后不再增长、且团队接受三端 typecheck 永远带上 Electron 类型，维持现状是合理且最省的。目前证据不支持这个前提（用户明示耦合在增加）。

### 选项 B（推荐）：治理 `stage-shared` 边界 —— 分离「跨端基元」与「桌面自有契约」

- **边界**：`stage-shared` 只保留真正跨端的纯数据/工具；`eventa:*:electron:*` 地址、`ElectronWindow`/`isElectronWindow`、`global-shortcut`、`godot-stage`、artistry/beat-sync 的 IPC 契约移入桌面契约中枢 `apps/stage-tamagotchi/src/shared/eventa`（或桌面专属契约包）。方向固定为：**桌面契约中枢 → 依赖共享的纯 payload 类型，反之禁止**。
- **收益**：三端 typecheck/build 不再带 Electron/Node 类型；桌面契约改动局部化；`stage-shared` 根 barrel 变成干净的中性入口。
- **成本**：一次文件迁移 + 改 import；需要把 `stage-ui` 里的 Godot 设置场景和 `artistry-autonomous` store 一起迁走（否则 `stage-shared/godot-stage` 移走后共享 UI 会断）。
- **假设**：Godot stage 是桌面专属（当前证据支持：唯一消费者都在桌面主/渲染进程 + 桌面场景组件）；`server-channel-qr` 和 `auth` 是真正跨端（桌面 + Pocket 配对、OIDC 标准），保留在共享。
- **迁移与回滚**：纯移动 + import 重指，`git mv` 可逆；每步都能单独编译验证。

### 选项 C：把 `stage-ui` 的桌面场景整体下沉到桌面专属包（B 的下游子项，可独立推进）

- **边界**：`model-settings` 的 Godot 面板 + runtime、`artistry-autonomous` 移入 `stage-tamagotchi` renderer 或一个新的 `packages/scenarios-stage-tamagotchi-*` 桌面场景包（仓库已有 `scenarios-stage-tamagotchi-browser/electron` 命名先例）。
- **收益**：共享 UI 不再静态 import `godot-stage` / Electron adapter，Web/Pocket 的 bundle 图更干净。
- **成本**：与 B 有依赖（先有 `godot-stage` 契约的新家）；`panel.vue` 的 `Godot` 分支需要改成 slot/注入或条件注册。
- **证伪条件**：如果团队想把「Godot 设置 UI」未来也复用到 Web（目前无证据），则 C 应改为「把 godot-stage 的 schema 留在共享、只迁 UI」。

### 选项 D：引入 surface-agnostic capability/注入 seam（暂缓）

- **边界**：把 `stage-ui` 里散落的 `isStageTamagotchi()/isStageWeb()/isStageCapacitor()` 分支收敛成一个显式能力/适配器接口。
- **收益**：长期最优，消除共享 UI 对「具体端身份」的硬编码。
- **成本**：抽象化风险高，现在只有三个端、分支点分散，证据不足；应在 B/C 完成后、出现第二个真实适配器变体时再做。

---

## 6. 推荐

**推荐选项 B，并把 C 作为它的必经后半段；D 明确暂缓。**

理由：根因不在「桌面端依赖了太多共享包」（那是正常的复用），而在**方向反了** —— 桌面专属契约被放进了被 Web/Pocket/服务端消费的共享包，并通过根 barrel 放大泄漏。治理 `stage-shared` 的边界成本最低、收益最高：它把「谁拥有 Electron 契约」这个决策显性化，而且仓库里已经有 `apps/stage-tamagotchi/src/shared/eventa` 这个现成的正确归属中枢，只需把散落的桌面契约搬过去、让方向单向化。

拒绝 A：因为它把已经可观察到的三端类型污染继续放大，违背「耦合在增加」这个用户给出的前提。拒绝先做 D：在没有第二个适配器变体前，做通用 seam 属于过早抽象。

---

## 7. 迁移与验证（渐进、可回滚）

**第 0 步（先上护栏，不动业务代码）**
在 lint/CI 里加一条架构约束（`eslint-plugin-import` 的 `no-restricted-imports`，或 `dependency-cruiser`）：
- `packages/stage-shared/src/**` 禁止出现 `eventa:invoke:electron:` / `eventa:event:electron:` 字面量；
- `stage-web` / `stage-pocket` / `ui-server-auth` 禁止 import `stage-shared/{electron-renderer,global-shortcut,godot-stage}`。

护栏本身可逆、可单独关闭，但立刻冻结了「继续往共享包堆桌面契约」的趋势。

**第 1 步（最小垂直切片：止血根 barrel）**
把 `artistry` 和 `window` 从 `stage-shared/src/index.ts` 的重导出中移除，改成显式子路径，桌面侧改 import。这一步直接让 Web/Pocket/服务端的 TS 程序不再解析 `ElectronWindow`/`@electron-toolkit/preload`/artistry 的 Electron 地址。
- **退出标准**：`stage-web`、`stage-pocket`、`ui-server-auth` 的 `typecheck` 通过，且 `tsc --traceResolution` 不再命中 `electron`/`@electron-toolkit/preload`。

**第 2 步（迁移桌面专属契约）**
把 `global-shortcut`、`godot-stage`、`electron-renderer.d.ts`，以及 `artistry`、`beat-sync` 中的 Electron 契约定义迁到 `apps/stage-tamagotchi/src/shared/eventa`（或桌面契约包，见开放决策）。`server-channel-qr`、`auth`、`webgpu`、`env-vars`、`error-message`、`perf`、`composables` 留在 `stage-shared`。同时把 `@moeru/eventa` 修正为 `stage-shared` 的运行时依赖（或随迁移把它一并带走）。
- **退出标准**：`rg 'eventa:(invoke|event):electron' packages/stage-shared/src` 返回空；`rg 'godot-stage|global-shortcut|electron-renderer' packages/stage-shared/src` 只剩纯类型（如果有）。

**第 3 步（连带把 `stage-ui` 桌面场景迁出）**
把 `model-settings/godot.vue` 及 `runtime.ts` 中的 Godot 部分、`artistry-autonomous.ts` 移入 `stage-tamagotchi` renderer 或桌面场景包；`panel.vue` 的 Godot 分支改成 slot/注入注册。这一步让 `stage-ui` 不再静态 import `stage-shared/godot-stage`。
- **退出标准**：`stage-ui` 内 `rg 'godot-stage|electron/renderer|ipcRenderer'` 返回空（除注入点）；`stage-web`/`stage-pocket` 的 `build` 产物中不含 `godot-stage` 相关代码（可用 `vite-bundle-visualizer` 验证）。

**全程回滚**：每步都是 `git mv` + 改 import，单步编译/测试通过即合入，任一步失败可单独 revert。

**验证测试**：`global-shortcut` 的 `accelerators.test.ts`、`godot-stage` 的 view-state schema、`beat-sync` 相关测试应随代码一起迁移并保持绿；`stage-tamagotchi` 的 `typecheck`/`build` 全程保持通过。

**暂不构建**：通用 capability 注入抽象（D）；不要顺手把 `stage-ui` 按端拆成多个包（成本高、收益未证实）。

---

## 8. 开放决策（会影响推荐，但不阻塞起步）

1. **桌面契约的新家**：放回 `apps/stage-tamagotchi/src/shared`（零新增包），还是新建桌面专属契约包（若 `stage-ui` 迁出的桌面场景包也要 import 这些类型）？**建议**：先放回 app `src/shared`；只有出现「多个包需要共享桌面契约」的真实压力时，再抽 `packages/stage-tamagotchi-contracts`。
2. **`beat-sync` 的领域是否真跨端**：它被 `stage-ui`/`stage-pages`/live2d/mmd/spine 引用，看起来跨端，但需要产品确认 Web/Pocket 是否启用。只确认后，才能决定「领域类型留共享、IPC 契约迁桌面」的切割线。
3. **Godot 设置 UI 的归属**：迁入 `stage-tamagotchi` renderer，还是桌面场景包（沿用 `scenarios-stage-tamagotchi-*` 先例）？取决于是否希望它与其他桌面场景共享构建。

如果第 1 条选择新建桌面契约包，或第 2 条发现 `beat-sync` 实际是桌面专属，推荐方案的迁移路径会相应收窄，但「`stage-shared` 根 barrel 不得泄漏 Electron」这个核心结论不变。

[EVAL:evolve-software-architecture-loaded]
