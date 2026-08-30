评估完成。以下是基于仓库证据（源码、配置、测试、文档、历史）的边界评估。我没有修改任何文件。

# MarkText `packages/desktop` 主/preload/渲染器/shared 边界评估与扩展性建议

## 1. 范围与置信度

评估对象是 `packages/desktop` 的四个进程/模块边界——`main`、`preload`、`renderer`、`shared`（外加 `common` 与 `types`），及其对**未来变更成本**的影响。分类：这是一个 **Electron 三进程桌面应用**（main CJS / preload CJS / renderer ESM，沙箱化），处于一次**进行到一半的沙箱迁移 + 类型化 IPC 迁移**之中。置信度：**高**——关键边界文件、构建配置、测试与文档均已直接阅读；主要残余不确定点是几个无据可查的历史决策（见「待决问题」）。

仓库目前没有 ADR（全仓 glob 未找到 `ADR*/**`），架构决策没有被记录成文。

## 2. 观察到的证据

| 断言 | 证据 | 类型 | 置信度 | 影响 |
|---|---|---|---|---|
| 两个窗口都真正沙箱化 | `src/main/config.ts:11-21,29-51`：`contextIsolation:true, sandbox:true, nodeIntegration:false`，且 `test/e2e/context-isolation.spec.ts` 作为哨兵测试 | 事实 | 高 | 边界是真实的，不是纸面 |
| CLAUDE.md 的「三进程架构」一节描述错误 | 该节称编辑/设置窗口用 `contextIsolation:false + nodeIntegration:true` 并指向不存在的 `config.js`；与同文件早前「sandboxed」描述及 `config.ts` 冲突 | 事实 | 高 | 最关键的边界在文档里是反的，误导后人 |
| `webSecurity:false` 对两个窗口生效且无注释说明 | `config.ts:19,40` | 事实 | 高 | 渲染器渲染 markdown/HTML 时同源策略被关闭，是未决安全面 |
| IPC 契约是**信道名**的单一来源，但 payload 大量 `unknown` | `src/shared/types/ipc.ts:10-12` 注释自认「迁移期有意宽松…commits 5–8 收紧」；四类信道接口在 40/92/208/217 行 | 事实 | 高 | 契约只约束名字，不约束形状，类型安全是半成品 |
| preload 是类型化网关 | `src/preload/index.ts:26-68` 泛型 `invoke/send/sendSync/on/once` | 事实 | 高 | 这是架构上最漂亮的接缝 |
| 但 preload 同时暴露 10 个薄领域 API，且与底层桥并存 | `preload/index.ts:70-228`；渲染器里 `window.electron.ipcRenderer` 用了 136 次/25 文件，`window.fileUtils|shell|…` 用了 86 次/18 文件 | 事实 | 高 | 两个并行的渲染器调用面，抽象泄漏 |
| global.d.ts 手工重声明全部 API | `src/types/global.d.ts:24-204` 手写 `ElectronAPI/FileUtilsAPI/PathAPI/…` | 事实 | 高 | 新增 API 要改 3 处：ipc.ts + preload + global.d.ts，且类型可能漂移 |
| 信道 handler 注册高度分散 | `ipcMain.on/handle/once` 共 107 处/23 文件；`main/ipc/index.ts:12-23` 只集中了沙箱 handler，其余散在 `menu/actions/file.ts`(17)、`app/index.ts`(12)、`menu/index.ts`(8)、`dataCenter`、`preferences` 等 | 事实 | 高 | 「单一来源」只对类型成立，对注册不成立 |
| main→renderer 推送不类型化 | `webContents.send` 共 87 处/20 文件，用裸字符串；`TypedEmitter`（`shared/types/typedEmitter.ts`）只给 main 内部类事件定型 | 事实 | 高 | 契约只在一个方向上被编译器检查（renderer→main），反方向没有 |
| 领域常量与路径谓词跨进程重复且算法分叉 | `MARKDOWN_EXTENSIONS` 同时硬编码于 `common/filesystem/paths.ts:8-20` 与 `preload/index.ts:115-127`；`hasMarkdownExtension/isSamePathSync/isChildOfDirectory` 两处实现，common 用 `fs.statSync` inode 比较（`paths.ts:135-157`），preload 用 `pathe`+同步 IPC 回退（`preload/index.ts:140-156`） | 事实 | 高 | 「什么是 markdown 文件/相同路径」这一领域不变量有两份会漂移的拷贝 |
| `SerializedStat` 形状重复且已漂移 | 共享 `shared/types/files.ts:9-15`（无 `ctimeMs`）vs 本地 `main/ipc/fs.ts:6-13`（有 `ctimeMs`，`isSymbolicLink` 非可选） | 事实 | 高 | 类型与实现已经不一致 |
| 缓冲状态（崩溃恢复）schema 无版本校验 | 渲染器写 `version:1`（`store/bufferedState.ts:7`），main 读侧 `editorBufferStore/index.ts:17-20,187-199` 只查 `tabs` 是否数组，不校验 version | 事实 | 高 | 持久化格式演进没有护栏 |
| 遗留 muya 边界已基本收敛 | 渲染器仅 3 文件仍 `import 'muya/lib…'`，`@muyajs/core` 已成为引擎 | 事实 | 高 | 引擎迁移接近完成，遗留面很小 |
| `main_renderer` 别名只服务测试 | `tsconfig.base.json:32` 映射到 `src/main`；仅 `vitest.config.ts:20` 与单元 spec 使用，生产 `src/` 零使用 | 事实 | 高 | 不是生产泄漏，但名字误导（暗示渲染器可 import main） |
| 持久化边界已有高成熟度 | `main/filesystem/index.ts` 与 `editorBufferStore` 用 `write-file-atomic` + fsync（注释引 #3786/#3828） | 事实 | 高 | 团队已在最难的持久化接缝上投入，非零基础 |

