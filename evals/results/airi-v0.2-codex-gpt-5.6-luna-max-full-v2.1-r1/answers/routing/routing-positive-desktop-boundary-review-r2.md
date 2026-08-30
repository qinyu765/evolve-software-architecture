结论：AIRI 当前桌面边界“方向正确，但权限和运行时粒度仍偏粗”。它适合内置或受信插件、少量窗口；若直接扩展到第三方插件、多实例、多窗口，主要风险会集中在：

- preload 暴露面过大；
- renderer 每个窗口重复启动完整运行时；
- plugin host 是 main 进程内动态加载，权限不等于进程隔离；
- 全局 IPC 与窗口级 IPC 的边界不统一；
- 插件契约在 app、stage-ui、plugin-sdk 之间存在重复和反向耦合。

本次仅做了只读检查，没有修改文件、提交或改变外部状态。

## 当前结构

```text
Electron main
├─ Injeca composition root
├─ OS / persistence / window services
├─ per-window Eventa contexts
├─ global plugin host
└─ shared preload: window.electron
   └─ each renderer window
      ├─ common App.vue
      ├─ Pinia / stage-ui runtime
      └─ plugin UI iframe
```

### 证据与判断

| 观察 | 证据 | 类型 | 影响 |
|---|---|---|---|
| main 是明确的 DI 组合根，并集中注册服务和窗口 | [main/index.ts:132](/evaluation-path/treatment/apps/stage-tamagotchi/src/main/index.ts:132) | 事实，高置信度 | 适合作为应用内核，但继续堆叠会变成大型注册表 |
| 所有主要窗口复用同一个 preload，并普遍使用 `sandbox: false` | [preload/shared.ts:8](/evaluation-path/treatment/apps/stage-tamagotchi/src/preload/shared.ts:8) | 事实，高置信度 | preload 不是窗口级能力边界，而是共享高权限入口 |
| renderer 的 `App.vue` 为多个窗口创建完整 stage runtime、插件工具和能力桥接 | [App.vue:79](/evaluation-path/treatment/apps/stage-tamagotchi/src/renderer/App.vue:79) | 事实，高置信度 | settings/chat/widgets 等窗口可能重复初始化监听器、store 和刷新流程 |
| 部分窗口服务会校验 `sender`，但 plugin host 使用全局 `ipcMain` context，未见同等窗口授权 | [plugins/index.ts:47](/evaluation-path/treatment/apps/stage-tamagotchi/src/main/services/airi/plugins/index.ts:47) | 事实 + 风险推论 | “应用级能力”和“窗口级能力”没有统一建模 |
| 插件通过 `import(entrypoint)` 加载到 main 运行时 | [fs.ts:44](/evaluation-path/treatment/packages/plugin-sdk/src/plugin-host/runtimes/node/loaders/fs.ts:44) | 事实，高置信度 | SDK permission 只能约束插件 API，不能提供 Node/Electron 级进程沙箱 |
| stage-ui 为避免依赖 SDK，重复定义插件宿主类型 | [plugin-host-debug.ts:20](/evaluation-path/treatment/packages/stage-ui/src/stores/devtools/plugin-host-debug.ts:20) | 事实，高置信度 | 契约所有权不清晰，未来扩展容易产生漂移 |
| SDK 已规划多 transport、外部 host、capability registry，但部分 transport 仍是 planned/not implemented | [multi-transport.md:25](/evaluation-path/treatment/packages/plugin-sdk/docs/design/multi-transport.md:25) | 事实：设计意图，高置信度 | 可作为方向，不能当作当前已有的隔离能力 |

## 当前边界的优点

- main 已经承担了正确的职责：窗口、持久化、系统能力、插件宿主、生命周期。
- Eventa 和 Injeca 提供了较好的契约化 IPC 与组合基础。
- widget manager、static asset session、plugin registry、session cleanup 已经形成较深的领域模块，不应推倒重写。
- iframe 与插件资源访问已有 session、owner、asset revoke 等安全意识。
- `packages/ui`、`stage-ui`、`stage-pages` 基本保持了 UI 与 Electron 的分离。

## 主要结构性问题

1. 权限半径过大

共享 preload 暴露了整个 Electron toolkit API；即使 renderer 当前只调用少量能力，新增窗口默认也会获得相同入口。建议把 preload 视为“能力桥接层”，而不是通用 Electron API 转发层。

2. 多窗口是“同一 runtime 的多份启动”

