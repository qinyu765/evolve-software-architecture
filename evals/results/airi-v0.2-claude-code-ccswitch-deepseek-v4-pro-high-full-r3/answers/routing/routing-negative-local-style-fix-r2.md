在 `apps/component-calling/src/pages/index.vue:474` 的 Send 按钮上，只需改这一处属性值：

- 当前：`bg="primary-200 dark:primary-900"`
- 改为：`bg="blue-200 dark:blue-900"`

即把 `<button bg="primary-200 dark:primary-900" w-full ...>` 里的 `bg` 属性值整体替换成蓝色系。该应用使用 `presetWind3` + `presetAttributify`（见 `apps/component-calling/uno.config.ts:20-21`），Wind3 预设自带标准 `blue-*` 调色板，`blue-200`（浅色模式）和 `blue-900`（深色模式）都能正常生成，且保持了原有的「200 浅 / 900 深」明暗档位，是最小的局部改动。

如果你想要更明显的蓝色，也可以把浅色档换成 `blue-500`，但保持 `blue-200 dark:blue-900` 与现有 `primary` 的明暗层级最接近。
