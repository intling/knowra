## ADDED Requirements

### Requirement: 独立管理工作区与入口兼容
前端 SHALL 提供运行总览、用户管理、模型服务、处理任务、操作审计、系统状态六个页面；`/admin` MUST 进入 `/admin/overview`，原 `/admin/users` 和 `/admin/models` MUST 继续可用。此入口规则在本变更实施后替代 `add-admin-console` 中旧的 `/admin` 重定向规则。

#### Scenario: 管理员导航
- **WHEN** 管理员从账户菜单进入后台
- **THEN** 页面 MUST 展示总览及六个管理页面的导航、当前位置和返回知识书房入口
- **AND** 直接打开原用户和模型地址 MUST 显示对应页面

#### Scenario: 无权访问
- **WHEN** 访客打开后台地址
- **THEN** 系统 MUST 跳转登录并仅保留安全站内返回地址
- **WHEN** 已登录成员或只读用户打开后台地址
- **THEN** 页面 MUST 显示权限不足且 MUST NOT 请求管理数据
- **AND** 直接调用管理接口 MUST 返回 403 `forbidden` 与明确原因

### Requirement: 有口径的运行总览
系统 SHALL 通过 `GET /api/admin/overview` 返回管理员运行统计，包含 `snapshot_at,users,uploads,jobs_by_kind,attention_items`。账号、资料和容量 MUST 使用设计中定义的有效记录口径；三类任务 MUST 独立计算当前排队/运行计数及最近 24 小时完成结果。该接口 MUST 要求 `operations:read`。

#### Scenario: 可解释统计
- **WHEN** 管理员查看运行总览
- **THEN** 界面 MUST 标明统计时间、最近 24 小时口径及“原文件逻辑容量”
- **AND** 账号 active 数 MUST NOT 表述为在线人数
- **AND** 任一阶段成功率 MUST NOT 表述为整条资料处理链的成功率

#### Scenario: 无数据与依赖失败
- **WHEN** 查询成功但没有账号以外的业务资料或任务
- **THEN** 对应计数 MUST 为 0，成功率无分母时 MUST 为 null 并显示“暂无数据”
- **WHEN** 某区块无法读取
- **THEN** 对应字段 MUST 为 null 并附不可用状态，界面 MUST NOT 使用 0 或伪造趋势替代
- **AND** 其他成功区块 MUST 继续显示

#### Scenario: 异常定位
- **WHEN** 总览显示失败任务或模型配置异常
- **THEN** 管理员 MUST 能进入对应带筛选条件的任务、模型或系统页面
- **AND** 读取总览 MUST NOT 调用外部付费模型或读取他人正文、问答、chunk、向量和引用内容

### Requirement: 一致的查询与操作状态
后台列表 SHALL 使用服务端分页和筛选，默认 20 条、最大 100 条；筛选变化 MUST 回到第一页，较早请求返回 MUST NOT 覆盖更新的结果。模型、密码和高风险操作 MUST 延续已有确认及秘密清理规则。

#### Scenario: 查询与刷新
- **WHEN** 管理员改变筛选并立即再次改变
- **THEN** 页面 MUST 最终展示最新查询对应的数据，且总数 MUST 为该条件下全量结果数
- **WHEN** 已有数据的刷新失败
- **THEN** 界面 MUST 显示失败原因并将保留数据明确标记为旧数据

#### Scenario: 表单和确认
- **WHEN** 管理员提交表单或确认高风险操作
- **THEN** 系统 MUST 阻止相同操作重复提交并明确反馈成功或失败
- **AND** 取消确认 MUST NOT 执行写请求，保存后不匹配当前筛选 MUST 给出说明
- **AND** 删除账号 MUST 要求输入目标邮箱并说明软删除、资料保留与会话失效；无邮箱旧账号 MUST 改为明确要求完整账号 UUID，不能使用可重复的显示名称
- **AND** 关闭、成功或卸载密码/密钥表单 MUST 清除秘密且 MUST NOT 写入日志、URL 或持久存储

### Requirement: 响应式与可访问性
后台 SHALL 沿用项目语义令牌及本地字体，支持 320px、768px、1440px 布局；窄屏导航与详情 MUST 可完整操作，状态 MUST 同时提供文本，不单靠颜色。

#### Scenario: 键盘和窄屏
- **WHEN** 管理员在 320px 宽度查看列表、详情或表单
- **THEN** 页面 MUST 无整体横向溢出并保留主要操作
- **WHEN** 使用键盘打开抽屉及确认框
- **THEN** 最上层 MUST 约束焦点、支持 Esc 关闭并归还触发控件焦点
