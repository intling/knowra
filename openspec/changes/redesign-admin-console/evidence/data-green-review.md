# 数据增量 GREEN 验证

用户回复“请继续”后，完成已评审的 15 项数据 RED 对应最小实现。

## 实现范围

- 新增 `AdminAuditEvent`、`ModelProbeResult`，统一注册于 `models.base`。
- 模型配置增加非空 `revision`，Python/SQL 默认值均为 1。
- Alembic `20261022_0002` 接在实际旧 head `20261022_0001` 后；新增两表及查询索引。
- 删除模型配置时诊断关联 SET NULL，审计保留原资源 UUID；不增加私有资料或凭据列。
- 原认证/额度迁移测试改为验证唯一 head 及祖先链，继续保留历史父节点断言，允许新增迁移。
- 根 README、后端 README 同步结构及回退说明；新页面、审计写服务及诊断接口尚未实现。

## 实际验证

1. `uv run pytest tests/admin_console/test_operations_schema.py tests/admin_console/test_operations_migration.py -q --tb=short`：**15 passed**，见 `data-green-initial.txt`。
2. 原后台及认证/额度相关回归，配置一次性 PostgreSQL 的 `ADMIN_TEST_DATABASE_URL`：**165 passed, 1 skipped**。4 项原 PostgreSQL 并发测试实际通过；剩余额度并发测试另设 `CHAT_QUOTA_TEST_DATABASE_URL` 单独运行：**1 passed**，验证 8 个同时请求恰好放行 3 个。见 `data-backend-regression.txt`、`data-quota-postgres.txt`。
3. `uv run pytest -q --tb=short`，同样启用原后台 PostgreSQL 并发：**1252 passed, 5 skipped**，见 `data-backend-full.txt`。此结果在新增下一批审计 RED 测试前取得。
4. 本次变更的 9 个 Python 文件 Ruff 检查及格式检查均通过，见 `data-ruff-changed.txt`、`data-format-changed.txt`。
5. 全库 Ruff 仍报告 39 个既有问题，涉及的 9 个文件均不在本次修改中；全库格式检查报告 6 个既有文件。见 `data-ruff-all.json`、`data-format-all.txt`。未批量修改无关历史代码。

## 真实 PostgreSQL 迁移往返

使用新建的 `pgvector/pgvector:pg18` 一次性容器及 `knowra_verify` 库，绑定本机临时端口；没有复用现有容器的数据库或读取其凭据。脚本 `verify_operations_postgres.py` 只接受本机同名验证库。

从空库运行全部历史迁移至 `20261022_0001`，填入合成账号、凭据、真实格式会话、额度、完整文档/分块/2560 维向量及旧模型绑定。随后实际执行：

```bash
uv run alembic upgrade head
uv run alembic downgrade 20261022_0001
uv run alembic upgrade head
```

三个阶段均逐行比较 **15 张旧表、19 条记录**，全部保持；向量维度为 2560。升级验证默认 revision、新表及索引，降级只移除两张新表和 revision 列。结果见 `data-postgres-roundtrip.txt`。该降级检查不适用于生产业务库，代码回退应保留历史。

完成验证后已停止并删除本次一次性容器。原有 4 个用户修改文件的 SHA-256 均与开工快照一致；全库 Ruff 涉及的文件也均与 HEAD 一致，见 `data-preservation-check.json`。
