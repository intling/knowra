# 前后端框架初始化方案

**日期**：2026-05-14  
**阶段**：架构搭建第一步  
**范围**：只搭建前后端基础框架、开发工具链和最小联通能力，不实现文档上传、检索、RAG 问答等业务功能。

## 1. 目标

本阶段目标是把空的 `front` 和 `backend` 目录初始化为可运行、可维护、便于后续扩展的前后端分离项目。

完成后应具备：

- 后端：FastAPI 应用可启动，提供健康检查接口，具备配置管理、数据库连接、SQLModel 模型与迁移基础。
- 前端：Vue 3 + TypeScript + Vite 应用可启动，具备路由、状态管理、Tailwind CSS、基础 API 调用封装。
- 联调：前端可通过开发代理访问后端接口，后端 CORS 配置清晰。
- 工程化：具备格式化、静态检查、测试入口、环境变量模板和本地开发说明。

## 2. 技术栈基线

### 后端

- Python 3.14.5
- FastAPI
- uvicorn：开发环境 ASGI 服务
- gunicorn：生产环境进程管理
- PostgreSQL + pgvector
- SQLModel
- Alembic：数据库迁移
- Pydantic Settings：环境配置
- pytest：测试运行器、断言、fixture 和测试组织
- FastAPI TestClient：API 接口测试客户端
- ruff：格式化与静态检查

### 前端

- Node.js 24.15.0 LTS
- Vue 3
- TypeScript
- Vite 8.0.12
- Tailwind CSS
- Pinia
- Vue Router
- Vitest：单元测试
- ESLint + Prettier：静态检查与格式化

## 3. 推荐目录结构

```text
knowra/
├── backend/
│   ├── app/
│   │   ├── api/
│   │   │   ├── routes/
│   │   │   │   └── health.py
│   │   │   └── router.py
│   │   ├── core/
│   │   │   ├── config.py
│   │   │   └── logging.py
│   │   ├── db/
│   │   │   ├── session.py
│   │   │   └── init_db.py
│   │   ├── models/
│   │   │   └── base.py
│   │   ├── schemas/
│   │   ├── services/
│   │   └── main.py
│   ├── alembic/
│   ├── tests/
│   │   ├── conftest.py
│   │   └── api/
│   │       └── test_health.py
│   ├── alembic.ini
│   ├── pyproject.toml
│   ├── .env.example
│   └── README.md
├── front/
│   ├── src/
│   │   ├── api/
│   │   │   ├── client.ts
│   │   │   └── health.ts
│   │   ├── assets/
│   │   ├── components/
│   │   ├── layouts/
│   │   ├── router/
│   │   │   └── index.ts
│   │   ├── stores/
│   │   │   └── app.ts
│   │   ├── views/
│   │   │   └── HomeView.vue
│   │   ├── App.vue
│   │   ├── main.ts
│   │   └── style.css
│   ├── public/
│   ├── index.html
│   ├── package.json
│   ├── vite.config.ts
│   ├── tsconfig.json
│   ├── .env.example
│   └── README.md
├── docs/
│   └── framework-initialization-plan.md
└── README.md
```

## 4. 后端初始化方案

### 4.1 项目创建

后端建议使用 `uv` 或项目当前约定的 Python 包管理工具创建虚拟环境和依赖管理。如果没有既定工具，建议用 `uv`，因为它适合锁定依赖、同步环境和执行命令。

推荐命令：

```bash
cd backend
uv init --package
uv python pin 3.14.5
uv add fastapi uvicorn gunicorn sqlmodel psycopg[binary] pgvector alembic pydantic-settings python-dotenv
uv add --dev pytest pytest-asyncio httpx ruff
```

如果本机暂时没有 Python 3.14.5，可先记录在 `.python-version` 和文档中，实际开发环境安装完成后再执行依赖同步。

### 4.2 应用入口

`backend/app/main.py` 负责创建 FastAPI 实例、挂载路由、配置 CORS 和应用生命周期。

建议最小能力：

- `GET /api/health`：返回服务状态、应用名、环境。
- OpenAPI 路径保留默认 `/docs`，开发阶段便于调试。
- API 统一挂载到 `/api` 前缀。

### 4.3 配置管理

`backend/app/core/config.py` 使用 Pydantic Settings 读取环境变量。

基础配置项：

