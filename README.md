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
上传文档 -> 解析文本 -> 建立索引 -> 用户提问 -> 检索相关内容 -> 生成带引用的回答
```

后续会逐步扩展语义检索、RAG 对话、知识图谱和效果评测等能力，但当前阶段的重点是先完成一个可用的最小闭环：**上传资料，然后基于资料提问并得到可信回答**。

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
