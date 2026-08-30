目标局部样式位于 [`preference.vue:72`](/evaluation-path/treatment/packages/desktop/src/renderer/src/pages/preference.vue:72)：

```diff
- background: var(--editorBgColor);
+ background: var(--themeColor);
```

即仅将 `.pref-container` 的背景变量改为主题主色 `--themeColor`，不修改文件。