- `APP_NAME=knowra`
- `APP_ENV=local`
- `DEBUG=true`
- `API_PREFIX=/api`
- `BACKEND_CORS_ORIGINS=http://localhost:5173`
- `DATABASE_URL=postgresql+psycopg://knowra:knowra@localhost:5432/knowra`

环境变量模板放在 `backend/.env.example`，实际 `.env` 不提交。

### 4.4 数据库基础

PostgreSQL 与 pgvector 是后续语义检索的基础，本阶段只做连接和迁移骨架。

建议内容：

- `backend/app/db/session.py`：创建 SQLModel engine 和 session 依赖。
- `backend/app/models/base.py`：集中导入模型，供 Alembic 自动发现元数据。
- `backend/alembic/`：初始化迁移目录。
- 首个迁移可只启用 `vector` 扩展，不创建业务表。

首个迁移目标：

```sql
CREATE EXTENSION IF NOT EXISTS vector;
```

### 4.5 后端质量门禁

后端测试采用 `pytest + FastAPI TestClient` 组合，而不是二选一：

- `pytest` 作为统一测试框架，负责测试发现、断言、fixture、参数化和插件生态。
- `FastAPI TestClient` 作为 API 测试客户端，负责在测试中模拟 HTTP 请求并验证 FastAPI 路由行为。
- 纯函数、服务层、配置读取等不经过 HTTP 的测试只使用 `pytest`。
- 路由、请求参数、状态码、响应 JSON 等接口行为使用 `pytest + TestClient`。
- 后续如果出现复杂异步数据库或异步外部请求测试，再引入 `pytest-asyncio + httpx.AsyncClient`。

建议在 `backend/tests/conftest.py` 中提供共享客户端 fixture：

```python
import pytest
from fastapi.testclient import TestClient

from app.main import app


@pytest.fixture
def client():
    return TestClient(app)
```

健康检查接口测试示例：

```python
def test_health_check(client):
    response = client.get("/api/health")

    assert response.status_code == 200
    assert response.json()["status"] == "ok"
```

建议在 `pyproject.toml` 中配置：

- ruff lint
- ruff format
- pytest
- Python 版本约束
- 测试路径

推荐脚本或 Make 目标：

```bash
uv run ruff check .
uv run ruff format .
uv run pytest
uv run uvicorn app.main:app --reload
```

## 5. 前端初始化方案

### 5.1 项目创建

在 `front` 目录初始化 Vite + Vue + TypeScript 项目。

推荐命令：

```bash
cd front
npm create vite@latest . -- --template vue-ts
npm install
npm install pinia vue-router
npm install -D tailwindcss @tailwindcss/vite eslint prettier vitest jsdom @vue/test-utils
```

如 Vite 8 或 Tailwind 当前版本的命令与插件方式有变化，实施时以官方包生成结果为准，但需要保持 `vite.config.ts` 中的插件和项目结构清晰可审查。

### 5.2 应用入口

`front/src/main.ts` 负责创建 Vue 应用并挂载：

- Pinia
- Vue Router
- 全局样式 `style.css`

`front/src/App.vue` 只保留应用壳层，不承载业务逻辑。

### 5.3 路由

`front/src/router/index.ts` 提供基础路由：

- `/`：首页，占位展示系统名称和后端健康状态。
- 后续业务路由按模块拆分，例如 `/documents`、`/chat`、`/settings`，本阶段不实现。

### 5.4 状态管理

`front/src/stores/app.ts` 只放应用级状态：

- 应用名称
- 后端健康状态
- 基础加载状态

避免在初始化阶段提前设计复杂业务 store。

### 5.5 API 调用封装

`front/src/api/client.ts` 封装基础请求能力。

基础约定：

- `VITE_API_BASE_URL=/api`
- 开发环境通过 Vite proxy 转发到后端。
- 请求错误统一抛出可读错误，页面层负责展示。

`front/src/api/health.ts` 调用 `GET /api/health`，用于验证前后端联通。

### 5.6 Tailwind CSS

`front/src/style.css` 引入 Tailwind。

本阶段只建立设计基础，不提前建立复杂组件库：

- 全局字体和基础背景色。
- 简洁的应用壳布局。
- 首页展示服务状态即可。

### 5.7 前端质量门禁

建议 `package.json` 脚本：

```json
{
  "scripts": {
    "dev": "vite",
    "build": "vue-tsc -b && vite build",
    "preview": "vite preview",
    "lint": "eslint .",
    "format": "prettier --write .",
    "test": "vitest run"
  }
}
```

