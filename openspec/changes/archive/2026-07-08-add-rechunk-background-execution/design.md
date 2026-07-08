# Design: 补全重新分块后台执行链路

## 问题分析

当前重新分块的两条代码路径存在断裂：

```
API 层 routes/document_chunking.py          Service 层 document_chunking.py
─────────────────────────────────────       ───────────────────────────────
rechunk_parsed_document()                   rechunk()
├── 校验 shutdown                           ├── 校验权限
├── 校验 tokenizer readiness                ├── 校验冲突
├── 校验 tokenizer scope                    ├── _parse_original_file()
├── 校验原始文件可用                          ├── _create_job()
├── create_queued_rechunk_job() → QUEUED    ├── _run_job() → SUCCEEDED/FAILED
└── return 202                              └── (无人调用)
     ↑                                              ↑
  实际执行路径                                  完整但被孤立
```

API 层和 Service 层的 `rechunk()` 各自实现了一套校验逻辑，但 API 层创建 job 后没有调度执行，Service 层的完整实现也没有任何调用方。

## 目标架构

参照 `run_parse_job` 的成熟模式（API 创建 QUEUED job → BackgroundTasks 调度 → 独立函数执行），重新分块应遵循相同范式：

```
POST /api/parsed-documents/{id}/rechunk
    │
    ├── 校验 shutdown / tokenizer / scope / 原始文件 / 冲突检测
    ├── create_queued_rechunk_job() → job (QUEUED)
    ├── RechunkDispatcher.enqueue(job.id)          ← 新增
    └── return 202 + job
            │
            ▼  [FastAPI BackgroundTasks]
    run_rechunk_job(job_id, session_factory, parser, ...)
            │
            ├── 加载 job + parsed_document + uploaded_file
            ├── 重新解析原始文件 → DoclingDocument
            │   └── 使用 DoclingParserAdapter（与 run_parse_job 一致）
            ├── make_document_chunking_service()
            └── service.execute_queued_job(job, parsed_document, document)
                    │
                    └── _run_job()
                        ├── QUEUED → RUNNING
                        ├── chunker.chunk(document) → chunks
                        ├── _save_chunk() × N
                        ├── _supersede_previous_jobs()
                        └── RUNNING → SUCCEEDED / FAILED
```

## 模块变更

### 1. `DocumentChunkingService` — 瘦身为执行引擎

```
变更前                              变更后
────────                            ────────
run_initial_chunking()   保留      run_initial_chunking()    保留（parse 路径）
rechunk()                移除      execute_queued_job()      新增（rechunk 路径）
_run_job()               保留      _run_job()                保留（核心引擎）
_create_job()            保留      _create_job()             保留
_save_chunk()            保留      _save_chunk()             保留
_parse_original_file()   移除      —                         移到 dispatcher
_ensure_tokenizer_ready() 保留     _ensure_tokenizer_ready()  保留
_ensure_not_shutting_down() 保留   _ensure_not_shutting_down() 保留
_supersede_previous_jobs() 保留    _supersede_previous_jobs()  保留
```

**`execute_queued_job()` 签名：**

```python
def execute_queued_job(
    self,
    *,
    job: DocumentChunkJob,           # API 层已创建的 QUEUED job
    parsed_document: ParsedDocument,
    transient_docling_document: object,
) -> DocumentChunkJob:
    return self._run_job(
        job=job,
        parsed_document=parsed_document,
        transient_docling_document=transient_docling_document,
        supersede_previous=True,      # rechunk 总是 supersede
    )
```

### 2. 新增 `run_rechunk_job` — 后台执行函数

文件位置：`backend/app/services/document_chunking.py`（与 `mark_incomplete_chunk_jobs_failed_for_shutdown` 同文件）

```python
def run_rechunk_job(
    job_id,
    *,
    session_factory: SessionFactory | None = None,
    parser: object | None = None,
    upload_storage_root: str | Path | None = None,
    model_readiness: object | None = None,
    shutdown_state: object | None = None,
) -> None:
```

核心流程：
1. 获取 settings，打开 session
2. 加载 job → 校验 status == QUEUED（幂等保护）
3. 加载 parsed_document → uploaded_file
4. 检查 shutdown
5. 构建 parser（支持注入，默认 `DoclingParserAdapter`）
6. 调用 `active_parser.parse(source_path)` → 提取 `transient_docling_document`
7. 构建 `DocumentChunkingService` + `execute_queued_job()`
8. 异常处理：捕获各类错误，标记 job FAILED

### 3. 新增 `RechunkDispatcher` — 调度器

文件位置：`backend/app/services/document_chunking.py`

```python
class RechunkDispatcher:
    def __init__(self, background_tasks: BackgroundTasks) -> None:
        self.background_tasks = background_tasks

    def enqueue(self, job_id) -> None:
        self.background_tasks.add_task(run_rechunk_job, job_id)
```

结构复制 `BackgroundTasksParseJobDispatcher`，保持一致性。

### 4. API 端点变更

`rechunk_parsed_document()` 在 `create_queued_rechunk_job()` 之后增加：

