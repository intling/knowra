## 1. 契约与 RED 测试（阶段一，已完成）

- [x] 1.1 补齐 OpenSpec：`proposal.md` 扩展、`design.md`、`specs/frontend-redesign/spec.md`、`specs/chat-recall-ui/spec.md`。
- [x] 1.2 新增测试夹具 `front/src/__tests__/fixtures/search.ts`，完整镜像 `SearchResponse`、`SearchResultItem`、`ParsedDocument`。
- [x] 1.3 样式契约 RED：`front/src/__tests__/style-contract.test.ts`，用真实 Tailwind 编译器编译产物，覆盖以下内容：
  - 字体令牌、中文回退、禁止 Inter / Roboto / Arial。
  - 语义色彩令牌。
  - `prose-knowra` 的列表、表格、代码块。
  - reduced-motion。
  - 不依赖外网字体。
- [x] 1.4 组件 RED：
  - `SourceList.spec.ts`、`RetrievalDetails.spec.ts`、`KnowledgeInfo.spec.ts`、`AnswerPanel.spec.ts`、`ResultsPanel.spec.ts`。
  - `ConfirmDialog.spec.ts`（新增可访问性用例组）。
  - `ChatInput-attachment.spec.ts`（新增重构交互用例组）。
  - `welcome-user-message.spec.ts`（起手路径、排版契约）。
  - `sidebar.spec.ts`（资料库分区、标题顺序、删除确认）。
- [x] 1.5 集成 RED：
  - `ChatArea.spec.ts`：欢迎页交互、问答流，并附带 6 条回归守护。
  - `ChatLayout-nav.spec.ts`：移动端抽屉、键盘、焦点、自动收起。
- [x] 1.6 运行 RED 并记录到 [RED 证据](evidence/red-evidence.md)。
  - 结果：66 个失败、3 个模块缺失、359 个通过（其中原有 345 个全部通过）。主控评审后回复"继续"。
- [x] 1.7 落实 review-notes：改为"已解析"用词；新增焦点循环、选择当前对话也关闭抽屉、只请求一次接口、ID 唯一、不嵌套按钮、原文保真等用例。先建最小空组件，确认行为断言 RED（104 失败 / 359 通过），记录在 red-evidence.md。

## 2. 设计系统（GREEN：style-contract）

- [x] 2.1 `front/src/style.css`：
  - 改用 `--font-display` / `--font-sans` / `--font-mono` 命名空间和本地字体栈。
  - 新增语义令牌 `paper`、`paper-deep`、`surface`、`ink`、`ink-muted`、`ink-faint`、`line`、`cite`；`brand-*` 重绘为松烟青，`neutral-*` 重绘为暖灰。
- [x] 2.2 `prose-knowra` 补齐以下规则：
  - `ul` 为 disc、`ol` 为 decimal，并设置左内边距。
  - 表格设置单元格下边框和 `overflow-x: auto`。
  - `pre`、`blockquote`、`hr`。
- [x] 2.3 全局添加 `prefers-reduced-motion` 规则，并设置 `:focus-visible` 焦点环颜色。
- [x] 2.4 `front/index.html`：移除 Google Fonts 的 `preconnect` 和 `link`；`<title>` 改为"知寻 knowra"。
- [x] 2.5 验证：`npx vitest run src/__tests__/style-contract.test.ts` 全部通过。

## 3. 回答、来源与诊断（GREEN：SourceList / RetrievalDetails / AnswerPanel / ResultsPanel）

- [x] 3.1 新增 `components/chat/SourceList.vue`：
  - 按 `parsed_document_id` 聚合并编号。
  - 页码去重排序，显示分块编号。
  - 预览 + 展开原文（`aria-expanded` / `aria-controls`，`whitespace-pre-wrap`）。
  - 空结果提示；文档名为空时显示"未命名文档"。
- [x] 3.2 新增 `components/chat/RetrievalDetails.vue`：
  - 原生按钮折叠控件，默认收起，摘要显示"N 个片段 · T ms"。
  - 按条件渲染 Rewrite / Results / Prompt 三个子面板。
- [x] 3.3 `AnswerPanel.vue`：
  - 去掉卡片外壳，改为印章 + 正文列，只保留 `prose-knowra`。
  - Token 底栏只显示总数（`token-total`），明细放在 `title` 和 `sr-only` 中。
- [x] 3.4 `ResultsPanel.vue`：单条结果的分数条宽度为 `clamp(1 - score, 0, 1)`，加 `data-testid="result-score-bar"`，并显示相似度（`title` 中保留余弦距离）。分布柱状图保留原始余弦距离，标签为"分数分布（余弦距离，越小越相似）"。
- [x] 3.5 `PanelSection.vue` 新增 `variant="flat"`，用于诊断区内的平铺子面板；`RewritePanel` 去掉 emoji。
- [x] 3.6 验证：`npx vitest run src/components/chat src/components/__tests__ src/__tests__/components src/views` 全部通过，其中旧版 `ChatView.spec.ts` 必须保持通过。

