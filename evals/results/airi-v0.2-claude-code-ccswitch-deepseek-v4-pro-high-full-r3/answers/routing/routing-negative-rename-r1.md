该重命名是文件内局部改动，`handleChatSendMessage` 在 `apps/component-calling/src/pages/index.vue` 中共出现 3 处，且在整个仓库中没有其他引用，改名不会破坏外部调用点。

具体改动点：

1. **第 320 行 — 函数声明**
   - `async function handleChatSendMessage() {` → `async function sendChatMessage() {`

2. **第 472 行 — Textarea 的 submit 监听**
   - `@submit="handleChatSendMessage"` → `@submit="sendChatMessage"`

3. **第 474 行 — 按钮的 click 监听**
   - `@click="handleChatSendMessage"` → `@click="sendChatMessage"`

其余代码（函数体、消息推送、`streamText` 调用等）均不受影响，无需改动。
