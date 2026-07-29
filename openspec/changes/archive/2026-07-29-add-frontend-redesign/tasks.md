## 1. Phase 1 准备 — 目录结构与新组件目录

- [x] 1.1 创建组件子目录 `front/src/components/layout/`、`front/src/components/sidebar/`、`front/src/components/chat/`、`front/src/components/shared/`

## 2. Phase 1 — 布局壳 + 路由重构

- [x] 2.1 编写路由重构 RED 测试：验证 `/` 和 `/verify` 两条路由可访问，`/home` 和 `/chat` 重定向至 `/`
- [x] 2.2 重构 `front/src/router/index.ts`：精简为 `/` (ChatLayout) 和 `/verify` (VerificationView) 两条路由，添加旧路由重定向
- [x] 2.3 创建 `front/src/components/layout/ChatLayout.vue`：左右分栏布局壳，左侧侧边栏占位 + 右侧 MainPanel 占位
- [x] 2.4 创建 `front/src/components/layout/MainPanel.vue`：右侧主区域容器，包裹 ChatArea
- [x] 2.5 创建 `front/src/components/layout/ChatArea.vue`：将 ChatView 核心逻辑（消息流、发送、面板展示）迁入此组件
- [x] 2.6 重构 `front/src/App.vue`：移除全局 header，变为纯 `<RouterView>` 壳
- [x] 2.7 删除 `front/src/views/HomeView.vue` 及对应的测试文件 `front/src/views/HomeView.test.ts`
- [x] 2.8 更新 `front/src/views/ChatView.vue`：保留向后兼容（若有外部引用），迁移完成后标记 deprecated
- [x] 2.9 验证 Phase 1 质量门禁：`cd front && npm run lint && npm run test && npm run build`

## 3. Phase 2 — 侧边栏组件与功能

- [x] 3.1 编写 useChatStore RED 测试：验证创建对话、删除对话、重命名对话、切换活跃对话、localStorage 持久化与读取
- [x] 3.2 创建 `front/src/stores/chat.ts`（useChatStore）：实现对话列表、活跃对话管理、localStorage 持久化
- [x] 3.3 编写 useKnowledgeStore RED 测试：验证获取知识库文件数、空状态处理
- [x] 3.4 创建 `front/src/stores/knowledge.ts`（useKnowledgeStore）：实现知识库文件数获取（复用现有 API）
- [x] 3.5 编写侧边栏组件 RED 测试：验证 AppSidebar 渲染结构、ConversationList 列表渲染与空状态、ConversationItem 操作按钮
- [x] 3.6 创建 `front/src/components/sidebar/SidebarHeader.vue`：Logo + 应用名称 + 新建对话按钮
- [x] 3.7 创建 `front/src/components/sidebar/ConversationItem.vue`：单条对话条目，hover 显示重命名/删除按钮，当前激活项高亮
- [x] 3.8 创建 `front/src/components/sidebar/ConversationList.vue`：对话列表容器，支持空状态，集成 ConversationItem
- [x] 3.9 创建 `front/src/components/sidebar/KnowledgeInfo.vue`：知识库信息展示（文件数概要）
- [x] 3.10 创建 `front/src/components/sidebar/AppSidebar.vue`：侧边栏容器，组合 SidebarHeader + KnowledgeInfo + ConversationList
- [x] 3.11 扩展 `front/src/stores/app.ts`（useAppStore）：新增 `sidebarCollapsed` 状态和 `toggleSidebar()` 方法
- [x] 3.12 编写 ConfirmDialog RED 测试：验证确认/取消交互、插槽内容渲染
- [x] 3.13 创建 `front/src/components/shared/ConfirmDialog.vue`：通用确认对话框组件
- [x] 3.14 验证 Phase 2 质量门禁：`cd front && npm run lint && npm run test && npm run build`

## 4. Phase 3 — 对话增强 + 视觉统一

- [x] 4.1 编写 WelcomeView 与 UserMessage RED 测试：验证欢迎页渲染、消息气泡样式、发送后欢迎页消失
- [x] 4.2 创建 `front/src/components/chat/WelcomeView.vue`：空状态欢迎页（欢迎语 + 引导文案）
- [x] 4.3 创建 `front/src/components/chat/UserMessage.vue`：用户消息气泡组件
- [x] 4.4 编写 ChatInput 重构 RED 测试：验证多文件 chips 渲染、单文件删除、上传状态指示、附件按钮与发送互不干扰
- [x] 4.5 重构 `front/src/components/ChatInput.vue`：增加附件按钮、文件 chips 区域（多文件 + 独立删除）、上传状态指示、加载 spinner
- [x] 4.6 ChatArea 集成新组件：WelcomeView 空状态、UserMessage 气泡、ChatInput 附件区、AnswerPanel/ResultsPanel/PromptPreview 内嵌折叠面板
- [x] 4.7 编写 VerificationView 重构 RED 测试：验证顶部导航栏渲染、Logo 返回链接、配色变更不破坏现有功能
- [x] 4.8 重构 `front/src/views/VerificationView.vue`：统一新视觉风格（顶部导航栏、品牌蓝按钮、圆角卡片），保留全部业务逻辑
- [x] 4.9 更新 `front/src/style.css`：引入品牌蓝配色变量，统一圆角/阴影/排版规范，确保 Tailwind CSS v4 主题与设计文档一致
- [x] 4.10 编写 移动端响应式 RED 测试：验证侧边栏折叠/展开行为、汉堡菜单渲染
- [x] 4.11 实现移动端响应式适配：侧边栏 `<768px` 默认折叠、汉堡菜单按钮、overlay 模式
- [x] 4.12 细节打磨：过渡动画（侧边栏滑入/滑出、消息出现）、hover 状态、焦点样式
- [x] 4.13 验证 Phase 3 质量门禁：`cd front && npm run lint && npm run test && npm run build`

## 5. 收尾验证

- [x] 5.1 全量测试通过：`cd front && npm run test`
- [x] 5.2 全量 lint 通过：`cd front && npm run lint`
- [x] 5.3 生产构建通过：`cd front && npm run build`
- [x] 5.4 本地浏览器验证：启动前端，手动验证 `/` 页面左右分栏、侧边栏新建/切换/删除对话、对话区发送消息与召回验证面板、`/verify` 页面新视觉风格、移动端侧边栏折叠
