建议在 Click 8.1.8 上采用**新增异步调用入口、保留同步入口语义，并对上下文隔离做必要结构调整**的方案。复用现有解析器、装饰器和命令对象；Group/chain 仍按原顺序执行。首期以 `asyncio.Task.cancel()` 提供协作式取消，暂不引入通用执行引擎或新的异步资源管理框架。

本次使用了 `evolve-software-architecture` Skill，全程只读，没有修改文件、安装依赖、创建提交或改变外部状态。以下区分已核实事实与设计建议。

**当前能力核实如下。** 仓库 HEAD 为 `934813e`，标签和包内版本均为 8.1.8；这是 Python CLI 库，最低 Python 版本为 3.7，现有测试配置覆盖 CPython 3.7–3.13 和 PyPy 3.10。[版本声明](/evaluation-path/repository/src/click/__init__.py:75)、[包配置](/evaluation-path/repository/pyproject.toml:15)、[测试配置](/evaluation-path/repository/tox.ini:1)。

| 已核实事实 | 可检查证据 | 对方案的影响 |
|---|---|---|
| 调用链为 `main → Command.invoke → Context.invoke → callback`；末端直接返回回调结果，没有等待协程 | [core.py](/evaluation-path/repository/src/click/core.py:737)，以及其中的 `main`、`Command.invoke` | 现有 API 能接收异步函数，但不构成异步执行支持 |
| `pass_context`、`pass_obj` 使用同步包装函数；`make_pass_decorator` 内部还会调用同步 `ctx.invoke` | [decorators.py](/evaluation-path/repository/src/click/decorators.py:27) | 不能仅用 `iscoroutinefunction(callback)` 判断是否需要等待 |
| 当前上下文存储于 `threading.local()` 的可变列表 | [globals.py](/evaluation-path/repository/src/click/globals.py:1) | 同线程任务交错执行时可能串上下文 |
| Context 已有嵌套深度、同步 `ExitStack`、`with_resource` 和 `call_on_close` | [Context 生命周期](/evaluation-path/repository/src/click/core.py:462) | 应复用现有资源所有权；清理时当前 Context 仍须有效 |
| Group 调用自身回调、子命令及结果回调；chain 先创建子上下文，再逐个执行 | [MultiCommand.invoke](/evaluation-path/repository/src/click/core.py:1663) | 只等待叶子命令不足以支持混合同步/异步命令树 |
| CliRunner 同步调用 `cli.main`，隔离期间替换标准流、环境变量和若干全局函数；普通异常捕获为 `except Exception` | [testing.py](/evaluation-path/repository/src/click/testing.py:160) | 异步等待必须发生在隔离区内；新增异步入口也不能承诺并发测试隔离 |

我另做了不写文件的最小运行复现：从本地 `src` 导入 Click，`CliRunner.invoke(async_command, standalone_mode=False)` 返回退出码 **0** 和协程对象，但命令体没有执行；随后等待该协程时，Click 当前上下文已经不存在。两个任务交错进入不同 Context 时，任务 A 确实读到了任务 B 的 Context。以上结论来自实现和运行行为，不是依据搜索不到 `async` 推断能力缺失。

已有取消相关能力是 `Abort`、`Exit` 和 `KeyboardInterrupt`/`EOFError` 的同步处理，它们尚未形成任务取消契约。历史提交 `ffd43e9` 修复过 CliRunner 未恢复 ANSI 补丁的问题，也说明全局状态恢复属于必须回归的边界。

**方案比较与选择。**

| 方案 | 收益 | 成本、局限及失效条件 |
|---|---|---|
| 局部扩展：利用 `command(cls=...)` 增加异步命令类，在同步调用内运行协程 | 改动集中，现有装饰器和 CliRunner 可继续使用；适合独立进程中的单个异步命令 | 若按回调创建循环，会分裂 Group 生命周期；不能直接嵌入已运行的循环，任务取消和上下文隔离仍需另行解决。仅当需求明确限于独立 CLI、无异步宿主时适用 |
| **推荐：新增异步调用链，加上下文任务隔离** | 支持已有循环、混合同步/异步回调和可取消命令树；旧同步入口保持原义 | 需覆盖 Context、Command/MultiCommand 和 testing；存在少量同步/异步编排重复，必须用行为对照测试防止漂移 |
| 重构成统一执行计划、调度器或多后端执行引擎 | 多运行时、多调度策略出现后可能降低扩展成本 | 当前没有这些需求的证据；会放大自定义命令类、异常和资源生命周期的迁移面。暂缓，出现实际第二运行时或并行编排需求后再评估 |