```python
from fastapi import BackgroundTasks

def rechunk_parsed_document(
    ...,
    background_tasks: BackgroundTasks,   # 新增参数
    ...
):
    # ... 现有校验保持不变 ...
    
    job = create_queued_rechunk_job(...)
    
    # 新增：调度后台执行
    RechunkDispatcher(background_tasks).enqueue(job.id)
    
    return DocumentChunkJobRead.model_validate(job, from_attributes=True)
```

### 5. 移除死代码

| 移除项 | 位置 | 原因 |
|--------|------|------|
| `DocumentChunkingService.rechunk()` | `document_chunking.py` | 无调用方，校验逻辑与 API 层重复 |
| `DocumentChunkingService._parse_original_file()` | `document_chunking.py` | 移到 dispatcher，且包含 dead path |
| `DeferredOriginalFileDocument` | `document_chunking.py` | 仅被 `_parse_original_file()` 的 dead path 引用 |
| `DocumentChunkOriginalFileUnavailableError` | `document_chunking.py` | 仅被 `rechunk()` 引用 |
| `MissingDoclingDocumentError` 和 `DocumentModelUnavailableError` | `document_chunking.py` | 仅被 `rechunk()` 引用 |

### 6. 前向兼容

- `run_initial_chunking()` 保持不变——parse 路径不受影响
- `_run_job()` 保持不变——核心分块逻辑不受影响
- API 响应结构不变——前端零改动
- `mark_incomplete_chunk_jobs_failed_for_shutdown()` 保持不变——关闭收尾覆盖所有 QUEUED/RUNNING job（无论来自 parse 还是 rechunk）

## 数据流

```
                    ┌──────────┐
                    │  用户点击  │
                    │「重新分块」│
                    └─────┬────┘
                          │
                    ┌─────▼──────────────────────────┐
                    │  POST /rechunk                  │
                    │  ├─ 校验 (shutdown, tokenizer,  │
                    │  │    scope, file, conflict)     │
                    │  ├─ create QUEUED job           │
                    │  ├─ enqueue BackgroundTasks      │
                    │  └─ return 202 + job             │
                    └─────┬──────────────────────────┘
                          │
          ┌───────────────┼───────────────┐
          │               │               │
          ▼               ▼               ▼
    ┌──────────┐   ┌──────────┐   ┌──────────┐
    │ 前端轮询  │   │ 后台线程  │   │ 关闭检测  │
    │ 每1s GET │   │ run_rech │   │ 标记      │
    │ job 状态  │   │ unk_job  │   │ FAILED    │
    └────┬─────┘   └────┬─────┘   └──────────┘
         │              │
         │    ┌─────────▼────────────────────┐
         │    │  run_rechunk_job()            │
         │    │  ├─ 加载 job (QUEUED → RUN)   │
         │    │  ├─ 重新解析原始文件            │
         │    │  ├─ chunker.chunk(document)    │
         │    │  ├─ _save_chunk() × N          │
         │    │  ├─ _supersede_previous_jobs() │
         │    │  └─ job → SUCCEEDED / FAILED   │
         │    └────────────────────────────────┘
         │              │
         ▼              ▼
    ┌──────────────────────────┐
    │  GET /chunks              │
    │  ← 新 chunks（或旧 chunks │
    │     如果新 job 失败）     │
    └──────────────────────────┘
```

## 生命周期与 Graceful Shutdown

遵循与 `run_parse_job` 一致的 shutdown 语义：

- **API 层**：shutdown 期间拒绝创建新的 rechunk job（已有实现，不变）
- **执行前**：`_ensure_not_shutting_down()` 快速失败（已有实现，不变）
- **chunk 生成后、写入成功前**：`_ensure_not_shutting_down()` 再次检查（已有实现，不变）
- **收尾**：`mark_incomplete_chunk_jobs_failed_for_shutdown()` 覆盖所有 QUEUED/RUNNING（已有实现，不变）
- **不可捕获边界**（SIGKILL 等）：残留 QUEUED/RUNNING job 在下次启动时不会自动恢复——这是与现有 parse job 一致的行为；如有需要应在独立变更中引入启动自愈机制

## 测试策略

| 层级 | 测试内容 | 文件 |
|------|---------|------|
| 单元测试 | `execute_queued_job()` 对 QUEUED job 执行分块 | `test_document_chunking_service.py` |
| 单元测试 | `run_rechunk_job` 加载 QUEUED job 并执行 | 新增或扩展 |
| 集成测试 | API → dispatcher → job 状态流转 | `test_document_chunking.py` |
| 边界测试 | job 已非 QUEUED 时的幂等保护 | 新增 |
| 边界测试 | 原始文件缺失时 FAILED | 新增 |
| 回归测试 | `run_initial_chunking` 行为不变 | 现有测试保持 |
| 回归测试 | shutdown 收尾覆盖 rechunk job | 现有测试保持 |

## 验证命令

```bash
# 后端
cd backend
uv run ruff check .
uv run ruff format --check .
uv run pytest

# 前端（确认无回归）
cd front
npm run lint
npm run test
npm run build
```
