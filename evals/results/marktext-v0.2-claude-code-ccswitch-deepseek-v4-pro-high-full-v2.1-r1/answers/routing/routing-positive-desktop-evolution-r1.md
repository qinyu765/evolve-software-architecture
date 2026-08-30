我已完成对仓库的证据检查（只读）。下面是评估结论。

---

# MarkText 长期演进边界评估

## 1. 范围与置信度

**待决策问题**：多窗口管理、本地文件 IO、编辑器引擎、Electron shell 这四条边界，应当"维持现状增量修补"还是"做有针对性的结构调整"。

**仓库分类**：Electron 桌面应用（monorepo，`packages/desktop` 为应用，`packages/muya` 为新编辑器引擎，`packages/muyajs` 为遗留引擎）。置信度**高**——入口、进程模型、打包、IPC 契约、原生对话框/文件系统访问全部指向这一类型。

本评估基于对 `src/main`、`src/preload`、`src/shared/types/ipc.ts`、`electron.vite.config.ts`、两个引擎包及测试目录的直接阅读。**未修改任何文件。**

---

## 2. 观察事实（证据表）

| 主张 | 证据 | 类型/置信度 | 对决策的影响 |
|---|---|---|---|
| 窗口生命周期由 `WindowManager` 单例集中管理（`Map<number, BaseWindow>`、活动窗口 id、活动序列表、watcher 生命周期） | `src/main/app/windowManager.ts:85-115` | 事实 / 高 | 多窗口的"所有"落点已清晰，不需要重写 |
| 窗口**创建**和"文件/目录路由到哪个窗口"的编排在 `App`，而评分算法在 `WindowManager.findBestWindowToOpenIn` | `src/main/app/index.ts:386-640` 与 `windowManager.ts:256-305` | 事实 / 高 | 所有权分裂在 App 与 WindowManager 两处 |
| 关闭流程走主↔渲染往返：`close` → `preventDefault` → `mt::ask-for-close` → 渲染进程回 `mt::close-window-confirm` | `windows/editor.ts:256-272`、`menu/actions/file.ts:407-456` | 事实 / 高 | 关闭正确性依赖两条 IPC 链路，是高风险面 |
| `ipcMain` 被当作**进程内事件总线**使用：`ipcMain.emit()` 共 42 处、13 个文件，`onInternalChannel` 做签名适配 | `src/main/utils/internalIpc.ts`、全局计数 | 事实 / 高 | 跨模块调用退化为字符串通道，无编译期检查（推断） |
| 文档保存/另存/重命名/移动编排在**全局菜单动作模块** `menu/actions/file.ts`，且代码内 TODO 自认应移到 editor window | `menu/actions/file.ts:36-38`、`157-224`、`285-464` | 事实 / 高 | 保存语义与"打开窗口"、"导出/打印"耦合在同一模块，改动放大（推断） |
| **两条写路径持久性不同**：文档保存走 `write-file-atomic`（fsync+rename），而渲染进程通用 `mt::fs::write-file` 走 `fs-extra` 直写 | `main/filesystem/index.ts:25-49` vs `main/ipc/fs.ts:55-57` | 事实 / 高 | 崩溃持久性保证不一致，是潜在数据面隐患 |
| 编辑器已迁移到 `@muyajs/core`，但遗留 `muyajs` 包、`muya` 别名、约 25 个 `muya/lib/*` ambient 声明仍在 | `editor.vue:82-113`、`electron.vite.config.ts:38/58/84`、`src/types/muya.d.ts` | 事实 / 高 | 引擎边界处于"迁移收尾"阶段，双引擎并存 |
| 引擎迁移有成熟的对等测试计分板：15 个差距中 14 个已修复，PG14（源码模式切回的 undo 粒度）显式延期 | `test/PARITY_SCOREBOARD.md`、`PARITY_QA.md` | 事实 / 高 | 引擎侧已有可复用的迁移验证机制 |
| 沙箱配置与文档**矛盾**：`config.ts` 为 `sandbox:true / contextIsolation:true / nodeIntegration:false`，而 CLAUDE.md 架构节仍写 `contextIsolation:false + nodeIntegration:true`（且引用不存在的 `config.js`） | `main/config.ts:12-21`、CLAUDE.md | 事实 / 高 | 文档漂移会持续误导新贡献者 |
| 两个窗口都设 `webSecurity: false`；主进程用 `will-navigate`/`setWindowOpenHandler`/`will-attach-webview` 兜底 | `config.ts:19/40`、`app/index.ts:133-143` | 事实 / 高 | 长期安全边界，需评估能否收紧 |
| 渲染进程持有宽泛的通用 fs 面（`fileUtils` 31 处/10 文件）和 129 处 IPC 调用（25 文件），IPC 契约载荷仍多为 `unknown` | `preload/index.ts:158-180`、`shared/types/ipc.ts:10-13` | 事实 / 高 | shell 面比实际需求宽，契约迁移未完成 |
| 文件 IO 层已有高质量单测（原子写、buffer store 持久性、watcher、编码、危险可执行文件） | `test/unit/specs/write-file-atomic.spec.ts`、`buffer-store-durable.spec.ts`、`watcher-await-write-finish.spec.ts`、`encoding.spec.ts`、`dangerous-executable-file.spec.ts` | 事实 / 高 | 结构调整有现成护栏 |
| 引擎是 DOM 化、自带 CommonMark/GFM 一致性与大量 vitest 规格的自包含包 | `packages/muya/src/**`、`test/spec/` | 事实 / 高 | 引擎已是可移植核心，是"shell 边界"的正面资产 |
| 仓库无 ADR 目录 | 目录搜索无结果 | 事实 / 高 | 关键架构决策缺乏留痕 |

