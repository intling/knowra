## Context

knowra 目前已实现文档解析（Docling）和文档分块（Docling HybridChunker），能将用户上传的资料转化为结构化的文本块（`document_chunks`）。分块结果包含 `contextualized_text`（带层级标题上下文的富文本），支持 ≤2KB 直接入库、>2KB 走文件存储的混合策略。

当前项目已启用 pgvector 扩展（`CREATE EXTENSION vector`），Docker Compose 使用 `pgvector/pgvector:pg17` 镜像。但分块结果尚未被转化为语义向量——无法被语义检索消费，这是实现 RAG 知识库问答的关键缺失环节。

本设计在分块完成之后，新增云端 Embedding 模型调用与 pgvector 向量存储能力，采用 OpenAI 兼容 API 协议，首版对接阿里云 DashScope text-embedding-v3（1024 维），通过配置即可切换至其他兼容服务。

## Goals / Non-Goals

**Goals:**
- 分块成功后自动在同一后台任务中调用云端 Embedding API 生成语义向量
- 向量持久化到 pgvector `vector(1024)` 列，关联 chunk 和作业
- 支持通过配置切换 OpenAI 兼容的 Embedding 服务（千问/OpenAI/豆包等）
- 提供独立的 `/reembed` API 支持更换模型参数重新向量化
- 重新分块（`/rechunk`）成功后自动触发重新向量化
- 向量化作业沿用现有的 `superseded` 机制，与分块作业联动
- 向量化失败不影响分块结果的可用性

**Non-Goals:**
- 语义检索、RAG 问答、混合检索（后续能力）
- pgvector 高级索引（HNSW/IVFFlat）——检索阶段再加
- 多模型向量并存（同一时间只维护一套活跃向量）
- 向量化进度实时推送（WebSocket）
- 独立 worker + 队列（首版沿用 BackgroundTasks）
- 本地 Ollama/sentence-transformers 部署（本次只做云端）
- `text_type="query"` 侧的适配（检索 API 阶段再做）
- 稀疏向量（`output_type=sparse`）和 `instruct` 指令优化
- 旧向量清理 API
- 前端向量化状态展示（后续前端变更单独处理）

## Decisions

### 1. 维度固定为 1024

**决策：** pgvector 列类型写死 `vector(1024)`，与 text-embedding-v3 默认维度对齐。

**理由：**
- pgvector 的 `vector(N)` 类型 N 在建表时确定，同一列不能混存不同维度
- 1024 是 text-embedding-v3 的默认维度，也是业界主流选择（BGE-M3、OpenAI text-embedding-3-large 等均支持 1024）
- 如果后续换模型需要不同维度，通过新 migration 修改列类型（`ALTER COLUMN ... TYPE vector(新维度)`），配合 `/reembed` 全量重建

**替代方案：**
- 使用无维度约束的 `vector` 类型 → pgvector 仍会检查同列维度一致性，不解决问题
- 按维度分表（如 `document_chunk_embeddings_1024`）→ 过度设计，首版不需要

### 2. OpenAI 兼容协议适配器

**决策：** 实现 `OpenAIEmbeddingAdapter`，封装 OpenAI 兼容的 `/v1/embeddings` API，通过 `base_url` + `api_key` + `model` 配置切换服务商。

**API 契约：**
```
POST {base_url}/v1/embeddings
Authorization: Bearer {api_key}
Content-Type: application/json

{
  "model": "text-embedding-v3",
  "input": ["text1", "text2", ...],
  "dimensions": 1024
}

→ {
  "data": [
    {"embedding": [0.1, 0.2, ...], "index": 0},
    ...
  ]
}
```

**适配器接口：**
```python
class OpenAIEmbeddingAdapter:
    def __init__(
        self,
        base_url: str,
        api_key: str,
        model: str,
        dimensions: int,
        timeout: float = 60.0,
        max_retries: int = 3,
        extra_body: dict | None = None,  # 透传 provider 特有参数
    ): ...

    def embed(self, texts: list[str]) -> list[list[float]]:
        """按 batch_size 分片，循环发送，返回等长向量列表。"""
        ...

    @property
    def dimension(self) -> int: ...
    @property
    def model_name(self) -> str: ...
```

**理由：**
- 国内主流厂商（阿里 DashScope、硅基流动、DeepSeek 等）均兼容 OpenAI `/v1/embeddings` 协议
- 一次请求支持数组输入（`input: [...]`），天然批量，比 Ollama 单条请求高效得多
- `extra_body` 透传机制兼容 DashScope 的 `text_type` 等特有参数
- 适配器是项目中唯一接触 Embedding API 的地方，服务层和路由层不感知第三方协议细节

