这个改动只涉及 `apps/component-calling/src/pages/index.vue` 第 474 行的 Send 按钮，其余属性和结构都不动。

**位置**:`apps/component-calling/src/pages/index.vue:474`

**当前写法**:

```html
<button bg="primary-200 dark:primary-900" w-full rounded-lg px-4 py-2 outline-none @click="handleChatSendMessage">
  Send
</button>
```

**建议改成**（保持原样的明/暗两档，只把 `primary` 换成蓝色系）:

```html
<button bg="blue-200 dark:blue-900" w-full rounded-lg px-4 py-2 outline-none @click="handleChatSendMessage">
  Send
</button>
```

即把 attributify 里的 `bg="primary-200 dark:primary-900"` 替换为 `bg="blue-200 dark:blue-900"`，浅色模式用 `blue-200`，暗色模式用 `dark:blue-900`，对应原来的 200/900 明暗层级。`blue-*` 类来自项目已启用的 `presetWind3`（Uno 默认 Wind 调色板），仓库里已有同类用法，例如 `packages/stage-pages/src/pages/devtools/websocket-inspector.vue` 中的 `bg-blue-100 dark:bg-blue-900`。

如果想要的不是柔和蓝而是更饱和的强调蓝，可改用 `bg="blue-500 dark:blue-600"` 或按需选用 `blue-400`/`blue-500` 等，但按“仅替换色相、保持明暗层级”的意图，`blue-200 dark:blue-900` 是最直接的对应改法。

未做任何文件修改。
