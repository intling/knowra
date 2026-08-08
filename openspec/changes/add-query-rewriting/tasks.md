## 1. 测试基础设施与契约定义

### 1.1 后端测试 Fixture 与 Mock 基础设施

- [x] 1.1.1 创建 `backend/tests/services/query_rewriter/` 测试目录和 `conftest.py`，提供 `mock_chat_adapter`（返回可控 LLM 响应的 ChatAdapter mock）、`mock_embedding_adapter`（返回固定向量的 EmbeddingAdapter mock）、`sample_rewrite_result` 等共享 fixture

### 1.2 API 契约测试（RewriteInfo Schema）

- [x] 1.2.1 红测试：编写 `backend/tests/schemas/test_search_schema.py`——验证 SearchResponse 新增 `rewrite_info` 可选字段（含 RewriteInfo/RewrittenQuery 子模型，RewrittenQuery 含 query、strategy 字段）、rewrite_info=null 时正常序列化、rewrite_info 包含完整数据时字段类型正确（original_query、rewritten_queries、strategies_used、rewrite_time_ms、cache_hit）、SearchRequest 不变
- [x] 1.2.2 绿实现：在 `backend/app/schemas/search.py` 新增 `RewriteInfo`、`RewrittenQuery` Pydantic 模型（RewrittenQuery 含 query: str、strategy: str | None），SearchResponse 新增 `rewrite_info: RewriteInfo | None = None` 字段
- [x] 1.2.3 重构与质量门禁：运行 `uv run ruff check .`、`uv run ruff format --check .`、`uv run pytest backend/tests/schemas/test_search_schema.py -v`，确认全部通过

### 1.3 前端 API 类型扩展与测试

- [x] 1.3.1 红测试：扩展 `front/src/api/search.test.ts`——新增测试用例验证 `RewriteInfo` 类型字段（original_query、rewritten_queries、strategies_used、rewrite_time_ms、cache_hit）、`RewrittenQuery` 子类型（query、strategy），包含 rewrite_info=null 时正常解析、完整 rewrite_info 数据正确解析
- [x] 1.3.2 绿实现：在 `front/src/api/search.ts` 新增 `RewriteInfo`、`RewrittenQuery` TypeScript 接口（RewrittenQuery 含 query: string、strategy?: string | null），SearchResponse 新增 `rewrite_info?: RewriteInfo | null` 字段
- [x] 1.3.3 重构与质量门禁：运行 `npm run lint`、`npm run test -- front/src/api/search.test.ts`，确认全部通过

## 2. 模块一：AuditTrail 审计日志实现

### 2.1 红测试

- [x] 2.1.1 编写 `backend/tests/services/query_rewriter/test_audit_trail.py`——覆盖正常路径（完整审计事件包含 trace_id/原始查询/查询哈希/保护词/策略/耗时/token）、边界情况（空查询、超长查询截断、策略列表为空）、异常处理（logger 不可用时降级）

### 2.2 绿实现

- [x] 2.2.1 在 `backend/app/services/audit_trail.py` 创建 `AuditTrail` 类：提供 `record(event, **fields)` 方法，通过 `get_logger(__name__)` 获取 structlog logger，以 `query_rewrite_complete` 等固定事件消息 + 关键字参数结构化字段输出审计日志
- [x] 2.2.2 AuditTrail 支持记录：`trace_id`、`original_query`、`query_hash`、`protected_terms`、`context_used`、`intent`、`complexity`、`strategies_executed`、`rewrites`（含每条重写的 query/strategy/duration_ms/tokens）、`total_rewrite_time_ms`、`cache_hit`、`cache_level`、`quality_scores`、`prompt_versions`

### 2.3 重构与质量门禁

- [x] 2.3.1 运行 `uv run ruff check .`、`uv run ruff format --check .`、`uv run pytest backend/tests/services/query_rewriter/test_audit_trail.py -v`，确认全部通过

## 3. 模块一：QueryRewriter 顶层编排器实现

### 3.1 红测试

