该文件里只有一个局部处理函数，是第 12 行的导出箭头函数 `registerSandboxIpcHandlers`：

```ts
export const registerSandboxIpcHandlers = (): void => { ... }
```

重命名这个函数时，该文件内的直接引用情况是：**没有需要同步的其他引用**——`registerSandboxIpcHandlers` 在 `packages/desktop/src/main/ipc/index.ts` 中只出现这一次（定义兼导出处，第 12 行），函数体内调用的是从各模块 import 进来的 `registerBootInfo()`、`registerFsHandlers()` 等，与这个函数名无关。

所以若将其重命名（例如改为 `registerIpcHandlers`），本文件内唯一需要改动的位置就是第 12 行的定义行。

需要注意：这个函数是导出的，真正引用它的是文件外的 `packages/desktop/src/main/index.ts`——第 15 行的 `import { registerSandboxIpcHandlers } from './ipc'` 和第 83 行的 `registerSandboxIpcHandlers()`。如果范围仅限于“该文件内”，这两处不在同步范围内，但为了代码能编译，它们也必须同步改，否则会因导入名/调用名不匹配而报错。

综上，这一局部改动是：在 `index.ts` 第 12 行把 `registerSandboxIpcHandlers` 改为新名字，文件内无其他引用需改；若要保持可编译，还需同步 `src/main/index.ts` 第 15、83 行。
