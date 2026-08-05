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
- [x] 3.2.2a L1 缓存 Key 设计：`{session_id}:{normalized_query_hash}`——规范化 Query（trim + 小写 + 标准化空白）后计算哈希，与 session_id 组合作为 Key，确保不同会话的相同问题物理隔离
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

