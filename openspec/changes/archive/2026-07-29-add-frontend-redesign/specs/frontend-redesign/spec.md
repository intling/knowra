# Frontend Redesign Specification

本 spec 涵盖前端重新设计的所有新增和修改需求，按功能模块分节。

---

## ADDED Requirements

### 主页面布局

#### Requirement: 主页面左右分栏布局
系统 SHALL 在 `/` 路由提供左右分栏的主页面布局，左侧为固定宽度侧边栏（288px），右侧为自适应宽度的对话主区域。

##### Scenario: 桌面端默认显示分栏布局
- **WHEN** 用户在桌面端（视口宽度 ≥ 768px）访问 `/`
- **THEN** 左侧侧边栏默认可见（宽度 288px），右侧对话区填充剩余宽度
- **AND** 侧边栏右侧有 1px 分割线（`border-r border-zinc-200`）

##### Scenario: 移动端侧边栏默认折叠
- **WHEN** 用户在移动端（视口宽度 < 768px）访问 `/`
- **THEN** 侧边栏默认隐藏，对话区占满全屏
- **AND** 对话区顶部或侧边显示汉堡菜单按钮，用于展开侧边栏

##### Scenario: 移动端切换侧边栏可见性
- **WHEN** 用户在移动端点击汉堡菜单按钮
- **THEN** 侧边栏从左侧滑入覆盖对话区（overlay 模式）
- **AND** 点击侧边栏外部区域或对话区可关闭侧边栏

#### Requirement: App.vue 纯路由壳
系统 SHALL 将 `App.vue` 简化为仅包含 `<RouterView>` 的纯路由壳，移除全局 header 和导航栏。

##### Scenario: 路由壳渲染
- **WHEN** 应用初始化完成
- **THEN** `App.vue` 仅渲染 `<RouterView>` 组件，不包含全局 header 或导航菜单

#### Requirement: 路由精简为两条
系统 SHALL 将前端路由精简为 `/`（主页 ChatLayout）和 `/verify`（流程验证页），删除 `/home` 和 `/chat` 路由。

##### Scenario: 访问 `/` 渲染主页面
- **WHEN** 用户导航至 `/`
- **THEN** 系统渲染 `ChatLayout` 组件

##### Scenario: 访问 `/verify` 渲染流程验证页
- **WHEN** 用户导航至 `/verify`
- **THEN** 系统渲染 `VerificationView` 组件

##### Scenario: 旧路由重定向
- **WHEN** 用户访问 `/home` 或 `/chat`
- **THEN** 系统自动重定向至 `/`

---

### 侧边栏

#### Requirement: 侧边栏头部
系统 SHALL 在侧边栏顶部显示应用 Logo、名称"knowra"、副标题"个人知识助手"和"新建对话"按钮。

##### Scenario: 侧边栏头部渲染
- **WHEN** 主页面加载
- **THEN** 侧边栏顶部显示应用名称和副标题
- **AND** 显示全宽"新建对话"按钮，样式为品牌蓝（`bg-blue-600`）

##### Scenario: 新建对话按钮点击
- **WHEN** 用户点击"新建对话"按钮
- **THEN** 系统创建一个新对话，设置为当前活跃对话
- **AND** 对话区切换为空状态（WelcomeView）
- **AND** 新对话出现在历史对话列表顶部

#### Requirement: 知识库信息展示
系统 SHALL 在侧边栏"知识库"分区中展示知识库概要信息，至少包含已上传文件数量。

##### Scenario: 知识库有文件时显示文件数
- **WHEN** 知识库中存在已上传文件
- **THEN** 侧边栏"知识库"分区显示文件图标和文件数量

##### Scenario: 知识库为空时显示空状态
- **WHEN** 知识库中无已上传文件
- **THEN** 侧边栏"知识库"分区显示"暂无文件"提示

#### Requirement: 对话历史列表
系统 SHALL 在侧边栏"对话历史"分区中以列表形式展示所有历史对话，支持切换、重命名和删除操作。

