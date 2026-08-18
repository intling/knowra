## 📦 Archive Record

| 字段 | 值 |
|---|---|
| **归档日期** | 2026-08-11 |
| **变更名称** | add-query-rewriting |
| **工作流** | spec-driven |
| **任务完成** | 100/100 |

### 与主 Specs 的关系

本次归档同步了 4 个 delta spec 到主 specs 目录，具体变更如下：

| Delta Spec | 主 Spec 目标 | 操作 | 说明 |
|---|---|---|---|
| `specs/query-rewriting-phase1/spec.md` | `openspec/specs/query-rewriting-phase1/spec.md` | **新建** | 13 个 ADDED requirements：精确词保护、上下文融合、L1 精确缓存、请求去重、审计日志、模块开关、LLM 降级、SearchService 集成、配置独立、重写面板、面板风格、原始查询展示、改写结果列表、性能指标、API 类型扩展、管线集成 |
| `specs/query-rewriting-phase2/spec.md` | `openspec/specs/query-rewriting-phase2/spec.md` | **新建** | 15 个 ADDED requirements：意图分类、策略路由、规范化重述、术语对齐、扩展重述、L2 语义缓存、Schema 扩充、策略颜色、意图展示、缓存层级、管线扩展、动态 TTL、知识库指纹、四层校验、抽样清理 |
| `specs/query-rewriting-integration/spec.md` | `openspec/specs/query-rewriting-integration/spec.md` | **新建** | 13 个 ADDED requirements：质量评估、确定性预检查、回溯限制、normalize 快速路径、降级兜底、QualityScores Schema、评分可视化、维度详情、回溯提示、完整管线、SearchService 集成、日志链路、前端容错 |
| `specs/file-upload-storage/spec.md` | `openspec/specs/file-upload-storage/spec.md` | **追加** | 在已有主 spec 末尾追加 1 个 ADDED requirement：「基于内容哈希的幂等上传与软删除替换」（4 个 scenarios）。该需求为查询重写的知识库指纹（kb_fingerprint）缓存失效提供了数据基础 |
| `specs/query-rewriting-phase1/spec.md` | `openspec/specs/semantic-search/spec.md` | **修改** | 2 个 MODIFIED requirements：扩展「搜索响应元信息」requirement（新增 2 个 scenarios：重写未启用/失败时 rewrite_info=null），在主 spec 中新增「搜索耗时包含重写耗时」requirement |

---

## Why

当前 knowra 的 RAG 管线将用户原始查询**直接送入向量化+检索流程**，缺少查询预处理环节。口语化表达、术语不匹配、多意图纠缠、指代词依赖等问题导致检索结果偏离用户真实意图，进而影响 LLM 回答质量。作为一个以私有知识问答为核心价值的 AI 助手，knowra 需要在检索之前对用户查询进行智能重写和优化，使检索向量更接近知识库中正式文档的语义空间。

本变更聚焦于 Phase 1 + Phase 2（覆盖 80% 日常查询场景），在 SearchService 的查询向量化步骤之前插入查询重写管线，以纯 Prompt 驱动的方式实现分层渐进式查询优化，不引入额外模型训练或复杂 NLP 管线。

## What Changes

