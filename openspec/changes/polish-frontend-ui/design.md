## Context

knowra 前端是 Vue 3、Pinia 和 Tailwind 4 的单页应用，有两条路由：

- `/`：`ChatLayout`，由侧边栏和 `ChatArea` 组成。
- `/verify`：`VerificationView`，流程验证页。

工作区中已有一轮未提交的精修（`PanelSection`、设置弹层、`ChatTopNav` 重命名、favicon），本设计在其基础上继续，不回退。

现状问题已在 `proposal.md` 中说明，这里只补充对设计有约束的事实：

- 一次问答返回一个 `SearchResponse`，包含：
  - `answer`：Markdown 回答。
  - `results[]`：每项带 `rank`、`score`（余弦距离）、`document_name`、`parsed_document_id`、`sequence_index`、`page_numbers`、`heading_path`、`text`。
  - `rewrite_info`、`prompt_messages`、`answer_tokens`、`generation_error`。
- 后端的提示词把分块标为 `[分块 i]`，**但不保证回答正文里有可解析的引用标记**。因此前端**不做**"正文角标 ↔ 来源"的联动；来源编号只在来源列表内部使用。这是有意的范围控制，避免伪造对应关系。
- 上传：`POST /api/uploads` 成功后，由后端决定是否自动解析。前端只展示上传状态，不追踪解析进度（范围外）。
- 已解析文档：`GET /api/parsed-documents` 返回 `ParsedDocument[]`，可用来展示"已解析资料"的数量。
- 对话历史保存在 localStorage 的 `knowra:chat` 中，结构为 `{ conversations: Conversation[], activeConversationId }`。**本设计不改动这个结构。**

## Goals / Non-Goals

**Goals:**

1. 让"上传资料 → 提问 → 核对来源"在首屏一眼可见、可直接操作。
2. 来源紧挨回答展示，不需要展开调试面板；调试信息默认收纳，但随时能找到。
3. 建立统一且有辨识度的视觉语言，不依赖外网字体也能正常阅读中文。
4. 桌面、390px、320px 都可用；键盘可完成全部操作；尊重减少动画偏好。
5. 保留全部现有能力：
   - 上传、搜索、多轮 history / session_id。
   - Top-K 设置、强制替换开关。
   - 重命名、新建、切换、持久化、删除。
   - `/verify` 页的全部状态。

**Non-Goals:**

- 不改后端、API 契约、上传流水线，不在前端轮询解析进度。
- 不做正文引用角标与来源的联动（后端没有提供结构化引用）。
- 不做暗色主题、营销式落地页、资料库管理页（列表、删除、预览原文件）。
- 不新增运行时依赖或字体包；只把测试用的 `lightningcss`（原本是间接依赖）显式声明为 devDependency（见 D11）。

## Decisions

### D1 视觉方向："书房批注本"

knowra 处理的是用户自己的讲义、论文和笔记，回答的价值在于**能对照原文**。所以视觉上借用"读书批注"：纸面是底，正文是墨，来源像页边的朱批编号。这个方向不是只换一个主题色，它同时决定了排版层级和来源的呈现方式。

**色彩**（语义令牌，定义在 `@theme` 中）：

| 令牌 | 值 | 用途 |
|---|---|---|
| `--color-paper` | `#f6f3ec` | 应用底色（暖纸） |
| `--color-paper-deep` | `#efeadf` | 侧边栏、诊断区底色（书脊） |
| `--color-surface` | `#fffdf8` | 输入框、弹层、来源条目 |
| `--color-ink` | `#1f2624` | 正文、标题 |
| `--color-ink-muted` | `#5d625c` | 次要文字 |
| `--color-ink-faint` | `#8d8f87` | 提示、元数据 |
| `--color-line` | `#e2dccf` | 分隔线、描边 |
| `--color-brand-700` | `#1f5a52` | 松烟青，主操作、焦点、用户气泡 |
| `--color-cite` | `#b4452f` | 朱砂，来源编号和"无依据"提示 |

