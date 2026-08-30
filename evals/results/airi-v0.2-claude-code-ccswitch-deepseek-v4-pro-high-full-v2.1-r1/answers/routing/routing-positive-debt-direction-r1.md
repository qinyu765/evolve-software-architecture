# 建议：把「渲染进程主机桥接（renderer host-bridge）」定为下一条要治理的边界

**结论先行**：AIRI 里桌面端与共享 packages 的耦合，最值得先治理的不是把 `stage-shared` 拆碎，而是**把已经出现两次、但尚未被强制执行的「共享代码通过注入桥接消费桌面能力」这条接缝正式化并补齐**。共享包（`stage-ui` / `stage-pages` / `stage-shared`）应当只依赖中性的能力接口，由 `stage-tamagotchi` 的 preload/main 在启动时注入实现；共享包永远不 import `@moeru/eventa/adapters/electron/*`，也永远不读 `window.electron`。当前有 3 处共享代码直接违反了这个已经在仓库里成型的原则，且作者自己都留了 `TODO`/`FIXME`。这是收益/成本比最高、且完全可逆的下一步。

## 1. 范围与置信度

- **要做的决策**：在桌面端（Electron `apps/stage-tamagotchi`）与共享包（`packages/stage-ui`、`stage-pages`、`stage-shared`）之间，下一条最值得治理的架构边界是哪条。
- **仓库类型判定**：Electron 桌面应用 + 共享 Vue 包的 pnpm/turbo monorepo。注意不是 Tauri（`crates/` 是遗留的旧 Tauri；当前桌面是 Electron），但 skill 里 desktop 适配器关于「主/渲染进程边界、IPC 契约、生命周期」的关注点完全适用。**置信度：高**。
- **历史证据的局限（unknown）**：本次环境是浅克隆（`.git/objects` 指向外部对象库，且读取被拒），我拿不到逐文件的提交频次曲线。因此「耦合正在增加」我主要依据**当前源码中的 TODO/FIXME 标记、3 处已存在的泄漏、以及近期提交集中落在 stage-ui/stage-shared** 来推断，而不是基于一段时间的 diff 统计。这点若你要做 ADR，建议补一次 `git log --follow` 的真实 churn 数据。

## 2. 观察到的事实（可核查）

仓库其实已经有一半正确的答案了：

| 事实 | 证据 | 性质 |
| --- | --- | --- |
| 桌面端是「组合根」，preload 暴露 `window.electron/platform/api`，渲染层用 `useElectronEventaInvoke` 把主进程契约绑定成类型化 invoker，再注入共享 store | `apps/stage-tamagotchi/src/preload/shared.ts:19-20,40`；`apps/stage-tamagotchi/src/renderer/App.vue:100-106,140` | fact |
| 已存在的正确接缝 #1：MCP 工具桥是「接口 + set/get 注入」 | `packages/stage-ui/src/stores/mcp-tool-bridge.ts:29-50` | fact |
| 已存在的正确接缝 #2：plugin-host debug 桥，注释明确写了共享页面不耦合 electron-only import 的理由 | `packages/stage-ui/src/stores/devtools/plugin-host-debug.ts:82-108` | fact |
| 泄漏 #1：共享业务 store 直接 import renderer 适配器、硬编码 channel、`win.electron?.ipcRenderer as any` | `packages/stage-ui/src/stores/modules/artistry-autonomous.ts:4,34,37-44` | fact |
| 泄漏 #2：共享音频模块静态 import `electron-screen-capture`、运行时读 `window.electron.ipcRenderer`，作者留了 `FIXME(Makito)` | `packages/stage-shared/src/beat-sync/detector.ts:11,159-166` | fact |
| 泄漏 #3：共享设置页直接 import renderer 适配器 + `window.electron?.ipcRenderer`，作者留了 `TODO` | `packages/stage-pages/src/pages/settings/providers/artistry/comfyui.vue:5,25-49` | fact |
| 类型级泄漏：`stage-shared` 从 `@electron-toolkit/preload` 引入 `ElectronAPI` 类型，并有全局 `Window` 增强文件 | `packages/stage-shared/src/window.ts:1-12`；`electron-renderer.d.ts`（仅桌面 tsconfig 引用） | fact |
| `electron-screen-capture` 在 `stage-shared` 里是 devDependency，却在 `detector.ts` 运行时静态 import —— 属于依赖方向 + 依赖声明双重错误 | `packages/stage-shared/package.json:43` vs `detector.ts:11` | fact |
| 桌面 RPC 契约与 UI 预设内容混在同一个模块 | `packages/stage-shared/src/artistry.ts:1-23`（`eventa:invoke:electron:*` 契约）vs `:25-200`（图片预设/提示词/图标） | fact |
| 平台分支较广但大多较轻（分析 surface、能力门控）：58 处 `isStageTamagotchi/isStageWeb/isStageCapacitor/RUNTIME_ENVIRONMENT`，跨 stage-ui 19 个文件 | Grep 计数 | fact |
| 近期提交集中在 stage-ui/stage-shared；`vishot-*` 被移出仓库开源 | 提交 `5228f9412`、`1ddb68381`、`834f17f28`、`20416d689` | fact（「解耦是持续方向」是 inference） |

