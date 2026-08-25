定位完成。下面是这一处局部样式改动的说明，未修改任何文件。

## 改动位置

`packages/desktop/src/renderer/src/pages/preference.vue:72`，在文件末尾未加 `scoped` 的 `<style>` 块里，`.pref-container` 规则中的唯一一条背景声明：

```css
.pref-container {
  ...
  background: var(--editorBgColor);   /* 第 72 行 */
}
```

这确实是整个 `preference.vue` 里唯一的一处背景颜色（全文件只有这一个 `background` 声明）。

## 这行现在做什么

`.pref-container` 是偏好设置窗口的根容器，`position: fixed` 且宽高为 `100vw/100vh`，所以 `background: var(--editorBgColor)` 决定的是整个偏好设置窗口铺满视口的底色——默认浅色主题下是白色，深色主题下是深蓝灰（如 one-dark 的 `#282c34`）。

## 要做的改动

把这一行的 `var(--editorBgColor)` 换成一个更偏蓝的主题变量（例如主题系统中侧边栏/标题栏使用的背景 token `var(--sideBarBgColor)`）。改动范围只限这一行、这一个属性值，不影响 `.pref-container` 的尺寸、定位、flex 布局，也不涉及模板、脚本或其它组件。

一句话概括：**仅把偏好设置窗口根容器的背景从「编辑器背景色」切换为更偏蓝的主题背景变量，改动局限于 `preference.vue:72` 这一条声明。**