- [x] 3.1.1 编写 `backend/tests/services/query_rewriter/test_query_rewriter.py`——覆盖正常路径（重写管线执行：精确词保护 → L1 缓存查询 → 请求去重 → 上下文融合 → 保护词还原 → 缓存写入 → 审计日志）、条件触发（无指代词时跳过上下文融合、无保护词时跳过保护/还原）、缓存命中（L1 命中直接返回跳过 LLM）、降级场景（LLM 调用失败静默降级返回原始查询、管线超时降级）、模块开关（QUERY_REWRITE_ENABLED=false 时跳过重写）
- [ ] 3.1.2 编写 L1 缓存精细化测试——覆盖：缓存 Key 绑定会话 ID（不同会话相同查询不共享 L1 缓存）、严格精确匹配（仅规范化 Query 字符串完全一致时命中，大小写/空格差异不命中）

### 3.2 绿实现

- [x] 3.2.1 在 `backend/app/services/query_rewriter.py` 创建 `QueryRewriter` 类：组合 `ExactTermProtector`、`ContextRewriter`、`CacheManager`，实现 `rewrite(query, history=None) -> RewriteResult` 方法
- [x] 3.2.2 管线顺序实现：精确词保护 → L1 缓存查询 + 请求去重 → 上下文融合（条件触发 has_pronouns）→ 保护词还原 → 写入 L1 缓存 → 审计日志记录
- [ ] 3.2.2a L1 缓存 Key 设计：`{session_id}:{normalized_query_hash}`——规范化 Query（trim + 小写 + 标准化空白）后计算哈希，与 session_id 组合作为 Key，确保不同会话的相同问题物理隔离
- [x] 3.2.3 `RewriteResult` 包含：`original_query`、`rewritten_queries`（改写后的查询列表，每条含 query 文本和 strategy 策略名）、`strategies_used`、`rewrite_time_ms`、`cache_hit`
- [x] 3.2.4 LLM 调用失败时静默降级：捕获 `ChatAPIError`，记录警告日志 `query_rewrite_failed`，返回原始查询，rewrite_info 设为 None
- [x] 3.2.5 管线总超时保护：通过 `QUERY_REWRITE_PIPELINE_TIMEOUT`（默认 3s）控制整体超时，超时后使用原始查询继续

### 3.3 重构与质量门禁

- [x] 3.3.1 运行 `uv run ruff check .`、`uv run ruff format --check .`、`uv run pytest backend/tests/services/query_rewriter/test_query_rewriter.py -v`，确认全部通过

## 4. 模块一：SearchService 集成与 API Route 修改

### 4.1 红测试

- [x] 4.1.1 编写 `backend/tests/services/test_search_service_rewrite.py`——覆盖正常集成（SearchService.search() 调用 QueryRewriter → 改写查询用于向量化 → SearchResponse 含 rewrite_info）、重写未启用时 rewrite_info=null、重写失败时降级（rewrite_info=null 但搜索正常完成）、耗时统计分离（search_time_ms 含重写耗时，rewrite_time_ms 独立记录）
- [x] 4.1.2 编写 `backend/tests/api/test_search_route_rewrite.py`——覆盖 POST /api/search 端到端（含 rewrite_info 的完整响应 JSON 序列化验证、rewrite_info=null 时 JSON 不包含该字段或为 null）

### 4.2 绿实现

- [x] 4.2.1 修改 `backend/app/services/search.py`——在 `SearchService.__init__` 接收 `QueryRewriter` 依赖，在 `search()` 方法的查询向量化（Step 1）之前调用 `self.query_rewriter.rewrite()`，使用改写后的首个查询进行向量化
- [x] 4.2.2 SearchResponse 组装时填充 `rewrite_info`：原始查询、改写列表、使用策略、重写耗时、缓存命中状态
- [x] 4.2.3 重写失败时捕获异常，记录 `query_rewrite_failed` 警告日志，`rewrite_info=null`，使用原始查询继续检索
- [x] 4.2.4 修改 `backend/app/api/routes/search.py`——新增 `get_query_rewriter()` 依赖注入函数，创建独立的 ChatAdapter 实例（使用 QueryRewriteConfig），注入到 SearchService；Route 的 `get_search_service()` 接收 QueryRewriter 参数
- [x] 4.2.5 新增 `get_query_rewrite_config()` 依赖注入：从 Settings 构建 `QueryRewriteConfig`，使用 `QUERY_REWRITE_MODEL`、`QUERY_REWRITE_TEMPERATURE`、`QUERY_REWRITE_MAX_TOKENS`、`QUERY_REWRITE_TIMEOUT`、`QUERY_REWRITE_API_BASE_URL`、`QUERY_REWRITE_API_KEY` 配置项