- `brand-50…950` 就地重绘为松烟青色阶，`neutral-50…950` 重绘为暖灰色阶。这样现有的 `bg-brand-700`、`text-neutral-500` 等类名仍然有效，不需要逐个替换。
- 成功、警告、危险三种状态色沿用 emerald / amber / red，只做饱和度微调。
- 对比度目标：正文 `ink` 对 `paper` ≥ 12:1；`ink-faint` 只用于 ≥ 12px 的非关键元数据，对比度 ≥ 3:1；`brand-700` 上的白字 ≥ 7:1。

**字体**（只使用本地字体栈，不加载任何外链字体）：

```css
--font-display: "Iowan Old Style", "Palatino Linotype", Palatino, "Noto Serif SC",
  "Source Han Serif SC", "Songti SC", STSong, "SimSun", serif;
--font-sans: "Seravek", "Gill Sans Nova", "Segoe UI Variable Text", "Segoe UI",
  "PingFang SC", "Hiragino Sans GB", "Microsoft YaHei", "Noto Sans SC",
  "Source Han Sans SC", system-ui, sans-serif;
--font-mono: "JetBrains Mono", "SF Mono", ui-monospace, Menlo, Consolas,
  "Liberation Mono", monospace;
```

- 不使用 Inter、Roboto、Arial。
- 中文正文落在苹方、冬青、雅黑或思源黑体上；标题落在宋体或思源宋体上。在没有任何指定字体的 Linux 上，回退到 `serif` / `sans-serif` 仍可正常阅读。
- 删除 `index.html` 中的 Google Fonts `preconnect` 和 `link`。

**排版层级**：

| 元素 | 字体 | 字号 | 其他 |
|---|---|---|---|
| 欢迎标题 | display | 28 / 34px | `text-balance` |
| 侧边栏字标 | display | 20px | — |
| 顶栏标题 | sans | 14px，600 | — |
| 回答正文 | sans | 15.5px | 行高 1.8 |
| 来源文档名 | sans | 13.5px，500 | — |
| 元数据 | sans | 12px | `tabular-nums` |

**形状与阴影**：

- 圆角：卡片 12px，按钮 8px，输入框 16px，用户气泡 16px（右下角 6px）。
- 阴影只用于两处：输入框（`0 1px 0 line, 0 8px 24px -12px rgb(31 38 36 / .18)`）和弹层。其余层次靠底色和描边区分。

**图标**：统一使用 1.75px 线宽的线性 SVG 内联图标，不使用 emoji（`RewritePanel` 中意图标签的 emoji 一并去掉）。

### D2 应用壳布局

```text
桌面 ≥768px
┌──────────────┬───────────────────────────────────────────────┐
│ 知寻 knowra  │ ChatTopNav: 标题(可重命名)          模型 ● │
│ [＋ 新对话]  ├───────────────────────────────────────────────┤
│              │        内容列 max-w 760px，居中               │
│ 资料库       │  ┌───────────────────────── 用户气泡 ─┐      │
│ 12 份已解析  │  知 回答正文……                              │
│ 流程验证 →   │     来源 · 3 份文档                           │
│              │     ① 讲义.pdf  p.3 · #12  预览…  [展开]     │
│ 最近对话     │     ② 论文.pdf  p.7 · #4                      │
│ · 当前对话 ✎🗑│     复制 · 引用5片段/3文档 · 1,234 tokens    │
│ · …          │     ▸ 检索详情（改写·分数·提示词）            │
│              │                                               │
│ 用户         │  ┌ 输入框 ─────────────────────────────────┐ │
└──────────────┴──┴─────────────────────────────────────────┴─┘

移动 <768px
┌ [≡] 标题……………… 模型 ┐  ← 菜单按钮在顶栏流式布局内，不浮动
│ 内容列 px-3            │
│ 输入框 宽 = 视口 − 24px│
└────────────────────────┘
抽屉：fixed，w-[min(18rem,86vw)]，遮罩 ink/30
```

