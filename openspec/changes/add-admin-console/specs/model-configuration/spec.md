## Purpose

为资料向量化、检索重排、查询改写和带引用回答提供可持久化的模型服务配置，支持管理员维护多个接入方案并按用途选择默认配置，同时保护模型密钥和现有向量空间的一致性。

## ADDED Requirements

### Requirement: 模型配置管理契约
系统 SHALL 提供 `/api/admin/models` 列表与创建、`/{id}` 编辑与删除、`/{id}/activate` 设为默认和 `/{id}/deactivate` 恢复环境配置；仅持有 `models:manage` 的管理员可访问。

#### Scenario: 创建并读取四种用途配置
- **WHEN** 管理员创建 `chat`、`embedding`、`rerank` 或 `query_rewrite` 用途配置
- **THEN** 系统 MUST 返回 201 和公开配置：`id,name,kind,base_url,model,enabled,is_default,has_api_key,timeout_seconds,max_retries,dimensions,api_format,created_at,updated_at`
- **AND** `GET` MUST 返回 `items,total,offset,limit` 分页，`PATCH` MUST 返回 200；配置用途创建后 MUST 不可更改
- **AND** 创建的配置 MUST 默认启用但不自动设为默认，MUST NOT 隐式覆盖运行中的配置

#### Scenario: 参数校验
- **WHEN** 地址不是 HTTP(S)、包含用户名密码、query 或 fragment，名称或模型为空，超时不在 1–120 秒，重试不在 0–3 或用途/重排协议无效
- **THEN** 系统 MUST 返回 422 及字段原因，MUST NOT 保存或激活配置
- **AND** 地址 MUST 允许管理员明确配置的本地模型服务
- **AND** Embedding 的维度 MUST 与现有索引的 2560 维约束一致，其他维度 MUST 返回 422

### Requirement: 模型密钥保护
系统 SHALL 加密保存 API Key，仅在请求模型时解密，公开配置只返回 `has_api_key`；创建可省略密钥以支持无鉴权本地服务。

#### Scenario: 更新时保留密钥
- **WHEN** 修改请求省略 `api_key` 或传入空字符串
- **THEN** 系统 MUST 保留已有密钥
- **WHEN** 修改请求传入非空 `api_key`
- **THEN** 系统 MUST 替换加密密钥且 MUST NOT 回显秘密
- **WHEN** 修改请求显式提交 `clear_api_key=true`
- **THEN** 系统 MUST 清除密钥，并在同时提交非空密钥时返回 422

#### Scenario: 加密配置缺失或损坏
- **WHEN** 密钥加密主配置缺失或不能解密已有配置
- **THEN** 系统 MUST 以 503、`model_secret_unavailable` 和可读原因拒绝需要加解密的操作
- **AND** MUST NOT 明文存储、降级忽略后台默认配置或暴露秘密

#### Scenario: 校验与日志保密
- **WHEN** 管理操作成功、失败或请求字段校验失败
- **THEN** 响应、异常和业务日志 MUST NOT 包含 API Key、密文或加密主密钥

### Requirement: 每种用途的默认配置
每种用途 SHALL 至多有一个后台默认配置，默认切换 MUST 原子生效，未绑定时 MUST 沿用对应环境配置；禁用配置不得激活，默认配置不得直接禁用或删除。

#### Scenario: 切换和恢复
- **WHEN** 管理员激活一个启用中的配置
- **THEN** 系统 MUST 返回 200，并仅切换相应用途的默认配置，其他用途 MUST 保持原状态
- **WHEN** 管理员取消当前默认配置
- **THEN** 系统 MUST 返回 200 并恢复该用途环境配置
- **WHEN** 多个管理员同时激活相同用途配置
- **THEN** 最终 MUST 仍只有一个默认配置

#### Scenario: 禁用和删除保护
- **WHEN** 管理员激活禁用配置
- **THEN** 系统 MUST 返回 409、`model_disabled` 与具体原因
- **WHEN** 管理员删除或禁用默认配置
- **THEN** 系统 MUST 返回 409、`model_in_use` 并要求先切换或恢复环境配置
- **WHEN** 管理员删除非默认配置或操作不存在的配置
- **THEN** 系统 MUST 分别返回 204 或 404、`model_not_found` 及具体原因

### Requirement: 模型配置进入实际调用链
搜索、查询改写、重排、自动向量化和重新向量化 SHALL 使用请求开始或任务入队时解析的有效配置；保存配置 MUST 不要求进程重启，MUST 不修改环境配置对象。

#### Scenario: 下一次请求使用默认配置
- **WHEN** 管理员保存或切换默认配置后发起新的搜索或资料处理
- **THEN** 相应适配器 MUST 使用新的地址、模型、密钥、超时与重试配置
- **AND** 生成、改写、重排和向量化用途 MUST 相互独立，模型调用失败 MUST 沿用既有有界重试与降级语义

#### Scenario: 在途任务与缓存
- **WHEN** 模型配置在请求或后台任务执行期间发生变化
- **THEN** 在途工作 MUST 继续使用原配置快照，后续请求 MUST 使用新配置
- **AND** 配置切换 MUST 使旧搜索/改写缓存和模型熔断状态无法影响新配置，缓存仍 MUST 按用户隔离
- **AND** 回答 MUST 保持原有文档、片段和引用的可追溯性

#### Scenario: 后台默认启用向量化
- **WHEN** 管理员已激活后台 Embedding 默认，解析与分块功能启用
- **THEN** 分块成功后系统 MUST 使用该默认进行自动向量化，即使原环境向量化开关关闭

### Requirement: Embedding 索引兼容性
存在任何未删除用户的有效向量数据或待执行/运行中的向量任务时，系统 SHALL 拒绝把有效 Embedding 地址、模型标识或维度切换到不同值，包括编辑默认配置及恢复环境配置。

#### Scenario: 不兼容切换
- **WHEN** 已有有效向量且管理员尝试启用、编辑或恢复一个不同的 Embedding 配置
- **THEN** 系统 MUST 返回 409、`embedding_index_conflict`，说明需规划重建索引
- **AND** 当前默认配置、向量及检索行为 MUST 保持原状态，MUST NOT 自动重建或混用向量空间

#### Scenario: 密钥与超时调整
- **WHEN** 管理员仅修改现有 Embedding 配置的密钥或超时
- **THEN** 系统 MUST 允许保存且保持索引和既有资料不变

#### Scenario: 请求不得覆盖后台向量空间
- **WHEN** 已存在后台 Embedding 默认，重新向量化请求指定不同模型或维度
- **THEN** 系统 MUST 返回 409 `embedding_configuration_managed`，MUST NOT 创建不同空间的向量任务
- **AND** 无后台默认时 MUST 保留既有环境配置路径的参数兼容性
