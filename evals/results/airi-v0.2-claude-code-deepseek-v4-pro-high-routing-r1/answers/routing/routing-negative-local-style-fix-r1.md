这一处局部改动位于 `apps/component-calling/src/pages/index.vue:474` 的 Send 按钮：

```html
<button bg="primary-200 dark:primary-900" w-full rounded-lg px-4 py-2 outline-none @click="handleChatSendMessage">
```

改为：

```html
<button bg="blue-200 dark:blue-900" w-full rounded-lg px-4 py-2 outline-none @click="handleChatSendMessage">
```

说明：

- 只是把 `bg` 属性值从 `primary-200 dark:primary-900` 替换为 `blue-200 dark:blue-900`，属于一对一替换，按钮的其余属性（`w-full rounded-lg px-4 py-2 outline-none`）和事件绑定都不动。
- 深浅色语义保持一致：亮色模式用浅蓝 `blue-200`，暗色模式用深蓝 `blue-900`，和原来的 `primary-200` / `primary-900` 色阶（200 亮、900 暗）一一对应。
- 这两个类是 `presetWind3()` 自带的标准色阶，项目已在 `uno.config.ts` 中启用该 preset，因此无需额外配置即可生效。

需要提醒的一点是：项目里 `presetChromatic` 的 `baseHue` 是 `220.44`，本身就是一个偏蓝色的主色，所以 `primary-*` 系列在视觉上已经接近蓝；改成 `blue-*` 是改用 UnoCSS 标准蓝色阶、脱离主题色系统，而不是换到一个完全不同的色相。
