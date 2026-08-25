已完成对 `packages/desktop` 四个边界（main / preload / renderer / shared）的实证评估。以下是结论与建议（只评估，未改任何代码）。

## 1. 范围与置信度

- **评估对象**：Electron 桌面应用 `packages/desktop` 的进程边界、IPC 契约、共享代码模块及其可扩展性。
- **分类置信度：高**。多信号一致（Electron 42 + electron-vite + `src/main`/`src/preload`/`src/renderer` 三进程结构、`contextBridge`、`ipcMain`、electron-builder 打包）。
- **方法说明**：本仓库附带的是 Desktop/Tauri 适配器（技能里唯一桌面适配器），Electron 与 Tauri 在「进程边界稳定性 / 生命周期 / 平台安全 / 可测试性」上高度重叠，因此采用核心流程 + 桌面通用关注点；Tauri 特有的 capabilities/permissions、Rust 进程部分不适用。本次未运行 `git log`（会话禁用 Bash/Git），历史热点依赖代码内迁移注释与文件规模推断，已标注。

## 2. 观察到的现状

| 结论 | 证据 | 性质 | 影响 |
| --- | --- | --- | --- |
| IPC 有单一类型契约 | `src/shared/types/ipc.ts` 定义四类通道（invoke/send/sync/main-event），preload 用泛型包装 | 事实 | 正向：渠道名/参数/返回可被 typecheck 校验 |
| main 侧处理器注册是**两套并存** | 新处理器在 `src/main/ipc/*`（`registerSandboxIpcHandlers`）；旧处理器在 `src/main/app/index.ts` 的 `_listenForIpcMain()` | 事实 | 加通道时要选注册位置，契约里查不到处理器在哪 |
| 内部事件复用渲染器 IPC 通道 | `src/main/windows/editor.ts` 用 `ipcMain.emit('watcher-watch-file'…)`；`src/main/utils/internalIpc.ts` 用 `ipcMain.on` 双向复用 | 事实 | 把「renderer→main」消息面与「main→main」控制流耦合在一起 |
| `common/` 并非渲染器安全 | `common/filesystem/index.ts` 引 `fs`、`fs-extra`；`paths.ts` 用 `fs.statSync`、`process.platform`；renderer 只对 `path`→`pathe` 做了别名 | 事实 | 「common 可在所有进程使用」的不变量是假的，靠自觉维持 |
| 路径谓词在 preload 与 common 重复 | `MARKDOWN_EXTENSIONS`/`hasMarkdownExtension`/`isChildOfDirectory`/`isSamePathSync` 两边各一份，语义还不一致（common 用 inode，preload 用字符串比较 + 同步 IPC 兜底） | 事实 | 改一个扩展名要改多处 |
| 类型化 IPC 迁移进行中 | `ipc.ts` 头注释「commits 5–8 逐步收紧」；`bus.ts` 提「Stage 3/4/5」；`typedEmitter.ts` 提「Commit 5d」；大量 `unknown` 载荷（uploader、ripgrep、load-state 等） | 事实 | 类型安全是部分的，尚未端到端强制 |
| renderer 大量绕过 facade 直接打裸通道 | 136 处 `window.electron.ipcRenderer`，25 个文件，`store/editor.ts` 独占 56 处 | 事实 | 通道名字符串仍散布在 store/组件里，抽象层很薄 |
| `webSecurity: false` | `src/main/config.ts` 两个窗口都关掉了 Chromium web 安全（虽有 contextIsolation/sandbox/nodeIntegration:false） | 事实 | 安全边界与 CLAUDE.md「完全沙箱」叙事不符，存在 XSS 邻近风险 |
| 遗留全局面仍存在 | `window.marktext` / `window.DIRNAME`，31 处、14 个文件（`editor.ts` 11 处） | 事实 | 与类型化 preload 桥平行的第二套启动面 |
| 单元测试可测 main 进程模块 | `main_renderer` 别名（`tsconfig.base.json`、`vitest.config.ts`）让 Vitest 在 jsdom 下 `vi.mock` electron 后测 main 模块 | 事实 | 正向：是真正的测试接缝 |
| 大文件集中 | `renderer/src/store/editor.ts` ≈2102 行、`commands/index.ts` ≈756 行、`main/app/index.ts` ≈850 行 | 事实（近似） | 变更放大集中在这几个「上帝文件」 |
| 无 ADR | 仓库内未发现 ADR/决策记录 | 事实 | 关键边界决策（沙箱、IPC 迁移）没有可追溯记录 |

