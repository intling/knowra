## Purpose

在主页面对话流中展示 Markdown 回答和可追溯的原文来源，将改写、检索分数及提示词收纳在默认折叠的检索详情内，支持检查端到端 RAG 的输入输出。

## Requirements

### Requirement: 对话召回验证页面路由
系统 SHALL 将对话召回验证功能内嵌至主页面 `/` 的 ChatArea 中，不再作为独立 `/chat` 路由页面。每轮回答在对话流中 SHALL 依次展示：AI 回答（AnswerPanel）、来源列表（SourceList）、默认折叠的检索详情（RetrievalDetails，内含查询改写、检索结果与提示词预览）。

#### Scenario: 页面可访问
- **WHEN** 用户导航至 `/`
- **AND** 用户在对话区发送问题并收到回答
- **THEN** 用户问题下方依次出现 AnswerPanel、SourceList 与"检索详情"入口
- **AND** 不再通过 `/chat` 路由访问独立对话页

### Requirement: 文本输入与发送
页面 SHALL 提供文本输入框，按 Enter 发送，Shift+Enter 或 Ctrl/Cmd+Enter 插入换行；也可点击发送按钮发送。没有已上传附件时禁止发送空文本（仅含空白字符也视为空文本）。Top-K（1–50，默认 5）在设置弹层中调节。

#### Scenario: Enter 发送
- **WHEN** 用户在输入框中按下 Enter（未按 Shift、Ctrl 或 Cmd，且未处于输入法组字状态）
- **AND** 输入框内容非空（去掉首尾空白后仍有内容）
- **THEN** 系统发送搜索请求，输入框内容作为 query

#### Scenario: Shift/Ctrl/Cmd+Enter 换行
- **WHEN** 用户在输入框中按下 Shift+Enter、Ctrl+Enter 或 Cmd+Enter
- **THEN** 输入框内插入换行符，不发送请求

#### Scenario: 输入法候选确认不发送
- **WHEN** 用户组字时按 Enter 确认候选词，事件 `isComposing=true` 或 keyCode 为 229
- **THEN** 不发送请求并保留输入草稿

#### Scenario: 点击按钮发送
- **WHEN** 用户点击发送按钮
- **AND** 输入框内容非空
- **THEN** 系统发送搜索请求

#### Scenario: 空文本无法发送
- **WHEN** 输入框内容为空或仅含空白字符，且没有已上传附件
- **THEN** 发送按钮处于禁用状态，按 Enter 不触发发送

#### Scenario: Top-K 调整
- **WHEN** 用户打开设置弹层并把 Top-K 滑块调至 10
- **THEN** 下一条搜索请求中 top_k=10

### Requirement: AI 回答展示
页面 SHALL 在对话消息流中显示 AI 回答，包含 Markdown 渲染的回答内容、引用统计（引用 N 个分块 · 来自 K 个文档）、Token 总数和复制按钮。K SHALL 按本轮检索结果中不同 `parsed_document_id` 的数量计算，而不是"被搜索文档数"。Token 明细（prompt / completion）SHALL 通过悬停提示和读屏文本提供，不在底栏常显。

#### Scenario: 显示回答
- **WHEN** 搜索成功
- **THEN** 对话流中用户问题下方显示 AI 回答，包含 Markdown 渲染的回答文本、引用统计和 Token 总数

#### Scenario: 引用统计按引用文档去重计数
- **WHEN** 本轮返回 2 个检索结果，均来自同一 `parsed_document_id`，而 `searched_document_count` 为 3
- **THEN** 引用统计显示"引用 2 个分块 · 来自 1 个文档"

#### Scenario: Token 底栏只显示总数
- **WHEN** answer_tokens 为 prompt 500、completion 200、total 700
- **THEN** Token 统计可见文本显示 700 及 "tokens"，不显示 "prompt"、"completion" 字样
- **AND** 悬停提示（title）中包含 prompt 500 与 completion 200 的明细

#### Scenario: Markdown 列表与表格正常呈现
- **WHEN** 回答包含有序列表、无序列表、表格和代码块
- **THEN** 有序列表显示数字序号（`list-style-type: decimal`），无序列表显示圆点（`list-style-type: disc`）
- **AND** 表格有行分隔线并可在窄屏横向滚动，代码块可横向滚动，均不撑破页面宽度

