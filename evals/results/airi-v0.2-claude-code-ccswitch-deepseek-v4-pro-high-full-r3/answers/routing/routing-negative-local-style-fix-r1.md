在 `apps/component-calling/src/pages/index.vue:474`，Send 按钮当前的属性写法是：

```html
<button bg="primary-200 dark:primary-900" w-full rounded-lg px-4 py-2 outline-none @click="handleChatSendMessage">
  Send
</button>
```

这里 `bg="primary-200 dark:primary-900"` 是 UnoCSS 的 attributify 写法，等价于类名 `bg-primary-200 dark:bg-primary-900`：浅色模式用 `primary-200`，深色模式用 `primary-900`。

要改成蓝色背景类，保持同样的“浅色 200 / 深色 900”层级，只需把颜色名从 `primary` 换成 `blue`：

```html
<button bg="blue-200 dark:blue-900" w-full rounded-lg px-4 py-2 outline-none @click="handleChatSendMessage">
  Send
</button>
```

即只改动第 474 行的一处：`primary-200 dark:primary-900` → `blue-200 dark:blue-900`。其余属性（`w-full`、圆角、内边距、`outline-none`、点击事件）保持不变。

补充一点：如果想要的不是同层级的浅蓝/深蓝，而是更醒目的主题蓝，也可以换成 `bg="blue-500 dark:blue-600"` 这类，但按原样“仅替换颜色名、保留明暗层级”的最小改动就是 `blue-200 dark:blue-900`。文件未做任何修改。