**替代方案：**
- 每个厂商写独立 Adapter → 过度设计，OpenAI 兼容协议已覆盖主流需求
- 使用 langchain/openai 等第三方 SDK → 引入不必要的依赖，增加了项目复杂度

### 3. Batch 分片策略

**决策：** Adapter 内部按 `batch_size`（默认 10）分片，循环发送 HTTP 请求。

**理由：**
- DashScope text-embedding-v3 单次最多 10 条输入
- 不同厂商的 batch 限制不同，通过配置项 `DOCUMENT_EMBEDDING_BATCH_SIZE` 灵活调整
- 个人知识库单文档通常 < 100 chunks，按 10 条/批最多 10 次 HTTP 请求，可接受

**替代方案：**
- 并发请求 → 首版顺序请求已足够，避免引入 asyncio/aiohttp 复杂度
- 不限制 batch 全量发送 → 超出厂商限制会直接报错

### 4. 数据模型设计

**决策：** 新增 `document_embedding_jobs` 和 `document_chunk_embeddings` 两张独立表，不修改 `document_chunks` 表。

**表结构：**

`document_embedding_jobs`：
| 字段 | 类型 | 说明 |
|------|------|------|
| id | UUID PK | 主键 |
| chunk_job_id | UUID FK → document_chunk_jobs.id | 关联分块作业 |
| parsed_document_id | UUID FK → parsed_documents.id | 冗余关联解析结果 |
| owner_user_id | UUID FK → users.id | 权限归属 |
| status | String(32) | queued/running/succeeded/failed/superseded |
| embedder_name | String(64) | 模型名，如 text-embedding-v3 |
| embedder_version | String(64) nullable | 模型版本 |
| embedding_dim | Integer | 向量维度，固定 1024 |
| embed_config_json | JSON nullable | 配置快照（base_url, model, dimensions, batch_size） |
| chunk_count | Integer | 成功写入的向量数 |
| attempt_count | Integer | 重试次数 |
| started_at | DateTime(tz) nullable | 开始时间 |
| finished_at | DateTime(tz) nullable | 完成时间 |
| error_code | String(64) nullable | 错误码 |
| error_message | String(2048) nullable | 错误详情 |
| created_at | DateTime(tz) | 创建时间 |
| updated_at | DateTime(tz) | 更新时间 |

`document_chunk_embeddings`：
| 字段 | 类型 | 说明 |
|------|------|------|
| id | UUID PK | 主键 |
| chunk_id | UUID FK → document_chunks.id | 关联被向量化的 chunk |
| embedding_job_id | UUID FK → document_embedding_jobs.id | 关联向量化作业 |
| owner_user_id | UUID FK → users.id | 权限归属 |
| embedding | pgvector vector(1024) | 向量数据（使用原始 SQL 创建） |
| sequence_index | Integer | 冗余 chunk 序号 |
| created_at | DateTime(tz) | 创建时间 |

**理由（独立表）：**
- 一个 chunk 可以有多个 embedding（不同 embedding_job），独立表比在 chunk 上加列更灵活
- supersede 机制要求旧向量保留但不活跃，独立表更容易隔离
- chunk 和 embedding 生命周期不同：chunk 随分块变更，embedding 可独立更新（`/reembed`）
- 不修改 `document_chunks` 表，与分块模块解耦

### 5. 集成到现有流水线

**决策：** 在 `run_parse_job()` 和 `run_rechunk_job()` 中，分块成功后插入向量化步骤。

**集成点 1：`run_parse_job()`（document_parse_dispatcher.py）**
```python
# 现有：分块成功后（第 130-147 行）
if should_chunk:
    chunk_job = service.run_initial_chunking(...)
    # ★ 新增：分块成功后自动向量化
    if should_embed and chunk_job.status == "succeeded":
        embedding_service.run_initial_embedding(
            chunk_job=chunk_job,
            parsed_document=parsed_document,
        )
```

**集成点 2：`run_rechunk_job()`（document_chunking.py）**
```python
# 现有：execute_queued_job 成功后
service.execute_queued_job(...)
# ★ 新增：重分块成功后自动向量化
if should_embed:
    embedding_service.run_initial_embedding(
        chunk_job=job,
        parsed_document=parsed_document,
    )
```

**理由：**
- 向量化在分块成功的同一后台任务中执行，chunk 文本从已持久化的 `document_chunks` 记录读取
- 沿用现有 `BackgroundTasks` 调度范式，不引入新调度器
- 向量化失败用 `suppress(Exception)` 包裹，不影响解析和分块结果的可用性

### 6. Chunk 文本读取策略

**决策：** `DocumentEmbeddingService` 从 `document_chunks` 表读取 `contextualized_text`，自动处理 DB 内联和文件存储两种情况。

