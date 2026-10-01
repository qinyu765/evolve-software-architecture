**最值得优先治理的是“命令调用作用域的状态恢复与清理归属”**：先收紧 `CliRunner` 的隔离边界，并修补 `Context` 清理失败后的退栈路径。公开 API 和命令继承结构暂时保持稳定。这个方向有实际缺陷和历史证据支撑，收益比全面拆分 `core.py` 更确定，兼容性风险也更可控。

本评估使用了 `evolve-software-architecture`；技术依据来自你已授权的维护方仓库内 8.1.8 文档，并与实现、测试和 Git 历史交叉核对。检出版本为 `8.1.8`，HEAD 为 `934813e`。全程未修改文件、安装依赖或改变外部状态；执行了禁用字节码写入的内存探针，未运行完整测试矩阵。

**三个边界的现状**

公开 API 是门面，同时包含真实扩展契约。[顶层导出](/evaluation-path/repository/src/click/__init__.py:8)集中提供命令、上下文、参数等对象，但[官方 API 文档](/evaluation-path/repository/docs/api.rst:1)还覆盖 `click.core.ParameterSource`、`click.testing`、补全等模块。因此，兼容性不能只检查 `import click`；公开方法、子类覆盖点和模块路径也需要保留。[自定义类测试](/evaluation-path/repository/tests/test_custom_classes.py:4)明确验证了 `context_class`、格式器及命令类定制。

命令调用已有分工：

- 装饰器把函数和参数声明组装为命令对象。
- `__call__ → main` 处理进程入口、补全、错误展示和退出。
- `make_context → parse_args` 解析参数、转换类型、执行参数回调并记录来源。
- `Command.invoke → Context.invoke` 执行回调；多命令调用负责子命令上下文、链式结果与结果回调。

这不是纯计算管线：解析阶段也会触发回调和提前退出；`Context` 保存参数、父子关系及资源清理栈。上述路径可从[命令实现](/evaluation-path/repository/src/click/core.py:1065)、[解析与调用](/evaluation-path/repository/src/click/core.py:1408)和[多命令调用](/evaluation-path/repository/src/click/core.py:1663)核查。全面提取“执行引擎”会牵动这些时序契约。

测试边界则依赖进程内替换。`CliRunner.invoke` 调用真实的 `cli.main`，但其隔离作用域会替换标准流、提示函数、ANSI 判断、终端宽度及指定环境变量；文件系统隔离另行改变工作目录。[维护方文档](/evaluation-path/repository/docs/testing.rst:10)明确声明它会改变解释器状态且不支持线程安全。[实现](/evaluation-path/repository/src/click/testing.py:208)与此一致。

**决定优先级的证据**

| 观察 | 证据与性质 | 对决策的影响 |
|---|---|---|
| 增加隔离补丁需要同步维护保存、替换和恢复位置 | `ffd43e9` 修复遗漏的 `_compat.should_strip_ansi` 恢复；此前 `d83868a` 增加 Windows 色彩处理。历史事实，高置信 | 已出现跨模块改动后的恢复遗漏 |
| 隔离初始化失败会泄漏终端宽度 | [设置宽度早于保护块](/evaluation-path/repository/src/click/testing.py:237)；无效编码探针抛 `LookupError` 后，宽度从 `None` 留为 `80`。复现事实，高置信 | 仅保护命令执行阶段不足以保证恢复 |
| 清理回调失败会泄漏当前上下文 | [`close()` 位于 `pop_context()` 之前](/evaluation-path/repository/src/click/core.py:473)；关闭回调抛异常后，探针仍取得退出中的上下文。复现事实，高置信 | 命令生命周期边界也需要异常安全 |
| 正常路径已有保护 | 正常嵌套隔离探针恢复成功；[现有测试](/evaluation-path/repository/tests/test_context.py:103)检查嵌套清理和正常退栈。事实，高置信 | 应补强失败路径，不必重建整套调用模型 |

由此推断：当前主要摩擦是**状态修改与撤销责任没有紧密绑定**。这比“模块过大”更直接地解释已观察到的问题。尚未建立的是缺陷发生频率、维护成本和下游依赖规模；不能据此宣称它是整个项目最大的成本来源。

**方案与权衡**

决策优先级建议为：兼容性约束优先，其次是异常后的状态完整性、测试可信度、维护局部性。性能作为回归检查，当前没有性能瓶颈证据。

