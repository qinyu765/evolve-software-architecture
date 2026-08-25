找到了。这是一个只读说明，我不会改动任何文件。

**要改动的局部样式**

`packages/desktop/src/renderer/src/pages/preference.vue:72`，在 `<style>` 块的 `.pref-container` 规则里：

```css
.pref-container {
  ...
  background: var(--editorBgColor);   /* ← 这一行 */
}
```

这是该文件里唯一的背景色声明（`.title-bar` 等没有局部背景色，只继承）。

**改动内容**

把背景色变量从 `--editorBgColor` 换成主题强调色 `--themeColor`：

```css
background: var(--themeColor);
```

**为什么这样改会「更蓝」**

- `--editorBgColor` 是中性编辑器底色：暗色主题下是 `#282828`（深灰），light/graphite 下是白色/`#f7f7f7`。
- `--themeColor` 是主题强调色簇（`--themeColor` / `--themeColor10` … `--themeColor90`）。在 `dark` 主题里它是 `#409eff`（蓝色，`packages/desktop/src/renderer/src/assets/themes/dark.theme.css:3`），在 oxocarbon、palenight、tokyo-night、catppuccin、cyberdream 等主题里也基本都是蓝色，因此整个偏好设置窗口背景会从灰/白变成蓝色调。

**一个需要注意的点**

`--themeColor` 是主题强调色，不是所有主题都是蓝的：默认 light 主题里它是绿色 `rgba(33, 181, 111, 1)`（`assets/styles/index.css:8`）。所以「更蓝」只在蓝色强调色的主题下成立。如果目标是「淡淡的蓝色底」而不是整片高饱和强调色，更稳妥的改法是换成它的低透明度变体，例如：

```css
background: var(--themeColor10);
```

`--themeColor10` 是同一蓝色主题色的 10% 透明度版本（dark 主题下 `rgba(64, 158, 255, 0.1)`），能在保留主题一致性的同时只给背景加一层轻微蓝调。