- **侧边栏**：
  - 宽 272px（`w-68`），底色 `paper-deep`，右侧 1px `line` 描边。
  - 分区从上到下：`SidebarHeader`（字标 + 新对话）→ `KnowledgeInfo` → `ConversationList`（滚动区）→ `SidebarUser`。
  - 分区标题使用 12px、字距 0.08em 的 `ink-faint` 文字，前面没有图标。
- **顶栏 `ChatTopNav`**：
  - 高 52px，与内容区同底色，带半透明纸色背景和 `backdrop-blur`，底部 1px `line`。
  - 菜单按钮由 `ChatTopNav` 渲染在标题左侧：`ChatLayout` 通过 `provide("mobileNav", { isMobile, isOpen, open, triggerRef })` 提供能力，`ChatTopNav` 用 `inject` 获取，中间的 `MainPanel` / `ChatArea` 无需层层透传。
  - 按钮保留 `data-testid="hamburger-menu"` 和 `hamburger-icon`，只是顶栏 flex 布局中的一项，不再使用 `absolute` 定位，因此不会和标题重叠。
  - 没有 provide 时（单独挂载 `ChatTopNav`），不渲染菜单按钮。
- **内容列**：最大宽度 760px（原来是 900px），以保证行长适合阅读。输入区使用同一个容器，两者左右对齐。390px 下左右各留 12px，文本区宽度约 340px。

### D3 移动端抽屉的可访问性

`ChatLayout` 持有 `mobileSidebarOpen` 状态，行为如下：

- **关闭时**：
  - 抽屉元素设置 `inert` 和 `aria-hidden="true"`，内部控件不可聚焦。
  - 仍保留 `-translate-x-full`，方便做过渡动画。
- **打开时**：
  - 抽屉设置 `role="dialog"` 和 `aria-modal="true"`，`aria-label="导航"`。
  - 焦点移到抽屉内第一个可聚焦元素（"新对话"按钮）。
- **关闭途径**：遮罩点击、Esc（监听 document `keydown`）、内部的"关闭"按钮。关闭后焦点回到菜单按钮。
- **自动收起**：不能只监听 `activeConversationId`，因为选择"当前"对话时 ID 不变，会漏掉这条路径。改为由 `AppSidebar` 发出 `navigate` 事件：`ConversationItem` 被选中时发出 `select`，经 `ConversationList` 冒泡上来，与 `SidebarHeader` 的新建对话一起汇总到 `AppSidebar`。`ChatLayout` 在移动抽屉上监听 `@navigate` 后关闭抽屉。
- **焦点陷阱**：抽屉打开时，在抽屉根元素上监听 `keydown`：在最后一个可聚焦元素上按 Tab 时跳回第一个，在第一个上按 Shift+Tab 时跳到最后一个。背景主区域在抽屉打开期间设置 `inert`，双重保证焦点不会逃逸。
- **只挂载一个侧边栏**：桌面侧边栏用 `v-if="!isMobile"`，移动抽屉用 `v-if="isMobile"`，两者互斥。这样 `KnowledgeInfo` 和 `SidebarUser` 只会挂载一次，避免重复请求 API。
- 菜单按钮带 `aria-expanded` 和 `aria-controls="mobile-sidebar"`。

### D4 欢迎页：三步路径 + 推荐问题（填入，不直接发送）

`WelcomeView` 是纯展示组件，通过两个事件与外部通信：

- `upload`：由 ChatArea 调用已有的 `handleAddFiles()`，打开同一个隐藏的 file input。
- `pick-suggestion(text)`：由 ChatArea 把 `text` 写入 `query`，并让 `ChatInput` 聚焦（`ChatInput` 通过 `defineExpose({ focus })` 提供该能力）。

页面结构：

```text
        今天想从资料里找什么？          （display 28px）
   knowra 只根据你上传的资料回答，并标注来源。

 ① 上传资料        ② 提问              ③ 核对来源
 PDF、Word、Markdown 用自然语言描述问题   每个回答下方列出
 [上传资料]                              引用的原文片段

 试着问：
 [总结这些资料的核心观点]
 [列出资料中的关键概念并解释]
 [资料里有哪些结论需要特别注意？]
```

