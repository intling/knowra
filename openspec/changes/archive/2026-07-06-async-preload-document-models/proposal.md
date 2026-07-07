## Why

当前启动模型 bootstrap 只保证 Docling artifacts 和 tokenizer 文件已下载到本地，第一次 PDF 解析仍会在用户请求路径中初始化 Docling pipeline 并加载 layout/tableformer 权重，导致首个解析作业出现明显长等待。该变更将“模型文件准备”和“模型对象加载到内存”拆开，让应用启动后异步预热内存模型，并在预热期间对需要模型的请求快速返回明确错误状态。

## What Changes

- 在现有文档模型 bootstrap 完成后启动进程内异步预加载流程，后台加载 Docling PDF converter/pipeline 和分块 tokenizer 到内存。
- 应用启动不等待内存预加载完成；预加载状态通过进程内 readiness 暴露为 `loading`、`ready`、`unavailable` 或 `skipped`。
- 需要 Docling 模型的解析请求在模型仍为 `loading` 或 `unavailable` 时快速失败，不进入 Docling 的长初始化路径。
- 自动分块和重新分块在 tokenizer 仍为 `loading` 或 `unavailable` 时快速失败或返回服务不可用，不在请求/作业路径中临时加载模型。
- 模型预加载成功后，解析和分块复用已加载到内存的 converter/tokenizer，减少首次用户作业的冷启动耗时。
- 扩展现有 `/api/health` 的 `document_models` 摘要，使部署方能看到模型内存预加载状态；不新增独立模型健康检查 endpoint。

## Capabilities

### New Capabilities
- 无

### Modified Capabilities
- `document-parsing`: 增加 Docling 内存预加载 readiness、预加载期间解析快速失败、预加载完成后复用内存 converter 的要求。
- `document-chunking`: 增加 tokenizer 内存预加载 readiness、预加载期间分块快速失败、预加载完成后复用内存 tokenizer 的要求。

## Impact

- 后端启动流程：FastAPI lifespan 在同步模型文件 bootstrap 后启动非阻塞后台预加载，不阻塞应用启动完成。
- 后端服务边界：新增进程内文档模型 runtime/preload 状态对象；解析和分块服务读取该状态决定是否执行。
- API 行为：`POST /api/uploads/{upload_id}/parse` 和 `POST /api/parsed-documents/{parsed_document_id}/rechunk` 在模型仍加载中时可返回 `503`；已创建的后台作业仍使用 `error_code=model_unavailable` 表达模型未就绪。
- 健康检查：现有 `GET /api/health` 继续返回 `200`，并通过 `document_models` 暴露 `loading`/`ready`/`unavailable`/`skipped` 摘要。
- 数据库：不新增表或迁移，模型加载状态只保存在进程内。
- 外部依赖：继续使用 Docling 和 Transformers；不新增面向用户的模型下载 API。
- 回滚：移除 runtime/preload 层后，系统可回到模型文件 ready 后由首次解析/分块懒加载的旧行为。
