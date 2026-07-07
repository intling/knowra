## Context

现有 `add-startup-model-bootstrap` 变更已经把 Docling artifacts 和 tokenizer 文件的检查/下载前移到 FastAPI lifespan 启动阶段。启动日志中的 `Document model bootstrap ready` 表示磁盘文件已就绪，但用户贴出的解析日志显示第一次 PDF 解析仍会在 `Initializing pipeline for StandardPdfPipeline` 后加载 layout/tableformer 权重，导致首个解析作业等待约几十秒。

Docling `DocumentConverter` 内部有 initialized pipeline cache。`DocumentConverter.initialize_pipeline(InputFormat.PDF)` 会创建并缓存 `StandardPdfPipeline`，而 `StandardPdfPipeline.__init__()` 会初始化 layout/tableformer 等重模型。因此可以在应用启动完成后异步调用该初始化入口，把 converter/pipeline 保存在进程内 runtime state，后续解析复用同一个 converter。

分块侧也有类似冷启动点：`DoclingChunkerAdapter` 当前在执行分块时创建 Hugging Face tokenizer。启动 bootstrap 已经保证 tokenizer 文件在本地可用，本变更会在后台预加载 tokenizer 对象并在分块时复用。

## Goals / Non-Goals

**Goals:**

- 在模型文件 bootstrap ready 后，后台异步加载 Docling PDF converter/pipeline 和分块 tokenizer 到内存。
- FastAPI startup 不等待内存预加载完成；应用可对 health、用户等非模型请求正常服务。
- 对需要模型的解析/分块操作，在预加载期间快速返回 `loading`/`model_unavailable` 语义，而不是等待第三方 SDK 初始化。
- 预加载完成后，解析和分块复用进程内已加载对象，减少首个用户作业的冷启动等待。
- 通过现有 `/api/health` 暴露模型内存状态，不新增独立健康检查 endpoint。

**Non-Goals:**

- 不把模型加载状态持久化到数据库。
- 不新增前端模型管理页面、下载进度 UI 或用户触发预加载 API。
- 不实现多进程/多副本之间的模型加载协调或共享内存。
- 不异步化模型文件下载；文件下载/check 仍沿用现有 bootstrap 策略。
- 不改变 embedding、检索、RAG 或引用生成能力。

## Decisions

### Decision 1: 新增进程内 `DocumentModelRuntime`，包裹 bootstrap readiness

`DocumentModelRuntime` 保留与既有 readiness 相同的 `status`、`docling`、`tokenizer` 访问形态，并额外保存已加载对象：

- `docling.status`: `loading`、`ready`、`unavailable`、`skipped`
- `docling.artifact_dir`
- `docling.resource`: 已初始化 pipeline 的 `DocumentConverter`
- `tokenizer.status`
- `tokenizer.model_name`
- `tokenizer.cache_dir`
- `tokenizer.resource`: 已创建的 `HuggingFaceTokenizer`

当 bootstrap 结果为 `skipped` 时，runtime 也保持 `skipped`，解析/分块回到旧的懒加载行为。当 bootstrap 结果为 `unavailable` 时，runtime 保持 `unavailable` 并不启动预加载。当 bootstrap 结果为 `ready` 时，runtime 初始化为 `loading` 并启动后台预加载。

选择理由：

- 兼容现有 health、解析、分块服务读取 readiness 的方式。
- 保持状态进程内，不引入数据库迁移。
- 允许后台线程原地更新状态，已排队的任务读取同一个对象即可看到最新状态。

替代方案：

- 复用不可变 `DocumentModelReadiness` 并反复替换 `app.state`：实现简单，但已排队后台任务可能持有旧对象，不采用。
- 在每个服务内各自管理预加载状态：会重复加载模型并分散错误语义，不采用。

### Decision 2: 预加载由 lifespan 启动后台线程，不阻塞 `yield`

FastAPI lifespan 继续先执行同步 `DocumentModelBootstrapService.run()`。如果文件 bootstrap ready，则构造 `DocumentModelRuntime` 并调用 `start_async()`，随后立即进入 `yield`。后台线程顺序加载 Docling converter 和 tokenizer，并用结构化日志记录 `loading`、`ready`、`unavailable`。

选择理由：

