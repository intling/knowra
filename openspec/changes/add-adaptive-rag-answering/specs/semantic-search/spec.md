## MODIFIED Requirements

### Requirement: 跨文档语义搜索

系统 SHALL 接收自然语言查询文本，对需要资料检索的问题使用与文档相同的 Embedding 模型进行 pgvector 余弦距离搜索。默认检索当前认证用户可见的全部已向量化文档；显式 `document_ids` SHALL 限定范围。闲聊、明确通用知识请求和文档总结 SHALL 使用自适应路由。

#### Scenario: 默认搜索全部文档
- **WHEN** 用户发送需要检索的查询且未指定文档范围
- **THEN** 系统搜索当前用户可见的已向量化文档，返回最相关的 Top-K 个片段

#### Scenario: 系统无任何向量化数据
- **WHEN** 当前用户没有向量化数据且提出普通问题
- **THEN** 系统返回 200 和通用模型回答，`results=[]`、`retrieval_status=empty`
- **AND** 不因向量数量为零返回 404，不查询其他用户的文档

#### Scenario: top_k 大于实际分块总数
- **WHEN** 检索请求的 top_k 大于实际匹配的分块总数
- **THEN** 返回所有符合条件的片段，结果数小于 top_k

### Requirement: 搜索响应元信息

搜索响应 SHALL 保留查询回显、向量预览、模型、维度、top_k、搜索数量、文档数量、耗时与 `rewrite_info`，并增加回答方式和检索状态。跳过检索时向量预览为空、搜索数量为零；模型名称和 token 必须来自真实生成。总结结果与向量命中 SHALL 通过回答方式区分，不能把总结选取顺序称为语义相关排名。

#### Scenario: 响应元信息完整性
- **WHEN** 搜索完成
- **THEN** 响应保留 `query,query_embedding_preview,embedding_model,embedding_dimensions,top_k,total_searched,searched_document_count,search_time_ms`
- **AND** 返回 `answer_mode`（`general|rag|summary|clarification`）、`retrieval_status`（`skipped|matched|no_match|empty|unavailable`）与 `summary_coverage`
- **AND** 仅总结返回非空 `summary_coverage`，包含 `document_count,included_document_count,total_chunks,included_chunks,truncated`

#### Scenario: 重写未启用时 rewrite_info 为 null
- **WHEN** 搜索成功完成且未执行查询重写
- **THEN** `rewrite_info=null`，包括跳过检索的通用回答和文档总结

#### Scenario: 重写失败时 rewrite_info 为 null
- **WHEN** 查询重写失败且未生成诊断信息
- **THEN** 检索继续使用原始查询，`rewrite_info=null`，不能阻止后续回答

#### Scenario: 重写失败时保留可用诊断
- **WHEN** 查询重写失败且已有错误诊断
- **THEN** 保留 `rewrite_info.error` 和原始查询，检索继续，不能阻止后续回答

## ADDED Requirements

### Requirement: 显式文档范围校验

`POST /api/search` SHALL 接收可选 `document_ids`，值为 1 至 20 个解析文档 UUID。重复 ID SHALL 去重；所有 ID 都必须属于当前用户且源文件未删除。格式或数量非法时 SHALL 返回 422 和具体字段原因；不可见 ID SHALL 返回 404 和一致的可读原因。省略范围保持原有请求兼容。

#### Scenario: 请求携带文档范围
- **WHEN** 请求中提供有效的 `document_ids`
- **THEN** 检索、计数、总结和缓存均限定在该范围内

#### Scenario: 非法文档 ID
- **WHEN** `document_ids` 包含非 UUID 字符串、为空数组或超过 20 个 ID
- **THEN** 返回 422，响应说明 `document_ids` 的格式或数量错误，不开始模型调用

#### Scenario: 未授权访问
- **WHEN** 未登录用户请求任意回答方式
- **THEN** 返回 401 和认证原因，不调用检索或模型

### Requirement: 自适应问答额度

系统 SHALL 对成功生成的通用、资料增强和总结回答沿用账号问答额度。澄清、模型生成失败和服务错误 SHALL 释放当前预留；通用回答不得绕过额度限制。准入必须先于昂贵依赖执行。

#### Scenario: 通用回答消耗额度
- **WHEN** 有限额账号成功获得通用模型回答
- **THEN** 本次按一次成功问答计入额度；达到额度后下一次请求返回 429、具体原因和 `Retry-After`

#### Scenario: 澄清不消耗额度
- **WHEN** 缺少可总结资料而返回澄清
- **THEN** 当前问答预留释放，用户仍能继续下一次有效提问
