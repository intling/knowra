# Frontend Redesign Specification

## Purpose

前端重新设计——提供左右分栏主页面布局（侧边栏 + 对话区）、对话管理（创建/切换/重命名/删除）、对话增强（欢迎页、消息气泡、骨架屏、多文件附件上传），统一品牌蓝 + Zinc Gray 视觉规范。

## Requirements

### Requirement: 主页面左右分栏布局
系统 SHALL 在 `/` 路由提供左右分栏的主页面布局，左侧为固定宽度侧边栏（288px），右侧为自适应宽度的对话主区域。

#### Scenario: 桌面端默认显示分栏布局
- **WHEN** 用户在桌面端（视口宽度 ≥ 768px）访问 `/`
- **THEN** 左侧侧边栏默认可见（宽度 288px），右侧对话区填充剩余宽度
- **AND** 侧边栏右侧有 1px 分割线（`border-r border-zinc-200`）

#### Scenario: 移动端侧边栏默认折叠
- **WHEN** 用户在移动端（视口宽度 < 768px）访问 `/`
- **THEN** 侧边栏默认隐藏，对话区占满全屏
- **AND** 对话区顶部或侧边显示汉堡菜单按钮，用于展开侧边栏

#### Scenario: 移动端切换侧边栏可见性
- **WHEN** 用户在移动端点击汉堡菜单按钮
- **THEN** 侧边栏从左侧滑入覆盖对话区（overlay 模式）
- **AND** 点击侧边栏外部区域或对话区可关闭侧边栏

### Requirement: App.vue 纯路由壳
系统 SHALL 将 `App.vue` 简化为仅包含 `<RouterView>` 的纯路由壳，移除全局 header 和导航栏。

#### Scenario: 路由壳渲染
- **WHEN** 应用初始化完成
- **THEN** `App.vue` 仅渲染 `<RouterView>` 组件，不包含全局 header 或导航菜单

### Requirement: 路由精简为两条
系统 SHALL 将前端路由精简为 `/`（主页 ChatLayout）和 `/verify`（流程验证页），删除 `/home` 和 `/chat` 路由。

#### Scenario: 访问 `/` 渲染主页面
- **WHEN** 用户导航至 `/`
- **THEN** 系统渲染 `ChatLayout` 组件

#### Scenario: 访问 `/verify` 渲染流程验证页
- **WHEN** 用户导航至 `/verify`
- **THEN** 系统渲染 `VerificationView` 组件

#### Scenario: 旧路由重定向
- **WHEN** 用户访问 `/home` 或 `/chat`
- **THEN** 系统自动重定向至 `/`

### Requirement: 侧边栏头部
系统 SHALL 在侧边栏顶部显示应用 Logo、名称"knowra"、副标题"个人知识助手"和"新建对话"按钮。

#### Scenario: 侧边栏头部渲染
- **WHEN** 主页面加载
- **THEN** 侧边栏顶部显示应用名称和副标题
- **AND** 显示全宽"新建对话"按钮，样式为品牌蓝（`bg-blue-600`）

#### Scenario: 新建对话按钮点击
- **WHEN** 用户点击"新建对话"按钮
- **THEN** 系统创建一个新对话，设置为当前活跃对话
- **AND** 对话区切换为空状态（WelcomeView）
- **AND** 新对话出现在历史对话列表顶部

### Requirement: 知识库信息展示
系统 SHALL 在侧边栏"知识库"分区中展示知识库概要信息，至少包含已上传文件数量。

#### Scenario: 知识库有文件时显示文件数
- **WHEN** 知识库中存在已上传文件
- **THEN** 侧边栏"知识库"分区显示文件图标和文件数量

#### Scenario: 知识库为空时显示空状态
- **WHEN** 知识库中无已上传文件
- **THEN** 侧边栏"知识库"分区显示"暂无文件"提示

### Requirement: 对话历史列表
系统 SHALL 在侧边栏"对话历史"分区中以列表形式展示所有历史对话，支持切换、重命名和删除操作。

#### Scenario: 对话列表渲染
- **WHEN** 主页面加载且存在历史对话
- **THEN** 侧边栏按时间倒序显示对话列表，每项显示对话标题

#### Scenario: 切换对话
- **WHEN** 用户点击某个历史对话
- **THEN** 该对话设为当前活跃对话，对话区加载对应消息历史
- **AND** 该对话条目高亮显示（`bg-zinc-100`）

#### Scenario: 重命名对话
- **WHEN** 用户对某个对话触发重命名操作
- **THEN** 对话标题变为可编辑状态
- **AND** 用户确认后标题更新并持久化到 localStorage

#### Scenario: 删除对话
- **WHEN** 用户对某个对话触发删除操作
- **THEN** 系统弹出确认对话框
- **AND** 用户确认后该对话从列表和 localStorage 中移除
- **AND** 如果删除的是当前活跃对话，对话区切换到空状态

