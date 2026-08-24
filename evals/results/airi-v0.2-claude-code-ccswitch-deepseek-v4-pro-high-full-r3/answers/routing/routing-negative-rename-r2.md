在 `apps/component-calling/src/pages/index.vue` 中，`handleChatSendMessage` 共有三处出现，全部在该文件内部：

1. 函数定义：`index.vue:320` — `async function handleChatSendMessage() {`
2. 模板内 Textarea 的提交事件：`index.vue:472` — `@submit="handleChatSendMessage"`
3. 模板内 Send 按钮的点击事件：`index.vue:474` — `@click="handleChatSendMessage"`

需要做的局部改动是：

- 将第 320 行的函数名从 `handleChatSendMessage` 改为 `sendChatMessage`；
- 将第 472 行和第 474 行模板中的 `handleChatSendMessage` 引用同步改为 `sendChatMessage`。

也就是说，这三处字符串 `handleChatSendMessage` 都要替换为 `sendChatMessage`。该文件没有把 `handleChatSendMessage` 暴露给其他文件（没有 `export`），所以不需要改动文件外的任何引用。除此之外不做其他修改。
