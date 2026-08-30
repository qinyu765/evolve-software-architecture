结论：当前 `packages/desktop` 已形成可靠的 Electron 安全边界，但业务边界仍处于迁移中。整体未来扩展性为“中等偏弱”：新增功能可以继续做，但容易同时改动 main、preload、renderer、shared 和测试。建议采用“能力切片 + 逐步收紧合约”，暂不进行全量重写。

本轮只读检查，未修改文件、创建提交或改变外部状态。由于仓库没有 `node_modules`，未执行测试；以下结论来自源码、配置、测试代码和 Git 历史。

## 观察到的事实

| 边界 | 证据 | 判断 |
|---|---|---|
| main | `Accessor` 集中创建 Preference、DataCenter、BufferStore、Menu、WindowManager 等服务；`App` 本身 853 行，并在构造函数中注册大量 IPC。([accessor.ts:12](/evaluation-path/treatment/packages/desktop/src/main/app/accessor.ts:12)、[app/index.ts:38](/evaluation-path/treatment/packages/desktop/src/main/app/index.ts:38)) | 职责完整，但 service locator、构造函数副作用和 App 单体使变更定位困难。 |
| preload | 窗口配置实际为 `contextIsolation: true`、`sandbox: true`、`nodeIntegration: false`。([config.ts:8](/evaluation-path/treatment/packages/desktop/src/main/config.ts:8)) preload 通过 typed bridge 暴露多个 capability。([preload/index.ts:286](/evaluation-path/treatment/packages/desktop/src/preload/index.ts:286)) | 安全 seam 较强，但 API 面较宽，仍暴露多个全局对象和通用 IPC。 |
| renderer | `editor.ts` 约 2102 行，`editor.vue` 约 2133 行；大量直接调用 `window.electron.*`，编辑器组件直接依赖 `@muyajs/core`。([editor.vue:79](/evaluation-path/treatment/packages/desktop/src/renderer/src/components/editorWithTabs/editor.vue:79)) | renderer 同时承担 UI、文档状态、IPC 协议消费和 Muya 适配，业务扩展的变更半径较大。 |
| shared | IPC 被定义为四类 channel map，但源码明确保留大量 `unknown` 作为迁移期占位。([ipc.ts:1](/evaluation-path/treatment/packages/desktop/src/shared/types/ipc.ts:1)) | 目前更像类型目录和迁移脚手架，还不是可靠的运行时协议边界。 |
| common | 文档把 `common` 描述为跨进程可用，但其中 `filesystem` 直接导入 `fs`、`fs-extra` 和 Node `path`。([filesystem/index.ts:1](/evaluation-path/treatment/packages/desktop/src/common/filesystem/index.ts:1)) | `common` 实际混合了纯工具和 main-only Node 工具，目录边界不够精确。 |

## 主要摩擦

1. IPC 合约存在可观察的漂移。

`shared/types/ipc.ts` 声明 `mt::window-active-status` 传递 `boolean`，但 main 实际发送 `{ status: boolean }`；renderer 只能通过类型转换修正。([ipc.ts:282](/evaluation-path/treatment/packages/desktop/src/shared/types/ipc.ts:282)、[editor.ts:237](/evaluation-path/treatment/packages/desktop/src/main/windows/editor.ts:237)、[store/index.ts:25](/evaluation-path/treatment/packages/desktop/src/renderer/src/store/index.ts:25))

菜单事件也类似：shared 声明字符串或空参数，但 main 实际发送对象，renderer 明确写了 boundary cast。([window.ts:38](/evaluation-path/treatment/packages/desktop/src/main/ipc/window.ts:38)、[popupMenu.ts:76](/evaluation-path/treatment/packages/desktop/src/renderer/src/contextMenu/popupMenu.ts:76))

原因是 typed bridge 主要约束 renderer/preload 调用点，main 的 `webContents.send` 没有被同一套类型包装；运行时也没有统一 payload 校验。

2. IPC channel 同时承担跨进程通信和 main 内部事件总线。

