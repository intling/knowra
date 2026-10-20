## Why

knowra 的核心价值是"基于私有资料、可追溯来源的问答"。当前主界面能用，但既枯燥又不够直接，并且在几个关键点上削弱了这一价值：

- **资料 → 提问 → 核对来源 这条主线看不出来**。欢迎页只有一个 Logo 和一句标语，没有上传入口，也没有可操作的提问建议；上传只藏在输入框里的回形针图标里。
- **来源难找**。引用来源只能在默认折叠的"检索结果"调试面板里找到，和查询改写、提示词这些技术信息混在一起，用户很难快速核对回答依据。
- **排版基础设施失效**。
  - 浏览器实测：AI 回答中的 `ol` / `ul` 的 `list-style-type` 都是 `none`。原因是没有安装 typography 插件，`prose` 类不生效，而 Tailwind 预设样式清空了列表样式。
  - `font-display` / `font-mono` 字体令牌按 Tailwind v4 规则命名有误（写成了 `--font-family-*`），所以从未生效。
  - 页面依赖 Google Fonts 外链（Inter / Newsreader），离线或受限网络下会回退到不可控字体，中文没有任何字体回退。
- **视觉单调**。冷灰配学术蓝，所有内容都套同一种白卡片；回答下方四个面板层级一样，看不出哪个重要。
- **移动端不可用**。
  - 390px 视口下输入框文本区只有约 164px 宽。
  - 浮动的菜单按钮压住了顶栏标题。
  - 侧边栏关闭后，里面不可见的按钮仍能被键盘 Tab 到；选择对话后侧边栏也不会自动收起。
- **已有规范尚未落地**。`frontend-redesign` 要求的几项行为还没做：删除对话的二次确认、侧边栏"知识库"分区、欢迎页推荐问题。

## What Changes

本次变更对前端进行一次完整的视觉与交互重构。设计方向是**"书房批注本"**：暖纸色底、墨色正文、松烟青强调色、朱砂色来源编号、中文衬线标题配人文无衬线正文。详见 `design.md`。

- **设计系统重建（`style.css`）**
  - 语义化色彩令牌：`paper` / `surface` / `ink` / `line` / `brand`（松烟青）/ `cite`（朱砂）。`brand-*` 与 `neutral-*` 色阶就地重绘为松烟青和暖灰，现有类名保持可用。
  - 字体令牌改用 Tailwind v4 命名空间（`--font-display` / `--font-sans` / `--font-mono`），只使用本地字体栈并给出中文回退。
  - 移除 Google Fonts 外链。
  - `prose-knowra` 恢复列表标记、表格边框、引用块和代码块样式。
  - 全局支持 `prefers-reduced-motion`，并统一焦点环样式。
- **应用壳**
  - 侧边栏改为暖纸色"书脊"，从上到下依次为：字标、新对话、资料库、最近对话、用户。
  - 移动端菜单按钮并入顶栏流式布局，不再浮动遮挡标题。
  - 抽屉关闭时设为 `inert`，键盘无法 Tab 进去。
  - Esc 关闭抽屉，焦点回到菜单按钮。
  - 选择对话或新建对话后自动收起抽屉。
- **欢迎页**
  - 用"① 上传资料 → ② 提问 → ③ 核对来源"三步路径代替装饰性 Logo；"上传资料"是真实按钮，复用输入框的上传流程。
  - 提供 3 个通用推荐问题。**点击只填入输入框并聚焦，不直接发送**，由用户确认后再发送（理由见 `design.md` D4）。
- **问答流**
  - 用户提问保留右对齐气泡，并保留换行。
  - 回答不再套"AI 回答"卡片，改为"书页正文"排版：左侧"知"字印章，右侧正文列。
  - 回答下方紧跟**来源列表**（`SourceList`）：
    - 按文档聚合，显示编号、文档名、页码和分块编号，以及首个片段的预览。
    - 展开后显示原始分块全文。
    - 没有检索到片段时，明确提示"本回答没有资料依据"。
  - 查询改写、检索结果（含分数）、提示词预览统一收进默认折叠的**"检索详情"**。
  - 回答底栏只保留复制、引用统计和 Token 总数，Token 明细放在悬停提示里。
  - 等待阶段在回答位置显示"正在检索资料…" / "正在生成回答…"，并通过 `aria-live` 播报。
- **输入框**
  - 文本框独占整行；下方工具栏依次为：附件、检索设置（显示“检索 N 段”，Top-K 留在弹层中）、按键提示、圆形发送按钮。
  - 设置弹层支持 Esc 关闭并把焦点还给触发按钮。
- **侧边栏**
  - "资料库"分区：只读调用 `GET /api/parsed-documents`，显示已解析资料数量，提供加载、空、错误（可重试）状态，以及流程验证入口。
  - "最近对话"标题放在列表和空状态之前。
  - 对话条目主体改为原生按钮，支持键盘操作和 `aria-current`。
  - 操作按钮在当前对话、悬停和键盘聚焦时可见。
  - 删除对话前弹出可访问的二次确认框：`role="dialog"`，Esc 取消，打开后焦点落在"取消"上。
