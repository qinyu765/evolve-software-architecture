`packages/desktop/src/main/ipc/index.ts` 里并没有“局部处理函数”可以重命名——这个文件只有 24 行，是一个聚合入口。

文件内唯一定义在本地的函数是第 12 行的 `registerSandboxIpcHandlers`，而它是 IPC 注册的聚合器，不是处理函数本身：它只是依次调用从 `./fs`、`./shell`、`./window` 等兄弟模块导入的 `register*Handlers` 函数。真正的 handler 都定义在 `fs.ts`、`shell.ts` 这些子文件里，不在 `index.ts` 中。

因此按你描述的操作（“重命名 + 同步该文件内的直接引用”）在这个文件里没有对应目标：

- `registerSandboxIpcHandlers` 在 `index.ts` 内部没有任何直接引用（它只在第 12 行被定义并导出，未被本文件调用），所以“同步文件内引用”这一步为空。
- 它的引用全在文件外：`packages/desktop/src/main/index.ts:15` 的 import 和 `:83` 的调用。若真要重命名它，改动点在这两处，而不是 `index.ts` 内部。

所以这一改动实际不能只落在 `index.ts` 一个文件内完成。如果你确实想重命名某个 handler，目标应该在 `ipc/` 下的具体子模块里（例如 `fs.ts`、`shell.ts`），而不是 `index.ts`。