局部扩展可以作为受限原型，但不能满足“嵌入异步环境、可靠取消、保持兼容”的完整目标。推荐方案只调整已证实存在问题的边界，保留解析和命令模型。

**建议的接口契约如下，名称均为拟议接口。**

| 接口 | 建议行为 |
|---|---|
| 现有 `main`、`invoke`、`Context.invoke/forward`、`CliRunner.invoke` | 签名、返回方式和异常处理维持原义；不自动等待返回的 awaitable |
| `Command.main_async` | 提供异步主入口；建议默认 `standalone_mode=False`，便于宿主等待和取消 |
| `Command.invoke_async`、`MultiCommand.invoke_async` | 在有效 Context 内执行并等待命令、Group 和结果回调 |
| `Context.invoke_async/forward_async` | 保留参数默认值、转发及子上下文规则，补上异步等待生命周期 |
| `CliRunner.invoke_async` | 异步返回现有 `Result`；隔离持续到执行及清理结束，普通异常沿用 `catch_exceptions` 契约 |

异步调用只检查**回调实际返回值**是否为 awaitable，并等待一层，因而支持现有同步包装装饰器。同步回调照常执行；其返回的 awaitable 在新入口中被解释为待执行结果，这是新接口必须明确说明的语义。

无需新增 `@async_command` 装饰器。现有 `@command`、`@group`、`@option` 和传递上下文的装饰器继续构建同一种命令对象。异步回调主动调用另一个命令时，应使用 `await ctx.invoke_async(...)`；不能直接等待旧 `ctx.invoke(other_command)` 的返回值，否则它创建的子 Context 可能已提前关闭。

自定义命令类也是兼容边界：旧同步覆写继续按原方式分派；异步入口不能静默绕过已有 `invoke`。同步自定义命令可通过受控适配调用；自行编排异步子命令的自定义 Group 需要显式实现 `invoke_async`。仓库已有自定义 `BaseCommand.invoke` 和 `context_class` 测试，迁移必须覆盖这些情况。

**内部所有权和失败处理应遵守以下规则。**

- `globals.py` 使用 `ContextVar` 保存不可变上下文栈，避免任务复制上下文后仍共享同一个可变列表。公开 `get_current_context` 行为保持不变；每次调用拥有自己的 Context，不能把同一个可变 Context 当作可并发共享对象。
- 异步调用层负责保持 Context 有效，直到回调及其等待完成。保留“清理先于出栈”的行为，并确保清理抛错后仍恢复上下文。现有 `__exit__` 是先 `close()` 再 `pop_context()`，这一失败路径需要专门验证。
- 普通 Group 保留结果回调与子上下文的现有嵌套关系；chain 保留逐个执行、逐个关闭子上下文后再处理结果列表的规则。不能为了异步化统一延长所有文件的生命周期。[仓库官方 chain 文档](/evaluation-path/repository/docs/commands.rst:415)。
- chain 已经提前解析出的、尚未执行的 Context，以及解析中途失败的 Context，也必须进入资源清理所有权范围；取消时不能只清理当前执行的节点。
- 首期继续使用同步 `ExitStack`。异步资源由回调自身的 `async with`/`finally` 管理。只有出现跨 Group 共享异步资源的实际需求，才增加异步资源登记接口，并明确混合同步/异步清理顺序；不把现有 `close()` 偷换成 awaitable。
- 参数回调、类型转换、prompt 和 shell completion 首期保持同步。它们各有独立调用路径，不能因命令回调支持异步便宣称全部支持异步。