- 新增 **QueryRewriter 模块**：顶层编排器，分三模块渐进实现——模块一（精确词保护+上下文融合+L1缓存+请求去重+审计日志），模块二（意图分类+路由+三种重写策略+L2语义缓存），模块三（质量评估+回溯+SearchService完整集成+端到端验收）
- 新增 **ExactTermProtector**：精确词保护（正则+词汇表标记化），零 LLM 成本
- 新增 **ContextRewriter**：多轮对话上下文融合（指代消解），条件触发
- 新增 **StrategyRouter**：LLM 驱动的意图分类（7 种意图）和复杂度评分（1-10），按分层规则选择最优重写策略组合
- 新增 **核心重写策略**（3 种）：规范化重述（口语→书面）、术语对齐（口语→专业术语）、扩展重述（模糊查询→多维度扩展）
- 新增 **CacheManager**：模块一实现会话绑定 L1 精确匹配缓存 + 连续重复意图检测，模块二实现跨会话 L2 语义相似缓存，含微批请求去重。支持动态 TTL（通用知识 30min / 上下文依赖 5min / 搜索结果 10min / 零向量不缓存）、知识库指纹（Fingerprint）感知的缓存失效机制、写入时抽样清理（概率性过期条目回收）
- 新增 **Postprocessor**：改写质量评估（5 维评分），低质量改写自动丢弃或触发回溯（升级策略重新改写）。确定性预检查采用 2-gram 中文分词 + 子串包含判定计算关键词留存率，按意图类型使用分层阈值（procedural/chitchat/ambiguous → 0.50–0.55，factual → 0.80，默认 0.70），并提供单策略 normalize 降级快速路径（仅清理/补全的改写不被预检误杀）
- 新增 **PromptLoader**：YAML Prompt Catalog 三层降级加载 + 版本注入审计日志
- 新增 **配置项**：~30 个 `QUERY_REWRITE_` 前缀的环境变量已添加至 `config.py`（Settings 字段）
- 新增 **AuditTrail**：每次重写的结构化审计日志（trace_id → 输入/输出/策略/耗时/token/质量分数），仅通过 structlog 输出至日志文件，不持久化到数据库
- 修改 **SearchResponse Schema**：新增 `RewriteInfo` + `RewrittenQuery` Pydantic 模型和 `rewrite_info` 可选字段
- 修改 **SearchService.search()**：在查询向量化之前调用 QueryRewriter，将改写结果传递给检索模块
- 新增 **策略并行执行**：normalize 和 term_align 无依赖关系，管线预算充足时通过 ``asyncio.gather`` 并行执行，减少端到端延迟
- 新增 **策略优先级排序**：预算紧张时按 normalize > term_align > expand 优先级降序串行执行，确保最高价值策略优先
- 新增 **单策略硬超时兜底**：每个策略通过 ``asyncio.wait_for`` 施加硬超时，单策略超时仅丢弃当前策略，其余策略继续执行，保证超时隔离
- 新增 **前端「查询重写详情」面板**：可折叠面板展示改写结果、策略标签、质量评分、性能指标，风格遵循 knowra v2.0 设计系统
- 新增 **前端 API 类型扩展**：`RewriteInfo`、`RewrittenQuery` TypeScript 接口已添加至 `search.ts`
- 修改 **ChatAdapter 重试策略**：关闭 OpenAI SDK 内部重试（`max_retries=0`），将重试控制权完全收归 ChatAdapter 业务层。业务层实现指数退避重试，支持 jitter 抖动避免惊群效应，并对 429 响应自动解析 `Retry-After` 头以遵守服务端限流窗口。此举消除 SDK 默认重试与业务层重试叠加导致的不可控延迟累积：SDK 的 `max_retries=2` 在每次失败后立即重试（无退避、无 jitter），与业务层的指数退避机制叠加后，单次 API 故障的理论最大等待时间可达分钟级；关闭 SDK 重试后，故障路径的延迟完全由业务层精确控制。
- 新增 **搜推分离超时体系**：将搜索（向量检索）与生成（LLM 回答）的超时和重试参数完全解耦。搜索侧保持现有 `request_timeout=60s` 不变；生成侧引入独立配置——`chat_request_timeout=15s`（单次 LLM 生成调用的最大等待时间）+ `chat_max_retries=1`（业务层最多重试 1 次，总等待上限 30s）。该分离确保即使 LLM 服务响应缓慢或不可用，向量检索结果仍可在 100ms 内返回并展示给用户，LLM 延迟不再阻塞搜索结果的首屏呈现。
- 新增 **ChatAdapter.generate_async() 流式生成方法**：基于 OpenAI `stream=True` 的异步流式生成能力，在流式接收过程中检测服务可用性。核心机制为 `chat_first_token_timeout=10s`——若发起流式请求后 10 秒内未收到首个 token，判定 LLM 服务不可用并立即终止请求、返回降级响应；流式接收过程中如遇连接中断或数据流超时，同样触发降级兜底。该方法累积完整流式内容后返回与同步 `generate()` 接口一致的 `ChatResult`，对调用方透明。
- 修改 **SearchService 生成失败降级策略**：将 `_generate_answer()` 的 LLM 调用包装在 `asyncio.wait_for(timeout=20s)` 安全网中。当 LLM 调用超时或抛出异常时，不向上传播错误，而是返回包含降级信息的 `SearchResponse`：`generation_error` 字段记录具体失败原因（超时/API 错误/熔断），`answer` 字段返回面向用户的友好提示文本，`answer_tokens=0`，`chat_model` 仍正常返回以反映当前配置。检索结果（`results`）不受生成失败影响，保持完整返回——**检索结果优先可用，AI 回答尽力而为**。
- 修改 **CircuitBreaker 保护范围**：将熔断器从仅覆盖查询重写模块扩展至 RAG 回答生成环节。新增 `ChatCircuitBreaker`，基于与查询重写熔断器相同的 `CircuitBreaker` 基类但独立追踪 LLM 生成的失败计数。当连续失败次数达到 `CHAT_CIRCUIT_BREAKER_THRESHOLD`（默认 5 次）时自动进入熔断状态，冷却期（`CHAT_CIRCUIT_BREAKER_COOLDOWN_SECONDS`，默认 60s）内所有 LLM 生成请求被直接短路——跳过 API 调用，返回降级响应，避免在服务不可用时持续消耗 API 配额和系统资源。冷却期满后进入半开状态，允许单次探测请求验证服务是否恢复：成功则关闭熔断恢复正常，失败则重新进入熔断。配置项 `CHAT_CIRCUIT_BREAKER_ENABLED`（默认 true）提供全局开关，允许运维侧在排查故障时手动禁用熔断逻辑。

