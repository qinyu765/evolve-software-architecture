在 `apps/component-calling/src/pages/index.vue:474` 的 Send 按钮上：

```html
<button bg="primary-200 dark:primary-900" w-full rounded-lg px-4 py-2 outline-none @click="handleChatSendMessage">
  Send
</button>
```

这一处局部改动就是把 `bg` 属性的值从 `primary-200 dark:primary-900` 换成蓝色 UnoCSS 背景类，例如：

```html
<button bg="blue-500" w-full rounded-lg px-4 py-2 outline-none @click="handleChatSendMessage">
  Send
</button>
```

其余属性（`w-full rounded-lg px-4 py-2 outline-none` 和 `@click`）都不动。这里用的是 UnoCSS 的 attributify 写法，所以保留 `bg="..."` 形式；`blue-500` 来自 `presetWind3()` 的标准配色，项目里无需额外配置即可生效。
