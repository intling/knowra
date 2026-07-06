## Why

当前文档解析依赖的 Docling 模型会在用户上传文件后、解析作业真正执行时才被检查和按需下载。受限网络或未预热环境会让用户在解析阶段才遇到长时间等待和超时失败，阻断“接入资料 -> 解析内容 -> 分块与索引”的核心链路。

本变更将模型可用性检查和可选下载前移到项目启动后的模型准备流程中，让部署方可以指定独立的模型目录和 Hugging Face 镜像地址，并在解析前得到明确的 readiness 状态。

## What Changes

- 新增后端启动后的文档模型 bootstrap 流程，用于检查 Docling PDF 解析 artifacts 和分块 tokenizer 是否可用。
- 新增独立的 `DOCUMENT_MODEL_*` 环境变量命名空间，用于控制启动模型准备、下载策略、失败策略、模型存放目录、Hugging Face 镜像地址、Docling 模型清单和 tokenizer 缓存目录。
- 明确模型 bootstrap 配置 MUST NOT 复用或扩展既有 `DOCUMENT_PARSE_*` 或 `DOCUMENT_CHUNK_*` 环境变量，避免解析行为配置、分块行为配置和模型准备配置混在一起。
- 支持在模型缺失时按配置自动下载到指定目录，或仅检查并在不可用时进入失败/降级状态。
- 解析和分块链路在执行前使用 bootstrap readiness，模型不可用时返回或记录明确的模型不可用错误，而不是在 Docling 或 tokenizer 内部网络超时后才泛化为解析失败。
- 更新 `.env.example`、README 和后端文档，说明模型准备变量、镜像配置、离线/受限网络部署方式和启动失败策略。

## Capabilities

### New Capabilities

- 无

### Modified Capabilities

- `document-parsing`: 增加启动模型 bootstrap、独立模型环境变量、Docling artifacts readiness、模型不可用错误语义和解析前 readiness 检查要求。
- `document-chunking`: 增加分块 tokenizer readiness 接入要求，确保自动分块和重新分块不会在 tokenizer 缺失时退化为不明确的下载超时错误。

## Impact

- 后端配置：新增 `DOCUMENT_MODEL_*` 设置项和 `.env.example` 示例；既有 `DOCUMENT_PARSE_*` 与 `DOCUMENT_CHUNK_*` 语义保持不变。
- 后端启动流程：FastAPI lifespan 或等价启动阶段新增模型 bootstrap service，并保留禁用、检查、下载缺失、失败策略等配置化行为。
- 文档解析服务：解析任务执行前需要确认模型 readiness；错误码需要区分模型不可用和普通解析失败。
- 文档分块服务：默认 tokenizer 可用性纳入启动 readiness；分块失败应输出明确的 tokenizer/model unavailable 信息。
- 外部依赖：继续使用 Docling、Hugging Face Hub 和 Transformers 现有能力；镜像地址通过环境变量注入，不增加面向用户的任意下载 URL API。
- API/用户体验：复用现有 `GET /api/health` 暴露模型 readiness 摘要，不新增独立模型健康检查 endpoint；解析作业错误信息会更早、更明确。
- 数据库：不需要新增表或迁移。
- 回滚：移除 bootstrap service、新增配置和 readiness 检查后，系统可回到现有按解析时懒加载模型的行为；已下载到新模型目录的本地文件可由部署方手动清理。