##### Scenario: 对话列表渲染
- **WHEN** 主页面加载且存在历史对话
- **THEN** 侧边栏按时间倒序显示对话列表，每项显示对话标题

##### Scenario: 切换对话
- **WHEN** 用户点击某个历史对话
- **THEN** 该对话设为当前活跃对话，对话区加载对应消息历史
- **AND** 该对话条目高亮显示（`bg-zinc-100`）

##### Scenario: 重命名对话
- **WHEN** 用户对某个对话触发重命名操作
- **THEN** 对话标题变为可编辑状态
- **AND** 用户确认后标题更新并持久化到 localStorage

##### Scenario: 删除对话
- **WHEN** 用户对某个对话触发删除操作
- **THEN** 系统弹出确认对话框
- **AND** 用户确认后该对话从列表和 localStorage 中移除
- **AND** 如果删除的是当前活跃对话，对话区切换到空状态

##### Scenario: 无对话时的空状态
- **WHEN** 用户没有任何历史对话
- **THEN** "对话历史"分区显示空状态提示

#### Requirement: 对话数据持久化
系统 SHALL 将对话列表和消息内容持久化到浏览器 localStorage，确保页面刷新后对话历史不丢失。

##### Scenario: 页面刷新后对话保留
- **WHEN** 用户创建对话并发送消息后刷新页面
- **THEN** 侧边栏仍显示之前的对话列表
- **AND** 上次活跃对话的消息历史仍然可用

##### Scenario: localStorage 数据异常处理
- **WHEN** localStorage 中对话数据格式异常或损坏
- **THEN** 系统初始化空对话列表，不崩溃
- **AND** 通过日志记录数据异常，module_name="chat-store"

---

### 对话增强

#### Requirement: 空状态欢迎页
系统 SHALL 在无活跃对话时显示欢迎页，包含引导文案和可选推荐问题。

##### Scenario: 无活跃对话时显示欢迎页
- **WHEN** 用户创建新对话或删除当前活跃对话
- **AND** 该对话尚未发送任何消息
- **THEN** 对话区居中显示欢迎语"今天想了解什么？"
- **AND** 显示副标题引导用户上传资料或提问

##### Scenario: 发送消息后欢迎页消失
- **WHEN** 用户在欢迎页状态下发送第一条消息
- **THEN** 欢迎页替换为对话消息流视图

#### Requirement: 用户消息气泡
系统 SHALL 以气泡样式展示用户发送的消息，与 AI 回答卡片形成视觉区分。

##### Scenario: 用户消息渲染
- **WHEN** 用户发送一条消息
- **THEN** 消息以右对齐气泡展示，背景色 `bg-zinc-950` 文字白色，圆角 `rounded-2xl rounded-br-md`

#### Requirement: AI 回答加载骨架屏
系统 SHALL 在等待 AI 回答时显示骨架屏动画，分两个阶段展示加载文案。

##### Scenario: 搜索阶段骨架屏
- **WHEN** 用户发送问题后检索尚未完成
- **THEN** 对话区显示骨架屏动画，文案为"搜索中…"
- **AND** 发送按钮显示加载状态并禁用

##### Scenario: 生成阶段骨架屏
- **WHEN** 检索完成但 AI 回答尚未返回
- **THEN** 骨架屏文案变更为"生成回答中…"

##### Scenario: 加载完成骨架屏消失
- **WHEN** AI 回答返回
- **THEN** 骨架屏替换为 AnswerPanel 组件展示的回答内容

#### Requirement: 内嵌多文件附件上传
系统 SHALL 在对话输入框中提供内嵌附件上传功能，支持选择多个文件、预览文件 chips 和独立删除。

##### Scenario: 选择文件后显示 chips
- **WHEN** 用户点击输入框附件按钮并选择一个或多个文件
- **THEN** 输入框上方或内部显示文件 chips，每个 chip 包含文件名、文件大小和删除按钮

##### Scenario: 单文件独立删除
- **WHEN** 用户点击某个文件 chip 上的删除按钮
- **THEN** 该文件从待上传列表中移除，不影响其他已选文件

