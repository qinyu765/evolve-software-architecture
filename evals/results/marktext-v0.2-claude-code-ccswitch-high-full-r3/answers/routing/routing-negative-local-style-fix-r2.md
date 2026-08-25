这个文件里只有一处局部背景色：`packages/desktop/src/renderer/src/pages/preference.vue:72`，在 `.pref-container` 的样式块中：

```css
.pref-container {
  ...
  background: var(--editorBgColor);
```

要改成“更蓝的主题变量”，就是把 `var(--editorBgColor)` 换成主题的主色变量 `var(--themeColor)`：

```css
background: var(--themeColor);
```

理由：默认主题（`packages/desktop/src/renderer/src/assets/themes/dark.theme.css`）里 `--editorBgColor` 是 `#282828`（接近黑的编辑器底色），而 `--themeColor` 是 `#409eff`（Element Plus 主蓝），明显更蓝。主题里另一个等价变量 `--focusColor` 也是 `var(--themeColor)`，指向同一颜色。

一点提示：`--themeColor` 是各主题的强调色，默认/蓝色系主题下是蓝色；换成 `--themeColor` 后偏好设置页的整体背景会随主题强调色变化。若想保留“蓝但更淡”的观感，也可以用其透明度变体，例如 `var(--themeColor90)`、`var(--themeColor80)` 等（`--themeColor90` 是 `rgba(64,158,255,0.9)`）。

按要求未修改任何文件。
