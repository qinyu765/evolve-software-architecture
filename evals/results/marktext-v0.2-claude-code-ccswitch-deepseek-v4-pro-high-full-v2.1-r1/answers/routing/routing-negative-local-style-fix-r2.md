找到的局部样式改动点在 `packages/desktop/src/renderer/src/pages/preference.vue:72`。

## 现状

这是 `preference.vue` 里唯一的背景颜色声明，位于 `.pref-container` 规则中：

```css
.pref-container {
  ...
  background: var(--editorBgColor);   /* 第 72 行 */
  ...
}
```

它引用的是编辑器背景变量 `--editorBgColor`，在主题里是中性的灰/白（默认浅色主题为 `#ffffff`，`dark` 主题为 `#282828`），没有蓝色倾向。

## 改动

把这一行改成主题的蓝色强调变量：

```css
background: var(--themeColor);
```

`--themeColor` 是主题系统里的蓝色主色变量（`dark` 主题下是 `#409eff`，`packages/desktop/src/renderer/src/assets/themes/dark.theme.css:3`），相比中性的 `--editorBgColor` 更蓝，因此符合“更蓝的主题变量”这个目标。

## 一处需要说明的事实

这个改动只对深色主题成立。默认浅色主题（`packages/desktop/src/renderer/src/assets/styles/index.css:8`）里 `--themeColor` 是绿色 `rgba(33, 181, 111, 1)`（`#21B56F`），所以若要求浅色模式下也“更蓝”，并没有现成的蓝色背景变量；那时需要改用 `--themeColor10`（蓝色 10% 透明）之类的浅蓝 tint，而不是直接套 `--themeColor`。

只做说明，未修改任何文件。
