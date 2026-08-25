# MarkText 架构演进边界评估

## 1. 范围与置信度

本次评估聚焦四个演进边界：**多窗口协调**、**本地文件 IO**、**编辑器引擎**、**Electron shell（进程模型/IPC/预加载）**。结论基于对 `packages/desktop/src/{main,preload,renderer,shared}`、`packages/muya`、构建配置与测试布局的直接阅读，未修改任何文件。

仓库分类置信度高：这是一个 **Electron 桌面应用**（main/preload 编译为 CommonJS，renderer 为 ESM，`sandbox: true` + `contextIsolation: true`，见 `packages/desktop/src/main/config.ts:8-27`）。技能目录里唯一的桌面适配器是 Tauri 专用，因此这里只借用其"进程边界稳定性、生命周期正确性、原生适配器可替换、IPC 契约测试"这些跨桌面通用的关注点，Tauri 特定内容不适用。

核心判断：当前架构的**大方向已经走对了**——沙箱边界已收紧、IPC 契约已开始类型化、引擎已从 legacy `muyajs` 切到自包含的 `@muyajs/core`。剩下的问题不是"要不要重构架构"，而是**三处具体的接缝在放大变更成本**：多窗口状态的双重所有权、编码/换行策略的双实现、以及把 main↔main 内部总线混进 renderer↔main IPC 契约。

## 2. 观察事实

| 断言 | 证据 | 类型 | 置信度 | 对决策的影响 |
|---|---|---|---|---|
| renderer 是 tab 状态的唯一事实源（Pinia `tabs/currentFile`） | `src/renderer/src/store/editor.ts:150-155` | 事实 | 高 | 决定了多窗口状态应"由 main 派生"而非"双写" |
| main 侧 `EditorWindow` 又维护一份 `_openedFiles/_openedRootDirectory` 镜像 | `src/main/windows/editor.ts:57-58, 412-444` | 事实 | 高 | 双重所有权，需三条路径同步 |
| 镜像通过三条路径更新：main 直接 push、renderer→main 的 `mt::window-tab-closed`、main 内部 `ipcMain.emit('window-add-file-path'/'window-change-file-path')` | `windows/editor.ts:536-539`、`store/editor.ts:1046-1049`、`menu/actions/file.ts:209,374,385,508,555` | 事实 | 高 | 这是多窗口变更放大的根因 |
| 内部 bus 用 `ipcMain.emit/on` 实现，且**混入** renderer 面向的 `IpcSendChannels` 契约 | `utils/internalIpc.ts`、`shared/types/ipc.ts:188-202` | 事实 | 高 | 两种传输语义共用一张类型表，已产生错位 |
| 契约与 handler 存在两处不一致：`mt::window-add-file-path` 声明 `[windowId, filePath]` 但 handler 读 `(e, filePath)`；`window-change-file-path` 声明 `[windowId, oldPath, newPath]` 而实际 emit 是 `(win.id, newPath, oldPath)` | `ipc.ts:183,197` vs `windowManager.ts:369,447` vs `file.ts:385,508,555` | 事实 | 高 | 说明内部 channel 不该进 renderer 契约，typecheck 抓不到 `ipcMain.emit` 端 |
| `mt::window-add-file-path`（`mt::` 前缀版）无 renderer 发送方，疑似死 channel | 全 `src` grep 仅在 windowManager 有 handler | 推断 | 中高 | 删除它近乎零风险 |
| 保存路径：renderer 把全文 markdown 经 `mt::response-file-save` 发给 main，main 用 `write-file-atomic` 原子落盘 | `store/editor.ts:512-530`、`menu/actions/file.ts:157-225`、`filesystem/index.ts:25-49` | 事实 | 高 | renderer 拥有活文本、main 拥有磁盘，存在跨进程"读己之写"问题（见 `flushActiveEditor` #3803） |
| 编码/换行规范化在 main（`loadMarkdownFile`）与 renderer（`adjustTrailingNewlines`/`getOptionsFromState`）各有一份 | `filesystem/markdown.ts:90-159` vs `store/editor.ts:1802-1850` | 事实 | 高 | 新增编码/EOL 选项要改两边 |
| watcher 在外部变更时自己重读文件内容并重组编码选项 | `filesystem/watcher.ts:41-99, 132-153` | 事实 | 高 | 与 load 路径重复实现同一策略 |
| legacy `@marktext/muyajs`（`packages/muyajs`）在 desktop 源码中**零运行时 import**；只剩 alias、ambient 类型、workspace 依赖、注释与 CLAUDE.md 描述 | grep `@marktext/muyajs|muyajs|muya/lib` 全仓仅命中文档/工具链/注释 | 事实 | 高 | 引擎切换已完成，遗留的是死脚手架 |
| 活动引擎是 `@muyajs/core`（自包含 TS 包，自有 lint/madge/conformance），desktop 通过 `editor.vue` 约 1900 行适配它，且 `MuyaInstance = any`、事件 payload 手写 `MuyaChange` 再强转 | `components/editorWithTabs/editor.vue:82-140, 164-194, 1729-1793` | 事实 | 高 | 包边界干净，但包内边界是"运行时宽接口"，类型不设防 |
| desktop 为引擎维护 per-tab **synthetic history**，因为引擎 `getHistory()` 形状 ≠ 桌面 `tab.history` 形状 | `editor.vue:289-294`、`syntheticHistory.ts` | 事实 | 高 | 桌面与引擎在 history/save-dirty 上锁步演进 |
| 沙箱配置为 `sandbox:true, contextIsolation:true, nodeIntegration:false`，但 `webSecurity:false` | `config.ts:8-27` | 事实 | 高 | 安全边界已收紧，`webSecurity:false` 是遗留平台约束 |
| `Accessor` 是持有全部主进程单例的服务定位器，透传给每个窗口 | `app/accessor.ts` | 事实 | 高 | 是现状接缝，但替换为 DI 的杠杆低 |
| 文档漂移：`ARCHITECTURE.md`/CLAUDE.md 仍写 `contextIsolation:false + nodeIntegration:true`，与 `config.ts` 相反 | `docs/dev/ARCHITECTURE.md:20` vs `config.ts` | 事实 | 高 | 结构变更需同步修文档 |
| 单测几乎全在 renderer 纯逻辑与少量 main 纯函数；**无多窗口协调测试**、无 IPC 契约测试 | `test/unit/specs/*`（53 个），grep 无 windowManager/多窗口用例 | 事实 | 高 | 验证缺口集中在进程边界与生命周期，恰是风险所在 |

