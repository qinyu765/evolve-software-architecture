结论：下一条最值得治理的不是拆分 `stage-ui`，而是明确「共享 renderer packages ↔ Electron 桌面壳」之间的能力/RPC 边界。首个垂直切片建议选 Artistry，随后用 beat-sync 验证模式。

## 范围与置信度

本次仅检查当前工作树中的真实文件、包配置与 Git 历史；未修改文件、未创建提交、未改变外部状态。对边界判断的置信度高；对 Artistry 是否长期支持 Web/移动端的产品意图，置信度中等。

## 关键事实

| 事实 | 证据 | 判断 |
|---|---|---|
| `stage-ui` 明确同时服务 Web、桌面和移动端 | [项目概览](/evaluation-path/treatment/docs/content/zh-Hans/docs/overview/index.md:110) | 共享包不应默认依赖 Electron transport |
| 共享包直接创建 Electron Eventa context | [Artistry store](/evaluation-path/treatment/packages/stage-ui/src/stores/modules/artistry-autonomous.ts:3)、[共享设置页](/evaluation-path/treatment/packages/stage-pages/src/pages/settings/providers/artistry/comfyui.vue:4) | 平台能力和业务页面的所有权混在一起 |
| 同一个 widget IPC 地址被重复定义 | 桌面端是强类型的 [widgetsAdd](/evaluation-path/treatment/apps/stage-tamagotchi/src/shared/eventa/index.ts:329)，共享 store 又用 `any` 重定义 [同一地址](/evaluation-path/treatment/packages/stage-ui/src/stores/modules/artistry-autonomous.ts:34) | 契约没有唯一拥有者 |
| 主进程确实拥有 provider、配置、去重、轮询和网络策略 | [Artistry bridge](/evaluation-path/treatment/apps/stage-tamagotchi/src/main/services/airi/widgets/artistry-bridge.ts:101)、[handler 注册](/evaluation-path/treatment/apps/stage-tamagotchi/src/main/services/airi/widgets/artistry-bridge.ts:452) | 需要治理的是 transport 边界，不是把执行策略搬进共享包 |
| 该问题会扩大变更面 | `4e6da5ef0` 的 Artistry 提交一次改动 64 个文件、增加 6234 行；beat-sync 的 `bbb437a77`、`97f53a818` 也分别跨 17、15 个文件 | 这是已发生的变更放大，不是抽象上的担忧 |
| 共享 runtime 注入已有成功先例 | [McpToolRuntime](/evaluation-path/treatment/packages/stage-ui/src/tools/mcp.ts:64)、[桌面端注入](/evaluation-path/treatment/apps/stage-tamagotchi/src/renderer/stores/mcp-tools.ts:20) | 目标架构可以渐进复用现有模式 |

当前 Artistry 链路大致是：

```text
共享 page/store
  -> 共享包内直接访问 window.electron
  -> stage-shared 中的 Electron-addressed Eventa contract
  -> preload / main
  -> desktop artistry-bridge
  -> provider、网络、配置和 widgets
```

同时，非 Electron 环境有的路径直接 `fetch`，有的路径静默跳过；例如共享 store 在没有 IPC 时会跳过生成。[对应逻辑](/evaluation-path/treatment/packages/stage-ui/src/stores/modules/artistry-autonomous.ts:220)

## 方案比较

| 方案 | 优点 | 代价 |
|---|---|---|
| 维持现状 | 无迁移成本；新增桌面功能快；已有 Web fallback | 继续产生重复地址、`window as any`、Electron 分支和隐式 no-op；共享包难以独立测试；一次功能会继续同时触碰 app、pages、ui、shared |
| 能力端口 + 桌面适配器（推荐） | 共享包只依赖平台中立的 `ArtistryRuntime`、`WidgetRuntime` 等小接口；桌面端集中创建 Eventa adapter 和 Electron contracts；Web/移动端显式选择 browser 或 unavailable 实现 | 初期需要注入和生命周期设计；需要补齐契约、adapter、主进程测试 |
| 把所有业务 Eventa contract 都塞进 `electron-eventa` | 名字集中 | 共享 UI 仍会依赖 Electron，只是把耦合搬到另一个包；通用 Electron 包会被业务领域反向污染，不建议 |