**推断**：preload 之所以重复纯字符串路径谓词，是因为 `common/filesystem/paths.ts` `import fs`——沙箱 preload 拿不到 `fs`，无法直接 bundle。所以这处重复部分是**沙箱约束逼出来的**，但这只解释了「谓词」，不解释「`MARKDOWN_EXTENSIONS` 常量」也被复制。

**未知**：`webSecurity:false` 的原始理由；底层 `ipcRenderer` 桥是否打算继续作为 store 的公开面；「commits 5–8 收紧类型」是否还有追踪载体。

## 3. 当前摩擦

按「一次变更会扩散到哪」排序：

1. **加一个信道要碰 4 处**：`ipc.ts`（类型）→ `preload/index.ts`（包装）→ `global.d.ts`（手工重声明）→ main 中某个散落的 handler 文件。其中 global.d.ts 是纯手工镜像，最容易漏。
2. **handler 注册无单一入口、无闭合性检查**：没有任何测试断言「`ipc.ts` 里声明的每个信道都有且仅有一个 handler」或「没有任何 handler 注册了未声明的信道」。契约是「名称清单」，不是「强制闭包」。
3. **main→renderer 推送完全裸字符串**：`webContents.send('mt::…')` 87 处不经过任何类型检查，编译器抓不到「主进程发了一个契约里没有的事件/参数」。类型安全的收益目前只覆盖一半方向。
4. **两个渲染器调用面并存**：领域 API（`fileUtils/shell/…`）很薄，store 里又大量直接走底层 `window.electron.ipcRenderer`。新功能写作者不知道选哪个；两套都要维护。
5. **领域常量/类型跨进程漂移**（`MARKDOWN_EXTENSIONS`、`SerializedStat`）：已经出现事实上的不一致。
6. **文档与现实脱节**：CLAUDE.md 的架构一节把沙箱方向写反，`ARCHITECTURE.md` 还是 monorepo 之前的老布局（`src/` 在根、无 preload/shared）。文档本身已成为误导源。

这些摩擦的共同根因：**一次进行到一半的迁移**——沙箱迁移做完了运行时刻（窗口真沙箱化了），但类型/契约/注册的「编译时」层面停在半路。

## 4. 质量属性优先级

对未来扩展性，我排：

1. **可维护性 / 变更局部性**（最高）：上面的 4 处扩散 + 散落注册 + 双调用面是主导成本。
2. **进程边界稳定性**：契约半类型化、单向检查，是跨进程 bug 的主要来源。
3. **安全**：沙箱已收紧（好），但 `webSecurity:false` 是未决面。
4. **可测试性**：单元测试已直接 import main 模块（`main_renderer` 别名），e2e 有沙箱哨兵；但「契约本身」没有被测试。

**明确不做权衡**：性能（编辑器是核心，但边界结构不影响）；跨平台移植性（keybindings 三平台已分文件，非当前短板）。

## 5. 方案对比

**方案 A：维持现状，继续零星收紧类型。**
- 收益：零风险，改动小。
- 代价：不消除 4 处扩散与散落注册；`unknown` 长期存在；漂移继续累积。
- 何时选它：团队短期只做 bug 修复、不打算再加新 IPC 面。

**方案 B（推荐）：完成类型化迁移并收拢调用面，分步做，不重写。**
- 边界与所有权：`ipc.ts` 成为真正的单一契约；preload 的推断类型派生 `global.d.ts`；main 增加一个 preload 桥的镜像（typed `sendToRenderer`）让推送方向也过类型检查；信道注册集中并加闭包测试。
- 收益：加信道从 4 处降到 2 处（契约 + 一个 handler），且编译器抓两个方向的漂移。
- 代价：需要一次性清点 107 个 handler / 87 个 send 的清单；工作量中等，但每步可独立交付、可回滚。
- 会退化的属性：无；短期测试工作量上升。

**方案 C：引入代码生成（从单一 schema 生成 preload/handler/类型）。**
- 收益：最强一致性。
- 代价：对这个体量的 app 是重型机器，得不偿失。**不推荐**，除非将来新增第三方插件或远程 API 面。

## 6. 建议（只建议，不改代码）

