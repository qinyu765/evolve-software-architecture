## 1. 范围与置信度

问题：AIRI 桌面端（`@proj-airi/stage-tamagotchi`）与共享 packages 的耦合在加深，要选出一条最值得治理的架构边界，比较维持现状与重构，给出渐进路线。

仓库类型（置信度高）：pnpm + turbo 的 Electron/Vue monorepo，桌面端是 `apps/stage-tamagotchi`，共享层集中在 `packages/stage-shared`、`stage-ui`、`stage-pages`、`stage-layouts`。我的结论基于可读到的源码与 package 清单；**历史趋势这一点我无法离线验证**——`.git/logs/HEAD` 里只有一次 clone + checkout（无逐文件历史），系统快照里的 5 条近期提交主要是 `stage-ui` 的改动和 vishot 包移出。所以“耦合在增加”我当作你的前提接受，我能直接证实的是**当前结构性耦合已经存在并具有你说的失效模式**。

## 2. 观察到的证据（事实）

**桌面端对共享层的依赖规模**（`apps/stage-tamagotchi/package.json`）：
- 运行时 workspace 依赖 17 个（`package.json:58-75`）：`stage-ui`、`stage-pages`、`stage-layouts`、`stage-ui-three/live2d/mmd/spine`、`stage-shared`、`server-sdk`、`plugin-sdk-tamagotchi`、`audio`、`pipelines-audio` 等。
- dev 依赖再加 7 个（`package.json:163-171`）：`stage-shared`、`server-runtime`、`plugin-sdk`、`electron-eventa/screen-capture/vueuse` 等。

**关键反直觉事实**：桌面主进程没有引用任何渲染层 UI 包（`stage-ui`/`stage-pages`/`stage-layouts` 零直接引用），它只引用 `stage-shared`（auth、godot-stage、server-channel-qr、global-shortcut、artistry）、`server-runtime`、`plugin-sdk*`、`electron-*` 和 i18n locales。所以问题不在主进程，而在 `stage-shared` 这个共享包本身混入了桌面专属契约。

**`stage-shared` 是一个混合受众的包**（`packages/stage-shared/package.json:17-27`），同时被 11 个消费者依赖：`stage-ui`、`stage-pages`、`stage-layouts`、`stage-ui-three/live2d/mmd/spine`、`stage-web`、`stage-pocket`、`ui-server-auth`、`stage-tamagotchi`。它内部的模块分属两类：

| 模块 | 实际受众 | 是否 Electron 专属 |
|---|---|---|
| `global-shortcut/*` | 仅 `stage-tamagotchi`（8 处引用全在 app 内） | 是（Electron accelerator 格式化） |
| `electron-renderer.d.ts` | 仅 tamagotchi 的 `tsconfig.json:42` | 是（`Window extends ElectronWindow`） |
| `window.ts` | tamagotchi preload + beat-sync 内部 | 是（`import type { ElectronAPI } from '@electron-toolkit/preload'`，`window.ts:1`） |
| `artistry.ts` | tamagotchi main/renderer + `stage-pages` 的 ComfyUI 页 | 部分是（`eventa:invoke:electron:*`，`artistry.ts:11-23`） |
| `beat-sync/eventa.ts`、`detector.ts` | `stage-ui`、`stage-pages`、`stage-ui-live2d`、tamagotchi | 是（`eventa:invoke:electron:*` 与 `electron-screen-capture` 值导入） |
| `godot-stage/*` | tamagotchi + `stage-ui`（godot 设置组件） | 否（纯 Valibot schema，但领域是桌面 Godot 舞台） |
| `auth/pkce`、`server-channel-qr`、`beat-sync/types+settings`、`environment`、`webgpu`、`composables`、`url`、`env-vars`、`error-message` | 跨 web/pocket/tamagotchi | 否（真正跨平台） |

**最尖锐的证据**是 `beat-sync`：`packages/stage-shared/src/beat-sync/index.ts:1-2` 把 `detector` 和 `eventa` 一起 barrel 导出；`detector.ts:11` 是 `import { setupElectronScreenCapture } from '@proj-airi/electron-screen-capture/renderer'`（**值导入**，不是 type-only）。于是 `stage-ui` 的 `stores/settings/beat-sync.ts`、`stage-pages` 的 `settings/modules/beat-sync.vue`、`stage-ui-live2d` 的 `Model.vue` 只要 `import ... from '@proj-airi/stage-shared/beat-sync'`，就把 Electron 屏幕捕获代码带进了 web 的模块图/类型检查图。运行时它被 `isElectronWindow(window)` 守卫（`detector.ts:160-166`）挡住，但**构建解析与类型检查的耦合已经发生**。

