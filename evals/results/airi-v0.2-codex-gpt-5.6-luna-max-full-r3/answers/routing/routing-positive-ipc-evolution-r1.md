结论：建议保留 Eventa 作为内部事件/RPC 原语，但逐步把 renderer 面向 Electron 的入口收敛为类型化的 `window.airi` 能力桥。main 负责状态、权限和副作用；preload 只负责窄桥接与序列化；renderer 不再直接接触 `ipcRenderer`、Electron 类型或 `IpcMainEvent`。

```text
renderer feature
  -> window.airi.<domain>
  -> preload transport adapter
  -> main WindowScope / AppScope
  -> domain service
```

## 范围与信心

仓库是多窗口 Electron + Vue 单体应用，主要对象是 `apps/stage-tamagotchi`，同时共享 `stage-ui`、`stage-pages` 和 `stage-shared`。对当前 IPC 结构的判断信心高；对 Eventa 内部实现细节不做额外假设，以仓库现有用法为准。

## 观察事实

| 事实 | 证据 | 影响 |
| --- | --- | --- |
| 所有主要窗口复用同一个 preload，且显式 `sandbox: false` | [electron.vite.config.ts:81](</evaluation-path/treatment/apps/stage-tamagotchi/electron.vite.config.ts:81>)、[main/index.ts:80](</evaluation-path/treatment/apps/stage-tamagotchi/src/main/windows/main/index.ts:80>) | preload 是高价值的能力边界，不能长期暴露通用 IPC |
| preload 暴露了 `electronAPI`，renderer 可取得通用 `ipcRenderer` | [preload/shared.ts:8](</evaluation-path/treatment/apps/stage-tamagotchi/src/preload/shared.ts:8>)、[stage-shared/window.ts:1](</evaluation-path/treatment/packages/stage-shared/src/window.ts:1>) | renderer 与 Electron/Eventa transport 耦合 |
| Eventa 契约已集中，但应用 barrel 达约 500 行，插件才开始按领域拆分 | [shared/eventa/index.ts](</evaluation-path/treatment/apps/stage-tamagotchi/src/shared/eventa/index.ts>)、[plugin/domains.test.ts:42](</evaluation-path/treatment/apps/stage-tamagotchi/src/shared/eventa/plugin/domains.test.ts:42>) | 应延续领域模块 + 兼容 barrel 的模式 |
| main 已有按窗口创建 context，但仍大量手动检查 sender | [shared/window.ts:134](</evaluation-path/treatment/apps/stage-tamagotchi/src/main/windows/shared/window.ts:134>)、[widgets/index.ts:33](</evaluation-path/treatment/apps/stage-tamagotchi/src/main/services/airi/widgets/index.ts:33>) | 窗口授权策略没有统一归属 |
| 多处调用 `ipcMain.setMaxListeners(0)`，代码注释明确 Eventa 尚未提供 window namespace | [main/rpc/index.electron.ts:43](</evaluation-path/treatment/apps/stage-tamagotchi/src/main/windows/main/rpc/index.electron.ts:43>) | 这是生命周期/监听器治理缺口的信号，不应成为长期解决方案 |
| 错误传播混合使用 throw、`{ ok: false }` 和状态事件 | [widgets/validation.ts:49](</evaluation-path/treatment/apps/stage-tamagotchi/src/main/services/airi/widgets/validation.ts:49>)、[channel-server/index.ts:504](</evaluation-path/treatment/apps/stage-tamagotchi/src/main/services/airi/channel-server/index.ts:504>) | 需要稳定的错误分类，而非统一强行改成 Result |
| 测试已有良好的 in-memory context 和 sender 隔离测试，但 preload/真实 adapter 覆盖较少 | [app.test.ts:32](</evaluation-path/treatment/apps/stage-tamagotchi/src/main/services/electron/app.test.ts:32>)、[widgets/index.test.ts:68](</evaluation-path/treatment/apps/stage-tamagotchi/src/main/services/airi/widgets/index.test.ts:68>) | 应保留纯 handler 测试，再补 bridge contract 测试 |
| 当前 Electron 为 `^41.2.1`，部分共享包 peer range 仍限制 `<41` | [pnpm-workspace.yaml:255](</evaluation-path/treatment/pnpm-workspace.yaml:255>)、[electron-eventa/package.json:31](</evaluation-path/treatment/packages/electron-eventa/package.json:31>) | 这是需要先澄清的发布与升级约束 |