#### Scenario: 无对话时的空状态
- **WHEN** 用户没有任何历史对话
- **THEN** "对话历史"分区显示空状态提示

### Requirement: 对话数据持久化
系统 SHALL 将对话列表和消息内容持久化到浏览器 localStorage，确保页面刷新后对话历史不丢失。

#### Scenario: 页面刷新后对话保留
- **WHEN** 用户创建对话并发送消息后刷新页面
- **THEN** 侧边栏仍显示之前的对话列表
- **AND** 上次活跃对话的消息历史仍然可用

#### Scenario: localStorage 数据异常处理
- **WHEN** localStorage 中对话数据格式异常或损坏
- **THEN** 系统初始化空对话列表，不崩溃
- **AND** 通过日志记录数据异常，module_name="chat-store"

### Requirement: 空状态欢迎页
系统 SHALL 在无活跃对话时显示欢迎页，包含引导文案和可选推荐问题。

#### Scenario: 无活跃对话时显示欢迎页
- **WHEN** 用户创建新对话或删除当前活跃对话
- **AND** 该对话尚未发送任何消息
- **THEN** 对话区居中显示欢迎语"今天想了解什么？"
- **AND** 显示副标题引导用户上传资料或提问

#### Scenario: 发送消息后欢迎页消失
- **WHEN** 用户在欢迎页状态下发送第一条消息
- **THEN** 欢迎页替换为对话消息流视图

### Requirement: 用户消息气泡
系统 SHALL 以气泡样式展示用户发送的消息，与 AI 回答卡片形成视觉区分。

#### Scenario: 用户消息渲染
- **WHEN** 用户发送一条消息
- **THEN** 消息以右对齐气泡展示，背景色 `bg-zinc-950` 文字白色，圆角 `rounded-2xl rounded-br-md`

### Requirement: AI 回答加载骨架屏
系统 SHALL 在等待 AI 回答时显示骨架屏动画，分两个阶段展示加载文案。

#### Scenario: 搜索阶段骨架屏
- **WHEN** 用户发送问题后检索尚未完成
- **THEN** 对话区显示骨架屏动画，文案为"搜索中…"
- **AND** 发送按钮显示加载状态并禁用

#### Scenario: 生成阶段骨架屏
- **WHEN** 检索完成但 AI 回答尚未返回
- **THEN** 骨架屏文案变更为"生成回答中…"

#### Scenario: 加载完成骨架屏消失
- **WHEN** AI 回答返回
- **THEN** 骨架屏替换为 AnswerPanel 组件展示的回答内容

### Requirement: 内嵌多文件附件上传
系统 SHALL 在对话输入框中提供内嵌附件上传功能，支持选择多个文件、预览文件 chips 和独立删除。

#### Scenario: 选择文件后显示 chips
- **WHEN** 用户点击输入框附件按钮并选择一个或多个文件
- **THEN** 输入框上方或内部显示文件 chips，每个 chip 包含文件名、文件大小和删除按钮

#### Scenario: 单文件独立删除
- **WHEN** 用户点击某个文件 chip 上的删除按钮
- **THEN** 该文件从待上传列表中移除，不影响其他已选文件

#### Scenario: 文件上传中状态
- **WHEN** 文件正在上传中
- **THEN** 对应的文件 chip 显示上传进度指示
- **AND** 相同的文件不可重复提交

#### Scenario: 文件上传成功后状态
- **WHEN** 文件上传成功
- **THEN** 文件 chip 变更为已上传状态（如显示 ✓ 标记）
- **AND** 用户可发送附带已上传文件引用的消息

#### Scenario: 文件上传失败后处理
- **WHEN** 文件上传失败
- **THEN** 对应的文件 chip 显示错误状态和错误提示
- **AND** 用户可移除该 chip 或重新尝试上传

#### Scenario: 附件按钮与文本发送互不干扰
- **WHEN** 用户已选择附件但未输入文本
- **THEN** 发送按钮可用（因为有附件待发送）
- **AND** 系统发送时仅携带已上传成功的文件信息

### Requirement: 对话输入增强
系统 SHALL 保留现有 ChatInput 的文本输入、Top-K 调节和发送功能，并增强附件上传入口。

#### Scenario: Enter 发送文本
- **WHEN** 用户在输入框中按下 Enter（未按 Shift 或 Ctrl）
- **THEN** 系统发送当前输入内容

#### Scenario: Shift+Enter 换行
- **WHEN** 用户在输入框中按下 Shift+Enter
- **THEN** 输入框内插入换行符，不发送

#### Scenario: Top-K 调节保留
- **WHEN** 用户调整 Top-K 滑块
- **THEN** 下一条搜索请求使用调整后的 top_k 值

#### Scenario: 空文本且无附件时发送按钮禁用
- **WHEN** 输入框为空（或仅含空白）且无已选附件
- **THEN** 发送按钮处于禁用状态
