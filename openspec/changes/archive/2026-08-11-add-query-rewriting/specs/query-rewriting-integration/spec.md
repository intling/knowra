## ADDED Requirements

> **依赖**：本模块基于 query-rewriting-phase1 和 query-rewriting-phase2 的管线。Phase 1 已提供精确词保护、上下文融合、L1 精确缓存、请求去重、审计日志和基础重写详情面板。Phase 2 已提供意图分类与路由、三种重写策略、L2 语义缓存和增强的前端展示。本模块添加质量评估与回溯机制，完成 SearchService 的完整集成和端到端验收。

### Requirement: 改写质量评估
系统 SHALL 通过 LLM 对每条改写结果进行 5 维质量评分：语义保留度、清晰度提升、信息增量、术语准确性、可检索性（各 1-5 分）。总分 ≥ 20 为 excellent，15-19 为 good，10-14 为 marginal（建议回溯），<10 为 poor（丢弃改写，回退原始查询）。语义保留度 < 3 时自动判定为 poor 并丢弃。

#### Scenario: 高质量改写通过
- **WHEN** 改写质量总分为 22 且语义保留度为 5
- **THEN** 改写结果被保留并传递给检索模块，质量分数记录在审计日志中

#### Scenario: 低质量改写丢弃
- **WHEN** 改写语义保留度为 2（语义严重偏离原始意图）
- **THEN** 该改写结果被自动丢弃，回退使用原始查询进行检索

#### Scenario: marginal 改写触发回溯
- **WHEN** 改写质量总分为 12
- **THEN** 该改写结果被丢弃，系统升级重写策略（如从规范重述升级为扩展重述）重新改写

### Requirement: 确定性预检查
系统 SHALL 在 LLM 质量评估之前先执行确定性预检查（零 LLM 成本）：关键词留存率检查（基于 2-gram 中文分词 + 子串包含判定）和长度比例检查。预检查不通过的改写可直接丢弃，跳过 LLM 评估。关键词留存率阈值 SHALL 按意图类型分层设置：procedural/chitchat/ambiguous 使用较低阈值（0.50–0.55），factual 使用较高阈值（0.80），其他意图使用默认值（0.70）。

#### Scenario: 关键词留存率低于阈值直接丢弃
- **WHEN** 改写结果的关键词留存率 < 意图对应的分层阈值（如 factual 意图的 0.80）
- **THEN** 该改写结果被直接丢弃，不进入 LLM 质量评估

#### Scenario: 2-gram 中文分词正确识别有意义 token
- **WHEN** 原始查询为"基本操作"，改写结果为"基本用户操作指南"
- **THEN** 2-gram 分词提取 token 列表 ["基本","本操","操作"]，通过子串包含判定后留存率为 2/3 ≈ 0.67（"基本"和"操作"均在改写结果中找到）

#### Scenario: procedural 意图使用较低分层阈值
- **WHEN** 查询意图为 procedural 且关键词留存率为 0.60
- **THEN** 留存率 0.60 ≥ procedural 阈值 0.50，预检查通过（若使用默认阈值 0.70 则会被拒绝）

#### Scenario: factual 意图使用较高分层阈值
- **WHEN** 查询意图为 factual 且关键词留存率为 0.75
- **THEN** 留存率 0.75 < factual 阈值 0.80，预检查不通过，改写被丢弃

#### Scenario: 长度比例异常标记可疑
- **WHEN** 改写长度 < 原始长度的 30% 或 > 原始长度的 500%
- **THEN** 该改写结果被标记为可疑，降低后续 LLM 评估的通过阈值

### Requirement: 回溯限制
质量不合格触发回溯时，系统 SHALL 限制最多回溯 1 次（配置项 `QUERY_REWRITE_QUALITY_MAX_BACKTRACK_ATTEMPTS`，默认 1）。二次失败直接丢弃改写结果，回退使用原始查询，不无限回溯。

### Requirement: 单策略 normalize 降级快速路径
当仅执行 normalize 一个策略且确定性预检查失败时，系统 SHALL 接受改写结果为 ``quality_fallback``，不触发回溯或不丢弃。normalize 仅为清理/补全，不应因形式化预检（如关键词留存率）而被丢弃。

#### Scenario: normalize 策略预检失败仍接受结果
- **WHEN** 仅 normalize 策略执行且关键词留存率低于阈值导致预检查失败
- **THEN** 改写结果被接受，``RewriteResult.quality_fallback`` 设为 True，不触发回溯升级

#### Scenario: normalize + expand 同时执行时预检失败按正常逻辑处理
- **WHEN** normalize 和 expand 策略同时执行且预检查失败
- **THEN** 不在快速路径范围内，按正常逻辑丢弃或触发回溯

#### Scenario: 首次回溯升级策略
- **WHEN** 改写质量总分为 12（marginal）且为首次失败
- **THEN** 系统升级策略（如从 normalize 升级为 expand）重新改写

#### Scenario: 二次失败直接丢弃
- **WHEN** 回溯后的改写质量总分仍 < 15
- **THEN** 系统丢弃改写结果，回退使用原始查询，不再重试

### Requirement: 质量评估降级兜底
当质量评估本身的 LLM 调用失败（超时或 API 错误）时，系统 SHALL 保守接受改写结果，避免因评估器故障丢弃有效改写。

#### Scenario: 评估 LLM 调用失败时保守接受
- **WHEN** 质量评估 LLM 调用抛出异常
- **THEN** 系统记录警告日志，保守接受改写结果并继续后续流程