## 3. 当前摩擦

真正的痛点是**同一件事有三种写法**：

- 有的能力走「注入桥」——`mcp-tool-bridge.ts`、`plugin-host-debug.ts`；
- 有的能力走「共享包直接摸 `window.electron`」——`artistry-autonomous.ts`、`beat-sync/detector.ts`、`comfyui.vue`；
- 有的能力走「编译期环境分支」——`isStageTamagotchi()` 散在 19 个文件里。

后果有三条，都是可量化的：

1. **改动被放大**：每加一个桌面能力，开发者没有既定入口可遵循，于是复制最省事的 `window.electron + createContext + as any` 写法，泄漏继续增长（三个 TODO/FIXME 就是证据）。
2. **共享逻辑测不动**：`artistry-autonomous` 的 headless 生成路径、`beat-sync` 的桌面采集路径，测试要么 mock `window.electron`，要么干脆不测——而仓库的测试规范明确反对硬 mock 平台全局。
3. **依赖方向已经倒转**：`stage-shared`（被 web/desktop/pocket 共同依赖）运行时依赖了 `@proj-airi/electron-screen-capture`（桌面专用包），还放在 devDependencies 里。这会让 web 构建背上一段根本不会执行的桌面代码，也让 `stage-shared` 的语义继续漂移成「杂物抽屉」（auth、beat-sync、global-shortcut、godot-stage、webgpu、electron-renderer 全在一个包的子路径导出里）。

（inference）「耦合在增加」的直接机制就是：**边界没有被声明，也没有被工具强制**，所以新代码会自然趋向于直接 import 而不是注入。

## 4. 质量属性优先级

| 优先级 | 属性 | 目标 | 现状证据 | 哪一选项改善它 | 可能回退什么 |
| --- | --- | --- | --- | --- | --- |
| 1 | 可维护性 / 局部性 | 加一个桌面能力只改两处：共享接口定义 + 桌面注入 | 同能力三种写法，改动四处散落 | Option B | 迁移期一次性成本 |
| 2 | 可测试性 | 共享业务逻辑可在无 Electron 下用 mock 桥测试 | `window.electron` + `as any` 逼出全局 mock | Option B | —（桥本身就能 mock） |
| 3 | 可移植性 | web/Capacitor 构建零 Electron 代码 | `stage-shared` 运行时依赖 electron-screen-capture | Option B | 无 |
| 4 | 进程边界稳定性 | IPC 契约集中、可版本化 | Eventa 契约已集中，但绑定动作泄漏进共享包 | Option B | 无 |

明确不追求：性能、资源占用——本次决策不改变运行时路径，只改绑定位置。

## 5. 选项对比

### 选项 A：维持现状

