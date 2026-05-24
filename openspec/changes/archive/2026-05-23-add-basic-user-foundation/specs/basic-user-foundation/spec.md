## ADDED Requirements

### Requirement: 基础用户数据模型
系统 SHALL 持久化基础用户数据，并为后续文件、文档、知识库等资源提供稳定用户主键。

#### Scenario: 创建用户表结构
- **WHEN** 数据库迁移执行完成
- **THEN** 数据库 MUST 存在 `users` 表
- **AND** `users` 表 MUST 包含 `id`、`display_name`、`email`、`avatar_url`、`status`、`deleted_at`、`created_at`、`updated_at` 字段

#### Scenario: 邮箱可空且非空唯一
- **WHEN** 多个用户的 `email` 为空
- **THEN** 系统 MUST 允许这些用户同时存在
- **WHEN** 两个用户使用相同的非空 `email`
- **THEN** 系统 MUST 拒绝后写入的重复邮箱

### Requirement: 用户软删除
系统 SHALL 使用 `deleted_at` 表示用户软删除，并在常规用户读取和当前用户解析中排除已软删除用户。

#### Scenario: 用户被软删除
- **WHEN** 用户被删除
- **THEN** 系统 MUST 设置该用户的 `deleted_at`
- **AND** 系统 MUST NOT 物理删除该用户记录

#### Scenario: 当前用户解析排除软删除用户
- **WHEN** 默认用户的 `deleted_at` 非空
- **THEN** 当前用户解析 MUST NOT 返回该用户
- **AND** `GET /api/users/me` MUST 返回明确错误

### Requirement: 当前用户解析
系统 SHALL 提供统一当前用户解析能力，本阶段默认解析为系统默认用户。

#### Scenario: 解析默认用户
- **WHEN** 系统存在状态为 `active` 且 `deleted_at` 为空的默认用户
- **THEN** 当前用户解析 MUST 返回该用户

#### Scenario: 默认用户不可用
- **WHEN** 默认用户不存在、状态不是 `active` 或 `deleted_at` 非空
- **THEN** 当前用户解析 MUST 失败并提供可诊断错误
- **AND** 系统 MUST NOT 静默创建匿名用户

### Requirement: 当前用户 API
系统 SHALL 通过 `GET /api/users/me` 返回当前解析出的用户。

#### Scenario: 获取当前用户成功
- **WHEN** 客户端请求 `GET /api/users/me`
- **AND** 当前用户解析成功
- **THEN** API MUST 返回 200
- **AND** 响应体 MUST 包含 `id`、`display_name`、`email`、`avatar_url`、`status`、`deleted_at`、`created_at`、`updated_at`

#### Scenario: 当前用户不可用
- **WHEN** 客户端请求 `GET /api/users/me`
- **AND** 当前用户解析失败
- **THEN** API MUST 返回非 2xx 状态码
- **AND** 响应体 MUST 包含可诊断错误信息

#### Scenario: 不提供注册接口
- **WHEN** 客户端尝试通过本变更创建普通用户
- **THEN** 系统 MUST NOT 提供作为注册能力使用的 `POST /api/users` 接口

### Requirement: 资源归属边界
系统 SHALL 规定普通资源创建流程由后端根据当前用户解析结果写入资源归属。

#### Scenario: 前端不提交资源归属用户
- **WHEN** 后续普通前端流程创建文件、文档或知识库资源
- **THEN** 客户端 MUST NOT 要求用户填写 `owner_user_id`
- **AND** 后端 MUST 根据当前用户解析结果写入资源归属

#### Scenario: 历史资源保留用户追溯
- **WHEN** 已有关联资源的用户被软删除
- **THEN** 历史资源 MUST 保留原有用户外键值
- **AND** 系统 MUST NOT 因用户软删除而物理删除历史资源

### Requirement: 前端当前用户状态
前端 SHALL 封装当前用户读取，并在应用状态中表达当前用户加载结果。

#### Scenario: 前端获取当前用户
- **WHEN** 前端调用 `getCurrentUser()`
- **THEN** 前端 MUST 请求 `GET /api/users/me`
- **AND** 前端 MUST NOT 在业务代码中硬编码后端主机地址

#### Scenario: 前端用户加载成功
- **WHEN** `GET /api/users/me` 返回当前用户
- **THEN** 前端 user store MUST 保存当前用户
- **AND** 前端 MUST 能展示当前用户上下文

#### Scenario: 前端用户加载失败
- **WHEN** `GET /api/users/me` 返回错误或请求失败
- **THEN** 前端 user store MUST 保存错误状态
- **AND** 依赖用户归属的前端操作 MUST 显示用户不可用反馈

#### Scenario: 前端不提供认证入口
- **WHEN** 本变更完成
- **THEN** 前端 MUST NOT 新增登录、注册、退出、找回密码或用户切换入口
