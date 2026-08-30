## 结论

下一条最值得治理的边界是：

> 共享 renderer 业务逻辑与 Electron 能力/主进程之间的能力边界。

建议先从 Artistry/Widgets 做第一条纵切面。暂时不要全面拆分 `stage-ui`、新建通用 `stage-runtime`，也不要重写 Eventa。

本次审查基于 `HEAD 5228f9412`（2026-07-22）；工作树无改动，仅检查源码、配置和 Git 历史，未宣称测试通过。

## 观察到的事实

| 事实 | 证据 | 判断 |
| --- | --- | --- |
| `stage-ui` 同时服务 Web、Pocket、Electron | 三个 app manifest 都依赖 `@proj-airi/stage-ui` | 共享包必须保持跨运行时可用 |
| Electron renderer 已有集中式组合根 | [`App.vue:79`](</evaluation-path/treatment/apps/stage-tamagotchi/src/renderer/App.vue:79>) 的 `createFullStageRuntime` 统一创建 stores 和 Eventa invoker | 已存在可复用的适配位置 |
| `stage-ui` 业务 store 绕过组合根直连 Electron | [`artistry-autonomous.ts:3`](</evaluation-path/treatment/packages/stage-ui/src/stores/modules/artistry-autonomous.ts:3>) 使用 Electron Eventa、[`artistry-autonomous.ts:37`](</evaluation-path/treatment/packages/stage-ui/src/stores/modules/artistry-autonomous.ts:37>) 读取 `window.electron` | 共享业务代码同时拥有平台传输知识 |
| Widgets IPC 合约被重复定义 | `stage-ui` 用 `defineInvokeEventa<..., any>`；桌面共享合约已有类型化的 [`widgetsAdd:331`](</evaluation-path/treatment/apps/stage-tamagotchi/src/shared/eventa/index.ts:331>) | 存在合约漂移风险 |
| `stage-shared` 也包含 Electron 实现 | BeatSync detector 直接导入 [`electron-screen-capture:3`](</evaluation-path/treatment/packages/stage-shared/src/beat-sync/detector.ts:3>)；但该依赖在 [`package.json:39`](</evaluation-path/treatment/packages/stage-shared/package.json:39>) 仅列为 devDependency | 包的运行时边界不自洽 |
| 包边界已经被源码路径穿透 | [`stage-ui/stores/mcp.ts:3`](</evaluation-path/treatment/packages/stage-ui/src/stores/mcp.ts:3>)、[`Stage.vue:30`](</evaluation-path/treatment/packages/stage-ui/src/components/scenes/Stage.vue:30>) 直接引用 sibling `src` | package exports 尚未成为真实接缝 |
| 共享包还反向依赖 server app | [`api.ts:1`](</evaluation-path/treatment/packages/stage-ui/src/composables/api.ts:1>) 导入 `apps/server/src/app` 的 `AppType` | 这是后续需要治理的第二类边界 |

真实运行链路目前是：

```text
stage-ui chat.ts
  -> useAutonomousArtistryStore
    -> 直接创建 Electron Eventa context
      -> stage-shared/artistry.ts 合约
        -> stage-tamagotchi main artistry-bridge
          -> widgets service / window manager
```

同时，`App.vue` 还独立 watch Artistry 配置并同步到主进程。聊天触发点见 [`chat.ts:362`](</evaluation-path/treatment/packages/stage-ui/src/stores/chat.ts:362>)，主进程处理见 [`artistry-bridge.ts:452`](</evaluation-path/treatment/apps/stage-tamagotchi/src/main/services/airi/widgets/artistry-bridge.ts:452>)。

## Git 历史说明

- `4e6da5ef0`（2026-04-24）一次提交新增或修改 64 个文件、约 6,234 行，横跨桌面端、`stage-ui`、`stage-pages`、`stage-shared`，正是 Artistry/Widgets 这类跨边界功能的变化放大。
- 从 2025-10-01 起，限定在这些路径的历史中：
  - 208 个提交同时改动桌面端和 `stage-ui`；
  - 235 个提交同时改动桌面端和任意 shared package；
  - `App.vue` 被改动 52 次，`stage-tamagotchi/src/main/index.ts` 被改动 74 次。
- `bf41655db` 已经采用过“兼容 facade + 下沉纯 runtime”的渐进抽取方式，将纯 Agent 逻辑移出 `stage-ui`。这说明小步建立边界比一次性重构更符合当前仓库演进方式。
- BeatSync 的 `97f53a818`、`4febd46ba` 也显示：跨桌面/共享包的 transport 变化会扩散到多个 package。

这些数字是变化放大指标，不等同于缺陷数量，但足以说明该边界已经是持续成本来源。

## 方案比较

