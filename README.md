# 知寻 knowra

知寻（knowra）是一个面向个人知识库的 AI 助手项目。

它的核心思想很简单：用户把自己的文档、笔记、资料上传到系统后，可以直接用自然语言提问，系统从这些资料中查找相关内容，并基于真实文档生成回答，同时给出来源引用。

## 项目定位

知寻不是一个通用聊天机器人，而是一个围绕“个人资料”的知识问答工具。

它希望解决的问题是：

- 资料越来越多，靠文件名和关键词很难快速找到信息；
- 文档之间的知识关系分散，人工整理成本高；
- 直接把私有资料交给公开 AI 工具存在隐私风险；
- AI 回答如果没有来源引用，难以判断是否可信。

因此，知寻更关注三个方向：

- **私有知识管理**：让用户自己的文档成为可查询、可追溯的知识库；
- **基于文档的智能问答**：回答尽量来自用户上传的资料，而不是凭空生成；
- **可验证的 AI 回答**：每个重要结论都应能追溯到原始文档片段。

## 基本工作流

```text
上传文档 -> 解析文本 -> 文档分块 -> 建立索引 -> 用户提问 -> 检索相关内容 -> 生成带引用的回答
```

后续会逐步扩展查询改写、HyDE、知识图谱和效果评测等能力。当前实现已经支持资料上传、Docling 解析、解析后自动分块、embedding 向量化、跨文档语义检索（pgvector 余弦距离）和基于检索结果的 RAG 回答生成（含来源引用、幻觉防护）；知识图谱和检索效果评测仍待建设。

## 后台管理

管理员登录后，从账户菜单进入“后台管理”（`/admin` → `/admin/overview`）。后台提供运行总览、用户管理、模型服务、处理任务、操作审计、系统状态六页，保留 `/admin/users` 和 `/admin/models` 原地址，支持桌面侧栏、窄屏导航与详情抽屉。

用户管理支持服务端搜索和组合筛选、账号详情、滚动问答额度调整、撤销他人全部会话，以及原有新增、改密、启停、软删除和角色变更。额度表示最近 60 分钟已占用名额（含处理中），不是历史问答量或账单；调整不会清空已有预留，不限额期间的请求不会追溯补记。

模型服务展示四用途生效来源与版本，显式连接测试与保存、切换默认分开。测试使用固定短样例，可能产生少量费用，15 分钟内且配置版本一致的结果才作为当前参考。任务页仅提供三阶段安全运行元数据；审计记录管理变更与追踪标识；系统状态标明检查时间和当前实例范围。管理员独占 `users:manage`、`models:manage`、`operations:read`、`audit:read`，管理权限不包含读取他人私有资料。

