## 问题1：
backend/app/services/search.py
        缓存键 = SHA-256(session_id + ":" + query + ":" + str(top_k)) 的前 16 字符。
        三方组合确保：相同会话 + 完全相同查询文本 + 相同 top_k 才能命中。
        """
        raw = f"{session_id}:{query}:{top_k}"
**[阻断] history 没有进入完整 `SearchResponse` 的缓存键。** 显式 `session_id` 存在时，`_resolve_session_id()` 会忽略 history，而这里的 key 只含 session/query/top_k。当前 Head 的真实请求中，同一 session/query 仅把 history 从"蓝色档案"改为"红色档案"后，第二次 25.7ms 直接返回了蓝色的改写和检索结果。
**建议** 请把规范化 history digest（以及服务端可信的用户/会话身份）纳入 response cache identity；无法确定身份时不要用全局 `__default__` 复用完整私有响应。

## 问题2
backend/app/services/cache_manager.py
            )
            return None

        # NOTE: L1 不校验知识库指纹（设计决策：同一会话内知识库
**[阻断] 这个"L1 不校验 fingerprint"的前提被本 PR 的 force/软删除流程打破。** 当前 Head 复验：缓存结果后软删除 `blue-review.txt`，同 session 23.6ms 仍返回已删除来源；新 session 重新检索则正确排除它。上传/替换可以在同一会话的 TTL 内发生，所以完整搜索响应不能跳过文档可见性失效。
**建议** 请在 delete/force/索引状态变化时失效 response cache，或把 active-document 版本纳入读取校验。

## 问题3：
backend/app/services/query_rewriter.py
        if dedup_key in self._inflight:
            inflight_event = self._inflight[dedup_key]
            if not inflight_event.is_set():
                await inflight_event.wait()
**[阻断] `_inflight` 中的 `asyncio.Event` 被同步 FastAPI 路由创建的不同 `asyncio.run()` event loop/worker thread 共享，且这里没有等待边界。** 当前 Head 的两线程复现中只有 1 个请求完成，另一个在 2 秒后仍停在此处。跨 loop 直接等待/`set()` 不是线程安全交接。
**建议** 请让整条请求运行在同一个应用 event loop，或改用线程安全的 future/lock，并为 follower 等待设置超时和清理路径。

## 问题4：
backend/app/services/query_rewriter.py

            # Update the last strategy rewrite's query to the restored version
            if strategy_rewrites:
                strategy_rewrites[-1]["query"] = final_query
**[阻断] 并行 `term_align` 的输出在这里被 normalize 的 `current_query` 覆盖。** `term_result` 在 934–945 行只 append、未更新 `current_query`；因此本行会把最后一条标记为 `term_align` 的 query 改成 normalize 结果。当前最小复现得到两条都是 `normalized result`，而 Postprocessor 在覆盖前评估的是 term-align 文本，检索又使用第一个结果。
**建议** 请明确选出唯一 effective query，并让质量评估、`rewritten_queries`、策略标签和向量检索都使用同一份值。

## 问题5：
backend/app/services/cache_manager.py
        normalized = self._normalize_text(query_text)
        composite_key = self._make_l2_key(normalized)

        entry = self._l2_store.get(composite_key)
**[阻断] 这仍是规范化文本的精确字典查询，不是 OpenSpec 承诺的 L2 语义缓存。** 当前实现没有 query embedding 或余弦距离候选检索；复验写入"如何办理退款？"后查询"退款流程是什么？"必然 miss。`query-rewriting-phase2` 要求向量余弦距离 `<= 0.05` 时命中。
**建议** 请实现向量/余弦检索和后续 fingerprint/context/TTL 校验，或在本 PR 中撤下该未完成能力，不能以固定 `similarity=1.0` 宣称 semantic cache。

## 问题6： 
backend/app/models/uploaded_file.py
        Index("ix_uploaded_files_owner_user_id", "owner_user_id"),
        Index("ix_uploaded_files_status", "status"),
        Index("ix_uploaded_files_created_at", "created_at"),
        Index(
**[重要] 这只是普通索引，既不能保证并发幂等，也不会被部署数据库创建。** `create_upload()` 是 select-then-insert；这里没有 `unique=True` 或 active-row partial constraint，且本 PR 没有 Alembic revision。当前 `alembic check` 检测到新增 `ix_uploaded_files_dedup`，但 fresh upgrade 后真实 DB 中没有该索引。
**建议** 请增加 migration，使用 `(owner_user_id, checksum_sha256) WHERE deleted_at IS NULL` 的 partial unique index，并把 `IntegrityError` 转为读取已存在记录。

## 问题7：
backend/app/services/search.py
                    error=str(exc),
                )
        else:
            # 未配置重写时仍返回基本 RewriteInfo，保证前端始终展示

**[重要] canonical Phase 1 要求 disabled 或 rewrite failure 时 `SearchResponse.rewrite_info=null`，这里却强制构造空对象。** 当前 Head 以 `QUERY_REWRITE_ENABLED=false` 启动后，真实 `/api/search` 返回的 `rewrite_info` 仍非 null，前端会显示空的重写面板。
**建议** 请将 schema 改为 nullable，在 disabled/failure 路径返回 null，并只在非 null 且有改写结果时渲染 RewritePanel。


## 方案对比与最优选择

以下对每个问题的可行方案从**代码复杂度**、**执行效率**、**维护成本**三个维度进行对比，并给出最优方案。

---

### 问题1：history 未进入 SearchResponse 缓存键

**现状**：`_make_search_cache_key` (search.py:157-164) 仅包含 `(session_id, query, top_k)`。当显式传入 `session_id` 时 `_resolve_session_id` (search.py:167-180) 直接使用它而忽略 history，导致不同 history 的相同 query 返回同一缓存。

#### 方案 A：将 history digest 纳入缓存键（散列拼接）

在 `_make_search_cache_key` 中增加 `history_digest` 参数，对 history 做规范化后 SHA-256，拼入 raw 字符串。

```python
raw = f"{session_id}:{query}:{top_k}:{history_digest}"
```

| 维度 | 评价 |
|------|------|
| 复杂度 | ⭐⭐ 低 — 单函数修改，~15 行 |
| 效率 | ⭐⭐⭐ 高 — SHA-256 是 O(n)，history 通常 < 20 条消息，开销可忽略（< 0.1ms） |
| 维护 | ⭐⭐⭐ 高 — 语义清晰：缓存键明确表达"相同输入 → 相同结果" |

#### 方案 B：在 store 时校验 history 差异（读时比较）

缓存时不改键，但在 `lookup` 命中后额外比对 history 是否一致，不一致则视为 miss。

| 维度 | 评价 |
|------|------|
| 复杂度 | ⭐ 中 — 需要在 lookup 处增加比较逻辑，且缓存条目需额外存储 history 快照 |
| 效率 | ⭐ 低 — 每次命中都要做 O(n) 列表比较，且无效条目会占用缓存空间直到被 LRU 淘汰 |
| 维护 | ⭐ 低 — 语义不直观：缓存键与有效性条件分离，调试时难以追踪 |

#### 方案 C：禁用显式 session_id 时的响应缓存

当 `session_id` 显式传入且同时有 history 时，跳过 SearchResponse 缓存。

| 维度 | 评价 |
|------|------|
| 复杂度 | ⭐⭐⭐ 最低 — 一个 if 判断 |
| 效率 | ⭐ 低 — 牺牲了全部显式 session_id 场景的缓存收益 |
| 维护 | ⭐⭐ 中 — 简单粗暴，但未来需要解释"为什么有 session_id 就不缓存" |

#### ✅ 最优方案：A

**理由**：方案 A 成本最低、收益最大。方案 B 的"读时比较"浪费内存且逻辑分散。方案 C 因噎废食——显式 session_id 恰恰是多轮对话中最需要缓存的场景。实现时注意 history 需先做确定性规范化（排序、去空白），确保相同语义产生相同 digest。

**⚠️ 补充安全要求**：当无法确定可信用户/会话身份时（如未认证的匿名请求、缺少可信身份令牌），**不得使用全局 `__default__` 会话复用完整私有 SearchResponse 缓存**。`__default__` 仅能用于非用户相关的公共查询缓存；任何包含私有上下文的完整响应（如含 history 的改写结果、含文档来源的检索结果）必须绑定到可验证的会话身份。实现要点：
1. `_resolve_session_id` 在无法确定身份时应返回 `None` 而非 `__default__`
2. `_make_search_cache_key` 收到 `session_id=None` 时应跳过缓存写入（不 store），仅做只读查询
3. 或在缓存键中注入可信身份 digest（如 JWT subject hash），确保不同用户无法互相命中私有缓存

---

### 问题2：L1 缓存不校验文档可见性

**现状**：`lookup` (cache_manager.py:122-169) 明确注释"L1 不校验知识库指纹"，理由是"同一会话内知识库不可能在 5-30 分钟的缓存 TTL 内发生变更"。但本 PR 的软删除/上传/替换操作可在同一会话 TTL 内发生，导致已删除文档的内容仍被返回。

#### 方案 A：文档状态变更时主动失效缓存（事件驱动）

在 `delete/force/upload` 操作完成后，调用 `CacheManager.invalidate_session(session_id)` 清空该会话的全部 L1 条目。

| 维度 | 评价 |
|------|------|
| 复杂度 | ⭐⭐ 低 — 在 CacheManager 新增一个 `invalidate_session` 方法，在文件操作 API 中调用 |
| 效率 | ⭐⭐ 中 — 主动失效是最精确的，但粒度是"整个会话"，会误伤该会话中与变更无关的其他查询缓存 |
| 维护 | ⭐⭐⭐ 高 — 语义清晰：状态变更 → 缓存失效，符合 cache invalidation 最佳实践 |

#### 方案 B：L1 增加文档版本/指纹校验

在 `lookup` 时额外检查缓存条目中的文档版本号是否与当前一致。

| 维度 | 评价 |
|------|------|
| 复杂度 | ⭐ 中-高 — 需要维护全局文档版本号（每次增删改递增），L1 条目存储版本号，lookup 时比对 |
| 效率 | ⭐⭐⭐ 高 — 精确到条目级别，无误伤 |
| 维护 | ⭐ 中 — 引入"文档版本"概念，与已有的知识库指纹部分重叠，增加概念负担 |

#### 方案 C：缩短 L1 TTL 到忽略变更窗口

将 SearchResponse L1 缓存 TTL 从 600s 缩短到 30s。

| 维度 | 评价 |
|------|------|
| 复杂度 | ⭐⭐⭐ 最低 — 改一个配置值 |
| 效率 | ⭐ 低 — 缓存命中率大幅下降，30s 内同一查询重复的概率远低于 600s |
| 维护 | ⭐ 低 — 治标不治本，30s 内发生删除仍然命中脏数据 |

#### ✅ 最优方案：A

**理由**：这是一个典型的 **cache invalidation** 问题，而非 cache key design 问题。方案 A 遵循"写时失效"（write-invalidate）模式——当数据源发生变更时主动清除受影响的缓存。粒度选择"整个会话"是因为：L1 本身就是会话绑定缓存，文件操作影响该会话中的所有检索结果，全量清理由此合理。相比方案 B，不需要引入新的版本号概念（知识库指纹已存在且 L1 故意不用）；相比方案 C，不牺牲缓存命中率。

---

### 问题3：`asyncio.Event` 跨 event loop 共享导致请求挂起

**现状**：`_inflight` (query_rewriter.py:380-381) 使用 `asyncio.Event` 做请求去重。但搜索端点 `search_documents` (routes/search.py:298) 是 `def`（同步函数），FastAPI 将其分配到线程池中的独立线程执行。`_run_async` 在调用 `rewrite()` 时创建新的 event loop。不同线程的 event loop 各自独立，一个线程中 `event.set()` 无法唤醒另一个线程中 `event.wait()`——导致永久挂起。

#### 方案 A：将 `asyncio.Event` 替换为 `threading.Event` + 线程安全包装

```python
import threading

self._inflight: dict[str, threading.Event] = {}
self._inflight_results: dict[str, RewriteResult] = {}
self._inflight_lock = threading.Lock()
```

| 维度 | 评价 |
|------|------|
| 复杂度 | ⭐⭐ 低 — 替换 import 和初始化，逻辑不变，需增加 Lock 保护 dict 操作 |
| 效率 | ⭐⭐⭐ 高 — `threading.Event` 开销与 `asyncio.Event` 同级，线程安全等待不占用 CPU |
| 维护 | ⭐⭐ 中 — 混合使用 threading 原语与 asyncio 代码，风格上略有不一致；需确保 `threading.Event.wait()` 可在 async 上下文中不阻塞 event loop（添加超时参数） |

#### 方案 B：将搜索端点改为 `async def`，统一到同一个 event loop

| 维度 | 评价 |
|------|------|
| 复杂度 | ⭐ 中-高 — 需要将整个 `search()` → `_vector_search()` → `_build_results()` 链路改为 async，涉及数据库 session 的 async 支持（需引入 `sqlalchemy.ext.asyncio`） |
| 效率 | ⭐⭐⭐ 最高 — 真正的 async 全链路，释放线程池资源，提升并发能力 |
| 维护 | ⭐⭐⭐ 最高 — 长期最优解，与 FastAPI 最佳实践一致 |

#### 方案 C：移除请求去重，仅依赖 L1 缓存

```python
# 直接删除 _inflight 相关逻辑
```

| 维度 | 评价 |
|------|------|
| 复杂度 | ⭐⭐⭐ 最低 — 删代码 |
| 效率 | ⭐ 中 — 失去去重保护，两个并发相同查询会各自调用 LLM，浪费 token |
| 维护 | ⭐⭐⭐ 高 — 代码更简单 |

#### ✅ 最优方案：**短期 A / 长期 B**

**理由**：方案 B 是架构层面的正解——FastAPI 的同步端点 + 内部 async 桥接本身就是技术债务。但改造成本高（需异步化整个 DB 访问链路），不应在本 PR 中做。**推荐本 PR 先用方案 A**：用 `threading.Event` 替换 `asyncio.Event`，加上 `threading.Lock` 保护 dict 操作，并在 `wait()` 上设置超时（如 30s）+ 超时后的清理路径。同时创建一个技术债务 issue 追踪方案 B 的长期改造。

方案 C 虽然最简单，但损失了有价值的去重能力（两个用户在同一个 session 中同时问相同问题，去重可以节省一次 LLM 调用）。

---

### 问题4：并行 `term_align` 结果被 `normalize` 的 `current_query` 覆盖

**现状**：并行执行 normalize 和 term_align（query_rewriter.py:914-944）时，normalize 更新 `current_query`（932 行），term_align 不更新 `current_query`（只 append 到 `strategy_rewrites`）。后续保护词还原（1187 行）基于 `current_query`（此时为 normalize 输出）计算 `final_query`，然后用 `strategy_rewrites[-1]["query"] = final_query`（1193 行）覆盖最后一条——即 term_align 条目。

#### 方案 A：明确"主策略"概念，只更新主策略对应的条目

在并行结果合并时标记哪个是"主策略"（primary/effective），后续保护词还原只更新主策略条目 + 同步更新 `current_query`。

```python
# 并行合并时
primary_strategy_index = None  # 记录主策略在 strategy_rewrites 中的索引
if norm_result is not None:
    strategy_rewrites.append({...})
    primary_strategy_index = len(strategy_rewrites) - 1
    current_query = norm_query

# 保护词还原后
if primary_strategy_index is not None:
    strategy_rewrites[primary_strategy_index]["query"] = final_query
```

| 维度 | 评价 |
|------|------|
| 复杂度 | ⭐⭐ 低 — ~10 行改动，逻辑自文档化 |
| 效率 | ⭐⭐⭐ 高 — 零额外开销 |
| 维护 | ⭐⭐⭐ 高 — "主策略"概念清晰，后续扩展并行策略时不会出错 |

#### 方案 B：保护词还原应用到所有 `strategy_rewrites` 条目

```python
for rw in strategy_rewrites:
    rw["query"] = self._protector.restore(rw["query"], term_map)
```

| 维度 | 评价 |
|------|------|
| 复杂度 | ⭐⭐⭐ 最低 — 3 行改动 |
| 效率 | ⭐⭐ 中 — 多次调用 `restore()`（虽然开销很小，但语义上不必要） |
| 维护 | ⭐ 低 — 保护词还原应该只保护一次，多次还原可能引入双重替换的边界情况；且 `current_query` 的来源仍然模糊 |

#### 方案 C：并行结果不混合，N选1

并行执行 normalize 和 term_align，但只保留一个结果（如质量更高的那个），丢弃另一个。`strategy_rewrites` 中只记录选中的策略。

| 维度 | 评价 |
|------|------|
| 复杂度 | ⭐ 中 — 需要引入选择逻辑（用 Postprocessor 评估？用启发式？） |
| 效率 | ⭐ 低 — 浪费了一条 LLM 调用的结果 |
| 维护 | ⭐⭐ 中 — 概念上更简单（一个查询一个改写），但损失了调试可见性 |

#### ✅ 最优方案：A

**理由**：方案 A 在最小改动的前提下解决了根因——`strategy_rewrites[-1]` 的"最后一条"假设在并行场景下不成立。"主策略"概念明确表达了意图：并行分支中选一个作为后续策略链的输入，它的 `query` 才是 effective query。方案 B 看似更简单，但在保护词还原中"对每个改写各自还原"可能导致 term_align 的结果被二次处理（term_align 可能已经处理了术语映射，restore 可能引入语义漂移）。方案 C 损失了并行策略的调试可见性。

**⚠️ 补充一致性约束**：实现时必须确保以下四个消费点使用**同一份** effective query 值，禁止各自推导或独立选择：
1. **质量评估（Postprocessor）** — 评估的文本必须是最终被检索使用的 query
2. **`rewritten_queries` 列表** — 返回给前端的改写记录中，主策略条目的 `query` 必须与 effective query 一致
3. **策略标签（`strategies_used`）** — 标签与实际使用的策略对齐，不能被覆盖为错误策略名
4. **向量检索** — `SearchService._vector_search()` 接收的 query 参数必须是 effective query

实现约束：在并行合并完成后、保护词还原完成后、以及最终构造 `RewriteInfo` 前，各增加一次断言/日志检查，确保 `current_query == strategy_rewrites[primary_strategy_index]["query"]`。

---

### 问题5：L2 语义缓存实为精确文本匹配

**现状**：`lookup_l2` (cache_manager.py:293-353) 使用 `_normalize_text` + `_make_l2_key` 做规范化文本的精确字典查询，返回固定 `similarity: 1.0`。OpenSpec 要求向量余弦距离 ≤ 0.05 命中。

#### 方案 A：实现真正的向量语义检索

引入 EmbeddingAdapter，在 `store_l2` 时计算并存储查询向量，在 `lookup_l2` 时计算当前查询向量，对 L2 中的所有向量做余弦相似度计算，返回相似度 > 0.95 的最佳匹配。

| 维度 | 评价 |
|------|------|
| 复杂度 | ⭐ 中-高 — 需要修改 L2 条目格式（增加 embedding 字段）、实现余弦检索逻辑、处理 O(n) 暴力搜索的性能问题（L2 条目数增长后需切换到 ANN 索引） |
| 效率 | ⭐ 低-中 — 每次 lookup 需要向量化当前查询 + 与所有 L2 条目计算余弦距离。嵌入 API 调用增加延迟（通常 50-200ms） |
| 维护 | ⭐⭐ 中 — 引入了嵌入依赖和 ANN 索引的未来需求，复杂度显著增加 |

#### 方案 B：本 PR 降级为精确缓存，更新文档和 OpenSpec

保留当前精确匹配实现，但：
1. 删除 `similarity: 1.0` 的虚假宣称
2. 将 `lookup_l2` 的文档注释更新为"精确文本匹配（规范化后）"
3. 更新 OpenSpec 将向量语义检索标记为后续迭代
4. 在 `store_l2` 的注释中说明当前限制

| 维度 | 评价 |
|------|------|
| 复杂度 | ⭐⭐⭐ 最低 — 只改注释和文档 |
| 效率 | ⭐⭐⭐ 最高 — 精确匹配 O(1)，无额外开销 |
| 维护 | ⭐⭐⭐ 高 — 诚实的文档是最好维护的 |

#### 方案 C：混合方案——精确匹配 + 编辑距离/ngram 模糊匹配

不引入嵌入向量，在精确匹配 miss 时用 Jaccard/Dice/编辑距离做轻量级模糊匹配。

| 维度 | 评价 |
|------|------|
| 复杂度 | ⭐ 中 — 实现简单，但语义效果有限 |
| 效率 | ⭐ 中 — O(n) 扫描全部 L2 条目，但无 API 调用 |
| 维护 | ⭐ 低 — 模糊匹配不是"语义"匹配，"如何办理退款"和"退款流程是什么"仍然会 miss |

#### ✅ 最优方案：B（本 PR）+ A（后续 PR）

**理由**：方案 A 是功能目标，但成本估算被低估了——向量语义缓存的端到端延迟增加（每次 lookup 需额外嵌入 API 调用 50-200ms）可能抵消甚至超过缓存命中的收益（省去 LLM 调用）。一个精确文本缓存也有其价值："Python 列表排序"这种标准化查询在不同用户之间频繁重复。**推荐本 PR 执行方案 B**：诚实降级、更新文档，将向量检索标记为后续迭代。方案 C 是伪语义，不解决根本问题，不推荐。

关键：在后续 PR 实现方案 A 时，需做性能基准测试——确认向量检索的延迟增加（嵌入 API）确实小于 LLM 调用节省的延迟。

---

### 问题6：缺少 Alembic migration + 去重索引非 unique → 并发上传可重复

**现状**：[uploaded_file.py:16-21](backend/app/models/uploaded_file.py#L16-L21) 的 `ix_uploaded_files_dedup` 是普通复合索引（非 unique），且 PR 没有 Alembic migration。`create_upload()` 是 select-then-insert，存在竞态窗口。

#### 方案 A：Partial unique index + Alembic migration + IntegrityError 处理

```python
# 模型
Index(
    "ix_uploaded_files_dedup",
    "owner_user_id",
    "checksum_sha256",
    unique=True,
    postgresql_where=(UploadedFile.deleted_at.is_(None)),
)
```

在 `create_upload()` 中捕获 `IntegrityError` 并转为读取已存在记录。

| 维度 | 评价 |
|------|------|
| 复杂度 | ⭐⭐ 低 — 改动集中：模型 1 行 + migration 1 个文件 + upload 逻辑 5 行 |
| 效率 | ⭐⭐⭐ 高 — 数据库级唯一约束是最高效的并发保护（B-tree 唯一索引，O(log n)） |
| 维护 | ⭐⭐⭐ 最高 — 这是数据库并发控制的行业标准模式，任何 DBA 都能理解 |

#### 方案 B：应用层加锁（`threading.Lock` 或 `asyncio.Lock`）

在 `create_upload()` 中对 `(owner_user_id, checksum_sha256)` 加应用层互斥锁。

| 维度 | 评价 |
|------|------|
| 复杂度 | ⭐⭐ 低 — 加锁解锁 |
| 效率 | ⭐ 低 — 单实例锁，多进程/多实例部署时无效（无法水平扩展） |
| 维护 | ⭐ 低 — 应用层锁是分布式系统中的反模式；多个 worker 进程各自持有锁，无法互斥 |

#### 方案 C：乐观锁——先 insert，冲突后 select

不做唯一索引，保留 select-then-insert，但在 IntegrityError 时 fallback。

| 维度 | 评价 |
|------|------|
| 复杂度 | ⭐⭐⭐ 最低 — 只加 try/except |
| 效率 | ⭐ 低 — 没有唯一约束，IntegrityError 不会触发（当前索引不是 unique），竞态窗口依然存在 |
| 维护 | ⭐ 低 — 根本没有保护效果 |

#### ✅ 最优方案：A

**理由**：这是数据库并发控制的标准答案——**partial unique index**。PostgreSQL 的 partial unique index 天然支持软删除场景（`WHERE deleted_at IS NULL`），允许多个已删除的同文件记录共存，同时保证活跃记录唯一。方案 B 无法水平扩展。方案 C 是空中楼阁——当前索引不是 unique，`IntegrityError` 永远不会被触发，只是心理安慰。

需要创建的 Alembic migration：
```python
# 删除旧非 unique 索引 + 创建 partial unique index
op.drop_index("ix_uploaded_files_dedup", table_name="uploaded_files")
op.create_index(
    "ix_uploaded_files_dedup",
    "uploaded_files",
    ["owner_user_id", "checksum_sha256"],
    unique=True,
    postgresql_where=text("deleted_at IS NULL"),
)
```

---

### 问题7：`QUERY_REWRITE_ENABLED=false` 时 `rewrite_info` 仍非 null

**现状**：[search.py:307-314](backend/app/services/search.py#L307-L314) 在 `_query_rewriter` 为 None 时仍然构造非 null 的 `RewriteInfo`（含空列表）。[search.py:181](backend/app/schemas/search.py#L181) 的 `SearchResponse.rewrite_info` 有 `default_factory`，始终非 null。OpenSpec 要求 disabled 时返回 null。

#### 方案 A：rewrite_info 改为 Optional，未配置时返回 None

```python
# schema
rewrite_info: RewriteInfo | None = Field(default=None, ...)

# search.py
if self._query_rewriter is not None:
    rewrite_info = ...
else:
    rewrite_info = None
```

前端仅当 `rewrite_info !== null && rewrite_info.rewritten_queries.length > 0` 时渲染 RewritePanel。

| 维度 | 评价 |
|------|------|
| 复杂度 | ⭐⭐⭐ 最低 — Schema 1 行 + search.py 3 行 + 前端 1 行 |
| 效率 | ⭐⭐⭐ 最高 — 无性能影响 |
| 维护 | ⭐⭐⭐ 最高 — 语义精确：null = "功能未启用"，与 OpenSpec 契约一致 |

#### 方案 B：保持非 null，前端根据 `strategies_used` 是否为空决定显示

| 维度 | 评价 |
|------|------|
| 复杂度 | ⭐⭐⭐ 最低 — 不改后端 |
| 效率 | ⭐⭐⭐ 高 — 无变化 |
| 维护 | ⭐ 低 — `strategies_used: []` 既可以表示"未启用"也可以表示"重写失败" -> 语义过载，前端无法区分 |

#### ✅ 最优方案：A

**理由**：null vs empty 是 API 设计中的经典问题。`null` 的语义是"不存在"（功能禁用），`[]` 的语义是"存在但为空"（功能启用了但重写出空了）。方案 A 让 null 承载正确的语义，前后端一致。方案 B 的语义过载会导致前端无法区分"未启用重写"和"重写尝试了但没产出"——虽然在当前实现中两者表现相同，但未来的差异化处理（如"重写失败"显示错误提示）将无法实现。

改动量极小（~6 行），风险为零（纯 additive 的 schema 变更——字段从 required non-null 变为 optional nullable，老客户端反序列化不受影响，因为 `null` 被 `model_validate` 直接接受）。

---

## 优先级排序

按 **严重性 × 影响范围 ÷ 整改难度** 综合排序。P0 为阻断性缺陷（必须最先修复），P1 为高危缺陷，P2 为重要改进，P3 为一般问题。

### P0 — 阻断性缺陷（立即修复）

| # | 问题 | 严重性 | 影响范围 | 难度 | 症状 |
|---|------|--------|----------|------|------|
| **问题3** | `asyncio.Event` 跨 event loop 共享导致请求挂起 | 🔴 阻断 | 所有并发用户 | 中-高 | 两并发请求中 1 个永久阻塞在 `inflight_event.wait()`，2s 后仍未返回 |
| **问题1** | history 未进入 SearchResponse 缓存键 | 🔴 阻断 | 所有带上下文的用户 | 中 | 切换 history 后返回旧缓存的改写和检索结果（25.7ms 缓存命中，内容完全错误） |
| **问题2** | L1 缓存不校验文档可见性，软删除后仍返回已删除来源 | 🔴 阻断 | 所有在会话 TTL 内发生增删的用户 | 低-中 | 上传/删除后同 session 23.6ms 返回已删除文件；新 session 才正确 |

**定级理由：**
- 问题3 是**可用性阻断**——请求直接挂起，无降级路径。任何生产并发都会触发。
- 问题1 是**正确性阻断**——用户获得错误答案，且与预期完全相反（不同 history 本应产生不同搜索结果）。
- 问题2 是**数据完整性阻断**——用户看到已被删除的敏感文档，在合规场景下可能构成信息泄露。

### P1 — 高危缺陷（本轮必修复）

| # | 问题 | 严重性 | 影响范围 | 难度 | 症状 |
|---|------|--------|----------|------|------|
| **问题4** | 并行 `term_align` 结果被 `normalize` 的 `current_query` 覆盖 | 🟠 高危 | 触发并行策略的用户 | 低-中 | `term_align` 和 `normalize` 输出均变为 `normalized result`；质量评估与检索使用不同文本 |

**定级理由：** 这是一个**静默正确性缺陷**——不会报错、不会挂起，但搜索结果使用了错误的改写文本，且 `rewritten_queries` 标签与实际使用的 query 不一致，导致调试/审计链路断裂。

### P2 — 重要缺陷（本 PR 应修复）

| # | 问题 | 严重性 | 影响范围 | 难度 | 症状 |
|---|------|--------|----------|------|------|
| **问题6** | 缺少 Alembic migration + 去重索引非 unique → 并发上传可重复 | 🟡 重要 | 并发上传同一文件的用户 | 低 | `alembic check` 检测到未迁移的索引；fresh upgrade 后 DB 无该索引；select-then-insert 竞态 |
| **问题5** | L2 语义缓存实际为精确文本匹配，非向量余弦检索 | 🟡 重要 | 所有期望语义缓存的用户 | 高 | "如何办理退款？" 写入后查询 "退款流程是什么？" 必然 miss；`similarity=1.0` 虚假宣称 |

**定级理由：**
- 问题6 本身修复简单（partial unique index + migration + IntegrityError 处理），但涉及数据库 schema 变更，一旦合并后难以回退，应在合入前完成。
- 问题5 是**功能不完整**而非缺陷——不影响正确性但影响缓存命中率。若实现向量检索成本过高，建议本 PR 中降级为精确缓存并更新文档/OpenSpec，后续 PR 补充语义能力。

### P3 — 一般问题

| # | 问题 | 严重性 | 影响范围 | 难度 | 症状 |
|---|------|--------|----------|------|------|
| **问题7** | `QUERY_REWRITE_ENABLED=false` 时 `rewrite_info` 仍非 null | 🟢 一般 | 禁用重写的部署环境 | 低 | 前端渲染空 RewritePanel；与 OpenSpec 要求矛盾 |

**定级理由：** 纯前端展示问题，不影响搜索正确性。但违反 OpenSpec 契约，且会在禁用重写的部署中暴露无意义的 UI 元素。

### 建议修复顺序

```
问题3 (请求挂起) → 问题1 (错误结果) → 问题2 (信息泄露)
    ↓
问题4 (静默覆盖) → 问题6 (数据完整性) → 问题5 (功能完整性 或 降级) → 问题7 (UI 契约)
```

P0 三项互相独立，可并行修复；P1 和 P2 可并行；P3 可随时修复。

---

