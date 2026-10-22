# 用户体系变更前的验证基线

执行日期：2026-10-20。以下结果在新增用户体系测试和修改生产代码之前取得。

| 范围 | 命令 | 实际结果 |
| --- | --- | --- |
| 后端既有用户模块 | `cd backend && uv run pytest tests/api/test_users.py tests/services/test_user_service.py tests/models/test_user.py tests/alembic/test_create_users_migration.py -q` | 14 passed |
| 前端既有用户、路由与 API client | `cd front && npm run test -- src/api/users.test.ts src/stores/user.test.ts src/router/__tests__/index.spec.ts src/api/client.test.ts` | 4 files passed，10 tests passed |
| 后端全量 | `cd backend && uv run pytest -q` | 3 failed，956 passed，4 skipped，耗时 41.76s |
| 前端全量 | `cd front && npm run test` | 36 files passed，471 tests passed，耗时 19.21s |

后端既有失败用例：

- `tests/api/test_document_chunking.py::test_post_rechunk_returns_202_and_created_job`
- `tests/api/test_uploads.py::test_post_uploads_returns_created_record_and_stores_file`
- `tests/services/test_upload_service.py::test_create_upload_force_replaces_duplicate`

后续验收必须逐项复核，不能把这些失败归因于新变更，也不能以既有失败为由忽略新增回归。

当前工作区原有的 `.playwright-mcp/`、`knowra-new-settings-popover.png` 和 `knowra-new-welcome.png` 不属于本变更。
