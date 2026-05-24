## 1. 契约与后端测试

- [x] 1.1 为 `uploaded_files` SQLModel 和 Alembic migration 编写失败测试，覆盖字段、用户外键、`storage_key` 唯一约束和关键索引。
- [x] 1.2 为上传配置编写失败测试，覆盖上传存储目录、单文件大小限制和允许内容类型的默认值与环境变量读取。
- [x] 1.3 为上传服务编写失败测试，覆盖服务端生成 `storage_key`、保存原始文件、计算 `byte_size` 和 `checksum_sha256`、写入当前用户归属元数据。
- [x] 1.4 为上传服务错误分支编写失败测试，覆盖空文件、超出大小限制、不允许内容类型、存储写入失败和元数据失败后的文件清理。
- [x] 1.5 为 `POST /api/uploads` 编写失败测试，覆盖 `201` 成功响应结构、缺少文件字段、当前用户不可用、空文件和超限文件。
- [x] 1.6 运行新增后端测试并确认因上传能力尚未实现而 RED。

## 2. 后端实现

- [ ] 2.1 增加 multipart 解析所需后端依赖并更新锁文件。
- [ ] 2.2 在 `backend/app/core/config.py` 和 `backend/.env.example` 中增加上传存储目录、单文件大小限制和允许内容类型配置。
- [ ] 2.3 新增 `UploadedFile` 数据模型并确保模型被 Alembic metadata 发现。
- [ ] 2.4 新增 Alembic migration 创建 `uploaded_files` 表、外键、唯一约束和索引，并实现 downgrade。
- [ ] 2.5 新增上传响应 schema，统一时间字段序列化风格。
- [ ] 2.6 新增本地文件存储服务，负责安全路径生成、按块写入、校验值计算和失败清理。
- [ ] 2.7 新增上传业务服务，串联当前用户解析、文件校验、本地存储和元数据入库。
- [ ] 2.8 新增 `/api/uploads` 路由并注册到后端 API router，保持路由层只处理参数、依赖和 HTTP 错误映射。
- [ ] 2.9 运行后端相关测试，确认后端上传能力达到 GREEN。

## 3. 前端测试

- [x] 3.1 为 `front/src/api/uploads.ts` 编写失败测试，覆盖 `multipart/form-data` 上传、成功响应解析和错误响应处理。
- [x] 3.2 为首页附件上传流程编写失败测试，覆盖选择文件、提交上传、上传中禁用重复提交、成功后清空文件和失败后展示错误。
- [x] 3.3 为当前用户不可用场景编写失败测试，确认上传不可提交且展示用户不可用反馈。
- [x] 3.4 运行新增前端测试并确认因上传前端能力尚未实现而 RED。

## 4. 前端实现

- [ ] 4.1 新增 uploads API 类型和 `uploadFile(file)` 封装，继续使用 `VITE_API_BASE_URL` 和 `/api` 前缀约定。
- [ ] 4.2 更新首页附件提交流程，在有文件时调用上传 API，并确保请求不包含 `owner_user_id`。
- [ ] 4.3 增加上传中、上传成功、上传失败和当前用户不可用的页面状态反馈。
- [ ] 4.4 防止上传中重复提交，并在上传成功后清空本地文件选择。
- [ ] 4.5 运行前端相关测试，确认前端上传体验达到 GREEN。

## 5. 文档与集成验证

- [ ] 5.1 更新后端 README 或根 README，说明上传 API、上传配置、存储目录和本地文件清理注意事项。
- [ ] 5.2 更新前端 README 或相关文档，说明附件上传工作流和开发环境 API 代理要求。
- [ ] 5.3 运行 `uv run ruff check .`、`uv run ruff format --check .` 和 `uv run pytest` 验证后端。
- [ ] 5.4 运行 `npm run lint`、`npm run test` 和 `npm run build` 验证前端。
- [ ] 5.5 执行 Alembic upgrade/downgrade 验证，确认 `uploaded_files` migration 可正向和反向执行。
- [ ] 5.6 启动本地前后端并用浏览器或 API smoke check 验证有效文件上传、用户不可用错误和超限错误。
