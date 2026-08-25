我已完成对四个区域的证据核查（多窗口、本地文件 IO、编辑器引擎、Electron shell 边界）。下面是决策导向的评估——只读、不改代码。

---

# MarkText 长期演进边界评估

## 1. 范围与置信度

**决策问题**：在「多窗口管理、本地文件 IO、编辑器引擎、Electron shell」四个边界上，是维持现状，还是做结构性调整？分别的代价、风险与验证方式是什么？

**仓库分类**：Electron 桌面应用（三进程：main / sandboxed preload / renderer），Vue 3 + Pinia 渲染层，编辑器引擎为独立 workspace 包 `@muyajs/core`。skill 的 desktop 适配器虽以 Tauri 命名，但其「进程边界稳定性、平台安全、生命周期正确性、可测试性」四条核心关注点完全适用于 Electron——本评估采用该框架，但把 Tauri 特有的 capability/permission 语言替换为 Electron 的 sandbox/contextBridge/webPreferences。【事实 + 推断】

**置信度**：高。四个区域的关键文件都已直接读取；遗留引擎的「无运行时引用」结论经全包 grep 交叉验证。

## 2. 观察事实（证据表）

| 主张 | 证据 | 类型 | 置信度 |
|---|---|---|---|
| 窗口注册、活动窗口、跨窗口文件路由集中在 `WindowManager` | `main/app/windowManager.ts:88`（`Map<number, BaseWindow>`）、`:256-305`（`findBestWindowToOpenIn` 打分） | 事实 | 高 |
| main 侧为每个编辑窗口维护「已打开文件/根目录」镜像，用于路由打分 | `main/windows/editor.ts:52-59`（`_openedRootDirectory`/`_openedFiles`）、`:411-444`、`:449-469` | 事实 | 高 |
| 该镜像与 renderer 的 tab 列表是两份数据，靠多条 IPC 手动同步 | renderer `store/editor.ts:1046-1050`（`mt::window-tab-closed`）、`editor.ts:411-416`（`addToOpenedFiles`）、`menu/actions/file.ts:209/374/385/394` | 事实 | 高 |
| 已有自述 TODO：save/save-as 应移入 EditorWindow、renderer 只与窗口通信 | `main/menu/actions/file.ts:36-38` | 事实 | 高 |
| `ipcMain.emit(...)` 被当作 main 进程**内部**事件总线使用 | `windowManager.ts:369-474`、`file.ts:209/374/385/394/433/508/555`、`dataCenter/index.ts:107/117/136`、`editor.ts:396/402/415/430/443/475` | 事实 | 高 |
| 同名的 `watcher-*`/`window-*` 通道同时出现在 renderer→main 类型契约里，且签名不同（契约 `[windowId, path]` vs 内部 `(BrowserWindow, path)`） | `shared/types/ipc.ts:191-202` vs `windowManager.ts:424-435` | 事实 | 高 |
| 文档保存走 main 的原子写 + fsync | `main/filesystem/index.ts:25-49`（`write-file-atomic` 注释明确 fsync 语义） | 事实 | 高 |
| 读取是整文件 `readFile` + iconv 解码，注释自认「未用流、多次缓冲」 | `main/filesystem/markdown.ts:90-159`（`:97` TODO） | 事实 | 高 |
| 崩溃恢复 buffer 每窗口一个 JSON，用稳定 UUID、原子写、不驻内存 | `main/editorBufferStore/index.ts:91-124`、`:178-185`；`editor.ts:140-146`（`restoreBufferId` 挂在 BrowserWindow 的 side-channel 属性上） | 事实 | 高 |
| renderer 运行时已 100% 走 `@muyajs/core`（新 TS 引擎），无任何 `@marktext/muyajs`/`muya/lib` 运行时 import | `renderer/src/components/editorWithTabs/editor.vue:82-140`；grep 全 desktop 仅命中注释与 `.d.ts` | 事实 | 高 |
| 但遗留引擎的**边界清理未完成**：`muya` alias、workspace 依赖、`muya.d.ts` 仍在 | `electron.vite.config.ts:38/58/84`、`desktop/package.json:62`、`src/types/muya.d.ts` | 事实 | 高 |
| 渲染进程已完全沙箱化 | `main/config.ts:11-21`、`:34-42`（`contextIsolation:true, sandbox:true, nodeIntegration:false`）；`preload/index.ts:1-7` | 事实 | 高 |
| 两个窗口都设置了 `webSecurity: false` | `main/config.ts:19`、`:40` | 事实 | 高 |
| CLAUDE.md 架构一节写「editor/preferences 用 `contextIsolation:false + nodeIntegration:true`」，与 config.ts 和其余文档矛盾 | CLAUDE.md Architecture 段 vs `config.ts` | 事实（文档与代码冲突） | 高 |
| IPC 处理器注册分散在多处：`ipc/index.ts` 一次注册 + `menu/actions/*` + 各类的 `_listenForIpcMain()` | `ipc/index.ts:12-23`；`editorBufferStore/index.ts:214-218`；`dataCenter/index.ts:162-213`；`windowManager.ts:367-495` | 事实 | 高 |

