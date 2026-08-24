# Electron main / preload / renderer IPC 长期演进方案（AIRI）

## 1. 范围与置信度

**范围**：为 `apps/stage-tamagotchi` 的 Electron 三进程 IPC 层（main、preload、renderer）给出可长期演进的架构建议，重点权衡你点名的四个维度：契约版本、错误传播、测试隔离、迁移成本。只给建议，不改代码。

**仓库分类（置信度：高）**：桌面 Electron 应用，但 IPC 层刻意建立在 transport-agnostic 的 `@moeru/eventa` 之上，且 plugin SDK 已有本地/远端 channel 抽象（`packages/plugin-sdk/src/channels/`）。因此这**不是**一个"Electron 专用 RPC"问题，而是一个"事件/RPC 契约如何随桌面壳长期演进"的问题。

**置信度说明**：以下所有事实均来自源码直接观察并附路径；推断会标注【推断】；无法确认处标注【未知】。`node_modules` 未安装，所以 eventa Electron adapter 的错误序列化细节和 `@electron-toolkit/preload` 的精确暴露面无法直接读源码验证。

## 2. 观察事实（证据）

- **Eventa 是 IPC 唯一骨架**。契约用 `defineInvokeEventa<Res, Req>(name)` / `defineEventa<T>(name)` 定义，main 用 `defineInvokeHandler(context, contract, handler)` 注册，renderer 用 `defineInvoke(context, contract)` 调用。仓库自带 `.agents/skills/eventa/SKILL.md` 是权威 API 参考。
- **契约分两层**：
  - 传输形态层 `packages/electron-eventa/src/electron/*`（`window.ts:3-28`、`app.ts:1-14`）——直接镜像 `BrowserWindow` 方法签名，如 `Parameters<BrowserWindow['setVibrancy']>`。
  - 领域层 `apps/stage-tamagotchi/src/shared/eventa/index.ts`（约 500 行，~90 个 invoke/event 契约）+ `plugin/*` 子模块。契约名是裸字符串（如 `eventa:invoke:electron:window:close`），**没有任何版本号、没有任何 schema**。
- **preload 是纯透传，不是契约边界**。`src/preload/index.ts` 和 `beat-sync.ts` 都只调用 `expose()`；`preload/shared.ts:19` 只 `contextBridge.exposeInMainWorld('electron', electronAPI)`（通用 toolkit API）。renderer 实际通过 `packages/electron-vueuse/src/composables/use-electron-eventa-context.ts:18-24` 直接读 `window.electron.ipcRenderer` 再构造自己的 eventa context。
- **`sandbox: false` 是当前约束**：`windows/main/index.ts:89-91`、`desktop-overlay/window-contract.ts:37`。这是 renderer 能直接碰 `ipcRenderer` 的前提。
- **invoke 命名空间是全局的，emit 是按窗口的**。每个窗口都 `createContext(ipcMain, window)`（`windows/main/rpc/index.electron.ts:48`），`setupBaseWindowElectronInvokes` 给每个窗口重复注册同一批基础服务（`windows/shared/window.ts:134-149`）。因为所有窗口共享同一个 `ipcMain` EventEmitter，仓库出现重复 TODO："once we refactored eventa to support window-namespaced contexts, we can remove the setMaxListeners call"（`main/index.ts:55-58`、`windows/main/index.ts:211-214`、`windows/main/rpc/index.electron.ts:43-46`、`desktop-overlay/rpc/index.electron.ts:34-37`），并用 `setMaxListeners(100)` / `setMaxListeners(0)` 压掉告警。
- **发送者隔离靠手工 `sender.id` 比较**。`services/electron/window.ts:44-123` 里每个 handler 重复 `options?.raw.ipcMainEvent.sender.id === params.window.webContents.id`，且只有部分服务做了这个校验（`screen.ts`、`app.ts` 没做）。
- **错误传播是非结构化的**。SKILL.md 明确"handlers can throw errors safely — eventa propagates them to the caller"；调用侧统一用 `errorMessageFrom(error)`（`@moeru/std`）或 `errorMessageFromValue`（`packages/stage-shared/src/error-message.ts`）重新提取字符串。跨进程没有错误码、没有信封。唯一的例外是**领域级手写结果信封**，且不一致：widgets iframe 中继用 `{ ok: false, error: string }`（`shared/eventa/index.ts:156-203`），MCP 用 `{ isError?: boolean }`，MCP 测试结果用 `{ ok, error? }`。
- **测试隔离靠整模块 `vi.mock`**。`desktop-overlay/rpc/index.electron.test.ts:11-43` mock 了 `@moeru/eventa`、`@moeru/eventa/adapters/electron/main`、`electron`、两个服务工厂——测的是"接线"，不是契约行为。仓库里更优的种子是纯函数测试缝 `desktop-overlay/window-contract.test.ts`（把 BrowserWindow 选项/输入隔离抽成纯函数，无 Electron）。
- **清理语义不一致**。`defineInvokeHandler` 返回 disposer，但只有 `windows/main/index.ts:217-221` 用了它；`window.ts` 的 handler 不返回 disposer 也不在 `closed` 清理；`powerMonitor.ts`/`screen.ts` 靠全局 `onAppBeforeQuit`/`onAppWindowAllClosed` 清理；`global-shortcut.ts:46-57,162-167` 用 `Set<context>` + `window.on('closed')` 清理。
- **仓库规范约束**（AGENTS.md）：用 Valibot 做 schema 校验且贴近消费者；契约集中定义、不重复声明；错误优先 `errorMessageFrom`；**禁止向后兼容守卫**；用 `injeca` DI；`evolve-software-architecture` 要求"少而深的缝，而非宽而薄的层"。