---

## 3. 当前摩擦（change amplification）

四条边界各自的摩擦不同，但有一个共同根因：**主进程内的模块协作依赖字符串通道（`ipcMain.emit` + `BrowserWindow.fromWebContents`），而不是直接方法调用**。

1. **多窗口**：窗口创建在 `App`，评分与活动窗口追踪在 `WindowManager`，而"关闭/保存时按窗口收尾"又在 `menu/actions/file.ts` 的全局 handler 里。一次涉及窗口的改动要横跨 3 个模块，且 `restoreBufferId` 是通过 `(win as unknown as { restoreBufferId: string })` 挂在窗口上的无类型属性（`editor.ts:145`）。

2. **本地文件 IO**：文档级 IO（`main/filesystem/markdown.ts`）与文件操作编排（`menu/actions/file.ts`）分裂，且存在两条持久性不同的写路径。这是唯一一处代码里**自己承认**该重构的地方（`file.ts:36-38`）。

3. **编辑器引擎**：这是最健康的边界——新引擎 `@muyajs/core` 自包含、有测试、有迁移计分板。摩擦在于**收尾不彻底**：遗留包、别名、ambient 声明、`ag-*` 主题 DOM 都还在，形成"双引擎"认知负担。

4. **Electron shell**：沙箱化本身是近期的正确方向（`#4244`），但 `webSecurity:false`、宽泛的通用 fs 面、未收紧的 `unknown` 载荷、以及**过时的架构文档**，使"实际边界"和"文档描述的边界"分叉。

---

## 4. 质量属性优先级（明确取舍）