- **为什么填入而不是直接发送**：
  - 推荐问题是通用措辞，用户通常想先补上具体对象（"第三章的"、"关于 X 的"）。
  - 知识库为空时直接发送只会得到"无法回答"。
  - 填入后用户仍保有对提示词的控制权；空输入仍然不能发送，这条规则不变。
- **三步是一行三列的轻量排列**（不是卡片网格）：
  - 每步一个序号圆点和两行文字，步骤之间用细线连接；只有第一步带按钮。
  - 小于 640px 时改为纵向排列。
- **欢迎页不读取资料数量**。资料数量由侧边栏 `KnowledgeInfo` 负责，避免欢迎页依赖网络状态。

### D5 回答区：正文 + 来源 + 收纳的诊断

每轮问答的结构：

```text
UserMessage
AssistantTurn（ChatArea 内的模板块，不新增组件）
 ├─ 等待中：印章 + "正在检索资料…" / "正在生成回答…"（role=status, aria-live=polite）+ 三行骨架
 ├─ 失败：chat-error（请求失败 + 具体原因）
 └─ 有回答：
     AnswerPanel        正文（prose-knowra）+ 底栏
     SourceList         results ≥ 0 时都渲染
     RetrievalDetails   默认折叠，包含 RewritePanel / ResultsPanel / PromptPreview
```

**`AnswerPanel`**：

- 去掉卡片外壳。左侧是 28px 的"知"字印章（`brand-700` 底、白字、display 字体），右侧是正文列。
- 降级状态（生成失败、对话模型未启用）保留，改为琥珀色 / 中性色的"批注条"样式。
- 底栏：
  - "复制"按钮。
  - 引用统计，文案保持"引用 N 个分块 · 来自 K 个文档"，与已有测试兼容。
  - Token 总数，显示为"1,234 tokens"；明细（prompt / completion）放在 `title` 属性和 `sr-only` 文本里。
  - `data-testid="token-stats"` 保留，其文本包含 `total_tokens`。

**`SourceList`**（新增）：

- 输入：`results: SearchResultItem[]`。
- 按 `parsed_document_id` 聚合（同名但不同 id 的文档分开显示），组按首次出现的 rank 排序，编号从 ①（1）开始。
- 每组显示：
  - 朱砂色编号、文档名（允许折行，`break-words`）、片段数。
  - 每个片段的元数据：页码（"第 3、4 页"）、分块编号（"分块 #12"）、标题路径（用 ` › ` 连接）。
  - 预览：默认显示该组第一个片段，最多 2 行（`line-clamp-2`）。
- 组头是 `<button aria-expanded>`。展开后显示该组**所有片段的原始全文**，保留换行（`whitespace-pre-wrap`）。
- 首组默认折叠。理由：回答已经在上方，来源列表应该先保持可扫描；需要核对时点一下即可。
- 没有结果时显示 `data-testid="sources-empty"` 和"没有检索到相关资料，本回答缺少资料依据。"，用朱砂色细边提示。
- 标题为"来源 · K 份文档"。

**`RetrievalDetails`**（新增）：

- 原生 `<button aria-expanded aria-controls>` 加区块容器，默认折叠，文案为"检索详情"，附带一行摘要："改写 · N 个片段 · T ms"。
- 展开后按顺序渲染：
  - `RewritePanel`（`rewrite_info !== null` 时）。
  - `ResultsPanel`（`results.length > 0` 时）。
  - `PromptPreview`（`prompt_messages.length > 0` 时）。
- 三个子面板各自的折叠逻辑和 testid（`results-toggle`、`prompt-toggle`、`rewrite-toggle`）不变，因此诊断区需要两级展开。这保证了旧的 `ChatView`（直接渲染子面板）测试不受影响。
- 视觉：`paper-deep` 底色，细描边，子面板改为平铺分隔（`PanelSection` 新增 `variant="flat"`），不再是卡片套卡片。