## 3. 当前摩擦（按杠杆从高到低）

1. **`ipcMain` 双用途**：它既是 renderer→main 的传输，又被 `ipcMain.emit` 当成 main→main 的内部总线，且通道名与签名被两套语义复用。`onInternalChannel`（`utils/internalIpc.ts:8-13`）只能靠强制转型抹掉合成 `IpcMainEvent`。后果：从类型上无法回答「这个通道谁能发」——renderer 理论上可以按契约签名发送 `watcher-watch-file`，而 main 内部又用 `BrowserWindow` 作为首参 emit 同名通道。这是 shell 边界与多窗口路由共同的根因摩擦。

2. **打开文件集合的双份真相**：renderer 的 `tabs` 是权威，main 的 `_openedFiles/_openedRootDirectory` 是为 `findBestWindowToOpenIn` 打分维护的镜像，靠 `mt::window-tab-closed` / `window-add-file-path` / `window-change-file-path` 等手动同步。任何新增「影响 tab 的操作」都要求两端同时改，否则路由打分失准或 watcher 泄漏。【推断：这是未来多窗口功能变化的主要放大点】

3. **文件操作处理器是全局的、非窗口作用域**：`menu/actions/file.ts` 里的 save/rename/move 用 `BrowserWindow.fromWebContents(e.sender)` 反查窗口，再通过 `ipcMain.emit` 触达 `WindowManager`/`EditorWindow` 内部。文件本身已有 TODO 承认应改为窗口作用域通道（`mt::window-save-tabs$wid:<windowId>`）。

4. **引擎迁移「代码完成、边界未完成」**：`@marktext/muyajs` 已是死依赖，但 `muya` alias 仍指向 `../muyajs`。风险不是现在的 bug，而是**未来**一个不经意的 `import … from 'muya/lib/…'` 会静默编译进旧引擎，让一个 bundle 里出现两套编辑器。

5. **文档漂移**：CLAUDE.md 关于 sandbox 的描述与代码相反。它可能诱导下一个贡献者按旧文档重新打开 `nodeIntegration`。

6. **`webSecurity: false`** 是潜在安全边界，需要确认是否仍为加载本地图片/绝对路径所必需（见第 8 节待决问题）。

## 4. 质量属性优先级

对本次决策真正起支配作用的属性，按权重排序：