### Requirement: 检索结果面板
页面 SHALL 在"检索详情"内提供可折叠的检索结果面板（默认折叠），包含搜索摘要栏（搜索 N 个文档 · M 个向量 · 耗时 T ms）和按文档分组的结果列表，每条结果展示排名、相似度分数条、分块文本（可展开全文）、元数据（页码、标题路径、Token 数、分块编号）。

#### Scenario: 结果按文档分组
- **WHEN** 搜索结果来自多个文档
- **THEN** 结果按文档名称分组显示，每组显示文档名称和结果数量

#### Scenario: 分数条按相似度计算
- **WHEN** 结果列表展示，某结果余弦距离 score=0.2
- **THEN** 该结果分数条宽度为 80%（相似度 = 1 − score）

#### Scenario: 最不相似的结果分数条不为空
- **WHEN** 本轮结果距离分别为 0.2 和 0.6
- **THEN** 两条分数条宽度分别为 80% 与 40%，距离最大的结果不显示为 0%

#### Scenario: 分数条宽度限制在 0–100%
- **WHEN** 某结果距离大于 1（如 1.2）或小于 0（如 -0.1）
- **THEN** 分数条宽度分别为 0% 与 100%

#### Scenario: 空结果
- **WHEN** 搜索返回 0 条结果
- **THEN** 不渲染检索结果面板，来源列表显示"无资料依据"提示

#### Scenario: 默认折叠状态
- **WHEN** 用户展开"检索详情"
- **THEN** 检索结果面板仍处于折叠状态，用户需手动点击展开

### Requirement: 提示词预览
页面 SHALL 在"检索详情"内显示可折叠的提示词预览面板（默认折叠），展示实际发送给 LLM 的完整 messages 数组（每个 message 的 role + content）和复制按钮。

#### Scenario: 提示词面板内容
- **WHEN** 用户展开检索详情并展开提示词预览
- **THEN** 显示完整的 system message 和 user message 内容

#### Scenario: 默认折叠状态
- **WHEN** AI 回答展示完成后
- **THEN** 提示词预览不可见，直到用户先展开"检索详情"再展开该面板

### Requirement: 加载状态反馈
页面 SHALL 在搜索过程中显示分段加载状态：检索中 → 生成回答中 → 完成。可见阶段文案显示在回答占位区；发送按钮显示加载指示并保留读屏可读的阶段文本。

#### Scenario: 检索阶段加载
- **WHEN** 搜索请求已发送但尚未返回
- **THEN** 回答占位区显示"正在检索资料…"
- **AND** 发送按钮禁用，并包含读屏文本"搜索中…"

#### Scenario: 生成阶段加载
- **WHEN** 检索已完成但 LLM 回答尚未返回
- **THEN** 回答占位区文案变更为"正在生成回答…"

#### Scenario: 加载期间不能重复发送
- **WHEN** 当前对话存在尚未返回的请求
- **THEN** 发送按钮禁用，按 Enter 不会发出第二个请求

### Requirement: 错误状态处理
页面 SHALL 对各种错误状态提供用户友好的提示，包括网络错误、API 错误、chat 禁用等场景。

#### Scenario: API 错误提示
- **WHEN** 搜索请求返回 4xx 或 5xx 错误
- **THEN** 页面显示具体错误信息，不崩溃

#### Scenario: 网络错误提示
- **WHEN** 网络请求失败（fetch error）
- **THEN** 页面显示网络错误提示，用户可重试

### Requirement: 对话历史
页面 SHALL 维护当前会话的对话历史列表，每条对话包含 query + answer + results 组合。对话历史受侧边栏的 useChatStore 管理，支持跨对话切换时保留各自的消息历史。首次加载时显示空状态引导（WelcomeView 欢迎页）。

#### Scenario: 对话历史累积
- **WHEN** 用户在当前对话中连续发送多条查询
- **THEN** 对话区显示完整消息历史，最新消息在最下方

#### Scenario: 切换对话后消息历史独立
- **WHEN** 用户从对话 A 切换到对话 B
- **THEN** 对话区显示对话 B 的消息历史
- **AND** 切换回对话 A 时消息历史完整保留

#### Scenario: 空状态引导
- **WHEN** 页面首次加载且无对话历史
- **THEN** 对话区显示 WelcomeView 欢迎页