### 4.3 重构与质量门禁

- [x] 4.3.1 运行 `uv run ruff check .`、`uv run ruff format --check .`、`uv run pytest backend/tests/services/test_search_service_rewrite.py backend/tests/api/test_search_route_rewrite.py -v`，确认全部通过

## 5. 模块一：前端 RewritePanel 基础组件

### 5.1 红测试

- [x] 5.1.1 编写 `front/src/__tests__/components/RewritePanel.test.ts`——覆盖显示/隐藏逻辑（rewrite_info 非 null 且 rewritten_queries 非空时渲染、rewrite_info=null 时不渲染、rewritten_queries 为空时不渲染）、默认折叠状态、点击折叠按钮展开/收起、原始查询展示、改写结果列表展示（策略标签 + 改写文本）、性能指标展示（重写耗时、缓存命中）、视觉样式一致性（折叠按钮/标题/chevron 动画与现有 PromptPreview 一致）


### 5.2 绿实现

- [x] 5.2.1 在 `front/src/components/RewritePanel.vue` 创建独立组件：接收 `rewriteInfo: RewriteInfo | null` prop，使用 `v-if` 控制显示/隐藏，`ref(false)` 管理折叠状态
- [x] 5.2.2 折叠按钮行：改写条数徽章、🗒️ 图标 + 标题 "查询重写详情"、SVG chevron 动画图标，样式使用 `flex w-full items-center justify-between px-5 py-3 text-left transition hover:bg-neutral-50`
- [x] 5.2.3 展开内容区域：原始查询（`text-sm text-neutral-500 italic`）+ 改写结果列表（`divide-y divide-neutral-100` 分隔）+ 性能指标（重写耗时 `text-xs text-neutral-400`、缓存命中 `⚡ emerald-500`）
- [x] 5.2.4 策略标签：根据 `strategy` 字段映射显示文本（如 `normalize` → "规范重述"），统一使用灰色标签样式（Phase 1 暂不区分颜色，Phase 2 扩展）

### 5.3 重构与质量门禁

- [x] 5.3.1 运行 `npm run lint`、`npm run test -- front/src/__tests__/components/RewritePanel.test.ts`、`npm run build`，确认全部通过
- [x] 5.3.2 在 `ChatArea.vue` 中集成 RewritePanel 组件（渲染于 AnswerPanel 上方），传递 `searchResponse.rewrite_info`
- [x] 5.3.3 浏览器验证：启动前端开发服务器，发送测试查询，确认 RewritePanel 在 AnswerPanel 上方正确渲染、折叠/展开交互正常

## 6. 模块二：PromptLoader 实现

### 6.1 红测试

- [x] 6.1.1 编写 `backend/tests/services/query_rewriter/test_prompt_loader.py`——覆盖三层降级加载（YAML Catalog 命中 → 返回 YAML 版本；YAML 缺失某策略 → 回退代码默认值；环境变量 `QUERY_REWRITE_PROMPT_NORMALIZE` 覆盖 → 优先级最高）、启动验证（模板缺少 `{query}` 占位符 → 抛出 `ValueError` 并包含策略名和缺失变量名；所有模板占位符完整 → 正常通过）、版本注入（`PromptLoader.all_versions(filter_names=["intent_classification", "normalize"])` 仅返回本次实际使用的策略版本，未在 YAML 中配置的策略不出现在返回结果中；`filter_names=None` 返回全部 YAML 条目）、YAML 文件不存在时降级为代码默认值（不抛出异常）、YAML 格式错误时抛出明确错误

### 6.2 绿实现

