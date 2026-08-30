# 结论

不建议把当前结构作为长期边界，也不建议一次性重写。推荐保留 Electron 主进程 / preload / 每窗口 renderer、`@muyajs/core` 与 CodeMirror 的总体拓扑，采用渐进式边界调整：

1. 先明确文件会话、窗口路由和 IPC 责任。
2. 再抽离文档文件服务与编辑器宿主适配层。
3. 最后根据真实的多窗口同文件需求，决定是否引入跨窗口文档注册表。

本次仅进行了只读检查，未修改文件、提交代码或改变外部状态；测试也未执行，因此以下“验证”是建议方案，不代表当前测试已通过。

## 证据与判断

| 观察 | 类型 | 证据与长期含义 |
|---|---|---|
| 多窗口策略分散在 `App`、`WindowManager`、`EditorWindow` 和 renderer store | Fact / Inference | `App` 负责启动参数、单实例和新窗口策略；`WindowManager` 同时管理窗口、活动窗口和 watcher；`EditorWindow` 保存打开文件集合。见 [`app/index.ts`](/evaluation-path/treatment/packages/desktop/src/main/app/index.ts)、[`windowManager.ts`](/evaluation-path/treatment/packages/desktop/src/main/app/windowManager.ts)、[`editor.ts`](/evaluation-path/treatment/packages/desktop/src/main/windows/editor.ts)。 |
| 文件 IO 已具备原子写入、编码和行尾处理，但读写职责过于低层且重复 | Fact / Inference | [`markdown.ts`](/evaluation-path/treatment/packages/desktop/src/main/filesystem/markdown.ts) 负责文档解码；[`watcher.ts`](/evaluation-path/treatment/packages/desktop/src/main/filesystem/watcher.ts) 变更后再次读取；保存逻辑又位于 [`file.ts:36`](/evaluation-path/treatment/packages/desktop/src/main/menu/actions/file.ts:36)。 |
| Muya 与 CodeMirror 之间存在较宽的 renderer 兼容层 | Fact | WYSIWYG 使用 `@muyajs/core`，源码模式单独使用 CodeMirror；[`editor.vue`](/evaluation-path/treatment/packages/desktop/src/renderer/src/components/editorWithTabs/editor.vue) 维护 per-tab engine history、synthetic history 和事件转换；[`sourceCode.vue`](/evaluation-path/treatment/packages/desktop/src/renderer/src/components/editorWithTabs/sourceCode.vue) 是另一套编辑状态。 |
| 引擎类型边界仍不够稳定 | Fact | [`muya-core.d.ts`](/evaluation-path/treatment/packages/desktop/src/types/muya-core.d.ts) 使用了较宽的声明和 `any` 兼容；Vite/tsconfig 仍保留旧 `muya` alias，说明迁移尚未完全收口。 |
| Electron 安全边界方向正确，但 shell 权限仍较宽 | Fact | `contextIsolation`、sandbox、`nodeIntegration:false` 已配置并有 canary 测试：[`config.ts:8`](/evaluation-path/treatment/packages/desktop/src/main/config.ts:8)、[`context-isolation.spec.ts:5`](/evaluation-path/treatment/packages/desktop/test/e2e/context-isolation.spec.ts:5)。但 `webSecurity:false`，preload 暴露了通用文件系统 API，IPC payload 仍大量使用 `unknown`：[`ipc.ts:1`](/evaluation-path/treatment/packages/desktop/src/shared/types/ipc.ts:1)。 |
| 当前问题不是纯粹推测 | Fact | Git 历史中反复出现 flush、atomic save、watcher、external reload、source-mode dirty 和 tab history 修复；[`PARITY_SCOREBOARD.md:44`](/evaluation-path/treatment/packages/desktop/test/PARITY_SCOREBOARD.md:44) 还记录了迁移后的 undo parity 缺口。 |

## 主要长期摩擦

- **责任归属不清。** renderer 持有 markdown、dirty、cursor、history；main 持有路径、窗口和 watcher；菜单 action 又持有保存编排。`file.ts` 明确留下了“保存应移动到 EditorWindow”的 TODO。
- **文件身份被多处复制。** `EditorWindow._openedFiles`、renderer tabs、watcher entries、buffer store 各自保存路径或文档状态，且路径比较存在精确匹配与规范化匹配两种语义。
- **保存与外部变更依赖时序。** watcher 通过 `awaitWriteFinish` 和短期 ignore window 抑制自身保存事件；这对原子写入、快速连续保存、云盘同步或多窗口写入都较脆弱。
- **编辑器状态有双重真相。** Muya、CodeMirror 和 Pinia 都拥有实时状态，必须依靠 flush、事件顺序、synthetic history 和 bus 维持一致；近期修复说明这里已有较高变化放大效应。
- **多窗口同文件语义尚未明确。** 当前代码可以让多个窗口分别 watch 同一文件，但仓库中未发现针对“两个窗口打开同一文件并同时修改”的专门行为契约或 E2E。这里应标记为 Unknown，而不是假定已有冲突解决方案。
- **测试覆盖偏单窗口。** 现有 `tabs`、保存、watcher、source-mode 测试较丰富，但本次检查的测试树中未检出专门的 `WindowManager`/多窗口行为套件。这是 coverage gap，不代表绝对不存在其他测试。

