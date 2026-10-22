## MODIFIED Requirements

### Requirement: 跨文档语义搜索
系统 SHALL 接收已认证用户的自然语言查询，通过现有 EmbeddingAdapter 向量化后，使用 pgvector 余弦距离在该用户拥有的有效文档中检索最相似的 Top-K 分块。检索候选、总数、文档名、片段、引用和发送给 LLM 的上下文 MUST 具有一致的用户边界。

#### Scenario: 默认搜索全部文档
- **WHEN** 已认证用户发送查询
- **THEN** 系统 MUST 仅在该用户拥有且源文件未软删除的已向量化文档中检索
- **AND** MUST 返回按余弦距离升序排列的前 K 条结果
- **AND** `total_searched` MUST 仅统计同一可见范围

#### Scenario: 系统无任何向量化数据
- **WHEN** 整个系统没有向量化数据
- **THEN** SearchService MUST 返回空结果和引导上传的友好提示，且 MUST NOT 调用 LLM
- **AND** HTTP 路由 MUST 返回 404 和空知识库提示，与当前空知识库接口约定一致

#### Scenario: 当前用户无向量化数据
- **WHEN** 其他用户具有向量化数据，但当前用户没有可见向量
- **THEN** SearchService MUST 返回空结果和引导上传的友好提示，且 MUST NOT 调用 LLM
- **AND** HTTP 路由 MUST 保持现有空知识库状态约定并提供明确原因，MUST NOT 暴露其他用户的向量总数

#### Scenario: top_k 大于实际分块总数
- **WHEN** top_k 大于当前用户实际可见的匹配分块总数
- **THEN** 系统 MUST 仅返回该用户可见的匹配分块

#### Scenario: 管理员查询私有知识
- **WHEN** 管理员发送查询
- **THEN** 检索范围 MUST 仍限定为管理员自己的资料
- **AND** 账号管理权限 MUST NOT 扩展资料可见范围

## ADDED Requirements

### Requirement: 搜索缓存和指纹用户边界
搜索响应缓存、查询重写缓存、请求去重和知识库指纹 SHALL 绑定服务端认证得到的用户身份。客户端 `session_id` 和对话历史 MUST NOT 充当授权身份。

#### Scenario: 伪造相同对话标识
- **WHEN** 两个用户发送相同 query、history 和 `session_id`
- **THEN** 系统 MUST NOT 复用另一用户的搜索或上下文重写结果

#### Scenario: 跨用户无历史查询
- **WHEN** 两个用户发送相同查询且未提供 `session_id` 或历史
- **THEN** 所有缓存与去重结果 MUST 仍按真实用户隔离

#### Scenario: 知识库更新失效
- **WHEN** 当前用户新增、替换或删除资料
- **THEN** 系统 MUST 使该用户的旧知识库缓存失效
- **AND** 指纹聚合 MUST 仅依赖该用户可见资料
