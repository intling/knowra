# 数据增量 RED 评审

## 当前状态

任务 1.1、1.2、1.3、2.1 已完成，4/36；2.2 的测试代码与失败证据已准备，等待本批红测试评审。尚未编写生产模型、服务或迁移，未连接或修改真实业务数据库。

## 已运行验证

后端目录执行：

```bash
uv run pytest tests/admin_console tests/auth/test_admin_users_api.py tests/auth/test_chat_quota.py tests/auth/test_chat_quota_api.py tests/auth/test_chat_quota_migration.py tests/auth/test_auth_migration.py -q
```

新增测试前基线：146 passed、5 skipped，8.99 秒。跳过项需要可选 PostgreSQL 测试配置。

前端目录执行：

```bash
npm run test -- src/views/__tests__/AdminConsole.spec.ts src/views/__tests__/AdminUsersView.spec.ts src/views/__tests__/AdminUsersLifecycle.spec.ts src/api/adminUsers.test.ts src/router/__tests__ src/components/shared/__tests__/ConfirmDialog.spec.ts
```

结果：7 个测试文件、68 passed，4.56 秒。

首批 RED，后端目录执行：

```bash
uv run pytest tests/admin_console/test_operations_schema.py tests/admin_console/test_operations_migration.py -q --tb=short --junitxml=../openspec/changes/redesign-admin-console/evidence/data-red.xml
```

结果：15 failed，0 error，0.48 秒，进程退出码 1。失败原因均为预期新能力缺失：

- 缺少 `admin_audit_events`、`model_probe_results` 注册及实际持久化结构。
- 缺少 `model_profiles.revision`。
- Alembic 仍停在既有模型配置迁移，缺少本变更的增量迁移。

未将收集错误、导入错误或工具缺失视作 RED。原始输出见 `data-red.txt`，机器可读结果见 `data-red.xml`。

测试文件的 `ruff check` 和 `ruff format --check` 均通过；没有运行应用全套验证或声称功能已完成。

## 本批评审范围

- `test_operations_schema.py`：历史可追溯、删除关联、配置快照、状态约束、查询索引、时间类型和存储字段边界。
- `test_operations_migration.py`：从真实迁移图发现增量 head，实际迁移 roundtrip，逐行比较已有账号、凭据、会话、额度、完整资料链、向量和默认绑定。
- 测试只使用独立 SQLite 和临时目录；真正 PostgreSQL 的迁移、锁和多进程一致性仍由后续任务验证。

## 评审点来源

`openspec/config.yaml:64` 明确要求：“输出红测试代码后必须立刻停止生成，并明确提示用户：‘红测试已生成，请评审。确认无误后，请回复‘继续’，我将进入绿测试阶段。’在用户明确回复‘继续’或给出修改意见前，不得进入绿测试阶段。”

本变更 `tasks.md` 的 2.2 继承该规则。本次实施授权后已完成首批测试的具体编写和 RED 确认，接下来需要针对这批可评审测试通过评审点。