## 3. 当前摩擦（变化放大点）

1. **改一个契约 = 盲改字符串**。契约名和 payload 形貌漂移只在运行时以"renderer 捕获未知 rejection"的形式爆出来，离改动点很远。没有编译期/握手期检测，也没有 edge 校验。
2. **窗口路由是每处手写的**。同一个 `sender.id` 判断在多个 handler 里复制，且有的服务做、有的不做——这既是 bug 温床，也是"窗口命名空间"这件事没人拥有的体现。
3. **错误模型分裂**。同一类"预期失败"有的 throw、有的 `{ok:false}`、有的 `{isError}`，renderer 无法程序化区分"未找到/超时/降级/传输中断"。
4. **测试塔脆弱**。每新增一个服务要堆一层 `vi.mock`，且测不到真实注册/调用/错误往返。
5. **preload 缺席了本应承担的角色**。它是自然的安全/契约咽喉，但现在是透传；这直接锁死了 `sandbox: true`。

## 4. 质量属性优先级（按权重排序，含取舍）

| 排名 | 属性 | 为什么 | 取舍 |
|---|---|---|---|
| 1 | **变更安全 / 可测试性** | 这个仓库主导成本是"不用 Electron 证明 IPC 接线正确" | 牺牲一点运行时魔法，换取契约可单测、可握手校验 |
| 2 | **可演进性（契约局部化 + 版本）** | 长期演进的直接含义 | 不为每个契约上重版本，版本与 schema 按契约价值成比例投入 |
| 3 | **错误语义正确性** | UI 与 MCP/plugin/godot 需要区分"可操作失败"与"降级可用" | 统一信封会约束领域表达，但消除字符串匹配控制流 |
| 4 | **可运维性** | 握手/就绪/契约不匹配要可观测 | 少量启动期成本 |
| 5 | **性能** | 控制面 IPC 无热路径；热流（屏幕/鼠标）已用 renderer loop 节流 | 低优先级 |
| 6 | **安全（约束，非目标）** | `sandbox:false` 是现状，设计应朝 `sandbox:true` 演进而非扩大暴露 | preload 作为唯一咽喉 |

## 5. 方案对比

**方案 0：维持现状**（可辩护的基线）——裸字符串契约 + 全局 invoke 命名空间 + 手工 `sender.id` + `vi.mock` 测试 + throw-with-message 错误。

**方案 1（推荐）：在 Eventa 内演进**——"版本化契约模块 + 统一错误信封 + 窗口命名空间路由 + preload 类型咽喉 + 可注入 in-memory context 的测试缝"。不替换 Eventa，只补上它缺的四样东西。

**方案 2：自研类型化 RPC 桥**——preload `contextBridge` façade + `ipcMain.handle` + 代码生成 client/server + 版本化 channel + schema 注册表，最终替换 Eventa。

| 维度 | 方案 0 维持 | 方案 1 演进（推荐） | 方案 2 自研桥 |
|---|---|---|---|
| 边界与所有权 | 契约分散、路由无人拥有 | 契约+版本+schema 归 shared；窗口路由归一处 helper；错误信封归一处类型 | 全部归新框架，代价最大 |
| 契约版本 | 无 | 应用级握手 + 边缘 schema + 按需契约版本 | 每 channel 强制版本 |
| 错误传播 | throw + 字符串重取，分裂 | 预期失败→类型化结果联合；意外→throw + 一次 `errorMessageFrom` | 全信封化，最严格 |
| 测试隔离 | 整模块 `vi.mock` | in-memory `createContext()` 真跑 main↔renderer，无 Electron mock | 可测但需新 test harness |
| 迁移成本 | 0 | 低（契约、服务、调用点全部复用；preload 迁移是机械替换） | 极高：~150 契约 ×（契约+main+preload+renderer）重写，且要重造 eventa 的 streaming/event 原语 |
| 回滚 | — | 可逐步、可回退（新旧可共存于同一 eventa context） | 一旦替换难以回退 |
| 主要风险 | 继续累积窗口路由/错误分裂债 | 需验证 eventa 在 `sandbox:true` 下的行为【未知】 | 违反仓库"集中 Eventa、不重复声明"规范，两轨并存 |

