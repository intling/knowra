# query-rewriting-phase2 Specification

## Purpose
提供查询重写 Phase 2 进阶能力——意图分类与策略路由、三种重写策略（规范化重述、术语对齐、扩展重述）、L2 语义缓存（含动态 TTL、知识库指纹、跨会话复用、上下文相关性校验、写入时抽样清理）、不满意重试检测，以及前端增强展示（策略颜色区分、意图徽章、缓存层级标签）。

> **依赖**：本模块基于 query-rewriting-phase1 的管线。Phase 1 已提供精确词保护、上下文融合、L1 精确缓存、请求去重、审计日志和基础重写详情面板。

## Requirements

### Requirement: 意图分类与复杂度评分
系统 SHALL 在重写之前通过 LLM 对查询进行意图分类和复杂度评分。意图分为 7 种（factual、analytical、comparative、procedural、exploratory、chitchat、ambiguous），复杂度为 1-10 的整数。分类结果用于策略路由决策。

#### Scenario: 识别事实型查询
- **WHEN** 用户查询为 "Redis 默认端口是多少"
- **THEN** 意图分类返回 intent="factual"、complexity ≤ 2

#### Scenario: 识别分析型查询
- **WHEN** 用户查询为 "为什么系统在高并发下会崩溃"
- **THEN** 意图分类返回 intent="analytical"、complexity ≥ 6

#### Scenario: 识别模糊查询
- **WHEN** 用户查询仅为 "Redis"
- **THEN** 意图分类返回 intent="ambiguous"、complexity ≤ 3

### Requirement: 分层策略路由
系统 SHALL 根据意图和复杂度评分按分层规则选择重写策略。简单查询（complexity ≤ 2 且 intent 为 factual 或 chitchat）跳过重写直接检索；中等查询（complexity 3-5）使用规范重述+术语对齐；模糊查询使用扩展重述。策略选择结果记录在审计日志中。

#### Scenario: 简单事实查询跳过重写
- **WHEN** 意图为 factual、复杂度 ≤ 2
- **THEN** 路由决策为 "direct"（跳过重写），原始查询直接送入检索

#### Scenario: 中等复杂度使用基础策略
- **WHEN** 意图为 procedural、复杂度为 4
- **THEN** 路由决策包含 normalize 和 term_align 策略

#### Scenario: 模糊查询使用扩展重述
- **WHEN** 意图为 ambiguous
- **THEN** 路由决策包含 expand 策略

### Requirement: 规范化重述
系统 SHALL 通过 LLM Prompt 将口语化、碎片化的查询转为书面化、标准化、完整的查询语句。不添加用户未提及的信息，不改变查询意图。保护词必须原样保留。

#### Scenario: 口语转书面
- **WHEN** 用户查询为 "那个数据库怎么搞快点"
- **THEN** 规范化重述输出 "如何提升数据库的性能"

#### Scenario: 省略补全
- **WHEN** 用户查询为 "上次说的那个bug修复了没"
- **THEN** 规范化重述输出 "之前的软件缺陷是否已修复"

### Requirement: 术语对齐
系统 SHALL 将用户查询中的口语化、非正式表达替换为正式的专业术语，使其与知识库中的用词一致。优先使用本地术语表精确匹配（零 LLM 成本），未命中时使用 LLM 对齐。保护词必须原样保留。

#### Scenario: 本地术语表精确替换
- **WHEN** 用户查询包含 "电脑"（本地术语表中映射为 "计算机"）
- **THEN** 术语对齐使用本地映射将 "电脑" 替换为 "计算机/个人电脑"，不调用 LLM

#### Scenario: LLM 术语对齐
- **WHEN** 用户查询包含不在本地术语表中的非正式表达 "怎么让程序跑得更快"
- **THEN** 术语对齐通过 LLM 将 "跑" 替换为 "运行"，输出 "如何让程序运行得更快"

### Requirement: 扩展重述
系统 SHALL 对模糊、简短的查询进行语义扩展，补充同义词、上位概念、相关维度和多角度表述。扩展围绕原始查询意图，不引入无关概念。保护词必须原样保留。

