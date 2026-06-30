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

后续会逐步扩展语义检索、RAG 对话、知识图谱和效果评测等能力。当前实现已经支持资料上传、Docling 解析、解析后自动分块、chunk 预览和重新分块入口；首版分块只生成可追溯的知识单元，不代表已经完成 embedding、pgvector 索引、语义检索、RAG 问答或引用生成。

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

## 启动前端

```bash
cd front
npm install
cp .env.example .env
npm run dev
```

前端默认运行在 `http://localhost:5173`，开发环境通过 Vite proxy 将 `/api` 转发到后端。

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
