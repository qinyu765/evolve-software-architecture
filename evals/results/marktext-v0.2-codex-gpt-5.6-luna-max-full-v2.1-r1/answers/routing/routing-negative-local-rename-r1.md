只读检查结果：

`packages/desktop/src/main/ipc/index.ts:12` 中唯一的聚合处理函数是 `registerSandboxIpcHandlers`。该文件内没有它的直接调用；实际引用位于 [`main/index.ts:15`](/evaluation-path/treatment/packages/desktop/src/main/index.ts:15) 和 [`main/index.ts:83`](/evaluation-path/treatment/packages/desktop/src/main/index.ts:83)。

因此重命名时需同步这两处；需求未指定新名称，无法据证据确定具体改名。文件未修改，工作区保持干净。