##### Scenario: 文件上传中状态
- **WHEN** 文件正在上传中
- **THEN** 对应的文件 chip 显示上传进度指示
- **AND** 相同的文件不可重复提交

##### Scenario: 文件上传成功后状态
- **WHEN** 文件上传成功
- **THEN** 文件 chip 变更为已上传状态（如显示 ✓ 标记）
- **AND** 用户可发送附带已上传文件引用的消息

##### Scenario: 文件上传失败后处理
- **WHEN** 文件上传失败
- **THEN** 对应的文件 chip 显示错误状态和错误提示
- **AND** 用户可移除该 chip 或重新尝试上传

##### Scenario: 附件按钮与文本发送互不干扰
- **WHEN** 用户已选择附件但未输入文本
- **THEN** 发送按钮可用（因为有附件待发送）
- **AND** 系统发送时仅携带已上传成功的文件信息

#### Requirement: 对话输入增强
系统 SHALL 保留现有 ChatInput 的文本输入、Top-K 调节和发送功能，并增强附件上传入口。

##### Scenario: Enter 发送文本
- **WHEN** 用户在输入框中按下 Enter（未按 Shift 或 Ctrl）
- **THEN** 系统发送当前输入内容

##### Scenario: Shift+Enter 换行
- **WHEN** 用户在输入框中按下 Shift+Enter
- **THEN** 输入框内插入换行符，不发送

##### Scenario: Top-K 调节保留
- **WHEN** 用户调整 Top-K 滑块
- **THEN** 下一条搜索请求使用调整后的 top_k 值

##### Scenario: 空文本且无附件时发送按钮禁用
- **WHEN** 输入框为空（或仅含空白）且无已选附件
- **THEN** 发送按钮处于禁用状态

---

## MODIFIED Requirements

### 对话召回验证 UI（chat-recall-ui）

#### Requirement: 对话召回验证页面路由
系统 SHALL 将对话召回验证功能内嵌至主页面 `/` 的 ChatArea 中，不再作为独立 `/chat` 路由页面。

##### Scenario: 对话召回验证在主页内可用
- **WHEN** 用户导航至 `/`
- **AND** 用户在对话区发送问题
- **THEN** AI 回答（AnswerPanel）、检索结果（ResultsPanel）、提示词预览（PromptPreview）在对话流中内嵌展示
- **AND** 不再通过 `/chat` 路由访问独立对话页

#### Requirement: AI 回答展示
页面 SHALL 在对话消息流中显示 AI 回答面板，包含 Markdown 渲染的回答内容、引用统计（引用 N/M 分块 · 来自 K 个文档）、Token 用量（prompt + completion = total）、复制回答按钮。AnswerPanel 作为 ChatArea 内嵌组件，位于用户问题消息下方，默认展开。

##### Scenario: 显示回答
- **WHEN** 搜索成功
- **THEN** 对话流中用户问题下方显示 AI 回答面板，包含 Markdown 渲染的回答文本、引用统计和 Token 用量
- **AND** 面板默认展开

#### Requirement: 检索结果面板
页面 SHALL 在 AI 回答下方显示可折叠的检索结果面板（默认折叠），包含搜索摘要栏（搜索 N 个文档 · M 个向量 · 耗时 T ms）和按文档分组的结果列表，每条结果展示排名、可视化分数条、分块文本（前 300 字符可展开）、元数据（页码、标题路径、Token 数）。ResultsPanel 作为 ChatArea 内嵌组件。

##### Scenario: 结果按文档分组
- **WHEN** 搜索结果来自多个文档
- **THEN** 结果按文档名称分组显示，每组显示文档名称和结果数量

##### Scenario: 分数条可视化
- **WHEN** 结果列表展示
- **THEN** 每条结果旁显示可视化分数条，分数越小（越相似）条越长

##### Scenario: 空结果
- **WHEN** 搜索返回 0 条结果
- **THEN** 结果显示区域显示空结果提示