关键文件：`src/shared/types/ipc.ts`、`src/preload/index.ts`、`src/types/global.d.ts`、`src/main/ipc/fs.ts`、`src/main/app/index.ts`、`src/main/utils/internalIpc.ts`、`src/common/filesystem/paths.ts`、`electron.vite.config.ts`。

## 3. 当前摩擦（按重要性）

1. **IPC 契约的 main 侧不对称**。preload 侧有统一泛型包装，main 侧却是「新 `main/ipc/*` + 旧 `App._listenForIpcMain`」两套注册，且 `unknown` 载荷仍多。契约文件是唯一真源，但**它没有告诉你处理器住在哪、是否真的注册了**——这是最影响可扩展性的一点。
2. **`ipcMain.emit` 把进程边界当进程内事件总线**。watcher / screenshot 等通道既被 renderer `send`，又被 main 内部 `emit`。`IpcSendChannels` 类型因此混进了「main→main」语义。任何一侧改法，另一侧都要知道。项目里其实已经有 `shared/types/typedEmitter.ts`（TypedEmitter），只是没用在这些内部控制流上。
3. **`common/` 的不变量不成立且无强制**。TypeScript 的 `paths` 别名不构成边界；今天 renderer 没 import `common/filesystem` 只是运气/自觉，一个未来的 import 就会把 `fs` 拉进沙箱 bundle。
4. **预加载重复实现纯谓词**，是迁移期间「复制一份能跑」的典型事故复杂度，正在悄悄固化三份同义实现。
5. **`webSecurity: false` 是安全质量属性的真实回退**，且与「沙箱已完成」的对外表述冲突。

## 4. 质量属性优先级

对「未来可扩展性」这个决策，排序如下（并明确权衡）：

1. **可维护性 / 变更局部性** —— 当前最大痛点（上帝文件 + 两套注册 + 重复实现）。目标：改一个通道/扩展名只动一处。代价：可能需要一次小重构。
2. **进程边界稳定性** —— IPC 契约要能被机械校验（不只是人肉 typecheck）。目标：渠道名在代码里只出现于契约与一处注册表。
3. **安全性** —— 沙箱是既定方向，`webSecurity: false` 与 `common` 的 fs 泄漏都削弱它。目标：守住 `contextIsolation/sandbox/nodeIntegration` 已拿到的成果，不回退。
4. **可测试性** —— `main_renderer` 接缝是强项；缺的是「契约 vs 实际注册」的契约测试。
5. **可扩展性** —— 以上四项做好后自动获得；不单独为它建抽象。

**权衡**：优先用 CI 已有的 `pnpm typecheck`/`lint` 作为强制机制（便宜、已就位），暂不引入运行时 schema 校验层；`webSecurity: false` 的翻转作为独立加固步骤，不与 IPC 收敛混在一起做。

## 5. 可选方案

**方案 A — 维持现状，继续逐通道迁移**。可辩护：类型契约 + 沙箱已是最大收益，剩下的多是「把迁移做完」。风险：两套注册、`common` 不安全、preload/common 重复会随每次改动继续放大，技术债线性累积。

