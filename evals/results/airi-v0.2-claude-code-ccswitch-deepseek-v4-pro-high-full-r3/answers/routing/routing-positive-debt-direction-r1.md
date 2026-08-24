## 1. 范围与置信度

**决策对象**：AIRI 桌面端（`apps/stage-tamagotchi`）与共享 packages（尤其 `packages/stage-shared`、`stage-ui`、`stage-pages`、`stage-layouts`）之间，下一条最值得治理的架构边界。

**仓库分类置信度**：高。这是一个 pnpm monorepo + Electron 桌面的多端（web / capacitor / electron）共享 UI 架构。我基于只读检查（无 Bash，用 Glob/Grep/Read）确认了目录、`package.json`、Vite 配置、以及 28 个文件中的环境分支使用点。

一句话结论先行：**最值得治理的边界是"桌面宿主的契约与能力归属"——具体落点是 `stage-shared` 这个包。它目前同时扮演"跨端中立工具包"和"桌面 IPC 契约/环境检测的宿主"，而桌面契约已经有另一个规范归宿（`apps/stage-tamagotchi/src/shared`）。先把 Electron 契约与行为从共享包迁回桌面 app、再把 `isStageTamagotchi()` 行为分支收敛为注入式宿主能力接口。**

---

## 2. 观察到的事实（附证据）

**F1｜`stage-shared` 是一个混合环境、无 build 的"杂物包"。**【事实】
- `package.json` 的 description 只有 "Shared"；`exports` 同时暴露 `auth`、`beat-sync`、`global-shortcut`、`godot-stage`、`server-channel-qr`、`electron-renderer`、`webgpu`、`composables`（`packages/stage-shared/package.json:17-27`）。
- 没有 `build` script，只有 `typecheck`；`exports` 直接指向 `.ts` 源码。因此所有消费者（web / tamagotchi / pocket）都通过 Vite alias 直连 `src`（见 F5），不存在编译期强制边界。

**F2｜`stage-shared` 里直接定义了 Electron IPC 契约。**【事实】
- `src/artistry.ts:11-23` 定义 `eventa:invoke:electron:artistry:*` 契约，还混入了 Replicate 预设数据。
- `src/beat-sync/eventa.ts:11-18` 定义 `eventa:invoke:electron:beat-sync:*` 契约，并用 `isElectronWindow` 在 Electron IPC 与 BroadcastChannel 之间分支。
- `src/window.ts`、`src/electron-renderer.d.ts` 把 `ElectronWindow` 通过 `declare global` 注入到 `Window`。

**F3｜桌面契约已有规范归宿，且已存在"正确模式"。**【事实】
- `apps/stage-tamagotchi/src/shared/eventa/index.ts` 集中定义了数百个 Electron 契约（`electronGodotStageStart` 等，408-417 行）。
- Godot 场景的**中立类型/valibot schema 放在 `stage-shared/godot-stage`，Electron 契约放在桌面 app**，两者通过类型 import 连接（`index.ts:11-17` 只 import 类型）。这正是应该推广的模式。

**F4｜共享 UI 层大量用 `isStageTamagotchi()` 做行为/布局/能力分支。**【事实】
- 全 packages 共 28 个文件使用 `isStageTamagotchi|StageEnvironment|RUNTIME_ENVIRONMENT`（grep 计数）。
- 分支分三类：行为（`stage-ui/src/stores/auth.ts:50-58` 登录跳转跳过；`plugin-host-capabilities.ts:13-15` 仅在桌面发布能力）、能力门控（`providers.ts:330-336,956-958`、`libs/providers/providers/nvidia/index.ts:28` 的 `isAvailableBy: isStageTamagotchi`）、布局（`stage-layouts/src/layouts/settings.vue:86-102` 的头部隐藏/高度/返回按钮）。

**F5｜两个 app 都把共享包 alias 到 `src`，桌面用"排除列表"合并共享路由。**【事实】
- `apps/stage-tamagotchi/electron.vite.config.ts:137-149`：`stage-ui/stage-pages/stage-shared` alias 到 `src`；`VueRouter` 的 `routesFolder` 先挂 `stage-pages` 再挂桌面 pages，并用 7 个字符串路径的 `exclude` 列表排除被桌面覆盖的共享页（218-227 行）。
- `apps/stage-web/vite.config.ts:68-76`：同样 alias 到 `src`，但 web 用**顺序**（web pages 在前）实现覆盖，与桌面的**显式排除列表**机制不一致。

