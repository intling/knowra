## Purpose

提供查询重写（Query Rewriting）能力——在用户查询进入向量化检索之前，通过精确词保护、上下文融合、L1 精确缓存和请求去重等机制对查询进行优化改写，提升语义搜索的召回质量。

## Requirements

### Requirement: 精确词保护
系统 SHALL 在查询重写前后自动识别并保护技术术语、专有名词和代码标识符，防止被 LLM 意外替换或翻译。识别通过正则匹配（版本号、IP 地址、全大写缩写、驼峰命名、路径/URL）和可配置的自定义词汇表完成。保护流程为：匹配 → 占位符替换 → LLM 重写 → 占位符还原，零 LLM 成本。

#### Scenario: 专有名词在重写中原样保留
- **WHEN** 用户查询包含 "JVM 参数怎么调优"
- **THEN** 精确词保护将 "JVM" 替换为占位符后传给 LLM 重写，重写完成后还原为 "JVM"，最终结果中 "JVM" 原样保留、未被翻译或替换

#### Scenario: 多术语同时保护
- **WHEN** 用户查询包含多个保护词（如 "SpringBoot"、"K8s"、"@Autowired"）
- **THEN** 所有保护词均被正确标记和还原，重写结果中所有术语原样保留

#### Scenario: 无保护词时透传
- **WHEN** 用户查询不包含任何可匹配的保护词
- **THEN** 查询直接进入后续处理流程，不执行占位符替换，不影响正常重写

### Requirement: 上下文融合
系统 SHALL 在多轮对话场景中，将用户含有指代词（它、那个、这个、其等）或省略主题的当前查询与对话历史融合，改写为独立、完整、不依赖上下文的查询。融合通过 LLM Prompt 实现，仅当查询中包含指代词或明显省略主题时触发。

#### Scenario: 指代词消解
- **WHEN** 对话历史为 "Nginx 配置文件的默认路径是什么"，当前查询为 "它的配置怎么改"
- **THEN** 上下文融合将当前查询改写为 "Nginx 配置文件的配置如何修改"，指代词 "它" 被替换为对话历史中的具体实体 "Nginx 配置文件"

#### Scenario: 无指代词时透传
- **WHEN** 当前查询为独立完整的 "如何配置 Nginx 反向代理"
- **THEN** 上下文融合返回原查询文本，不做修改

#### Scenario: 对话历史为空时跳过
- **WHEN** 当前查询不含指代词且对话历史为空
- **THEN** 上下文融合步骤被完全跳过，不调用 LLM

### Requirement: L1 精确缓存
系统 SHALL 使用内存 LRU 缓存存储查询文本 SHA256 哈希到重写结果的精确映射。命中时直接返回缓存结果，跳过所有重写步骤。

#### Scenario: 精确缓存命中
- **WHEN** 用户发出与之前完全相同（逐字符匹配）的查询
- **THEN** 系统返回缓存的重写结果，不调用 LLM，缓存命中状态记录在 rewrite_info 中

#### Scenario: 精确缓存未命中
- **WHEN** 用户发出新查询（未在缓存中）
- **THEN** 系统正常执行重写管线，重写完成后将结果写入 L1 缓存

### Requirement: 请求去重
系统 SHALL 在时间窗口（默认 100ms）内对完全相同或语义相似的并发请求进行去重合并，合并后的请求共享同一份重写结果，避免重复计算。

#### Scenario: 并发相同请求合并
- **WHEN** 在 100ms 时间窗口内收到两个完全相同的查询 "如何优化数据库性能"
- **THEN** 第二个请求等待第一个请求的重写结果，不发起新的 LLM 调用

### Requirement: 审计日志（仅文件输出，不持久化数据库）
系统 SHALL 为每次查询重写记录结构化审计日志，包含 trace_id、原始查询、查询哈希、保护词列表、上下文使用标记、意图标签、复杂度分数、执行的策略列表、每条改写的结果/耗时/token、总重写耗时、缓存命中状态和质量评估结果。审计日志 SHALL 仅通过 structlog 输出至日志文件，不持久化到数据库，不创建数据库表。

