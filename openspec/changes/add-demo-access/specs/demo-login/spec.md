## Purpose

为网申和面试试用提供可直接分享的登录入口，使访问者无需手输共享演示凭据即可开始了解基于资料的问答流程，同时在表单中说明共享额度并避免凭据留存在地址、日志和浏览器持久存储中。

## ADDED Requirements

### Requirement: 演示链接预填登录表单

登录页 SHALL 从 URL 片段中读取演示凭据，只有明确指定的 demo@deerfd.com 身份和有效字符串密码可以自动填入。该操作 MUST NOT 自动登录或触发提交；密码 MUST NOT 硬编码于生产源码。

#### Scenario: 正确链接
- **WHEN** 未登录访问者打开 /login#demo= 加有效 base64url 编码的 JSON email/password
- **THEN** 邮箱与密码输入框 MUST 自动填好
- **AND** 页面 MUST 显示演示账号最近 60 分钟最多成功问答 3 次且额度共享的提示
- **AND** 点击登录后 MUST 通过普通认证流程验证该表单，不附加后端认证旁路

#### Scenario: 无效片段
- **WHEN** 片段不是有效有界 JSON 对象、邮箱属于其他账号、密码为空或过长、或 demo 参数重复
- **THEN** 系统 MUST 忽略该片段、不抛页面运行错误、不填入任意攻击者内容

#### Scenario: 普通登录
- **WHEN** 访问者打开没有演示片段的登录页
- **THEN** 表单 MUST 保持普通空表单和原有登录/错误行为

### Requirement: 凭据消费后清理

系统 SHALL 在消费演示片段后通过替换当前地址清除片段，保持合法站内 redirect，并 MUST NOT 将密码写入 query、localStorage、sessionStorage、IndexedDB、日志或网络探测请求。

#### Scenario: 填充后地址清除
- **WHEN** 演示片段成功填表或因内容无效被忽略
- **THEN** 当前登录页地址 MUST 移除 demo 片段且不新增带秘密的历史项
- **AND** 仅表单内存保留密码，重新打开清理后的地址 MUST 不再自动恢复凭据

#### Scenario: 失败清空密码
- **WHEN** 用户提交演示凭据但普通认证失败
- **THEN** 页面 MUST 保留邮箱、清空密码并显示原有可读失败原因
- **AND** MUST NOT 在日志或持久存储记录凭据

### Requirement: 公网演示入口

共享入口 SHALL 使用既有 HTTPS 域名，访问者可以直接进入登录页；私有 API 仍 MUST 由应用会话认证与权限控制保护。

#### Scenario: 无浏览器认证弹窗
- **WHEN** 面试官在新浏览器打开分享链接
- **THEN** 系统 MUST 展示可预填的应用登录页，无额外 Basic 认证弹窗
- **AND** 匿名访问私有 API MUST 返回有可读原因的 401，不能取得其他用户资料
