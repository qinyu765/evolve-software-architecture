结论：建议采用“方案 B：按风险渐进出进程的混合架构”。保留当前 Electron 主进程作为桌面组合根和可信能力宿主；稳定插件、窗口、后台能力的协议与所有权边界；只有当插件不可信、运行时间长、资源重或需要独立故障域时，才迁移到独立进程。不要现在就建设全量外置插件平台或通用后台 supervisor。

## 当前结构与关键判断

| 观察 | 证据 | 判断 |
|---|---|---|
| `[Fact]` 主进程同时组装窗口、插件、HTTP/WebSocket server、MCP、Godot | [`main/index.ts:154`](/evaluation-path/treatment/apps/stage-tamagotchi/src/main/index.ts:154)、[`main/index.ts:176`](/evaluation-path/treatment/apps/stage-tamagotchi/src/main/index.ts:176) | `[Inference]` 组合根是高变更、高耦合热点；新增能力容易扩大依赖图。 |
| `[Fact]` 插件通过 Electron runtime 在主进程动态 `import` | [`plugins/host/index.ts:224`](/evaluation-path/treatment/apps/stage-tamagotchi/src/main/services/airi/plugins/host/index.ts:224)、[`fs.ts:72`](/evaluation-path/treatment/packages/plugin-sdk/src/plugin-host/runtimes/node/loaders/fs.ts:72) | `[Inference]` 权限系统不是进程级沙箱；第三方代码的阻塞、崩溃和资源泄漏仍可能影响主进程。 |
| `[Fact]` 插件已有 manifest、session、permission、module/binding、asset revoke、tool owner 等边界 | [`core.ts:235`](/evaluation-path/treatment/packages/plugin-sdk/src/plugin-host/core.ts:235)、[`host/index.ts:363`](/evaluation-path/treatment/apps/stage-tamagotchi/src/main/services/airi/plugins/host/index.ts:363) | 这是值得稳定的逻辑所有权边界。 |
| `[Fact]` 窗口已有 reusable/referenced manager 和每窗口 Eventa context，但代码仍依赖全局 listener 上限，且明确 TODO 窗口命名空间 | [`referenced-window.ts:41`](/evaluation-path/treatment/apps/stage-tamagotchi/src/main/windows/shared/referenced-window.ts:41) | `[Inference]` 窗口生命周期已有基础隔离，事件路由和依赖注入仍有隐藏耦合。 |
| `[Fact]` server-runtime 可独立启动，MCP/Godot 已有子进程管理 | [`server/run.ts:7`](/evaluation-path/treatment/packages/server-runtime/src/bin/run.ts:7)、[`mcp-servers/index.ts:441`](/evaluation-path/treatment/apps/stage-tamagotchi/src/main/services/airi/mcp-servers/index.ts:441) | `[Inference]` 仓库已有多种后台边界，不需要马上抽象成一个万能框架。 |
| `[Fact]` plugin SDK 的 WebSocket/worker transport 仍未实现，设计文档标为 Planned | [`runtimes/node/index.ts:24`](/evaluation-path/treatment/packages/plugin-sdk/src/plugin-host/runtimes/node/index.ts:24)、[`multi-transport.md:152`](/evaluation-path/treatment/packages/plugin-sdk/docs/design/multi-transport.md:152) | `[Constraint]` 不能把设计文档中的远程/worker 形态当成当前可用基础设施。 |

## 应稳定的边界

1. 插件逻辑边界：`extensionId → sessionId → moduleId → resource/requestId`。  
   Manifest、权限、kit、binding、tool、asset session 应成为插件唯一的正式入口。插件不应依赖 `BrowserWindow`、`ipcMain`、Electron 主进程对象或具体 Node 进程布局。

2. 窗口边界：`windowId + owner + route + reuse policy + lifecycle/dispose`。  
   保留 reusable、referenced、overlay、widgets 等不同策略，不要强行统一成一个“万能窗口类”。新窗口应通过窄的 manager/handle 操作，不把整个依赖图注入窗口。

3. 跨边界协议：Eventa 契约、插件协议、server-sdk 协议应是稳定面。  
   所有请求和事件应明确 `windowId`、`extensionId`、`sessionId`、`moduleId`、`requestId` 等关联键。共享事件文件可以按领域拆分，但不要再增加第二套隐式事件总线。

4. 后台能力边界：启动、停止、状态、健康、重启、所有权和退出清理。  
   继续复用现有 `Server`/`ServerManager`、MCP、Godot 的生命周期思想。后台服务不应反向依赖窗口或渲染器。

5. 配置与回滚边界：每个服务拥有自己的配置和运行时状态；配置应用失败必须恢复旧运行态。现有 server channel 已经有明确回滚实现，可作为范式。[`channel-server/index.ts:468`](/evaluation-path/treatment/apps/stage-tamagotchi/src/main/services/airi/channel-server/index.ts:468)

## 应延后的抽象