#### Scenario: 简短查询扩展
- **WHEN** 用户查询仅为 "微服务"
- **THEN** 扩展重述输出包含 "微服务架构的设计原则、服务拆分策略、服务间通信方式、服务治理" 等多个相关维度的扩展查询

#### Scenario: 已具体的查询不扩展
- **WHEN** 用户查询已经具体明确（如 "如何配置 Nginx 反向代理到本机 8080 端口"）
- **THEN** 扩展重述判定无需扩展，返回原查询

### Requirement: L2 语义缓存
系统 SHALL 使用向量余弦距离匹配语义相似的查询。当两个查询的向量余弦距离 ≤ 0.05 时视为语义相同，共享重写结果。

#### Scenario: 语义相似命中
- **WHEN** 用户查询 "如何优化数据库性能" 的向量与缓存中 "怎么提升数据库的性能" 的向量余弦距离 ≤ 0.05
- **THEN** 系统返回缓存的重写结果，缓存命中状态记录在 rewrite_info 中

#### Scenario: 语义不相似跳过
- **WHEN** 用户查询与缓存中所有查询的向量余弦距离均 > 0.05
- **THEN** 系统正常执行重写管线

### Requirement: 扩充 RewriteInfo Schema（策略和分类信息）
RewriteInfo Schema SHALL 在 Phase 1 基础上新增意图分类和缓存层级字段。

#### Scenario: RewriteInfo 包含分类信息
- **WHEN** 重写模块执行了意图分类
- **THEN** RewriteInfo 包含 intent: string | null、complexity: number | null、cache_level: "L1" | "L2" | null 字段

### Requirement: 策略标签颜色区分
前端 RewritePanel 中每条改写结果的策略标签 SHALL 按策略类型使用不同颜色区分，便于用户识别改写类型。

#### Scenario: 规范化重述标签
- **WHEN** 改写采用 normalize 策略
- **THEN** 策略标签使用 `bg-blue-100 text-blue-700` 样式

#### Scenario: 术语对齐标签
- **WHEN** 改写采用 term_align 策略
- **THEN** 策略标签使用 `bg-purple-100 text-purple-700` 样式

#### Scenario: 扩展重述标签
- **WHEN** 改写采用 expand 策略
- **THEN** 策略标签使用 `bg-amber-100 text-amber-700` 样式

#### Scenario: 上下文融合标签
- **WHEN** 改写采用 context_fusion 策略
- **THEN** 策略标签使用 `bg-teal-100 text-teal-700` 样式

#### Scenario: 未知策略回退样式
- **WHEN** 改写采用未识别策略
- **THEN** 策略标签使用 `bg-brand-100 text-brand-700` 回退样式

### Requirement: 意图分类展示
前端 RewritePanel 的折叠按钮行 SHALL 展示意图分类的简要信息。

#### Scenario: 展示意图和复杂度
- **WHEN** rewrite_info 包含 intent="analytical"、complexity=7
- **THEN** 折叠按钮行显示 "🔍 分析型 · 复杂度 7" 的小型徽章（`text-xs`）

### Requirement: 缓存层级展示
前端 RewritePanel SHALL 在缓存命中时区分展示命中层级。

#### Scenario: L1 精确命中展示
- **WHEN** rewrite_info.cache_hit 为 true 且 cache_level 为 "L1"
- **THEN** 面板展示 "L1 精确命中" 标签

#### Scenario: L2 语义命中展示
- **WHEN** rewrite_info.cache_hit 为 true 且 cache_level 为 "L2"
- **THEN** 面板展示 "L2 语义命中" 标签

### Requirement: 管线扩展（模块二叠加策略路由和重写策略）
QueryRewriter 管线 SHALL 在 Phase 1 的上下文融合之后、保护词还原之前插入策略路由和重写策略执行步骤。策略执行遵循以下规则：

