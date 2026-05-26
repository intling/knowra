## Context

knowra 已经有基础用户体系：后端通过 `get_current_user(session)` 解析当前用户，前端通过 `GET /api/users/me` 读取当前用户上下文，普通业务资源不应由前端提交 `owner_user_id`。前端首页也已经存在附件选择入口，但当前只在本地展示选中文件，没有把文件提交到后端。

本变更位于核心工作流的第一步“接入资料”。目标是先把用户文件可靠保存到 knowra 的应用内存储，并记录可追溯元数据。后续文档解析、分块、索引和 RAG 可以消费这份上传记录，但不在本变更内实现。

整体数据流：

```text
前端 File input
  -> POST /api/uploads multipart/form-data
  -> 后端 get_current_user(session)
  -> UploadService 校验并生成 storage_key
  -> LocalFileStorage 写入原始文件
  -> uploaded_files 写入元数据
  -> 返回上传记录
```

## Goals / Non-Goals

**Goals:**

- 提供单文件上传 API，将原始文件保存到应用内本地存储目录。
- 为每个上传文件创建 `uploaded_files` 元数据记录，并通过 `owner_user_id` 关联当前用户。
- 保证前端不提交资源归属用户，上传归属只来自后端当前用户解析。
- 提供可配置的上传存储目录、单文件大小限制和允许内容类型。
- 前端在现有附件选择入口上接入上传调用，并展示上传中、成功、失败和用户不可用反馈。
- 通过测试覆盖 API 状态码、响应结构、归属写入、错误分支、前端 API 封装和关键 UI 状态。

**Non-Goals:**

- 不实现登录、注册、退出、用户切换、团队权限或资源授权模型。
- 不实现文档解析、OCR、分块、embedding、pgvector 索引、检索、RAG 或引用生成。
- 不实现对象存储、预签名上传、断点续传、多文件批量上传或文件下载。
- 不基于上传文件内容立即回答问题；本阶段只完成“原始资料进入系统”的存储闭环。

## Decisions

### Decision 1: 上传接口使用 `POST /api/uploads`

路由新增在后端 API 聚合下，业务路径为 `POST /api/uploads`。请求使用 `multipart/form-data`，文件字段名为 `file`。成功时返回 `201 Created` 和上传记录响应。

响应字段包含：

- `id`
- `owner_user_id`
- `original_filename`
- `content_type`
- `byte_size`
- `storage_key`
- `checksum_sha256`
- `status`
- `error_message`
- `deleted_at`
- `created_at`
- `updated_at`

选择理由：`uploads` 表达“原始上传事件/资源”，比 `documents` 更适合当前阶段，因为文件尚未解析成文档。使用单文件接口可以先稳定契约和错误语义，避免批量上传的一致性问题。

替代方案：

- `POST /api/documents`：会暗示文件已经完成文档化处理，当前不采用。
- 聊天发送接口同时接收问题和文件：会提前耦合问答流程，当前不采用。
- 批量上传接口：后续可以在单文件能力稳定后增加，当前不采用。

### Decision 2: 数据库新增 `uploaded_files` 表

新增 SQLModel 模型和 Alembic migration。表字段建议为：

- `id`: UUID 主键。
- `owner_user_id`: UUID，外键关联 `users.id`，非空。
- `original_filename`: 原始展示文件名，非空。
- `content_type`: 客户端上报的 MIME 类型，可空。
- `byte_size`: 文件大小，非空。
- `storage_key`: 应用内存储键，非空且唯一。
- `checksum_sha256`: 原始文件 SHA-256，可空或非空；实现时推荐写入。
- `status`: 上传状态，首批支持 `stored`、`failed`、`deleted`。
- `error_message`: 失败诊断信息，可空。
- `deleted_at`: 软删除时间，可空。
- `created_at` / `updated_at`: 时间字段。

索引建议：

- `owner_user_id`
- `status`
- `created_at`
- `storage_key` 唯一约束

选择理由：上传记录需要同时支撑用户资料列表、后续解析任务输入、审计和失败诊断。把文件二进制保存在数据库外，数据库只保存稳定存储键，便于后续替换存储后端。

替代方案：

- 文件二进制直接入库：实现简单但会让数据库膨胀，不利于后续大文件和对象存储演进，当前不采用。
- 只保存文件不入库：无法按用户追溯、无法支撑后续解析状态和资料列表，当前不采用。

### Decision 3: 本阶段使用本地文件存储服务

新增 `LocalFileStorage` 或同等服务边界，负责根据 `storage_key` 写入文件。配置项建议：

- `upload_storage_dir`: 默认 `storage/uploads`。
- `max_upload_bytes`: 默认 20 MiB。
- `allowed_upload_content_types`: 默认允许常见文档和纯文本类型，例如 PDF、Markdown、TXT、DOCX。