### Requirement: 分数分布展示
页面 SHALL 在“检索详情”的检索结果面板内显示召回结果的分数分布迷你柱状图。柱状图 SHALL 保留原始余弦距离，并明确标注“余弦距离，越小越相似”，以区别于单条结果中按 `1 − score` 计算的相似度条。

#### Scenario: 分数分布显示
- **WHEN** 搜索返回多条结果，用户展开检索详情及检索结果面板
- **THEN** 结果区域顶部显示迷你柱状图，展示各分块原始余弦距离的分布
- **AND** 标题为“分数分布（余弦距离，越小越相似）”

### Requirement: 回答来源列表
页面 SHALL 在每条 AI 回答正下方直接展示来源列表（无需展开调试面板），按 `parsed_document_id` 聚合本轮检索结果，展示编号、文档名、页码、分块编号与片段预览，并允许展开查看原始分块全文。

#### Scenario: 来源按文档聚合并编号
- **WHEN** 本轮结果为 3 条，其中 2 条来自文档 A（rank 1、3），1 条来自文档 B（rank 2）
- **THEN** 来源列表显示 2 个来源条目，按首次出现顺序依次为 A（编号 1）、B（编号 2）
- **AND** 标题显示"来源 · 2 份文档"

#### Scenario: 来源条目显示页码与分块编号
- **WHEN** 文档 A 的两个片段页码分别为 [3] 与 [3, 4]，分块序号分别为 12 与 15
- **THEN** 条目显示去重排序后的页码"第 3、4 页"
- **AND** 显示"分块 #12"与"分块 #15"

#### Scenario: 无页码时不显示页码
- **WHEN** 某文档的所有片段 page_numbers 均为空或 null
- **THEN** 该条目不显示页码文案，其他元数据正常显示

#### Scenario: 同名不同 ID 的文档不合并
- **WHEN** 两个结果 document_name 相同但 parsed_document_id 不同
- **THEN** 来源列表显示为两个独立条目

#### Scenario: 默认显示片段预览，展开后显示原文
- **WHEN** 来源列表初次渲染
- **THEN** 每个条目显示首个片段的文本预览，条目按钮 `aria-expanded="false"`
- **WHEN** 用户点击某个条目
- **THEN** `aria-expanded="true"`，并显示该文档每个片段的原始全文，保留原文换行

#### Scenario: 展开原文与 API 文本完全一致
- **WHEN** 用户展开某个来源条目
- **THEN** 每个片段显示 API 返回的 text 原文（不截断、不摘要），并标注其原始检索排名与分块编号

#### Scenario: 多轮回答中的 ARIA ID 唯一
- **WHEN** 同一文档出现在多轮回答的来源列表或检索详情中
- **THEN** 每个展开控件的 aria-controls 指向唯一的区域 ID

#### Scenario: 文档名缺失时的回退
- **WHEN** 某结果 document_name 为空字符串
- **THEN** 条目显示"未命名文档"

#### Scenario: 无检索结果时明确提示无依据
- **WHEN** 本轮 results 为空数组
- **THEN** 来源列表显示"没有检索到相关资料，本回答缺少资料依据。"

### Requirement: 检索详情收纳
页面 SHALL 将查询改写、检索结果与提示词预览收纳在每条回答下方单一的"检索详情"折叠区中，默认折叠；折叠控件 SHALL 为带 `aria-expanded` 的按钮，并在折叠状态下显示简要摘要。

#### Scenario: 默认折叠
- **WHEN** 回答展示完成
- **THEN** "检索详情"按钮 `aria-expanded="false"`
- **AND** 查询改写、检索结果与提示词预览面板均不在页面中渲染

#### Scenario: 折叠状态显示摘要
- **WHEN** 本轮返回 5 个片段，检索耗时 120 ms
- **THEN** "检索详情"按钮上可见"5 个片段"与"120 ms"

#### Scenario: 展开后显示可用的诊断面板
- **WHEN** 用户点击"检索详情"
- **THEN** 按钮 `aria-expanded="true"`
- **AND** 存在 rewrite_info 时显示查询改写面板，结果非空时显示检索结果面板，prompt_messages 非空时显示提示词预览面板

#### Scenario: 无可用诊断数据时省略对应面板
- **WHEN** rewrite_info 为 null 且 prompt_messages 为空，用户展开检索详情
- **THEN** 不渲染查询改写面板与提示词预览面板，仅渲染检索结果面板（若有结果）