**F6｜共享 UI 并没有直接摸 `window.electron`/`window.api`。**【事实】grep 只命中 `stage-shared` 内 2 个文件。桌面语义的泄漏是**先集中到 `stage-shared` 的 helper 与契约，再被上层共享包引用**——这印证了 `stage-shared` 是关键的"单点泄漏"。

**F7｜已存在一个可推广的注入 seam 雏形。**【事实】`stage-ui/src/stores/mods/api/channel-server.ts:102-121` 的 `initialize({ connector })` 允许调用方注入 transport connector；provider 注册表已有 `isAvailableBy` 谓词字段。桌面页面覆盖也采用"组件级组合"而非整页复制（`apps/stage-tamagotchi/src/renderer/pages/settings/data/index.vue` 组合共享 section + 桌面 section）——这是好模式。

---

## 3. 当前摩擦（change amplification 与所有权缺失）

核心问题不是"共享包被桌面端引用"（那是正常方向），而是**方向颠倒：共享包开始拥有桌面语义**。

1. **桌面语义进入共享包，web/pocket 被迫吸收它。** 每新增一个"只在桌面生效"的行为，就会在 `stage-ui`/`stage-layouts` 里多一个 `if (isStageTamagotchi())` 分支。改动一个桌面功能需要触碰 2~4 个共享包，web 和 pocket 的维护者读代码时必须理解一个他们不关心的平台。
2. **同一类契约有两个家。** Electron 契约散在 `stage-shared/artistry.ts`、`stage-shared/beat-sync/eventa.ts` 与 `apps/stage-tamagotchi/src/shared/eventa` 之间，分界规则是"碰巧被谁消费"，而不是"谁拥有这个契约"。【推断】这是 ownership 缺失，不是有意的分层。
3. **`stage-shared` 没有可验证的边界。** 无 build、`exports` 指向源码、Vite alias 直连 `src`，意味着"包边界"只是名义上的——任何东西都可被 import，契约泄漏不会在类型或构建层面失败，只能靠 review 发现。
4. **`RUNTIME_ENVIRONMENT` 三态写死进共享包。** `environment.ts` 硬编码 web/capacitor/electron 三态，每个新宿主都要回改共享包。

次要但值得记录的摩擦：桌面路由覆盖依赖脆弱的字符串排除列表（F5），且与 web 的覆盖机制不一致。这是"共享 pages + 桌面覆盖"这个合理模式的实现代价，不是首要矛盾。

---

## 4. 质量属性优先级

按对本次决策的决定性排序：

1. **可维护性 / 变更局部性**（决定性）。桌面行为的变更应只落在 `apps/stage-tamagotchi`；共享包应只承载跨端中立逻辑。
2. **可移植性 / 平台隔离**。web 与 pocket 不应吸收桌面语义（契约、类型、行为分支）。
3. **可测试性**。注入式宿主适配器可被 mock；全局 `isStageTamagotchi()` 需要每个测试构造 Vite `define` 才能切换环境。
4. **构建/产物卫生**。桌面契约若被共享 UI 间接 import，存在被 web/pocket 打包进去的风险（`RUNTIME_ENVIRONMENT` 只能折叠运行时分支，不能折叠被引用的契约定义）。

**明确取舍**：现状用一行 `if` 换取最低短期成本，代价是共享层持续桌面化；宿主能力 seam 会新增一层抽象/间接，但把"桌面"从共享层的特殊 case 变成被注入的实现。性能在此决策中不构成约束。

---

## 5. 方案比较

### 方案 A：维持现状
- **边界/所有权**：无新增边界；桌面语义继续以 `isStageTamagotchi()` 和 Electron 契约的形式寄居在 `stage-shared` 及上层共享 UI。
- **带来/假设**：新增桌面功能成本最低（一行分支）；假设团队会持续在 review 里拦截"把更多桌面东西塞进共享包"。
- **迁移/回滚成本**：零。
- **运营/测试影响**：跨端测试必须构造 `RUNTIME_ENVIRONMENT`；web/pocket 读代码始终要理解 Electron 分支。
- **何时证明此方案错了**：`isStageTamagotchi()` 命中的文件数持续上升（当前已 28 个）；或 web/pocket 开始出现"为什么这个 Electron 分支会影响我"的 bug/困惑。