## 3. 当前摩擦

按四个领域，摩擦都表现为"**一处变更要向多处扩散**"：

- **多窗口**：打开文件状态被镜像在进程两侧，由三条 ad-hoc 路径同步，且 main 侧的路由启发式（`findBestWindowToOpenIn`/`getCandidateScores`，`windowManager.ts:256-305`、`editor.ts:449-469`）依赖这份镜像。任何新功能（固定标签、分屏、跨窗口拖拽标签、每窗口项目）都要同时改 renderer store、main 镜像、IPC 与 watcher。
- **文件 IO**：renderer 拥有活文本、main 拥有磁盘，保存把全文序列化过 IPC；编码/换行策略双实现；外部变更重载路径又重复一遍选项组装。跨进程"读己之写"已靠 `flushActiveEditor` 这类补丁兜底（`editor.ts:508-510`）。
- **引擎**：包级边界干净，但桌面适配层是宽的运行时接缝——类型 `any`、事件 payload 手写后强转、synthetic history 平移引擎内部形状。引擎升版时破坏面集中在 `editor.vue`，且 legacy shim 的"正在退休"状态与实测（零 import）不符，持续误导。
- **Shell**：IPC 契约把 main↔main 内部 bus 与 renderer↔main 混在一张表里，已产生两处 channel 形状错位；`Accessor` 耦合所有单例；`webSecurity:false` 是平台遗留；文档与实现漂移。

## 4. 质量属性优先级

按本决策实际支配力排序：

1. **进程边界稳定性**（IPC 契约、事件顺序、失败映射、序列化）——决定性，因为现有 bug 几乎都长在跨进程同步上（上文两处 channel 错位、save 竞态）。
2. **可测试性 / 局部性**——验证缺口集中在边界与生命周期；任何结构调整若不能让"候选窗口评分、快照 diff、文档端口、契约"可单测，就不值得做。
3. **平台安全**——沙箱已到位，`webSecurity:false` 是须遵守的现状约束，不应在本次动它。
4. **性能**——次要。全文读写对 markdown 编辑器足够（`markdown.ts:97` 已留 TODO 提到流式，但那是优化不是边界）。

可维护性不是独立维度，而是上面几项在四个领域上的合效果。

## 5. 方案对比

每个领域给出"维持现状"与"结构调整"两条可行路径，并按用户要求对照**代价 / 风险 / 验证方式**。

