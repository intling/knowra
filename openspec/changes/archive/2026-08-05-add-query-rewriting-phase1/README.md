# Archived: query-rewriting-phase1

**Archived:** 2026-08-05
**Parent change:** [add-query-rewriting](../../add-query-rewriting/)
**Schema:** spec-driven

## What was archived

Phase 1（模块一）——查询重写基础管线，是 `add-query-rewriting` 变更的第一个交付模块。

## Scope

| 模块 | 状态 |
|------|------|
| 测试基础设施与契约定义（RewriteInfo Schema、前端类型） | ✅ 完成（35/35 任务） |
| AuditTrail 审计日志 | ✅ 完成 |
| QueryRewriter 顶层编排器 | ✅ 完成 |
| SearchService 集成与 API Route | ✅ 完成 |
| 前端 RewritePanel 基础组件 | ✅ 完成 |

## Spec Sync

Delta spec `query-rewriting-phase1` 已同步到主规格：
- **新增** `openspec/specs/query-rewriting/spec.md`（16 个需求）
- **修改** `openspec/specs/semantic-search/spec.md`（扩展搜索响应元信息 + 新增搜索耗时需求）

## Key deliverables

- `backend/app/services/audit_trail.py` — 结构化审计日志（structlog，仅文件输出）
- `backend/app/services/query_rewriter.py` — QueryRewriter 顶层编排器
- `backend/app/services/term_protector.py` — 精确词保护（正则 + 占位符）
- `backend/app/services/context_rewriter.py` — 上下文融合（指代词消解）
- `backend/app/services/cache_manager.py` — L1 LRU 缓存 + 请求去重
- `backend/app/services/query_rewrite_config.py` — 独立 LLM 配置
- `backend/app/services/prompt_loader.py` — Prompt 加载器（基础）
- `backend/prompts/context_fusion.yaml` — 上下文融合 Prompt
- `backend/prompts/protected_terms.yaml` — 保护词汇表
- `front/src/components/RewritePanel.vue` — 可折叠重写详情面板

## Remaining work (not archived)

- **Phase 2:** 意图分类、策略路由、规范化重述、术语对齐、扩展重述、L2 语义缓存
- **Phase 3 (integration):** 质量评估、回溯、熔断器、端到端验收
