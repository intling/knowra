# 实施基线与首批测试范围

## 已完成的基线

- 既有后端后台、账号管理、限额及相关迁移：146 passed、5 skipped，8.99 秒；跳过项需要可选 PostgreSQL 测试配置，未将 SQLite 结果表述为 PostgreSQL 并发验证。
- 既有前端后台、用户生命周期、账号 API、路由和确认框：7 个文件、68 passed，4.56 秒。
- 原始输出见 `backend-baseline.txt` 和 `frontend-baseline.txt`；工作区原有四个修改文件的 SHA-256 和 HEAD 见 `workspace-baseline.json`。

## 需求与后续测试边界

| 规范 | 后端验证 | 前端与浏览器验证 |
| --- | --- | --- |
| admin-workspace | 总览统计、软删除排除、零分母、依赖失败、operations:read | 六页入口、原 URL、旧响应竞态、抽屉与 320/768/1440px |
| admin-account-controls | 字面子串搜索、额度占用/边界、无额度行切换并发、会话撤销、操作者失权 | 搜索防抖、详情、确认取消、重复提交、自身引导、秘密清理 |
| admin-model-diagnostics | 生效来源、配置版本、固定样例、超时/限流、目标地址约束、租约清理 | 保存/测试/激活分离、四用途卡片、过期提示、向量冲突 |
| admin-operational-monitoring | 三类任务关联和安全投影、范围/分页、系统检查截止时间和 scope | 无虚构进度、局部失败、阶段时间线、刷新不调用外部模型 |
| admin-audit-log | 白名单、同事务回滚、失败审计、查询权限与时间边界 | 按操作者/动作/trace ID 查询、安全前后值、空/错误态 |

## 首批 RED：任务 2.1

新增 `backend/tests/admin_console/test_operations_schema.py` 与 `test_operations_migration.py`，先验证数据增量，不提前编写生产模型或迁移。

- metadata 注册，模型配置非空起始版本。
- 审计记录保留 UUID，账号软删除、管理对象删除后仍能追溯。
- 模型删除后诊断关联置空，历史结果及所测版本保留。
- 诊断在途到终态的持久化，以及配置变化后的版本隔离。
- 审计结果、诊断状态数据库约束；时间与过滤索引；无专用秘密/正文列。JSON 内容白名单由后续审计服务行为测试覆盖。
- 从真实 Alembic 迁移图验证唯一增量 head；实际执行 upgrade/downgrade/upgrade，逐行比较账号、凭据、会话、额度、完整资料链、2560 维向量与原默认绑定。

本批采用独立内存 SQLite 并启用外键，不访问真实业务库、服务器文件或外部模型。PostgreSQL 真实迁移和并发仍由任务 2.4、3.3、4.3、6.4 覆盖，不在本批声称完成。

## 已明确的契约

首期角色保持 admin/member/viewer；新增只读权限 operations:read、audit:read 仅授予 admin。所有新接口、统计口径、UTC 半开窗口、31 天范围、稳定分页及错误码以 design 第 5、6 节为准。新增审计/诊断结构使用 design 第 9 节字段；诊断持久状态限定 running/passed/failed/interrupted，unknown 由过期租约推导。

管理审计动作采用 `user.create`、`user.update`、`user.reset_password`、`user.delete`、`user.chat_limit.update`、`user.sessions.revoke`、`model.create`、`model.update`、`model.activate`、`model.deactivate`、`model.delete`、`model.test`；结果为 success/denied/failed，resource_type 为 user/model。这些枚举须在业务实现前落实到规范及请求/响应模型，禁止存入任意客户端事件。
