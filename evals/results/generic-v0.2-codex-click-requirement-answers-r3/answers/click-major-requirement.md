建议采用**显式异步调用路径，保留现有同步路径，并只调整执行与上下文边界**。复用 Click 的参数解析、命令树和装饰器；异步路径负责等待回调、传播取消及完成清理。

如果需求仅限“一个同步入口调用一个异步叶子命令”，局部包装已经可行。若要把能力作为 Click 的可组合命令功能交付，覆盖 Group、chain、嵌套调用和结果回调，则推荐下面的有限结构调整。独立并发命令、多种异步运行时尚未被确认，不应成为扩大重构范围的理由。

以下是方案，未修改文件、安装依赖、创建提交或改变外部状态。

**当前能力已经核实。** 仓库 HEAD 为 `934813e`，标签及源码版本均为 8.1.8；这是 Python 库，其 manifest 要求 Python ≥3.7，现有测试矩阵覆盖 CPython 3.7–3.13、PyPy，以及 Windows、macOS、Linux。[版本](/evaluation-path/repository/src/click/__init__.py:75)、[依赖声明](/evaluation-path/repository/pyproject.toml:16)、[CI](/evaluation-path/repository/.github/workflows/tests.yaml:18)。

| 已观察事实 | 可检查证据 | 架构含义 |
|---|---|---|
| `main → Command.invoke → Context.invoke → callback` 直接返回结果，没有等待步骤 | [main](/evaluation-path/repository/src/click/core.py:1079)、[Context.invoke](/evaluation-path/repository/src/click/core.py:737) | 可以注册 `async def`，但当前调用链不会执行其协程体 |
| 当前上下文存在线程局部栈中；退出时先关闭资源，再弹栈 | [globals.py](/evaluation-path/repository/src/click/globals.py:9)、[生命周期](/evaluation-path/repository/src/click/core.py:462) | 线程隔离不等于任务隔离；等待必须发生在有效上下文内 |
| Group 顺序调用回调；chain 收集结果；叠加结果回调直接把前一结果传给后一回调 | [结果回调组合](/evaluation-path/repository/src/click/core.py:1604)、[Group 调用](/evaluation-path/repository/src/click/core.py:1663) | 只等待最终返回值无法保证初始化和结果处理顺序 |
| `pass_context` 等装饰器使用同步包装函数；部分包装器内部调用 `ctx.invoke` | [decorators.py](/evaluation-path/repository/src/click/decorators.py:27) | 仅检查外层函数是否为协程函数会漏掉被包装的异步回调 |
| CliRunner 替换标准流、环境变量和终端辅助函数；调用同步 `cli.main`，捕获 `SystemExit` 和 `Exception` | [隔离与调用](/evaluation-path/repository/src/click/testing.py:240) | 新异步测试入口必须覆盖整个执行及清理周期，仍不能承诺并发隔离 |
| 子类和自定义 Context 是已有扩展接口 | [扩展测试](/evaluation-path/repository/tests/test_custom_classes.py:20) | 新调度器不能静默绕过现有重写方法 |

只读内存探针使用本仓库 `src`、CPython 3.9.6，进一步观察到：

- 异步叶子命令经 CliRunner 调用后，退出码为 `0`，返回协程，函数体未运行。
- 普通 Group 在最外层等待之前，已经执行结果回调、关闭子命令资源和 Group 资源。
- 叠加结果回调的后一阶段收到未完成协程。
- 两个任务交错进入不同 Context 后，任务 A 读到 B 的上下文，任务 B 读到 A 的上下文。

这些结果验证了现状和反例，**不构成新方案兼容性已经通过的证明**。此外，历史提交 `ffd43e9` 修复过 CliRunner 未恢复全局补丁的问题，说明隔离恢复是已有维护成本，而非假设风险。

**方案比较如下。**

| 方案 | 收益与代价 | 适用条件、否定信号 |
|---|---|---|
| A：局部包装。同步回调内一次性运行异步工作 | 同步上下文包住异步执行，装饰器和 CliRunner 可沿用；成本最低。循环由包装器拥有 | 单个叶子命令足够时优先采用。需要宿主已有循环、跨命令异步资源或异步结果回调组合时，需重新评估 |
| B：新增异步执行路径，复用解析和命令模型 | 调用者可在已有循环中等待和取消；支持混合同步/异步命令。代价是维护执行顺序、上下文及扩展接口的双路径契约 | 推荐作为可组合能力交付。若真实范围仅为单个叶子命令，投入可能不值得 |
| C：统一替换为异步内核，同步 API 全部做桥接 | 长期减少两套调度逻辑；但同步调用也受循环、异常和生命周期变化影响 | 当前兼容性约束下不推荐。只有双路径长期出现大量重复修复，且扩展兼容性已有充分证据时再考虑 |

