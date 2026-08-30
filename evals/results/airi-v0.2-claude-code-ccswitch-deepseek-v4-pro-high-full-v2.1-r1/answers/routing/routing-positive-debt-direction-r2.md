# AIRI 桌面端与共享 packages 耦合：架构边界评估

## 0. 结论先行

下一条最值得治理的边界不是“把桌面代码从共享包里全部搬出去”，而是一条**更窄、可验证、可逆的规则：共享 stage 包在模块加载层面必须保持环境中立**（`stage-shared` / `stage-ui` / `stage-layouts` / `stage-pages` 不得静态 import Electron 运行时）。第一步只改一处：把 `stage-shared/beat-sync` 里对 `@proj-airi/electron-screen-capture/renderer` 的静态 import 改为按需动态 import，并补一条架构守卫（lint/依赖检查）防止回退。更大规模的“拆分 stage-shared / 引入 capability 抽象层”暂不做，等出现第二个具体的运行时泄漏案例再启动。

## 1. 范围与置信度

- **被评估对象**：`apps/stage-tamagotchi`（Electron 桌面端）与 `packages/` 中共享包的依赖方向与模块边界。
- **仓库类型**：pnpm monorepo，多环境（Electron / Web / Capacitor）共享一套 Vue 业务层。置信度高。
- **限制（未知）**：本会话 Bash 被禁用，`.git/logs/HEAD` 显示这是一次浅克隆（仅 clone/checkout 两条记录），因此我**无法独立核对完整 Git 历史**来验证“耦合正在增加”的趋势。下面的判断主要来自当前静态结构；趋势部分按“推断”处理。环境上下文中给出的 5 条近期提交（如 `1ddb68381 fix(stage-ui): preserve Kokoro worker on abort`、`20416d689 refactor(vishot-*): remove packages`）说明 `stage-ui` 与场景截图包是近期活跃改动点，但不足以单独证明耦合方向。

## 2. 观察到的事实

依赖方向是干净的（事实）：

- 没有任何 `packages/*` 代码反向 import `@proj-airi/stage-tamagotchi` 或 `apps/stage-tamagotchi/src`（grep 只命中 README 与一处注释）。桌面端 → 共享包的单向依赖成立。

唯一真实的**运行时**泄漏（事实）：

- `packages/stage-shared/src/beat-sync/index.ts:1` 直接 `export * from './detector'`。
- `detector.ts:11` **静态** import `setupElectronScreenCapture` from `@proj-airi/electron-screen-capture/renderer`。
- `detector.ts:159-193` 里 `StageEnvironment.Tamagotchi` 分支才调用它；`detector.ts:165` 的 Eventa Electron adapter 已经是动态 import（旁边还挂着 `FIXME(Makito): Will refactor later`，见 `detector.ts:164`）——也就是说**同一文件里已经有正确的懒加载范式，只是屏幕捕获这条没跟上**。
- 这条边通过 `stage-ui/src/stores/settings/index.ts:14`（`export * from './beat-sync'`）进入 `@proj-airi/stage-ui/stores/settings`，而 `apps/stage-web/src/App.vue:13`、`pages/index.vue:21` 都 import 了该入口；`packages/stage-pages/src/pages/settings/modules/index.vue:3` 也经 `use-modules-list.ts:3` 走到 `stage-shared/beat-sync`。
- `electron-screen-capture` 的 `index.ts:1` 与 `renderer.ts:1` 目前对 `electron` 都是 type-only import（事实），所以**今天 Web 构建大概率不会崩**（推断），但这仍然是一条未受控的跨环境依赖边。

桌面专属的“契约/纯函数”模块与真正跨平台模块混在同一包（事实）：

- `stage-shared` 的子路径同时暴露 `./global-shortcut`、`./godot-stage`、`./server-channel-qr`、`./electron-renderer`（桌面形态）和 `./auth`、`./composables`、`./webgpu`、`./perf`（跨平台/中立）。
- 但其中 `global-shortcut/accelerators.ts` 是**纯解析/格式化**，没有任何 Electron 运行时 import（事实），注释还明确为未来 C# 驱动保留结构化输出——这是“桌面形态但中立”的好样板，不应误伤。

环境分支正在共享层扩散（事实，量化）：