## 6. 建议（方案 1 的具体形状）

一句话：**把 Eventa 当传输层保留，把 preload 变成唯一的类型化咽喉，在契约定义处补"版本 + Valibot schema"，在窗口路由处补"一处 sender 守卫 + disposer"，在错误处补"一层统一信封"。**

分层如下（自底向上）：

### 6.1 契约层（shared，无副作用，稳定）
- 契约继续用 `defineInvokeEventa`/`defineEventa` 定义并集中放 `shared/eventa/`。**契约名作为稳定标识符，永不作为版本载体**；版本是独立字段。
- 每个契约旁边配一个 **Valibot schema**（贴近消费者，符合仓库规范），让 edge 校验成为默认行为，而不是 SKILL.md 里"validate at edges"的一句空话。
- 版本策略要**克制**：main/preload/renderer 是同一次构建原子发布的，所以**不为每个契约做运行时版本分支**（那会撞上"禁止向后兼容守卫"）。版本的真实价值是：
  1. 一个**应用级握手**（`handshake` invoke 返回 `{ ipcContractVersion, appVersion }`），不匹配时 main 日志亮红灯、renderer 显示"重启/更新"，而不是让 renderer 默默吃未知错误；
  2. **契约级版本只标记真正不兼容的外部化表面**（plugin SDK、server channel、MCP tool schema），用于变更追踪和迁移纪律，不用作运行时分支。

### 6.2 传输/路由层（把窗口命名空间这件事"拥有"起来）
- 首选：引入一个 `createWindowScopedInvokeHandler(context, window, contract, handler)` 助手，**它是唯一触碰 `options.raw.ipcMainEvent.sender.id` 的地方**，并且**始终返回 disposer**。这样 `window.ts` 里十几个重复的 sender 判断消失，handler 体变成 transport-agnostic 纯函数。
- 目标（仓库 TODO 已点名）：eventa 上游支持 window-namespaced context，从根上移除 `setMaxListeners(0/100)`。**不要阻塞在这个上游改动上**——助手是立即可做的、可逆的第一步，上游就绪后助手内部再下沉。
- 窗口创建处收集所有 disposer，`window.on('closed')` 统一 dispose，替代现在"有的清理、有的靠 app-quit、有的不清理"的三态。

### 6.3 preload 层（类型化咽喉，安全+版本的单一咽喉点）
- preload 里用 eventa 的 renderer adapter 构造 context，**遍历契约注册表 `defineInvoke` 生成 client**，再 `contextBridge.exposeInMainWorld('airi', frozenClient)`。页面世界永远不再碰 `ipcRenderer`。
- 迁移友好点：**保持 `useElectronEventaInvoke(contract)` 的 composable 签名不变**，只把它的内部实现从"自建 context 读 `window.electron.ipcRenderer`"改成"调 `window.airi` 暴露的 `invoke(contract)`"。这样 ~60+ 个 renderer 调用点**零改动**，只有 `packages/electron-vueuse` 内部变。
- 这直接解锁 `sandbox: true`（renderer 不再需要 raw ipcRenderer）。【未知】需验证 eventa renderer adapter 在 preload 世界构建 context、经 contextBridge 传冻结函数后，在 `sandbox:true` 下 invoke/emit 双向都工作。

### 6.4 错误层（统一信封，但两层语义）
- **传输层（意外失败/abort）**：保持 throw，renderer 边界**只做一次** `errorMessageFrom` 用于展示。这层不做结构化。
- **领域层（预期、可操作的失败）**：契约的 `Res` 类型用统一结果联合，例如 `{ ok: true, value } | { ok: false, error: { code, message, retryable? } }`，替换现在 ad-hoc 的 `{ok:false}`/`{isError}`/裸 throw 三分裂。给一个共享 helper 类型，所有契约看起来一样。
- 判定标准：**"调用方能据此做控制流"→结果联合；"只能展示给用户"→throw**。不要对同一类失败同时提供 throw 和 `ok:false`。
- 【未知】eventa 的 `ResErr`/`ReqErr` 泛型（`useElectronEventaInvoke<Res, Req, ResErr, ReqErr>`）是否能在跨进程时保留类型化错误，node_modules 缺失无法验证。若不能可靠保留，就以上述显式结果联合为准，不依赖跨进程类型化异常。