**分数条**：

- `similarity = clamp(1 - score, 0, 1)`，条宽为 `round(similarity × 100)%`。分数显示两位小数的相似度，并保留原始距离（`title="余弦距离 0.1234"`）。
- 颜色：similarity ≥ 0.75 为 `brand-600`，≥ 0.5 为 `amber-500`，其余为 `neutral-400`。
- 分布柱状图保留原始余弦距离，标签为"分数分布（余弦距离，越小越相似）"。每条结果自身的分数条按相似度显示，两者并存：一个看分布，一个看单条。

### D6 输入框

```text
┌──────────────────────────────────────────────────────────┐
│ [chips: 讲义.pdf 1.2MB ✓ ×]                                │
│ 向知寻提问，Enter 发送                                    │  ← textarea 独占整行
│ ⌘ 资料   ⚙ 检索 5 段      Shift+Enter 换行    ( ↑ )      │  ← 工具栏
└──────────────────────────────────────────────────────────┘
```

- 文本区宽度等于容器宽度减去 2 × 12px 内边距；在 390px 视口下 ≥ 300px。
- 发送按钮是 36px 圆形按钮，`aria-label="发送"`。
  - 加载时显示 spinner，并通过 `sr-only` 读出阶段文案"搜索中…" / "生成回答中…"（已有测试断言 `send-button` 文本包含"搜索中"，所以保留在 sr-only 中）。
  - 可见的阶段文案显示在回答占位区（D5）。
- 设置按钮显示"检索 {n} 段"，用户无需打开弹层就能看到当前值，主工具栏不出现 Top-K 术语；弹层内标签为"检索片段数（Top-K）"。
- 设置弹层：
  - 开关逻辑沿用现有实现（点击外部关闭）。
  - 新增：Esc 关闭且焦点回到设置按钮；`role="dialog"` 和 `aria-label="检索设置"`。
- 按键提示"Shift+Enter 换行"小于 480px 时隐藏。
- 按键行为不变：Enter 发送，Shift + Enter 或 Ctrl / Cmd + Enter 换行。
- 新增 `defineExpose({ focus })`，供推荐问题使用。

### D7 侧边栏与删除确认

**`KnowledgeInfo`**（新增）：

- 挂载时调用 `listParsedDocuments()`，组件内部管理状态，不新建 store（只有这一个消费者）。
- 四种状态：
  - 加载：`knowledge-loading`，显示骨架。
  - 有资料：`knowledge-count`，显示"N 份已解析资料"。
  - 空：`knowledge-empty`，显示"还没有已解析的资料"和"在对话框中上传"提示。
  - 错误：`knowledge-error`，显示"资料库状态获取失败"和"重试"按钮；点击后再次调用接口。
- 底部提供"流程验证"入口，是一个 `RouterLink` 或 `<a href="/verify">`；为避免在测试中引入 router，用 `<a>`。
- 日志：加载失败时用惰性 logger `components:KnowledgeInfo` 记录 warn。

**`ConversationList`**：先渲染"最近对话"标题，再渲染空状态或列表。

**`ConversationItem`**：

- 根元素仍是 `data-testid="conversation-item"` 的 `div`，用于定位，但不再承担点击。
- 内部主体是 `<button data-testid="conversation-select">`，点击选中；当前对话加 `aria-current="page"`。
- 为兼容现有测试，根 `div` 上的 click 也会选中（事件冒泡）；重命名和删除按钮使用 `.stop`。
- 当前对话使用 `bg-neutral-100`（暖灰）背景，左侧加 2px `brand-600` 指示条。
- 操作按钮容器：当前对话时常显；其他条目使用 `opacity-0 group-hover:opacity-100 group-focus-within:opacity-100`，保证键盘聚焦时可见。按钮带 `aria-label="重命名对话"` / `"删除对话"`。
- 删除：点击后打开 `ConfirmDialog`，标题"删除这段对话？"，正文"「{标题}」及其全部问答记录将被删除，且无法恢复。"，按钮"删除"（危险色）和"取消"。确认后调用 `deleteConversation(id)`，取消时不调用。