| 排名 | 属性 | 目标/预算 | 当前证据 | 说明 |
|---|---|---|---|---|
| 1 | 可维护性 / 局部性 | 单次改动停留在一个模块 | 字符串总线 42 处、保存编排在全局菜单模块 | 决策主驱动；其余属性服务于它 |
| 2 | 进程边界稳定性（IPC 契约正确性） | 通道改名/签名变化在编译期暴露 | 契约已类型化但载荷为 `unknown`，进程内总线完全无类型 | 边界破了就是数据丢失或功能失效 |
| 3 | 可测试性 | 通过预期接口验证 | 文件 IO 单测齐全；总线路径无法单测 | 结构调整依赖既有护栏 |
| 4 | 安全性 | 收紧 `webSecurity:false` 与通用 fs 面 | 两个窗口均关、fs 面宽 | 长期关切，非本次直接驱动 |
| 5 | 可移植性 | 引擎可移植、shell 薄适配 | 引擎 DOM 化自包含；main/preload 深度 Electron/Node 绑定 | **不做** shell 抽象，见第 6 节 |

明确不追求的性能、可操作性等，不纳入本次决策。

---

## 5. 选项对比

### 选项 A —— 维持现状（继续增量修补）

- **边界与所有权**：保持 `WindowManager`+`App` 双所有权、`menu/actions/file.ts` 全局 save 编排、`ipcMain.emit` 总线、双引擎并存、通用 fs IPC 面。
- **代价**：短期最低——没有迁移风险，修复路径大家都熟悉。
- **风险**：即时风险低；**累积风险**是——字符串通道改名/删 handler 会**静默失效**（无编译错误）、双写路径持久性不一致是潜在数据隐患、双引擎与漂移文档持续抬高新贡献者的理解成本。
- **验证**：现有单测 + e2e 可兜住大部分回归；但总线和跨模块编排**没有编译期保障**，只能靠运行时观察或人工审查。
- **会被证伪的信号**：一旦出现"改保存语义 / 加一个文件操作 / 需要精确定位哪个窗口拥有某文件"这类需求，放大系数会明显上升。

### 选项 B —— 结构调整（加深少量 seam，而非重写）

四个可独立执行的 seam，对应四条边界：

1. **文件 IO 收敛**：把 save/save-as/rename/move 编排从 `menu/actions/file.ts` 移到由 `EditorWindow` 持有的文档文件服务；删掉中转的 `ipcMain.emit`；统一两条写路径为原子写；把 `mt::fs::*` 收敛为渲染进程真实需要的最小面。
2. **多窗口直调化**：把"路径路由/评分"从 `App` 下沉 `WindowManager`；用直接方法调用替换 `BrowserWindow.fromWebContents` + `ipcMain.emit`；给 `restoreBufferId` 一个类型化属性。
3. **引擎退役收尾**：主题从 `ag-*` 迁到 `mu-*` DOM 后，删除遗留 `muyajs` 包、`muya` 别名与 `muya.d.ts` ambient 声明；PG14 维持延期。
4. **shell 边界加固**：收紧 IPC 契约的 `unknown` 载荷；评估 `webSecurity:false` 可否收敛；修正 CLAUDE.md 架构节。

- **代价**：中等，但每个 seam 独立、可小步迁移、可回滚（见第 7 节）。
- **风险**：保存/关闭路径的回归是数据面风险，必须靠既有 `write-file-atomic`/`buffer-store-durable` 单测和 e2e 护栏；引擎删包必须先过主题迁移。
- **验证**：直接方法调用 + 收紧类型后，改名会在编译期失败，这是现状不具备的保障。

---

## 6. 建议

**推荐选项 B，但按"风险从低到高、可逆优先"的顺序推进，而不是一次性重构。**

具体排序：

1. **先做零行为变化的机械收尾（最可逆）**：修正 CLAUDE.md 架构节；收紧 IPC `unknown` 载荷；若确认无运行时引用，移除死别名/ambient 声明。这些有编译期验证，风险趋近于零。
2. **统一文件写路径**：先让 `mt::fs::write-file` 与文档保存共享同一原子写语义（或明确标注它不用于文档持久化），再迁移保存编排到 `EditorWindow`/专用服务。
3. **多窗口直调化**：路由下沉 `WindowManager`，用直调替换总线。
4. **最后退役遗留引擎**：主题迁移完成后再删包。