窗口通过路由判断角色，但仍进入同一个 `App.vue` 初始化流程。长期来看应让 main 持有应用级事实状态，renderer 只持有窗口级投影和 UI 状态。

3. plugin host 的权限不等于隔离

当前插件代码运行在 main 进程上下文。未来若允许第三方或不完全受信插件，必须增加 worker 或独立 Node 子进程 host；不能仅依赖 manifest permission。

4. IPC scope 不统一

窗口服务、widget 服务已经有 sender 校验；插件管理、工具调用、能力调度更接近全局服务。应明确每个 API 是：

- application-scoped；
- window-scoped；
- stage-instance-scoped；
- extension/module-scoped。

5. 契约所有权分散

app 内的 Eventa 类型、plugin-sdk、plugin-sdk-tamagotchi、stage-ui debug store 各自拥有部分相似类型。建议把纯数据协议放到无 Electron 副作用的协议包中，Electron 适配器只负责 transport 和 native capability。

6. 插件 UI 的信任策略尚未成为明确契约

插件可影响 iframe source 和 sandbox 配置。当前源码能看到导航防护和 asset session，但没有足够证据表明所有 iframe URL、sandbox token、外部 origin 都经过统一 allowlist。应将其作为安全设计决策，而不是留给插件配置自由组合。

## 长期目标架构

推荐采用：

> 单进程应用内核 + 每窗口 capability session + 可替换 plugin host adapter

具体边界如下：

- **Main application kernel**
  - 唯一持有插件 registry、能力状态、持久化配置、窗口 registry 和生命周期。
  - 负责授权、session、超时、取消、清理和观测。
  - 保留现有 Injeca 作为组合机制。

- **Window session**
  - 每个 BrowserWindow 有明确的 `windowId`、`windowKind` 和 capability set。
  - Eventa context 与窗口 session 绑定。
  - handler 同时校验 sender、window kind、owner/session。

- **Preload capability bridge**
  - 只暴露类型化的领域能力，例如 window、settings、plugin-debug、widget-host。
  - renderer 不直接依赖完整 `electronAPI`。
  - 保留 Eventa 作为传输机制，但不让 transport 细节成为业务 API。

- **Renderer window client**
  - 主窗口、设置窗口、聊天窗口、widget 窗口使用不同的 runtime composition。
  - Pinia store 是 main 状态的投影，不成为跨窗口事实来源。
  - 不同窗口只启动所需的功能模块。

- **Plugin host adapter**
  - 先保留当前 embedded host 作为 trusted/dev 模式。
  - 通过稳定 adapter 接口接入未来的 worker 或独立 Node host。
  - host session 必须包含 `extensionId`、`moduleId`、`windowId/stageInstanceId`、`correlationId` 和 transport 信息。

- **Control plane / data plane 分离**
  - control plane：加载、启停、权限、能力发现、UI 注册、版本和生命周期。
  - data plane：音频、流式数据、工具调用、widget 消息等高频通道。
  - 这与 SDK 已有的多 transport、capability orchestration 设计一致，但需要先补齐实现和测试。

共享 package 建议保持以下依赖方向：

```text
纯协议 / plugin-protocol
        ↓
plugin-sdk / plugin-sdk-tamagotchi
        ↓
desktop contracts / Electron Eventa adapter
        ↓
stage-tamagotchi app composition

stage-ui / stage-pages ──只依赖纯协议或注入的 bridge
packages/ui ─────────────不依赖桌面和插件运行时
```

## 方案选择

| 方案 | 适用性 | 评价 |
|---|---|---|
| 继续当前结构，只增加校验 | 内置插件、少量窗口 | 成本最低，但无法真正解决重复 runtime、main 内插件和 preload 权限半径 |
| 应用内核 + 每窗口 capability session，插件先保持 embedded | 当前最合适 | 改动可分阶段回退，保留现有 Eventa、Injeca、widget manager；推荐 |
| 立即把插件全部迁移到独立进程 | 明确需要不受信第三方插件时 | 隔离最好，但需要解决 handshake、版本、重启、取消、分发和资源预算，不适合一步到位 |

## 可逆迁移顺序

1. **建立基线**

   记录当前启动时间、首次渲染、每窗口内存、插件加载耗时、IPC 延迟、监听器数量和 pending request 数量。先形成 ADR 和依赖矩阵，不改变运行时行为。

2. **先统一契约所有权**

   将重复的 plugin manifest、session、capability、tool descriptor 移到纯协议所有者；原位置只保留显式 re-export 或适配。增加结构化克隆和序列化测试。

