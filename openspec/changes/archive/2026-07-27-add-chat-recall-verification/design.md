## Context

knowra 已完成 **上传 → 解析 → 分块 → 向量化** 全链路，`document_embeddings` 表（pgvector Vector(2560)）存储了大量 Qwen3-Embedding-4B 生成的向量。但目前系统没有任何搜索/召回代码，向量处于"只存不查"状态。用户无法对已向量化的私有知识进行提问或获取答案。

本项目已有 OpenAI SDK (`openai>=1.0.0`)，当前仅用于 `client.embeddings.create`（EmbeddingAdapter）。扩展到 `client.chat.completions.create` 是同一 SDK 的自然延伸。

本设计参考已完成的 HTML 方案文档 `docs/chat-recall-verification.html`，其中包含详细的线框图、API 契约和任务分解。

## Goals / Non-Goals

**Goals:**
- 搭建可对话的页面，输入自然语言问题，无需手动选择文档
- 调用后端语义搜索端点，跨所有已向量化文档召回相关分块
- 调用 LLM 生成带来源引用的答案，验证端到端 RAG 质量
- 展示召回结果与 AI 回答并列：分块文本、相似度分数、来源文档、LLM 回答
- 展示实际发送给 LLM 的提示词（可折叠，用于调试和 prompt 迭代）
- ChatAdapter 架构预留流式输出参数位，后续零破坏性添加

**Non-Goals:**
- 不做混合搜索（BM25 + 向量）
- 不做 Reranker
- 不做多轮对话
- 不做分页
- 不做流式输出
- 不做文档范围过滤（始终跨文档搜索）

## Decisions

### 1. LLM 集成：极简接入

**选择**：复用现有 OpenAI SDK 和 EmbeddingAdapter 设计模式，新增 ChatConfig + ChatAdapter（~140 行），始终调用 LLM 生成带引用答案。

**替代方案**：
- LangChain/LlamaIndex 集成：引入额外依赖和抽象层，当前阶段不需要其编排能力
- 仅后端检索不带 LLM：无法验证 RAG 端到端质量，检索质量只能通过答案质量来评估

**理由**：RAG 的检索质量只能通过答案质量来验证。余弦距离是代理指标——高分块可能缺少前置上下文导致 LLM 编造。OpenAI SDK 已在项目中，扩展成本极低（同 SDK 实例的方法族切换）。行业最佳实践为先跑通端到端基线再逐组件优化。

### 2. 对话模型：独立中转站部署

**选择**：ChatAdapter 使用独立中转站和模型（qwen3.5-plus），与 EmbeddingAdapter（Qwen3-Embedding-4B）分离部署。

**理由**：Embedding 和 Chat 对 API 延迟、吞吐、模型能力的诉求不同。分离部署允许独立扩缩容和故障隔离。两者各自创建独立的 `OpenAI` 实例，使用各自的 `api_base_url` 和 `api_key`。

### 3. 多轮对话：延后至 Phase 2

**选择**：本阶段严格单轮问答。

**理由**：多轮对话依赖单轮 RAG 先跑通——检索质量不过关，多轮毫无意义。需要对话历史存储、上下文窗口管理、追问 vs 新话题判断等基础设施。行业最佳实践均为单轮优先。

### 4. 流式输出：架构预留，暂不实现

**选择**：ChatAdapter.generate() 预留 `stream: bool = False` 参数，本阶段固定 False。返回类型用 `ChatResult` 统一封装。

**理由**：流式输出对验证目标零增益——不改变答案内容，只改变呈现方式。一次性返回更利于调试（完整观察 prompt 和 response）。OpenAI SDK 原生支持 (`stream=True`)，后续零破坏性添加。

### 5. 搜索范围：跨文档搜索

**选择**：默认搜索所有已向量化文档。

**理由**：符合真实 RAG 场景——用户提问时不知道答案在哪个文档里，跨文档搜索是唯一合理的默认行为。

### 6. 相似度度量：pgvector cosine distance

**选择**：使用 pgvector `<=>` operator 计算余弦距离。

**替代方案**：
- 应用层计算：需拉取所有向量到内存，不可扩展
- 欧氏距离或内积：余弦距离对语义搜索更稳定，不受向量模长影响

**理由**：pgvector 原生支持，计算在数据库层完成，无需应用层后处理。

### 7. 查询向量化：复用 EmbeddingAdapter

**选择**：使用现有 `EmbeddingAdapter.embed_single()` 向量化用户查询。

**理由**：确保查询与文档使用同一模型和配置，语义空间一致。无需引入新依赖。

### 8. 提示词模板：后端组装

**选择**：在 SearchService 中组装 system + context + question 的 messages 数组，context 使用分块完整文本（非截断版本）。

**理由**：LLM 需要足够上下文生成准确答案。API 响应中截断至 300 字符是为了减少传输量，但 prompt 组装时应使用完整文本。

### 9. ChatAdapter 与 EmbeddingAdapter 独立实例化

**选择**：两个 Adapter 各自创建独立的 `OpenAI` 实例，各自读取各自的配置。

**理由**：保持简单。如果后续需要共享连接池，可以在路由层创建单例 client 并分别注入两个 Adapter 的 `client` 参数。本期不做此优化。

## Risks / Trade-offs

- **[幻觉风险] LLM 可能编造不在上下文中的信息** → 通过低温设置（0.1）和严格的 system prompt 指令（"仅根据上下文回答，否则明确说明无法回答"）缓解；后续 Phase 4 加入幻觉自动检测
- **[上下文窗口溢出] 多个高相关分块的文本总和可能超过模型上下文限制** → 当前使用 `chat_max_tokens=1024` 且 top_k 默认 5，分块 token 数约 300-500，总上下文约 1500-2500 tokens，安全余量充足；后续可加入上下文压缩
- **[LLM API 不可用] 独立中转站故障时 LLM 生成会失败** → 优雅降级：返回 200 SearchResponse，检索结果完整保留，answer 为硬编码错误提示，generation_error 记录原始错误；前端正常展示检索结果面板，回答面板降级展示错误提示。两个 Adapter 独立部署，Embedding 故障不影响 Chat，反之亦然
- **[chat_model 为空时功能不可用]** → chat 未配置时优雅降级：返回 200 SearchResponse，检索结果完整保留，answer 为硬编码提示 "AI 回答生成功能未启用，请联系管理员配置对话模型。"，generation_error 为 "Chat generation is disabled"，前端展示"未启用"降级 UI

## Migration Plan

**部署步骤：**
1. 在 `.env` 和 `.env.example` 中新增 7 个 LLM 配置字段（chat_api_base_url、chat_api_key 等）
2. 部署后端代码，新增路由自动注册
3. 部署前端代码，新增 `/chat` 路由
4. 验证：上传测试文档 → 向量化 → 访问 `/chat` → 提问 → 检查回答和引用

**回滚方案：**
- 无数据库 schema 变更，直接回滚代码即可
- 若 chat 配置未设置（chat_model 为空），LLM 生成功能静默禁用，不影响现有功能
- 新文件和路由为纯增量，删除即可，不影响现有功能

## Open Questions

- ChatAdapter 中转站地址已确认：`https://newapi.bytcloud.org`，模型 `qwen3.5-plus`（Qwen3.5-Plus），由独立中转站提供 OpenAI 兼容 API
- 后续是否需要支持用户自定义 prompt 模板（当前固定在后端）？
