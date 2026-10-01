建议**保留现有 Eventa／kit 契约，渐进明确调用身份、授权策略和生命周期所有权**。当前实现适合受信任本地插件；不可信第三方插件需要另行建立执行隔离边界。

本次仅检查源码、配置、测试与历史，未修改文件、启动应用或运行测试；以下“事实”指代码可证实行为。

**完整调用路径与关键事实**

`devtools 页面 → 共享 Pinia inspector store → App.vue 注入 bridge → Eventa renderer → preload 暴露的 Electron API → 主进程插件 RPC → hostService → ExtensionHost → 文件入口 import／kit 操作`

| 边界 | 可检查事实及影响 |
|---|---|
| 启动 | 主进程通过 injeca 启动插件宿主，依赖 serverChannel 与 widgetsManager；宿主扫描 `<userData>/extensions/v1` 并加载已启用插件。[启动装配](/evaluation-path/repository/apps/stage-tamagotchi/src/main/index.ts:176) |
| 窗口配置 | settings 窗口使用共享 `index.mjs` preload、显式 `sandbox:false`，并安装导航保护。未显式设置的 `contextIsolation`、`nodeIntegration`，Electron 41.2.1 默认分别为 `true`、`false`；不能把关闭 sandbox 理解成开启页面 Node。[窗口配置](/evaluation-path/repository/apps/stage-tamagotchi/src/main/windows/settings/index.ts:56)、[对应版本官方说明](https://raw.githubusercontent.com/electron/electron/v41.2.1/docs/api/structures/web-preferences.md) |
| 桥入口 | preload 暴露 `electronAPI`；共享 App 初始化安装管理 bridge。主进程插件入口使用 `createContext(ipcMain)`，应用处理器未显式校验 sender/frame、窗口角色或请求 schema。[preload](/evaluation-path/repository/apps/stage-tamagotchi/src/preload/shared.ts:17)、[RPC 入口](/evaluation-path/repository/apps/stage-tamagotchi/src/main/services/airi/plugins/index.ts:49) |
| 权限授予 | 桌面创建 host 时没有传入 `permissionResolver`；SDK 默认授予 manifest 声明，module 权限再与 extension grant 取交集。已有 kit 权限检查，但入口 `import` 发生在授权决策之前。[授予与会话](/evaluation-path/repository/packages/plugin-sdk/src/plugin-host/core.ts:250)、[入口加载](/evaluation-path/repository/packages/plugin-sdk/src/plugin-host/runtimes/node/loaders/fs.ts:72) |
| 状态所有权 | 主进程分别持有持久化 `enabled/autoReload/known`、发现 registry、运行时 loaded/session，以及资产 cookie/session。renderer Pinia 保存快照。**禁用不会停止已加载会话，直接 load 也不要求 enabled**；授权缓存是内存 Map。[宿主状态与操作](/evaluation-path/repository/apps/stage-tamagotchi/src/main/services/airi/plugins/host/index.ts:343) |

插件后续通过 kit 注册工具或打开 widget；工具 IPC 按 `ownerExtensionId + tool name` 查找执行记录，widget 请求由主进程 coordinator 按 `requestId + widget id` 匹配，并处理超时、关闭。iframe 桥已配置 `expectedSource`，这些现有边界值得保留。

**新增第三方插件／窗口时，应稳定什么**

- **调用者身份**：由主进程确定窗口、frame、允许操作；插件 ownership 字段用于归属，不能代替调用授权。Electron 官方也要求校验 IPC sender。[官方指导](https://www.electronjs.org/docs/latest/tutorial/security#17-validate-the-sender-of-all-ipc-messages)
- **授权与执行**：复用现有 `permissionResolver`，明确批准、权限扩大和撤销规则。当前同进程 `import` 可执行插件顶层代码，kit 权限无法约束任意 Node／Electron 调用。独立进程能改善故障隔离，但仍须明确系统资源权限。
- **状态与生命周期**：主进程保持权威状态；窗口保存可刷新快照。新增窗口不应因复用 App 就获得管理权或成为 capability 发布者。目前各共享 App renderer 注册 provider responder，并报告同一个 capability；应明确发布者选择、关闭撤回和接管规则。[renderer 装配](/evaluation-path/repository/apps/stage-tamagotchi/src/renderer/App.vue:139)

| 选择 | 收益 | 代价／适用条件 |
|---|---|---|
| 保留现状 | 改动少，现有开发插件流程继续工作 | 必须接受“插件与桌面 UI 均受信任”的前提 |
| 渐进调整，推荐 | 收紧入口，保留 kit、会话和工具契约，新增窗口的改动更局部 | 增加身份管理、授权记录与生命周期验证成本；执行隔离另分阶段 |

建议优先级为：**信任边界 → 状态一致性 → 扩展成本**。

**迁移、回滚与验证标准**

1. 先定义操作权限表与状态语义，沿现有入口增加身份、载荷验证，并明确 capability 发布者。验收：未授权窗口／frame 调用无副作用，两个窗口的请求和结果不串线。
2. 接入授权策略，按 extension 串行处理 load/unload/reload，明确禁用是否立即停止。验收：双窗口同时加载只产生一个会话；setup 失败、卸载、重载后，工具、binding、资产会话均正确清理，旧会话消息被拒绝。
3. 第三方执行隔离单独试点，保留现有公开契约。验收：插件失败不拖垮主进程，越权操作被拒绝，超时／关闭后 pending 请求归零；启动与调用耗时相对当前基线符合约定预算。

每阶段独立发布、保留可恢复的配置格式；失败时回退上一阶段。隔离阶段回滚时暂停第三方插件加载，避免重新落入主进程直接执行。现有 SDK 测试覆盖权限收窄和清理，但桌面入口测试替换了真实 IPC adapter，不能证明 sender 校验或多窗口路由正确。

未决项：第三方插件是否允许任意 Node 能力；禁用的产品语义；授权持久化与撤销策略；capability 发布者接管规则。Eventa beta.8 适配器源码未取得，实际跨窗口回复／广播语义仍需真实 Electron 验证。

技术依据包括已安装 Eventa、Vue、vue-best-practices、VueUse Skills：Eventa 上游确有同名 Skill，但本地内容与 beta.8 的对应关系未核验；Vue／VueUse 属社区指导。Electron 默认值按 41.2.1 官方文档核对，sender 建议来自当前官方文档。

[EVAL:evolve-software-architecture-loaded]