`ipcMain.emit` 被用于 watcher、菜单、窗口和偏好设置等内部调用，`onInternalChannel` 还需要类型转换适配。([internalIpc.ts:4](/evaluation-path/treatment/packages/desktop/src/main/utils/internalIpc.ts:4)、[windowManager.ts:112](/evaluation-path/treatment/packages/desktop/src/main/app/windowManager.ts:112))

静态搜索约有 43 处 `ipcMain.emit`、87 处 `webContents.send` 和 108 处 `ipcMain.on/handle`。这不是质量评分，但说明协议与内部调用已经高度分散。

3. renderer 仍然直接依赖宿主细节。

除了直接使用 `window.electron`、`window.fileUtils`、`window.path` 等全局外，偏好设置侧边栏还直接导入 main 目录下的 `schema.json`。([config.ts:11](/evaluation-path/treatment/packages/desktop/src/renderer/src/prefComponents/sideBar/config.ts:11))

这会使 renderer 难以脱离 Electron 运行，也使未来增加第二个宿主、插件宿主或独立测试环境的成本变高。

4. shared 模型混合了 UI 状态和 wire DTO。

`IFileState` 同时包含 `cursor`、`blocks`、通知 action 等开放字段；真正的 buffered state 又在 renderer 里另行裁剪成可序列化结构。([files.ts:62](/evaluation-path/treatment/packages/desktop/src/shared/types/files.ts:62)、[editor.ts:2024](/evaluation-path/treatment/packages/desktop/src/renderer/src/store/editor.ts:2024))

建议明确区分：

- renderer 内部状态；
- 跨进程可序列化 DTO；
- main 内部服务事件。

5. monorepo 的包边界和 CI 边界不完全一致。

desktop 同时依赖旧的 `@marktext/muyajs` 和新的 `@muyajs/core`。([packages/desktop/package.json:62](/evaluation-path/treatment/packages/desktop/package.json:62)) 当前 renderer 已直接消费 `@muyajs/core`，但 desktop 的 unit、E2E、build、lint workflow 都对 `packages/muya/**` 使用 `paths-ignore`。([test.yml:6](/evaluation-path/treatment/.github/workflows/test.yml:6)、[build.yml:6](/evaluation-path/treatment/.github/workflows/build.yml:6))

这意味着 Muya 自身测试通过，并不等于 Electron host 集成通过。

6. 文档存在代际冲突。

root `CLAUDE.md` 前文描述 sandbox 正确，但后面的“三进程模型”仍写着 `contextIsolation: false + nodeIntegration: true`。([CLAUDE.md:81](/evaluation-path/treatment/CLAUDE.md:81)、[CLAUDE.md:241](/evaluation-path/treatment/CLAUDE.md:241))

website architecture 文档仍使用旧的 `src/muya`、JS Muya 和单仓库描述。([ARCHITECTURE.md:12](/evaluation-path/treatment/packages/website/content/docs/dev/ARCHITECTURE.md:12))

## 测试与 Git 历史

优势是测试已经覆盖关键行为：

- E2E 明确验证 contextBridge、sandbox、`require/global/Buffer` 不泄漏。([context-isolation.spec.ts:24](/evaluation-path/treatment/packages/desktop/test/e2e/context-isolation.spec.ts:24))
- unit 测试覆盖 main 菜单、renderer store、文件 watcher、保存 flush 等关键回归。
- 但很多 unit 测试通过 mock Electron、手动构造 `window.electron`，或通过 `main_renderer` alias 直接导入 main 实现。([keybinding-menu-rebuild.spec.ts:21](/evaluation-path/treatment/packages/desktop/test/unit/specs/keybinding-menu-rebuild.spec.ts:21))

Git 历史显示这是一个刚完成多次迁移的系统：

- `fa84fc00`：renderer sandbox 化；
- `ab88a70a`：建立 shared IPC 类型，但明确保留 `unknown`；
- `b9409bc9`：typed preload bridge；
- `565bfcdc`：迁移到 pnpm monorepo；
- `1f3d0010`、`9c5e611b`：为 Muya 迁移补 unit/E2E；
- 近期 `c907b29c`、`ac273f46`、`6c23b1ba` 又持续修复保存、崩溃恢复和原子写入。

