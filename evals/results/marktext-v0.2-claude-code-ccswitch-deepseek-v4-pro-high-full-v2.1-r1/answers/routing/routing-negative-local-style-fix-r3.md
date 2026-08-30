I'll keep this read-only and just describe the change.

## 局部样式改动说明

`preference.vue` 中唯一的局部背景声明在 `.pref-container` 上（第 72 行）：

```css
background: var(--editorBgColor);
```

改动为使用更蓝的主题变量：

```css
background: var(--themeColor);
```

**依据**：`--editorBgColor` 是中性色背景变量——浅色主题下是白色（`styles/index.css:30` 的 `rgba(255,255,255,1)`），深色主题下是中性灰 `#282828`（`dark.theme.css:24`）。而 `--themeColor` 是主题的强调色变量，在默认深色主题及多数 railscasts 主题下取 Element Plus 蓝 `#409eff`（`dark.theme.css:3`），因此换用后背景会明显更蓝。

需要说明一点：`--themeColor` 的值随主题变化——默认浅色主题（`styles/index.css:8`）里它是绿色 `rgba(33, 181, 111, 1)`，所以“更蓝”的效果主要体现在深色主题下；如果要求在所有主题下都偏蓝，`--themeColor` 并不是跨主题恒定蓝色的变量。但就“把这一处局部背景换成更蓝的主题变量”而言，目标行就是第 72 行，替换变量为 `--themeColor`。

本次未修改任何文件。
