## Why

当前前端由三个独立页面（首页文件上传、对话验证、流程验证）组成，用户需要在页面之间跳转才能完成"上传资料 → 提问 → 查看结果"的核心工作流。这割裂了对话体验，缺少对话历史管理，且首页文件上传与对话区分离导致操作路径冗长。本次重新设计将以对话为中心，将上传与提问融合在一个界面中，新增侧边栏提供对话历史与知识库概览，提升用户从"资料接入到带引用回答生成"的连贯性和效率。

## What Changes

- **新增 `ChatLayout` 左右分栏布局**：左侧侧边栏（新建对话、知识库信息展示、历史对话列表）+ 右侧对话区（消息流 + 内嵌文件上传 + 对话召回验证面板），路由为 `/`
- **新增侧边栏组件体系**：`AppSidebar`、`SidebarHeader`、`ConversationList`、`ConversationItem`、`KnowledgeInfo`，提供对话历史管理（新建/切换/重命名/删除）和知识库概要信息展示
- **对话输入增强**：`ChatInput` 重构为支持多文件附件上传、文件 chip 预览、加载状态展示的内嵌输入组件
- **新增对话区组件**：`WelcomeView`（空状态欢迎页）、`UserMessage`（用户消息气泡）、`MainPanel`（右侧主区域容器）、`ChatArea`（对话消息流）
- **删除 `HomeView`**：其文件上传和对话功能合并入 `ChatLayout` 的对话区
- **重构 `App.vue`**：去掉全局 header，变为纯路由壳
- **重构 `VerificationView`**：保留现有全链路验证功能，统一新视觉风格（侧边栏替换为简化顶部导航），路由保持 `/verify`
- **重构路由**：精简为 `/` 和 `/verify` 两条路由
- **视觉风格统一**：引入品牌蓝（Blue）作为主操作色，保持 Zinc Gray 中性基调，统一圆角、阴影、排版规范
- **状态管理扩展**：新增 `useChatStore`（对话状态）、`useKnowledgeStore`（知识库状态），扩展 `useAppStore`（侧边栏折叠、活跃视图）
- **对话历史持久化**：使用 Pinia + localStorage 本地存储，数据永久保存在用户本地

## Capabilities

### New Capabilities

- `chat-layout`: 主页面左右分栏布局，包含侧边栏容器与右侧对话区容器的壳结构，支持移动端侧边栏折叠
- `sidebar`: 侧边栏功能，包括新建对话按钮、知识库信息概要展示（文件数）、历史对话列表及其管理（切换/重命名/删除）
- `chat-enhancement`: 对话区增强，包括空状态欢迎页、用户消息气泡、AI 回答加载骨架屏、内嵌多文件附件上传

### Modified Capabilities

- `chat-recall-ui`: AnswerPanel、ResultsPanel、PromptPreview 从独立页面组件变为 ChatArea 内嵌折叠面板，保留现有折叠交互，位置固定在 AI 回答下方
- `file-upload-storage`: 文件上传入口从单独首页移至对话输入框内嵌附件按钮，支持多文件 chips 预览和独立删除
- `pipeline-verification`: VerificationView 保留全链路验证功能，视觉风格统一为新的品牌蓝 + Zinc Gray 配色，侧边栏替换为顶部简化导航

## Impact

- **Affected code**: `App.vue`, `router/index.ts`, `views/HomeView.vue`（删除）, `views/ChatView.vue`（逻辑迁移）, `views/VerificationView.vue`, `components/ChatInput.vue`, `stores/app.ts`, `style.css`
- **New code**: `components/layout/ChatLayout.vue`, `MainPanel.vue`, `ChatArea.vue`; `components/sidebar/AppSidebar.vue`, `SidebarHeader.vue`, `ConversationList.vue`, `ConversationItem.vue`, `KnowledgeInfo.vue`; `components/chat/WelcomeView.vue`, `UserMessage.vue`; `components/shared/ConfirmDialog.vue`; `stores/chat.ts`, `stores/knowledge.ts`; `api/knowledge.ts`
- **Dependencies**: 无新增外部依赖，全部使用现有 Vue 3 + TS + Tailwind CSS v4 技术栈
- **API**: 对话管理使用 localStorage 本地存储，不依赖后端 API；知识库文件数通过现有 API 获取
- **Breaking**: 删除 `HomeView` 及其路由 `/home`，依赖该页面的外部链接需更新为 `/`