- 满足“应用启动后开始加载到内存，不阻塞主进程”。
- 避免在请求路径上创建长耗时任务。
- 对测试友好：runtime 可注入 fake loader，并可同步调用 `load_once()` 验证状态转换。

替代方案：

- 在 lifespan 中同步预加载：可以保证首个请求 ready，但会阻塞启动，不符合要求。
- 使用 FastAPI BackgroundTasks：只在请求后运行，不适合应用启动任务，不采用。

### Decision 3: Docling 预加载调用 `DocumentConverter.initialize_pipeline(InputFormat.PDF)`

`DoclingParserAdapter` 增加创建/preload converter 的公开方法。预加载服务使用与解析相同的 `ocr_enabled`、`max_pages` 和 `docling_artifact_dir` 创建 converter，并调用 `initialize_pipeline(InputFormat.PDF)` 触发 `StandardPdfPipeline` 初始化。解析时如果 runtime `docling.resource` 存在，则把该 converter 注入 `DoclingParserAdapter`。

选择理由：

- 不需要构造临时 PDF 文件，也不需要执行用户文档转换。
- 使用 Docling 已有 pipeline cache 机制。
- 预加载和真实解析使用同一配置，避免 hash 不一致导致真实解析再初始化一套 pipeline。

替代方案：

- 后台转换一个最小 PDF：可行但更慢、更脆弱，还会产生额外测试/临时文件复杂度，不采用。
- 只创建 `DocumentConverter`：不能保证权重已加载，不采用。

### Decision 4: 需要模型的请求在 `loading` 时 fail-fast

解析创建接口在识别出上传文件需要 Docling artifacts 且 runtime `docling.status == "loading"` 时返回 `503`。如果后台解析作业直接执行或读取到 `loading` 状态，则将作业失败为 `error_code=model_unavailable`。纯文本/Markdown 解析不依赖 Docling artifacts，仍可执行。

分块侧在 tokenizer `loading` 或 `unavailable` 时拒绝重新分块请求或把分块作业失败为 `error_code=model_unavailable`。当 tokenizer `skipped` 时维持旧行为。

选择理由：

- 避免请求线程或后台作业进入第三方 SDK 的长初始化路径。
- 复用现有 `model_unavailable` 错误语义，前端已有作业失败展示可继续使用。
- 纯文本路径不被 Docling 模型加载状态无谓阻塞。

替代方案：

- 请求等待预加载完成：用户明确要求不阻塞主进程，不采用。
- 把请求排队到预加载完成后自动执行：会隐藏真实等待时间并引入队列取消/超时语义，不采用。

## Risks / Trade-offs

- 多 worker 部署会让每个进程各自预加载一份模型 → 首版继续沿用单进程模型准备假设，未来多进程部署再设计共享/锁机制。
- 后台预加载失败会让模型状态变为 `unavailable` → health 暴露诊断，解析/分块快速失败，生产可通过日志和 health 发现。
- 共享 Docling converter 的线程安全依赖 Docling pipeline 设计 → 当前 Docling `StandardPdfPipeline` 明确按每次 execute 隔离运行状态；如未来出现并发问题，可在 runtime 中给 converter 使用加锁包装。
- `skipped` 会回到旧懒加载行为 → 这是禁用 bootstrap 的显式行为，适合测试或开发；生产建议保持 bootstrap enabled。

## Migration Plan

1. 新增 OpenSpec delta 和任务清单。
2. 按 TDD 增加 runtime 状态转换、lifespan 非阻塞启动、health loading 摘要、解析/rechunk fail-fast、解析/分块复用预加载资源的测试。
3. 新增 `DocumentModelRuntime` 和默认 preloader，接入 FastAPI lifespan。
4. 调整解析和分块服务读取 runtime resource 与 `loading` 状态。
5. 更新 README/.env.example 中模型 bootstrap 文档，说明模型文件 ready 后还会异步加载到内存。
6. 运行后端 targeted tests、ruff、format 和 pytest。

回滚时移除 runtime/preloader、lifespan 接入和请求期 loading 检查，保留既有文件 bootstrap 即可回到旧行为。

## Open Questions

无。首版按进程内异步预加载实现，不新增用户可触发的模型加载 API，也不改变模型文件下载策略。
