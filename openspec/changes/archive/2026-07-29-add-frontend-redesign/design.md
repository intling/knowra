## Context

knowra 前端当前为三页面结构：`/home`（文件上传 + 对话入口）、`/chat`（对话 + 召回验证）、`/verify`（流程验证）。用户在多个页面间跳转才能完成"上传资料 → 提问 → 查看回答与来源"的核心工作流。本次重新设计旨在以对话为中心重构信息架构，合并首页与对话页为单一左右分栏布局，新增侧边栏管理对话历史，并统一全站视觉风格。

**约束**：
- 必须复用现有 `AnswerPanel`、`ResultsPanel`、`PromptPreview` 三个核心验证面板组件
- 技术栈不变：Vue 3.5 + TypeScript + Tailwind CSS v4 + Pinia + Vue Router
- 对话历史使用 localStorage 持久化，纯本地存储不依赖后端 API
- 流程验证页 (`/verify`) 保留功能完整性，仅统一视觉风格

## Goals / Non-Goals

**Goals:**
- 将三页面（首页、对话、验证）精简为两页面（主页 `/`、流程验证 `/verify`）
- 主页采用左右分栏布局：左侧侧边栏 + 右侧对话区
- 侧边栏提供：新建对话按钮、知识库信息概要（文件数）、历史对话列表（切换/重命名/删除）
- 对话输入框内嵌文件上传能力（多文件 chips + 独立删除）
- 对话区展示三态视图：空状态（欢迎页）、加载中（骨架屏）、对话中（消息流）
- 保留 AnswerPanel / ResultsPanel / PromptPreview 的折叠面板交互，作为对话区内嵌组件
- 全站统一新视觉风格：Zinc Gray 中性基调 + Blue 品牌色

**Non-Goals:**
- 不实现知识库批量上传/删除管理页面（侧边栏仅展示概要信息）
- 不实现对话后端 API 持久化，对话数据仅存储在本地 localStorage
- 不修改后端 API 契约
- 不修改 AnswerPanel / ResultsPanel / PromptPreview 的内部逻辑（仅样式微调）
- 不实现用户认证/权限变更

## Decisions

### 1. 布局架构：左右分栏 + 路由壳

**决策**：`App.vue` 变为纯 `<RouterView>` 壳，`ChatLayout.vue` 实现左右分栏。

**理由**：
- 将布局逻辑从 App.vue 解耦，使不同路由可使用不同布局（`/` 用分栏布局，`/verify` 用全宽居中布局）
- 现有 `App.vue` 包含全局 header，重构后移入侧边栏的 SidebarHeader

**替代方案**：使用嵌套路由 + 命名视图。不采用，因为只有两个路由，嵌套路由增加不必要的复杂度。

### 2. 组件拆分为三个目录

**决策**：新增组件按职责分入 `components/layout/`、`components/sidebar/`、`components/chat/` 三个子目录。

**理由**：
- `layout/` — 页面级布局壳（ChatLayout, MainPanel, ChatArea）
- `sidebar/` — 侧边栏功能组件（AppSidebar, SidebarHeader, ConversationList, ConversationItem, KnowledgeInfo）
- `chat/` — 对话区功能组件（WelcomeView, UserMessage）
- 现有顶层组件（AnswerPanel, ResultsPanel, PromptPreview, ChatInput）保持在 `components/` 根目录，减少移动成本
- `components/shared/` — 跨模块通用组件（ConfirmDialog）

### 3. 状态管理：对话使用独立 Pinia Store

**决策**：新建 `useChatStore` 管理对话状态，新建 `useKnowledgeStore` 管理知识库概要状态，扩展 `useAppStore` 增加 UI 状态。

**理由**：
- 对话列表和活跃对话状态原先在 `ChatView.vue` 组件局部管理中，迁移至 Pinia 后可跨侧边栏和对话区共享
- 知识库文件数信息需在侧边栏展示，独立 store 便于后续扩展
- 侧边栏折叠状态属于全局 UI 状态，适合放在 `useAppStore`

**Store 设计**：
- `useChatStore`：`conversations: Conversation[]`、`activeConversationId: string | null`、`addConversation()`、`deleteConversation(id)`、`renameConversation(id, title)`、`setActiveConversation(id)`，持久化为 localStorage
- `useKnowledgeStore`：`fileCount: number`、`fetchFileCount()`（调用现有 API 获取文件数）
- `useAppStore`（扩展）：`sidebarCollapsed: boolean`、`toggleSidebar()`

### 4. 对话持久化策略：纯本地存储

**决策**：对话列表和消息内容存入 `localStorage`，通过 Pinia store 内直接读写，永久保存在用户本地，不涉及后端 API。

**理由**：
- 无需后端 API 变更，快速交付
- 对话数据结构简单，localStorage 容量足够
- 数据完全在用户掌控中，无需网络连接即可访问历史对话

### 5. 文件上传：从独立页面移至对话输入框

**决策**：`ChatInput.vue` 重构为支持附件上传，文件 chips 展示在输入框上方或内部，每文件独立删除按钮。