- [x] 6.2.1 在 `backend/app/services/prompt_loader.py` 创建 `PromptLoader` 类：提供 `load(strategy_name: str) -> str` 方法，实现三层降级加载逻辑（环境变量 `QUERY_REWRITE_PROMPT_<NAME>` → YAML Catalog `backend/prompts/rewrite_prompts.yaml` → 策略类代码默认值 `DEFAULT_PROMPT_TEMPLATE`）
- [x] 6.2.2 YAML Catalog 解析：启动时加载 `prompts/rewrite_prompts.yaml`（路径可通过 `QUERY_REWRITE_PROMPT_PATH` 配置），解析每个 Prompt 的 `version`、`template`、`description` 字段，存入内部 dict
- [x] 6.2.3 创建 `backend/prompts/rewrite_prompts.yaml` 初始 Catalog 文件：包含 `intent_classification`、`context_fusion`、`normalize`、`term_align`、`expand`、`quality_evaluation` 共 6 个 Prompt 模板，每个含 `version: "1.0.0"` 和 `description`
- [x] 6.2.4 启动验证：`PromptLoader.validate_all()` 在启动时验证所有已加载模板包含必需占位符（`{query}` 为所有策略必需，`{history}` 为 `context_fusion` 必需，`{protected_terms}` 为 `term_align`/`normalize`/`expand` 必需），缺少时抛出 `ValueError` 阻止启动
- [x] 6.2.5 版本追踪：`PromptLoader.all_versions(filter_names: list[str] | None = None) -> dict[str, str]` 返回 `{strategy_name: version}` 映射。仅返回在 YAML Catalog 中显式配置了版本的条目（代码默认版本不出现），`filter_names` 过滤时仅返回实际使用的策略
- [x] 6.2.6 各重写策略类（`NormalizeRewriter`、`TermAlignRewriter`、`ExpandRewriter`、`ContextRewriter`、`StrategyRouter`、`Postprocessor`）通过 `PromptLoader.load(strategy_name)` 获取 Prompt 模板，不再硬编码

### 6.3 重构与质量门禁

- [x] 6.3.1 运行 `uv run ruff check .`、`uv run ruff format --check .`、`uv run pytest backend/tests/services/query_rewriter/test_prompt_loader.py -v`，确认全部通过

## 7. 模块二：策略路由与重写策略集成

### 7.1 红测试

- [x] 7.1.1 编写 `backend/tests/services/query_rewriter/test_query_rewriter_phase2.py`——覆盖意图分类+路由集成（factual+低复杂度跳过重写、情+中复杂度执行 normalize+term_align、ambiguous 执行 expand、高复杂度执行 normalize+term_align+expand）、L2 语义缓存命中跳过 LLM、多策略串联执行（前策略输出作为后策略输入）、策略开关（QUERY_REWRITE_STRATEGY_NORMALIZE/EXPAND/TERM_ALIGN=false 时跳过对应策略）
- [x] 7.1.1a 编写 L2 语义缓存精细化测试`backend/tests/services/query_rewriter/test_semantic_cache_l2.py`——覆盖：跨会话缓存 Key 不依赖 SessionID（基于语义向量检索，不同会话相同语义查询可命中）、极高相似度阈值（仅相似度 > 0.95 时考虑命中，略低则跳过）、通用知识分类（缓存答案为通用知识时可跨会话复用，如"报销流程"、"Python 语法"）、上下文依赖检测（缓存答案依赖特定历史背景如"基于刚才的代码"→ 禁止跨会话复用）、上下文相关性校验（L2 命中后必须通过 LLM 轻量校验，确认答案不依赖特定上下文才返回；校验失败则回退到正常重写管线）
- [x] 7.1.1b 编写不满意重试检测测试`backend/tests/services/query_rewriter/test_dissatisfaction_retry.py`——覆盖：同一会话中短时间内重复提问相同问题（如问完"Python怎么学？"得到答案后紧接着又问"Python怎么学？"）→ 识别为不满意信号 → 跳过 L1 缓存 → 触发"扩展重述"或"换一种解释"策略而非复读机；不同问题不误触发；超过滑动窗口（默认 60s）的重复不触发
- [x] 7.1.2 编写 `backend/tests/services/query_rewriter/test_normalize_rewriter.py`——覆盖正常路径（口语化查询 → 规范书面语：如"咋整Python"→"如何学习Python"、错别字修正、冗余词去除）、边界情况（已是规范查询时保持原样、纯符号/数字查询原样返回、空字符串处理）、LLM 调用失败降级（返回原始查询）、Prompt 模板占位符正确填充（`{query}`、`{protected_terms}`）

### 7.2 绿实现

