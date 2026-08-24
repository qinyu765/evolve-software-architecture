## 1. 范围与信心

结论：下一条最值得治理的边界是：

> `packages/stage-*` 的共享领域/UI 逻辑 ↔ `apps/stage-tamagotchi` 的 Electron 能力与进程通信。

不建议现在拆分整个 `stage-ui`，也不建议从 overlay 生命周期重新开架构线；桌面状态文档已明确 overlay 不是当前阻塞项。[desktop-lane-status.md](/evaluation-path/treatment/docs/desktop-lane-status.md:63)

判断信心高：结论同时由当前源码、依赖关系和 Git 历史支持。未来是否需要 Web/Mobile 复用桌面能力，则属于未知。

## 2. 观察到的事实

| 类型 | 证据 |
|---|---|
| [事实] `stage-shared` 已混入桌面专属内容 | 根 barrel 同时导出 `artistry` 与 `window`。[index.ts](/evaluation-path/treatment/packages/stage-shared/src/index.ts:1) |
| [事实] 共享代码直接创建 Electron Eventa 上下文 | `stage-ui` 的 artistry store 读取 `window.electron` 并调用 Electron adapter。[artistry-autonomous.ts](/evaluation-path/treatment/packages/stage-ui/src/stores/modules/artistry-autonomous.ts:4) |
| [事实] 共享页面同时承担浏览器和 Electron 传输分支 | ComfyUI 设置页在 Tamagotchi 分支直接创建 Electron Eventa context。[comfyui.vue](/evaluation-path/treatment/packages/stage-pages/src/pages/settings/providers/artistry/comfyui.vue:5) |
| [事实] Beat Sync 的共享 detector 直接依赖 Electron screen capture | detector 中存在 Electron runtime import。[detector.ts](/evaluation-path/treatment/packages/stage-shared/src/beat-sync/detector.ts:11)；但该依赖在 `stage-shared` manifest 中列为 devDependency。[package.json](/evaluation-path/treatment/packages/stage-shared/package.json:39) |
| [事实] 合约已有重复 | Electron app 已有带类型的 `widgetsAdd` 合约。[eventa/index.ts](/evaluation-path/treatment/apps/stage-tamagotchi/src/shared/eventa/index.ts:331)，而共享 store 又用同一地址和 `any` 重新声明。 |
| [事实] 影响面已不是单一包 | 当前文本搜索中，`stage-shared` root 被 `stage-ui` 约 40 个文件、`stage-pages` 约 23 个文件使用；同时 Web、Mobile 也依赖它。 |
| [历史] 这种扩散在持续发生 | `beat-sync` 曾在 `stage-tamagotchi`、`stage-pages`、`stage-shared`、`stage-ui` 之间迁移；`artistry` 在 `4e6da5ef0` 一次性新增 app bridge、共享合约、共享页面和共享 store。 |
| [历史] 仓库已有较好的反例/先例 | `bf41655db` 将 `stage-ui` 中的纯 runtime 逻辑抽到 `core-agent`，采用 contracts/ports，并保留兼容 façade。 |

## 3. 当前摩擦

当前真正的问题不是所有 `isStageTamagotchi` 判断。部分环境判断属于正常的 UI 可用性策略。更值得治理的是：

- 共享 store/page 知道 Electron 的 `window.electron`、IPC context 和事件地址。
- `stage-shared` 同时承担中立类型、领域逻辑、Electron transport 和窗口类型。
- Electron 进程生命周期实际由 app 的 DI、隐藏窗口和 main service 管理，但共享包暴露了部分生命周期与传输实现。
- 新增一个桌面能力，容易同时修改 app、`stage-shared`、`stage-ui`、`stage-pages`。
- IPC 序列化、错误映射、窗口关闭和 screen capture 清理等语义分散在多个共享调用点；现有测试搜索也未发现 Artistry bridge 或共享 Beat Sync transport 的专门覆盖。

## 4. 质量属性优先级

1. **变更局部性**：桌面能力的变化应主要落在 Electron app/adapter，而不是扩散到共享 UI。
2. **可测试性**：共享包测试不应需要伪造 Electron window；跨进程行为应在 adapter/contract 层测试。
3. **跨运行时可移植性**：Web/Mobile 不应因导入共享 root 而间接携带 Electron 专属边界。
4. **生命周期可靠性**：Beat Sync 的隐藏窗口、BroadcastChannel、screen capture 和清理顺序需要由桌面 host 统一负责。
5. **短期成本**：避免一次性重命名和大规模包拆分。

性能目前没有足够测量证据，不应作为这次重构的主要理由。

## 5. 方案比较

