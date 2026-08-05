## ADDED Requirements

> **依赖**：本模块基于 query-rewriting-phase1 的管线。Phase 1 已提供精确词保护、上下文融合、L1 精确缓存、请求去重、审计日志和基础重写详情面板。本模块在 Phase 1 管线中插入意图分类与策略路由、三种重写策略和 L2 语义缓存。

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
QueryRewriter 管线 SHALL 在 Phase 1 的上下文融合之后、保护词还原之前插入策略路由和重写策略执行步骤。策略按路由决策顺序串联执行（前一个策略的输出作为后一个策略的输入）。路由决策为 "direct"（空策略列表）时跳过所有策略。

#### Scenario: 多策略串联执行
- **WHEN** 路由决策包含 normalize + term_align
- **THEN** 先执行 normalize 策略，其输出作为 term_align 的输入，最终结果同时反映两种策略的效果

#### Scenario: 简单查询跳过策略
- **WHEN** 路由决策为 "direct"（空策略列表）
- **THEN** 跳过所有重写策略，直接使用保护词处理后的查询进入后续流程