### 6.5 测试层（把 in-memory context 用起来，干掉 mock 塔）
- 关键杠杆：eventa SKILL.md 里 `createContext()` 是**同进程内存 context**。只要 handler 体不碰 `options.raw.ipcMainEvent`（由 6.2 的助手隔离），服务就能接受一个 `EventaContext`，测试里 `const { context } = createContext()` 真跑"注册 + invoke + 错误往返"，**完全不用 `vi.mock('electron')` 或 mock eventa adapter**。这是对当前 `desktop-overlay/rpc/index.electron.test.ts` mock 塔的直接替代。
- 三层测试缝：
  1. 契约+schema 纯校验（无 mock）：名字唯一、schema 合法、无重复注册；
  2. handler 单测：handler 体是 `(payload, services) => result` 纯函数，services 用 `vi.fn` DI；
  3. 接线测试：用 in-memory context 断言"N 个契约被注册、disposer 清理干净"。
- 把 `window-contract.ts` 这种"抽纯函数"模式推广成服务层的默认形态。

## 7. 迁移与验证（可逆步骤）

**迁移是渐进、可回退的**，因为新旧路径共享同一 eventa context：

1. **第一步（最小，立即）**：`createWindowScopedInvokeHandler` 助手 + disposer 收集。它不改变任何契约，只消除复制粘贴的 sender 守卫和清理不一致。验证：现有 `window.test.ts` 之外，加一个助手单测（假 context + 假 window）。
2. **第二步**：给 `shared/eventa` 引入契约注册表 + Valibot schema + 应用级握手。先只对新增契约强制，存量契约逐个补 schema。
3. **第三步（咽喉）**：preload façade + `useElectronEventaInvoke` 内部改指 `window.airi`。这是唯一需要动 renderer 的步骤，但因为 composable 签名不变，实际 diff 集中在 `packages/electron-vueuse`。先在一个窗口（如 about 或 desktop-overlay）做垂直切片验证 sandbox:true。
4. **第四步**：统一错误信封，按契约逐个把 `{ok:false}`/`{isError}` 收敛到共享结果联合，先收敛 MCP/godot/plugin 这些"renderer 需要分支处理"的契约。
5. **第五步（目标，勿阻塞）**：eventa 窗口命名空间就绪后，删掉 `setMaxListeners` 与助手里的 sender 分支。

**回滚**：每步独立可回退；preload façade 未完成前保留旧 `window.electron` 暴露路径即可，两路径并存不冲突。

**验证清单**：
- `pnpm type-check` + 定向 vitest。
- **契约注册表测试**：遍历 shared/eventa 模块，断言每个契约有 schema+版本、名字唯一、符合命名约定。
- **in-memory 端到端测试**：`createContext()` 上注册真实服务 → 真实 `defineInvoke` → 断言结果 + 错误信封，全程无 Electron。
- **握手测试**：版本不匹配 → 可观测降级态（不是静默 rejection）。
- **边界守卫**：用 ESLint `no-restricted-imports` 禁止 renderer 直接 import eventa 的 electron/renderer adapter（只有 preload 能 import），把"preload 是唯一咽喉"变成机器可查的不变量。
- 上线前手测：多窗口同时开时不再出现 `MaxListenersExceededWarning`；关窗重建后 handler 不重复注册、不泄漏。

## 8. 待定决策（答案会改变建议）

1. **eventa 上游窗口命名空间是否已存在/是否愿意做**？决定助手是"永久方案"还是"过渡方案"。
2. **eventa 跨进程错误类型保真度**（`ResErr` 泛型是否可靠）？决定错误层用"类型化 throw"还是"显式结果联合"为主。最快验证方式：装依赖后对 electron adapter 写一个最小往返测试。
3. **`sandbox: true` 是否是可接受的产品变更**？它需要 preload façade 完全就位且所有 `window.electron` 直连点被收口。若团队决定暂不动 sandbox，preload 咽喉仍是纯契约/版本收益，但优先级可降。
4. **外部化契约（plugin SDK、server channel、MCP）是否要和桌面壳 IPC 用同一套版本策略**？目前它们是独立的 `channels/` + `plugin-protocol` 表面，若外部化，契约级版本投入需要加大。

---

一句话总结：不要重写 IPC 框架，Eventa 的传输抽象是对的；把力气花在四个真实缺口上——preload 的类型化咽喉（顺带解锁 sandbox）、窗口路由的一处拥有（消灭 `sender.id` 复制）、契约的 schema+握手（版本只做检测不做兼容分支）、以及用 in-memory context 替换 mock 塔的测试缝（让 IPC 逻辑可无 Electron 验证）。

[EVAL:evolve-software-architecture-loaded]