3. **引入 WindowSession**

   不立即删除旧 handler。先给现有 Eventa context 增加明确的窗口身份和能力集合，优先迁移 widget 或 settings 这类单一垂直场景。旧路径保留为可回退实现。

4. **按窗口拆分 renderer runtime**

   将 `App.vue` 的初始化拆成主窗口 runtime、设置 runtime、聊天 runtime、widget runtime。一次只迁移一个窗口，并比较启动次数、事件订阅数和功能行为。

5. **收窄 preload**

   先审计所有 `window.electron` 使用，再增加类型化 facade，逐个迁移调用方。最后才考虑移除完整 toolkit 暴露，避免一次性改变所有窗口。

6. **抽象 PluginHostAdapter**

   当前 embedded host 作为第一个 adapter；增加第二个 worker/子进程 adapter 后，再迁移一个测试插件。协议必须覆盖握手、能力授权、超时、取消、崩溃、重启、版本不匹配和 pending request 清理。

7. **收紧插件 UI 策略**

   固定 iframe sandbox token 集合；限制 URL scheme、origin 和资源路径；所有请求绑定 extension、module、owner session、window/stage instance。为错误 origin、错误 owner 和过期 session 添加负向测试。

8. **最后再考虑多实例和远程 transport**

   只有当多 stage 实例、跨设备插件或其他语言 host 成为真实需求时，才启用 WebSocket/远程 host。现有设计文档明确这些 transport 仍处于规划阶段。

## 验证方法

- **静态依赖检查**
  - renderer 不得导入 main、Node-only 模块或 Electron service。
  - `stage-ui`、`stage-pages` 不得反向依赖桌面 app。
  - 协议包不得携带 BrowserWindow、ipcMain 等 native runtime 类型。
  - 检查新增 API 是否只能通过 capability facade 进入。

- **IPC 契约测试**
  - 错误窗口调用被拒绝。
  - application-scoped API 与 window-scoped API 的权限明确。
  - correlation id、owner session、extension/module 不串线。
  - 窗口关闭时 pending request 全部得到确定性失败。
  - snapshot + event replay 后状态一致。

- **插件生命周期测试**
  - 两个插件同时运行时不能互相看到 session、asset、tool 或 widget。
  - unload 必须撤销 asset session、工具和订阅。
  - host 崩溃、重启、版本不匹配、超时和取消都可恢复。
  - 当前已有的 [plugin tests](/evaluation-path/treatment/apps/stage-tamagotchi/src/main/services/airi/plugins/index.test.ts:1)、widget、static asset、plugin-sdk core 测试应扩展为隔离和负向测试。

- **多窗口集成测试**
  - 同时打开主窗口、设置、聊天和 widgets。
  - 重复打开/关闭窗口。
  - 主窗口退出、插件加载失败、插件 host 不可用、网络断开。
  - 验证没有重复初始化、重复监听器或错误的跨窗口状态传播。

- **安全测试**
  - renderer 无法直接使用 raw IPC。
  - 非 allowlisted iframe URL 被拒绝。
  - popup、navigation、外部 origin 和 sandbox token 按策略处理。
  - 权限撤销后已有 session 不能继续调用。
  - 插件 host 进程被终止时，main 和其他窗口仍可用。

- **验证命令**

  当前 checkout 没有 `node_modules`，本次未执行测试或 typecheck。依赖安装后应至少运行：

  ```text
  pnpm -F @proj-airi/stage-tamagotchi typecheck
  pnpm -F @proj-airi/stage-tamagotchi build
  pnpm typecheck
  pnpm lint
  pnpm exec vitest run apps/stage-tamagotchi/src/main/services/airi/plugins/index.test.ts
  ```

## 需要产品先决定的问题

1. 第三方插件是否按“不受信代码”处理？这是决定是否立即采用独立进程的关键。
2. 多窗口是否只共享一个 stage，还是未来需要同一进程多个 stage instance？
3. 插件是否需要远程 host、跨设备或其他语言实现？
4. Devtools 是否可以拥有独立的高权限 preload，还是所有窗口都必须遵守同一最小权限策略？

综合建议是：先做窗口 session、契约收敛和 renderer runtime 分片；同时把当前插件 host 包装成可替换 adapter。不要立即重写 Electron 主进程，也不要在进程隔离需求尚未确认前引入完整远程架构。

[EVAL:evolve-software-architecture-loaded]