| 方案 | 收益 | 成本、风险及适用条件 |
|---|---|---|
| 保持结构，仅修补缺陷 | 改动最小，适合维护版本 | 保存与恢复仍靠人工配对；若类似遗漏继续发生，就不足以控制变更成本 |
| **在现有边界内集中管理恢复责任** | 覆盖初始化失败，新增补丁可在同一处登记撤销；保留调用模型 | 增加少量私有机制，需要验证恢复顺序和异常传播；若局部修复已能清楚保证这些不变量，可停止进一步提取 |
| 拆分 `core.py`，引入独立执行引擎 | 可能提高职责局部性 | 涉及继承、上下文时序和错误策略，迁移成本较高；待出现具体新增执行模式或持续跨职责修改后再评估 |
| 默认改为子进程 Runner | 提供更真实的进程边界 | 启动成本增加，命令对象、返回对象及异常信息难以原样传递；适合作为少量入口验证，不能直接替代现有 Runner |

推荐第二项，但从第一项的最小修复开始。结构调整应服务于已验证的恢复不变量。

**兼容性需要保留什么**

8.1.8 的 `standalone_mode=False` 不能理解为完全无进程行为。[异常文档](/evaluation-path/repository/docs/exceptions.rst:43)概括为关闭异常处理和隐式退出，但实现中仍有补全退出、EPIPE 退出，以及将中断转换为带原始原因的 `Abort`；后者有[现有测试](/evaluation-path/repository/tests/test_commands.py:534)支持。建议补充文档精度，保留现有语义。

探针还确认：

| 回调行为 | 默认 Runner | `standalone_mode=False` |
|---|---|---|
| `return 1` | `exit_code=0`，`return_value=None` | `exit_code=0`，`return_value=1` |
| `ctx.exit(1)` | `exit_code=1`，记录 `SystemExit` | `exit_code=0`，`return_value=1` |

因此，不能把返回整数自动解释成退出码，也不能在内部重构时顺便统一这些行为。

另外需保留 `CliRunner` 的公开方法覆盖点、`Result` 属性、默认 stderr 混合方式、提示回显、色彩规则，以及命令子类的调用分派。`Context` 清理时仍须能取得当前上下文，这一顺序已有[测试约束](/evaluation-path/repository/tests/test_context.py:219)。失败后恢复状态属于可观察的缺陷修复，应明确写入变更记录。

**迁移、回滚和验证**

以下是建议执行计划，本次没有实施：

1. **固定基线。** 为两个复现增加失败路径测试，同时锁定返回值、退出码、输出与异常原因。记录一份简短 ADR，说明状态归属和兼容性约束。
2. **分开修补。** `CliRunner` 从首次状态修改开始就受恢复保护；`Context` 即使清理抛异常也要退栈，同时保持“先清理、后退栈”和异常传播。两项独立提交，便于分别回滚。
3. **按收益提取私有恢复机制。** 在 `testing.py` 内利用已有标准库能力，让状态替换与撤销登记靠近，按逆序恢复。命令资源仍由 `Context` 管理，测试补丁仍由 Runner 管理；保留现有公开签名与覆盖点。
4. **补充进程入口验证。** 保留快速的进程内契约测试，增加少量子进程检查，覆盖真实 argv、退出码、stdout/stderr 和补全。现有[子进程测试](/evaluation-path/repository/tests/test_imports.py:56)主要检查导入依赖。

回滚以每一步的独立提交为单位。若私有恢复机制改变输出或子类行为，可撤销该机制，保留经过验证的局部修复；无持久数据格式迁移，也无需双实现长期共存。

完成标准应可观察：

- 初始化、执行及清理阶段失败后，标准流、Runner 替换的函数、终端宽度和指定环境变量恢复原值；嵌套退出后恢复到外层状态。
- 清理回调抛异常后，当前上下文恢复到进入前的上下文；异常仍可追踪，正常资源关闭顺序和次数保持一致。
- 上述返回值/退出码表、stderr 混合、提示回显、色彩及子类契约无未声明差异。
- 原有测试与新增失败路径测试通过；按[仓库矩阵](/evaluation-path/repository/tox.ini:1)完成 Python 3.7–3.13、PyPy，以及 CI 中 Windows/macOS/Linux 检查，并通过类型和文档检查。
- 新增隔离状态只需在一处声明替换与撤销；导入依赖不扩大，重复调用性能相对基线无显著退化。

这套恢复保证应限定于 Click 管理的状态。线程并发能力、任意命令对环境的修改，以及更完整的解析失败资源生命周期，仍需各自的需求与验证后再扩大范围。

[EVAL:evolve-software-architecture-loaded]