A 方案不应实现为“`main()` 返回后再等待”：探针已经证明此时资源可能关闭。每个 Group 回调分别建立事件循环也不是通用方案，因为可能引入跨循环资源和取消所有权问题。

**B 方案的接口与职责，应限定如下。** 名称为提议，尚非 Click 8.1.8 已有 API。

1. **调用入口。** 新增 `Command.amain`、`Command.ainvoke` 及 `Context.ainvoke/aforward`。嵌入场景在调用者循环中运行，返回最终值，调用者可通过所属 Task 的 `cancel()` 取消。终端入口提供同步桥接方法，例如 `main_async`，一次调用只拥有一个循环；已有运行中循环时，明确要求使用 `amain`，不偷偷转到线程。
2. **旧接口。** 现有 `main/invoke/forward/__call__` 的返回值、异常和调用顺序保持原契约。同步函数可以返回任意对象，不能把旧路径改成“遇到 awaitable 就自动等待”；仓库文档明确支持任意返回值。[返回值契约](/evaluation-path/repository/docs/commands.rst:542)。
3. **回调识别。** 调用原包装函数，保留参数注入、元数据和装饰器顺序。异步路径结合可追踪的原函数及显式异步标记识别回调，再等待实际返回的 awaitable；只等待该次调用一次，不递归消费返回数据。普通同步回调返回 awaitable 仍作为数据，除非明确选择异步执行语义。
4. **命令编排。** Group 初始化完成后才进入子命令；chain 保持串行，禁止默认改为 `gather`。结果回调逐阶段完成后再传递结果。注册叠加结果回调时保留阶段信息，同时保留原同步组合行为；这不是单个“等待辅助函数”能够解决的变化。
5. **扩展接口。** 继续使用 `make_context`、`context_class`、默认值转换和现有命令解析接口。仅重写旧 `invoke` 的第三方子类在新异步模式中，必须显式提供适配，或明确拒绝进入该模式；不能宣称调用旧重写后等待其返回值就足以兼容，因为重写方法可能在返回前已经执行后处理。

参数类型转换、参数回调、默认值提供器和交互输入首期继续同步。它们处在解析边界内；不应顺带扩展为异步参数系统。[参数回调实现](/evaluation-path/repository/src/click/core.py:2358)。

上下文职责留在 `Context/globals`，执行职责留在命令调用层：

- 异步调用域使用 `ContextVar` 保存**不可变栈值**，同步域保留线程局部行为。异步域的空栈不能回退到其他任务的线程栈；跨同步/异步入口的继承与恢复必须有明确规则。
- Context 对象本身仍是可变对象；任务局部存储不会自动使 `params/obj/meta/_depth` 并发安全。每次独立调用创建自己的 Context，禁止多个任务同时拥有并修改同一个 Context。
- 当前上下文保持到回调等待和清理结束。普通 Group 与 chain 的资源关闭顺序应分别复制现有行为，不能统一延长所有子上下文到最后。[现有清理断言](/evaluation-path/repository/tests/test_context.py:219)。
- 首期异步资源可在回调中使用 `async with`。若确认需要跨回调共享异步资源，再增加异步资源注册和 `aclose`；异步域应统一定义混合资源的逆序清理，不直接替换旧 `close()`。

