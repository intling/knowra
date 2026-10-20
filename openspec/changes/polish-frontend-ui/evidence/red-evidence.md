# RED 证据：polish-frontend-ui（书房批注本重构）

模型：dtmaas / claude-opus-5-5。工作目录：`/root/project/knowra/front`。

## 基线（主控已确认）

在写 RED 之前，主控在未改动任何生产代码的状态下运行了 `npm run test`、`npm run lint`、`npm run build`：test 结果为 345 个用例全部通过，lint 和 build 也都通过。

## RED 第一轮（阶段一，只改测试）

命令：`npx vitest run`。主控独立复跑的[完整输出](codex-red-run.txt)。

```
Test Files  12 failed | 24 passed (36)
     Tests  66 failed | 359 passed (425)
```

- 原有 345 个用例全部仍然通过。
- 新增用例中有 7 个当时就通过，作为回归守护：
  - ChatArea 的 6 个：上传成功、上传失败、请求错误、多轮请求带 history 和 session_id、Top-K 生效、空输入不能发送。
  - "有对话时标题位于条目之前"：现有实现本来就满足。
- `SourceList`、`RetrievalDetails`、`KnowledgeInfo` 三个测试文件因为组件不存在，报 `Failed to resolve import "../X.vue"`。这是功能缺失导致的预期失败。
- 主要失败原因（实际断言输出）如下：

| 测试文件 | 实际失败原因（节选） | 对应的缺失功能 |
|---|---|---|
| style-contract | `expected '' to contain 'font-family: var(--font-display)'`；`编译产物中未定义 --font-display`；`.prose-knowra ol` 声明中没有 `list-style-type: decimal`；没有找到 `prefers-reduced-motion` 规则；`仍引用外网字体：https://fonts.googleapis.com…` | 字体令牌命名错误、列表样式被清空、不支持减少动画、依赖外网字体 |
| AnswerPanel | 缺少 `token-total`；`expected '' to contain '500'`（`title` 中没有明细）；`[prose, prose-sm, prose-knowra] to not include 'prose'` | Token 只显示总数，明细放 `title`；去掉无效的 `prose` 类 |
| ResultsPanel | 缺少 `result-score-bar` | 分数条按相似度计算 |
| ChatInput | `expected '' to contain '12'`；`expected undefined to be 'dialog'`；按 Esc 后弹层仍在；`vm.focus is not a function`；缺少工具栏 | 设置按钮显示 Top-K、弹层键盘操作、暴露 focus、上下两行布局 |
| Welcome / UserMessage | `welcome-step` 为 0 个；没有 `welcome-upload`；推荐问题为 0 条；`[...] to include 'whitespace-pre-wrap'` | 三步路径、上传入口、推荐问题、保留换行 |
| ChatArea | 没有推荐问题和上传按钮；没有 `answer-pending`；没有 `source-list` 和 `retrieval-details-toggle`；`'引用 2 个分块 · 来自 3 个文档' to contain '来自 1 个文档'` | 欢迎页交互、等待占位、来源列表、诊断收纳、按引用文档去重计数 |
| ChatLayout-nav | 菜单按钮不在 `chat-top-nav` 内；`inert` 为 `undefined`；`aria-expanded` 为 `undefined`；没有关闭按钮；选择或新建对话后抽屉不收起 | 抽屉的可访问性和自动收起 |
| ConfirmDialog | 没有 `role="dialog"`；焦点没有落在取消按钮；按 Esc 没有 emit | 确认框的可访问性 |
| sidebar | 没有 `knowledge-info`；没有"知寻"；`最近对话` 排在 `暂无对话` 之后（`expected 5 to be less than 0`）；没有 `conversation-select`；按 Esc 时实际已调用 `deleteConversation`，说明点击删除就直接删除了 | 资料库分区、字标、标题顺序、删除二次确认 |

## RED 第二轮（落实主控 review-notes 后，阶段二开始前）

### 新增和调整的测试

**用词修正**：`GET /api/parsed-documents` 只能说明文档已解析，不能说明已建好索引、可以检索。因此相关测试的用词从"N 份资料可检索"改为"N 份已解析资料"，空状态改为"还没有已解析的资料"。

**新增用例**：

| 测试文件 | 新增用例 |
|---|---|
| ChatLayout-nav | 在抽屉中选择当前对话也会收起 |
| ChatLayout-nav | 抽屉打开时 Tab / Shift+Tab 在抽屉内循环 |
| ChatLayout-nav | 移动端只请求一次已解析文档接口 |
| ChatLayout-nav | 桌面端只请求一次已解析文档接口，且不渲染移动抽屉 |
| ConfirmDialog | Tab 与 Shift+Tab 焦点在对话框内循环 |
| ConfirmDialog | 两个实例的 `aria-labelledby` 互不相同 |
| sidebar | 取消删除后焦点回到删除按钮 |
| SourceList | 多个实例中同一文档的 `aria-controls` ID 唯一 |
| SourceList | 展开的原文与 API 返回的文本完全一致 |
| SourceList | 展开后显示每个片段的原始排名 |
| RetrievalDetails | 两个实例的 `aria-controls` 互不相同 |
| RetrievalDetails | 展开提示词面板后不存在 button 嵌套 button |

