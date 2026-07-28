## 1. 后端 LLM 基础设施

- [x] 1.1 创建 ChatConfig frozen dataclass（`backend/app/services/chat_config.py`），包含 api_base_url、api_key、model、temperature、max_tokens、request_timeout、max_retries 字段，提供 from_settings() 类方法和 snapshot() 方法
- [x] 1.2 在 Settings（`backend/app/core/config.py`）中新增 7 个 LLM 配置字段：chat_api_base_url、chat_api_key、chat_model、chat_temperature、chat_max_tokens、chat_request_timeout、chat_max_retries，含合理的默认值
- [x] 1.3 TDD 红测试：编写 ChatAdapter 单元测试（`backend/tests/services/test_chat_adapter.py`），覆盖正常生成、超时重试、5xx 重试、4xx 不重试、重试耗尽抛错，确认测试失败后停止等待评审
- [x] 1.4 实现 ChatAdapter（`backend/app/services/chat_adapter.py`）：封装 chat.completions.create，含 ChatError/ChatAPIError 异常类、ChatResult dataclass、指数退避重试、generate() 方法（含 stream 参数预留），使用 `from app.core.logging import get_logger` 结构化日志
- [x] 1.5 验证 ChatAdapter 测试通过：运行 `cd backend && uv run pytest tests/services/test_chat_adapter.py -v`

## 2. 后端 Schema 与搜索服务

- [x] 2.1 创建 SearchRequest / SearchResponse / SearchResult / AnswerTokens Pydantic Schema（`backend/app/schemas/search.py`），含 query、top_k 等请求字段和完整的响应字段（answer、answer_tokens、chat_model 等），query 长度 1–2000，top_k 范围 1–50
- [x] 2.2 TDD 红测试：编写 SearchService 单元测试（`backend/tests/services/test_search_service.py`），覆盖全部文档搜索、空结果、正常返回 answer，确认测试失败后停止等待评审
- [x] 2.3 实现 SearchService（`backend/app/services/search.py`）：构造函数 DI 注入 session、embedding_adapter、chat_adapter、chat_config；search() 方法编排查询向量化 → pgvector 跨文档检索（JOIN parsed_documents）→ 文本截断 → LLM 生成 → 组装 SearchResponse，使用结构化日志
- [x] 2.4 实现 SearchService 的 LLM 生成部分：prompt 模板组装（system + context + question），context 使用分块完整文本，token 统计提取，chat 未启用时拒绝生成
- [x] 2.5 验证 SearchService 测试通过：运行 `cd backend && uv run pytest tests/services/test_search_service.py -v`

## 3. 后端路由与注册

- [x] 3.1 TDD 红测试：编写 Search API 集成测试（`backend/tests/api/test_search_api.py`），覆盖 200（正常搜索+生成）、404（无向量数据）、422（参数校验失败）、502（嵌入失败）、503（chat 禁用），确认测试失败后停止等待评审
- [x] 3.2 创建 POST /api/search 路由（`backend/app/api/routes/search.py`）：请求验证、依赖注入 SearchService、错误码映射（含 502 embedding/chat 错误、503 chat 禁用）
- [x] 3.3 在 api_router（`backend/app/api/router.py`）中注册 search router
- [x] 3.4 验证 Search API 测试通过：运行 `cd backend && uv run pytest tests/api/test_search_api.py -v`

## 4. 后端质量门禁

- [x] 4.1 运行后端 lint 检查：`cd backend && uv run ruff check .`
- [x] 4.2 运行后端格式检查：`cd backend && uv run ruff format --check .`
- [x] 4.3 运行后端全量测试：`cd backend && uv run pytest`

## 5. 前端 API Client

- [x] 5.1 TDD 红测试：编写 search.ts API Client 测试（`front/src/api/__tests__/search.spec.ts`），覆盖正常响应解析、answer 字段解析、HTTP 错误处理、网络错误处理，确认测试失败后停止等待评审
- [x] 5.2 创建 search.ts（`front/src/api/search.ts`）：TypeScript 类型定义（SearchRequest、SearchResultItem、AnswerTokens、SearchResponse）+ searchChunks() 函数，使用延迟 Logger 创建模式，错误时抛出 SearchApiError
- [x] 5.3 验证 API Client 测试通过：运行 `cd front && npm run test -- --run src/api/__tests__/search.spec.ts`

## 6. 前端 ChatView 页面

- [x] 6.1 创建 ChatView.vue 骨架（`front/src/views/ChatView.vue`）：页面布局框架、组件划分结构、空状态引导提示"无需选文档，直接输入问题即可获取 AI 回答"
- [x] 6.2 实现 ChatInput：文本输入框（Enter 换行 / Ctrl+Enter 或按钮发送）、空文本发送禁用（按钮置灰 + 快捷键无效）、Top-K 滑块（1–50，默认 5）、发送按钮、加载状态（"搜索中..." → "生成回答中..."）
- [x] 6.3 实现 AnswerPanel：Markdown 渲染 AI 回答、引用统计（引用 N/M 分块 · 来自 K 个文档）、Token 用量展示（prompt + completion = total）、复制回答按钮
- [x] 6.4 实现 ResultsPanel：可折叠面板（默认折叠）、搜索摘要栏（搜索 N 个文档 · M 个向量 · 耗时 T ms）、按文档分组的结果列表、排名+可视化分数条、分块文本（截断+展开）、元数据行
- [x] 6.5 实现 PromptPreview：可折叠面板（默认折叠）、完整 messages 数组展示（role + content）、复制按钮
- [x] 6.6 连接 API 与状态管理：调用 searchChunks()、对话历史维护、错误处理与展示、加载状态管理
- [x] 6.7 实现分数分布迷你柱状图：在 ResultsPanel 顶部展示各分块相似度分布

## 7. 前端路由注册与导航

- [x] 7.1 新增 `/chat` 路由（`front/src/router/index.ts`）：路由配置 + 导航栏"对话验证"入口
- [x] 7.2 TDD 红测试：编写 ChatView 组件测试（`front/src/views/__tests__/ChatView.spec.ts`），覆盖发送查询显示回答+结果、空结果、API 错误处理，确认测试失败后停止等待评审
- [x] 7.3 验证 ChatView 测试通过：运行 `cd front && npm run test -- --run src/views/__tests__/ChatView.spec.ts`

## 8. 前端质量门禁

- [x] 8.1 运行前端 lint 检查：`cd front && npm run lint`
- [x] 8.2 运行前端全量测试：`cd front && npm run test -- --run`
- [x] 8.3 运行前端构建验证：`cd front && npm run build`

## 9. 端到端验证

- [x] 9.1 手动 E2E 验证：上传 2 份以上文档 → 向量化 → 访问 `/chat` → 跨文档搜索 → 验证 LLM 回答引用准确性 → 验证幻觉检测（问文档中没有的内容）
- [x] 9.2 验证客观检查项：分数单调性（rank 与 score 严格单调递增）、文本完整性（所有结果 text 不为 null）、去重（chunk_id 不重复）、查询向量维度与 embedding_dimensions 一致、top_k 生效（结果数 ≤ top_k）、search_time_ms 正值、answer 非空、answer_tokens 正确（prompt + completion = total）
- [x] 9.3 验证边界情况：系统无向量数据 → 404、top_k 大于总分块数 → 返回全部、特殊字符/emoji 查询 → 正常向量化、chat 未配置 → 503、LLM API 超时 → 502