**`ConfirmDialog`** 增强：

- 对话框容器加 `role="dialog"`、`aria-modal="true"`、`aria-labelledby`。
- 打开时焦点落到"取消"（安全默认）。
- Esc 触发 `cancel`（只在可见时生效）；Tab / Shift+Tab 在对话框内的可聚焦元素之间循环。
- 标题 ID 用 `shared/a11y/focus.ts` 的 `uniqueId()`（模块级自增计数）生成。没有使用 Vue `useId()`，因为它按应用实例计数，单测里各自挂载的实例会得到相同 ID；本项目是纯 SPA，不需要考虑 SSR 水合一致性。
- 关闭后由调用方（`ConversationItem`）把焦点还给触发它的删除按钮。
- 使用 `<Teleport to="body">`，避免被侧边栏的 `overflow` 或 `transform` 裁切。Teleport 放在 `ConversationItem` 中包裹 `ConfirmDialog`，而不是放在 `ConfirmDialog` 内部。这样 `ConfirmDialog` 自身的 DOM 结构不变，已有的 15 条 `ConfirmDialog.spec.ts` 断言不受影响；侧栏测试通过 `attachTo: document.body` 在 `document` 上查询。
  - 必须使用 Teleport 的原因：移动端抽屉带有 `transform`，会把 `position: fixed` 的遮罩限制在抽屉内部。

**`SidebarUser`**：用户信息去掉 `role="button"` 和 `tabindex`，它不是可操作控件。

### D8 `/verify` 页

- 只改视觉：
  - 顶栏改为字标"知寻 knowra"加"流程验证"面包屑，底色 `paper`。
  - 卡片使用 `surface` 底、`line` 描边。
- 继续保留 `rounded-lg`、`shadow-sm`、`bg-brand-700`、`hover:bg-brand-800`、`disabled:bg-neutral-200` 这些类，现有测试断言了它们；颜色经 D1 重绘后自然统一。
- 所有 testid 和业务逻辑不变。不新增测试，由现有 40+ 条 Verification 测试守护回归。

### D9 动效与减少动画

- 保留的动效：消息淡入（200ms，位移 6px）、抽屉滑入（220ms）、折叠箭头旋转。
- 全局规则：

  ```css
  @media (prefers-reduced-motion: reduce) {
    *, ::before, ::after {
      animation-duration: 0.01ms !important;
      animation-iteration-count: 1 !important;
      transition-duration: 0.01ms !important;
      scroll-behavior: auto !important;
    }
  }
  ```

- 焦点：`:focus-visible` 使用 2px `brand-600` 外描边，偏移 2px。

### D10 Markdown 排版契约（`prose-knowra`）

不依赖 typography 插件，`prose-knowra` 自行声明以下规则：

- 列表：`ul { list-style-type: disc; padding-left: 1.5em }`，`ol { list-style-type: decimal; padding-left: 1.5em }`，嵌套 `ul ul` 使用 `circle`。
- 表格：`table` 设置 `width: 100%`、`border-collapse: collapse`；`th` / `td` 设置 `border-bottom: 1px solid var(--color-line)`；外层允许横向滚动（`display: block; overflow-x: auto`），保证 320px 下不撑破页面。
- 代码块：`pre` 使用墨绿深底 `#1d2a27`，`overflow-x: auto`。
- `hr`、`blockquote`（左侧 3px `brand-600`）、行内 `code` 均有样式。
- `AnswerPanel` 移除无效的 `prose prose-sm` 类，只保留 `prose-knowra`。
- 长文本：正文列和用户气泡都设置 `overflow-wrap: anywhere`。

### 数据流