存储键格式建议：

```text
uploads/{owner_user_id}/{upload_id}/original{safe_extension}
```

真实路径由 `upload_storage_dir` 和 `storage_key` 组合得到。原始文件名只作为展示字段，不参与路径拼接。扩展名从原始文件名中提取时必须做安全化处理；没有可信扩展名时可以省略或使用 `.bin`。

选择理由：本地存储适合当前项目阶段和本地开发，配置和测试成本低。保留存储服务边界，可以在后续切换到 MinIO、S3 或 OSS，而不改变上传 API 和数据库主键。

替代方案：

- 直接在路由中写文件：短期少一个类，但会让校验、路径、安全和测试逻辑散在路由层，当前不采用。
- 立即接入对象存储：更接近生产但需要凭据、桶策略和部署依赖，会扩大当前变更范围，当前不采用。

### Decision 4: 上传服务先写文件，再提交元数据

服务层负责完整流程：

1. 解析当前用户。
2. 校验文件存在、非空、未超过大小限制、内容类型在允许范围内。
3. 生成上传 ID 和 `storage_key`。
4. 以流式方式写入本地存储，同时计算 `byte_size` 和 `checksum_sha256`。
5. 写入 `uploaded_files` 元数据，状态为 `stored`。
6. 返回响应 schema。

如果文件写入失败，不创建成功记录。如果元数据提交失败，应尽量清理刚写入的文件，避免孤儿文件。若需要记录失败诊断，可以只在已能确定上传 ID 的情况下写入 `failed` 状态，但 API 不应把失败记录伪装成成功。

选择理由：文件系统和数据库无法形成真正原子事务，先写文件再写元数据更容易避免数据库中出现指向不存在文件的成功记录。清理失败文件是主要一致性补偿。

替代方案：

- 先写数据库 `pending` 再写文件：有利于记录每次尝试，但失败后会留下更多中间状态；当前没有后台任务消费，先不引入。
- 路由层直接处理事务：会让 API 层过厚，当前不采用。

### Decision 5: 前端在现有附件入口上增加上传状态

前端新增 `front/src/api/uploads.ts`，封装 `uploadFile(file: File)`。现有首页附件区域增加上传状态：

- 未选文件：保持现有输入体验。
- 已选文件：显示文件名和可移除操作。
- 上传中：禁用重复提交，显示上传中反馈。
- 上传成功：清空选中文件，并展示成功状态或记录信息。
- 上传失败：保留文件选择，展示可理解错误。
- 当前用户不可用：禁用上传并展示用户不可用反馈。

选择理由：当前产品还没有资料管理页，直接在已有入口接入上传可以形成最小闭环。前端状态保持轻量，不引入复杂上传队列。

替代方案：

- 新建完整资料管理页面：更完整但范围更大，当前不采用。
- 只做 API 不改前端：无法完成用户可见资料接入体验，当前不采用。

## Risks / Trade-offs

- 大文件导致内存压力 → 服务层必须按块读取并写入，测试覆盖大小限制，避免一次性读取完整文件。
- 文件写入成功但数据库写入失败 → 元数据提交失败时执行文件清理；后续可增加孤儿文件巡检任务。
- 客户端伪造文件名或路径 → 原始文件名只用于展示；真实路径由服务端生成，并对扩展名做安全化处理。
- MIME 类型不可信 → 本阶段只作为基础过滤和展示，不把它作为安全边界；后续解析前可增加内容嗅探。
- 当前默认用户不可用 → 上传 API 返回明确错误，不创建无归属资源。
- 本地存储不适合多实例部署 → 当前阶段接受该限制；通过 `storage_key` 和存储服务接口为对象存储替换保留空间。
- 上传与提问仍未打通 → 这是刻意的阶段边界；后续用独立变更消费 `uploaded_files` 做解析和索引。

## Migration Plan

1. 增加后端依赖以支持 `multipart/form-data`，并更新锁文件。
2. 增加配置项：上传存储目录、大小限制和允许内容类型；同步 `.env.example`。
3. 新增 `uploaded_files` SQLModel 模型和 Alembic migration。
4. 新增上传 schema、上传服务、本地存储服务和 `/api/uploads` 路由。
5. 新增前端 uploads API 封装，更新现有附件提交流程和 UI 状态。
6. 更新 README 或端侧文档，说明上传配置、存储目录和 API 行为。
7. 回滚时先撤销前端调用和后端路由，再通过 Alembic downgrade 删除 `uploaded_files` 表；本地已写入文件按 `upload_storage_dir` 进行人工或脚本清理。