- **并行执行**：normalize 和 term_align 无依赖关系，管线剩余预算 ≥ 16s 时通过 `asyncio.gather` 并行执行，两者接收相同输入（当前查询）。
- **优先级排序**：预算不足（< 16s）或并行条件不满足时，策略按优先级降序串行执行：normalize > term_align > expand。高优先级策略结果作为低优先级策略的输入。
- **硬超时兜底**：每个策略通过 `asyncio.wait_for` 施加硬超时（单个策略超时 = `strategy_timeout`，默认 30s），超时后该策略被丢弃，其余策略继续执行。
- **并行块优先于串行块**：并行 normalize + term_align 执行完毕后，其输出（normalize 结果优先）作为后续串行策略的输入。
- 路由决策为 "direct"（空策略列表）时跳过所有策略。

#### Scenario: normalize + term_align 并行执行
- **WHEN** 路由决策包含 normalize + term_align 且管线剩余预算 ≥ 16s
- **THEN** normalize 和 term_align 通过 `asyncio.gather` 并行执行，两者接收相同的当前查询作为输入，并行块执行完毕后 normalize 的结果作为后续策略的输入

#### Scenario: 预算紧张时串行回退
- **WHEN** 路由决策包含 normalize + term_align 但管线剩余预算 < 16s
- **THEN** 策略按优先级排序串行执行（normalize 先于 term_align），term_align 接收 normalize 的输出作为输入

#### Scenario: 策略硬超时隔离
- **WHEN** 某个策略（如 normalize）执行时间超过 `asyncio.wait_for` 硬超时
- **THEN** 该策略被 `TimeoutError` 丢弃，其余策略（如 term_align）正常继续执行，不会被阻塞

#### Scenario: 优先级排序（预算紧张时）
- **WHEN** 路由决策包含 expand + normalize 且预算不足以并行
- **THEN** 策略按优先级重新排序为 normalize → expand（normalize 优先级 0，expand 优先级 2），高优先级策略先执行

#### Scenario: 三策略全量执行（并行 + 串行）
- **WHEN** 路由决策包含 normalize + term_align + expand 且预算 ≥ 16s
- **THEN** normalize 和 term_align 先并行执行（Step 4a），expand 后串行执行（Step 4b），expand 接收 normalize 的输出作为输入

#### Scenario: 简单查询跳过策略
- **WHEN** 路由决策为 "direct"（空策略列表）
- **THEN** 跳过所有重写策略，直接使用保护词处理后的查询进入后续流程

### Requirement: 动态 TTL 策略
缓存系统 SHALL 按内容类型采用差异化 TTL，而非使用统一固定 TTL。内容类型分为通用知识（30 分钟）、上下文依赖（5 分钟）、搜索结果（10 分钟）。零向量查询 SHALL NOT 被缓存。各类型 TTL 均可通过环境变量独立配置。

#### Scenario: 通用知识缓存 30 分钟
- **WHEN** L2 缓存写入一条通过上下文相关性校验的通用知识缓存条目
- **THEN** 该条目的 TTL 为 `QUERY_REWRITE_CACHE_TTL_GENERAL_KNOWLEDGE` 秒（默认 1800），在 TTL 内可被跨会话复用

#### Scenario: 上下文依赖缓存 5 分钟
- **WHEN** 缓存条目被标记为 `context_dependent`（依赖特定对话历史背景）
- **THEN** 该条目的 TTL 为 `QUERY_REWRITE_CACHE_TTL_CONTEXT_DEPENDENT` 秒（默认 300），且仅写入 L1 会话绑定缓存，不进入 L2 跨会话缓存

#### Scenario: 搜索结果缓存 10 分钟
- **WHEN** 缓存条目包含语义搜索结果（向量检索结果 + LLM 回答）
- **THEN** 该条目的 TTL 为 `QUERY_REWRITE_CACHE_TTL_SEARCH` 秒（默认 600）

#### Scenario: 零向量不缓存
- **WHEN** 查询向量化后为零向量（全零向量）
- **THEN** 系统跳过缓存写入，不将零向量条目写入任何缓存层级，记录 `zero_vector_skip_cache` 日志事件

