## Purpose

对话召回验证前端页面——提供 Markdown 渲染的 LLM 回答展示、按文档分组的召回结果面板、可折叠的提示词调试面板，用于验证端到端 RAG 质量。

## Requirements

### Requirement: 对话召回验证页面路由
系统 SHALL 在 `/chat` 路径提供对话召回验证页面，与现有流水线验证页面（`/verify`）并列，导航栏新增"对话验证"入口。

#### Scenario: 页面可访问
- **WHEN** 用户导航至 `/chat`
- **THEN** 页面渲染 ChatView 组件，显示对话召回验证界面

### Requirement: 文本输入与发送
页面 SHALL 提供文本输入框，支持 Enter 换行、Ctrl+Enter 或点击按钮发送，禁止发送空文本（仅含空白字符也视为空文本），以及 Top-K 滑块（1–50，默认 5）。

#### Scenario: Enter 换行
- **WHEN** 用户在输入框中按下 Enter
- **THEN** 输入框内插入换行符，不发送请求

#### Scenario: Ctrl+Enter 或点击按钮发送
- **WHEN** 用户按下 Ctrl+Enter 或点击发送按钮
- **AND** 输入框内容非空（去掉首尾空白后仍有内容）
- **THEN** 系统发送搜索请求，输入框内容作为 query

#### Scenario: 空文本无法发送
- **WHEN** 输入框内容为空或仅含空白字符
- **THEN** 发送按钮处于禁用状态，Ctrl+Enter 不触发发送

#### Scenario: Top-K 调整
- **WHEN** 用户调整 Top-K 滑块至 10
- **THEN** 下一条搜索请求中 top_k=10

### Requirement: AI 回答展示
页面 SHALL 显示 AI 回答面板，包含 Markdown 渲染的回答内容、引用统计（引用 N/M 分块 · 来自 K 个文档）、Token 用量（prompt + completion = total）、复制回答按钮。

#### Scenario: 显示回答
- **WHEN** 搜索成功
- **THEN** 页面显示 AI 回答面板，包含 Markdown 渲染的回答文本、引用统计和 Token 用量

### Requirement: 检索结果面板
页面 SHALL 显示可折叠的检索结果面板（默认折叠），包含搜索摘要栏（搜索 N 个文档 · M 个向量 · 耗时 T ms）和按文档分组的结果列表，每条结果展示排名、可视化分数条、分块文本（前 300 字符可展开）、元数据（页码、标题路径、Token 数）。

#### Scenario: 结果按文档分组
- **WHEN** 搜索结果来自多个文档
- **THEN** 结果按文档名称分组显示，每组显示文档名称和结果数量

#### Scenario: 分数条可视化
- **WHEN** 结果列表展示
- **THEN** 每条结果旁显示可视化分数条，分数越小（越相似）条越长

#### Scenario: 空结果
- **WHEN** 搜索返回 0 条结果
- **THEN** 结果显示区域显示空结果提示

### Requirement: 提示词预览
页面 SHALL 显示可折叠的提示词预览面板（默认折叠），展示实际发送给 LLM 的完整 messages 数组（每个 message 的 role + content）和复制按钮。

#### Scenario: 提示词面板内容
- **WHEN** 用户展开提示词预览
- **THEN** 显示完整的 system message 和 user message 内容

### Requirement: 加载状态反馈
页面 SHALL 在搜索过程中显示分段加载状态："搜索中..." → "生成回答中..." → 完成。

#### Scenario: 检索阶段加载
- **WHEN** 搜索请求已发送但尚未返回
- **THEN** 发送按钮显示加载状态，文字提示"搜索中..."

#### Scenario: 生成阶段加载
- **WHEN** 检索已完成但 LLM 回答尚未返回
- **THEN** 加载文字变更为"生成回答中..."

### Requirement: 错误状态处理
页面 SHALL 对各种错误状态提供用户友好的提示，包括网络错误、API 错误、chat 禁用等场景。

#### Scenario: API 错误提示
- **WHEN** 搜索请求返回 4xx 或 5xx 错误
- **THEN** 页面显示具体错误信息，不崩溃

#### Scenario: 网络错误提示
- **WHEN** 网络请求失败（fetch error）
- **THEN** 页面显示网络错误提示，用户可重试

### Requirement: 对话历史
页面 SHALL 维护当前会话的对话历史列表，每条对话包含 query + answer + results 组合，可独立展开/折叠。首次加载时显示空状态引导："向知寻提问"。

#### Scenario: 对话历史累积
- **WHEN** 用户连续发送多条查询
- **THEN** 页面上方显示历史对话列表，最新对话在最下方

#### Scenario: 空状态引导
- **WHEN** 页面首次加载且无对话历史
- **THEN** 聊天区域显示空状态引导文字

### Requirement: 分数分布展示
页面 SHALL 显示召回结果的分数分布迷你柱状图，直观展示各分块相似度差异。

#### Scenario: 分数分布显示
- **WHEN** 搜索返回多条结果
- **THEN** 结果显示区域顶部显示迷你柱状图，展示各分块分数的分布情况