##### Scenario: 默认折叠状态
- **WHEN** AI 回答展示完成后
- **THEN** ResultsPanel 默认处于折叠状态，用户需手动点击展开

#### Requirement: 提示词预览
页面 SHALL 在检索结果下方显示可折叠的提示词预览面板（默认折叠），展示实际发送给 LLM 的完整 messages 数组（每个 message 的 role + content）和复制按钮。PromptPreview 作为 ChatArea 内嵌组件。

##### Scenario: 提示词面板内容
- **WHEN** 用户展开提示词预览
- **THEN** 显示完整的 system message 和 user message 内容

##### Scenario: 默认折叠状态
- **WHEN** AI 回答展示完成后
- **THEN** PromptPreview 默认处于折叠状态，用户需手动点击展开

#### Requirement: 对话历史
页面 SHALL 维护当前会话的对话历史列表，每条对话包含 query + answer + results 组合。对话历史受侧边栏的 useChatStore 管理，支持跨对话切换时保留各自的消息历史。首次加载时显示空状态引导。

##### Scenario: 对话历史累积
- **WHEN** 用户在当前对话中连续发送多条查询
- **THEN** 对话区显示完整消息历史，最新消息在最下方

##### Scenario: 切换对话后消息历史独立
- **WHEN** 用户从对话 A 切换到对话 B
- **THEN** 对话区显示对话 B 的消息历史
- **AND** 切换回对话 A 时消息历史完整保留

##### Scenario: 空状态引导
- **WHEN** 页面首次加载且无对话历史
- **THEN** 对话区显示 WelcomeView 欢迎页

---

### 文件上传（file-upload-storage）

#### Requirement: 前端上传体验
前端 SHALL 在对话输入框中提供内嵌附件上传入口，基于附件按钮选择文件、在输入框区域展示文件 chips 并支持多文件选择和独立删除，上传状态在 chip 上反馈。

##### Scenario: 选择文件后显示待上传文件
- **WHEN** 用户通过对话输入框中的附件按钮选择文件
- **THEN** 前端 MUST 在输入框上方或内部显示被选中文件的 chips，每个 chip 包含文件名和删除按钮
- **AND** 前端 MUST 允许用户逐个移除待上传文件

##### Scenario: 多文件选择
- **WHEN** 用户通过附件按钮选择多个文件
- **THEN** 前端 MUST 为每个文件显示独立的 chip
- **AND** 每个 chip 有独立的删除按钮和上传状态指示

##### Scenario: 提交文件上传
- **WHEN** 当前用户加载成功
- **AND** 用户选择了文件并触发上传
- **THEN** 前端 MUST 调用上传 API
- **AND** 前端 MUST NOT 在请求中提交 `owner_user_id`

##### Scenario: 上传过程中展示加载状态
- **WHEN** 上传请求尚未完成
- **THEN** 对应文件 chip MUST 展示上传中状态（如 spinner 动画）
- **AND** 前端 MUST 防止同一文件被重复提交

##### Scenario: 上传成功后更新 chip 状态
- **WHEN** 上传 API 返回成功上传记录
- **THEN** 对应文件 chip MUST 变更为已上传完成状态（如显示 ✓ 标记）
- **AND** 文件 chip 保留在输入区上方，作为已附加文件引用

##### Scenario: 上传失败后展示错误
- **WHEN** 上传 API 返回错误或请求失败
- **THEN** 对应文件 chip MUST 展示用户可理解的错误反馈
- **AND** 前端 MUST 保留用户移除该 chip 或重新尝试上传的可能性

##### Scenario: 当前用户不可用时禁用上传
- **WHEN** 前端当前用户加载失败
- **THEN** 依赖用户归属的上传操作 MUST 不可提交
- **AND** 附件按钮 MUST 处于禁用状态
- **AND** 前端 MUST 展示当前用户不可用反馈

#### Requirement: 发送消息携带已上传文件
前端 SHALL 在用户发送消息时携带已上传成功的文件引用，确保后端能将提问与相关文件关联。