1. **进程边界稳定性（IPC 契约）**——四个区域全部跨越 renderer↔main 边界；未来任何改动的代价都由这条契约是否清晰决定。**权重最高。**
2. **局部性 / 变更成本**——上述摩擦的直接表现就是「改一处要同步多处」。
3. **数据持久正确性**——已是强项（原子写 + fsync + 每窗口 buffer），是**约束**而非驱动项，任何重构不得回退。
4. **安全性（sandbox 姿态）**——sandbox 已开启，边界良好；但 `webSecurity:false` 与文档漂移是待治理项。
5. **可测试性**——目前 main 逻辑与 `ipcMain`/`BrowserWindow` 深度纠缠，难以脱离 Electron 单测；这是验证杠杆而非目标本身。
6. **可移植性 / OS 差异**（watcher 轮询、行尾、编码）——多为真实领域复杂度，不是本决策要动的意外复杂度。

权衡说明：这里不能同时最大化所有属性。把「进程边界稳定性」放到第一位，意味着接受短期内不追求「通用 IPC 层」这类大抽象——真正的目标是让现有契约**可枚举、可校验、单义**，而不是增加抽象层数。

## 5. 方案比较

### 方案 A：维持现状

**边界与所有权**：维持 `WindowManager` 注册表 + main 侧文件镜像 + 分散的 IPC 处理器 + `ipcMain.emit` 内部总线 + 死遗留依赖。

- **代价**：现在几乎为零。
- **风险**：摩擦是复利式的——每加一个多窗口特性，镜像同步与通道语义歧义的维护成本递增；文档漂移可能诱导安全回退；死 alias 可能诱导双引擎。
- **验证**：现有 Vitest + Playwright e2e 已覆盖行为；但当前接缝无法脱离 Electron 单测，回归靠黑盒 e2e 兜底。
- **使 A 变错的信号**：出现第二个内部事件的真实消费者；新增「跨窗口拖 tab / 每窗口 workspace 恢复」类特性；有人踩中 `watcher-*` 签名冲突；安全审计盯上 `webSecurity:false` 或 IPC 面。

**结论**：如果项目进入纯维护期、且不再新增多窗口/工作区特性，A 是可辩护的、更便宜的选项。但仓库本身已经在朝「收紧边界」方向走（#4244 sandbox、typed IPC 契约、引擎迁移），A 与这个方向相悖。

### 方案 B：结构性调整（少量深接缝，非重写）

拆成四个**各自可逆**的接缝，按杠杆排序：

- **B1 把内部总线从 `ipcMain` 中剥离**：引入一个极小的类型化进程内事件总线（`TypedEmitter` 已存在，见 `shared/types/typedEmitter.ts`），替换所有 `ipcMain.emit` 的 main→main 用途；`ipcMain` 只保留 renderer↔main。订阅侧 `onInternalChannel` 已经是隔离点，改动集中。
- **B2 完成引擎退役**：删除 `muya` alias、`@marktext/muyajs` workspace 依赖、`muya.d.ts`（保留仍被引用的声明），并加一条架构检查禁止 `muya/lib` / `@marktext/muyajs` import。
- **B3 窗口作用域化文件操作**：按既有 TODO（`file.ts:36`）把 save/rename/move/close 移入 `EditorWindow`，renderer 只走窗口作用域通道；持久化函数（`writeMarkdownFile`）保持为纯模块函数不动。这一步自然让 `_openedFiles` 镜像的维护收敛到 `EditorWindow` 单点。
- **B4（可选、暂缓）合并文件镜像**：把 `_openedFiles/_openedRootDirectory` 明确为「打开文件索引」并给它单一所有权与对账路径，或改为按需向 renderer 查询。风险最高，放最后。

**方案 B 的假设**：内部事件与跨进程 IPC 是两个不同抽象，值得分开；渲染层继续作为文档内容的唯一真相源（不动所有权方向）。**使 B 变错的证据**：如果内部事件最终只有一两处、且团队明确不再扩展多窗口，B1 就不值得；如果未来要把文档所有权上移到 main（协同编辑），则 B3 的窗口作用域方向需要重新评估。

## 6. 建议

**推荐方案 B，但分阶段、只做前三个接缝（B1→B2→B3），B4 暂不做。** 理由：

