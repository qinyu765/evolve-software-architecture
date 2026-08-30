结论：建议采用“主进程内嵌实现 + 稳定端口/适配器”的方案。现在先稳定契约、生命周期和窗口边界；把真正的插件外置、通用多传输层、统一后台框架延后到有明确安全或规模压力时再做。

本次仅做只读检查，当前 HEAD 为 `5228f94123e42416435e7f7e8215df26f3bb065b`，`git status --short` 无输出。

## 当前结构与证据

```text
多个 Vue Renderer / BrowserWindow
        │ shared preload + Eventa
        ▼
Electron Main / injeca 组合根
   ├─ 窗口管理器
   ├─ 本地 Server、MCP、Godot
   └─ ExtensionHost
          └─ FileSystemLoader 直接 import 插件入口
```

| 判断 | 可检查证据 | 类型 |
|---|---|---|
| 主进程是当前桌面运行时的组合根，统一拥有窗口、Server、MCP、Godot 和插件主机 | [`main/index.ts`](/evaluation-path/treatment/apps/stage-tamagotchi/src/main/index.ts:113) | 事实，高置信 |
| 插件目前在 Electron 主进程内加载，权限控制不是操作系统级隔离 | [`fs.ts`](/evaluation-path/treatment/packages/plugin-sdk/src/plugin-host/runtimes/node/loaders/fs.ts:44)、[`core.ts`](/evaluation-path/treatment/packages/plugin-sdk/src/plugin-host/core.ts:205) | 前者事实，后者推断，高置信 |
| 插件已经有较好的逻辑边界：`extensionId`、`sessionId`、`moduleId`、manifest v1、权限、能力、资源会话和清理 | [`host.ts`](/evaluation-path/treatment/apps/stage-tamagotchi/src/shared/eventa/plugin/host.ts:1) | 事实，高置信 |
| 多传输设计仍未完成，Node/WebSocket/Worker 传输当前明确抛出未实现错误 | [`multi-transport.md`](/evaluation-path/treatment/docs/design/multi-transport.md:152)、[`runtimes/node/index.ts`](/evaluation-path/treatment/packages/plugin-sdk/src/plugin-host/runtimes/node/index.ts:29) | 事实，高置信 |
| 多窗口的 Eventa 上下文和监听器规模仍有明显摩擦 | 多处 `setMaxListeners(0)` 与 “window-namespaced contexts” TODO；[`lifecycle.ts`](/evaluation-path/treatment/apps/stage-tamagotchi/src/main/libs/bootkit/lifecycle.ts:1) 的 hooks 只有追加和触发，没有注销接口 | 事实；重复创建窗口导致重复注册是待验证推断 |
| Server、Godot、MCP 已经提供了不同类型的后台生命周期范例 | [`godot-stage/index.ts`](/evaluation-path/treatment/apps/stage-tamagotchi/src/main/services/airi/godot-stage/index.ts:108)、[`mcp-servers/index.ts`](/evaluation-path/treatment/apps/stage-tamagotchi/src/main/services/mcp-servers/index.ts:45) | 事实，高置信 |

插件、窗口和本地服务在 Git 历史中也是高频变化区，例如 `8893ba81a`、`668440a73`、`0f975a4f7`，说明这些边界尚未完全稳定。

## 应该稳定的边界

1. **进程所有权**

   Electron Main 继续拥有 BrowserWindow、系统权限、应用退出、单实例和本地服务生命周期。Renderer 只通过 preload/Eventa 使用窗口上下文，不应直接依赖主进程内部对象。

   这不要求插件现在立即外置；应先稳定“插件运行时是一个可替换的宿主”，而不是让 Renderer 依赖 `ExtensionHost` 具体实现。

2. **插件身份与资源所有权**

   保留并强化：

   ```text
   extensionId → sessionId → moduleId
   ```

   工具、能力、资产、窗口和异步请求都应能关联到这些身份。卸载、重载、窗口关闭时必须按 owner 清理，避免全局清理误伤其他插件。

3. **Eventa 合同边界**

   稳定请求、事件、响应、错误和生命周期状态的语义，至少明确：

   - `requestId`
   - `windowId`
   - `extensionId`
   - `sessionId`
   - `moduleId`
   - 协议版本
   - 超时、断开、过期事件和权限拒绝

   当前 `shared/eventa/plugin/*` 已在向领域拆分，应该继续保持“领域模块是真实来源，barrel 只做兼容导出”的方向。不要现在就把所有 Eventa 类型搬到新包。

