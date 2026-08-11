## ADDED Requirements

### Requirement: 基于内容哈希的幂等上传与软删除替换
系统 SHALL 基于文件内容 SHA-256 哈希实现幂等上传，并支持通过软删除方式替换已有重复文件。

#### Scenario: 幂等上传——重复文件返回已有记录
- **WHEN** 当前用户上传一个文件
- **AND** 该用户已存在一条 `checksum_sha256` 相同且未被软删除（`deleted_at IS NULL`）的上传记录
- **AND** 请求未携带 `force` 标记
- **THEN** 系统 MUST 清理本次上传写入的临时文件
- **AND** 系统 MUST 返回已存在的上传记录（`201` 或 `200`）
- **AND** 系统 MUST NOT 创建新的上传记录
- **AND** 系统 MUST NOT 创建新的物理文件副本

#### Scenario: 强制替换——软删除旧记录并创建新记录
- **WHEN** 当前用户上传一个文件
- **AND** 该用户已存在 `checksum_sha256` 相同且未被软删除的上传记录
- **AND** 请求携带 `force` 标记
- **THEN** 系统 MUST 将匹配的旧记录 `deleted_at` 设置为当前时间（软删除）
- **AND** 系统 MUST 将新文件写入存储并创建新的上传记录
- **AND** 新记录 MUST 拥有新的 `id` 和 `storage_key`
- **AND** 被软删除的旧记录 MUST 保留其原始数据（`checksum_sha256`、`storage_key` 等）不变

#### Scenario: 去重范围限定当前用户
- **WHEN** 用户 A 上传了一个文件
- **AND** 用户 B 上传了内容相同的文件
- **THEN** 用户 B 的上传 MUST NOT 被视为重复
- **AND** 系统 MUST 为用户 B 创建独立的上传记录和物理文件
- **AND** 去重逻辑 MUST 仅在 `owner_user_id + checksum_sha256` 维度匹配

#### Scenario: 软删除记录不参与去重匹配
- **WHEN** 当前用户上传一个文件
- **AND** 该用户存在 `checksum_sha256` 相同的上传记录但其 `deleted_at` 非空
- **THEN** 该软删除记录 MUST NOT 被匹配为重复
- **AND** 系统 MUST 创建新的上传记录