### 方案 B：治理"桌面宿主契约/能力归属"（推荐）
分两层、渐进实施：

- **B1｜契约归属（机械、低风险）**：把 `stage-shared` 里的 Electron 契约（`artistry.ts`、`beat-sync/eventa.ts`）迁回 `apps/stage-tamagotchi/src/shared`，只保留中立 schema/类型在共享侧——完全照抄 `godot-stage` 已有模式（F3）。`electron-renderer.d.ts`/`window.ts` 的 `ElectronWindow` 类型改由桌面 app 的 preload 契约拥有或保持为纯类型但明确标注"桌面宿主类型"。
- **B2｜能力 seam（设计级、中风险）**：把共享 UI 里的 `isStageTamagotchi()` **行为分支**（登录、插件宿主、数据重置、beat-sync 传输）收敛为注入式宿主能力接口，参考已有的 `channel-server` `connector` 注入（F7）。`isStageTamagotchi()` 只保留给**编译期构建变体与 tree-shaking**，不再用于运行时业务分支。布局分支（F4 第三类）单独处理，优先用 slot/组件覆盖而非环境布尔。

- **边界/所有权**：桌面 app 拥有宿主契约与宿主实现；共享包拥有中立领域逻辑与"宿主能力"的**接口**。
- **带来/假设**：桌面功能变更局部化；web/pocket 完全脱离 Electron 语义。假设"宿主能力"的接口能保持小而稳定（登录、插件宿主、生成、beat-sync 传输、窗口能力）。
- **迁移/回滚成本**：B1 是纯搬家，回滚即 revert；B2 逐 store 替换，每个都可独立回滚。
- **运营/测试影响**：B1 后契约集中一处，grep 可验证；B2 后宿主实现可 mock，共享层测试不再依赖环境 define。
- **何时证明此方案错了**：如果"宿主能力"接口膨胀到需要超过 ~5 个能力、且各能力之间无共同协议，说明该拆成多个独立适配器而不是一个 seam。

### 方案 C：按环境拆包（重、不建议现在做）
把 `stage-shared` 拆成 `stage-shared-core` / `stage-host-electron` 等按环境拆分的包。
- 一次性治理最彻底，但成本最高：要改所有 import、alias、`exports`，且当前无 build 的源码包模式使拆包边界同样只是名义上的。**在 B1/B2 未落地前拆包，只会把泄漏从"子路径"变成"包名"，不解决所有权问题。** 先否掉。

---

## 6. 推荐

**推荐方案 B，且把 B1 作为第一步、B2 作为目标态——两者是同一条边界（"桌面宿主拥有自己的契约与能力"）的两层，不是两个竞争方案。**

核心理由：
1. 根因单一。所有症状（共享 UI 环境分支、契约双家、`stage-shared` 无身份）都来自"共享包拥有桌面语义"。B1 先止住新契约继续泄漏，B2 再消解存量行为分支。
2. B1 已有可复制的正确先例（`godot-stage` 的 schema/契约分家），且完全机械、grep 可验证、回滚零成本。
3. B2 已有现成的注入 seam 雏形（`channel-server` 的 `connector`、provider 的 `isAvailableBy`），不是从零发明抽象。

**拒绝方案 A**：当前 28 个文件的环境分支和 `stage-shared` 里成形的 Electron 契约，已经表明"靠 review 拦"失效了——泄漏正在发生，这正是用户观察到的"耦合正在增加"。

**拒绝方案 C（先做）**：在没有所有权规则时拆包，只会把问题重命名。

**值得写 ADR 的决策**：
- "Electron IPC 契约只允许存在于 `apps/stage-tamagotchi/src/shared`，`packages/*` 只能放中立 schema/类型。"
- "`isStageTamagotchi()`/`RUNTIME_ENVIRONMENT` 仅用于编译期变体与 tree-shaking；运行时宿主行为一律走注入的能力接口。"