| 方案 | 优点 | 代价与风险 |
|---|---|---|
| 维持现状，继续向 `stage-shared` 增加 Electron 合约 | 立即成本最低，已有调用路径不变 | 继续扩大共享包的桌面知识；合约重复、`any` 和 Electron 分支会增加；Web/Mobile 的边界更模糊 |
| **领域端口 + Electron adapter，渐进迁移** | 共享逻辑只依赖稳定的领域能力；Electron transport、窗口生命周期集中在 app；易做单元测试和回滚 | 需要设计端口、增加一次 wiring；短期会同时存在旧 façade 和新 adapter |
| 大规模拆成 `stage-ui-core` / `stage-ui-desktop` | 隔离最彻底 | 迁移面过大，容易把 UI、领域逻辑和 host transport 一起重组；当前没有足够证据证明需要这么大的包级拆分 |

推荐第二种。第一种只有在未来确认“这些能力永远只服务 Electron、共享包也不再承担多运行时职责”时才合理；当前 Web/Mobile consumer 和历史扩散趋势已经不支持这个假设。

## 6. 推荐形态

采用**领域专属端口**，不要先创建一个巨大的 `StageHostCapabilities` 总线。

建议的所有权：

- `stage-shared`：中立数据结构、配置、纯 detector/domain logic。
- `apps/stage-tamagotchi/src/shared/eventa`：Electron 专属事件地址和 payload。
- `apps/stage-tamagotchi`：Electron context、窗口生命周期、screen capture、main service wiring。
- `stage-ui` / `stage-pages`：只调用 `ArtistryHostPort`、`BeatSyncPort` 这类领域端口。
- `packages/electron-eventa`、`packages/electron-screen-capture`：继续作为底层 Electron adapter，不让业务共享包直接组装它们。

第一条切入线应是 **Artistry**：

- 它是最近新增且跨层最明显的功能。
- 当前已有重复 `widgetsAdd` 合约、Electron context 创建和 `any`。
- main 侧 `setupArtistryBridge` 已经是自然的桌面拥有者。[artistry-bridge.ts](/evaluation-path/treatment/apps/stage-tamagotchi/src/main/services/airi/widgets/artistry-bridge.ts:452)

第二条切入线是 **Beat Sync**：

- detector 已经有 `start(createSource)` 这样的注入 seam。
- 将 Electron screen capture、BroadcastChannel 和 Electron Eventa context 移到 app host；共享包保留纯音频分析和中立状态。

## 7. 渐进路线与验收

### 第一步：记录边界和基线

先写 ADR，明确共享包禁止直接依赖：

- `window.electron`
- `@moeru/eventa/adapters/electron/*`
- `@proj-airi/electron-*`
- Electron window/process lifecycle

同时列出现有例外，避免一次性强制清理。

### 第二步：迁移 Artistry

1. 将 artistry 的 presets/中立请求响应类型与 Electron Eventa 合约分开。
2. 定义 `ArtistryHostPort`。
3. 在 Tamagotchi renderer host 中创建 Electron adapter，并在 `App.vue` 或专门 bootstrap 位置注入。
4. 让共享 store/page 消费端口，不再读取 `window.electron`。
5. 统一使用 app 已有的 `widgetsAdd` 合约。
6. 为 adapter、main bridge、Web fallback 分别补测试。

验收标准：共享 Artistry 代码不再直接 import Electron；没有重复事件地址；共享测试无需 Electron runtime。

### 第三步：迁移 Beat Sync

1. 保留 detector 的纯分析能力。
2. 将 screen capture source 创建移到 Electron adapter。
3. 将状态/beat/spectrum transport 封装为 `BeatSyncPort`。
4. 保留现有隐藏窗口和 channel 行为，先只改变所有权。
5. 增加启动、停止、窗口关闭、权限失败和重启场景测试。

### 第四步：固化规则

两个垂直切片完成后，再增加静态依赖检查，并确认：

- `stage-shared` root 不再导出桌面专属模块。
- manifest 中的运行时依赖与源码真实使用一致。
- 后续桌面能力默认从 app host 开始设计，而不是从共享包开始设计。

未来实现时建议执行：

- `pnpm -F @proj-airi/stage-shared typecheck`
- `pnpm -F @proj-airi/stage-ui typecheck`
- `pnpm -F @proj-airi/stage-tamagotchi typecheck`
- 端口、adapter、main bridge 的定向 Vitest
- 用 `rg` 检查共享包中的 Electron import

本轮未运行这些命令，因为用户要求只读建议，且类型检查/测试可能产生缓存或其他工作区状态。

## 8. 尚需确认的决策

- Web/Mobile 在未来是否需要 Artistry headless generation 或 screen capture 的等价能力。
- `stage-shared` 是否只是内部源码包，还是计划成为真正 runtime-independent 的可复用包。
- Electron Eventa 的窗口命名空间和多窗口生命周期是否会近期变化；app main 中已有相关 TODO，因此不建议在本次边界治理中同时重做 transport 协议。
- 迁移期间是否允许短期 façade；若允许，应明确删除条件，避免成为永久兼容层。

本轮工作区保持未修改、未创建提交，也未改变外部状态。

[EVAL:evolve-software-architecture-loaded]
