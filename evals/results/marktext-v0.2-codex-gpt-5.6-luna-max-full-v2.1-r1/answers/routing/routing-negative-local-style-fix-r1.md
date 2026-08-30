仅需改动 [preference.vue:72](/evaluation-path/treatment/packages/desktop/src/renderer/src/pages/preference.vue:72)：

```diff
- background: var(--editorBgColor);
+ background: var(--themeColor);
```

即将 `.pref-container` 的背景切换为更偏蓝的主题主色变量；不涉及其他代码或样式，文件未修改。
