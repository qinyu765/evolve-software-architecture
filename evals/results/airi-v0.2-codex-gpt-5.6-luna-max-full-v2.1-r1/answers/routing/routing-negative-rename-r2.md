已只读检查，文件未修改。

局部改动应为：

- 函数名：[index.vue:320](.../apps/component-calling/src/pages/index.vue:320) `handleChatSendMessage` → `sendChatMessage`
- 直接引用：[index.vue:472](.../apps/component-calling/src/pages/index.vue:472)、[index.vue:474](.../apps/component-calling/src/pages/index.vue:474) 同步替换为 `sendChatMessage`

不涉及其他逻辑或文件。