## 方案比较

| 方案 | 代价 | 风险 | 验证方式 |
|---|---|---|---|
| A. 维持现状，仅补测试和局部修复 | 近期成本最低，回归面最小 | 长期仍会有跨层修改、重复 IO、事件时序问题；多窗口语义继续模糊 | 增加多窗口 E2E、保存/外部变更压力测试、统计 watcher 与重复读取 |
| B. 渐进式调整边界（推荐） | 中等，需要多次兼容迁移 | 过渡期可能同时存在新旧 IPC；路径规范化和保存顺序容易引入回归 | 旧 handler 作为适配器保留；契约测试、双路径对照、可回退开关 |
| C. 一次性建立跨窗口共享文档注册表并重构 shell | 最高，接近重写核心状态流 | 生命周期、冲突、IPC、恢复和性能风险集中爆发 | 需要先定义同文件协作模型，并进行长时间稳定性和性能测试 |

## 推荐的目标边界

建议选择 B，但保持现有进程拓扑：

- `WindowManager`：只负责窗口生命周期、焦点和路由。
- `EditorWindow / WindowSession`：负责单窗口 tab 和关闭协议。
- `DocumentService`：负责路径规范化、编码/行尾、加载、原子保存、重命名、watcher 和变更版本。
- renderer `DocumentStore`：只负责 UI 文档状态、dirty、cursor、布局和 tab 展示。
- `EditorHost`：分别包裹 Muya 与 CodeMirror，向 store 提供稳定的 `load / flush / snapshot / replace / restore / onChange` 能力。
- preload：文档操作使用高层、强类型 API；通用 `fileUtils` 继续只服务侧边栏、资源和非文档场景。
- Muya 保持 Electron 无关，不把 shell API 引入引擎包；不要强行把 Muya 和 CodeMirror 抽象成“同一种编辑器”。
- 旧 `@marktext/muyajs`、alias 和 handwritten declaration 只有在依赖图、构建、类型检查和测试全部证明不再需要后才移除。

尤其应把 watcher 的“按时间忽略自身事件”逐步替换为带 `operationId` 或文档版本的事件关联；否则多窗口和快速保存仍然只能靠时序猜测。

## 建议的迁移与验证顺序

1. 先记录四个决策：路径身份规则、同文件多窗口行为、保存失败语义、外部变更冲突语义。
2. 先补行为基线：不同窗口打开文件、同文件重复打开、保存后 watcher、外部修改未保存文档、关闭窗口取消保存。
3. 在现有 IPC 上增加高层文档契约，旧 handler 暂时转发到新实现。
4. 按已有 TODO，把保存、重命名、移动和关闭编排从全局菜单 action 收拢到窗口/文档服务。
5. 抽离 watcher 的文档身份和变更版本；保留原子写入与 `awaitWriteFinish`，但增加快速连续写入、原子 rename、云盘式延迟写入测试。
6. 最后收窄 `EditorHost` 类型边界，消化 Muya/CodeMirror 的事件和 history 适配，再清理旧 engine alias。
7. 每一步保留旧路径作为回退实现，确认新旧结果一致后再删除旧路径。

验收重点应包括：无丢失最后一次输入、无半写文件、保存后不误报外部修改、窗口路由正确、同文件策略可预测、sandbox/bridge 安全测试保持通过，以及启动、打开大文件、内存和 watcher 数量没有超出预设预算。

## 尚待产品确认的决定

- 是否允许同一文件同时出现在多个窗口？
- 若允许，采用最后写入、冲突提示，还是共享文档会话？
- `webSecurity:false` 是否是本地图片、HTML、Mermaid/PlantUML 等能力的明确要求？
- 是否仍计划支持旧 `@marktext/muyajs` 消费者或构建路径？
- 真实工作负载中窗口数、文件大小和 watcher 数量上限是多少？

[ EVAL:evolve-software-architecture-loaded ]