```python
def _read_contextualized_text(chunk: DocumentChunk, storage: ChunkArtifactStorage) -> str:
    if chunk.contextualized_text is not None:
        return chunk.contextualized_text  # ≤2KB，DB 内联
    if chunk.contextualized_text_storage_key is not None:
        path = storage.path_for(chunk.contextualized_text_storage_key)
        return path.read_text(encoding="utf-8")  # >2KB，文件读取
    # fallback: 原始 text
    if chunk.text is not None:
        return chunk.text
    if chunk.text_storage_key is not None:
        path = storage.path_for(chunk.text_storage_key)
        return path.read_text(encoding="utf-8")
    raise MissingChunkTextError(f"Chunk {chunk.id} 无可读文本")
```

**理由：**
- 分块文本可能 >2KB 走文件存储，不能假设内存中总有全文
- 优先使用 `contextualized_text`（带标题上下文），这是向量化最有价值的输入

### 7. 配置项设计

**决策：** 新增以下配置项，全部通过环境变量注入：

| 配置项 | 默认值 | 说明 |
|--------|--------|------|
| `DOCUMENT_EMBEDDING_ENABLED` | `true` | 向量化总开关 |
| `DOCUMENT_EMBEDDING_BASE_URL` | `https://dashscope.aliyuncs.com/compatible-mode/v1` | OpenAI 兼容 API 地址 |
| `DOCUMENT_EMBEDDING_API_KEY` | `""` | API Key |
| `DOCUMENT_EMBEDDING_MODEL` | `text-embedding-v3` | 模型名称 |
| `DOCUMENT_EMBEDDING_DIM` | `1024` | 向量维度 |
| `DOCUMENT_EMBEDDING_BATCH_SIZE` | `10` | 单次请求发送的文本数 |
| `DOCUMENT_EMBEDDING_TIMEOUT` | `60.0` | 请求超时秒数 |
| `DOCUMENT_EMBEDDING_MAX_RETRIES` | `3` | 最大重试次数 |
| `DOCUMENT_EMBEDDING_EXTRA_BODY` | `{"text_type":"document"}` | 透传给 API body 的额外参数 |

### 8. 错误处理策略

| 错误场景 | 处理方式 |
|----------|----------|
| API Key 无效 (401) | 不重试，标记 failed，`error_code=unauthorized` |
| 模型不存在 (404) | 不重试，标记 failed，`error_code=model_not_found` |
| 服务不可达 (ConnectionError) | 重试 3 次（指数退避），仍失败标记 failed，`error_code=service_unreachable` |
| 请求超时 | 重试 1 次，仍失败标记 failed，`error_code=request_timeout` |
| 向量维度不匹配 | 适配器初始化时探测维度，与配置比对，不匹配则阻止写入 |
| 单次 batch 请求部分失败 | 整体标记 failed（原子性：全部成功或全部失败） |
| 进程 shutdown | 作业标记 failed，`error_code=process_shutdown` |

### 9. 生命周期与关闭语义

- 向量化在 `run_parse_job` / `run_rechunk_job` 内同步执行，不持有独立后台线程
- 在每次 batch API 调用前检查 `shutdown_state.is_shutting_down`，发现关闭时快速失败
- 关闭时 `queued`/`running` 的向量化作业标记为 `failed`，`error_code=process_shutdown`
- 适配器本身无状态，不持有需要释放的资源

## Risks / Trade-offs

- **[API 依赖风险]** 向量化依赖外部云服务可用性。→ 缓解：向量化失败不影响分块结果可用性；通过 `DOCUMENT_EMBEDDING_ENABLED=false` 可全局禁用；重试 + 明确错误信息帮助诊断。
- **[网络延迟]** 云端 API 调用增加端到端延迟。→ 缓解：个人知识库文档 chunk 数少，按 10 条/批、每批 ~200ms 计算，100 chunks 约 2 秒，可接受。
- **[维度锁定]** 建表写死 1024 维，换模型维度需 migration。→ 缓解：1024 是主流选择，切换模型通常需要全量重建向量（本身就需 migration + `/reembed`）。
- **[API Key 安全]** Key 存储在 `.env` 文件中。→ 缓解：与现有 `DATABASE_URL` 密码同级安全，后续统一升级 secret 管理。
- **[BackgroundTasks 可靠性]** 与解析和分块作业相同的限制。→ 缓解：向量化作业状态持久化，失败可诊断和重试；后续与解析/分块一起迁移到独立 worker。
- **[Batch 大小限制]** DashScope 单次最多 10 条。→ 缓解：Adapter 内部自动分片，通过配置项适配不同厂商的 batch 限制。