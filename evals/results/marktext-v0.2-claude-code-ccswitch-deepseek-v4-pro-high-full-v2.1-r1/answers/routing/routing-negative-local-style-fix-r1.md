`preference.vue` 里唯一的局部背景色在非 scoped 的 `<style>` 块中，即 `.pref-container` 规则里的这一条（第 72 行）：

```css
background: var(--editorBgColor);
```

这就是要改的那一处局部样式。当前用的是 `--editorBgColor`——主题的中性编辑器底色（默认 dark 主题里是 `#282828`，light 主题里是白色），不是蓝色。

改成更蓝的主题变量，最直接的是换成主题强调色变量 `--themeColor`：

```css
background: var(--themeColor);
```

依据（可核实）：
- `packages/desktop/src/renderer/src/assets/themes/dark.theme.css:3` 定义 `--themeColor: #409eff`，即蓝色，这是主题里最“蓝”的可用变量。
- 同文件里 `--editorBgColor: #282828`（第 24 行）是中性灰，`--themeColor` 相比它明显更蓝。

一个需要说明的边界：`--themeColor` 是跟随用户主题强调色的，并不在所有主题下都是蓝的——默认 light 主题在 `assets/styles/index.css:8` 把它定义为绿色 `rgba(33, 181, 111, 1)`。所以“更蓝”这个描述在 dark / 蓝色强调主题下成立；如果要求无论主题如何都保持蓝色，主题变量体系里并没有一个专门的蓝色背景变量，蓝色只出现在强调色（`--themeColor`）以及 dark 主题里硬编码的 `--linkColor: #409eff`、`--emColor: #66b1ff` 等少数几处。

总结：改动范围只有 `preference.vue:72` 的 `background` 声明，从 `var(--editorBgColor)` 换为 `var(--themeColor)`，其余不动。