### 5.1 多窗口

| 维度 | A. 维持现状 | B. 单一事实源 + 快照 channel |
|---|---|---|
| 边界 | renderer 事实源 + main `_openedFiles` 镜像，三条同步路径 | renderer 上报唯一快照，main 派生 watcher 订阅与路由 |
| 代价 | 零迁移；新功能持续三处扩散 | 中等：窗口状态同步从 ~6 个 channel 收为 1 个快照 + 一次 diff，一次小重构 |
| 风险 | 同步逻辑分散、已有 channel 形状错位苗头、无测试兜底，随功能增长漂移 | 中等，但可分步迁移、每步可回滚；风险主要是一次性动多路径 |
| 验证 | 靠手工 e2e 回归（现无多窗口用例） | 候选评分/快照 diff 可提为纯函数单测；补一个多窗口 e2e |

### 5.2 本地文件 IO

| 维度 | A. 维持现状 | B. 文档端口收口编码/EOL |
|---|---|---|
| 边界 | main `filesystem/markdown.ts` 端口 + renderer 重复推导 | main 端口独有编码/换行规范化，返回 doc + 写回配方，renderer 不再推导 |
| 代价 | 低；新增编码/EOL 选项要改两边 | 小：端口已存在，只收紧边界，不重写读写 |
| 风险 | 双实现漂移、watcher 重载路径重复组装选项 | 低，保存/重载行为可通过 e2e 锁定 |
| 验证 | 已有 encoding/write-file-atomic 单测，缺跨进程 save/load 契约测试 | 加端口级单测 + 一轮保存/重载 e2e |

### 5.3 编辑器引擎

| 维度 | A. 维持现状 | B. 清 shim + 薄适配层 |
|---|---|---|
| 边界 | `@muyajs/core` + 宽运行时适配 + legacy shim | `@muyajs/core` + 唯一适配模块 + 无 shim |
| 代价 | 极低；但死代码持续误导 | 小到中：删 shim（机械），再引入 `renderer/src/engine/` 薄适配收口命令式表面 |
| 风险 | 引擎类型不设防，桌面直触引擎内部（synthetic history），升版破坏面大 | 低：适配层只做"暴露少数操作"，不建通用抽象 |
| 验证 | 引擎自有 conformance + e2e 回归 | typecheck + build + grep 无残留 + 现有 e2e 全绿 |

### 5.4 Electron shell

| 维度 | A. 维持现状 | B. 拆 transport + 删死 channel + 逐步收紧 |
|---|---|---|
| 边界 | 单张 IPC 契约混两类语义，`Accessor` 服务定位器 | 内部 bus 用独立 TypedEmitter，renderer 契约只含真实跨进程 channel；`Accessor` 暂留但按需传窄接口 |
| 代价 | 低 | 小到中：契约拆分是机械改动，删死 channel 近乎零风险 |
| 风险 | 已出现 arity/参数序错位；typecheck 抓不到 `ipcMain.emit` 端 | 低；`Accessor` 不替换（换 DI 是高成本低杠杆） |
| 验证 | 目前仅 typecheck 覆盖调用端，handler 注册不受约束 | 引入契约测试：对每个 invoke/send 断言 handler 签名与 payload 形状 |

## 6. 建议

**选定方向：定向收缝（B 组合），保持三进程 Electron 模型与 `@muyajs/core` 包边界不动。** 这两项刚付过成本、方向正确，不重平台、不建大抽象。真正值得改的是三处接缝，按杠杆从高到低、且每一步可独立回滚：