- B1 是**杠杆最高、行为无变化、最易回滚**的一步。它消除「通道谁能发」的歧义，让 B3 的窗口作用域通道可以安全推理，也让 IPC 契约有机会变成可枚举、可校验的单一注册点。它是后面所有结构化的前提，而它本身不改变任何运行时行为。
- B2 是**零风险、高清晰度**的独立清理，可与 B1 并行，且能立即移除「双引擎」的未来风险。
- B3 解决的是仓库自己已经承认的债务（TODO 在代码里），并把镜像维护收敛到单点，但它比 B1/B2 更重，放第三。

**拒绝的方案**：不在此时引入通用 IPC 框架 / 服务层抽象——当前只有两个进程方向（renderer↔main）与一种内部广播，抽象收益不成立；先做「让现有契约单义」，等出现第二个跨进程消费者再评估。

**维持现状（A）的时机**：若接下来一两个版本明确不碰多窗口、不碰引擎边界、不碰安全审计，则 A 在短期更便宜；但 B1+B2 的总成本其实很低（机械替换 + 删死代码），即便只做这两步，长期摩擦也已显著下降。

## 7. 迁移与验证

**增量步骤（每步独立可合入、可回滚）**：

1. B2 先行：删 alias / 依赖 / `muya.d.ts`。回滚 = 还原删除。退出标准：`pnpm run typecheck`、`pnpm run lint`、`pnpm -C packages/desktop exec vitest run` 全绿，且 grep 确认无 `muya/lib` / `@marktext/muyajs` 运行时引用。
2. B1：以 `onInternalChannel` 的对称发布端替换 `ipcMain.emit`。回滚 = revert 单次提交。退出标准：新增架构检查断言 `ipcMain.emit` 只出现在唯一适配器内；现有单测 + e2e 全绿。
3. B3：把 save/rename/move/close 的处理器迁入 `EditorWindow`，通道改窗口作用域。回滚 = revert。退出标准：新增契约测试断言每个 renderer→main 通道**恰好注册一次**且与类型契约一致；多窗口 e2e 通过。

**验证清单（跨越真实接缝，而非只测纯函数）**：

- **契约/架构检查**：ESLint `no-restricted-imports` 或等价 grep 测试，禁止 `ipcMain.emit`（B1 后）、禁止遗留引擎 import（B2 后）、要求通道注册走单一注册表（B3 后）。
- **行为回归**：`pnpm run test`、`pnpm run test:e2e`；重点覆盖多窗口路由——同一文件开在两个窗口、关闭其一，验证 watcher 释放与路由打分不漂移。
- **失败模式**：保存后自身变更事件仍被 `ignoreChangedEvent` 抑制（不产生假 reload）；崩溃恢复 buffer 仍原子写；`webSecurity:false` 若被收窄，本地图片/绝对路径加载需专项 e2e。
- **观察项**：main 进程启动时通道注册的去重告警（若引入注册表，可在 dev 模式对重复注册打日志）。

## 8. 待决问题（答案会改变建议）

1. **多窗口路由是否还要演进**（拖 tab 跨窗口、每窗口 workspace/恢复、会话级窗口布局）？若「是」，B4（合并文件镜像）应提前；若「否」，B4 可长期搁置。
2. **`webSecurity: false` 是否仍必要**？能否换成自定义协议或按来源收紧？这直接改变 shell 安全姿态，并可能牵连本地图片/链接加载的接缝设计。
3. **`@muyajs/core` 的供给模型**：确认它只在本 monorepo 内以 workspace 消费（当前如此），这决定 B2 是「删除遗留包」还是「仅断开 alias/依赖」。
4. **文档所有权的最终方向**：未来是否可能把文档内容真相源从 renderer 上移到 main（例如为协同编辑铺路）？若可能，B3 的窗口作用域方向需要与「文档所有权上移」并存设计，而不是互相冲突。

[EVAL:evolve-software-architecture-loaded]
