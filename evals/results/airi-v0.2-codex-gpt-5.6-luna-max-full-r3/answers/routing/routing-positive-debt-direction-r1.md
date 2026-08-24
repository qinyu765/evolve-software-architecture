结论：下一条最值得治理的边界是“共享 renderer/UI 与 Electron host 能力之间的运行时边界”，首个切片建议选 Artistry，再处理 Beat Sync。不要先拆整个 `stage-ui`。

## 1. 范围和信心

仓库是 Electron 桌面端 + Web/Mobile 共享 Vue monorepo，分类信心高：桌面端有 main/preload/renderer 进程结构，`stage-ui` 同时被 Web、桌面和移动端依赖。[overview:103](/evaluation-path/treatment/docs/content/zh-Hans/docs/overview/index.md:103)

## 2. 观察到的事实

| 事实 | 证据 | 判断 |
| --- | --- | --- |
| `stage-shared` 已不是纯跨平台包 | 根入口导出 `artistry`；`window.ts` 依赖 `ElectronAPI`；Beat Sync 直接导入 Electron screen capture 和 Electron Eventa | 高置信事实；Electron 能力正在进入共享层。[index:1](/evaluation-path/treatment/packages/stage-shared/src/index.ts:1) |
| IPC 合同有两个所有者 | 桌面端 `src/shared/eventa/index.ts` 已约 500 行；Artistry/Beat Sync 合同则放在 `stage-shared` | 高置信事实；新功能没有唯一落点。[desktop contracts:33](/evaluation-path/treatment/apps/stage-tamagotchi/src/shared/eventa/index.ts:33) |
| 共享代码直接操作 Electron transport | `stage-ui` 自己创建 Electron Eventa context，并临时定义 `widgetsAdd`；`stage-pages` 手写 `window.electron` 类型并 cast `ipcRenderer` | 高置信事实；共享业务代码知道了传输细节。[artistry-autonomous:3](/evaluation-path/treatment/packages/stage-ui/src/stores/modules/artistry-autonomous.ts:3)、[comfyui:4](/evaluation-path/treatment/packages/stage-pages/src/pages/settings/providers/artistry/comfyui.vue:4) |
| Artistry 已形成完整跨边界链路 | `stage-ui`/`stage-pages` → `stage-shared` 合同 → `setupArtistryBridge` → Electron main 的 provider 和 widgets | 高置信事实；这是可用于治理的真实纵向切片。[bridge:452](/evaluation-path/treatment/apps/stage-tamagotchi/src/main/services/airi/widgets/artistry-bridge.ts:452) |
| 这种扩张是持续趋势 | `4febd46ba` 曾专门拆分 Beat Sync 的 Eventa 与业务；`97f53a818` 又将 transport 合并进共享 Beat Sync；`4e6da5ef0` 的 Artistry 一次改动涉及 55 个文件、5730 行新增；之后还有 global shortcut、MCP、插件能力等跨包改动 | 高置信历史事实；问题不是单个文件，而是边界反复漂移 |
| 仓库已有更好的模式 | `PluginHostDebugBridge` 和 `McpToolRuntime` 都让共享包声明窄接口，由桌面 renderer 在启动时注入 Electron 实现 | 高置信事实；可直接复用，而非重新发明框架。[plugin bridge:81](/evaluation-path/treatment/packages/stage-ui/src/stores/devtools/plugin-host-debug.ts:81)、[MCP runtime:64](/evaluation-path/treatment/packages/stage-ui/src/tools/mcp.ts:64) |

当前实际结构近似为：

```text
stage-ui / stage-pages
  └─ window.electron + Electron Eventa
       └─ stage-shared 中的 Electron 合同
            └─ stage-tamagotchi main bridge
                 └─ injeca / provider / widgets
```

主要摩擦是：同一个业务功能同时依赖共享业务状态、Electron transport、桌面 widgets 合同和 main-process 生命周期。`stage-ui` 甚至重新声明了一份 `widgetsAdd` 合同，形成合同重复。

## 3. 质量属性优先级

1. **变更局部性**：新增桌面能力不应同时修改共享 store、共享页面、Electron 合同和 main wiring。
2. **进程边界稳定性与可测试性**：序列化、错误、不可用状态和窗口上下文应集中在 adapter。
3. **跨平台性**：Web/Mobile 应通过明确的 browser/unavailable 实现工作，而不是依赖 Electron 类型和运行时分支。
4. **迁移成本**：保持现有 Eventa 和多窗口行为，不引入大规模分层。

## 4. 方案比较

### 方案 A：维持现状