#### Scenario: TTL 过期后缓存未命中
- **WHEN** 缓存条目已超过其内容类型对应的 TTL
- **THEN** 缓存查询返回未命中，过期条目在读取时惰性删除或写入时抽样清理

### Requirement: 知识库指纹（Fingerprint）缓存失效
系统 SHALL 维护知识库指纹（`kb_fingerprint`）——基于当前所有活跃文档的 `(doc_id, updated_at)` 列表计算的 SHA-256 哈希。L2 语义缓存命中后 SHALL 额外校验缓存条目的指纹与当前指纹是否一致，不一致则丢弃缓存条目并回退到正常重写管线。

#### Scenario: 指纹一致时缓存有效
- **WHEN** L2 缓存命中且缓存条目的 `kb_fingerprint` 与当前知识库指纹一致
- **THEN** 缓存条目通过指纹校验，继续后续的上下文相关性校验和 TTL 检查

#### Scenario: 文档更新后指纹不一致导致缓存失效
- **WHEN** 用户上传/删除/替换文档导致知识库指纹变化，L2 缓存命中但缓存的指纹与当前指纹不一致
- **THEN** 缓存条目被惰性删除，记录 `l2_fingerprint_mismatch` 审计事件，系统回退到正常重写管线

#### Scenario: 指纹机制仅影响 L2 缓存
- **WHEN** L1 精确缓存查询
- **THEN** 不校验知识库指纹（L1 缓存为会话绑定、短 TTL，同一会话内知识库不会在 TTL 内变更）

#### Scenario: 指纹机制可配置关闭
- **WHEN** `QUERY_REWRITE_CACHE_FINGERPRINT_ENABLED` 设置为 false
- **THEN** L2 缓存跳过指纹校验，仅依赖语义相似度和上下文相关性校验

### Requirement: L2 缓存知识库版本感知
L2 语义缓存的跨会话复用 SHALL 在原有语义相似度校验和上下文相关性校验的基础上，增加知识库版本感知层。只有语义相似度、知识库指纹、上下文相关性、动态 TTL 四层校验全部通过，才返回缓存命中。

#### Scenario: 四层校验全部通过才命中
- **WHEN** L2 缓存查询命中一个语义相似的条目
- **THEN** 系统依次校验：1) 向量余弦距离 ≤ 0.05 → 2) kb_fingerprint 匹配 → 3) 上下文相关性校验通过（LLM 轻量判断答案不依赖特定历史背景）→ 4) 动态 TTL 未过期。全部通过后才返回缓存命中

#### Scenario: 任一校验失败回退重写
- **WHEN** L2 缓存查询的指纹校验或上下文校验或 TTL 校验失败
- **THEN** 系统跳过该缓存条目，回退到正常重写管线

### Requirement: 写入时抽样清理
缓存系统 SHALL 在每次写入操作时以可配置的概率触发轻量过期条目清理扫描，而非依赖后台定时线程。清理包括移除 TTL 过期条目和指纹不匹配条目。

#### Scenario: 写入触发抽样清理
- **WHEN** `CacheManager.store()` 被调用且随机数 < `QUERY_REWRITE_CACHE_SAMPLING_CLEANUP_RATIO`（默认 0.1）
- **THEN** 系统执行一次清理扫描：移除 TTL 过期的条目和 kb_fingerprint 不匹配的条目，单次扫描最多处理 `QUERY_REWRITE_CACHE_MAX_CLEANUP_SCAN`（默认 500）个条目

#### Scenario: 抽样概率为 0 时跳过清理
- **WHEN** `QUERY_REWRITE_CACHE_SAMPLING_CLEANUP_RATIO` 设置为 0
- **THEN** 写入时跳过清理扫描，过期条目仅通过读取时惰性删除回收

#### Scenario: 清理不影响写入延迟
- **WHEN** 写入时触发抽样清理
- **THEN** 清理扫描耗时 < 1ms（遍历上限 500 条目），对缓存写入路径的延迟影响可忽略