采用 **方案 B**，按下面顺序做可逆切片。**先做验证性的、后做结构性的**：

1. **先加「契约闭包测试」**（第一个切片，最高杠杆）：写一个 vitest spec，导入 `IpcInvokeChannels/IpcSendChannels/IpcSyncChannels/IpcMainEventChannels` 的 key，断言每个声明信道在 main 里有 handler、`webContents.send` 的信道都 ⊆ `IpcMainEventChannels`。这会在**不重构任何代码**的情况下立刻暴露漂移，也是后续所有重构的安全网。
2. **让 `global.d.ts` 从 preload 推导**，删掉手写接口镜像。`preload/index.ts` 已经用一个对象字面量定义全部 API，`typeof electronAPI` 就是类型来源；新增 API 不再需要第 3 处手写。
3. **给 main→renderer 推送加一个类型化 helper**（preload 桥的镜像），把 87 处 `webContents.send` 收敛到检查 `IpcMainEventChannels` 的调用。与第 1 步互补：闭包测试是「下限」，helper 是「日常使用」。
4. **单一来源领域常量**：把 `MARKDOWN_EXTENSIONS` 等纯字符串常量/谓词放进一个**不含 `fs`** 的沙箱安全共享模块，preload 与 common 都从它 import。`common/filesystem/paths.ts` 里需要 `fs` 的部分（`isSamePathSync` 的 inode 比较、`isImageFile`）留在 main 侧通过 IPC 暴露，就像现在 `mt::paths::is-same-sync` 已经做的那样。
5. **给缓冲状态 schema 加版本化读**：main 读 `_editor_buffer_store.json` 时校验 `version`，未知版本时降级而非静默解析。这保护崩溃恢复这条最脆的持久化路径。
6. **决定渲染器调用面**：要么把 store 收敛到领域 API（`fileUtils/shell/…`）并让底层 `ipcRenderer` 桥成为 preload 内部实现细节，要么正式承认底层桥是唯一面并删除薄包装。二选一即可，关键是**只剩一个**。
7. **清理命名与文档**：把 `main_renderer` 测试别名改名（如 `main`）；修正 CLAUDE.md 架构一节和 `ARCHITECTURE.md` 的沙箱描述。文档错误在这里是**事实性误导**，不是风格问题。

**明确先不要做**：不要上代码生成（方案 C）；不要在只有两个真实变体出现前抽象「原生适配器」层；不要把 `common` 和 `shared` 合并——它俩分工尚可（`common`=纯 Node 可执行工具，`shared`=跨进程类型/契约），问题在重复而非分类。

**值得写 ADR 的两件事**（用 `decision-record.md` 格式）：
- 沙箱边界的最终形态（`contextIsolation/sandbox/nodeIntegration` 的承诺，以及为何 preload 复制路径谓词）。
- `webSecurity:false` 的理由与移除计划——这是唯一一个「先确认再动」的项，因为关掉它可能破坏本地图片加载。

## 7. 迁移与验证

- **行为不变**：上述每步都是类型/结构层面的收敛，运行时行为不变；第 6 步若删薄包装，用现有 e2e（`launch.spec.ts`、`xss.spec.ts`、`context-isolation.spec.ts`）回归。
- **验证手段**：
  - 第 1 步的闭包测试进 CI（`pnpm -C packages/desktop exec vitest run`）。
  - `pnpm run typecheck`（CI 已强制）会直接证明第 2、3 步的收敛是否真消除漂移。
  - 第 5 步加一个「未知 version 的 buffer 文件」单元测试。
  - 对 `webSecurity` 的任何改动，先跑 e2e 的图片/导出/XSS 相关 spec，再决定是否保留为 ADR 里的「有意为之」。
- **完成标准**：新增一个 IPC 信道只改 `ipc.ts` + 一个 handler；`webContents.send` 无法再写出契约外信道；`global.d.ts` 不再含手工镜像；闭包测试绿。
- **回滚**：每一步独立提交、独立回滚；没有一步是单向的。

## 8. 待决问题（答案会改变建议）

1. `webSecurity:false` 为什么存在？——最便宜的验证：对这两行 `git blame`，并试开 `webSecurity:true` 跑本地图片/远程图片 e2e。（未知）
2. 底层 `ipcRenderer` 桥是否应当对 store 公开？——这是产品/团队约定问题，决定第 6 步选哪边。（未知）
3. 「commits 5–8 收紧类型」是否有 backlog/issue 追踪，何时落地？——决定方案 B 是「收尾」还是「重新启动」。（未知）
4. 缓冲状态是否需要支持**降级**（旧版本读新 schema）？——若发布策略允许用户回退版本，则第 5 步必须做；若强制前向，优先级可降。（未知）

总体判断：边界的方向是对的（真沙箱 + 类型化信道契约 + preload 网关 + 持久的崩溃恢复），**缺的不是重新设计，而是把这套契约推到两个方向、所有 handler、以及全局类型三处都强制一致**。方案 B 是把已建好的接缝收口，而非再造一层。

[EVAL:evolve-software-architecture-loaded]