---

## 7. 迁移与验证（渐进、可逆）

**第一阶段（B1，契约搬家，1 个 PR 内可完成）**
1. 新增一条可执行的不变量（grep/knip/eslint 规则均可）：「`packages/**` 中不允许出现 `eventa:invoke:electron:` / `eventa:event:electron:` 字面量」——这是验证边界的关键手段，先立规则再搬家。
2. 把 `stage-shared/src/artistry.ts` 的契约迁到 `apps/stage-tamagotchi/src/shared/eventa/artistry.ts`；Replicate 预设数据迁到中立位置（可留在共享包，但和契约分离）。
3. 把 `stage-shared/src/beat-sync/eventa.ts` 的契约迁到桌面 app；`beat-sync` 只保留 detector 状态类型与本地检测逻辑，传输选择改为注入（这同时是 B2 的切片）。
4. `electron-renderer.d.ts`/`window.ts` 的 `ElectronWindow` 改由桌面 app 拥有；共享侧只留一个不含 Electron 类型的窄接口（如 `hasHostApi()` 谓词）。

**验收**：`pnpm -F @proj-airi/stage-tamagotchi typecheck` 与 `pnpm -F @proj-airi/stage-web typecheck` 均过；grep `packages/**` 不再命中 `eventa:invoke:electron:`；`pnpm test:run` 绿。

**第二阶段（B2，能力 seam，逐 store 渐进）**
1. 定义最小 `HostCapabilities` 接口（首版 ≤ 5 个能力：signIn 触发、plugin-host 发布、artifact 生成、beat-sync 传输、desktop 数据重置）。
2. 用 Pinia store 或 provide/inject 提供默认（web/capacitor）实现；`apps/stage-tamagotchi` 在 renderer 入口注入 Electron 实现。
3. 逐个替换 `auth.ts`、`plugin-host-capabilities.ts`、`use-data-maintenance.ts`、`beat-sync` 的行为分支；每替换一个 store 加一个针对该能力接口的 mock 测试。
4. 布局分支（`stage-layouts`）最后处理：优先抽成"槽位/可覆盖子组件"，而不是把布尔继续传下去。

**验收**：共享包内 `isStageTamagotchi()` 仅剩编译期/树摇用途（可 grep 审计）；web 构建不包含任何 Electron 契约；桌面行为可通过 mock 宿主实现做单元测试。

**回滚**：每一阶段/每个 store 独立可 revert；B1 纯搬家无行为变更，B2 用行为等价测试兜底（迁移前后同一用例）。

**不要现在做**：不要按环境拆包（方案 C）；不要一次性把所有 `isStageTamagotchi()` 清干净（会变成无法 review 的大重构）；不要为布局差异引入通用"平台皮肤系统"（过度抽象）。**触发重审的信号**：出现第 4 个宿主（如 Tauri/CLI），或宿主能力接口需要超过 ~5 个且互不相关的能力。

---

## 8. 开放决策（可能改变推荐）

1. **【未知】`RUNTIME_ENVIRONMENT` 三态是否够用？** 若团队已知即将支持第 4 个宿主，能力 seam 的接口设计要提前预留，且 B1 迁移顺序不变。
2. **【未知】`stage-shared` 的中立部分是否该整体改名/收敛**（如只保留 `composables`、`auth`、`webgpu`、`server-channel-qr`）。这不改变 B1/B2 方向，但影响"契约搬家"后 `stage-shared` 的最终形状。
3. **【推断】共享 UI 层是否愿意引入一个轻量 DI**（Pinia store 已够用）。若团队坚持共享层零 DI，B2 需要改用事件/回调注入，接口设计会不同。

---

**结论**：下一条最值得治理的边界是"桌面宿主的契约与能力归属"，落点是 `stage-shared`。第一步（最便宜、最可验证）是把 Electron 契约从共享包迁回 `apps/stage-tamagotchi/src/shared`，用一条 grep 不变量固化边界；第二步把 `isStageTamagotchi()` 行为分支收敛为注入式宿主能力接口。维持现状会继续让桌面语义向共享层扩散。

[EVAL:evolve-software-architecture-loaded]