- `isStageTamagotchi|isStageCapacitor|isStageWeb|isElectronWindow` 在 `packages/` 内共 **106 处、33 个文件**，横跨 `stage-shared`、`stage-ui`、`stage-layouts`、`stage-pages`、`stage-ui-live2d`。典型如 `stage-layouts/src/layouts/settings.vue:2`、`stage-pages/src/pages/settings/flux.vue:4`、`stage-ui/src/stores/analytics/posthog.ts:5`。

依赖声明与运行时不一致（事实）：

- `stage-layouts` 与 `stage-pages` 的 `package.json` 都把 `@proj-airi/stage-shared` 放在 **devDependencies**，但运行时 `.vue/.ts` 却在 import（例如 `stage-layouts/src/layouts/default.vue:2`、`stage-pages/src/pages/settings/providers/artistry/comfyui.vue:7`）。目前被 app 层（`apps/stage-web/package.json:40` 的 `stage-shared` 依赖）掩盖（推断），但边界未治理。

## 3. 当前的摩擦

真正的变化放大点不是“桌面端依赖共享包”本身（这是健康的复用），而是这三件事叠加：

1. **共享包承载了 Electron 运行时**：`stage-shared/beat-sync` 是唯一一条静态运行时泄漏，但它把“Web 也能 import 的共享入口”和“Electron 屏幕捕获”绑死在同一模块加载路径上。
2. **环境判断内联散落**：33 个文件里的 106 处 `isStage*` 分支意味着每加一个“桌面与 Web 行为不同”的功能，改动会同时触碰布局、页面、store、composable。`environment.ts` 的编译期开关本身是合理的（可 tree-shake），问题在**分支的放置位置**没有规则。
3. **包身份不清**：`stage-shared` 这个名字无法告诉调用者“什么能安全 import、什么只在桌面端有语义”，`stage-layouts/stage-pages` 的 devDependency 错配就是这种不清的直接症状。

## 4. 质量属性优先级（含取舍）

| 优先级 | 属性 | 理由与取舍 |
|---|---|---|
| 1 | **可演进性 / 可维护性** | 共享层是高频改动点；目标是最小化“改一个环境、伤另一个环境”的意外。 |
| 2 | **构建/依赖正确性** | 消除跨环境运行时泄漏与依赖声明错配；用守卫把正确性锁住。 |
| 3 | **可测试性** | 让共享 detector 能在 jsdom/vitest 里脱离 Electron 测试；不动运行时行为。 |
| 4 | **成本 / 可逆性** | 拒绝一次性大重构；先做单点修复 + 规则，行为不变、可回滚。 |

明确放弃：**运行时性能**（编译期环境常量已 tree-shake，当前无性能问题）、**大一统的 capability/DI 抽象**（在只有一个具体泄漏点时属于过度设计，违背仓库里“避免浅模块/透传服务”的规范）。

## 5. 选项

### 选项 A：维持现状
- 边界：不设边界，共享包继续同时承载多环境代码。
- 好处：零迁移成本；`environment.ts` 编译期开关目前确实能跑。
- 代价：分支持续累积；`stage-shared/beat-sync` 的静态 Electron import 是悬而未决的隐患（一旦 `electron-screen-capture` 引入运行时 `electron` import，Web 构建会坏）；依赖声明错配继续靠巧合工作。
- 会让该选项“错”的证据：出现第二个共享包静态 import Electron 运行时，或 `isStage*` 分支在半年内明显继续增长。

### 选项 B：治理“模块加载中立”边界（推荐）
- 边界：共享包不得静态 import `@proj-airi/electron-*` / `electron` 运行时；环境专属运行时只能经 app 拥有的接线点（如 `apps/stage-tamagotchi/src/renderer/beat-sync.main.ts`）或专用 electron 包注入。
- 好处：把“什么算共享”变成一个可 lint 的规则；一步修复当前唯一泄漏；保留现有 `createBeatSyncDetector({ env })` 策略接缝（它已经是对的形态，只是绑定时机错了）。
- 代价：需要一次小改动 + 一条守卫规则；要接受“type-only 的 electron 类型 import 仍允许”（`window.ts:1` 的 `ElectronAPI` type import 属于低优先级，暂不动）。
- 会让该选项“错”的证据：如果守卫规则被证明误伤大量合法共享代码，或团队判定共享包本就允许承载桌面端代码，那就回到 A。