### Requirement: 结构化质量评分 Schema
RewriteInfo SHALL 包含结构化的 `QualityScores` 模型，提供 5 维评分的详细数据。``rewrite_info`` SHALL 包含 ``quality_fallback`` 布尔字段，指示改写结果是否通过单策略 normalize 降级快速路径被接受。

#### Scenario: QualityScores 结构完整
- **WHEN** 前端从 API 接收 rewrite_info.quality_scores 数据
- **THEN** QualityScores 包含 semantic_preservation: number、clarity_improvement: number、information_gain: number、term_accuracy: number、retrievability: number、total_score: number、verdict: "excellent" | "good" | "marginal" | "poor"、issues: string[] 字段

#### Scenario: quality_fallback 标记
- **WHEN** 仅 normalize 策略执行且预检失败，改写被快速路径接受
- **THEN** rewrite_info.quality_fallback 为 true，表示该改写结果通过降级快速路径保留

### Requirement: 质量评分可视化展示
前端 RewritePanel SHALL 在每条改写结果下方展示对应的质量评分，颜色按等级区分。

#### Scenario: 优秀评分展示
- **WHEN** 改写质量 total_score ≥ 20（excellent）
- **THEN** 评分数字使用 `text-emerald-600` 颜色和 `font-mono tabular-nums` 等宽数字字体

#### Scenario: 良好评分展示
- **WHEN** 改写质量 total_score 15-19（good）
- **THEN** 评分数字使用 `text-amber-600` 颜色

#### Scenario: 需改进评分展示
- **WHEN** 改写质量 total_score < 15（marginal 或 poor）
- **THEN** 评分数字使用 `text-red-600` 颜色

### Requirement: 评分维度详情展开
前端 RewritePanel SHALL 提供可展开的 5 维度评分详情，以条形图形式展示各维度得分。

#### Scenario: 5 维度条形图展示
- **WHEN** 用户点击展开评分详情
- **THEN** 展示 5 个维度（语义保留度、清晰度提升、信息增量、术语准确性、可检索性）的评分条形图：`bg-neutral-200` 底色 + 彩色填充 `rounded-full h-1.5`

### Requirement: 回溯提示展示
前端 RewritePanel SHALL 在改写结果因质量不足触发回溯时展示提示信息。

#### Scenario: 回溯提示
- **WHEN** 改写质量触发了一次回溯升级策略
- **THEN** 面板展示提示文字（`text-xs text-amber-500`）"已自动升级策略重新改写"

### Requirement: QueryRewriter 管线完整集成（模块三）
QueryRewriter 管线 SHALL 在模块二的每条策略执行后调用 Postprocessor.evaluate() 进行三层递进式安全网检查：确定性预检查（含 2-gram 分词留存率 + 分层阈值 + 长度比例检查）→ LLM 质量评估 → 降级兜底。单策略 normalize 执行且预检失败时走快速路径（quality_fallback）。质量评估结果存储在 RewriteResult.quality_scores 中。

#### Scenario: 完整管线执行
- **WHEN** QueryRewriter.rewrite() 被调用
- **THEN** 管线按照 精确词保护 → L1/L2 缓存查询 → 请求去重 → 上下文融合 → 意图分类 → 策略路由 → 策略执行（并行 normalize+term_align 优先 → 串行剩余策略，各策略含 ``asyncio.wait_for`` 硬超时）→ Postprocessor 评估 → 保护词还原 → 缓存写入 → 审计日志 的顺序执行

#### Scenario: 策略硬超时不影响管线完整性
- **WHEN** 某个策略因 ``asyncio.wait_for`` 硬超时被丢弃
- **THEN** 管线继续执行剩余策略和后续步骤（Postprocessor 评估、保护词还原等），不因单个策略超时而中断整个 rewrite 流程

#### Scenario: 质量分数正确传递
- **WHEN** Postprocessor 完成质量评估
- **THEN** RewriteResult.quality_scores 包含完整的 QualityScores 数据，并正确传递到 SearchResponse.rewrite_info 中

### Requirement: SearchService 完整集成
SearchService.search() SHALL 完整集成 QueryRewriter 的全部功能（模块一 + 模块二 + 模块三的质量评估与回溯）。search_time_ms 包含完整重写管线的耗时。

#### Scenario: 全功能集成流程
- **WHEN** SearchService.search() 被调用且所有重写功能启用
- **THEN** 流程为：完整查询重写（含质量评估+回溯）→ 查询向量化 → 检索 → LLM 生成，SearchResponse 包含完整的 rewrite_info（含 intent、complexity、cache_level、quality_scores）

#### Scenario: 回溯不影响 search_time_ms 语义
- **WHEN** 重写过程中触发了回溯升级策略
- **THEN** search_time_ms 包含原始重写+回溯+重新评估的全部耗时，rewrite_time_ms 独立记录重写模块总耗时

### Requirement: 端到端日志链路完整性
系统 SHALL 确保从请求到响应的审计日志链路完整可追溯。同一请求的所有日志事件 SHALL 共享相同的 trace_id。

#### Scenario: 完整链路日志
- **WHEN** 一次完整的搜索请求完成（含重写）
- **THEN** 日志文件中包含相同 trace_id 的以下事件：query_rewrite_complete、strategy_rewrite_complete（如有）、quality_evaluation_complete（如有），各事件包含 prompt_versions、token 消耗和耗时字段

### Requirement: 评分缺失时前端容错
前端 RewritePanel SHALL 在 quality_scores 为 null 或不存在时不崩溃，仅隐藏评分相关 UI。

#### Scenario: 评分缺失时隐藏评分区域
- **WHEN** rewrite_info.quality_scores 为 null
- **THEN** RewritePanel 正常展示改写结果，仅不渲染质量评分和维度详情区域