因此，当前最合适的方向是稳定新边界、降低变更放大，而不是再做一次大规模架构重写。

## 质量属性优先级

1. 可扩展性与变更局部性：新增一个能力时，应尽量只涉及一个 capability、一个 IPC 合约、一个 renderer facade。
2. 合约完整性与可测试性：main 发送端和 renderer 接收端必须共享同一份可验证协议。
3. 安全与可运维性：保持 sandbox，明确文件、shell、搜索、上传等 capability。
4. 性能：保留必要的 sync boot/path 和 ripgrep streaming，但不要继续扩大同步 IPC 的使用面。

另需审计两个配置点：`webSecurity: false` 当前同时用于 editor 和 preferences window。([config.ts:19](/evaluation-path/treatment/packages/desktop/src/main/config.ts:19)) 在引入远程内容或插件前，应确认其必要性和范围。

## 方案比较

1. 维持现状，只加规范和类型护栏  
   风险最低，可逐步收紧 `unknown`、补 contract test、禁止新增 raw channel；但 main 单体和 renderer 直连仍会存在。

2. 按能力做增量垂直切片——推荐  
   保留现有 Electron 分层，但新增功能统一经过：

   `shared DTO → main capability → preload facade → renderer service/store`

   先迁移“文件打开/保存/重命名/watcher/崩溃恢复”这一条链。它跨越最多边界，且最近 Git 历史已经证明是高风险变化区。旧 channel 作为 adapter 保留，迁移可逐能力回滚。

3. 全量重写 main、preload 和 IPC  
   暂不推荐。当前行为复杂、近期迁移密集，重写会同时放大数据丢失、窗口生命周期和 Muya parity 风险。

## 建议的迁移与验证

1. 先冻结协议规则：新代码不得新增未登记 channel、动态 channel 或裸 `webContents.send`；为 main 增加 typed sender wrapper，并修正现有 menu/status payload 漂移。
2. 将 `shared` 拆成“可序列化 contract”和“main-only runtime support”；`TypedEmitter` 不应继续作为 shared barrel 的潜在 renderer 依赖。([typedEmitter.ts:1](/evaluation-path/treatment/packages/desktop/src/shared/types/typedEmitter.ts:1))
3. 为文件生命周期建立明确的 request/event DTO、错误模型、取消模型和运行时校验；renderer store 只依赖 `documentApi`，不直接散布 IPC channel。
4. 新的 main capability 使用显式依赖注入；逐步停止在构造函数中注册 IPC，也不要再用 `ipcMain.emit` 作为新内部总线。
5. 将 Muya host 适配收窄到 renderer adapter；`@muyajs/core` 当前 workspace export 指向 `src`，desktop 又通过手写 `muya-core.d.ts` 截断类型。([muya-core.d.ts:5](/evaluation-path/treatment/packages/desktop/src/types/muya-core.d.ts:5)、[packages/muya/package.json:10](/evaluation-path/treatment/packages/muya/package.json:10)) 应让 desktop 在 CI 中消费构建后的声明。
6. 为 `packages/muya` 变更增加最小 desktop host smoke，而不是完全依赖独立 Muya CI。
7. 只有在源码搜索、构建、打包和 Electron E2E 都确认无依赖后，再删除旧 `@marktext/muyajs` 和 `muya.d.ts`。
8. 验收标准：选定 capability 不再新增 `unknown`；无新增动态 channel；contract pairing test 通过；sandbox E2E、文件生命周期 E2E 和 Muya host smoke 全部通过；旧 adapter 可独立移除或回滚。

待决策项是：`webSecurity: false` 是否仍必要、是否计划支持远程/插件内容、Muya host smoke 的 CI 触发策略，以及旧 Muya 依赖的正式退出时间表。

[EVAL:evolve-software-architecture-loaded]
