这个局部改动很明确。`apps/component-calling/src/pages/index.vue` 中共有 3 处 `handleChatSendMessage`，全部位于该文件内，无其他文件引用：

1. **第 320 行**（函数定义）：
   ```ts
   async function handleChatSendMessage() {
   ```
   改为：
   ```ts
   async function sendChatMessage() {
   ```

2. **第 472 行**（`Textarea` 的提交事件绑定）：
   ```html
   <Textarea v-model="sendingMessage" @submit="handleChatSendMessage" />
   ```
   改为 `@submit="sendChatMessage"`。

3. **第 474 行**（发送按钮的点击事件绑定）：
   ```html
   <button ... @click="handleChatSendMessage">
   ```
   改为 `@click="sendChatMessage"`。

即只把函数名从 `handleChatSendMessage` 改为 `sendChatMessage`，并同步更新第 472、474 行这两处直接引用。函数体、参数和调用语义均不变，且该文件外没有其他引用需要处理。
