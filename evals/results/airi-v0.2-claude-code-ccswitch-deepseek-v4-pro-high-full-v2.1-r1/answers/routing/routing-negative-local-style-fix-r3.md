`apps/component-calling/src/pages/index.vue:474` 的 Send 按钮当前是：

```vue
<button bg="primary-200 dark:primary-900" w-full rounded-lg px-4 py-2 outline-none @click="handleChatSendMessage">
  Send
</button>
```

这一处局部改动就是替换 `bg` 属性的值：

- 从：`bg="primary-200 dark:primary-900"`
- 改为：`bg="blue-200 dark:blue-900"`

在 UnoCSS 里 `bg="primary-200 dark:primary-900"` 等价于 `bg-primary-200 dark:bg-primary-900`，即浅色模式用 200 档、深色模式用 900 档。改成蓝色后保持同样的明暗档位，得到：

```vue
<button bg="blue-200 dark:blue-900" w-full rounded-lg px-4 py-2 outline-none @click="handleChatSendMessage">
  Send
</button>
```

只动 `bg` 属性值本身，`w-full`、`rounded-lg`、`px-4`、`py-2`、`outline-none` 以及 `@click` 都不变。如果希望更醒目的蓝，也可以把档位换成 `blue-500 dark:blue-700`，但按最小改动原则，`blue-200 dark:blue-900` 是最贴合的平移替换。
