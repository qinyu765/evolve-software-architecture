## 结论

下一条最值得治理的边界是：

`共享 UI/业务包` → `中性能力接口/数据契约` → `stage-tamagotchi Electron 适配层`

重点不是立即拆分整个 `stage-ui`，而是阻止 `stage-ui`、`stage-pages`、`stage-shared` 直接创建 Electron Eventa、访问 `window.electron` 或管理 Electron 窗口/屏幕采集。

建议首个垂直切片选择 `beat-sync`，随后治理 Artistry。

## 观察到的事实

- Electron renderer 通过 alias 直接编译共享包源码：[electron.vite.config.ts:145](</evaluation-path/treatment/apps/stage-tamagotchi/electron.vite.config.ts:145)。路由也直接指向 `packages/stage-pages/src/pages`：[electron.vite.config.ts:216](</evaluation-path/treatment/apps/stage-tamagotchi/electron.vite.config.ts:216)。

- `stage-shared` 的 beat-sync 同时持有业务逻辑、Electron 屏幕采集和 Electron Eventa transport：[detector.ts:3](</evaluation-path/treatment/packages/stage-shared/src/beat-sync/detector.ts:3)、[detector.ts:165](</evaluation-path/treatment/packages/stage-shared/src/beat-sync/detector.ts:165)、[eventa.ts:11](</evaluation-path/treatment/packages/stage-shared/src/beat-sync/eventa.ts:11)。

- 共享 UI 和页面也直接接入 Electron：`stage-ui` 的 Artistry store 创建 Electron renderer context 并内联 `widgetsAdd`：[artistry-autonomous.ts:3](</evaluation-path/treatment/packages/stage-ui/src/stores/modules/artistry-autonomous.ts:3)；`stage-pages` 的 ComfyUI 页面同样导入 Electron adapter：[comfyui.vue:5](</evaluation-path/treatment/packages/stage-pages/src/pages/settings/providers/artistry/comfyui.vue:5)。

- 桌面端 Eventa 总入口已有约 99 个事件定义、84 个消费者，覆盖窗口、插件、MCP、Godot、快捷键、Artistry 等多个领域：[eventa/index.ts:31](</evaluation-path/treatment/apps/stage-tamagotchi/src/shared/eventa/index.ts:31)。其中插件类型还在共享 SDK 与桌面端手工重复，代码明确留下了待解除耦合的 TODO：[eventa/index.ts:218](</evaluation-path/treatment/apps/stage-tamagotchi/src/shared/eventa/index.ts:218)。

- 这不是纯桌面代码：Web 也 alias `stage-ui`、`stage-pages`、`stage-shared`，Pocket 也依赖共享包。因此 Electron transport 泄漏会直接降低共享包的可移植性。

- 仓库已有较好的边界范例：`global-shortcut` 在共享包中定义中性的快捷键类型和失败语义，Electron 的 `globalShortcut`/uiohook driver 留在桌面端：[global-shortcut/types.ts:82](</evaluation-path/treatment/packages/stage-shared/src/global-shortcut/types.ts:82)、[global-shortcut.ts:67](</evaluation-path/treatment/apps/stage-tamagotchi/src/main/services/electron/global-shortcut.ts:67)。

## Git 历史说明的趋势

- `4febd46ba`、`97f53a818`、`e2b00e7d2`：beat-sync 从业务与 Eventa 拆分、迁移 BroadcastChannel、增加桌面持久化，说明该功能持续跨共享包、页面、renderer、main 演进。
- `4e6da5ef0`：Artistry 引入时跨 64 个文件，涉及桌面 main/renderer、`stage-pages`、`stage-ui`、`stage-shared`，体现出新桌面能力会迅速扩散。
- `bf41655db`：仓库曾将 `stage-ui` 中的纯运行时逻辑提取到 `core-agent`，提交说明明确指出原模块混合了运行时、Vue/Pinia 状态和浏览器适配器。这支持“抽取稳定端口、保留薄 facade”的渐进方式。
- `d02a76f94`、`ecf234c24`：快捷键和 Godot 已经分别形成“共享中性契约 + 桌面实现”的方向。

**推断：** 当前主要问题不是循环依赖，而是能力所有权不清晰：共享包同时承担业务、平台判断、传输和 Electron 生命周期，导致每次桌面能力扩展都扩大变更面。

## 方案比较

