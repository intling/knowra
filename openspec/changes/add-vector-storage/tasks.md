## 1. 测试（红测试阶段）

- [x] 1.1 编写 DocumentEmbedding 模型测试：验证 `embedding_vector` 字段能接受 `list[float]` 并正确映射到 `Vector(2560)` 类型
- [x] 1.2 编写 `_save_embeddings()` 双写测试：验证新生成的向量同时写入 `embedding_json` 和 `embedding_vector`，两列值一致
- [x] 1.3 编写回填验证测试：先在测试 DB 写入仅含 `embedding_json` 的旧格式数据，运行回填后验证 `embedding_vector` 值正确
- [x] 1.4 编写迁移测试：验证 `upgrade()` 正确添加 `embedding_vector vector(2560)` 列并回填数据；验证 `downgrade()` 正确删除列

## 2. 模型层

- [x] 2.1 在 `models/document_embedding.py` 的 `DocumentEmbedding` 中新增 `embedding_vector` 字段，使用 `pgvector.sqlalchemy.Vector(2560)` 类型，`sa_column=Column(Vector(2560), nullable=False)`
- [x] 2.2 从 `pgvector.sqlalchemy` 导入 `Vector` 类型

## 3. Alembic 迁移

- [x] 3.1 创建新迁移文件（如 `20260720_0001_add_embedding_vector_column.py`），设置正确的 `down_revision`
- [x] 3.2 在 `upgrade()` 中添加 `ALTER TABLE document_embeddings ADD COLUMN embedding_vector vector(2560)`
- [x] 3.3 在 `upgrade()` 中实现分批回填：循环 `UPDATE ... SET embedding_vector = embedding_json::vector WHERE embedding_vector IS NULL AND id IN (SELECT id ... LIMIT 500)`
- [x] 3.4 回填前添加数据完整性预检：检查 `jsonb_array_length(embedding_json) != 2560` 的行并记录警告日志
- [x] 3.5 回填后添加验证：确认 `WHERE embedding_vector IS NULL` 行数为 0
- [x] 3.6 回填验证通过后在 `upgrade()` 中添加 NOT NULL 约束：`ALTER COLUMN embedding_vector SET NOT NULL`
- [x] 3.7 在 `downgrade()` 中添加 `ALTER TABLE document_embeddings DROP COLUMN embedding_vector`

## 4. 服务层

- [x] 4.1 更新 `services/document_embedding.py` 的 `_save_embeddings()` 方法，在创建 `DocumentEmbedding` 时增加 `embedding_vector=result.embedding` 参数
- [x] 4.2 添加结构化日志记录双写行为（如 `logger.debug("Embedding records persisted", job_id=str(job.id), count=len(results), dual_write=True)`）

## 5. 集成验证

- [x] 5.1 端到端集成测试：上传文件 → 解析 → 分块 → 向量化 → 验证 `embedding_json` 和 `embedding_vector` 两列都有数据且值一致
- [x] 5.2 重新向量化后双写仍然正确的测试
- [x] 5.3 验证 `embedding_vector` 列可接受 pgvector 距离算子查询（`<=>`）

## 6. 质量门禁

- [x] 6.1 运行 `uv run ruff check .` 确认无 lint 错误
- [x] 6.2 运行 `uv run ruff format --check .` 确认格式正确
- [x] 6.3 运行 `uv run pytest` 确认全部测试通过
- [x] 6.4 验证迁移可重复执行（upgrade → downgrade → upgrade 幂等）