- **边界与所有权**：无明确边界；桌面能力既属于共享包（契约+绑定），也属于桌面 app（实现）。
- **优势**：零迁移成本；代码能跑。
- **代价**：泄漏持续累积；共享包继续吞入 Electron 类型和运行时依赖；`as any` 成为模板化写法；测试退化。
- **什么证据会推翻它（证明现状是对的）**：如果团队决定所有含桌面能力的页面永久只在桌面端、永不进共享包——但现状（共享 devtools/settings 页面已经承载插件 host、MCP、Godot、artistry）直接否定了这一点。

### 选项 B：正式化「渲染进程主机桥接」接缝（推荐）

- **边界与所有权**：
  - 共享包拥有**能力接口**（如 `McpToolBridge` 一样的小 interface）和**纯契约/schema**；
  - 桌面 app（preload/main + renderer `App.vue` 组合根）拥有**绑定**（`defineInvoke(context, contract)`、`setupElectronScreenCapture` 等）并负责注入；
  - 用一条 lint 规则禁止共享包 import `@moeru/eventa/adapters/electron/*` 和读 `window.electron`。
- **它解锁的变化**：每加一个桌面能力，只需（1）在共享包加一个 typed bridge 接口 +（2）在桌面 `App.vue` 注入实现。web/pocket 自动得到「此能力不可用」的清晰错误。
- **引入的假设**：每个能力都能在启动时一次性注入（当前桥都满足）；模块级 `set/get` 足以承载（不必上 DI 容器）。
- **迁移与回滚成本**：分 3 个小 PR 逐点搬移（见下），每步独立可回滚；行为不变。
- **证据会使它错误的情况**：如果未来出现「同一能力在窗口生命周期中途需要热切换实现」或第三个类桌面平台，则可能需要升级为 DI token——但那是以后的事，不是现在不做的理由。

### 选项 C：做一个通用平台抽象层 / PlatformCapabilities 框架

- 用一个 `injeca`/Pinia 插件统一注入所有平台能力。
- **为什么现在不做**：只有 web/desktop（外加 Capacitor）两三个真实变体；通用 provider 会**在变体点还没稳定前就引入间接层**，把每个能力的小接口藏进一个大对象里。等第三个类桌面平台真的出现再升级不迟。（推断）

### 选项 D：拆 `stage-shared` 杂物抽屉（global-shortcut/godot-stage/electron-renderer/桌面契约 + UI 预设各归其位）

- 这是对的，但**是 B 之后的机械清理**，不应先做：只拆包而不解决行为泄漏，`window.electron` 访问照样留在共享代码里；且它 churn 面大。建议作为 B 的第二步顺序执行。

## 6. 建议

选 **Option B**，把这条规则立为边界并补齐：

> **`packages/stage-ui`、`packages/stage-pages`、`packages/stage-shared` 不得依赖 Electron 适配器入口或 `electron*` 包；桌面能力一律通过宿主注入的 bridge 消费。**

理由：它不是一个新发明，而是把仓库里**已经自我声明的正确模式**（`mcp-tool-bridge.ts`、`plugin-host-debug.ts` 的注释）变成可执行的约束；它是一道小而深的接缝——接口极小、杠杆极大、每一步可逆；它同时解决依赖方向倒转（`stage-shared → electron-screen-capture`）、`as any` 模板化、和共享逻辑测不动三个问题。

被否决的替代：C（过早抽象）、D 先行（churn 大且没先堵住行为泄漏）、A（现状不可持续）。

## 7. 迁移与验证（渐进、可回滚）

**第 0 步 — 先立规则，不改行为**：在共享包加一条 `no-restricted-imports`（或等价 ESLint/oxlint 规则），禁 `@moeru/eventa/adapters/electron`、禁 `window.electron`/`win.electron`/`globalThis.window.electron`、禁共享包对 `@proj-airi/electron-screen-capture` 的运行时 import。这一步让边界立刻可见，暴露全部违规点（目前 3 处 + `window.ts` 类型导入）。同时跑一次仓库已有的 `knip`，确认没有共享包漏依赖 `electron*` 包。

