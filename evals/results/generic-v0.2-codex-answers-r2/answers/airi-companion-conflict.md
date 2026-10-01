建议**保留现有分层与深响应性，优先改善契约归属和异步状态一致性，再按职责渐进拆分页面**。本次评估限定于插件管理/检查界面及其状态链路；结论基于源码、配置、测试和历史，未作运行时性能测量。

现有链路是：

`共享 plugin-host 页面 → Pinia inspector store → 桌面注入的 bridge → Eventa IPC → 主进程插件宿主`

这个边界值得保留。页面负责展示和用户意图，store 保存检查快照，桌面负责传输适配，主进程拥有配置、发现结果和插件运行状态。共享页面并不意味着这些快照会自动跨窗口同步。

| 判断 | 可检查证据 | 性质与影响 |
|---|---|---|
| 已有运行时隔离接口 | [store 的 bridge 注入与运行时检查](/evaluation-path/repository/packages/stage-ui/src/stores/devtools/plugin-host-debug.ts:81)、[桌面注册 bridge](/evaluation-path/repository/apps/stage-tamagotchi/src/renderer/App.vue:139) | 高置信事实；共享 UI 无须引入 Electron |
| 数据契约存在重复定义 | store 中的 summary/snapshot 类型与 [Eventa 契约](/evaluation-path/repository/apps/stage-tamagotchi/src/shared/eventa/plugin/host.ts:60) 重复；历史 `9ca2eefb3` 曾补齐能力状态枚举 | 高置信事实；契约漂移已有历史证据 |
| 请求一致性需要加强 | [withBridge](/evaluation-path/repository/packages/stage-ui/src/stores/devtools/plugin-host-debug.ts:126) 每次请求独立切换同一个 loading，响应随后直接赋值 | 静态推断：请求重叠可能提前结束忙碌状态、旧响应覆盖新状态；尚未运行复现 |
| 页面有明确的拆分机会 | [plugin-host.vue](/evaluation-path/repository/packages/stage-pages/src/pages/devtools/plugin-host.vue:173) 同时包含命令输入、插件列表、状态汇总、kits 和 capabilities | 高置信事实；应按职责拆分，不能只凭行数拆分 |

还有一个必须保留的语义：[主进程 setEnabled](/evaluation-path/repository/apps/stage-tamagotchi/src/main/services/airi/plugins/host/index.ts:447) 更新启用配置，并不直接等同于加载或卸载。界面和 store 不应把 `enabled`、`loaded`、会话 `phase` 合并为一个状态。

已安装 Vue Skills 与本轮约束可以这样协调：

- [vue Skill](/evaluation-path/repository/.agents/skills/vue/SKILL.md) 建议在**不需要深响应性时**优先 shallowRef。当前明确要求保留深响应性，因此 registry、sessions、kits、capabilities 等继续使用既有 ref/reactive。根对象经常替换，也不能证明嵌套响应性不再需要。官方文档确认二者具有不同的嵌套更新语义。[Vue ref](https://vuejs.org/api/reactivity-core.html#ref)、[shallowRef](https://vuejs.org/api/reactivity-advanced.html#shallowref)。
- vue-best-practices 的响应性参考甚至建议基础值统一使用 shallowRef；这属于 Skill 偏好，本轮不采纳为迁移要求。采纳其 **computed 派生、显式数据流、集中副作用、按职责划分组件**的建议，保留现有基础值 ref 和组件风格。
- “只读状态＋actions”的建议不能直接套成 Pinia Setup Store 返回 `readonly(ref)`：Pinia 官方要求返回全部状态，并警告隐藏状态或将其设为只读会影响 SSR、DevTools 和插件。先通过组件 props/emits 与明确 actions 收敛写入口；若以后需要只读消费接口，再单独验证，避免改变底层状态注册。[Pinia Setup Stores](https://pinia.vuejs.org/core-concepts/#setup-stores)。

版本适用性较好：锁文件记录 Vue **3.5.32**、Pinia **3.0.4**。vue Skill 元数据标注 Anthony Fu、基于官方文档生成、版本 2026.1.31；vue-best-practices 标注 vuejs-ai、版本 18.0.0，不能据此认定它们是官方发布的 Skill。另使用了 Eventa Skill 检查传输契约，并按已有授权补充 Pinia 官方文档；这些通用建议没有被当成仓库事实。

方案取舍如下。优先级是**行为正确性与兼容性 → 变更局部性与可测试性 → 性能**；性能目前缺少预算和测量证据。

| 方案 | 收益 | 成本与取舍 |
|---|---|---|
| 保持现状，只补文档 | 成本最低 | 重复契约和请求一致性风险仍在；适合短期冻结 |
| **沿现有边界渐进改进** | 集中契约、明确请求策略，保留运行时隔离和响应性 | 有限类型迁移与行为验证成本；推荐 |
| 新建统一插件管理服务、全量拆组件 | 可能统一更多消费者 | 当前缺少实际变化需求支持，易形成转发层；暂缓 |

推荐的后续步骤与验收路径：

1. **统一纯数据契约。** registry、session、inspection DTO 应只有一个共享所有者；Eventa 事件继续留在桌面 shared，bridge 接口归共享 inspector 功能所有。[现有 plugin-protocol 包](/evaluation-path/repository/packages/plugin-protocol/package.json:17) 是候选承载位置，但需验证公开导出和浏览器编译链，避免引入 Node 宿主运行时。保持字段、事件名和返回值不变。
2. **在 store 内明确命令与刷新策略。** 忙碌状态覆盖“命令＋后续 inspection”的完整操作；写命令按序处理，读取结果防止过期提交。已有 stage-model store 使用请求序号，可参考其政策，暂不抽通用工具。命令成功而 inspection 失败时，应显示“操作已完成，快照刷新失败”，保留并标明旧快照，避免暗示主进程操作已回滚。单窗口策略不能保证跨窗口串行化。
3. **按职责拆界面。** 搜索词、手动输入 ID、toast 留在页面局部；共享快照与请求状态留在 store。先提取插件列表/操作组件、kit/capability 展示组件，以 typed props 输入、emits 表达意图，子组件不直接改共享对象。保留当前“顶部全局计数、列表随筛选变化”的行为，不批量迁移命名、样式或组件 API。

验证应先于生产代码修改：用受控 Promise 复现请求乱序和提前结束 loading；覆盖无 bridge、命令失败、命令成功但刷新失败。响应性回归要同时验证**根快照替换**及**嵌套字段/数组修改**仍更新 computed 和 DOM，防止迁移时丢失深响应性。

现有[宿主测试](/evaluation-path/repository/apps/stage-tamagotchi/src/main/services/airi/plugins/index.test.ts:1031)覆盖快照不泄漏可变引用，可继续复用；它不能替代 Vue 消费侧响应性测试。stage-ui 测试需使用其独立 Vitest 配置，根项目列表未包含它。未来实施后，再运行相关包 typecheck、定向测试及根 `pnpm typecheck`、`pnpm lint`；实际脚本名是 `typecheck`。

每步应独立可回退：先契约迁移，再请求政策，最后界面拆分。完成标准是行为和深响应性回归通过、共享代码不依赖桌面运行时、契约只维护一份。远程插件管理、多窗口实时一致性或经测量确认的性能瓶颈出现时，再重新评估更大的抽象。

本轮仅作只读检查，未修改文件、安装依赖、创建提交或运行测试、构建与 lint；并发风险及性能表现仍需上述验证。

[EVAL:evolve-software-architecture-loaded]