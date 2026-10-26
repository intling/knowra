# RED 阶段评审记录

日期：2026-10-26。变更：`add-adaptive-rag-answering`。

## 当前状态

方案、设计、四份能力规格和实施任务已建立。本阶段只新增 OpenSpec 工件、测试及测试结果，没有修改生产代码、部署或消费演示账号额度。按项目 `openspec/config.yaml` 第 64、109 行的要求，等待维护者评审后明确回复“继续”，再进入 GREEN。

## 已执行命令与结果

后端工作目录 `backend`：

```bash
uv run pytest tests/services/test_adaptive_rag_answering.py tests/services/test_adaptive_rag_summary.py tests/api/test_adaptive_rag_api.py -q --tb=line --show-capture=no --junitxml=../openspec/changes/add-adaptive-rag-answering/evidence/backend-red.xml
```

| 文件 | 总数 | 预期失败 | 保护用例通过 |
| --- | ---: | ---: | ---: |
| `tests/services/test_adaptive_rag_answering.py` | 17 | 17 | 0 |
| `tests/services/test_adaptive_rag_summary.py` | 14 | 14 | 0 |
| `tests/api/test_adaptive_rag_api.py` | 16 | 13 | 3 |
| 合计 | 47 | 44 | 3 |

退出码 1；`44 failed, 3 passed in 2.76s`。JUnit 中 errors=0、skipped=0。通过的保护用例为通用/总结请求仍需认证、未配置对话模型仍返回有原因的 503。

前端工作目录 `front`：

```bash
npm run test -- src/components/layout/__tests__/ChatArea-adaptive.spec.ts src/api/search-adaptive.test.ts --reporter=json --outputFile=../openspec/changes/add-adaptive-rag-answering/evidence/frontend-red.json
```

| 文件 | 总数 | 预期失败 | 保护用例通过 |
| --- | ---: | ---: | ---: |
| `src/components/layout/__tests__/ChatArea-adaptive.spec.ts` | 11 | 8 | 3 |
| `src/api/search-adaptive.test.ts` | 1 | 1 | 0 |
| 合计 | 12 | 9 | 3 |

退出码 1。通过的保护用例为复制/真实 token 仍可见、资料增强仍保留来源及折叠诊断、缺少新字段的旧响应仍按原样展示。

共 59 个用例，53 个预期失败、6 个保护用例通过；没有测试收集错误、缺少依赖或错误夹具导致的假 RED。测试过程中发现并修正了不可变 ChatResult 的夹具赋值方式，最终记录使用修正后的完整重跑结果。

静态检查：

```bash
cd backend
uv run ruff check tests/services/test_adaptive_rag_answering.py tests/services/test_adaptive_rag_summary.py tests/api/test_adaptive_rag_api.py
uv run ruff format --check tests/services/test_adaptive_rag_answering.py tests/services/test_adaptive_rag_summary.py tests/api/test_adaptive_rag_api.py
cd ../front
npx eslint src/components/layout/__tests__/ChatArea-adaptive.spec.ts src/api/search-adaptive.test.ts
```

均退出 0，Ruff 报告 `All checks passed!` 和 `3 files already formatted`。OpenSpec 使用已缓存的 CLI：

```bash
node /root/.npm/_npx/abab5bd700860149/node_modules/@fission-ai/openspec/bin/openspec.js validate add-adaptive-rag-answering --strict
```

退出 0，报告 `Change 'add-adaptive-rag-answering' is valid`。

## 失败原因与验收映射

- 问候/明确通用请求仍进入重写和 Embedding；受控 Embedding 故障阻断模型回答。
- 空知识库仍返回上传提示；零召回和弱相关过滤后仍返回固定拒答。HTTP 入口仍把空向量数统一转成 404。
- 资料提示词不允许有明确归属的通用知识补充，缺少资料时没有可操作的澄清状态。
- 总结没有按文档读取、覆盖预算或范围参数，不能处理无向量但已分块的文档、外置正文、最新成功版本及多文档范围。
- 服务未接收 `document_ids`，API 静默忽略其格式和内容，前端没有转发；范围隔离、计数与缓存用例因此失败。当前测试没有证明旧代码泄露了资料，只证明新的范围契约尚未存在。
- 空上下文路径没有调用模型，无法执行模型失败/空内容保护，也不能对通用问答正常计额或对澄清明确释放。
- 主界面始终挂载零引用、空来源告警和检索详情，缺少通用知识、检索故障及部分总结的展示；非空生成降级提示仍被当作正常答案。

## 评审入口

- [方案](../proposal.md)、[设计](../design.md)、[实施任务](../tasks.md)
- [回答策略测试](../../../../backend/tests/services/test_adaptive_rag_answering.py)
- [资料总结测试](../../../../backend/tests/services/test_adaptive_rag_summary.py)
- [HTTP 与额度测试](../../../../backend/tests/api/test_adaptive_rag_api.py)
- [主对话测试](../../../../front/src/components/layout/__tests__/ChatArea-adaptive.spec.ts)
- [API 转发测试](../../../../front/src/api/search-adaptive.test.ts)
- 原始结果：[后端日志](backend-red.log)、[JUnit](backend-red.xml)、[前端日志](frontend-red.log)、[Vitest JSON](frontend-red.json)

## 实测边界

资料读取、认证、SQLModel 和额度使用真实本地测试数据库；模型与 Embedding 仅在网络边界替换，SQLite 不支持的 pgvector 运算使用测试替身。这里验证的是行为契约和待修分支，没有验证真实模型的总结质量，也不代表 demo 账号已生效。GREEN 完成后仍须跑完整质量门禁和本地浏览器验收。
