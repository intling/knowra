# Proposal: 补全重新分块后台执行链路

## 动机

当前 `POST /api/parsed-documents/{id}/rechunk` 端点只创建了 QUEUED 状态的分块作业并返回 202，但**没有任何后台任务执行该作业**，导致重新分块作业永远停留在 QUEUED 状态。

这个问题有明确的产品副作用：
- 用户在知识库上传资料 → 解析完成 → 调整分块参数点击「重新分块」→ UI 进入轮询 → 作业永远不结束
- 前端已经实现了完整的异步轮询交互（`pollChunkJobUntilSettled`），但后端没有驱动作业状态流转

对比解析流程的完整链路（`POST /parse` → `BackgroundTasksParseJobDispatcher` → `run_parse_job`），重新分块缺失了 dispatcher + 后台执行函数这一整段。

## 范围

### 范围内

1. **新增 `run_rechunk_job` 后台执行函数**：从 DB 加载 QUEUED job，重新解析原始文件获得内存 `DoclingDocument`，调用分块适配器执行分块，保存结果并标记 job SUCCEEDED/FAILED
2. **新增 Rechunk 调度器**：在 API 端点创建 QUEUED job 后，通过 FastAPI `BackgroundTasks` 调度 `run_rechunk_job`
3. **重构 `DocumentChunkingService`**：新增 `execute_queued_job()` 方法，接收已创建的 QUEUED job 执行分块；废弃无人调用的 `rechunk()` 方法和 `DeferredOriginalFileDocument` 死路径
4. **re-parsing 逻辑调入 dispatcher**：重新解析原始文件的逻辑从 Service 移入 `run_rechunk_job`，复用 `DoclingParserAdapter`，遵循与 `run_parse_job` 一致的 parser 构造模式

### 范围外

- 不新增 API 端点，不修改现有 API 契约（请求/响应结构不变）
- 不修改前端代码（前端轮询交互已就绪）
- 不修改数据库 schema（不需要新的 migration）
- 不修改分块算法或 tokenizer 行为
- 不新增 embedding、向量索引或检索能力

## 受影响方

| 方 | 影响 |
|----|------|
| 后端 API 层 | `rechunk_parsed_document` 端点新增 dispatcher 调用 |
| 后端 Service 层 | `DocumentChunkingService` 新增 `execute_queued_job()`，移除 `rechunk()` 和 `_parse_original_file()` |
| 后端 Dispatcher | 新增 `run_rechunk_job` 和 `RechunkDispatcher` 类 |
| 前端 | 零改动——现有轮询逻辑直接生效 |
| 数据库 | 无 schema 变更 |

## 验收信号

1. `POST /rechunk` 返回 202 后，job 状态在合理时间内从 `queued` → `running` → `succeeded`（或 `failed`）
2. 重新分块成功后，chunks 正确入库，旧 job 被标记 `superseded`
3. 重新分块失败（如原始文件缺失），job 正确标记 `failed` 并记录错误信息
4. 重复触发 rechunk 仍返回 409，不受后台执行影响
5. 进程关闭时，QUEUED/RUNNING 的 rechunk job 被正确标记为 `process_shutdown`
6. 现有测试全部通过，新增测试覆盖后台执行路径