## 6. 本地开发联调

### 6.1 端口约定

- 后端：`http://localhost:8000`
- 前端：`http://localhost:5173`
- API 前缀：`/api`

### 6.2 Vite 代理

`front/vite.config.ts` 建议配置：

```ts
server: {
  proxy: {
    '/api': {
      target: 'http://localhost:8000',
      changeOrigin: true
    }
  }
}
```

### 6.3 CORS

后端允许前端开发地址：

```text
http://localhost:5173
```

生产环境根据实际域名通过环境变量覆盖，不写死在代码里。

## 7. Docker 与数据库建议

本阶段建议增加数据库开发编排，但不强制把前后端都容器化。

推荐在仓库根目录后续增加 `docker-compose.yml`：

```yaml
services:
  postgres:
    image: pgvector/pgvector:pg17
    environment:
      POSTGRES_DB: knowra
      POSTGRES_USER: knowra
      POSTGRES_PASSWORD: knowra
    ports:
      - "5432:5432"
    volumes:
      - postgres_data:/var/lib/postgresql/data

volumes:
  postgres_data:
```

说明：

- PostgreSQL 版本可在正式实施前结合 Python 驱动、部署环境再定。
- pgvector 镜像用于本地开发可减少扩展安装成本。
- 生产数据库部署方案后续单独设计。

## 8. 环境变量模板

### 后端 `backend/.env.example`

```env
APP_NAME=knowra
APP_ENV=local
DEBUG=true
API_PREFIX=/api
BACKEND_CORS_ORIGINS=http://localhost:5173
DATABASE_URL=postgresql+psycopg://knowra:knowra@localhost:5432/knowra
```

### 前端 `front/.env.example`

```env
VITE_API_BASE_URL=/api
```

## 9. 初始化执行顺序

1. 确认本机 Node.js 24.15.0 LTS 与 Python 3.14.5 可用。
2. 初始化后端包管理、依赖、FastAPI 应用入口。
3. 增加后端配置、健康检查路由、测试和 ruff 配置。
4. 初始化 Alembic 和数据库连接骨架。
5. 初始化前端 Vite + Vue + TypeScript。
6. 增加 Pinia、Vue Router、Tailwind CSS。
7. 增加前端 API client 和健康检查页面。
8. 配置 Vite proxy 与后端 CORS。
9. 补充前后端 README、`.env.example`、基础脚本。
10. 分别运行后端测试、前端测试、前端构建和本地联调验证。

## 10. 验收标准

### 后端

- `uv run uvicorn app.main:app --reload` 可以启动服务。
- `GET http://localhost:8000/api/health` 返回 200。
- `uv run pytest` 通过。
- `uv run ruff check .` 通过。
- Alembic 能连接数据库并执行首个迁移。

### 前端

- `npm run dev` 可以启动开发服务。
- 首页可以渲染，并能展示后端健康检查结果。
- `npm run build` 通过。
- `npm run test` 通过。
- `npm run lint` 通过。

### 联调

- 前端通过 `/api/health` 访问后端，不在业务代码中写死 `localhost:8000`。
- 后端 CORS 允许本地前端开发地址。
- `.env.example` 能说明启动所需的最小环境变量。

## 11. 暂不纳入本阶段的内容

以下内容属于后续业务或架构阶段，本次不实现：

- 用户认证与权限。
- 文档上传、存储、解析。
- Embedding 生成与向量索引。
- RAG 问答链路。
- 引用溯源展示。
- 生产部署流水线。
- 完整 UI 设计系统。
- 多环境配置中心。

## 12. 风险与注意事项

- Python 3.14.5 与 Node.js 24.15.0 LTS 的生态兼容性需要在实际初始化时验证，尤其是依赖是否已发布兼容版本。
- Vite 8.0.12 与 Tailwind CSS 的插件配置应以实施时实际包版本为准。
- PostgreSQL + pgvector 的镜像版本需要与生产目标版本尽量接近，避免迁移行为差异。
- 初始化阶段应避免提前建立过度复杂的领域模型，优先保证工程骨架清晰、可测试、可扩展。

## 13. 下一步

确认本方案后，可以进入实际框架搭建：

- 创建后端 FastAPI 工程骨架。
- 创建前端 Vue 工程骨架。
- 增加最小健康检查联调。
- 运行全部基础验证命令。
