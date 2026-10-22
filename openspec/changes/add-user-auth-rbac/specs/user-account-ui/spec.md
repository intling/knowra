## ADDED Requirements

### Requirement: 登录与注册界面
前端 SHALL 提供独立的 `/login` 与 `/register` 页面，沿用既有 paper、surface、ink、line、brand 令牌和本地字体，并支持桌面与 320px 宽移动端。

#### Scenario: 登录表单提交
- **WHEN** 用户填写邮箱与密码并提交登录
- **THEN** 前端 MUST 调用登录 API，提交期间禁用重复提交，并在成功后进入合法站内目标页
- **AND** 失败时 MUST 显示后端提供的可读原因，保留邮箱且 MUST NOT 将密码写入日志或持久存储

#### Scenario: 注册表单校验
- **WHEN** 用户填写显示名称、邮箱、密码和确认密码
- **THEN** 前端 MUST 校验必填项、邮箱、密码策略和两次密码一致性
- **AND** 校验失败时 MUST NOT 发出注册请求
- **AND** 注册成功后 MUST 建立账号的登录状态并进入工作台

#### Scenario: 公开入口互相跳转
- **WHEN** 用户尚无账号或已有账号
- **THEN** 登录页和注册页 MUST 提供清晰的相互导航入口
- **AND** 页面 MUST 具有表单标签、密码自动填充属性、键盘焦点和可读屏错误反馈

### Requirement: 路由认证与权限守卫
前端 SHALL 在进入私有页面前完成身份恢复。前端守卫用于界面体验，后端仍 MUST 独立校验权限。

#### Scenario: 匿名访问私有页面
- **WHEN** 未登录用户访问工作台、验证、账户或管理页面
- **THEN** 前端 MUST 跳转登录页并记录安全的站内返回路径
- **AND** MUST NOT 短暂渲染旧账号的私有内容

#### Scenario: 已登录用户进入认证页面
- **WHEN** 有效已登录用户访问登录页或注册页
- **THEN** 前端 MUST 导向其可访问的工作台

#### Scenario: 非管理员进入管理页面
- **WHEN** 成员或只读用户访问 `/admin/users`
- **THEN** 前端 MUST 提供明确的权限不足反馈
- **AND** MUST NOT 请求管理员用户列表

#### Scenario: 拒绝外部返回地址
- **WHEN** 登录链接包含外部 URL、协议相对路径或反斜线变体返回地址
- **THEN** 登录成功 MUST 返回安全的站内默认页

### Requirement: 账户管理与退出
前端 SHALL 提供 `/account` 页面和侧栏账户入口，展示角色、账户信息、资料修改、密码修改和退出操作。

#### Scenario: 修改个人资料
- **WHEN** 用户修改显示名称并保存
- **THEN** 前端 MUST 调用个人资料 API 并更新当前用户与侧栏展示
- **AND** MUST 显示保存成功或可读失败原因

#### Scenario: 修改密码
- **WHEN** 用户填写当前密码、新密码和确认密码后保存
- **THEN** 前端 MUST 校验并调用密码修改 API
- **AND** 修改成功后 MUST 清理私有状态并要求使用新密码重新登录

#### Scenario: 退出
- **WHEN** 用户选择退出
- **THEN** 前端 MUST 请求服务端撤销当前会话、清理用户私有内存并回到登录页
- **AND** MUST NOT 仅靠删除前端状态模拟退出

### Requirement: 管理员用户界面
前端 SHALL 提供仅管理员可访问的 `/admin/users` 页面，显示分页账号列表、角色和状态，支持角色变更与禁用/启用。

#### Scenario: 管理角色和状态
- **WHEN** 管理员变更账号角色或状态
- **THEN** 前端 MUST 调用管理员 API 并在成功后刷新目标行
- **AND** 高影响操作 MUST 有确认与进行中反馈

#### Scenario: 末位管理员操作失败
- **WHEN** API 拒绝会移除最后一位有效管理员的操作
- **THEN** 前端 MUST 保留原行状态并显示明确原因

### Requirement: 私有浏览器状态隔离
前端 SHALL 以服务端返回的用户 UUID 隔离浏览器对话历史，并在退出、会话失效、账号切换和跨标签页登出时清理私有内存。

#### Scenario: 同一浏览器切换账号
- **WHEN** 用户 A 创建对话后退出，用户 B 登录
- **THEN** B MUST 看不到 A 的对话、气泡、引用、上传状态或验证结果
- **WHEN** A 再次登录
- **THEN** 系统 MUST 能恢复 A 自己的历史

#### Scenario: 旧版公共存储键
- **WHEN** 浏览器仍存在 `knowra:chat` 历史
- **THEN** 系统 MUST NOT 自动将其导入任意新注册账号

#### Scenario: 在途响应与会话失效
- **WHEN** 账号切换后旧账号请求完成，或任一业务请求返回 401
- **THEN** 前端 MUST 忽略旧身份的迟到响应并清空相应私有状态
- **AND** 401 MUST 触发统一的重新登录流程

### Requirement: 只读权限反馈
前端 SHALL 根据后端返回的权限集显示可用操作。

#### Scenario: 只读用户访问工作台
- **WHEN** 只读用户登录
- **THEN** 用户 MUST 能查看自己的资料、提问和核对引用
- **AND** 上传、重新解析、重新分块和重新向量化操作 MUST 不可用并有可理解说明