- [x] 7.2.0 创建 `backend/app/services/normalize_rewriter.py`——实现 `NormalizeRewriter` 类：接收 `ChatAdapter` + `PromptLoader` 依赖，提供 `rewrite(query, protected_terms: list[str] | None = None) -> dict` 方法。通过 `PromptLoader.load("normalize", vocabulary=...)` 获取模板（``{vocabulary}`` 占位符由 PromptLoader 在返回前完成替换），使用 `str.replace` 填充 ``{query}`` 和 ``{protected_terms}``（避免 `.format()` 将词汇表文本中的花括号误解析为占位符）。通过模块级 `@lru_cache` 缓存词汇表文本（进程生命周期内仅解析 YAML 一次）。LLM 调用失败时静默降级返回原始查询。返回 `dict` 含 `query`、`strategy="normalize"`、`duration_ms`、`tokens`
- [x] 7.2.1 在 `QueryRewriter.rewrite()` 管线中插入 Phase 2 步骤：上下文融合之后 → 意图分类（`StrategyRouter.route()`）→ 策略路由决策 → 策略执行（`NormalizeRewriter`/`TermAlignRewriter`/`ExpandRewriter`）→ 保护词还原
- [x] 7.2.1a 不满意重试检测：在意图分类阶段维护 `(session_id, normalized_query_hash)` → `last_seen_at` 的短期滑动窗口（默认 60s，通过 `QUERY_REWRITE_DISSATISFACTION_WINDOW_SECONDS` 配置）。同一会话相同规范化查询在窗口内再次出现 → 判定为"不满意重试"→ 跳过 L1 缓存 + 自动升级策略（追加 expand/alternate 策略，而不是复读相同答案），记录 `dissatisfaction_retry` 审计事件
- [x] 7.2.2 路由决策为 "direct"（空策略列表）时跳过所有重写策略，直接进入保护词还原
- [x] 7.2.3 多策略串联：前一个策略的输出（`rewritten_query`）作为后一个策略的输入（`query`），保护词在策略执行期间保持为占位符
- [x] 7.2.4 L2 语义缓存集成：L1 未命中时查询 L2 语义缓存（`CacheManager.lookup_l2(query_vector)`），命中时返回缓存结果并记录 `cache_level="L2"`
- [x] 7.2.4a L2 跨会话缓存 Key 设计：不依赖 SessionID，基于 query 语义向量在向量数据库中检索最近邻（`CacheManager.lookup_l2(query_vector)`），相似度阈值通过 `QUERY_REWRITE_L2_SIMILARITY_THRESHOLD`（默认 0.95）配置
- [x] 7.2.4b 通用知识分类标记：缓存写入时调用轻量分类器（或复用质量评估 LLM 的一次额外判断）标记答案类型——`general_knowledge`（通用知识，可跨会话复用）vs `context_dependent`（依赖历史上下文，仅限当前会话 L1 复用）。标记结果写入缓存元数据
- [x] 7.2.4c 上下文相关性校验层：L2 命中后，不直接返回缓存答案。调用轻量 LLM（使用低成本模型，单轮判断）输入缓存答案 + 当前对话历史摘要，判断答案是否依赖特定上下文背景。`context_dependent` 标记的答案直接跳过 L2 无需校验。校验不通过 → 记录 `l2_context_rejected` 审计事件 → 回退到正常重写管线。校验通过 → 返回缓存答案并标记 `cache_level="L2"` + `context_verified=true`
- [x] 7.2.5 `RewriteResult` 扩展：新增 `intent: str | None`、`complexity: int | None`、`cache_level: "L1" | "L2" | None` 字段
- [x] 7.2.6 扩展 `backend/app/schemas/search.py` 中的 `RewriteInfo` Pydantic 模型：新增 `intent: str | None = None`、`complexity: int | None = None`、`cache_level: Literal["L1", "L2"] | None = None` 字段，`RewrittenQuery` 新增 `duration_ms: float | None = None`、`tokens: int | None = None` 字段

### 7.3 重构与质量门禁

- [x] 7.3.1 运行 `uv run ruff check .`、`uv run ruff format --check .`、`uv run pytest backend/tests/services/query_rewriter/test_query_rewriter_phase2.py -v`，确认全部通过

## 8. 模块二：前端 RewritePanel 增强

### 8.1 红测试

- [x] 8.1.1 扩展 `front/src/__tests__/components/RewritePanel.test.ts`——覆盖策略标签颜色区分（normalize→blue、term_align→purple、expand→amber、context_fusion→teal、未知策略→brand 回退）、意图分类展示（折叠按钮行显示 "🔍 分析型 · 复杂度 7" 徽章）、缓存层级展示（L1 精确命中 / L2 语义命中标签）

### 8.2 绿实现