**第 1 步 — 首个纵向切片：`beat-sync/detector.ts`**（最干净、测试收益最大）：给 detector 注入一个 `createScreenCaptureSource` 适配器，替代 `case StageEnvironment.Tamagotchi` 里直摸 `window.electron` + 动态 import renderer 适配器；桌面侧（beat-sync 窗口/`App.vue`）用现成的 `useElectronScreenCapture(...)` 构建后注入。这一步同时消除 `stage-shared → electron-screen-capture` 的运行时依赖和 `FIXME`，并把 `electron-screen-capture` 从 devDep 改成正确的声明位置。

**第 2 步：`artistry-autonomous.ts`**：定义 `HeadlessArtistryBridge`（`generate` + `addWidget`），用 `set/get` 注入；把 `defineInvoke`/`createContext`/channel 绑定全部移到桌面 renderer（桌面对应的 `widgets` 内置工具已经在 renderer 里用 `useElectronEventaInvoke` 组装）。这一步移除共享 store 里的 `as any` 和 `@moeru/eventa/adapters/electron/renderer` import。

**第 3 步：`stage-pages/comfyui.vue`**：页面消费注入的 `testComfyUIConnection` 函数，IPC 绑定移入桌面。共享页面只负责 UI 状态机。

**第 4 步 — 类型边界**：把 `window.ts` 的 `ElectronWindow` + `electron-renderer.d.ts` 全局增强移进 `packages/electron-vueuse`（或桌面 types 包）；`isElectronWindow` 改成结构判断（`'electron' in window`），不再 import `@electron-toolkit/preload` 类型。这样 web 消费 `stage-shared` 根导出时不再拖着 Electron 类型。

**第 5 步（可选、后置）：拆 `stage-shared`**：把 `eventa:invoke:electron:*` 契约、`global-shortcut`、`godot-stage` 归入桌面契约包；把 `artistry.ts` 里的 UI 预设迁到 `stage-ui`/`stage-pages`。

每步都是独立 PR、可独立回滚，web 行为不变（原分支本来就 fall-through），桌面行为不变（函数还是那几个函数，只是绑定位置换了）。

**验证与完成标准**：
- `pnpm lint` 在边界规则开启下零违规；`knip` 无共享包依赖 `electron*`。
- `stage-web` 产物中不含 `ipcRenderer`/electron 适配器代码（用已有的 `vite-bundle-visualizer` 或对 dist 做一次 grep 即可）。
- 共享包单测全部用 mock bridge 通过，测试文件里不再出现 `window.electron`。
- `stage-tamagotchi` typecheck + renderer 冒烟通过。
- review diff 时确认：web 路径零改动、共享包只删 Electron 引用。

## 8. 待定决策（会改变建议的问题）

1. **桌面 Eventa 契约到底归谁**：中性 `stage-shared`（符合仓库「契约集中定义」的现有惯例），还是桌面专属 contracts 包（更符合「只有桌面 main 实现」的事实）。这决定第 5 步怎么拆，以及 bridge 接口的 import 方向。
2. **bridge 用哪种形态统一**：继续用模块级 `set/get`（与 `mcp-tool-bridge` 一致），还是升级为 `injeca`/Pinia token。现在 renderer 只有简单版，建议在加第 4、5 个桥之前先定调，避免又长成两套风格。
3. **`stage-pocket`（Capacitor）是否纳入同一条接缝**：`isStageCapacitor` 说明它是第一类平台；它若也要消费同类能力，现在就把 bridge 设计成三平台通用，而不是只服务桌面。

需要的话，我可以把第 0–1 步整理成一份 ADR 草稿（按仓库 `docs/solutions/` 的 YAML frontmatter 格式），以及那条 lint 边界规则的具体配置——但按你的要求，本轮只给建议、不改代码。

[EVAL:evolve-software-architecture-loaded]