## Capabilities

### New Capabilities
- `query-rewriting`: 查询重写核心能力——在检索之前对用户原始查询进行意图分类、复杂度评分和策略路由，通过规范化重述、术语对齐、扩展重述等策略提升检索准确率，包含精确词保护、上下文融合、缓存去重、质量评估，以及前端可折叠的「查询重写详情」面板

### Modified Capabilities
- `semantic-search`: SearchService 在查询向量化之前集成 QueryRewriter；SearchResponse 新增 rewrite_info 字段暴露重写元信息及连续重复检测标记；SearchRequest 新增 session_id 可选字段用于会话绑定缓存；POST /api/search 的请求 schema 目前不引入 conversation_history 参数（多轮对话上下文由前端在 query 中隐式携带，重写模块通过 ContextRewriter 从历史中消解指代）
- `file-upload-storage`: 新增基于内容 SHA-256 哈希的幂等上传与软删除替换机制——重复上传同一文件（同一用户 + 相同 checksum_sha256）默认幂等返回已有记录（不创建新记录、不产生物理文件副本）；携带 `force` 标记时软删除旧记录并创建新记录；去重仅在 `owner_user_id + checksum_sha256` 维度生效，软删除记录不参与去重匹配。该机制为后续查询重写的知识库指纹（kb_fingerprint）缓存失效提供可靠的数据基础。

## Impact

- **后端新增文件**：`query_rewriter.py`（顶层编排器）、`audit_trail.py`（审计日志）、`query_rewrite_config.py`（配置 dataclass）、`exact_term_protector.py`（精确词保护）、`cache_manager.py`（缓存管理器）、`rewrite_strategies.py`（重写策略集）、`strategy_router.py`（策略路由器）、`prompt_loader.py`（Prompt 加载器）、`postprocessor.py`（后处理器）、`protected_terms_loader.py`（受保护术语加载器）、`term_alignment_loader.py`（术语对齐加载器）
- **后端修改文件**：`config.py`（新增 ~30 个 Settings 字段）、`search.py`（Service 集成 QueryRewriter + LLM 快速失败降级）、`search.py`（Schema 新增 rewrite_info 字段）、`search.py`（Route 注入 QueryRewriter 和 ChatCircuitBreaker 依赖）、`chat_adapter.py`（关闭 SDK 内部重试 + 新增 generate_async 流式生成方法 + 首 token 超时）、`chat_config.py`（新增 first_token_timeout 配置字段）、`circuit_breaker.py`（扩展至 RAG 回答生成熔断）、`uploads.py`（UploadService.create_upload 新增基于 checksum_sha256 的内容去重与 force 软删除替换逻辑）
- **前端新增文件**：`RewritePanel.vue`（组件）、`RewritePanel.spec.ts`（组件测试）、`search.spec.ts`（API 类型测试）
- **前端修改文件**：`search.ts`（API Client 类型扩展）、`ChatArea.vue`（集成 RewritePanel）
- **配置影响**：需新增 ~35 个环境变量（`QUERY_REWRITE_ENABLED` 等 + `CHAT_REQUEST_TIMEOUT`、`CHAT_MAX_RETRIES`、`CHAT_FIRST_TOKEN_TIMEOUT`、`CHAT_CIRCUIT_BREAKER_*`），当 `QUERY_REWRITE_ENABLED=false` 时查询重写模块静默跳过，SearchService 行为与当前一致；生成熔断和降级逻辑始终生效
- **数据模型**：无新增数据库表或 migration；审计日志仅通过 structlog 输出至日志文件（10MB 轮转 × 5 保留），不持久化到数据库
- **API 契约**：SearchResponse 新增 `rewrite_info` 可选字段（向后兼容——不传或为 null 表示未启用重写）；SearchRequest 新增 `session_id` 可选字段（用于缓存绑定和连续重复检测，不传时从 history 自动派生）
- **Depends**：复用现有 ChatAdapter 基础设施（创建独立实例，使用专用 `QueryRewriteConfig` 配置独立的 model/temperature/max_tokens），默认模型与主对话相同但可独立覆盖
- **不做（Phase 3/4 范围外，预计在后续变更中执行）**：HyDE 策略、Multi-Query 生成、子问题分解、后退提示词、对比式重写、Query2Doc、异步改写通道、L3 热点缓存、知识图谱增强、RRF 融合（属于检索模块）。Phase 3 将引入高级重写策略（HyDE、Multi-Query、子问题分解等）和多结果 RRF 融合；Phase 4 将实现异步双通道改写（快速通道+增强通道）及 L3 热点缓存