- [x] 8.2.1 RewritePanel 策略标签颜色映射：`normalize` → `bg-blue-100 text-blue-700`、`term_align` → `bg-purple-100 text-purple-700`、`expand` → `bg-amber-100 text-amber-700`、`context_fusion` → `bg-teal-100 text-teal-700`、未知策略 → `bg-brand-100 text-brand-700`
- [x] 8.2.2 折叠按钮行新增意图+复杂度徽章：`text-xs` 样式，格式为 "{emoji} {意图中文名} · 复杂度 {score}"（意图映射：factual→事实型、analytical→分析型、comparative→比较型、procedural→操作型、exploratory→探索型、chitchat→闲聊、ambiguous→模糊）
- [x] 8.2.3 缓存层级展示：`cache_level="L1"` 显示 "L1 精确命中"、`cache_level="L2"` 显示 "L2 语义命中"
- [x] 8.2.4 扩展 `front/src/api/search.ts` 中的 `RewriteInfo` TypeScript 接口：新增 `intent?: string | null`、`complexity?: number | null`、`cache_level?: "L1" | "L2" | null` 字段

### 8.3 重构与质量门禁

- [x] 8.3.1 运行 `npm run lint`、`npm run test -- front/src/__tests__/components/RewritePanel.test.ts`、`npm run build`，确认全部通过
- [x] 8.3.2 浏览器验证：确认策略标签颜色正确区分、意图徽章正确显示、缓存层级标签正确展示

## 9. 模块三：质量评估与回溯集成

### 9.1 红测试

- [ ] 9.1.1 编写 `backend/tests/services/query_rewriter/test_query_rewriter_phase3.py`——覆盖 Postprocessor 集成（高质量改写通过、语义保留度<3 自动丢弃、总分<15 触发回溯升级策略、二次失败直接丢弃回退原始查询）、确定性预检查（关键词留存率<阈值直接丢弃跳过 LLM 评估、长度比例异常标记可疑）、质量评估降级兜底（评估 LLM 失败时保守接受改写）、回溯限制（最多 1 次，不可无限回溯）、QualityScores 正确传递到 RewriteResult

### 9.2 绿实现

- [ ] 9.2.1 在 `QueryRewriter.rewrite()` 管线中插入 Postprocessor 步骤：每条策略执行后 → `Postprocessor.evaluate()`→ 确定性预检查 → LLM 质量评估 → 质量合格则保留，不合格则回溯（最多 1 次）→ 二次失败丢弃回退原始查询
- [ ] 9.2.2 确定性预检查（零 LLM 成本）：关键词留存率检查（关键词留存率 < `QUERY_REWRITE_QUALITY_KEYWORD_RETENTION_THRESHOLD` → 直接丢弃）、长度比例检查（改写长度/原始长度 < 0.3 或 > 5.0 → 标记可疑）
- [ ] 9.2.3 回溯逻辑：首次质量不合格 → 升级策略重新改写（如 `normalize` → `expand`），二次不合格 → 丢弃改写，使用原始查询
- [ ] 9.2.4 质量评估降级：Postprocessor LLM 调用失败（超时或 API 错误）→ 记录警告日志，保守接受改写结果
- [ ] 9.2.5 `RewriteResult.quality_scores` 包含完整 `QualityScores`（5 维评分 + total_score + verdict + issues）
- [ ] 9.2.6 `SearchResponse.rewrite_info` 传递 `quality_scores`、`backtrack_triggered`（是否触发回溯）、`backtrack_strategy`（回溯后使用的策略）
- [ ] 9.2.7 扩展 `backend/app/schemas/search.py`：新增 `QualityScores` Pydantic 模型（semantic_preservation、clarity_improvement、information_gain、term_accuracy、retrievability 各 1-5 分 + total_score + verdict: Literal["excellent","good","marginal","poor"] + issues: list[str]），`RewriteInfo` 新增 `quality_scores: QualityScores | None = None`、`backtrack_triggered: bool = False`、`backtrack_strategy: str | None = None` 字段

### 9.3 重构与质量门禁

- [ ] 9.3.1 运行 `uv run ruff check .`、`uv run ruff format --check .`、`uv run pytest backend/tests/services/query_rewriter/test_query_rewriter_phase3.py -v`，确认全部通过

## 10. 模块三：前端质量评分展示

### 10.1 红测试