维持现状只有在以下假设成立时才合理：Artistry 永久只服务桌面端、不会出现第二个 Electron consumer、且短期不需要独立测试或替换 transport。当前共享页面已有浏览器 fallback，因此这些假设尚未被代码充分证明。

## 推荐的目标边界

建议建立以下依赖方向：

```text
stage-ui / stage-pages
  -> 平台中立的 ArtistryRuntime、WidgetRuntime
  -> desktop renderer adapter
  -> apps/stage-tamagotchi/src/shared/eventa
  -> Electron main artistry-bridge
```

具体原则：

- `stage-shared` 可以继续提供请求、结果、配置等平台中立类型，但 Artistry 的 Electron 地址和 `defineInvokeEventa` contract 应归桌面端契约模块所有。
- 共享 store/page 不再直接导入 `@moeru/eventa/adapters/electron/renderer`，也不再读取 `window.electron`。
- Artistry 生成和 widget 添加应是两个小能力端口，不要制造一个包含所有桌面能力的 `PlatformService`。
- provider registry、配置持久化、去重、轮询和外部网络调用继续留在主进程；这些是 [artistry-bridge](/evaluation-path/treatment/apps/stage-tamagotchi/src/main/services/airi/widgets/artistry-bridge.ts:110) 已经明确承担的策略。
- Web 继续使用现有 CORS 受限的直接请求，移动端或不支持环境返回显式的 unavailable 状态，而不是依靠隐式 `window` 检查。

## 渐进路线

1. 先写边界约定：共享包不得持有 Electron transport；一个 IPC 地址只能有一个契约定义；主进程是桌面能力的执行边界。

2. 以 Artistry 为首个切片，先抽出平台中立的请求/结果类型和两个 runtime 接口，不改变主进程行为。

3. 在 `stage-tamagotchi` renderer 中建立桌面 adapter，复用现有 `useElectronEventaInvoke` 和已有强类型 `widgetsAdd`，由桌面 app 负责把能力注入共享 store/page。

4. 迁移 Artistry 设置页和 autonomous store，移除共享包中的 Electron context、`window as any` 和重复 widget 地址。现有 Artistry store 测试只验证默认状态，[未覆盖 transport 行为](/evaluation-path/treatment/packages/stage-ui/src/stores/modules/artistry.test.ts:10)，应补上 fake runtime 测试。

5. 用同一模式治理 beat-sync/screen-capture。当前 [detector](/evaluation-path/treatment/packages/stage-shared/src/beat-sync/detector.ts:126) 仍在共享包内区分 Web 与 Tamagotchi，并动态加载 Electron adapter；它适合作为第二个验证切片，不建议第一步就重构整个 `stage-shared`。

6. 最后加入边界检查：禁止指定共享目录直接引用 Electron adapter 或 `window.electron`；检查重复 Eventa 地址；分别运行 shared fake-runtime、desktop main-handler、Web fallback 和一次 Electron smoke 测试。

## 待确认决策

- Artistry 的浏览器路径是正式产品能力，还是仅用于开发/实验？
- 是否预计会有第二个 Electron 应用？若没有，业务 contract 暂时保持在 `stage-tamagotchi` 更清晰。
- runtime 注入采用显式 store 初始化还是 Vue provide/inject，应以 Artistry 小范围试点后的生命周期和测试成本决定。
- `stage-shared` 最终定位是“跨平台纯共享”，还是“包含 Electron renderer 能力的共享层”；这个定位需要通过 ADR 固定下来。

本次检查时 Git 状态为 detached `HEAD` 且没有变更；未修改任何文件。

[EVAL:evolve-software-architecture-loaded]