## 当前主要摩擦

- renderer 直接创建 Eventa renderer context，甚至在共享包中读取 `window.electron.ipcRenderer` 并使用 `as any`，导致 Web/Electron 分支和测试替身不断扩散。
- 窗口级 handler 的注册、sender 校验、事件广播和清理由各服务自行决定；部分 handler 捕获 disposer，部分没有，重复创建 settings/widgets/onboarding 窗口时存在监听器累积风险。这是推断，需用窗口反复创建压力测试确认。
- Electron IPC 契约 ID 当前没有明确版本；插件 manifest 的 `apiVersion: v1` 是插件协议版本，不等于 Electron 内部 IPC 版本。
- 契约大量使用 Electron `ReturnType`、`Parameters` 以及宽泛 `Record<string, any>`，容易把 Electron 类型变化直接传导到 renderer。
- `useElectronEventaContext` 使用模块级 singleton；单个 renderer 窗口内合理，但不适合未来同一页面同时拥有多个 transport 或多个 capability scope。

## 质量属性优先级

1. **进程边界稳定性与生命周期正确性**：操作 ID、窗口归属、清理和错误形状必须可预测。
2. **测试隔离性**：业务服务应可用 in-memory port 测试，不依赖 Electron runtime。
3. **安全与能力最小化**：不要让 renderer 持有通用 IPC 入口；main 统一判断 sender 和窗口 profile。
4. **迁移成本**：不做一次性重写，保留现有 Eventa ID，按领域逐步迁移。
5. **性能**：高频 stage-three trace、beat-sync 等继续使用 renderer-local Eventa/BroadcastChannel，不要不必要地绕经 main。

## 可行方案

### A. 保持 Eventa 直连，集中治理

保留 renderer 直接使用 Eventa，只新增：

- `WindowScope` / `AppScope`
- 统一 sender 校验
- handler disposer 聚合
- Valibot 边界校验
- 统一错误码

优点是迁移成本最低，最符合当前代码。缺点是 preload 仍然暴露 transport，renderer 和共享包仍然知道 Electron。

### B. 类型化 `window.airi` capability bridge

推荐作为目标形态：

- preload 暴露 `window.airi.window`、`window.airi.widgets`、`window.airi.plugins` 等窄能力接口；
- Eventa 留在 bridge 内部作为 transport/事件实现；
- renderer 只依赖能力接口和订阅函数；
- Web 端通过注入的空实现或 Web adapter 提供同一业务接口；
- main 通过统一的 `WindowScope` 注册窗口级 handler，通过 `AppScope` 注册全局服务。

不要暴露公开的 `invoke(channel, unknown)`；那只是把 raw IPC 换成了字符串总线。

优点是边界、测试和安全性最好。缺点是需要维护 facade，事件、流式调用和多窗口广播的迁移成本较高。

### C. 建立一个全局通用 IPC broker

所有请求都包装成 `{ version, method, payload, requestId }`，由一个 router 分发。

不建议。它会削弱现有 Eventa 的类型和领域 locality，容易形成新的“万能总线”，同时并不能自动解决窗口授权和清理问题。

## 推荐设计

选择 B 作为长期目标，采用 A 的治理方式作为过渡。

### 契约

- 继续把契约放在纯 shared 模块；沿用现有插件的领域拆分方式，`index.ts` 只做兼容 re-export。
- `@proj-airi/electron-eventa` 负责跨应用复用的 Electron 契约；应用专属契约留在 `stage-tamagotchi`。
- 契约旁边同时定义：
  - wire DTO；
  - Valibot schema；
  - scope：`app`、`window`、`broadcast`；
  - 错误策略；
  - 是否允许取消/超时。
- 不要把 `BrowserWindow`、`Display` 等 Electron 运行时对象直接当作长期 wire contract；使用稳定的 JSON/structured-clone DTO。

### 版本

- 现有 `eventa:*` ID 视为隐式 v1，不要一次性重命名。
- 向后兼容的变化只新增可选字段，并保证旧消费者可忽略。
- 不兼容变化创建新的 contract ID，例如现有 ID 加 `:v2`，旧 handler 和新 handler 在明确迁移期内共存。
- 不要给每条消息强行增加通用版本 envelope；只有在插件、第三方 renderer 或独立发布的客户端存在时，才增加 bridge capability/handshake。
- 不保留无期限的静默兼容 fallback；每个临时双注册都应有移除条件。