- [ ] 10.1.1 扩展 `front/src/__tests__/components/RewritePanel.test.ts`——覆盖质量评分颜色区分（excellent→emerald-600、good→amber-600、marginal/poor→red-600，使用 `font-mono tabular-nums` 等宽数字字体）、5 维度条形图展开/收起、回溯提示展示（"已自动升级策略重新改写" `text-xs text-amber-500`）、评分缺失时容错（quality_scores=null 时不渲染评分区域不崩溃）

### 10.2 绿实现

- [ ] 10.2.1 RewritePanel 每条改写结果下方展示质量评分：`total_score` 数字 + `verdict` 中文标签，颜色按等级区分（excellent→emerald、good→amber、marginal/poor→red）
- [ ] 10.2.2 可展开的 5 维度评分详情：点击展开按钮展示条形图（`bg-neutral-200` 底色 + 彩色填充 `rounded-full h-1.5`），5 个维度 label + 分数
- [ ] 10.2.3 回溯提示：`backtrack_triggered=true` 时展示 "已自动升级策略重新改写" 提示文字（`text-xs text-amber-500`）
- [ ] 10.2.4 评分缺失容错：`quality_scores=null` 或不存在时仅隐藏评分相关 UI，不影响其他内容正常渲染
- [ ] 10.2.5 在 `front/src/api/search.ts` 新增 `QualityScores` TypeScript 接口（semantic_preservation、clarity_improvement、information_gain、term_accuracy、retrievability、total_score、verdict、issues），扩展 `RewriteInfo` 类型：新增 `quality_scores?: QualityScores | null`、`backtrack_triggered?: boolean`、`backtrack_strategy?: string | null`

### 10.3 重构与质量门禁

- [ ] 10.3.1 运行 `npm run lint`、`npm run test -- front/src/__tests__/components/RewritePanel.test.ts`、`npm run build`，确认全部通过
- [ ] 10.3.2 浏览器验证：确认质量评分颜色正确、5 维度条形图可展开/收起、回溯提示正确显示、评分缺失时 UI 不崩溃

## 11. 端到端验收与文档更新

### 11.1 端到端集成测试

- [ ] 11.1.1 编写 `backend/tests/test_query_rewrite_e2e.py`——覆盖完整端到端流程：POST /api/search → QueryRewriter 执行完整管线（精确词保护→缓存→去重→上下文融合→意图分类→策略路由→策略执行→质量评估→保护词还原→审计日志）→ SearchResponse 含完整 rewrite_info，验证 `search_time_ms` 包含重写耗时、`rewrite_time_ms` 独立准确、同一请求所有日志事件共享 trace_id

### 11.2 熔断器（Circuit Breaker）

- [ ] 11.2.1 红测试：编写熔断器单元测试——连续失败 N 次（默认 5 次）后自动断开、断开期间所有请求跳过重写、冷却期满后半开探测成功恢复、探测失败重新断开
- [ ] 11.2.2 绿实现：在 `QueryRewriter` 中集成熔断器逻辑（可使用 `pybreaker` 库或手动实现），通过 `QUERY_REWRITE_CIRCUIT_BREAKER_THRESHOLD` / `QUERY_REWRITE_CIRCUIT_BREAKER_COOLDOWN_SECONDS` 配置
- [ ] 11.2.3 运行 `uv run pytest backend/tests/ -k "circuit_breaker" -v`，确认全部通过

### 11.3 后端质量门禁汇总

- [ ] 11.3.1 运行全部后端测试：`uv run pytest backend/tests/ -v`
- [ ] 11.3.2 运行后端代码质量检查：`uv run ruff check .`、`uv run ruff format --check .`

### 11.4 前端质量门禁汇总

- [ ] 11.4.1 运行全部前端测试：`npm run test`
- [ ] 11.4.2 运行前端代码质量检查：`npm run lint`
- [ ] 11.4.3 前端构建验证：`npm run build`

### 11.5 文档更新

- [ ] 11.5.1 更新 `.env.example`——新增所有 `QUERY_REWRITE_` 前缀的配置项（~23 个）及默认值、说明注释
- [ ] 11.5.2 如 API 契约发生变化（SearchResponse 新增 rewrite_info 字段），同步更新相关 API 文档
- [ ] 11.5.3 更新 `AGENTS.md` 或项目 README——记录查询重写模块的架构概览、配置说明和使用方式
