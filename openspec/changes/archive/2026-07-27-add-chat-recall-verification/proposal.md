## Why

当前知识库已完成 **上传 → 解析 → 分块 → 向量化** 全链路，`document_embeddings.embedding_vector`（pgvector Vector(2560)）列存储了大量向量数据，但系统 **没有任何搜索/召回代码**，向量处于"只存不查"状态。用户无法对已向量化的私有知识进行提问或检索，端到端 RAG 闭环缺失最关键的一环——从问题到答案的检索与生成。本变更旨在补齐这一缺口，搭建从自然语言提问到带来源引用回答的完整验证链路。

## What Changes

- 新增 **ChatConfig** 与 **ChatAdapter**：独立的 LLM 对话配置与适配器，复用 OpenAI SDK 模式，与 EmbeddingAdapter 分离部署
- 新增 **POST /api/search** 跨文档语义搜索端点：接收自然语言查询，通过 pgvector 余弦距离检索相关分块
- 新增 **SearchService**：编排查询向量化 → pgvector 检索 → LLM 生成 → 结果组装
- 新增 **ChatView** 对话召回验证页面（`/chat` 路由）：召回结果展示、LLM 回答展示、提示词预览
- 新增 **前端 API Client** (`search.ts`)：TypeScript 类型定义 + `searchChunks()` 函数
- 新增 **Settings 字段**：7 个 LLM 配置字段（chat_api_base_url、chat_api_key、chat_model 等）
- 新增 **Pydantic Schema**：SearchRequest / SearchResult / SearchResponse（含 answer、answer_tokens 等字段）

## Capabilities

### New Capabilities
- `semantic-search`: 跨文档语义搜索能力——将用户自然语言问题向量化后，通过 pgvector 余弦距离在全部已向量化文档中检索最相关分块，支持 top_k 控制
- `chat-generation`: 基于检索上下文的 LLM 答案生成能力——将召回的分块组装为 prompt，调用 OpenAI 兼容的对话模型生成带来源引用的答案，含 token 统计与错误处理
- `chat-recall-ui`: 对话召回验证前端页面——提供 Markdown 渲染的 LLM 回答展示、按文档分组的召回结果面板、可折叠的提示词调试面板

### Modified Capabilities
<!-- 本次不修改现有 spec 的需求行为，均为新增能力 -->

## Impact

- **后端新增文件**：`chat_config.py`、`chat_adapter.py`、`search.py`（Schema）、`search.py`（Service）、`search.py`（Route）
- **后端修改文件**：`config.py`（新增 7 个 LLM Settings 字段）、`router.py`（注册 search router）
- **前端新增文件**：`search.ts`（API Client）、`ChatView.vue`（页面组件）
- **前端修改文件**：`router/index.ts`（新增 `/chat` 路由）
- **配置影响**：需新增 7 个环境变量（chat_api_base_url、chat_api_key、chat_model 等），当 `chat_model` 为空字符串时搜索功能不可用
- **依赖**：复用现有 OpenAI SDK（`openai>=1.0.0`）、EmbeddingAdapter（查询向量化）、pgvector、现有 Vue 组件风格
- **数据模型**：无新增数据库表或 migration，仅查询现有 `document_embeddings` 和 `parsed_documents` 表
- **API 契约**：新增 `POST /api/search` 端点，无现有 API 的破坏性变更
- **不做（本期范围外）**：混合搜索（BM25）、Reranker、多轮对话、流式输出、搜索结果分页
