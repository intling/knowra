# 成功审计事务底座 GREEN 验证

本批 47 项 RED 测试已获用户“请继续”确认。已完成任务 3.2、3.3，当前为 10/36。

## 实现

- `app/services/admin_audit.py` 提供唯一提交边界；业务状态和成功事件同事务提交。
- 原账号创建、角色/状态调整、改密、软删除，以及模型创建、修改、默认启停、删除共九类写操作接入。
- 创建尝试预分配资源 UUID；拒绝/失败先回滚，再独立提交 denied/failed，保留原业务错误。
- 动作字段白名单生成实际前后变化；密码重置变化为空，密钥与地址仅布尔标记。
- 审计不可写时返回 503 `admin_audit_unavailable`，全业务事务回滚；失败留痕也不可写时仅输出固定事件和安全标识。
- 原管理员存续锁、模型绑定锁、向量空间保护及 API 成功契约继续保留。
- README 与后端章程同步事务约束；新页面和账号新查询接口尚未实现。

## 实际验证

```bash
uv run pytest tests/admin_console/test_audit_transactions.py -q --tb=short
# 47 passed in 3.83s

ADMIN_TEST_DATABASE_URL=<一次性库> uv run pytest tests/admin_console/test_postgres_concurrency.py -q --tb=short
# 15 passed in 3.27s

ADMIN_TEST_DATABASE_URL=<一次性库> CHAT_QUOTA_TEST_DATABASE_URL=<一次性库> uv run pytest -q --tb=short
# 1311 passed, 4 skipped in 41.10s
```

原始输出分别为 `audit-green-initial.txt`、`audit-postgres.txt`、`audit-backend-full.txt`。
全量结果在编写下一批账号查询 RED 测试前取得，4 项跳过保留原集成开关。

## PostgreSQL 验证范围

新建 `pgvector/pgvector:pg18` 一次性容器，迁移至 head 后各测试另建 UUID schema。
角色降级、相互禁用/删除验证了唯一成功、一条独立拒绝审计、会话撤销及管理员存续；
并发激活验证了两次绑定版本与两条成功事件一致，向量入队仍阻止不兼容切换。

九类操作使用真实 PostgreSQL 触发器拒绝 success INSERT，随后逐表比较业务值完全不变；
允许的独立失败审计均成功提交。另验证 JSON 台账及应用日志无密码/哈希、会话材料、
密钥明密文、加密主密钥、配置显示名与完整地址。所有数据均为合成夹具，未访问业务库。

## 静态检查

本批修改 Python 文件 Ruff 与格式检查通过，见 `audit-ruff-changed.txt`、`audit-format-changed.txt`。
全库仍有先前已记录的 39 个 Ruff 问题及 6 个待格式化文件，均位于未修改的历史文件，
详见 `audit-ruff-all.json`、`audit-format-all.txt`；没有批量修整无关代码。

全库 Ruff 的 39 个问题逐条与上一阶段基线一致，涉及文件均未修改；原有 4 个用户修改文件
SHA-256 全部保持一致，见 `audit-preservation-check.json`。验证完成后已停止并删除本次一次性容器。
