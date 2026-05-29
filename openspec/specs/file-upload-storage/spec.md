# file-upload-storage Specification

## Purpose
TBD - created by archiving change add-file-upload-storage. Update Purpose after archive.
## Requirements
### Requirement: 上传文件元数据模型
系统 SHALL 持久化用户上传文件的元数据，并通过当前用户归属支持后续资料解析、索引和来源追溯。

#### Scenario: 创建上传文件表结构
- **WHEN** 数据库迁移执行完成
- **THEN** 数据库 MUST 存在 `uploaded_files` 表
- **AND** `uploaded_files` 表 MUST 包含 `id`、`owner_user_id`、`original_filename`、`content_type`、`byte_size`、`storage_key`、`checksum_sha256`、`status`、`error_message`、`deleted_at`、`created_at`、`updated_at` 字段

#### Scenario: 上传文件关联当前用户
- **WHEN** 后端成功保存上传文件元数据
- **THEN** `uploaded_files.owner_user_id` MUST 引用当前用户的 `users.id`
- **AND** 系统 MUST NOT 使用客户端提交的用户归属字段决定上传文件归属

#### Scenario: 上传记录保留原始文件展示信息
- **WHEN** 用户上传名为 `course-notes.pdf` 的文件
- **THEN** 上传记录 MUST 保存 `original_filename` 为原始展示文件名
- **AND** 上传记录 MUST 保存文件大小
- **AND** 上传记录 MUST 保存内容类型或明确保存为空

### Requirement: 单文件上传 API
系统 SHALL 提供单文件上传 API，将当前用户提交的原始文件保存到应用内存储并返回上传记录。

#### Scenario: 上传有效文件成功
- **WHEN** 当前用户解析成功
- **AND** 客户端向 `POST /api/uploads` 提交包含 `file` 字段的 `multipart/form-data` 请求
- **AND** 文件非空且未超过大小限制
- **THEN** API MUST 返回 `201`
- **AND** 响应体 MUST 包含 `id`、`owner_user_id`、`original_filename`、`content_type`、`byte_size`、`storage_key`、`checksum_sha256`、`status`、`error_message`、`deleted_at`、`created_at`、`updated_at`
- **AND** 响应体中的 `status` MUST 为 `stored`
- **AND** 响应体中的 `error_message` MUST 为空

#### Scenario: 上传请求缺少文件字段
- **WHEN** 客户端向 `POST /api/uploads` 提交不包含 `file` 字段的请求
- **THEN** API MUST 返回非 2xx 状态码
- **AND** 响应体 MUST 包含可诊断错误信息
- **AND** 系统 MUST NOT 创建成功上传记录

#### Scenario: 当前用户不可用时拒绝上传
- **WHEN** 当前用户解析失败
- **AND** 客户端向 `POST /api/uploads` 提交文件
- **THEN** API MUST 返回非 2xx 状态码
- **AND** 系统 MUST NOT 保存原始文件为成功上传
- **AND** 系统 MUST NOT 创建归属为空的上传记录

#### Scenario: 上传空文件失败
- **WHEN** 当前用户解析成功
- **AND** 客户端向 `POST /api/uploads` 提交空文件
- **THEN** API MUST 返回非 2xx 状态码
- **AND** 系统 MUST NOT 创建状态为 `stored` 的上传记录

#### Scenario: 上传超出大小限制失败
- **WHEN** 当前用户解析成功
- **AND** 客户端上传的文件大小超过系统配置的单文件大小限制
- **THEN** API MUST 返回非 2xx 状态码
- **AND** 响应体 MUST 表达文件大小超限
- **AND** 系统 MUST NOT 创建状态为 `stored` 的上传记录

### Requirement: 应用内原始文件存储
系统 SHALL 将上传的原始文件保存到应用内可配置存储位置，并通过稳定 `storage_key` 关联数据库记录。

#### Scenario: 成功上传后保存原始文件
- **WHEN** 文件上传 API 返回 `201`
- **THEN** 系统 MUST 在应用内存储中保存该原始文件
- **AND** 上传记录的 `storage_key` MUST 能定位该原始文件

#### Scenario: 存储键由服务端生成
- **WHEN** 用户上传文件
- **THEN** 系统 MUST 由服务端生成 `storage_key`
- **AND** `storage_key` MUST NOT 直接使用客户端提交的原始文件名作为完整路径

#### Scenario: 存储写入失败
- **WHEN** 系统无法将原始文件写入应用内存储
- **THEN** API MUST 返回非 2xx 状态码
- **AND** 系统 MUST NOT 创建指向不存在原始文件的成功上传记录

### Requirement: 上传配置
系统 SHALL 通过配置管理上传存储目录、单文件大小限制和允许内容类型，避免在业务代码中硬编码环境差异，并确保文档处理首批支持的文件类型可以进入上传存储流程。

#### Scenario: 配置上传存储目录
- **WHEN** 后端应用启动
- **THEN** 系统 MUST 从配置中读取上传存储目录
- **AND** 上传服务 MUST 使用该目录保存原始文件

#### Scenario: 配置单文件大小限制
- **WHEN** 后端应用启动
- **THEN** 系统 MUST 从配置中读取单文件大小限制
- **AND** 上传服务 MUST 使用该限制拒绝超限文件

#### Scenario: 配置允许内容类型
- **WHEN** 后端应用启动
- **THEN** 系统 MUST 从配置中读取允许上传的内容类型
- **AND** 上传服务 MUST 使用该配置决定是否接受受限类型文件
- **AND** 默认或示例配置 MUST 覆盖 TXT、Markdown、PDF、DOCX、PPT/PPTX 对应的内容类型

### Requirement: 前端上传体验
前端 SHALL 基于当前附件选择入口提交上传请求，并向用户展示上传状态和错误反馈。

#### Scenario: 选择文件后显示待上传文件
- **WHEN** 用户通过附件按钮选择文件
- **THEN** 前端 MUST 显示被选中文件的名称
- **AND** 前端 MUST 允许用户移除该待上传文件

#### Scenario: 提交文件上传
- **WHEN** 当前用户加载成功
- **AND** 用户选择了文件并触发提交
- **THEN** 前端 MUST 调用上传 API
- **AND** 前端 MUST NOT 在请求中提交 `owner_user_id`

#### Scenario: 上传过程中展示加载状态
- **WHEN** 上传请求尚未完成
- **THEN** 前端 MUST 展示上传中状态
- **AND** 前端 MUST 防止同一文件被重复提交

#### Scenario: 上传成功后清理本地选择
- **WHEN** 上传 API 返回成功上传记录
- **THEN** 前端 MUST 清空当前选中文件
- **AND** 前端 MUST 展示上传成功反馈

#### Scenario: 上传失败后展示错误
- **WHEN** 上传 API 返回错误或请求失败
- **THEN** 前端 MUST 展示用户可理解的错误反馈
- **AND** 前端 MUST 保留用户重新尝试上传的可能性

#### Scenario: 当前用户不可用时禁用上传
- **WHEN** 前端当前用户加载失败
- **THEN** 依赖用户归属的上传操作 MUST 不可提交
- **AND** 前端 MUST 展示当前用户不可用反馈