#### Scenario: 完整审计日志
- **WHEN** 一次查询重写完成（包含上下文融合和精确词保护）
- **THEN** 审计日志包含完整的 trace_id → 输入/输出/策略/耗时/token 链路，所有时间字段单位为毫秒，日志仅写入文件不涉及数据库

#### Scenario: 审计日志不依赖数据库
- **WHEN** 数据库不可用或未配置
- **THEN** 审计日志正常输出至文件，不受影响

### Requirement: 重写模块开关
系统 SHALL 通过 `QUERY_REWRITE_ENABLED` 环境变量控制重写模块的启用/停用。当设置为 `false` 时，重写模块静默跳过，SearchService 行为与未集成重写模块时完全一致。

#### Scenario: 重写模块禁用时透传
- **WHEN** QUERY_REWRITE_ENABLED=false
- **THEN** SearchService 直接将原始查询送入向量化，SearchResponse.rewrite_info 为 null

### Requirement: LLM 调用失败时跳过重写
当重写过程中任何 LLM 调用失败时，系统 SHALL 静默跳过后续重写步骤，使用原始查询继续检索流程。不抛出异常阻塞用户请求，失败详情记录在日志中。

#### Scenario: 上下文融合 LLM 失败
- **WHEN** 上下文融合 LLM 调用抛出异常（超时或 API 错误）
- **THEN** 系统记录警告日志 "query_rewrite_failed"，使用原始查询继续进行检索，rewrite_info 为 null

### Requirement: 重写模块与 SearchService 集成（模块一轻量版）
SearchService.search() SHALL 在查询向量化（Step 1）之前调用 QueryRewriter.rewrite()。QueryRewriter 返回 RewriteResult 对象，包含 original_query、rewritten_queries（改写后的查询列表）、strategies_used、rewrite_time_ms 和 cache_hit。SearchResponse SHALL 包含 rewrite_info 字段暴露这些信息。

#### Scenario: 正常集成流程
- **WHEN** SearchService.search() 被调用且重写模块已启用
- **THEN** 流程为：查询重写 → 查询向量化（使用 rewrite.rewritten_queries[0]） → 检索 → LLM 生成，SearchResponse 包含非 null 的 rewrite_info

#### Scenario: 重写后多查询检索
- **WHEN** 重写模块返回多个改写结果
- **THEN** SearchService 将原始查询和所有改写结果一并交付检索模块（当前阶段只使用原始查询+首个改写结果进行检索，其余改写结果保留在 rewrite_info 中供前端展示，多结果融合 RRF 属于 Phase 3 检索模块范围）

### Requirement: 重写模块配置独立
系统 SHALL 提供独立的查询重写 LLM 配置，允许使用与 ChatAdapter 相同或不同的模型、temperature 和 max_tokens。默认复用 ChatAdapter 的 api_base_url 和 api_key，但可通过 `QUERY_REWRITE_MODEL`、`QUERY_REWRITE_TEMPERATURE`、`QUERY_REWRITE_MAX_TOKENS` 独立覆盖。

#### Scenario: 使用独立重写模型
- **WHEN** QUERY_REWRITE_MODEL 配置为特定模型名称
- **THEN** QueryRewriter 使用该模型进行所有 LLM 调用，ChatAdapter 仍使用 chat_model 进行回答生成

### Requirement: 查询重写详情面板
系统 SHALL 在 AI 回答区域上方提供一个可折叠的「查询重写详情」面板，展示用户的原始查询如何被重写以及重写元信息。面板默认折叠，当 rewrite_info 存在且 rewritten_queries 列表非空时显示折叠按钮行。

#### Scenario: 有改写时显示面板
- **WHEN** SearchResponse.rewrite_info 非 null 且 rewritten_queries 列表长度 > 0
- **THEN** 在 AI 回答上方渲染可折叠的重写详情面板，折叠按钮行显示改写条数徽章

#### Scenario: 无改写时隐藏面板
- **WHEN** SearchResponse.rewrite_info 为 null 或 rewritten_queries 列表为空
- **THEN** 不渲染重写详情面板