**理由**：
- 用户在对话上下文中上传文件更自然，减少页面跳转
- 移除 `HomeView` 后上传入口唯一，需确保可用性
- 复用现有 `api/uploads.ts` 上传逻辑

**上传交互流**：点击 📎 按钮 → 文件选择器 → 文件 chips 显示（名称 + 大小 + 删除按钮）→ 上传中状态指示 → 上传完成/失败反馈

### 6. 对话召回验证面板：内嵌 + 默认折叠

**决策**：AnswerPanel 默认展开，ResultsPanel 和 PromptPreview 默认折叠，位置在 AI 回答消息下方。

**理由**：
- 保留现有折叠交互，用户按需展开查看检索结果和提示词
- 不改变面板内部逻辑，仅调整位置和默认状态
- 验证信息与对话流天然关联，内嵌展示比跳转更连贯

### 7. 视觉设计系统

**决策**：引入品牌蓝（Blue 50–900）作为主操作色，保持 Zinc Gray 作为中性基调。

**应用规则**：
- 页面背景：`bg-zinc-50`
- 侧边栏背景：`bg-white`，右侧 `border-r border-zinc-200` 分割线
- 主操作按钮（新建对话、发送）：品牌蓝 `bg-blue-600 hover:bg-blue-700`
- 次操作按钮：`bg-white border-zinc-200`
- 危险操作（删除）：`text-red-600 bg-red-50`
- 选中/激活状态：`bg-zinc-100`
- 用户消息气泡：`bg-zinc-950 text-white rounded-2xl rounded-br-md`
- 输入框：`rounded-2xl` + 强阴影

**圆角规范**：卡片 `rounded-xl` (12px)、按钮 `rounded-lg` (8px)、输入框 `rounded-2xl` (16px)、消息气泡 `rounded-2xl rounded-br-md`

### 8. 移动端响应式

**决策**：侧边栏默认可见（桌面端），移动端默认折叠，通过汉堡菜单按钮切换。

**理由**：
- Tailwind CSS `w-72` (288px) 侧边栏宽度，移动端 `<768px` 时 `translate-x-[-100%]` 隐藏
- `useAppStore.sidebarCollapsed` 控制折叠状态
- 对话区自适应剩余宽度 `flex-1`

### 9. 前端开发规范：默认使用 frontend-design skill

**决策**：本项目前端页面和组件的 UI 设计默认使用 `frontend-design` skill 进行设计，确保视觉风格统一且符合设计系统规范。

**理由**：
- `frontend-design` skill 提供一致的设计系统方法论，确保所有页面和组件视觉风格统一
- 避免手动编写样式时产生风格漂移或不一致
- 与第 7 项"视觉设计系统"决策配合，skill 生成的 UI 自动遵循品牌蓝 + Zinc Gray 的配色和圆角规范

**应用范围**：所有新增前端页面、组件、以及视觉重构均需使用 `frontend-design` skill 生成。

### 10. VerificationView 重构策略

**决策**：保留现有功能代码，仅替换外层布局和配色为统一风格。

**具体变更**：
- 移除侧边栏引用，改为顶部简化导航栏（Logo + "返回首页" 链接 + 页面标题）
- 卡片、按钮、文字配色统一为新视觉规范
- 内部业务逻辑（文档选择、验证执行、结果展示）不变

## Risks / Trade-offs

- **[数据丢失风险] 用户切换对话时未保存的输入可能丢失** → 切换对话前检查输入框是否有内容，有则弹出确认提示或自动保存草稿
- **[localStorage 容量风险] 对话消息积累过多可能超出 localStorage 限制 (5–10MB)** → 限制单对话消息条数，超出时提示用户清理旧对话或导出备份
- **[移动端体验] 左右分栏在移动端全屏展示对话区时，用户可能不知道侧边栏存在** → 汉堡菜单按钮始终可见，首次使用时显示引导提示
- **[ChatView 迁移] ChatView 核心逻辑迁入 ChatArea 时可能遗漏状态或副作用** → 分阶段迁移，Phase 1 先迁移布局壳，确保现有对话功能正常工作后再逐步增强
- **[VerificationView 回归] 视觉重构可能意外改变验证页交互行为** → 仅修改模板外层结构和 CSS 类名，不触碰 `<script setup>` 逻辑，重构后运行现有测试确认通过

## Migration Plan

1. **Phase 1 — 布局壳 + 路由重构**：创建 ChatLayout 壳组件、精简路由、移除 App.vue header、迁移 ChatView 逻辑到 ChatArea。此阶段结束时应可正常使用 `/` 和 `/verify`，功能与重构前等价。
2. **Phase 2 — 侧边栏功能**：创建侧边栏组件 + useChatStore + useKnowledgeStore，实现对话管理。
3. **Phase 3 — 对话增强 + 视觉统一**：ChatInput 附件上传、WelcomeView 空状态、VerificationView 视觉统一、全站配色微调、移动端适配。

**回滚策略**：每个 Phase 通过独立 Git 提交隔离，出现问题时 revert 对应 commit 即可。Phase 1 前创建备份分支。