另一个味道：`artistry.ts` 里的 Electron 事件契约被 root 再导出（`packages/stage-shared/src/index.ts:1` `export * from './artistry'`），因此任何 root 消费者（`stage-pages`、`stage-layouts`、`stage-ui`）的 graph 里都挂着 `eventa:invoke:electron:*` 地址。

**桌面端已有自己的契约家**：`apps/stage-tamagotchi/src/shared/eventa/index.ts` 是一个 500+ 行的主↔渲染 IPC/RPC 契约枢纽，已经在从 `stage-shared` 反引类型（`global-shortcut`、`godot-stage`、`server-channel-qr`，见其 `:7-18`），并且已经承载了 `eventa:invoke:electron:*` 的绝大多数定义。这说明正确的归属地已经存在，只是部分契约“放错了包”。

## 3. 当前摩擦点

1. **变更放大**：改一个桌面专属契约（新快捷键类型、新 artistry 事件、beat-sync 抓屏参数）会触发 `stage-shared` 的 typecheck/rebuild，涟漪到 11 个消费者，其中包括 web、pocket、three/live2d/mmd/spine 这些根本不用该功能的平台。
2. **“共享”名不副实**：`stage-shared` 名为共享，实际声明了 Electron dev 依赖（`@electron-toolkit/preload`、`@proj-airi/electron-screen-capture`，`package.json:39-45`），且 `detector.ts` 用 devDependency 做值导入——这是 `private: true` 下才不炸的隐性依赖，也是边界失守的标志。
3. **无规则可守**：没有任何 lint/knip/typecheck 守卫阻止下一个 desktop 功能继续落进 `stage-shared`。路径依赖会让它继续恶化——新人会照抄现有 `global-shortcut`/`artistry` 的模式。

## 4. 质量属性优先级

1. **可维护性 / 变更局部性**：桌面改动不应影响 11 个消费者的类型检查与构建。这是最主控的属性。
2. **可移植性 / 构建隔离**：web、pocket、模型渲染包不得解析 Electron 模块（`electron-screen-capture`、`@electron-toolkit/preload`）。这是可观测的硬约束。
3. **模块边界完整性**：“shared”必须有可执行的语义（跨平台），而不是一个什么都放的桶。
4. **成本 / 迁移风险**：作为制衡——方案必须渐进、可回滚，不能一次性重排整棵树。
5. **运行时性能**：不主控（现有 `isElectronWindow` 守卫已隔离运行时行为，这是构建期/类型期问题）。

## 5. 方案对比

### 方案 A：维持现状（保留 `stage-shared` 混合受众）

- **边界与所有权**：无明确边界；`stage-shared` 继续同时拥有跨平台契约与桌面专属契约。
- **收益**：单一 import 面、零迁移成本、subpath exports 已隔离大多数消费者、运行时守卫有效。
- **代价**：web/pocket 的模块图与类型检查持续解析 Electron 依赖；桌面改动放大到 11 个消费者；root barrel 无原则（`artistry` 预设、`error-message`、`window` 类型混在一起）；无守卫阻止进一步泄漏。
- **何时“维持现状”是错的**：只要 web/pocket 的构建必须能干净解析 `electron-screen-capture`，或团队希望 `stage-shared` 有可执行边界，现状就不成立。证据显示第一条已经发生（`detector.ts` 的值导入被 barrel 导出）。

### 方案 B：把 `stage-shared` 治理成“平台中立包”，桌面契约迁回桌面端

- **边界与所有权**：`stage-shared` = 跨平台纯逻辑（类型、schema、环境标志、composable），**禁止 Electron 导入**；桌面专属契约归 `apps/stage-tamagotchi/src/shared`（已存在的契约枢纽），或需要被插件外部消费时归一个 `stage-tamagotchi-*` 包。
- **收益**：恢复清晰平台缝；web/pocket 构建不再解析 Electron 模块；桌面改动只影响桌面端；规则可 lint/CI 强制执行；与现有 `src/shared/eventa` 归属一致。
- **代价**：import 改写、迁移期的临时 shim、需逐模块裁决（godot-stage/artistry 跨界的部分）、需新增守卫防回潮。
- **何时“重构”是错的**：如果这些契约真的在 web/桌面之间共享运行时语义（证据显示不是——`eventa:invoke:electron:*` 地址本身就是桌面专属），或团队更看重“一个 import 全都有”的便利。若迁移中暴露出隐藏的跨平台消费者，回退到方案 A 成本低。

## 6. 建议

**采纳方案 B，但把迁移拆成“先立规、后搬家、再拆分跨界模块”三个阶段，第一阶段之后任何一步都可停、可回滚。** 首选治理的边界就是 `stage-shared` 的平台中立性——它是唯一能同时解决“变更放大”“Electron 泄漏进 web 构建”“无守卫”三个摩擦点的缝。

