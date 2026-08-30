在 `apps/component-calling/src/pages/index.vue` 中，`handleChatSendMessage` 共有 3 处出现：

- **第 320 行**：函数定义 `async function handleChatSendMessage() {` —— 需改为 `async function sendChatMessage() {`
- **第 472 行**：模板引用 `<Textarea ... @submit="handleChatSendMessage" />` —— 需改为 `@submit="sendChatMessage"`
- **第 474 行**：按钮引用 `@click="handleChatSendMessage"` —— 需改为 `@click="sendChatMessage"`

即把函数定义重命名为 `sendChatMessage`，并同步该文件内第 472、474 两处模板引用。文件内没有其他对 `handleChatSendMessage` 的直接引用（本文件之外未检查，也未做修改）。
