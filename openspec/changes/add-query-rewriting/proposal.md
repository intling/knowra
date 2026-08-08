## Why

当前 knowra 的 RAG 管线将用户原始查询**直接送入向量化+检索流程**，缺少查询预处理环节。口语化表达、术语不匹配、多意图纠缠、指代词依赖等问题导致检索结果偏离用户真实意图，进而影响 LLM 回答质量。作为一个以私有知识问答为核心价值的 AI 助手，knowra 需要在检索之前对用户查询进行智能重写和优化，使检索向量更接近知识库中正式文档的语义空间。

本变更聚焦于 Phase 1 + Phase 2（覆盖 80% 日常查询场景），在 SearchService 的查询向量化步骤之前插入查询重写管线，以纯 Prompt 驱动的方式实现分层渐进式查询优化，不引入额外模型训练或复杂 NLP 管线。

## What Changes

- 新增 **QueryRewriter 模块**：顶层编排器，分三模块渐进实现——模块一（精确词保护+上下文融合+L1缓存+请求去重+审计日志），模块二（意图分类+路由+三种重写策略+L2语义缓存），模块三（质量评估+回溯+SearchService完整集成+端到端验收）
- 新增 **ExactTermProtector**：精确词保护（正则+词汇表标记化），零 LLM 成本
- 新增 **ContextRewriter**：多轮对话上下文融合（指代消解），条件触发
- 新增 **StrategyRouter**：LLM 驱动的意图分类（7 种意图）和复杂度评分（1-10），按分层规则选择最优重写策略组合
- 新增 **核心重写策略**（3 种）：规范化重述（口语→书面）、术语对齐（口语→专业术语）、扩展重述（模糊查询→多维度扩展）
- 新增 **CacheManager**：模块一实现会话绑定 L1 精确匹配缓存 + 连续重复意图检测，模块二实现跨会话 L2 语义相似缓存，含微批请求去重
- 新增 **Postprocessor**：改写质量评估（5 维评分），低质量改写自动丢弃或触发回溯（升级策略重新改写）
- 新增 **PromptLoader**：YAML Prompt Catalog 三层降级加载 + 版本注入审计日志
- 新增 **配置项**：~23 个 `QUERY_REWRITE_` 前缀的环境变量已添加至 `config.py`（Settings 字段）
- 新增 **AuditTrail**：每次重写的结构化审计日志（trace_id → 输入/输出/策略/耗时/token/质量分数），仅通过 structlog 输出至日志文件，不持久化到数据库
- 修改 **SearchResponse Schema**：新增 `RewriteInfo` + `RewrittenQuery` Pydantic 模型和 `rewrite_info` 可选字段
- 修改 **SearchService.search()**：在查询向量化之前调用 QueryRewriter，将改写结果传递给检索模块
- 新增 **前端「查询重写详情」面板**：可折叠面板展示改写结果、策略标签、质量评分、性能指标，风格遵循 knowra v2.0 设计系统
- 新增 **前端 API 类型扩展**：`RewriteInfo`、`RewrittenQuery` TypeScript 接口已添加至 `search.ts`

## Capabilities

### New Capabilities
- `query-rewriting`: 查询重写核心能力——在检索之前对用户原始查询进行意图分类、复杂度评分和策略路由，通过规范化重述、术语对齐、扩展重述等策略提升检索准确率，包含精确词保护、上下文融合、缓存去重、质量评估，以及前端可折叠的「查询重写详情」面板

### Modified Capabilities
- `semantic-search`: SearchService 在查询向量化之前集成 QueryRewriter；SearchResponse 新增 rewrite_info 字段暴露重写元信息及连续重复检测标记；SearchRequest 新增 session_id 可选字段用于会话绑定缓存；POST /api/search 的请求 schema 目前不引入 conversation_history 参数（多轮对话上下文由前端在 query 中隐式携带，重写模块通过 ContextRewriter 从历史中消解指代）
- `file-upload-storage`: 新增基于内容 SHA-256 哈希的幂等上传与软删除替换机制——重复上传同一文件（同一用户 + 相同 checksum_sha256）默认幂等返回已有记录（不创建新记录、不产生物理文件副本）；携带 `force` 标记时软删除旧记录并创建新记录；去重仅在 `owner_user_id + checksum_sha256` 维度生效，软删除记录不参与去重匹配。该机制为后续查询重写的知识库指纹（kb_fingerprint）缓存失效提供可靠的数据基础。

## Impact

- **后端新增文件**：`query_rewriter.py`（顶层编排器）、`audit_trail.py`（审计日志）、`query_rewrite_config.py`（配置 dataclass）、`exact_term_protector.py`（精确词保护）、`cache_manager.py`（缓存管理器）、`rewrite_strategies.py`（重写策略集）、`strategy_router.py`（策略路由器）、`prompt_loader.py`（Prompt 加载器）、`postprocessor.py`（后处理器）、`protected_terms_loader.py`（受保护术语加载器）、`term_alignment_loader.py`（术语对齐加载器）
- **后端修改文件**：`config.py`（新增 ~23 个 Settings 字段）、`search.py`（Service 集成 QueryRewriter）、`search.py`（Schema 新增 rewrite_info 字段）、`search.py`（Route 注入 QueryRewriter 依赖）、`uploads.py`（UploadService.create_upload 新增基于 checksum_sha256 的内容去重与 force 软删除替换逻辑）
- **前端新增文件**：`RewritePanel.vue`（组件）、`RewritePanel.spec.ts`（组件测试）、`search.spec.ts`（API 类型测试）
- **前端修改文件**：`search.ts`（API Client 类型扩展）、`ChatArea.vue`（集成 RewritePanel）
- **配置影响**：需新增 ~23 个环境变量（`QUERY_REWRITE_ENABLED` 等），当 `QUERY_REWRITE_ENABLED=false` 时查询重写模块静默跳过，SearchService 行为与当前一致
- **数据模型**：无新增数据库表或 migration；审计日志仅通过 structlog 输出至日志文件（10MB 轮转 × 5 保留），不持久化到数据库
- **API 契约**：SearchResponse 新增 `rewrite_info` 可选字段（向后兼容——不传或为 null 表示未启用重写）；SearchRequest 新增 `session_id` 可选字段（用于缓存绑定和连续重复检测，不传时从 history 自动派生）
- **Depends**：复用现有 ChatAdapter 基础设施（创建独立实例，使用专用 `QueryRewriteConfig` 配置独立的 model/temperature/max_tokens），默认模型与主对话相同但可独立覆盖
- **不做（Phase 3/4 范围外，预计在后续变更中执行）**：HyDE 策略、Multi-Query 生成、子问题分解、后退提示词、对比式重写、Query2Doc、异步改写通道、L3 热点缓存、知识图谱增强、RRF 融合（属于检索模块）。Phase 3 将引入高级重写策略（HyDE、Multi-Query、子问题分解等）和多结果 RRF 融合；Phase 4 将实现异步双通道改写（快速通道+增强通道）及 L3 热点缓存
