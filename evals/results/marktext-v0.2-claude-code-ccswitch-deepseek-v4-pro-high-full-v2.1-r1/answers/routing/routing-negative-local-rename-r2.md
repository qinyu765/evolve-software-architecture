无法按所描述的方式执行这个重命名，因为 `packages/desktop/src/main/ipc/index.ts` 里并不存在「局部处理函数」。

该文件共 23 行，内容只是：10 个从 `./bootInfo`、`./fs` 等同目录模块导入的 `register*Handlers` 函数，以及一个导出函数 `registerSandboxIpcHandlers`（`packages/desktop/src/main/ipc/index.ts:12`）。文件中没有任何用 `function`/`const` 定义、且仅在本文件内使用的局部函数。

这里唯一的函数 `registerSandboxIpcHandlers` 是 **导出** 的，不是局部函数：

- 定义：`packages/desktop/src/main/ipc/index.ts:12`
- 引用它的地方不在本文件内，而在 `packages/desktop/src/main/index.ts:15`（import）和 `packages/desktop/src/main/index.ts:83`（调用）。

因此如果要重命名它，改动范围就超出了「同步该文件内的直接引用」——本文件内部对它没有任何引用，需要同步的是 `packages/desktop/src/main/index.ts` 里的 import 和调用点。这与「局部改动」的前提不一致。

如果你希望我描述这个改动，可能的两种符合事实的写法是：

1. 若指的是文件里这些 `register*Handlers` 导入：它们都是从外部模块导入的，重命名需要改动各模块的导出处，同样不是本文件内的局部改动。
2. 若确实想重命名 `registerSandboxIpcHandlers`：需要改 3 处——`ipc/index.ts:12`（定义）、`main/index.ts:15`（import）、`main/index.ts:83`（调用），这是跨文件改动，不是「仅同步文件内引用」。

需要我按其中某一种方式，把具体的重命名方案（新名称 + 需同步的位置）写出来吗？