### 选项 C：拆分 `stage-shared` + 引入环境 capability 抽象（暂缓）
- 边界：把 `global-shortcut`/`godot-stage`/`server-channel-qr`/`electron-renderer`/`beat-sync` 桌面半区搬进桌面拥有的契约包，并用注入的 capability 接口替换 33 个文件里的 `isStage*` 内联分支。
- 好处：从根上消除“共享层分支散落”。
- 代价：大、风险高、需触碰 6 个包 33 个文件；在只有一个运行时泄漏点时是投机性抽象，容易产出浅模块。**不作为下一步**，作为 B 之后的“若需要”路线。

## 6. 建议

**采用选项 B**，并明确“长期 = 可逆演进”：

- 稳定不变的是：`environment.ts` 的编译期环境枚举与 `createBeatSyncDetector({ env })` 的策略接缝（它们已经能表达“同一概念、按环境不同实现”）。
- 需要变的是：**实现代码的归属**——Electron 实现不得在共享包加载期被静态绑定。
- 尚未可知的是：Web 包当前是否真的把 `electron-screen-capture` 打进去了（见 §7 验证）。

拒绝 A（把隐患留给未来）与 C（在证据不足时做大抽象）。

## 7. 迁移与验证（渐进、可回滚）

1. **第一个纵向切片（核心）**：把 `detector.ts:11` 的静态 import 改成 `StageEnvironment.Tamagotchi` 分支内的 `await import('@proj-airi/electron-screen-capture/renderer')`，与 `detector.ts:165` 的 Eventa adapter 写法对齐，并顺手消掉 `detector.ts:164` 的 `FIXME`。行为不变（该分支本就只在 Tamagotchi 执行），纯单点、可回滚。
2. **修复依赖声明**：把 `stage-layouts`、`stage-pages` 的 `@proj-airi/stage-shared` 从 devDependencies 移到 dependencies。
3. **加守卫**：为 `stage-shared`/`stage-ui`/`stage-layouts`/`stage-pages` 加 ESLint `no-restricted-imports`（或依赖图检查），禁止静态 import `@proj-airi/electron-*` 与 `electron` 运行时（type-only import 白名单放行）。
4. **验证**：
   - `pnpm lint` + 各 workspace `typecheck` 通过；
   - 为 `createBeatSyncDetector({ env: Web })` 补一条 vitest：在 jsdom 里只跑 Web 分支，断言不解析 `electron-screen-capture`；
   - 用 `pnpm -F @proj-airi/stage-web build` 后扫描产物（`vite-bundle-visualizer` 已在 `stage-tamagotchi` devDeps 里），确认 Web 包不再触及 `@proj-airi/electron-screen-capture`——这一步同时回答“未知：是否真被打包”；
   - 回归 `apps/stage-tamagotchi/src/renderer/beat-sync.main.ts` 桌面链路（typecheck + 现有测试）。
5. **完成标准**：守卫规则生效、Web 构建产物无 Electron 屏幕捕获引用、桌面 beat-sync 行为回归通过。
6. **暂不做**：拆分 `stage-shared`、引入 capability 层、迁移 `isStage*` 内联分支——等出现第二个具体运行时泄漏案例，或量化看到分支数持续增长，再开 ADR 重新评估。

## 8. 待决问题（只有这些答案会改变建议）

1. **`stage-shared` 的长期身份**：团队是想让它继续做“多子路径的单包”（并在 README 明确“哪些子路径是环境专属、哪些中立”），还是拆成 `stage-shared`（中立）+ `stage-electron-contracts`（桌面契约）？这取决于发布/命名偏好，不影响第 1-3 步，但影响后续走向。
2. **`isStage*` 内联分支的定位**：是接受“编译期环境常量”作为长期合法机制（只治理放置位置），还是未来改用注入式 capability？只有出现第二个泄漏或分支失控时才需要回答。
3. **旧 `useSettings` 聚合 store**（`stage-ui/src/stores/settings/index.ts:24-30` 已标 `@deprecated`）仍在把 `beat-sync` 等子 store 汇聚到一起，与“环境中立”边界有轻微张力；是否按 `@deprecated` 计划删除，需要单独确认，不阻塞本次建议。

[EVAL:evolve-software-architecture-loaded]
