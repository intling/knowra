## ADDED Requirements

### Requirement: 固定角色与服务端权限
系统 SHALL 支持 `admin`、`member`、`viewer` 三类固定角色，并由后端在每个业务请求执行权限校验。

#### Scenario: 角色能力矩阵
- **WHEN** 用户角色为 `viewer`
- **THEN** 用户 MUST 能读取、检索、问答和核对自己的资料，并管理个人账户
- **AND** MUST NOT 上传或触发资料解析、重新分块、重新向量化及用户管理
- **WHEN** 用户角色为 `member`
- **THEN** 用户 MUST 额外能够上传与处理自己的资料
- **WHEN** 用户角色为 `admin`
- **THEN** 用户 MUST 额外能够管理系统账号

#### Scenario: 普通用户绕过前端操作
- **WHEN** 非管理员直接调用用户管理 API，或只读用户直接调用资料写接口
- **THEN** 后端 MUST 返回 403 和具体权限不足原因
- **AND** MUST NOT 写入资源、创建后台任务、发送模型请求或更改目标用户

#### Scenario: 注册请求指定角色
- **WHEN** 注册请求提交 `admin` 角色、权限集或其他服务端控制字段
- **THEN** 系统 MUST 拒绝该请求或忽略其提升权限意图
- **AND** 公开注册生成的账号 MUST 仅具有普通成员权限

### Requirement: 用户管理与管理员存续
系统 SHALL 提供管理员专用的分页用户列表、角色变更与禁用/启用能力，并对每次操作读取数据库中的最新权限。

#### Scenario: 分页列表
- **WHEN** 管理员查询用户列表
- **THEN** 系统 MUST 返回公开用户字段和分页总数
- **AND** MUST NOT 返回密码哈希、会话令牌或其他认证秘密

#### Scenario: 禁用用户
- **WHEN** 管理员禁用一个账号
- **THEN** 该账号 MUST 立即无法继续使用已有会话或重新登录
- **AND** 其资料和所有权外键 MUST 保留

#### Scenario: 重新启用用户
- **WHEN** 管理员重新启用账号
- **THEN** 账号 MUST 能重新登录
- **AND** 已撤销的旧会话 MUST NOT 自动恢复有效

#### Scenario: 最后一个管理员保护
- **WHEN** 角色或状态变更会导致系统中没有有效管理员
- **THEN** 系统 MUST 拒绝并返回 409 与明确原因
- **AND** 并发请求 MUST NOT 绕过该不变量

#### Scenario: 管理员禁用自己
- **WHEN** 管理员尝试禁用当前登录的自己
- **THEN** 系统 MUST 返回 409、`code=cannot_disable_self` 与明确原因，且账号状态保持不变

#### Scenario: 角色变更即时生效
- **WHEN** 管理员把成员提升为管理员或把管理员降级
- **THEN** 目标用户的下一次请求 MUST 按新角色授权，无需重新登录

### Requirement: 管理员初始化与历史数据
系统 SHALL 提供受控管理命令建立管理员，并保留历史默认用户和资料归属；公开注册 MUST NOT 获得旧账号访问权。

#### Scenario: 第一个公开注册账号
- **WHEN** 系统还没有管理员且任意用户公开注册
- **THEN** 该账号 MUST 仍为普通成员
- **AND** MUST NOT 继承默认用户 UUID 或资料

#### Scenario: 初始化管理员
- **WHEN** 运维执行管理命令并输入独立邮箱和安全密码
- **THEN** 系统 MUST 创建可登录的管理员，且 MUST NOT 内置默认密码
- **AND** 密码 MUST NOT 经由普通命令行参数、日志或版本库暴露

#### Scenario: 默认用户历史资料
- **WHEN** 数据迁移完成但没有显式认领历史账号
- **THEN** 旧资料 MUST 保留其原始用户外键
- **AND** 旧默认账号 MUST NOT 通过匿名请求或任意新注册者访问

### Requirement: 资源所有权统一边界
资料、解析任务、解析文档、段落、分块任务、分块、向量任务、向量、管线验证、检索结果与引用 SHALL 统一限定为已认证用户拥有的资源。

#### Scenario: 访问他人的资源标识
- **WHEN** 已认证用户请求他人的资源 UUID
- **THEN** 系统 MUST 返回与资源不存在一致的 404 和可读说明
- **AND** MUST NOT 暴露该资源是否存在、名称、内容或数量

#### Scenario: 服务端确定归属
- **WHEN** 用户创建资料或派生后台任务
- **THEN** 系统 MUST 从已认证身份写入 `owner_user_id`
- **AND** MUST NOT 信任请求体提交的归属信息

#### Scenario: 后台派生任务
- **WHEN** 已授权请求创建后台任务
- **THEN** 任务 MUST 保留入队时已验证的用户和源资源归属
- **AND** 后台执行 MUST NOT 调用默认用户解析器
