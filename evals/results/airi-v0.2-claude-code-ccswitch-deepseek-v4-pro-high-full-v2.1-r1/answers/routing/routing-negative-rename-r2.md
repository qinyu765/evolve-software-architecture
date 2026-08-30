The rename would touch three occurrences in `apps/component-calling/src/pages/index.vue`, all of them direct references to the same local function:

1. **Definition** — `async function handleChatSendMessage()` at `apps/component-calling/src/pages/index.vue:320` becomes `async function sendChatMessage()`.
2. **Template submit handler** — `@submit="handleChatSendMessage"` on the `<Textarea>` at `apps/component-calling/src/pages/index.vue:472` becomes `@submit="sendChatMessage"`.
3. **Template click handler** — `@click="handleChatSendMessage"` on the Send button at `apps/component-calling/src/pages/index.vue:474` becomes `@click="sendChatMessage"`.

The name appears nowhere else in the file, so no other references need syncing. The change is purely a local rename with no behavioral impact — the function body, its call sites, and the `sendingMessage` state it reads are all unchanged.