##### Scenario: 发送时携带文件引用
- **WHEN** 用户输入文本并已上传文件
- **AND** 用户点击发送
- **THEN** 前端 MUST 在搜索请求中包含已上传文件的 ID 列表

##### Scenario: 仅上传文件无文本时
- **WHEN** 用户已上传文件但输入框为空
- **THEN** 发送按钮 MUST 可用
- **AND** 前端发送请求时 query 默认为"总结归纳文档的关键信息"，携带文件引用

---

### 流程验证（pipeline-verification）

#### Requirement: 前端验证页面
系统 SHALL 在 `/verify` 路由提供流水线存取验证页面，采用全宽居中布局 + 简化顶部导航栏（替代原有侧边栏），统一新视觉风格（品牌蓝 + Zinc Gray），保留全部现有验证功能。

##### Scenario: 页面加载时获取已解析文档列表
- **WHEN** 用户导航至 `/verify` 页面
- **THEN** 页面自动调用已有 API 获取当前用户的所有已解析文档列表，填充文档下拉选择器

##### Scenario: 用户选择文档并执行验证
- **WHEN** 用户从下拉列表选择一个文档并点击"执行验证"按钮
- **THEN** 页面调用 `GET /api/parsed-documents/{id}/pipeline-verification`，在加载期间显示骨架屏，请求完成后渲染文档信息、Pipeline 链路、验证摘要面板和分块-向量对照表

##### Scenario: 验证全部通过
- **WHEN** API 返回 `verification.passed` 为 true
- **THEN** 页面以绿色/通过样式展示所有 7 项检查，验证摘要面板显示 "7/7 通过"

##### Scenario: 部分检查失败
- **WHEN** API 返回部分检查 `passed` 为 false
- **THEN** 页面以红色/失败样式展示未通过的检查项，验证摘要面板显示实际通过数量和失败数量

##### Scenario: 选中文档无完整 pipeline
- **WHEN** API 返回 404 且 detail 指示某个阶段缺失
- **THEN** 页面显示错误详情，明确告知用户哪个 pipeline 阶段缺失（解析/分块/向量化），并建议下一步操作

##### Scenario: API 服务不可用
- **WHEN** API 返回 503 或其他 5xx 错误
- **THEN** 页面显示错误详情，建议用户稍后重试

##### Scenario: 无已解析文档时的空状态
- **WHEN** 当前用户没有任何已解析文档
- **THEN** 文档选择器显示空状态提示，引导用户先上传并解析文档

#### Requirement: 验证页顶部导航栏
系统 SHALL 在 `/verify` 页面顶部显示简化导航栏，包含 knowra Logo、返回首页链接和"流程验证"页面标题，替代旧版全局 header。

##### Scenario: 顶部导航栏渲染
- **WHEN** 用户访问 `/verify`
- **THEN** 页面顶部显示导航栏，包含可点击的 knowra Logo（链接至 `/`）和"流程验证"标题

##### Scenario: 返回首页
- **WHEN** 用户点击导航栏中的 Logo 或返回链接
- **THEN** 系统导航至 `/`

#### Requirement: 验证页视觉风格统一
系统 SHALL 将 `/verify` 页面的配色、卡片样式、按钮样式、排版统一为新的品牌蓝 + Zinc Gray 视觉规范。

##### Scenario: 按钮使用品牌蓝
- **WHEN** 验证页渲染"执行验证"主操作按钮
- **THEN** 按钮使用品牌蓝配色（`bg-blue-600 hover:bg-blue-700`）

##### Scenario: 卡片和面板统一圆角与阴影
- **WHEN** 验证页渲染卡片式面板
- **THEN** 卡片使用 `rounded-xl` 圆角和 `shadow-sm` 阴影

##### Scenario: 检查通过/失败状态色
- **WHEN** 验证结果显示检查通过或失败
- **THEN** 通过状态使用绿色（`text-emerald-600`），失败状态使用红色（`text-red-600`）
