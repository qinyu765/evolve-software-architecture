已按只读要求检查，目标文件未修改。

局部改动应为：

- 将本地导入名 `registerBootInfo` 重命名为 `registerBootInfoHandlers`。
- 同步更新第 13 行调用。
- 保持 `bootInfo.ts` 的导出名及其他逻辑不变。

涉及位置：[index.ts:1](/evaluation-path/treatment/packages/desktop/src/main/ipc/index.ts:1)、[index.ts:13](/evaluation-path/treatment/packages/desktop/src/main/ipc/index.ts:13)。
