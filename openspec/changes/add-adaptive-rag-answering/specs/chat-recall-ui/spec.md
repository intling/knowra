## MODIFIED Requirements

### Requirement: 对话召回验证页面路由
系统 SHALL 将对话召回验证功能内嵌至主页面 `/` 的 ChatArea 中，不再作为独立 `/chat` 路由页面。每轮 SHALL 展示 AI 回答；存在资料依据时在其后展示来源列表和默认折叠的检索详情。通用回答与澄清 SHALL 使用回答模式说明替代空来源告警；缺少模式字段的旧对话保持兼容展示。

#### Scenario: 页面可访问
- **WHEN** 用户导航至 `/`
- **AND** 用户在对话区发送问题并收到回答
- **THEN** 资料回答在用户问题下方依次出现 AnswerPanel、SourceList 与"检索详情"入口；通用回答不渲染空来源区
- **AND** 不再通过 `/chat` 路由访问独立对话页

### Requirement: AI 回答展示
页面 SHALL 在对话消息流中显示 Markdown 回答，存在资料依据时展示引用统计（引用 N 个分块 · 来自 K 个文档）、Token 总数和复制按钮。K SHALL 按本轮检索结果中不同 `parsed_document_id` 的数量计算，而不是"被搜索文档数"。Token 明细（prompt / completion）SHALL 通过悬停提示和读屏文本提供，不在底栏常显。

#### Scenario: 显示回答
- **WHEN** 搜索成功
- **THEN** 对话流中用户问题下方显示 AI 回答，包含 Markdown 渲染的回答文本、存在资料依据时的引用统计，以及真实生成的 Token 总数

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

#### Scenario: 通用回答不显示零引用
- **WHEN** `answer_mode=general` 且没有资料来源
- **THEN** 显示“基于通用知识”，省略零引用统计，保留正文、复制和真实 token 用量

#### Scenario: 澄清不伪造生成信息
- **WHEN** `answer_mode=clarification`
- **THEN** 显示可操作的澄清正文，省略零引用统计、模型用量与空来源告警

### Requirement: 回答来源列表
页面 SHALL 在每条有资料来源的 AI 回答正下方直接展示来源列表（无需展开调试面板），按 `parsed_document_id` 聚合本轮检索结果，展示编号、文档名、页码、分块编号与片段预览，并允许展开查看原始分块全文。

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
- **WHEN** 本轮 results 为空且 `answer_mode=general` 或 `clarification`
- **THEN** 主对话不挂载空来源列表，不显示红色无依据告警
- **AND** 缺少 `answer_mode` 的旧对话保留原有空来源提示

### Requirement: 检索详情收纳
页面 SHALL 将资料回答的查询改写、检索结果与提示词预览收纳在回答下方单一的"检索详情"折叠区中，默认折叠；折叠控件 SHALL 为带 `aria-expanded` 的按钮，并在折叠状态下显示简要摘要。

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

#### Scenario: 通用回答省略空检索详情
- **WHEN** 回答为通用模式且没有资料来源
- **THEN** 不显示“0 个片段”的检索详情栏

#### Scenario: 总结不展示伪造相似度
- **WHEN** `answer_mode=summary`
- **THEN** 展示总结范围和来源，不把内容选取顺序或占位分数展示为语义检索排名

## ADDED Requirements

### Requirement: 总结覆盖与回答归属说明

页面 SHALL 根据结构化回答模式展示归属。总结 SHALL 显示实际覆盖的文档数量，覆盖不完整时轻量说明“基于部分资料总结”。检索失败降级 SHALL 标注“资料检索暂不可用，本次基于通用知识回答”。欢迎说明和输入框提示 SHALL 允许普通提问，不再承诺每次回答都依据资料。

#### Scenario: 部分覆盖可见
- **WHEN** `answer_mode=summary` 且 `summary_coverage.truncated=true`
- **THEN** 显示“基于部分资料总结”和覆盖文档数量，真实来源仍可展开

#### Scenario: 检索不可用有独立提示
- **WHEN** `answer_mode=general` 且 `retrieval_status=unavailable`
- **THEN** 展示检索暂不可用的轻量说明，不将故障表述为资料不存在

#### Scenario: 欢迎页支持普通提问
- **WHEN** 用户首次进入主对话
- **THEN** 欢迎说明表达可以直接提问，上传资料可增强回答，并保留资料工作流引导

### Requirement: 不完整回答可见

页面 SHALL 在 `answer_incomplete=true` 时保留 Markdown 正文、来源与复制，并在正文前提示“回答尚未完成”和下一步。未提供该字段的旧记录沿用原展示。总结输入覆盖 SHALL 表述为已提供给模型的资料，不能暗示正文完整性。

#### Scenario: 输出中止仍可核对正文
- **WHEN** 返回正文和 `answer_incomplete=true`
- **THEN** 显示不完整提示、已有正文与来源，完整答案和旧记录不出现该提示