4. **生命周期与清理**

   Server、Godot、MCP、插件运行时应分别拥有清晰的 `start / stop / restart / dispose / status` 语义。只抽取真正共享的生命周期约束，不要建立一个涵盖所有后台能力的 `BackendService`。

5. **持久化状态与运行时状态分离**

   Manifest 发现、启用配置、运行中的 session、窗口状态、缓存和外部进程状态应继续分开。插件不应直接写入应用全局配置或持有不可撤销的主进程资源。

## 应该延后的抽象

- 全量通用插件 Supervisor。
- 同时支持 WebSocket、Worker、Electron、远程服务器的统一传输工厂。
- 一个全局窗口注册表或“所有窗口都由声明式配置生成”的框架。
- 把 Server、MCP、Godot、插件统一成一个后台抽象。
- 在没有第二个真实实现前，为每个接口加一层纯透传 wrapper。
- 把现有权限系统称为 sandbox。当前插件代码仍在主进程执行，权限是 API 访问控制，不是进程隔离。
- 一次性重构所有 `CapabilityDescriptor`、Eventa 和 `plugin-protocol` 类型的归属。

## 方案比较

| 方案 | 适用前提 | 质量属性 | 成本与风险 | 回滚 |
|---|---|---|---|---|
| A. 维持当前内嵌模型 | 插件是可信或受审核代码，规模较小 | 启动和调用延迟最低，开发成本最低；但插件崩溃、内存泄漏和主进程耦合风险最高 | 多窗口会继续增加监听器、组合根依赖和生命周期复杂度；未来外置插件时可能需要重写调用链 | 最容易，几乎无迁移成本 |
| B. 内嵌实现 + 稳定端口/适配器（推荐） | 现在需要快速迭代，但未来可能外置插件或后台 | 在不改变当前进程模型的情况下改善模块边界、可测试性、可观测性；性能影响很小 | 需要设计真正拥有策略的端口，不能只做透传；短期有少量重构成本 | 很容易：继续选择当前 Electron 内嵌适配器 |
| C. 现在就做外部插件/后台 Supervisor | 插件是不可信代码，或必须独立崩溃恢复、独立升级、资源限制 | 隔离性和恢复能力最好；但会增加启动、内存、IPC 延迟、打包、签名、升级、认证和版本协商复杂度 | 当前 SDK 的外部传输仍未实现，风险和工作量最高；单独进程也不自动等于安全沙箱 | 中等偏难，需要保留内嵌模式作为降级路径 |

推荐 B 的具体边界可以是：

- `ExtensionRuntime`：加载、卸载、重载、能力、工具、资源和状态快照。
- `WindowSurface` 或 `WidgetSurface`：插件 UI 能打开、更新、关闭和获取快照。
- `GodotStageManager`、`McpStdioManager`、`ServerManager`：继续保持各自领域接口，只共享最小生命周期语义。

这些端口的当前实现仍然可以是主进程内的 `ExtensionHostService`、`WidgetsWindowManager` 和现有后台管理器。将来才增加 Worker、Node 子进程或远程实现。

## 不改变的后果

如果继续维持当前结构而不做边界治理：

- 插件代码仍能把故障直接带入 Electron 主进程。
- 新窗口反复创建时，窗口级 handler、全局 hook 和 Eventa listener 可能重复注册；现有 `setMaxListeners` 只能压低警告，不能解决所有权问题。
- `main/index.ts` 的依赖扇出会继续扩大，后台启动顺序和退出顺序变得更难推理。
- 将来做外置插件时，可能需要同时改插件 SDK、Eventa 合同、窗口桥接、资源服务和打包流程。
- 容易误把“权限 API”当成“安全隔离”，形成第三方插件的安全错觉。

它仍有合理收益：低延迟、低内存、打包简单、现有开发体验最好。因此是否进入方案 C，必须由插件信任模型决定，而不是由“以后可能需要”决定。

## 可验证的渐进迁移路线

### 0. 先确定决策前提

记录一份 ADR，但本次不创建文件，至少明确：