取消由调用方持有的 Task 发起。`CancelledError` 应穿过 `main_async` 和 `CliRunner.invoke_async` 传播，清理后重新抛出；`catch_exceptions=True` 只捕获普通错误，不吞掉宿主取消。Python 3.8 将它改为 `BaseException` 子类，因此必须显式处理，避免 Python 3.7 与后续版本表现不同。[Python 3.8 官方异常文档](https://docs.python.org/fr/3.8/library/asyncio-exceptions.html)。

取消是协作式请求：同步阻塞回调、阻塞 prompt 或主动吞掉取消的代码不能获得强制终止保证；超时也不能被描述成严格完成期限。[Python 3.7 官方 Task 文档](https://docs.python.org/id/3.7/library/asyncio-task.html)。

事件循环归宿主所有，Click 异步入口不关闭它、不安装进程信号处理器。若后续需要供普通 CLI 或原有 `CliRunner.invoke` 使用的同步桥接，应显式选择该入口，只在最外层创建一次循环；已有循环中提示使用异步入口。Ctrl+C 的信号转发与退出码转换由桥接层承担，旧同步路径继续保留原有 Abort/退出码行为。

**质量属性按兼容性、取消可靠性、可维护性与可测试性、性能和可移植性排序。**

| 属性 | 目标与代价 | 验证方式 |
|---|---|---|
| 兼容性 | 同步调用结果、装饰器元数据、扩展分派和 CliRunner 行为不变；代价是保留两套入口 | 原测试通过，同步入口行为逐项对照 |
| 取消可靠性 | 停止后续命令、释放 Click 所有资源、恢复上下文和测试隔离；代价是必须等待清理，不能承诺即时结束 | 在各生命周期节点注入取消，检查资源与状态 |
| 可维护性/可测试性 | 复用解析和参数规则；异步编排承担少量重复 | 同一命令树分别经两入口执行，比较事件顺序和结果 |
| 性能/可移植性 | 同步路径不创建循环、Task 或线程；不提高 Python 下限 | 固定环境比较调用与启动开销，并跑支持矩阵；当前没有性能测量，预算需以基线确定 |

Python 3.7 已提供 `ContextVar` 和 `AsyncExitStack`，但本方案首期只需要前者；不依赖 Python 3.11 才有的 TaskGroup 等接口。[Python 3.7 官方上下文文档](https://docs.python.org/es/3.7/library/contextvars.html)、[资源管理文档](https://docs.python.org/ja/3.7/library/contextlib.html)。

**阶段迁移和回滚应按独立可审查步骤进行。**

1. 固化上述接口及取消契约，记录提议 ADR；建立现有行为基线。此阶段不改变运行行为。
2. 单独迁移上下文存储，验证同步嵌套、线程隔离和任务交错；保留独立回滚点。
3. 增加 Context、Command 和 Group 的异步路径，先通过混合命令树、资源和取消测试，再开放使用。
4. 增加 `CliRunner.invoke_async`，确保取消传播和全局状态恢复；更新版本适用文档、类型提示及变更记录。
5. 按实际需要增加同步桥接；跨命令异步资源登记、多后端和并行 chain 均留待独立决策。

发布前，每阶段可以撤回对应改动。发布后应先停止依赖新异步入口的调用，再退回旧版本；已经改成异步函数的回调不能直接交给旧同步入口作为回滚。ContextVar 调整涉及两种路径，应在异步功能停用并完成同步回归后再撤回。不要用自动线程执行或嵌套循环掩盖回滚问题。

**验收标准应覆盖行为，而不只是“协程成功执行”。**

| 范围 | 完成标准 |
|---|---|
| 原有兼容性 | 全部原测试通过；检查返回值、退出码、错误输出、颜色、prompt、装饰器和自定义类；类型与文档检查通过 |
| 异步执行 | 普通异步函数、被同步装饰器包装的异步函数、同步函数返回 awaitable、同步/异步混合 Group 均只执行一次，结果正确 |
| Group/chain | 调用、结果回调和关闭顺序符合原规则；取消后不执行后续节点或成功结果回调 |
| 上下文 | 多任务在等待前后读取正确 Context；完成、异常、取消及清理失败后栈恢复；子任务继承不共享可变栈容器 |
| 资源 | 解析失败、chain 后段取消及关闭函数抛错时，所有已创建 Context 的资源各清理一次；清理期间 Context 可访问 |
| 取消 | 启动前、等待中、嵌套调用和结果处理期间取消均可传播；`catch_exceptions=True` 不吞取消；超时及重复取消无遗留状态 |
| CliRunner | 输出收集覆盖等待和清理阶段；标准流、环境、颜色补丁及宽度状态恢复；重叠隔离调用在修改全局状态前拒绝 |
| 运行时边界 | 不关闭宿主循环、不取消宿主无关任务；后台任务需明确归应用所有，不通过扫描全循环“清场” |

并发命令上下文隔离与并发 CliRunner 隔离是两个边界。CliRunner 仍操作进程全局状态，新增异步方法不能让并发测试共享隔离区。[官方仓库测试文档](/evaluation-path/repository/docs/testing.rst:10)。

技术依据来自你授权的 Click 8.1.8 仓库实现、测试、维护方 `docs` 和版本适用的 Python 官方文档；没有加载 Python/Click 技术栈 Skill。本次验证了现状的最小复现，没有执行完整测试套件，也没有实现或验证拟议接口。方案假设首期面向 asyncio 和协作式取消；强制终止、多运行时及跨命令异步资源共享若成为明确要求，需要重新评估边界。

[EVAL:evolve-software-architecture-loaded]