| 方案 | 边界 | 优点 | 代价与失效条件 |
| --- | --- | --- | --- |
| 维持现状，加约定 | 共享包继续直接感知 Electron | 成本最低，短期开发最快 | 只能阻止新增，无法消除现有直连、重复合约和隐式 no-op；若继续增加桌面能力，收益很快耗尽 |
| 建立能力端口，逐个迁移 | `stage-ui` 只依赖 Artistry/Widgets 能力接口；桌面 renderer 提供 Electron adapter；主进程继续持有实现 | 改动局部、可测试、Web/Pocket 的能力缺失可显式表达；回滚成本低 | 需要定义能力语义、错误和生命周期；会增加一次适配层 |
| 全面拆分 package | 拆成 UI、domain、platform、contracts 等多个包，并清理所有 source alias | 长期边界最清晰 | 当前范围大、回滚贵，容易把真实问题变成层数；在第二、第三个能力端口尚未验证前不值得启动 |

## 推荐

选择第二种：建立能力端口，但以 Artistry/Widgets 为第一条切片。

目标形态：

```text
stage-ui 业务逻辑
  -> ArtistryRuntime port
     <- stage-tamagotchi renderer adapter
          -> 类型化 Eventa contract
             -> Electron main bridge
```

具体建议：

1. `stage-ui` 的 Artistry store 不再导入 Electron Eventa、不再读取 `window.electron`。
2. 桌面 renderer 使用现有的 `useElectronEventaInvoke` 和已存在的 `widgetsAdd` 合约构造 adapter。
3. Artistry 配置同步也逐步归入同一个桌面能力 adapter，避免 `App.vue` 直接知道 feature 细节。
4. Web/Pocket 明确提供“不支持生成”的能力状态，而不是由共享 store 通过 `window.electron` 探测后静默返回。
5. 第一阶段暂不移动所有 `stage-shared` 合约；先验证端口是否稳定，再决定合约应留在 `stage-shared` 子路径还是单独的 contracts package。

不建议现在创建一个万能 capability bus。当前已确认的 variation 是 Electron 与 Web/Pocket 的 Artistry/Widgets 差异，尚未证明所有平台能力应共享同一种抽象。

## 渐进路线

### 阶段 0：先冻结规则

记录一个 ADR，明确：

- shared package 允许依赖能力接口和可序列化数据；
- shared business code 不直接导入 Electron adapter、不读取 `window.electron`；
- Electron Eventa 的 transport adapter 由桌面 app 拥有；
- `stage-shared` 的实现代码和契约代码分开治理。

### 阶段 1：Artistry/Widgets 纵切

- 抽出最小的生成和添加 Widget 能力接口。
- 桌面 adapter 复用现有类型化合约。
- 移除 `artistry-autonomous.ts` 中重复的 `widgetsAdd` 字符串和 `any` 合约。
- 为 shared store 使用 fake port 编写单元测试。
- 为桌面主进程 handler 保留 Eventa contract test。

### 阶段 2：BeatSync

将 [`stage-shared/src/beat-sync/detector.ts`](</evaluation-path/treatment/packages/stage-shared/src/beat-sync/detector.ts>) 中的音频分析逻辑与 Electron screen-capture adapter 分离。共享包保留 detector、类型和设置；桌面端负责 Electron source selection 和 IPC。

### 阶段 3：收紧 package 边界

再处理：

- sibling `src` 相对路径导入；
- `stage-shared` 的运行时依赖声明；
- `stage-ui` 对 `apps/server/src/app` 的类型反向依赖；
- Vite 中直接 alias package `src` 的做法。

### 阶段 4：再评估是否拆包

只有当 Artistry、BeatSync 以及第三个真实能力都复用了相同边界时，才考虑提取独立的 platform/capability package。

## 验证退出条件

建议以这些条件判断边界是否真的建立：

- `packages/stage-ui/src`、`stage-pages/src` 中不再出现 raw Electron transport；
- Artistry shared tests 不需要 mock Electron；
- Web/Pocket 构建不会因为 `stage-shared` 解析 Electron screen capture；
- Artistry 的 IPC payload、错误、不可用状态都有 contract test；
- 桌面启动、辅助 chat window、widgets window、主进程重启后仍能正确初始化和清理；
- Artistry 配置和生成请求的 payload 大小、序列化耗时有基线；
- 修改一个桌面能力时，不再同时修改 shared business store 和多个 app 页面。

## 尚待决定的问题

这些未知项可能改变后续拆分深度，但不影响先做能力端口：

- Web/Pocket 将来是否也需要 Artistry 生成能力；
- Artistry API key 和 `globals` 是否应该继续由 renderer 同步到主进程；
- 第二个能力端口完成后，合约应继续放在 `stage-shared`，还是形成独立 contracts package。

[EVAL:evolve-software-architecture-loaded]