更新后先在 `backend` 执行 `uv run alembic upgrade head`，再按 [后端配置指南](backend/README.md#model-administration) 设置并独立备份 `MODEL_CONFIG_ENCRYPTION_KEY`。未选后台默认时沿用环境配置，选定后对新请求生效。已有向量索引或未完成任务时，系统会拒绝切换到不同的 Embedding 空间；不会自动重建索引。

模型诊断默认总超时 10 秒、每配置冷却 30 秒、全局并发 2，可通过 `ADMIN_MODEL_TEST_*` 配置；刷新总览或状态不调用外部模型。发布顺序为备份数据库与加密主密钥 → 增量迁移与兼容后端 → 新前端。前端可回退旧构建，保留新增表、审计和诊断历史；不会自动还原额度、账号或模型操作，业务库不执行有损降级。详见[验收与回退记录](openspec/changes/redesign-admin-console/evidence/verification.md)。

## 文档模型启动准备

后端启动时会执行文档模型 bootstrap，提前检查 PDF 解析所需的 Docling artifacts 和分块所需的 tokenizer。文件准备就绪后，应用会启动非阻塞后台预加载，把 Docling PDF pipeline 和 tokenizer 加载到进程内存里。现有 `GET /api/health` 会返回 `document_models` 摘要；不会新增独立的 `/api/health/document-models`。

模型内存预加载期间，`document_models.status` 或组件状态可能为 `loading`。这时 PDF 解析和分块/重分块会快速返回模型仍在加载或 `model_unavailable`，不会在用户请求路径里触发第一次长加载；纯文本解析不受 Docling 模型 loading 状态阻塞。

模型准备只读取新的 `DOCUMENT_MODEL_*` 变量，不复用、不扩展、也不 fallback 到既有 `DOCUMENT_PARSE_*` 或 `DOCUMENT_CHUNK_*`。常用配置包括：

- `DOCUMENT_MODEL_BOOTSTRAP_STRATEGY=download_missing`：启动时下载缺失模型；也可设为 `check_only` 只检查本地文件
- `DOCUMENT_MODEL_BOOTSTRAP_FAILURE_POLICY=degraded`：模型不可用时允许启动，但解析/分块会快速失败为 `model_unavailable`；生产环境可改为 `fail_fast`
- `DOCUMENT_MODEL_DOCLING_ARTIFACT_DIR=storage/document-models/docling`
- `DOCUMENT_MODEL_TOKENIZER_CACHE_DIR=storage/document-models/tokenizers`
- `DOCUMENT_MODEL_HF_ENDPOINT=`：可填写 Hugging Face 镜像地址，例如 `https://hf-mirror.com`
- `DOCUMENT_MODEL_SHUTDOWN_TIMEOUT_SECONDS=5.0`：收到 `Ctrl+C`、`SIGTERM` 或 lifespan teardown 时，模型预加载线程的优雅停止等待上限

最终交付 Docker 镜像时，建议在镜像构建阶段或容器单进程初始化阶段预热模型目录；首版不实现多进程同时下载同一模型目录的强文件锁。更多变量和离线预热命令见 `backend/README.md`。

应用优雅关闭时会把模型 readiness 标记为 `shutting_down`，清空进程内 Docling converter/tokenizer 引用，并把仍处于 `queued` 或 `running` 的解析/分块作业标记为 `failed`，错误码为 `process_shutdown`。这覆盖 `Ctrl+C`、`SIGTERM` 和 ASGI lifespan teardown；`SIGKILL`、宿主机崩溃或容器被强制杀死不属于进程内清理可保证范围。

## 文档分块能力

后端在解析作业成功保存 `parsed_documents` 后，会在同一个后台任务中把内存里的 Docling document 交给 Docling `HybridChunker` 自动分块。分块结果写入 `document_chunk_jobs` 和 `document_chunks`，长文本超过阈值时写入 `storage/chunks` 并在数据库中保存 storage key。

分块相关 API 挂载在 `/api` 前缀下：

- `GET /api/document-chunk-jobs/{job_id}`：读取分块作业状态、配置快照和错误信息
- `GET /api/parsed-documents/{parsed_document_id}/chunk-job`：读取某个解析结果的最新分块作业状态
- `GET /api/parsed-documents/{parsed_document_id}/chunks`：分页读取当前活跃分块结果
- `GET /api/document-chunks/{chunk_id}`：读取单个 chunk 详情
- `POST /api/parsed-documents/{parsed_document_id}/rechunk`：使用新参数重新读取原始上传文件、重新解析并重新分块

`/rechunk` 不会从旧 `docling.json` 或 pickle 还原 Docling document。新作业运行中或失败时，旧的成功分块结果仍保持为默认预览结果；只有新 chunk 集合成功持久化后，旧作业才会被标记为 `superseded`。

## 工程结构

```text
knowra/
├── backend/   # FastAPI + SQLModel 后端
├── front/     # Vue 3 + TypeScript + Vite 前端
├── docs/      # 项目设计与实施文档
└── docker-compose.yml
```

## 本地开发环境

- Python 3.14.5
- Node.js 24.15.0
- uv
- npm 11+
- Docker Compose v2 或兼容的容器编排工具

## 启动数据库

```bash
docker compose up -d postgres
```

如果当前 Docker CLI 没有 `docker compose` 子命令，请先安装 Docker Compose v2，或使用兼容工具启动 `docker-compose.yml` 中的 `postgres` 服务。

本地数据库默认连接串：

```text
postgresql+psycopg://knowra:knowra@localhost:5432/knowra
```

## 启动后端

```bash
cd backend
uv sync
cp .env.example .env
uv run alembic upgrade head
uv run uvicorn app.main:app --reload
```

后端默认运行在 `http://localhost:8000`，API 前缀为 `/api`。

从已有版本升级同样需要先执行 `uv run alembic upgrade head`。后台改版迁移
`20261022_0002` 仅新增审计、模型诊断历史结构及配置版本，不修改已有资料和向量；
实现与验收进度见[实施清单](openspec/changes/redesign-admin-console/tasks.md)。
原有账号与模型管理写操作已接入事务审计；审计不可写时返回
`admin_audit_unavailable` 并回滚业务操作，不保存密码、密钥或私有资料内容。
代码回退应保留新增历史表，迁移与回退说明见[后端 README](backend/README.md#database-migrations)。

## 启动前端

```bash
cd front
npm install
cp .env.example .env
npm run dev
```

前端默认运行在 `http://localhost:5173`，开发环境通过 Vite proxy 将 `/api` 转发到后端。

### 用户、角色与管理员初始化

首次访问会进入登录页，可通过注册创建普通成员。角色权限如下；管理员也只能检索自己的资料。

| 角色 | 读取与提问 | 上传与处理资料 | 后台账号、模型、运行与审计 |
|---|---|---|---|
| 管理员 `admin` | ✓ | ✓ | ✓ |
| 成员 `member` | ✓ | ✓ | — |
| 只读 `viewer` | ✓ | — | — |

完成数据库迁移后，在 `backend` 目录创建首位管理员。命令会隐藏输入密码并要求确认；密码须为 10–128 个字符且包含字母和数字。

```bash
uv run python -m app.cli create-admin --email admin@example.com --display-name 管理员
```

从旧版本升级时，若希望保留默认账号的历史资料和此浏览器的旧对话，首次创建管理员时使用 `--claim-legacy-user`。它认领原账号，不搬迁资料；不带此参数会创建独立的新账号。

```bash
uv run python -m app.cli create-admin --email admin@example.com --display-name 管理员 --claim-legacy-user
uv run python -m app.cli reset-password --email admin@example.com
```

注册不会自动授予管理员权限。侧栏账户菜单提供账户设置、退出和管理员用户管理入口；修改密码会退出所有设备。资料、检索与缓存均按用户隔离，对话保存在此浏览器各用户独立的存储键中。

可用 CLI 创建演示成员并限制最近 60 分钟最多成功问答 3 次：

```bash
uv run python -m app.cli create-user --email demo@deerfd.com --display-name 演示账号 --hourly-chat-limit 3
```

密码通过隐藏交互输入或受保护 stdin 提供。额度由数据库按账号统一控制，换设备、重新登录或新建对话不会重置；无资料、失败或生成降级不扣次数，超限返回 429 和等待秒数，未配置限额的账号不受影响。演示分享入口采用 `/login#demo=<base64url JSON>`，仅接受该演示邮箱，自动填表并清除地址片段，由访客点击登录。实际密码和分享链接不写入源码；格式与边界见 [前端 README](front/README.md#demo-interview-link)。

生产环境需要 HTTPS、`APP_ENV=production`、`AUTH_COOKIE_SECURE=true`，并将 `BACKEND_CORS_ORIGINS` 设为精确的前端来源（禁止 `*`）。详细接口、限流边界和迁移回滚步骤见 [后端 README](backend/README.md)。

### 主界面使用流程

1. **登录并上传资料**：登录后点击欢迎页的"上传资料"或输入框左下角的"资料"按钮，资料会上传到 `POST /api/uploads`。只读账号会显示不可上传的说明。侧边栏"资料库"显示已解析资料的数量（解析完成不代表已建好索引）。
2. **提问**：输入问题后按 Enter 发送，Shift+Enter 换行；输入法组字时按 Enter 不会发送。欢迎页的推荐问题只会填入输入框，确认后再发送。"检索 N 段"按钮用于调整每次检索的片段数（Top-K）。
3. **核对来源**：每个回答下方直接列出"来源"，按文档聚合，显示页码和分块编号；点开即可查看原文片段。查询改写、检索分数、提示词等诊断信息收在默认折叠的"检索详情"中。

`/verify` 是流程验证页，用于检查单个文档的解析、分块、向量化链路是否一致。

## 日志配置

后端和前端各自维护了一套结构化日志系统，通过 `X-Trace-ID` 请求头串联调用链。详见各子目录的 README。

后端日志配置项（`.env`）：

- `LOG_LEVEL`（默认 `INFO`）、`LOG_FORMAT`（`console` / `json`，默认自动）、`LOG_FILE_PATH`（默认 `logs/knowra.log`）、`LOG_FILE_MAX_SIZE`（默认 10 MB）、`LOG_FILE_BACKUP_COUNT`（默认 5）

前端日志配置项（`.env`）：

- `VITE_LOG_RING_SIZE`（默认 500）、`VITE_LOG_DISK_MAX_SIZE`（默认 5 MB）、`VITE_LOG_FLUSH_SIZE`（默认 100）、`VITE_LOG_CONSOLE_LEVEL`（默认 `debug`）、`VITE_LOG_BUFFER_LEVEL`（默认 `info`）

## 基础验证

后端：

```bash
cd backend
uv run ruff check .
uv run ruff format --check .
uv run pytest
```

前端：

```bash
cd front
npm run lint
npm run test
npm run build
```