```text
WelcomeView ──upload──▶ ChatArea.handleAddFiles ─▶ <input type=file> ─▶ uploadFile() ─▶ chips 状态
WelcomeView ──pick-suggestion(text)──▶ ChatArea.query = text; chatInputRef.focus()
ChatInput ──send──▶ ChatArea.handleSend ─▶ chatStore.addBubble ─▶ searchChunks({query, top_k, session_id, history})
                                      └▶ chatStore.updateBubble(response | error)
bubble.response ─▶ AnswerPanel / SourceList / RetrievalDetails(Rewrite/Results/Prompt)
KnowledgeInfo ──mount──▶ listParsedDocuments() ─▶ 计数 | 空 | 错误(重试)
ConversationItem ──删除──▶ ConfirmDialog ──confirm──▶ chatStore.deleteConversation
AppSidebar ──navigate（新建 / 选择，含选择当前对话）──▶ ChatLayout 关闭抽屉 ─▶ 焦点回到菜单按钮
```

以上都是纯前端状态和已有 API，不涉及后端服务、数据库或模型适配器。本变更不持有任何后台任务、长连接、文件句柄或外部客户端，因此**生命周期与 graceful shutdown 不适用**。唯一的全局监听器是 document 上的 `keydown` 和 `click`，在 `onUnmounted` 中移除。

### 测试策略

- **组件测试**（Vitest 加 @vue/test-utils，jsdom）：
  - 测试行为：事件、ARIA 状态、真实文本、调用参数。
  - 只 mock API 模块和 logger；store 尽量使用真实 Pinia。已有测试沿用各自的 mock 方式。
- **CSS 契约测试**：在测试里调用 `tailwindcss` 包的 `compile()`，编译真实的 `src/style.css`，然后检查生成的 CSS：
  - 字体令牌生成了 `font-family`，并包含中文字体和 `serif` / `sans-serif` 回退。
  - 字体栈中不含 Inter、Roboto、Arial。
  - `prose-knowra` 的列表、表格、`pre` 规则存在。
  - 存在 `prefers-reduced-motion` 规则。
  - `index.html` 不引用外部字体域名。

  这些测试检查的是编译产物，而不是源码字符串。
- **浏览器验收**（实现阶段，由主控执行）：Playwright 加 mock `/api/*`，覆盖 1440 / 390 / 320 三个视口、computed `list-style-type`、输入框宽度、菜单和标题的边界框不重叠、`scrollWidth ≤ clientWidth`、reduced-motion。
- **验证命令**：在 `front/` 下运行 `npm run lint && npm run test && npm run build`。

## Risks / Trade-offs

| 风险 | 说明与对策 |
|---|---|
| 就地重绘 `brand` / `neutral` 色阶，名字和颜色语义不再一致（"brand" 不再是蓝色） | 接受。换来的是改动面小、旧测试稳定。语义令牌（`paper` / `ink` / `line` / `cite`）用于新代码；在 `style.css` 头部注释中说明。 |
| 不加载 Web 字体，不同系统字体效果有差异 | 字体栈按 macOS / Windows / Linux 分层排列，最终回退到通用族。设计不依赖某一款字体的特殊字形，层级靠字号、字重和衬线 / 无衬线对比建立。 |
| 来源首组默认折叠，用户可能注意不到原文 | 每组始终显示片段预览（2 行）和页码、分块编号，折叠的只是全文。浏览器验收时检查首屏能看到来源列表。 |
| 诊断需要两级展开 | 这是有意的取舍：诊断面向开发者，默认不打扰普通用户；一级"检索详情"即可看到全部子面板标题。 |
| `ConfirmDialog` 的 Teleport 包裹放在 `ConversationItem` 中 | `ConfirmDialog.spec.ts` 不受影响；只有侧栏删除确认测试需要在 `document` 上查询。 |
| `inert` 在 jsdom 中只是一个属性，不会真正阻止聚焦 | 单测断言属性和 `aria-hidden`；是否真正不可 Tab 由 Playwright 验收。 |
| 推荐问题从"点击即发送"改为"填入" | 已在 proposal 和 spec 中同步更新，这是对旧方案的修正。 |