**测试清理**：sidebar 中挂载到 body 的 wrapper 改为在 `afterEach` 里显式 `unmount()`，避免全局监听器在测试之间泄漏。

### 最小空组件

按 brief 要求，先建立可加载的最小空组件 `SourceList.vue`、`RetrievalDetails.vue`、`KnowledgeInfo.vue`，内容只有 `<template><div /></template>`。这样相关测试会走到具体的行为断言，而不是停在 import 失败。

### 运行结果

命令：`npx vitest run`。[完整输出与失败用例](red-run-phase2.txt)。

```
Test Files  12 failed | 24 passed (36)
     Tests  104 failed | 359 passed (463)
```

失败原因节选：

- SourceList：`expected [] to have a length of 2 but got +0`；`sources-empty` 不存在；找不到 `source-toggle`。
- RetrievalDetails：找不到 `retrieval-details-toggle`。
- KnowledgeInfo：`expected "vi.fn()" to be called 1 times, but got 0 times`；找不到 `knowledge-loading`。
- ChatLayout-nav：
  - "移动端只请求一次"失败：`called 1 times, but got 0 times`，因为空组件不请求接口。
  - "Tab 循环"失败：焦点从抽屉最后一项逃逸到了 `sidebar-user-info`（`role="button"` 的 div）。
  - "选择当前对话也收起"失败：找不到 `conversation-select`。
- ConfirmDialog：焦点循环失败，Tab 后焦点仍停在确认按钮上，没有回到取消按钮；`[role=dialog]` 不存在，所以拿不到 `aria-labelledby`。
- sidebar：确认框不存在，`querySelector` 返回 `null`，无法点击取消，焦点回归断言无法执行。

所有失败都对应设计中的缺失行为，没有拼写错误或测试环境错误。原有 345 个用例仍然全部通过。

## RED 第三轮：主控验收反馈

### 回归测试

[完整输出](red-run-acceptance.txt)。

```
Tests  7 failed | 89 passed (96)
```

| 失败用例 | 实际失败原因 |
|---|---|
| 抽屉内确认框按 Esc 只关闭确认框 | `取消删除后抽屉应保持打开: expected 'true' to be undefined` |
| 抽屉内确认框打开时 Tab 焦点留在确认框内 | 焦点被抽屉的焦点循环带走 |
| 发送追问后最新一轮问答被滚入视野 | `expected "vi.fn()" to be called at least once` |
| 回答返回时不再额外滚动 | `expected 0 to be greater than 0`，即发送后没有发生任何滚动 |
| 纸面氛围 | `expected '' to contain 'radial-gradient'` |
| 输入法组字中的 Enter 不发送 | `expected [ [], [] ] to be undefined`，两次组字 Enter 都触发了 send |
| 设置按钮显示「检索 N 段」 | `expected 'Top-K 5' to contain '检索 5 段'` |

### 修复中发现的连带问题：测试监听器泄漏

`ConfirmDialog` 改为在捕获阶段 `stopImmediatePropagation` 之后，`ConfirmDialog.spec.ts` 中 2 个用例失败。原因是该文件里较早的用例挂载了可见的对话框却没有卸载，它们的全局监听器先拦截了事件。处理方式：在该文件启用 `enableAutoUnmount(afterEach)`，测试断言不变。

### 修复中发现的连带问题：真实浏览器中 Tab 无法从「取消」移到「删除」

jsdom 中合成的 Tab 事件不会触发原生的焦点移动，所以单测发现不了这个问题；我自己的真实 Chromium 自检发现了它。原因是对非边界位置也调用了 `preventDefault`，挡住了原生 Tab。修复：只在边界处循环焦点，其余交给浏览器原生 Tab。修复后实测焦点顺序为：确认 → 取消 → 确认 → 取消（最后一步是 Shift+Tab）。

### scrollIntoView 连带滚动外层应用壳

现象：`scrollIntoView` 会同时滚动 `overflow-hidden` 的祖先元素，滚动后视口顶部变为 −466，顶栏被移出屏幕（我的自检和主控浏览器检查都复现了，修复后的结果见 [输入与滚动验收](codex-browser-composer.txt)）。

新增断言：`scrollIntoView` 不得被调用，并且 `scrollTo` 的调用目标必须是 `chat-scroll` 容器。

用 scrollIntoView 版本的实现运行，确认 RED（[完整输出](red-run-scroll-container.txt)）：

```
发送追问后消息容器滚动到最新一轮问答  AssertionError: expected "vi.fn()" to be called at least once
回答返回时不再额外滚动                AssertionError: expected 0 to be greater than 0
Tests  2 failed | 14 passed (16)
```

恢复为容器 `scrollTo` 实现后：`Tests 16 passed (16)`。

### 真实 Chromium 复核

使用主控的脚本，未做任何修改：

- `node accept-composer.mjs`：PASS，覆盖场景 new-turn-visible、preserve-reading-position、ime-enter、normal-motion-shell-stable；第三轮时 `viewportTop` 为 52。
- `node accept-mobile.mjs`：PASS。