- 全量 `PluginRuntime`/transport 抽象：先完成一个真实的 sidecar 或 WebSocket 垂直切片，再推广。
- 通用后台 supervisor：至少出现两个以上拥有相同重启、健康检查、超时、日志、孤儿进程处理需求的服务后再抽取。
- 全量 capability lifecycle state machine：当前宿主实际只有 `setting-up/ready/failed/stopped`；设计文档中的复杂状态机暂时是提案。
- 元数据驱动的万能窗口 DSL：当前窗口类型差异真实存在，先稳定生命周期和所有权。
- “权限即安全沙箱”：进程隔离、资源限额和网络/文件系统策略仍需单独设计。
- 市场安装、签名、升级和信任模型：在产品明确“任意第三方代码”之前，不应提前固化。

## 方案比较

| 方案 | 结构 | 质量属性 | 成本与风险 | 回滚 |
|---|---|---|---|---|
| A. 维持现状 | 插件、窗口、后台继续由 Electron 主进程承载 | 延迟低、调试简单；隔离性、主进程可用性和安全性弱 | 成本最低；随着插件/窗口增加，主进程启动、内存、依赖图和崩溃半径持续扩大 | 最容易，基本无需迁移 |
| B. 混合架构，推荐 | 可信插件留在主进程；不可信、重型、长生命周期能力按插件/能力迁移到 sidecar 或独立 server | 在成本可控下改善故障隔离、可用性和演进性；增加协议延迟、重连、版本兼容和运维复杂度 | 中等成本；最大风险是短期双运行模式和协议语义重复 | 每个能力单独切换；sidecar 失败时安全地降级/禁用。对不可信插件不能自动退回主进程 |
| C. 全量外置插件宿主 | Electron 只做 UI shell；插件宿主、后台 supervisor、通信协议全部独立 | 隔离、独立重启、远程化能力最好 | 成本最高；当前 transport 尚未实现，需处理打包、升级、认证、重连、背压、版本协商、诊断和跨平台进程管理 | 需要长期保留旧宿主适配器，回滚成本高 |

如果所有插件都来自可信、签名和内置渠道，方案 A 仍然合理；如果目标是任意第三方插件、插件崩溃不能影响桌面、或后台能力必须在 UI 关闭后继续运行，则应直接把方案 B 的 sidecar 路线列为产品约束，而不是把权限系统当作替代品。

## 渐进迁移路线

1. **基线阶段**  
   先记录主进程启动时间、内存、窗口打开延迟、插件加载/卸载耗时、后台停止耗时、异常退出和孤儿进程数量。当前没有足够证据设定数值预算，这些属于 `[Unknown]`，不能凭经验硬编码。

2. **稳定逻辑契约，不改变进程拓扑**  
   新增插件只依赖 manifest、kit、binding 和 host command；新窗口只依赖窄的窗口 manager；后台能力只暴露生命周期和健康接口。为插件卸载、窗口关闭、iframe 请求、server 配置回滚补齐公共行为测试。

3. **选择一个垂直切片出进程**  
   选择一个非核心、长生命周期或高风险的外部集成插件，优先从无复杂 UI 的 tool/capability 开始。使用现有 plugin-protocol/server-sdk 作为候选协议，但必须先验证一个真实 transport 的握手、权限、重连和版本协商，不直接把当前 Planned 设计视为完成品。

4. **引入按能力选择的运行模式**  
   可信内置插件继续 in-process；sidecar 插件拥有独立 session、健康状态、日志关联和停止超时。sidecar 启动失败时进入 degraded/disabled 状态；不要为了“兼容”把不可信代码自动放回主进程。

5. **迁移独立后台能力**  
   对确实需要独立部署或独立重启的能力，优先复用可独立运行的 `server-runtime`。桌面内置 server 和 standalone server 保持同一协议及配置语义，切换必须是显式配置并具备失败回滚。

6. **只有证据出现后再升级到方案 C**  
   触发条件包括：任意第三方代码成为产品要求、主进程故障隔离成为硬指标、插件需要独立于 UI 生存、或多个 sidecar 已经重复实现 supervisor 逻辑。此时再实现正式 transport、版本协商、背压、进程预算和统一宿主。

## 可验证的迁移闸门

- 两个插件同时运行、卸载、重载时没有跨 session 的 tool、binding、asset、widget 或事件残留。
- 插件入口不能通过公共契约取得 Electron 主进程对象。
- sidecar 崩溃、卡死、断连不会导致主进程退出；没有孤儿进程；日志能关联到 extension/session/request。
- 窗口重复打开、关闭、销毁后，pending request 都有明确完成或拒绝结果；新增窗口不需要修改无关窗口的业务依赖。
- embedded server 与 standalone server 的认证、配置、健康状态和停止行为一致。
- transport 不兼容时明确失败并可禁用该能力；不通过多层隐式 fallback 掩盖版本问题。
- 现有插件宿主局部测试继续通过；再增加至少一个真实 transport 的集成测试和一个进程故障测试。当前检索到的测试主要覆盖插件/窗口局部服务，未看到覆盖整个 `injeca` composition root 的测试，这是覆盖空档而非对不存在测试的绝对断言。

不改变的后果是：短期开发速度最快、回滚最简单；但第三方插件仍与主进程共享故障域，窗口和后台能力继续扩大主进程依赖图，独立重启、资源限额和安全隔离会越来越难补。建议现在只稳定“协议、所有权、生命周期”，把“是否同进程”留作可替换部署策略。

本次仅做只读检查；工作树保持无修改、未创建提交、未改变外部状态。

[EVAL:evolve-software-architecture-loaded]