- **分数条**：按相似度（1 − 余弦距离，限制在 0–1）计算，最不相似的结果不再显示为空条。
- **`/verify` 页**：沿用新的令牌、字标和顶栏风格，业务逻辑与 testid 不变。
- **其他**：保留已有的 favicon，更新页面标题。
- **不涉及**：后端 API、上传流水线、数据模型、localStorage 结构、运行时依赖。

## Capabilities

### New Capabilities

（无）

### Modified Capabilities

- `frontend-redesign`
  - 视觉需求改为用语义令牌描述，不再写死具体类名。
  - 移动端抽屉补充键盘与焦点行为。
  - 知识库分区改为基于已解析文档。
  - 对话历史补充可访问的删除确认。
  - 欢迎页改为三步路径加推荐问题（填入，不直接发送）。
  - 用户消息保留换行。
  - 输入框中 Top-K 移入设置弹层。
  - 加载文案移到回答占位区。
- `chat-recall-ui`
  - 回答下方新增来源列表；调试面板收纳进"检索详情"。
  - 回答底栏统计改为总数加悬停明细。
  - 分数条按相似度计算。
  - 回答 Markdown 排版契约（列表、表格、代码块）。
  - 修正按键描述：Enter 发送，Shift / Ctrl / Cmd + Enter 换行，中文输入法组字时不发送。
  - 明确分数分布图展示原始余弦距离，位于默认折叠的检索详情内。

## Impact

- **受影响工作流**
  - 资料接入：欢迎页和输入框都提供上传入口，侧边栏显示已解析资料数量。
  - 提问：推荐问题、设置弹层、按键提示。
  - 回答与来源核对：来源列表直接可见，诊断信息收纳。
  - 对话管理：重命名、删除确认、移动端抽屉。
- **前端代码**
  - 改动：
    - 根与样式：`front/index.html`、`front/src/style.css`。
    - 布局：`components/layout/ChatArea.vue`、`ChatLayout.vue`。
    - 对话组件：`components/chat/ChatTopNav.vue`、`WelcomeView.vue`、`UserMessage.vue`。
    - 回答与检索面板：`components/AnswerPanel.vue`、`ResultsPanel.vue`、`PromptPreview.vue`、`RewritePanel.vue`。
    - 输入：`ChatInput.vue`。
    - 侧边栏与共享组件：`components/sidebar/*`、`components/shared/ConfirmDialog.vue`、`PanelSection.vue`。
    - 页面：`views/VerificationView.vue`。
  - 新增：`components/chat/SourceList.vue`、`components/chat/RetrievalDetails.vue`、`components/sidebar/KnowledgeInfo.vue`。
- **测试**
  - 新增：
    - 组件：`SourceList`、`RetrievalDetails`、`KnowledgeInfo`、`ConfirmDialog` 键盘行为。
    - 页面与布局：`ChatArea` 集成、`ChatLayout` 导航与键盘。
    - 样式：用真实 Tailwind 编译器检查编译后的 CSS 契约。
  - 补充：`ChatInput`、`sidebar`、`AnswerPanel`、`ResultsPanel`、`UserMessage` 用例。
  - 已废弃但保留的 `ChatView` 测试必须继续通过。
- **API**：只读复用现有 `GET /api/parsed-documents` 和 `POST /api/search`、`POST /api/uploads`。没有契约变更，没有后端改动。
- **依赖**：不新增运行时依赖；不引入 `@tailwindcss/typography`，也不引入任何字体包。样式契约测试直接使用的 `lightningcss` 原本已是 `@tailwindcss/vite` 的间接依赖，现在显式声明为 devDependency，避免依赖 hoisting。
- **文档**：同步根目录 `README.md`、`front/README.md` 的使用流程及 `front/AGENTS.md` 的 UI 规范；更新两份主规范，并保存可复现的浏览器验收脚本、夹具、截图和检查输出。
- **验收信号**
  - `npm run lint` / `npm run test` / `npm run build` 全部通过。
  - 用 Playwright 加 mock API 在浏览器中检查：
    - 1440×1000 桌面层级清晰。
    - 390×844 下输入框文本区 ≥ 300px，菜单与标题不重叠。
    - 320px 下文档没有横向溢出。
    - 回答中 `ul` / `ol` 的 `list-style-type` 分别为 `disc` / `decimal`。
    - "检索详情"默认折叠，删除对话出现确认框。
    - 开启 reduced-motion 时没有非必要动画。
  - 验收结果记录在 `acceptance-report.md`。
- **回滚**：纯前端改动，revert 本次提交即可。没有数据迁移；localStorage 中的 `knowra:chat` 结构不变。