| 方案 | 优点 | 代价与风险 |
|---|---|---|
| 维持现状 | 无 API 迁移，短期改动最小 | 新能力继续进入 `stage-shared` 或共享 UI；Electron 依赖、环境分支和窗口生命周期继续泄漏；测试只能间接覆盖 |
| 治理能力适配边界（推荐） | Electron adapter、Eventa 注册、BrowserWindow 和屏幕采集归桌面端；共享包只依赖中性 port/contract；更容易用 fake port 测试 | 需要调整 store/page 初始化方式，处理生命周期和异步错误 |
| 全面拆分 `stage-ui-core` / `stage-ui-electron` | 隔离最彻底 | 当前直接导入 Electron adapter 的共享文件数量还少，立即拆包会造成较大的 package graph 和 API 重排，收益不足 |

维持现状只有在“桌面不再持续增加独有能力、共享包不再服务多端”时才更合理；目前 Git 历史和实际依赖都不支持这个前提。

## 推荐的目标形态

共享包负责：

- 中性的状态、参数、序列化数据和业务规则；
- 可跨 Web/Desktop 使用的 detector 或 feature model；
- 明确的 capability port，例如 beat-sync、Artistry client。

桌面端负责：

- `@moeru/eventa/adapters/electron/renderer`；
- `window.electron`；
- Electron screen capture；
- hidden `BrowserWindow`、main-process handler 和生命周期；
- 桌面专属 Eventa 地址及其注册。

`stage-ui` 和 `stage-pages` 通过显式注入的能力接口使用功能，不再自行构造 Electron transport。现有 `isStageTamagotchi()` 分支不必一次性全部删除；先治理直接触碰 Electron API 的代码，避免把所有平台策略混成一次大重构。

## 渐进路线

1. **先记录架构决策和边界规则。**  
   明确共享包不得直接导入 Electron Eventa adapter、读取 `window.electron` 或管理 Electron window。不要先创建通用“平台服务”大抽象。

2. **整理桌面 Eventa contract ownership。**  
   按窗口、插件、Godot、快捷键、MCP 等领域拆分现有 `shared/eventa/index.ts`，保持当前事件地址和 payload 不变。仓库已有插件 Eventa 分拆和域测试，可以沿用其渐进方式。

3. **以 beat-sync 做第一条垂直切片。**

   - 将 detector 的中性逻辑与 Electron/BroadcastChannel bridge 分离。
   - 页面和 store 依赖 `BeatSync` 能力接口。
   - Web 使用本地实现，Desktop 使用由 Electron composition root 创建的 adapter。
   - hidden BrowserWindow 和屏幕采集继续由 `stage-tamagotchi` 管理。
   - 首轮不改变 Eventa 地址、持久化格式和用户行为。

   选择 beat-sync 的理由是它同时覆盖共享页面、共享 store、BroadcastChannel、Electron renderer、hidden window 和 screen capture，最能验证这条边界是否真的有效。

4. **第二条切片治理 Artistry。**  
   移除 `stage-ui` store 和 `stage-pages` 页面中的 Electron context 创建；将生成、ComfyUI 测试、widget 添加变成显式 desktop adapter。Artistry 的业务 preset/catalog 可以继续留在共享业务层，但 transport 不应留在那里。

5. **只有在两个以上领域稳定迁移后，才考虑新建窄 contract package。**  
   该包只放产品级中性契约，不要把所有 Electron API 或所有 Eventa 定义集中进去。若暂时没有第二个独立消费者，继续使用桌面端域模块即可。

## 验收标准

后续实现完成后应能验证：

- `stage-ui`、`stage-pages` 不再直接导入 Electron Eventa adapter 或读取 `window.electron`。
- `stage-shared/beat-sync` 不再直接依赖 Electron screen capture。
- Web、Pocket、Desktop 各自提供能力实现，共享页面可用 fake port 做单元测试。
- Electron Eventa 地址和 payload 在迁移期间保持稳定。
- beat-sync 的启动、停止、无音频、权限失败、窗口销毁和重启路径有跨进程测试。
- Desktop、Web、Pocket 的 typecheck/build 和相关 Vitest 均通过。
- 变更主要集中在桌面 adapter 与共享中性契约，而不是再次扩散到整个 `stage-ui`。

建议将该决定写成 ADR，例如：

`Keep Electron capabilities behind app-owned adapters and neutral stage contracts`

本轮仅进行了只读检查，没有修改文件、创建提交或改变外部状态。

[EVAL:evolve-software-architecture-loaded]