**方案 B — 收敛 IPC 边界（推荐）**。目标：
- main 侧单一处理器注册表，以契约为唯一渠道名来源（一处注册，双向可查）。
- 拆分 `common` 为「纯函数（渲染器安全）」与「main-only（含 fs/process）」，用 import 限制（ESLint `no-restricted-imports`）或物理目录强制。
- 用已有的 `TypedEmitter` 取代 `ipcMain.emit` 内部总线，watcher/screenshot 内部派发不再走渲染器通道。
- renderer 一律走 preload 命名 facade，渠道字符串逐步退出 store/组件。
- 逐通道收紧剩余 `unknown` 载荷。

**方案 C — 引入完整进程通信层（自动生成 IPC / 运行时 schema 校验）**。当前**否决**：单应用、迁移中途、团队规模小，成本与间接层远超收益；现有泛型包装已拿到约八成好处。

## 6. 建议

选 **方案 B**，按可逆步骤切分，第一个纵向切片建议是**契约测试**而不是动业务代码：

1. **契约测试**：枚举 `ipcMain` 上实际注册的 handle/on 渠道，断言全部落在 `IpcInvokeChannels` / `IpcSendChannels` / `IpcSyncChannels` 中（沙箱集合再做双向校验）。零行为改动，立刻抓住「契约里有、处理器没有」或反向的漂移。
2. **让 `common` 纯度可强制**：把含 `fs`/`process` 的文件标记为 main-only（物理拆目录或 ESLint import 限制），renderer 只许引纯子集。
3. **内部总线去 IPC 化**：watcher/screenshot 用 `TypedEmitter` 派发，`onInternalChannel`/`ipcMain.emit` 逐步退役。
4. **继续逐通道收紧 `unknown`**，并把 renderer 调用收进 preload facade。
5. **单独评估 `webSecurity: false`**（见待决问题），作为独立硬化步骤。

**被否决的替代**：方案 A（债务继续累积）、方案 C（过早抽象）。

## 7. 迁移与验证

- **每一步都保持行为不变、可独立回滚**：契约测试、import 限制、TypedEmitter 替换都不改变运行时语义。
- **验证**：`pnpm typecheck`、`pnpm lint`、`pnpm test:unit`（重点看 `main_renderer` 相关 spec）、`pnpm test:e2e`（重点 `test/e2e/context-isolation.spec.ts` 与 `launch.spec.ts`）。
- **完成标准**：契约测试在 CI 绿；`grep ipcMain.emit` 在 main 业务代码中为零（watcher/screenshot 内部派发走 TypedEmitter）；`grep "from 'common/filesystem'" src/renderer` 为零；renderer 中 `window.electron.ipcRenderer` 直用降至可控（仅 preload 内或极小桥接点）。
- **观察点**：若契约测试暴露大量未登记渠道，说明「两套注册」比估计更严重，可据此调整优先级。

## 8. 待决问题（答案会改变建议）

1. **`webSecurity: false` 是否 load-bearing？**（未知）它可能为本地文件渲染/iframe 而保留。若翻成 `true` 不破坏本地内容，应作为独立加固项；需要一次 spike 验证。
2. **分阶段 TS 迁移（注释里的 commits 5–8 / Stage 3/4/5）是否仍在进行、有无 owner 与终点？**（未知）仓库内无 ADR，我看不到对应计划；若已搁置，应先固化「当前状态即基线」，避免注释承诺与现状持续脱节。
3. **renderer 是否还要兼容旧 `muyajs` 引擎？**（未知）CLAUDE.md 说「being retired」，renderer 里已无 `muya/` 旧别名 import，但 `packages/desktop/package.json` 仍声明 `@marktext/muyajs` 依赖与 `muya` 别名；这决定 `common`/preload 里路径谓词到底该以哪份为准。

一句话总结：**类型化 IPC 契约 + 沙箱 preload 是这轮迁移真正有价值的地基，但目前只做了一半——main 侧双注册、`ipcMain.emit` 复用、`common` 伪共享、preload 重复实现，正是接下来「改一处要动多处」的主要来源。** 建议先上一道契约测试把边界锁死，再逐项收敛，而不是再建新的抽象层。

[EVAL:evolve-software-architecture-loaded]