## Review 调整（主控 review-notes，阶段二开始前写回）

### D11 评审修正汇总

1. **用词**：`GET /api/parsed-documents` 只能证明文档已解析，不能证明已建好向量和索引。UI、proposal 和 spec 一律写作"已解析资料"，不写"可检索"。
2. **ARIA ID 唯一**：`SourceList`、`RetrievalDetails`、`ConfirmDialog`、`PanelSection` 的 `aria-controls` 和 `aria-labelledby` 一律用 `uniqueId()` 生成组件级前缀（原因见 D7）。同一文档出现在多轮回答中时，ID 不会冲突。
3. **不嵌套按钮**：`PanelSection` 可折叠时，头部改为"`<div>` 头部行，内含 `<button>` 折叠区和独立的 actions 区"。`data-testid="${testid}-toggle"` 留在折叠按钮上，所以 actions 中的复制按钮不再嵌套在 button 里面。原有 Rewrite 测试检查的 toggle 类名（`w-full`、`items-center`、`justify-between`、`px-4`、`py-2.5`、`text-left`、`transition-colors`、`hover:bg-neutral-50`）保留在这个按钮上。
4. **来源保真**：展开区直接渲染 API 返回的 `text`，原样输出，不做截断、摘要或改写。每个片段标出原始 rank（`#rank`）和分块序号，同名文档按 `parsed_document_id` 区分。
5. **焦点**：抽屉和确认框都实现 Tab 循环，关闭后焦点回到触发它的控件。
6. **只挂载一个侧边栏**：见 D3。
7. **测试依赖**：`style-contract.test.ts` 直接导入 `lightningcss`。它原本已在依赖树中（作为 `@tailwindcss/vite` 的间接依赖），现在在 `devDependencies` 中显式声明，并同步 lockfile。所以本变更**不新增运行时依赖**，只把测试需要的已有间接开发依赖改为显式声明，不依赖偶然的 hoisting。

## 验收反馈调整（主控独立浏览器验收后）

### D12 键盘层级、滚动与输入法

1. **Esc 与 Tab 的层级**：确认框打开时，它是最上层。它在 document 上用**捕获阶段**监听 `keydown`，处理 Esc 时调用 `preventDefault()` 和 `stopImmediatePropagation()`。Tab 总是阻止传播到背景抽屉，仅在焦点循环边界调用 `preventDefault()`；中间位置保留浏览器原生焦点移动。`ChatLayout` 的抽屉处理器遇到 `defaultPrevented` 的事件直接忽略。因此第一次 Esc 只关闭确认框，并把焦点还给删除按钮；第二次 Esc 才关闭抽屉。Tab 在确认框打开期间只在确认框内循环。
2. **发送后滚动**：只在用户**主动发送**时，`ChatArea` 才在 `nextTick` 后滚动。它只滚动指定的消息容器 `chat-scroll`：先算出最新一轮问答根元素（`data-turn-id`）相对容器的偏移，再调用 `scrollRef.scrollTo({ top, behavior })`。`behavior` 在 reduced-motion 下为 `auto`，否则为 `smooth`。**禁止**使用 `element.scrollIntoView`：它会连带滚动 `overflow-hidden` 的外层应用壳，主控在普通动画模式下实测顶栏被滚出视口（`headerTop=-518`）。也不依赖新的 `scrollIntoView` `container` 选项。异步回答返回时不滚动，避免把正在向上翻阅的读者拉回底部。不新增"滚动到底部"按钮。
3. **输入法组字**：`keydown` 事件满足 `isComposing === true` 或 `keyCode === 229` 时直接返回，不发送也不插入换行，草稿原样保留。
4. **直白文案**：主工具栏显示"检索 N 段"，Top-K 只出现在弹层的高级标签里。
5. **纸面氛围**：新增工具类 `paper-atmosphere`：在 `paper` 底色上叠加两层同色板、极低对比度的 `radial-gradient`（顶部偏松烟青、底部偏暖纸），只用于主对话区背景。不使用图片或纹理。