**明确不要现在做的（避免过度抽象）**：
- 不要建 shell 抽象层（Tauri/web adapter）——仓库内没有任何第二个 shell 的证据，`YAGNI`。
- 不要为 PG14 硬上"整文档 ot-json1 diff 作为单个 undo op"——计分板已论证风险大于收益。
- 不要引入新的通用事件总线库来替代 `ipcMain.emit`——解药是**直接方法调用**，而不是更花哨的总线。
- 不要为渲染进程建通用 fs 权限框架——本地单用户、沙箱化渲染进程是受信方，缺的是"收窄"而非"加层"。

**被否掉的替代方案**：一次性全量重写 main 进程为"分层服务架构"——代价高、与收益不成比例，且现有 `WindowManager`/`Accessor`/单测已经足够好，缺的是局部 seam 而非整体换型。

**值得写 ADR 的决策**（当前无 ADR 目录）：(1) 文档保存编排所有权从 `menu/actions` 移至 `EditorWindow`/文档服务；(2) 退役遗留 `muyajs` 并删除别名；(3) `webSecurity:false` 的处置结论；(4) `ipcMain.emit` 进程内总线的禁用规则。

---

## 7. 迁移与验证

**可逆步骤与护栏**：

- 每步以小提交落地，`git revert` 即回滚；引擎删包放最后，因为那一步可逆性最差。
- 迁移保存编排时，先保留旧 `ipcMain.emit` 通道与新直调并存（双写期），用现有单测观察行为等价，再删旧通道。

**验证方式**：

- **编译期**：`pnpm run typecheck`；收紧 IPC 类型后 `vue-tsc --noEmit` 会在通道改名/签名变化时直接报错——这是现状总线无法提供的。
- **契约/残留检查**：删除别名后 `pnpm run lint` + 全局 `grep -r "muya/lib"` 应无命中；`grep -r "ipcMain.emit"` 应仅剩明确允许的内部通道（或归零）。
- **行为护栏（重点在数据面）**：`test/unit/specs/write-file-atomic.spec.ts`、`buffer-store-durable.spec.ts`、`watcher-await-write-finish.spec.ts`、`encoding.spec.ts` 必须持续绿；`pnpm run test:e2e` 的 parity 规格覆盖引擎与关闭/保存链路。
- **失败模式检查**：保存中断电/崩溃（fsync 路径）、多窗口关闭时的 buffer 清理（`buffer-store-durable`）、编码/换行回归（`encoding`）、源/所见即所得模式切换（parity PG 系列）。
- **打包冒烟**：`pnpm run build:unpack` 后跑 Playwright `launch.spec.ts`，确认沙箱 preload 与打包后 `file://` 加载未退化。

**完成标准**：跨模块 `ipcMain.emit` 调用归零或仅剩显式内部通道；遗留 `muyajs` 从 workspace 移除且 CI 绿；文档与 `config.ts` 一致；`pnpm run lint && pnpm run typecheck` 通过。

---

## 8. 开放决策（答案会改变建议）

1. **shell 未来**：是否有换壳计划（Tauri/Web）？仓库内无证据（未知）。若无，维持 Electron 并让引擎保持可移植即可；若有，代价集中在 main+preload，需重排优先级。最便宜的求证方式：查 roadmap / issue。
2. **`webSecurity:false` 的必要性**：哪些功能依赖 file:// 同源（图片、导出 CSS）？能否收紧到 `true` 并对例外单独处理（未知）？最便宜的求证：局部改 `true` 跑 e2e，观察哪个功能失效。
3. **PG14 是否复活**：是否值得为"源码模式一次编辑=一个 undo 步"做一个引擎级"整文档状态替换为一个 op"的 API？当前结论是 defer，信号（大量用户反馈该边界）出现才重新评估。
4. **通用 fs 面的最小集合**：`mt::fs::*` 的 31 处调用里，哪些是文档持久化、哪些是配置/缓存/导出？需逐个归类后确定收敛目标。

---

[EVAL:evolve-software-architecture-loaded]
