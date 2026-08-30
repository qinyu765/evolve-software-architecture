无需修改文件，只说明这一处局部改动。

**位置**：`apps/component-calling/src/pages/index.vue:474`，Send 按钮：

```vue
<button bg="primary-200 dark:primary-900" w-full rounded-lg px-4 py-2 outline-none @click="handleChatSendMessage">
  Send
</button>
```

**改动**：把 `bg` 属性的值从 `primary-200 dark:primary-900` 改为标准 UnoCSS 蓝色背景类，建议沿用文件里其他按钮的「浅色 200 / 深色 900」层级，即：

```vue
<button bg="blue-200 dark:blue-900" w-full rounded-lg px-4 py-2 outline-none @click="handleChatSendMessage">
```

`blue-200`、`blue-900` 都来自 `uno.config.ts` 中启用的 `presetWind3()` 默认色板（Tailwind 风格的 `blue-*` 系列），无需额外配置；`dark:` 变体也由该预设支持。其余属性（`w-full rounded-lg px-4 py-2 outline-none`）和 `@click` 保持不变。
