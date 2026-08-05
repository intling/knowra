## Purpose

提供跨文档语义搜索能力——将用户自然语言问题向量化后，通过 pgvector 余弦距离在全部已向量化文档中检索最相关分块，支持 top_k 控制、结果排序和完整的元数据返回。

## Requirements

### Requirement: 跨文档语义搜索
系统 SHALL 接收自然语言查询文本，通过复用现有 EmbeddingAdapter 将查询向量化后，使用 pgvector 余弦距离（`<=>` operator）在 `document_embeddings` 表中跨所有已向量化文档检索最相似的 Top-K 个分块。

#### Scenario: 默认搜索全部文档
- **WHEN** 用户发送查询请求
- **THEN** 系统在所有已向量化文档中搜索，返回按余弦距离升序排列的前 K 条结果

#### Scenario: 系统无任何向量化数据
- **WHEN** 系统中 document_embeddings 表为空
- **THEN** 系统返回 200 SearchResponse，results 为空数组，answer 为硬编码友好提示 "知识库中暂无任何已向量化的文档。请先上传文档并完成向量化后再提问。"，answer_tokens 和 chat_model 均为 None，不调用 LLM

#### Scenario: top_k 大于实际分块总数
- **WHEN** 用户请求的 top_k 大于实际匹配的分块总数
- **THEN** 系统返回所有匹配的分块，结果数小于 top_k

### Requirement: 查询向量化复用
系统 SHALL 使用现有 EmbeddingAdapter 的 `embed_single()` 方法向量化用户查询，确保查询向量与文档向量使用同一模型和配置。

#### Scenario: 查询向量维度一致
- **WHEN** 系统向量化用户查询
- **THEN** 生成的查询向量维度（2560）与 document_embeddings 中的向量维度一致

#### Scenario: 查询向量化失败
- **WHEN** Embedding API 调用失败（超时、连接错误或 5xx）
- **THEN** 系统返回 502 错误，错误描述为 "Failed to embed query"

### Requirement: 搜索结果包含完整元数据
每条搜索结果 SHALL 包含：全局排名、余弦距离分数、分块 ID、来源文档 ID、文档名称、分块序号、分块文本（截断至 300 字符）、上下文增强文本（截断至 300 字符）、token 数、标题路径、页码。

#### Scenario: 结果字段完整性
- **WHEN** 搜索成功返回结果
- **THEN** 每条结果包含 rank、score、chunk_id、parsed_document_id、document_name、sequence_index、text、contextualized_text、token_count、heading_path、page_numbers 字段

### Requirement: 搜索响应元信息
搜索响应 SHALL 包含：原始查询回显、查询向量前 5 维预览、嵌入模型名称、向量维度、top_k、总搜索向量数、涉及文档数、搜索耗时（毫秒）。当查询重写模块启用并成功执行时，响应 SHALL 额外包含 rewrite_info 字段，提供原始查询、改写后的查询列表、使用的策略列表、重写耗时和缓存命中状态。

#### Scenario: 响应元信息完整性
- **WHEN** 搜索成功完成
- **THEN** 响应包含 query、query_embedding_preview、embedding_model、embedding_dimensions、top_k、total_searched、searched_document_count、search_time_ms 字段，且 search_time_ms 为正值。如果重写模块执行了改写，还包含 rewrite_info 字段（original_query、rewritten_queries、strategies_used、rewrite_time_ms、cache_hit）

#### Scenario: 重写未启用时 rewrite_info 为 null
- **WHEN** 搜索成功完成但查询重写模块未启用（QUERY_REWRITE_ENABLED=false）
- **THEN** 响应中 rewrite_info 字段为 null

#### Scenario: 重写失败时 rewrite_info 为 null
- **WHEN** 搜索过程中查询重写 LLM 调用失败
- **THEN** 搜索正常继续使用原始查询，响应中 rewrite_info 字段为 null

### Requirement: 搜索耗时包含重写耗时
search_time_ms SHALL 包含查询重写的耗时。rewrite_time_ms 独立记录重写模块自身的耗时。

#### Scenario: 耗时统计分离
- **WHEN** 搜索完成且重写模块执行了改写
- **THEN** search_time_ms 包含从查询到达至组装响应完成的总时间（含重写），rewrite_time_ms 仅记录 QueryRewriter.rewrite() 的执行时间

### Requirement: 搜索参数验证
系统 SHALL 验证搜索请求参数：query 长度 1–2000 字符，top_k 范围 1–50。

#### Scenario: query 为空
- **WHEN** 用户发送空的 query 文本
- **THEN** 系统返回 422 验证错误

#### Scenario: top_k 超出范围
- **WHEN** 用户发送 top_k < 1 或 top_k > 50
- **THEN** 系统返回 422 验证错误

### Requirement: 分数单调性
搜索结果 SHALL 按余弦距离严格升序排列，rank 与 score 保持单调递增关系。

#### Scenario: 结果排序正确
- **WHEN** 搜索返回多条结果
- **THEN** rank 1 的 score ≤ rank 2 的 score ≤ ... ≤ rank N 的 score，且所有 chunk_id 不重复