#### Scenario: 默认折叠状态
- **WHEN** 重写详情面板首次渲染
- **THEN** 面板处于折叠状态，仅显示折叠按钮行

### Requirement: 面板视觉风格一致性
重写详情面板的视觉风格 SHALL 与现有 PromptPreview 和 ResultsPanel 面板保持一致，遵循 knowra v2.0 设计系统规范。

#### Scenario: 折叠按钮样式一致
- **WHEN** 重写详情面板渲染
- **THEN** 折叠按钮行使用 `flex w-full items-center justify-between px-5 py-3 text-left transition hover:bg-neutral-50` 样式，与 PromptPreview 切换按钮一致

#### Scenario: 标题样式一致
- **WHEN** 重写详情面板渲染
- **THEN** 标题使用 `font-display text-sm font-semibold text-neutral-700` 样式，图标使用 emoji 前缀

#### Scenario: 展开图标动画一致
- **WHEN** 用户点击折叠按钮
- **THEN** SVG chevron 图标使用 `size-4 text-neutral-400 transition-transform` 样式，展开时添加 `rotate-180`

### Requirement: 原始查询展示
面板展开后 SHALL 展示用户的原始查询文本，以灰色引用样式呈现，让用户可以对比改写前后的差异。

#### Scenario: 展示原始查询
- **WHEN** 重写详情面板展开
- **THEN** 面板内容区域顶部展示 "原始查询" 标签和原始查询文本（`text-sm text-neutral-500 italic`）

### Requirement: 改写结果列表
面板展开后 SHALL 以列表形式展示每条改写结果，列表项之间使用 `divide-y divide-neutral-100` 分隔。每条改写结果包含策略标签、改写后的查询文本。

#### Scenario: 展示改写结果
- **WHEN** rewrite_info.rewritten_queries 包含改写结果
- **THEN** 面板中按顺序展示改写结果，每一条显示对应的策略标签和改写文本

### Requirement: 性能指标展示
面板 SHALL 展示重写耗时和缓存命中状态。

#### Scenario: 展示重写耗时
- **WHEN** rewrite_info.rewrite_time_ms 为 320
- **THEN** 面板底部展示 "重写耗时: 320ms"，使用 `text-xs text-neutral-400` 样式

#### Scenario: 缓存命中展示
- **WHEN** rewrite_info.cache_hit 为 true
- **THEN** 面板展示 "缓存命中: 是"，使用 ⚡ 图标 + `text-emerald-500` 样式

### Requirement: API 类型扩展
前端 TypeScript 类型定义 SHALL 新增 RewriteInfo 接口，作为 SearchResponse 的可选字段。

#### Scenario: RewriteInfo 类型完整
- **WHEN** 前端从 API 接收 rewrite_info 数据
- **THEN** RewriteInfo 类型包含 original_query: string、rewritten_queries: string[]、strategies_used: string[]、rewrite_time_ms: number、cache_hit: boolean 字段

### Requirement: 查询重写管线集成（模块一轻量版）
SearchService.search() SHALL 在查询向量化（Step 1）之前调用 QueryRewriter。模块一的管线流程为：精确词保护 → L1 缓存查询 → 请求去重 → 上下文融合（条件触发）→ 保护词还原 → 写入 L1 缓存 → 审计日志。当 QueryRewriter 成功返回改写结果时，search() 使用改写后的查询进行向量化和检索。

#### Scenario: 重写后的查询用于向量化
- **WHEN** QueryRewriter 成功返回改写查询列表
- **THEN** SearchService 使用改写后的首个查询进行向量化，原始查询和改写列表记录在 SearchResponse.rewrite_info 中

#### Scenario: 重写模块未启用
- **WHEN** QUERY_REWRITE_ENABLED=false
- **THEN** SearchService 跳过 QueryRewriter 调用，直接使用原始查询向量化，流程与集成前完全一致

#### Scenario: 重写失败静默降级
- **WHEN** QueryRewriter.rewrite() 内部 LLM 调用失败
- **THEN** SearchService 记录警告日志后使用原始查询继续检索，rewrite_info 为 null，用户请求正常完成