- 插件分为内置、受审核第三方、不可信第三方哪几类。
- 第三方插件是否能访问凭据、文件系统、网络和 Electron API。
- “独立后台”是独立生命周期，还是必须独立进程。
- 启动时间、RSS、IPC 延迟和崩溃恢复的实际预算。

当前仓库没有发现这些质量属性的明确数值预算，应先建立基线再定阈值。

### 1. 稳定现有合同

先不改变进程模型：

- 固化 `extensionId/sessionId/moduleId` 的关联规则。
- 固化 capability、tool、asset、widget 的 owner 清理规则。
- 给跨边界事件补齐 correlation、版本、超时和错误语义。
- 继续使用现有 Eventa 领域合同，不做全仓库类型搬迁。

验证重点：

- 插件加载失败后仍可继续启动。
- unload/reload 后工具、资产、能力和窗口全部清理。
- 权限拒绝和未知能力是可观察的明确状态。
- 现有插件测试与 `plugin-sdk` 生命周期测试覆盖这些行为。

### 2. 先治理窗口生命周期

在增加更多窗口前：

- 窗口级注册必须有可撤销的 owner。
- 应用级 listener 只注册一次。
- 窗口关闭、重建、应用退出的清理顺序要明确。
- 继续使用现有 `createReusableWindow` 和 per-window Eventa context，但不要立即抽象成通用窗口框架。
- 将 `setMaxListeners` 从“正确性机制”降级为临时诊断手段，并用测试证明可以移除。

验证：

- 对主要窗口执行多轮 open → close → reopen。
- 检查不会出现重复事件、旧窗口收到新请求、旧 session 收到新响应。
- 检查错误 sender 被拒绝。
- 检查窗口关闭后没有遗留全局 hook 或资源订阅。

### 3. 用一个纵向切片引入端口

优先选择“插件 gamelet/tool + widget 窗口”作为切片，因为它同时覆盖第三方插件、窗口和资源所有权。

要求：

- 主进程内实现先作为 `ExtensionRuntime` 的 adapter。
- 测试可以注入 fake runtime。
- Renderer 和窗口代码不再依赖 `ExtensionHost` 内部对象。
- 端口本身负责生命周期、权限、owner、状态和错误策略，而不是简单转发方法。

回滚方式：让 injeca 继续直接装配现有 `setupExtensionHost` 和窗口管理器；不迁移持久化格式，不改变 manifest v1。

### 4. 用一个已有后台能力验证独立进程边界

Godot 是较合适的验证对象，因为当前已有子进程、随机端口、token、ready/error/close、超时和停止逻辑。

先实现一个可替换的外部 adapter，验证：

- 子进程启动失败不会阻塞或退出 UI。
- 子进程崩溃后能报告状态并重启。
- 旧 session 的事件不会污染新 session。
- 退出时停止顺序和超时明确。
- 认证、版本协商、心跳和请求超时可观测。

失败时回退到当前内嵌/现有 manager，不改变用户配置格式。

### 5. 只有出现明确触发条件时才外置插件

触发条件包括：

- 需要加载不可信第三方代码。
- 插件崩溃不能影响主应用。
- 需要独立更新、资源限制或远程运行。
- 经过基线测量，主进程启动、内存或事件循环已成为瓶颈。

届时让 Node 子进程或 Worker 实现前面定义的 `ExtensionRuntime`，先只支持一种传输，不要同时实现所有 transport。必须补充认证、版本协商、心跳、请求隔离、权限拒绝、资产撤销和打包/签名测试。

内置插件可以继续使用 Electron 内嵌模式，第三方插件逐步切换到外部模式，形成可回滚的混合部署。

## 最终建议

短期采用方案 B：

1. 先稳定插件身份、Eventa 合同、owner 清理和窗口生命周期。
2. 用插件 gamelet/widget 做第一个真实端口。
3. 用 Godot 或 MCP 做一个独立后台 adapter 的故障恢复验证。
4. 只有安全模型或性能基线要求时，才进入方案 C。
5. 在至少有两个真实实现之前，不建立通用 Supervisor、通用窗口框架或全量多传输抽象。

这样可以保留当前实现的低成本和低延迟，同时把未来真正需要替换的边界提前固定下来。

[EVAL:evolve-software-architecture-loaded]