### 错误

保留三类语义：

- 操作失败、权限失败、窗口不存在、未就绪、超时：main 抛出可序列化的 `IpcError`，renderer 的 Promise reject。
- 业务上正常但结果为否：继续使用 discriminated union，例如现有 shortcut/MCP test 的 `{ ok: false, ... }`。
- 长生命周期任务：继续使用状态事件，例如 updater/Godot 的 `status` 和 `lastError`。

建议稳定暴露：

```text
code: INVALID_ARGUMENT | FORBIDDEN | NOT_READY | UNAVAILABLE
      | CANCELLED | TIMEOUT | INTERNAL
message: 可展示文本
retryable?: boolean
details?: 经过 schema 限制的安全数据
```

日志中额外记录 operation、requestId、webContents.id；不要依赖跨进程传输完整 `Error` 对象，也不要把 token、密钥或不必要的本地路径放进 details。

### 窗口生命周期

建立单一的窗口 registry：

- `createAppScope()`：server channel、plugin host 等全局服务。
- `createWindowScope(window, profile)`：窗口状态、widgets、screen capture、auth 等。
- 每个 scope 返回一个 disposer，绑定 `closed`、`webContents.destroyed` 和 `render-process-gone`。
- sender 校验集中在 scope/adaptor，不再让每个 handler 手写 `options.raw.ipcMainEvent.sender.id`。
- 广播必须显式指定目标窗口或 profile。
- 在 disposer 完整前，不应继续用 `ipcMain.setMaxListeners(0)` 掩盖问题。

## 迁移与验证

1. 先建立契约清单，按 `app/window/broadcast` 分类；不修改现有 ID。
2. 以 `window lifecycle` 为第一个 vertical slice，同时覆盖一个 invoke、一个事件订阅、一个错误路径。不要从 updater 或 MCP 这种高复杂度领域开始。
3. 为该 slice 增加 `window.airi` facade，内部暂时调用现有 Eventa contract；旧调用仅作为明确的临时迁移路径。
4. 迁移 `setupBaseWindowElectronInvokes`，让所有 per-window service 返回清理函数；优先处理 settings、widgets、onboarding、notice 等可重复创建窗口。
5. 迁移 renderer 中直接访问 `window.electron.ipcRenderer` 的调用点，特别是 `stage-ui`、`stage-pages` 中的 Electron 分支；共享业务逻辑改为注入 desktop capability。
6. 再处理 widgets、plugin tools/capabilities、MCP、screen capture 的 runtime schema 和错误码。
7. 最后收紧 preload，删除 renderer 对 raw `ipcRenderer` 的依赖，并解决 Electron peer range 不一致。

验证标准：

- contract/schema 测试覆盖成功、非法 payload、旧字段缺失和不可序列化数据。
- handler 测试使用 `createContext()`，验证同窗口、跨窗口、销毁窗口和错误码。
- preload facade 使用 fake transport 测试 invoke、事件订阅和 unsubscribe。
- 反复创建/关闭 settings/widgets 窗口，确认 handler/listener 数量不增长。
- 保留一个真实 Electron smoke，覆盖 main → preload → renderer 的成功和失败往返；仓库已有 [desktop-overlay-live-window-smoke](</evaluation-path/treatment/apps/stage-tamagotchi/scripts/desktop-overlay-live-window-smoke.ts>) 可作为基础。
- 完成后执行仓库要求的 typecheck、lint、目标 Vitest 和 desktop build，并用 `rg` 确认 raw IPC 只存在于 bridge/测试层。

## 开放决策

只有以下问题会改变推荐强度：

- main、preload、renderer 是否始终随同一个 Electron artifact 原子发布？若是，通常不需要复杂 handshake；若插件或第三方 renderer 可独立升级，则必须正式定义 protocol version。
- 插件 iframe 或外部页面是否可能进入这些 privileged BrowserWindow？若可能，应更早拆分 capability preload。
- Electron 41 是否是正式统一版本？当前 peer range 不一致，需要在升级前解决。
- Eventa 是否会提供稳定的 window namespace/lifecycle API？若不会，A 中的 `WindowScope` wrapper 就应成为 AIRI 自己的长期边界。

本次仅执行了只读检查，工作树保持 clean；没有修改文件、创建提交或改变外部状态。

[EVAL:evolve-software-architecture-loaded]