拒绝的替代方案：
- 治理“桌面端嵌入 server-runtime/channel-server/http-server”是产品架构问题（桌面端兼作 server host），不是“与共享包耦合”问题，且体量更大、风险更高，不应作为第一步。
- 治理 `plugin-sdk` vs `plugin-sdk-tamagotchi` 已经是分离的边界，不是当下最痛点。
- 治理 `scenarios-stage-tamagotchi-*` 住在 `packages/` 只是命名/位置问题，ROI 低。

## 7. 渐进路线与验证

**第 0 步（先立规，最高杠杆、零风险）**：在 `AGENTS.md` 或一条 ADR 里写下规则：“`stage-shared` 平台中立，禁止 `electron`/`@electron-toolkit`/`electron-*` 工作区包导入，禁止 `eventa:invoke:electron:*` 地址；桌面 IPC 契约只放 `apps/stage-tamagotchi/src/shared`。” 配一个廉价守卫：ESLint `no-restricted-imports` 规则或一个 grep 型 typecheck 测试，命中 `stage-shared/src` 里的 Electron 导入即失败。这一步立即止血，防止新功能继续落入。

**第 1 步（无争议模块直接搬家）**：把 `global-shortcut/*`、`electron-renderer.d.ts`、`window.ts` 迁到 `apps/stage-tamagotchi/src/shared`，改写 tamagotchi 内约 15 处 import 和 `tsconfig.json` 的 types 引用。这三个模块**只有** tamagotchi 消费，所以无需 shim、无反向依赖，删掉即完成。验证：`pnpm typecheck` + `pnpm lint` 全绿，且 `grep` 确认 `stage-shared/src` 不再有这三个模块的引用。

**第 2 步（拆 `beat-sync`，真正摘掉 web graph 里的 electron-screen-capture）**：`types.ts`/`settings.ts`（纯）留在 `stage-shared`；`eventa.ts` 和 `detector.ts` 中 Electron 抓屏部分迁到 app。`stage-ui`/`stage-pages`/`stage-ui-live2d` 继续只 import 纯 subpath，不需要改它们的调用方。验证：`pnpm -F @proj-airi/stage-web build` 成功且不再解析 `electron-screen-capture`；`stage-shared` 的依赖清单里删掉 `electron-screen-capture` 后类型检查仍通过。

**第 3 步（`artistry` 拆分）**：把 `artistrySyncConfig`/`artistryGenerateHeadless`/`artistryTestComfyUIConnection` 三个 `eventa:invoke:electron:*` 契约迁到桌面 eventa 层；`stage-pages` 的 ComfyUI 页改为从桌面边界注入“测连接”能力，而不是从 `stage-shared` root import。预设数据（`REPLICATE_*_PRESETS`）单独裁决归属——见待决问题。验证：`stage-pages` 不再从 root import `artistry`，root barrel 不再导出 Electron 契约。

**第 4 步（锁定）**：把第 0 步的守卫接进 CI；跑一次 `pnpm knip` 检查死导出/未用导出；在 `docs/solutions` 或 ADR 记录边界与迁移理由。**完成判据**：`stage-shared/src` 内仅剩环境标志字符串 `'electron'`（`environment.ts:22` 的运行时探测，合法），无任何 Electron 模块导入。

**回滚**：每一步都是独立可回滚的 import 重写；第 0 步是纯规则+测试，随时可删；第 1–3 步若发现隐藏消费者，git 回退单步即可，不影响其他阶段。

## 8. 待决问题

1. **`godot-stage/*` 归属**（会改变方案）：它是纯 Valibot schema，但领域是桌面 Godot 舞台；同时被主进程和 `stage-ui` 消费。若移入 app，`stage-ui`（共享包）会产生“包依赖 app”的反向依赖；若留在 `stage-ui`，主进程会拉 Vue UI；若留 `stage-shared`，则需把规则放宽为“允许中性 schema”。我倾向**第一阶段先不动它**，待前两步完成后用“是否有 web 渲染路径真正使用它”来决定。
2. **`artistry` 预设数据归属**：它是产品配置（Replicate/ComfyUI 预设），本身平台中立，目前却被绑在 Electron 契约里。需要确认 web 端是否也会用 imagegen 预设；若是，preset 数据应留在共享层（单独 subpath），仅契约搬家。
3. **是否需要一个 `stage-tamagotchi-contracts` 包**：目前只有 `stage-tamagotchi` 和 `stage-pages` 消费这些契约；若未来插件（如 `airi-plugin-game-chess` 已依赖 `plugin-sdk-tamagotchi`）需要 import 桌面契约，则包边界比“app 内 `src/shared`”更合适。现在不建，等出现第二个外部消费者再建。

[EVAL:evolve-software-architecture-loaded]