## 4. 输入框与欢迎页（GREEN：ChatInput / WelcomeView / UserMessage）

- [x] 4.1 `ChatInput.vue`：
  - 文本框独占一行，下方是工具栏 `chat-input-toolbar`。
  - 设置按钮显示"检索 N 段"（主工具栏不出现 Top-K 术语，弹层标签为"检索片段数（Top-K）"）；弹层设置 `role="dialog"` 和 `aria-label="检索设置"`，Esc 关闭并归还焦点。
  - 输入法组字中（`isComposing` 或 keyCode 229）按 Enter 不发送。
  - 发送按钮为圆形图标按钮，用 `sr-only` 提供阶段文本。
  - `defineExpose({ focus })`。
- [x] 4.2 `WelcomeView.vue`：
  - 三步路径 `welcome-step`。
  - 上传按钮 `welcome-upload` emit `upload`。
  - 至少 3 条推荐问题 `welcome-suggestion`，emit `pick-suggestion`。
- [x] 4.3 `UserMessage.vue`：添加 `whitespace-pre-wrap` 和 `[overflow-wrap:anywhere]`。
- [x] 4.4 验证：`npx vitest run src/components/__tests__/ChatInput-attachment.spec.ts src/components/chat` 全部通过。

## 5. 对话区编排（GREEN：ChatArea）

- [x] 5.1 `ChatArea.vue`：
  - 等待占位 `answer-pending`：`role="status"`，`aria-live="polite"`，文案为"正在检索资料…"或"正在生成回答…"。
  - 在 AnswerPanel 之后依次渲染 SourceList 和 RetrievalDetails。
  - 引用文档数改为对结果的 `parsed_document_id` 去重计数。
  - 接线 `upload` 到 `handleAddFiles`，接线 `pick-suggestion` 到"写入 query 并调用 `chatInputRef.focus()`"。
  - 内容列宽度改为 760px；主对话区使用 `paper-atmosphere`。
  - 主动发送后，只对消息容器 `chat-scroll` 调用 `scrollTo` 滚到最新一轮问答；不使用 `scrollIntoView`；异步回答返回时不滚动。
- [x] 5.2 验证：`npx vitest run src/components/layout/__tests__/ChatArea.spec.ts` 全部通过（含 6 条回归守护）。

## 6. 应用壳与侧边栏（GREEN：ChatLayout / sidebar / ConfirmDialog）

- [x] 6.1 `ChatLayout.vue`：
  - 通过 provide 提供 `mobileNav`。
  - 抽屉在关闭时设置 `inert` 和 `aria-hidden`；打开时设置 `role="dialog"` 和 `aria-modal`，焦点移到"新建对话"。
  - Esc、遮罩、`mobile-sidebar-close` 都能关闭抽屉，关闭后焦点回到菜单按钮。
  - `AppSidebar` 发出 `navigate` 事件（新建或选择对话，包括选择当前对话）时自动收起抽屉；不使用对 `activeConversationId` 的监听。
  - 桌面侧边栏和移动抽屉互斥挂载，打开抽屉时背景主区域设为 `inert`。
- [x] 6.2 `ChatTopNav.vue`：通过 inject 在标题左侧渲染 `hamburger-menu`（用 `v-show` 控制显示，保持现有可见性测试），并设置 `aria-expanded` 和 `aria-controls`。
- [x] 6.3 新增 `components/sidebar/KnowledgeInfo.vue`：
  - 加载、数量、空、错误加重试四种状态；提供 `/verify` 链接。
  - 使用惰性 logger `components:KnowledgeInfo`。
- [x] 6.4 `AppSidebar.vue` / `SidebarHeader.vue`：添加"知寻"字标，在"新建对话"之后插入 KnowledgeInfo，底色改为 `paper-deep`。
- [x] 6.5 `ConversationList.vue`：标题放在空状态和列表之前。
- [x] 6.6 `ConversationItem.vue`：
  - 主体改为 `conversation-select` 按钮，并设置 `aria-current`。
  - 操作区 `conversation-actions` 设置 `group-focus-within:opacity-100`，补充 `aria-label`。
  - 删除改为 `<Teleport to="body">` 包裹的 `ConfirmDialog` 确认流程。
- [x] 6.7 `ConfirmDialog.vue`：
  - 设置 `role="dialog"`、`aria-modal`、`aria-labelledby`（ID 由 `uniqueId()` 生成）。
  - 打开时聚焦"取消"。在捕获阶段处理 Esc 和 Tab 并调用 `stopImmediatePropagation`，只关闭最上层。Tab 只在边界处循环，中间位置交给浏览器原生 Tab。