**取消必须有独立语义。** 建议采用 asyncio 的协作式取消：请求通过 Task 传播，在可让出控制的位置处理；它不能强制中断阻塞同步代码，也不保证吞掉取消异常的回调立即结束。[Python 3.7 任务与取消文档](https://docs.python.org/id/3.7/library/asyncio-task.html#task-object)。

- 嵌入式 `amain/ainvoke`：清理后重新抛出 `CancelledError`，不转换成正常返回。
- 终端桥接：仅管理自身拥有的执行任务。Ctrl-C 先请求取消、等待清理，再沿用 Click 的 `Abort`、`Aborted!`、退出码 `1` 行为；不默认改为 `130`。
- 借用宿主循环时，不关闭循环、不覆盖宿主信号处理器、不取消宿主无关任务。回调创建的子任务应在其作用域结束前收束；首期不承诺托管任意后台任务。
- 清理失败保留异常链并完成上下文恢复。再次 Ctrl-C 可提供强制中止，但应明确它会削弱完整清理保证。

Python 3.8 起，`CancelledError` 从 `Exception` 改为 `BaseException`，因此新入口必须显式处理取消，不能依赖 CliRunner 当前的 `except Exception`。[官方版本说明](https://docs.python.org/3.11/library/asyncio-exceptions.html#asyncio.CancelledError)。Python 3.11 的 `Runner` 和 SIGINT 行为可作为版本条件下的实现依据，不能作为最低运行时要求。[Runner 文档](https://docs.python.org/3.11/library/asyncio-runner.html#handling-keyboard-interruption)。

CliRunner 建议增加同步桥接 `invoke_async` 和可等待的 `ainvoke`，继续返回现有 `Result`：

- 原 `invoke` 和 `Result` 字段语义保持。
- 隔离必须覆盖执行、取消处理和所有清理输出，再恢复全局状态。
- 同步桥接捕获命令取消时，明确生成失败 Result，保留取消异常；取消 `ainvoke` 调用任务时，完成恢复后传播取消，不吞成成功 Result。
- `catch_exceptions=False` 的普通异常传播保持；不能为捕获取消而笼统吞掉全部 `BaseException`。
- 异步入口仍只允许串行使用。ContextVar 无法隔离标准流、环境变量或工作目录。[维护方测试限制](/evaluation-path/repository/docs/testing.rst:10)。

**质量属性按以下顺序取舍。**

| 优先级与目标 | 代价 | 验证方式 |
|---|---|---|
| 兼容性：已有同步可观察行为零回归 | 保留两条路径 | 旧套件及扩展反例；比较返回值、输出、异常链和清理顺序 |
| 取消正确性：取消后资源和上下文完成收束 | 清理会增加退出延迟 | Event 控制执行阶段，确认取消被观察且清理结束后才返回 |
| 可维护性：解析、参数绑定继续复用 | 编排和结果回调需异步分支 | 追踪修改传播范围；重复缺陷成为重新统一内核的信号 |
| 可测试性：通过公开入口确定性验证 | CliRunner 仍需串行 | 使用事件屏障而非固定 sleep；检测状态恢复和任务泄漏 |
| 性能与可移植性：同步调用不创建循环，保留支持矩阵 | 版本分支和异步入口启动成本 | 同步基准、循环创建次数、跨版本及跨平台验证 |

**阶段迁移、回滚和验收标准：**

1. **先固化契约。** 记录异步识别、取消结果、信号所有权、子类适配和资源顺序；形成“提议”状态 ADR。建立同步基线及上述反例。此阶段不改变运行行为。
2. **交付叶子命令能力。** 实现显式异步入口、任务局部上下文和同步终端桥接；覆盖装饰器、同步资源、成功、失败、取消和嵌套调用。回滚点是调用者切回旧入口；需要保留异步工作时，可退回 A 的局部包装。
3. **补齐组合与测试入口。** 覆盖 Group、chain、叠加结果回调、自定义 Context 和明确支持的子类适配，再开放 CliRunner 新入口。以已选异步入口作为发布边界，既有同步用户无需迁移。
4. **按证据扩展。** 跨回调异步资源、统一执行内核、其他运行时等需求，另作决策。发布后的 API 不应直接删除；回滚通过调用者切换、版本固定及兼容修复完成。切换前先取消并等待在途调用，不在执行中更换上下文机制。

发布门槛应包括：

- 现有同步测试全部通过；帮助、补全、参数默认值、装饰器顺序和自定义类行为保持。
- 同步、原生异步、同步包装异步及“同步返回 awaitable 数据”分别验证。
- Group/chain 初始化、结果传递和关闭顺序正确，结果回调不提前收到未完成协程。
- 两个独立 Context 的任务交错后，当前上下文、颜色和错误归属不串用。
- 在回调等待、子命令和结果回调阶段取消；后续命令停止，`finally` 执行，资源只清理一次。
- CliRunner 正常结束、异常、取消及清理失败后，恢复标准流、环境变量和终端补丁；保留正确的 Result 或异常传播。
- 自有循环、宿主循环及真实 Ctrl-C 分别测试。无未等待协程、未观察任务异常或新增任务泄漏；信号测试使用隔离子进程。
- 执行仓库现有版本、平台、类型检查和文档检查矩阵；未适配的第三方扩展不列入已验证兼容范围。

本次使用了 evolve-software-architecture 技能和你授权的官方文档替代路径。Click 判断以本地 8.1.8 实现、测试、维护方 docs 和历史为依据；Python 文档使用 3.7 语义及后续版本的明确变更标注。只运行了上述现状探针，未运行完整测试矩阵，也未实施方案。

[EVAL:evolve-software-architecture-loaded]