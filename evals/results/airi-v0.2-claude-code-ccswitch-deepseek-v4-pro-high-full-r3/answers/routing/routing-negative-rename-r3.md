这是一个纯局部的重命名，改动范围只有 `apps/component-calling/src/pages/index.vue` 一个文件（全仓库 grep 确认 `handleChatSendMessage` 只出现在这个文件里，没有被其他文件导入或引用）。

该文件内共有 3 处 `handleChatSendMessage`，都要改成 `sendChatMessage`：

1. **函数定义**（`index.vue:320`）：`async function handleChatSendMessage() {` → `async function sendChatMessage() {`
2. **模板里的 `@submit` 绑定**（`index.vue:472`）：`<Textarea v-model="sendingMessage" @submit="handleChatSendMessage" />` → `@submit="sendChatMessage"`
3. **模板里的 `@click` 绑定**（`index.vue:474`）：`<button ... @click="handleChatSendMessage">` → `@click="sendChatMessage"`

由于这是在 Vue SFC 的 `<script setup>` 中定义的本地函数，没有 `export`，函数体内部逻辑（校验空消息、推送 user/assistant 消息、调用 `createParser` 等）无需任何改动，只是符号名和两处模板绑定同步更名。该改动不会影响任何文件外的调用方。