1. **退役 legacy `muyajs` shim**（对应 5.3B 前半）——删 `muya` alias（`electron.vite.config.ts:38`）、`src/types/muya.d.ts`、`@marktext/muyajs` workspace 依赖，并同步清理 `eslint.config.js`、`.prettierignore`、`scripts/thirdPartyChecker.ts`、CI 工作流与 CLAUDE.md 中的相关条目。这是全仓最便宜的清晰度收益。
2. **拆分内部 bus 与 renderer IPC**（对应 5.4B）——把 `ipc.ts` 里的 `watcher-*`、`window-*`、`screen-capture`、`broadcast-*` 等内部 channel 移出 `IpcSendChannels`，改用 main 内一个带类型的 `TypedEmitter`；顺手删除死 channel `mt::window-add-file-path`，修正 `window-change-file-path` 的参数序。这一步同时消除两处已观察到的契约错位。
3. **窗口状态单一事实源**（对应 5.1B）——引入 renderer→main 的窗口状态快照（已打开文件 + 根目录），tab 开/关/改名统一经它上报；main 的 `EditorWindow` 只保留一份派生缓存，watcher 订阅与候选窗口评分都从快照 diff 算出。把 `getCandidateScores` 改成纯函数输入快照，补单测与一个多窗口 e2e。
4. **引擎薄适配层**（对应 5.3B 后半）——新建 `renderer/src/engine/` 作为唯一允许 import `@muyajs/core` 命令式表面的模块，把 `editor.vue` 里 `any` 化的 `MuyaInstance`、手写 `MuyaChange` payload 收口到一处；`editor.vue` 与 store 只面向适配层。
5. **文档端口收口编码/EOL**（对应 5.2B）——让 main 的 `filesystem/markdown.ts` 独占编码/换行规范化并返回写回配方，renderer 停止推导 `adjustLineEndingOnSave`/`trimTrailingNewline`，watcher 重载复用同一端口。

**明确不做的：**
- **不迁移 Tauri / 非 Electron 壳**——那是重平台不是结构调整；沙箱 + 类型化 IPC 已经把重活干了，且没有第二个宿主的需求信号，属投机。
- **不替换 `Accessor` 为 DI 框架**——服务定位器是已知的、受控的现状接缝，全量替换成本高、杠杆低；只沿已有 `AppMenuLike`/`EditorBufferStoreLike` 的窄接口传参方式继续收窄即可。
- **不给引擎做跨 shell 抽象、不做流式/增量 IO、不做通用虚拟文件系统**——当前无第二消费者，全文读写对 markdown 编辑器足够，这些是过度设计。

## 7. 迁移与验证

- **迁移**：每步独立提交、独立可回滚。第 1、2 步是纯机械清理，先做以建立"零残留"基线；第 3 步是唯一中等规模改动，用快照 diff 的分支策略（旧 channel 与新快照并行、`feature` 开关或直接一次性替换 + e2e 锁定）降低风险；第 4、5 步是边界收口，不改运行时行为。
- **验证**（对应每步）：
  - 第 1 步：`pnpm -C packages/desktop run typecheck` + `build:unpack` + 全仓 grep `muyajs|muya/lib` 无 runtime 命中。
  - 第 2 步：新增契约测试——对每个 invoke/send channel 断言 handler 签名与 payload 形状（现在 typecheck 只覆盖调用端，抓不到 `ipcMain.emit` 端）；跑 `typecheck`。
  - 第 3 步：候选窗口评分/快照 diff 的纯函数单测 + 一个多窗口 e2e（开两窗、拖文件、关窗清理 watcher、重启恢复各窗）。
  - 第 4 步：现有 60+ e2e 全绿（它们已覆盖引擎交互），`editor.vue` 对 `@muyajs/core` 的 import 收敛到适配层。
  - 第 5 步：保存/重载/外部变更的 e2e 锁定行为，编码相关单测保留。
- **完成判据**：grep 证明 legacy 零残留；`IpcSendChannels` 只含真实跨进程 channel 且无形状错位；窗口打开文件状态只有一处事实源；`editor.vue` 不再直接 `any` 化触达引擎内部；编码/EOL 策略只有 main 一处实现。
- **回滚**：每步都是局部改动，git 回退即可恢复行为；第 3 步若发现多窗口边界比预期更纠缠，可退回"镜像 + 三路径"，不损失已完成的 1、2 步。

## 8. 待决问题

以下问题若答案不同，会改变建议：

1. **引擎是否会有第二宿主**（web 版、其他壳）？若短期内确定有，第 4 步的薄适配层应升级为真正的宿主接口；若只是"可能"，维持薄适配、不提前抽象。
2. **`packages/muyajs` 是否被网站或外部脚本以未 grep 到的方式引用**？第 1 步删除前需以一次 `rg` 全仓 + CI 绿做最终确认（本轮只覆盖了 desktop/src 与全仓关键词，未逐文件审计 scripts/website）。
3. **是否有超大文件/协作编辑的真实需求**？若协作编辑排上日程，引擎的 OT 状态（`packages/muya/CLAUDE.md:57`）会改变文件 IO 与窗口状态的边界；若无，维持全文读写。
4. **`webSecurity:false` 的移除时机**由谁拍板？它是平台安全约束，本次不动，但任何 shell 结构调整都应把它列为单独的安全任务。

[EVAL:evolve-software-architecture-loaded]
