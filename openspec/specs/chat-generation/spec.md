## Purpose

基于检索上下文的 LLM 答案生成能力——将召回的分块组装为 prompt，调用 OpenAI 兼容的对话模型生成带来源引用的答案，含 token 统计、重试机制与优雅降级处理。

## Requirements

### Requirement: ChatAdapter 封装 LLM 调用
系统 SHALL 提供 ChatAdapter，封装 OpenAI 兼容的 `POST /v1/chat/completions` 端点，支持重试、错误处理和结构化返回，与 EmbeddingAdapter 使用独立的配置和 OpenAI 客户端实例。

#### Scenario: 正常生成回答
- **WHEN** ChatAdapter.generate() 被调用并传入有效的 messages 数组
- **THEN** 返回 ChatResult，包含 content（生成文本）、total_tokens、prompt_tokens、completion_tokens

#### Scenario: API 超时自动重试
- **WHEN** LLM API 调用超时
- **THEN** ChatAdapter 按照带随机抖动的指数退避策略自动重试（最多 max_retries 次），退避上限 60s

#### Scenario: 5xx 服务端错误重试
- **WHEN** LLM API 返回 5xx 状态码
- **THEN** ChatAdapter 自动重试，与超时错误使用相同的抖动退避策略

#### Scenario: 4xx 客户端错误不重试（除 429 外）
- **WHEN** LLM API 返回 4xx 状态码（401、403、404 等永久性错误）
- **THEN** ChatAdapter 立即抛出 ChatAPIError，不进行重试

#### Scenario: 429 Rate Limit 重试
- **WHEN** LLM API 返回 429 状态码（频率限制）
- **THEN** ChatAdapter 解析 Retry-After 响应头，若存在则按指定时长等待后重试；若无则使用带随机抖动的指数退避（上限 60s）重试，与超时/5xx 共用 max_retries 配额

#### Scenario: 重试耗尽后抛出错误
- **WHEN** 所有重试次数耗尽后仍然失败
- **THEN** ChatAdapter 抛出 ChatAPIError，包含原始错误信息

### Requirement: ChatConfig 独立配置
系统 SHALL 提供 ChatConfig frozen dataclass，从 Settings 构建，包含 LLM 对话所需的所有连接参数和生成参数。ChatConfig 使用独立中转站（`https://newapi.bytcloud.org`）和独立模型（`qwen3.5-plus`），与 EmbeddingConfig 的端点（`https://router.tumuer.me/v1`，`Qwen/Qwen3-Embedding-4B`）完全分离部署，两者各自创建独立的 OpenAI 客户端实例。

#### Scenario: 从 Settings 构建配置
- **WHEN** ChatConfig.from_settings() 被调用
- **THEN** 返回包含 api_base_url、api_key、model、temperature、max_tokens、request_timeout、max_retries 的不可变配置对象

#### Scenario: 配置快照可序列化
- **WHEN** ChatConfig.snapshot() 被调用
- **THEN** 返回不包含 api_key 的配置字典（api_base_url、model、temperature、max_tokens），可供 API 响应使用

### Requirement: Chat 未配置时优雅降级
当 chat_model 为空字符串（LLM 功能未配置）时，系统 SHALL 优雅降级：返回 200 SearchResponse，results 保留已成功检索的所有结果，answer 为硬编码友好提示，generation_error 为 "Chat generation is disabled" 供前端区分降级 UI。不抛异常、不丢弃检索结果。

**理由**：Chat 未配置和 LLM 运行时失败的共同点是检索都已成功完成，结果不应丢弃。行业框架（LangChain、LlamaIndex、Dify）在 LLM 不可用时均保留 source nodes/chunks。answer="" 是无意义信号——用户看到空白面板不知道发生了什么。三种降级策略（Chat 未配置 / LLM 失败 / 无向量数据）通过 generation_error 值统一区分。

#### Scenario: Chat 功能未启用
- **WHEN** chat_model 配置为空字符串
- **THEN** 系统返回 200 SearchResponse，results 完整保留检索结果，answer 为硬编码友好提示 "AI 回答生成功能未启用，请联系管理员配置对话模型。以下为检索到的相关内容。"，answer_tokens、chat_model 均为 None，generation_error 为 "Chat generation is disabled"，不调用 LLM

### Requirement: LLM 调用失败时优雅降级
当 LLM API 调用失败（重试耗尽）时，系统 SHALL 优雅降级：返回 200 SearchResponse，results 保留已成功检索的所有结果，answer 为硬编码错误提示，generation_error 记录原始 ChatAPIError 信息供前端展示。不抛异常、不丢弃检索结果。

**理由**：RAG 管线的检索和生成是两个独立阶段——检索成功不应因下游 LLM 失败而被抛弃。行业最佳实践（LangChain、LlamaIndex、Dify）在 LLM 失败时均保留 retrieved docs。对比 Embedding 失败（"入口失败"，无法检索，必须抛异常）与 LLM 失败（"下游失败"，上游结果已就绪）是两种完全不同性质的失败，应区分处理。

#### Scenario: LLM API 不可用
- **WHEN** ChatAdapter.generate() 抛出 ChatAPIError（重试耗尽）
- **THEN** 系统返回 200 SearchResponse，results 完整保留检索结果，answer 为硬编码友好提示 "AI 回答生成失败，请稍后重试。以下为检索到的相关内容。"，answer_tokens、chat_model 均为 None，generation_error 记录原始错误信息（如 "LLM API timeout"），SearchService 不向上传播异常

### Requirement: 提示词模板
系统 SHALL 在 SearchService 中组装发送给 LLM 的 messages 数组，包含 system 角色（定义回答规则：仅根据上下文回答、无法回答时明确说明、注明来源）和 user 角色（包含上下文信息和用户问题）。

#### Scenario: Prompt 包含完整上下文
- **WHEN** 系统组装 LLM prompt
- **THEN** user message 包含每个召回分块的来源信息（文档名、页码、标题路径）和完整文本内容（非截断版本），以及用户原始问题

#### Scenario: Prompt 包含回答规则
- **WHEN** 系统组装 LLM prompt
- **THEN** system message 明确规定：仅根据上下文回答、编造信息禁止、上下文不足时明确说明、引用注明来源、使用结构化格式

### Requirement: 流式输出架构预留
ChatAdapter SHALL 预留 `stream` 参数位，本阶段固定为 False。generate() 方法签名包含 `stream: bool = False`，返回类型使用 ChatResult 统一封装。

#### Scenario: stream 参数预留
- **WHEN** ChatAdapter.generate() 被调用且 stream=False（默认）
- **THEN** 正常返回 ChatResult，行为与当前一致

#### Scenario: stream=True 未实现
- **WHEN** ChatAdapter.generate() 被调用且 stream=True
- **THEN** 抛出 NotImplementedError，提示 "Streaming will be implemented in Phase 2"
