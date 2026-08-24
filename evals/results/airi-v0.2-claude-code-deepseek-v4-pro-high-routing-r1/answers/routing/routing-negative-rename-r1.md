这个局部改动只涉及 `apps/component-calling/src/pages/index.vue` 一个文件，`handleChatSendMessage` 在文件内共有 3 处出现（全仓库搜索确认没有其他文件引用它）：

1. `index.vue:320` — 函数定义：`async function handleChatSendMessage() {`
2. `index.vue:472` — `<Textarea ... @submit="handleChatSendMessage" />`
3. `index.vue:474` — `<button ... @click="handleChatSendMessage">`

需要同步改动的就是这三处：把定义和两个模板事件绑定中的 `handleChatSendMessage` 都改成 `sendChatMessage`。函数是局部声明、局部使用，没有对外导出或被其他文件 import，因此不需要改动文件外的任何引用。

按此改动后，该函数会在模板里以 `@submit="sendChatMessage"` 和 `@click="sendChatMessage"` 引用，行为不变。

（按要求只做说明，未修改任何文件。）