- [x] 6.8 `SidebarUser.vue`：移除用户信息上的 `role="button"` 和 `tabindex`。
- [x] 6.9 验证：`npx vitest run src/components/layout src/components/sidebar src/components/shared` 全部通过，其中原有 `ChatLayout.spec.ts` 必须保持通过。

## 7. `/verify` 页视觉统一

- [x] 7.1 `VerificationView.vue`：
  - 顶栏使用"知寻 knowra"字标和面包屑，底色改为 `paper`、`surface`，描边改为 `line`。
  - 保留所有 testid，以及 `rounded-lg`、`shadow-sm`、`bg-brand-700`、`hover:bg-brand-800`、`disabled:bg-neutral-200`。
- [x] 7.2 验证：`npx vitest run src/views` 全部通过。

## 8. 重构、文档与全量验证

- [x] 8.1 REFACTOR：清理重复的图标 SVG 和过时注释（例如"精密仪器"、"学术蓝"），保持测试全绿。
- [x] 8.2 `front/README.md` 新增"主界面"一节，说明三步路径、来源列表、检索详情、移动端抽屉。
- [x] 8.2b 同步根目录 `README.md`（主界面使用流程）和 `front/AGENTS.md`（UI 规范要点）。
- [x] 8.3 在 `front/` 下依次运行 `npm run lint`、`npm run test`、`npm run build`，全部通过，并记录实际输出。实际输出见 `evidence/codex-lint.txt`、`evidence/codex-test.txt`、`evidence/codex-build.txt`。
- [x] 8.4 Playwright 加 mock `/api/*` 浏览器验收（由主控执行），检查项：
  - 1440×1000 桌面截图。
  - 390×844：输入框文本区 ≥ 300px，菜单与标题的边界框不相交，发送按钮完整可见。
  - 320px：`document.documentElement.scrollWidth ≤ clientWidth`。
  - 回答中 `ul` / `ol` 的 computed `list-style-type` 分别为 `disc` / `decimal`。
  - "检索详情"默认折叠，删除对话出现确认框，抽屉关闭后 Tab 不进入抽屉。
  - 开启 reduced-motion 时，computed `transition-duration` 接近 0。
  - 截图覆盖：桌面、移动、对话、设置弹层、验证页。
- [x] 8.5 运行 `openspec validate polish-frontend-ui --strict` 通过；在 `acceptance-report.md` 中记录验收结论，截图和独立验证日志保存在 `screenshots/` 与 `evidence/`。

## 9. 主控验收反馈修复（RED → GREEN）

- [x] 9.1 抽屉内删除确认：Esc 只关闭确认框，抽屉保持打开，焦点回到删除按钮；第二次 Esc 才关闭抽屉；确认框打开时 Tab 不被抽屉抢走。用真实 `ChatLayout` 加真实 `ConfirmDialog` 的集成用例先确认 RED，再修复。
- [x] 9.2 发送追问后，新一轮问答进入视野，回答返回时不滚动；只滚动消息容器，不使用 `scrollIntoView`。先用单测确认 RED，再用真实 Chromium 在 390px 和 320px 下测量。
- [x] 9.3 输入法组字中的 Enter 不发送，非组字的 Enter 正常发送。
- [x] 9.4 主工具栏改用直白文案"检索 N 段"。
- [x] 9.5 纸面氛围 `paper-atmosphere`：先补样式契约测试确认 RED，再实现。
- [x] 9.6 `ConfirmDialog.spec.ts` 启用 `enableAutoUnmount`，避免已打开对话框的全局键盘监听泄漏到后续用例。

## 10. OpenSpec 同步与交付

- [x] 10.1 核对 proposal、design 与实际实现，统一“检索 N 段”、Enter / Shift / Ctrl / Cmd、附件发送条件及分数分布说明。
- [x] 10.2 将两份增量规范同步至 `openspec/specs/frontend-redesign/spec.md` 与 `openspec/specs/chat-recall-ui/spec.md`，保留未受影响的要求。
- [x] 10.3 将浏览器脚本、夹具与复现步骤保存于 `browser/`，支持环境变量配置，消除临时目录和本机缓存路径依赖。
- [x] 10.4 将 RED 与最终验证输出保存为 `evidence/*.txt`，检查报告中的相对链接完整性。
- [x] 10.5 提交前重新执行前端 lint/test/build、四组浏览器验收、变更及两份受影响主规范严格校验和 `git diff --check`，记录实际结果；全库校验中无关的已有缺失见验收报告。
- [x] 10.6 审查暂存范围与验收材料链接，确保仅包含前端重构、相关文档、主规范及本变更，排除临时截图与其他工作区产物。
