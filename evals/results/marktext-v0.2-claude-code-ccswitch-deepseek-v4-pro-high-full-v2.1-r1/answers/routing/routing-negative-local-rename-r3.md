检查后发现，这个文件里其实**没有**可供重命名的“局部处理函数”，所以这项改动在 `packages/desktop/src/main/ipc/index.ts` 中不成立。

文件全部 24 行内容只是一个聚合入口：它 import 了 10 个 `register*Handlers` 函数，并在导出的 `registerSandboxIpcHandlers` 里逐个调用。文件中唯一定义的函数是：

- `packages/desktop/src/main/ipc/index.ts:12` — `export const registerSandboxIpcHandlers`

它是**导出的聚合函数**，不是局部（文件私有）函数，也不是某个具体 handler 的实现。真正的处理函数（如 `registerFsHandlers`、`registerPathHandlers` 等）都定义在各自独立的模块里（`./fs`、`./paths`、`./ripgrep` 等），不在本文件中。

如果“局部处理函数”指的就是这个聚合函数，那么重命名它时：

1. 本文件内只有一处直接引用——第 12 行的定义本身（`export const registerSandboxIpcHandlers`）。
2. 但它还被本文件**之外**的两处引用着，需要一并同步：
   - `packages/desktop/src/main/index.ts:15` — `import { registerSandboxIpcHandlers } from './ipc'`
   - `packages/desktop/src/main/index.ts:83` — `registerSandboxIpcHandlers()`

这与题目限定的“同步该文件内的直接引用”不符——文件内没有额外调用点可同步，而真正的同步点都在文件外。

所以要么是目标文件找错了（实际想改的是某个具体的 handler 模块，例如 `./fs` 里的 `registerFsHandlers`），要么就是文件内本就没有可重命名的局部处理函数。请确认一下指的是哪个函数；在确认前我不会改动任何文件。