继续允许 `stage-shared` 放 Electron 合同，`stage-ui`/`stage-pages` 按需直接创建 Eventa context。

优点是立即成本最低，适合 Artistry 等实验功能快速迭代。

代价是：

- 合同继续分散在 `stage-shared` 和桌面 app-local `eventa`；
- 每个新能力都可能复制 `window.electron`、Eventa 地址和 `any` DTO；
- Web/Mobile 构建和测试继续承受桌面知识；
- main/renderer 的窗口归属、错误映射和可用性判断难以集中验证。

如果未来不再增加桌面专属能力，且 Artistry 永远只服务桌面端，这个方案仍可暂时成立；当前历史不支持这个假设。

### 方案 B：建立窄的运行时能力接口——推荐

共享包只依赖领域能力接口，例如 Artistry host 的“生成图片”和“测试连接”；桌面端 renderer 在 `App.vue` 这样的 composition root 中注入实现。实现内部才使用 `@proj-airi/electron-vueuse`、app-local Eventa 合同和 `window.electron`。

职责划分：

- `stage-ui` / `stage-pages`：业务流程、页面状态和 browser fallback；
- 桌面端：Eventa transport、main handler、窗口上下文、Electron 错误与序列化；
- `@proj-airi/electron-eventa`：继续只承载通用 Electron 合同；
- `stage-shared`：保留真正跨平台的类型和逻辑，不再作为 Electron 能力垃圾桶。

不要创建一个巨大的 `PlatformService`；按真实变化点定义小接口。Artistry 的 `widgetsAdd` 应隐藏在领域 adapter 内，而不是由共享 store 直接知道 widgets IPC。

代价是需要处理注入时序和多窗口上下文。但现有 Plugin Host bridge 已证明这条路线符合仓库实践，且控制面 IPC 的额外间接层不会成为性能瓶颈。

### 方案 C：立即建立完整 `stage-desktop-contracts` 包

把所有桌面合同、MCP、插件、Godot、窗口、Artistry、Beat Sync 一次性迁移到新包。

长期所有权最清晰，但当前过重，容易把新包变成另一个 500 行总 barrel。只有当第二个桌面 host、远程 renderer 或 SDK 需要复用这些合同后，才值得升级到该方案。

## 5. 推荐的渐进路线

1. **先冻结边界规则**  
   记录 ADR：共享业务包禁止直接导入 Electron adapter、`window.electron`、`ElectronAPI` 和 Electron screen-capture；允许项先建立清单。暂不拆整个 `stage-ui`。

2. **先迁移 Artistry**  
   定义窄的 Artistry runtime 接口；由桌面 `App.vue` 注入 Eventa 实现；保留当前 Web 的 fetch fallback，以及非 Electron 下的明确 unavailable 行为。将 `stage-shared/src/artistry.ts` 中的 Electron 地址、业务 DTO 和 provider presets 分开归属。

3. **消除重复合同**  
   让 Artistry adapter 内部组合 `artistryGenerateHeadless` 和 `widgetsAdd`，共享 store 不再声明 `widgetsAdd`，桌面 app-local Eventa 成为该桌面合同的唯一来源。

4. **以 Beat Sync 作为第二切片**  
   将 screen capture 选择和跨窗口 transport 抽成接口，保留现有 `toggleBeatSync` 等公共行为；Electron screen-capture 和 BroadcastChannel 逻辑移到各自 adapter。

5. **按触碰迁移其他能力**  
   Global shortcut、Godot、MCP、插件能力不做大爆炸迁移；下次修改时沿用现有 `McpToolRuntime` / `PluginHostDebugBridge` 模式。

完成标准：

- 共享包中不再出现直接 Electron transport；
- 每个 Eventa 地址只有一个合同来源；
- `stage-shared` 根入口不再导出 Electron 专属 Artistry；
- shared unit/browser tests 可使用 fake runtime；
- 桌面侧增加 renderer → preload/Eventa → main handler 的合同测试；
- 保留多窗口上下文隔离，并验证 IPC 不可用、main 未就绪、超时和 provider 错误。

## 6. 尚待确认的决策

- Artistry headless generation 是否计划支持 Web/Mobile；这决定 browser adapter 是真实实现还是 unavailable 实现。
- 是否会出现第二个桌面 host 或远程 renderer；这决定何时值得建立独立 desktop-contracts 包。
- 是否要为跨进程 DTO 全面增加运行时 schema 和版本策略；当前 Artistry 的 `Record<string, any>` 已显示这是后续风险。

本轮仅执行了只读检查，没有修改文件、提交 commit 或改变外部状态。

[EVAL:evolve-software-architecture-loaded]
