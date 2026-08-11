## Context

knowra 当前已完成 **上传 → 解析 → 分块 → 向量化 → 语义搜索 → LLM 生成** 的端到端 RAG 管线。但查询入口存在明显短板：用户原始查询直接送入向量化，未经任何预处理。口语化表达、术语不匹配、多意图纠缠、指代词依赖等问题导致检索向量偏离知识库中正式文档的语义空间，最终影响 LLM 回答质量。

本设计基于 `docs/query-rewriting-module-design.html` 中的完整方案，聚焦于 Phase 1 + Phase 2，在 SearchService 的查询向量化步骤之前插入纯 Prompt 驱动的查询重写管线。

**当前 SearchService 管线：**
```
用户查询 → embed_single() → pgvector 检索 → 结果过滤 → LLM 生成 → SearchResponse
```

**目标管线（集成 QueryRewriter 后）：**
```
用户查询 → [QueryRewriter.rewrite()] → embed_single(rewritten_query) → pgvector 检索 → 结果过滤 → LLM 生成 → SearchResponse (含 rewrite_info)
```

## Goals / Non-Goals

**Goals:**
- 在 SearchService 中透明集成查询重写管线，不改变检索和生成模块的契约
- 精确词保护：基于正则和词汇表，零 LLM 成本，防止专有名词被翻译
- 多轮对话上下文融合：指代消解，将依赖上下文的查询改写为独立完整查询
- 意图分类与复杂度评分：7 种意图 + 1-10 复杂度，驱动分层策略路由
- 三种核心重写策略：规范化重述、术语对齐、扩展重述（均通过单一 Prompt 模板实现）
- 两级缓存（模块一：会话绑定 L1 精确匹配；模块二：跨会话 L2 语义相似缓存 + 意图检测）
- 微批请求去重：时间窗口内相同/相似查询合并
- 改写质量评估：5 维评分，低质量改写自动丢弃或回溯升级策略
- 结构化审计日志：每次重写的完整链路可追溯
- 前端重写详情面板：可折叠展示改写结果，风格遵循 v2.0 设计系统
- 向后兼容：QUERY_REWRITE_ENABLED=false 时 SearchService 行为完全不变

**Non-Goals:**
- 不做 HyDE 策略（假设文档生成）
- 不做 Multi-Query 生成（多查询变体并发检索）
- 不做子问题分解（Decomposition）
- 不做后退提示词（Step-Back）
- 不做对比式重写、Query2Doc
- 不做异步改写通道（双通道：快速+增强）
- 不做 L3 热点统计缓存
- 不做知识图谱增强
- 不做 RRF 结果融合（属于检索模块 Phase 3）——当前阶段仅使用原始查询+首个改写结果进行检索
- 不新增数据库表——审计日志通过 structlog 输出至日志文件

## Decisions

### 1. 模块架构：单一入口 + 内部组件化

**选择**：`QueryRewriter` 作为顶层编排器，内部组合 ExactTermProtector、StrategyRouter、ContextRewriter、NormalizeRewriter、TermAlignRewriter、ExpandRewriter、CacheManager、Postprocessor、AuditTrail。外部通过 `QueryRewriter.rewrite(query, history)` 单一入口调用。

**组件职责：**
```
QueryRewriter.rewrite(query, history=None)
  │
  ├── ExactTermProtector.protect(query)        # 精确词保护（正则+词汇表）
  ├── CacheManager.lookup(query_hash)         # L1→L2 缓存查询
  │     ├── L1: SHA256(query)[:16] → 精确匹配
  │     └── L2: 向量余弦距离 ≤ 0.05 → 语义匹配
  ├── [ContextRewriter.rewrite()]            # 条件执行：has_pronouns=true（正则检测，零 LLM 成本）
  ├── StrategyRouter.route(query)            # 意图分类+复杂度评分→策略列表
  ├── [NormalizeRewriter.rewrite()]          # 条件执行：strategy in list
  ├── [TermAlignRewriter.rewrite()]          # 条件执行：strategy in list
  ├── [ExpandRewriter.rewrite()]             # 条件执行：strategy in list
  ├── ExactTermProtector.restore(result)      # 占位符还原
  ├── Postprocessor.evaluate(rewrites[])     # 质量评分+丢弃/回溯
  ├── CacheManager.store(query, result)      # 写入缓存
  └── AuditTrail.record(trace)               # 审计日志
```

**替代方案**：将各个组件分散为独立函数，在 SearchService 中直接编排。
**拒绝理由**：破坏 SearchService 的单一职责——SearchService 应专注于检索+生成编排，不应了解重写内部组件。单一入口更利于测试和后续升级（如 Phase 3 的异步双通道）。

### 2. LLM 调用策略：复用 ChatAdapter 基础设施，独立配置

**选择**：QueryRewriter 内部创建独立的 ChatAdapter 实例（使用专用的 QueryRewriteConfig），复用现有的重试、错误处理逻辑。所有重写 Prompt 调用共享同一个 ChatAdapter 实例。

**替代方案**：
- A) 直接用 openai SDK 调用——需要重新实现重试、错误处理，背离 DRY 原则
- B) 复用 SearchService 注入的 ChatAdapter——配置混在一起，无法独立调参

**理由**：ChatAdapter 已提供完善的重试、超时处理、错误封装。独立实例允许 QueryRewriter 使用与回答生成不同的 model/temperature/max_tokens 配置（例如用更轻量的模型减少延迟、更低温度确保输出稳定）。重写模块的 LLM 调用失败不应影响后续回答生成。

**关键配置：**
```python
# 重写模块独立配置，默认继承 ChatAdapter 的连接参数
QUERY_REWRITE_MODEL: str = "qwen3.5-plus"       # 默认与 chat_model 相同
QUERY_REWRITE_TEMPERATURE: float = 0.1           # 低温度确保输出稳定、可预测
QUERY_REWRITE_MAX_TOKENS: int = 512              # 重写输出较短
QUERY_REWRITE_TIMEOUT: float = 5.0               # 重写超时更短，避免阻塞检索
QUERY_REWRITE_API_BASE_URL: str = ""             # 为空时复用 document_embedding_api_base_url 或 chat_api_base_url
```

### 3. 策略路由与执行：两阶段 LLM 调用（分类→执行）

**选择**：先通过正则检测指代词（零 LLM 成本），若有指代词则先执行上下文融合（1 次调用），再进行意图分类+复杂度评分（1 次调用），最后根据结果选择性地执行重写策略（0-3 次调用）。简单查询（complexity ≤ 2, factual）直接跳过重写。

**路由规则：**
| 条件 | 策略 |
|---|---|
| complexity ≤ 2 且 intent ∈ {factual, chitchat} | 跳过重写（direct） |
| intent = ambiguous | 扩展重述 |
| complexity 3-5 | 规范重述 + 术语对齐 |
| complexity ≥ 6 | 规范重述 + 术语对齐 + 扩展重述（本阶段不使用 HyDE/Multi-Query） |

**策略执行模型**：

路由决策产出策略列表后，执行阶段遵循以下规则（在 ``_do_rewrite()`` 中实现）：

1. **并行执行非依赖策略**：normalize 和 term_align 无依赖关系，当管线剩余预算 ≥ 16s（每个策略最低 8s）时，通过 ``asyncio.gather`` 并行执行，两者接收相同的当前查询作为输入。并行块（Step 4a）必须在串行块（Step 4b）之前执行，确保 normalize 的结果能作为 expand 的输入。
2. **策略优先级动态调整**：预算紧张（无法并行）时，策略按优先级降序串行执行：``normalize (0) > term_align (1) > expand (2)``。高优先级策略的输出作为低优先级策略的输入。
3. **硬超时兜底**：每个策略通过 ``asyncio.wait_for`` 施加硬超时（``strategy_timeout``，默认 30s）。单策略超时后仅丢弃该策略，其余策略继续执行——超时隔离保证单个慢策略不会阻塞管线。
4. **预算感知**：每个策略执行前检查管线剩余时间预算，预算 < 2s 时跳过后续所有策略。

**替代方案**：单次 LLM 调用完成分类和重写——无法做分层跳过，简单查询也会产生不必要的 LLM 调用。
**理由**：分层调用遵循"低成本策略优先"原则，避免为简单查询浪费计算资源。指代词检测通过正则实现（零 LLM 成本），避免了对含指代词的查询进行两次分类（先分类→消解→再分类）的浪费——含指代词的查询必须在消解后才能准确分类，因此先消解再分类一次即可。不含指代词的简单查询在分类阶段即可被门控拦截，后续零 LLM 调用。并行执行利用 normalize 和 term_align 的独立性减少端到端延迟；优先级排序确保预算紧张时最高价值的策略优先执行；硬超时防止单策略卡死拖垮整个管线。

### 4. 精确词保护：纯本地实现，零 LLM 成本

**选择**：使用正则匹配（版本号、IP、全大写缩写、驼峰命名、路径/URL）+ 可配置的自定义词汇表，在 LLM 重写前将保护词替换为占位符（`[[TERM_0]]`），重写完成后还原。不依赖 LLM 进行术语识别。

**实现要点：**
- 匹配顺序：先正则规则集，再自定义词汇表（词汇表优先级高于正则，防止误匹配）
- 占位符使用 `[[TERM_N]]` 格式，选择 LLM 不会自然生成的分隔符
- 保护词映射通过线程局部存储传递，不进入 LLM 上下文

**理由**：LLM 识别技术术语存在不确定性（可能漏识别或过度识别）。正则+词汇表确定性高、零延迟、零 token 成本。参考 LangChain 的 `ProtectedTermsTransformer` 模式。

### 5. 缓存架构：模块一（会话绑定精确缓存）+ 模块二（跨会话语义缓存）

**选择**：使用 Python 内存 LRU 实现两级缓存：模块一的会话绑定 L1 精确匹配缓存，以及模块二的跨会话 L2 语义相似缓存与连续重复检测（意图检测）。不引入 Redis/外部依赖。

#### 模块一：会话内 L1 精确匹配缓存

```
L1: 复合键缓存 —— key = "{session_id}:{normalized_query_hash}"
    - 缓存 Key 绑定会话 ID：不同会话的相同问题不共享缓存（上下文不同）
    - 精确匹配：规范化后 Query 字符串完全一致时命中
    - LLM 调用：否，直接返回缓存的答案，节省 Token 和延迟
```

**规范化规则**：
- 去除首尾空白
- 将连续空白字符折叠为单个空格
- Unicode NFC 标准化
- 不做大小写折叠（中文无意义，英文术语大小写可能承载语义差异如 "US" vs "us"）

**会话 ID 来源**（优先级降序）：
1. ``SearchRequest.session_id``：前端显式传入（推荐）
2. ``history`` 哈希派生：对对话历史中 user/assistant 的 role+content 序列进行 SHA-256 哈希
3. 固定默认值 ``"__default__"``：当无 session_id 且无 history 时

#### 模块二：跨会话 L2 语义缓存 + 意图检测（连续重复检测）

```
L2: 语义向量缓存 —— key = quantize(query_vector)
    - 缓存 Key 不依赖 SessionID，基于语义向量检索（L2 语义缓存）
    - 触发逻辑：仅当相似度 > 0.95（极高阈值）时考虑命中
      因为"对话历史不同"，微小的语义偏差都可能导致答案错误
    - LLM 调用：不要直接返回原始 Answer！必须经过一层"上下文相关性校验"
      如果缓存的答案依赖于特定的历史背景（例如"基于刚才的代码，修复方案是..."），
      则绝对不能跨会话复用
    - 关键处理：只有当缓存的答案是通用知识时，才允许跨会话复用
      （如"公司报销流程是..."、"Python 列表推导式语法是..."）
```

**请求去重**：100ms 时间窗口内，通过 `asyncio.Event` 实现等待相同查询的第一个请求完成，后续请求复用结果。去重键为 ``{session_id}:{query_hash}``，与 L1 缓存键一致。

**替代方案**：
- A) Redis——Phase 1 引入不必要的运维依赖，单机部署场景下内存缓存更简单可靠
- B) 仅 L1 精确缓存——模块二 L2 语义缓存对口语化同义表达的高频场景有价值，但需要极高阈值和上下文校验
- C) 不绑定会话 ID——不同会话的上下文不同，相同查询可能对应不同答案，不绑定会导致错误复用

**理由**：模块一精确缓存覆盖"同一对话中重复提问"的常见场景（如用户反复确认信息）。模块二负责语义缓存 + 意图检测（连续重复检测），在后续阶段处理跨对话复用和用户不满意重新生成的场景。

#### 动态 TTL 策略

缓存条目按内容类型采用差异化 TTL，避免"一刀切"导致的内存浪费或过早失效：

| 内容类型 | TTL | 判定方式 | 理由 |
|---------|-----|---------|------|
| **通用知识** (`general_knowledge`) | **30 分钟** (`QUERY_REWRITE_CACHE_TTL_GENERAL_KNOWLEDGE`) | L2 上下文相关性校验通过（答案不依赖特定对话历史）的缓存条目 | 通用知识（如"报销流程"、"Python 语法"）跨会话复用价值高，适当延长 TTL |
| **上下文依赖** (`context_dependent`) | **5 分钟** (`QUERY_REWRITE_CACHE_TTL_CONTEXT_DEPENDENT`) | L2 校验判定答案依赖特定历史背景（如"基于刚才的代码"）的条目——仅限当前会话 L1 复用，不进入 L2 跨会话缓存 | 依赖上下文的答案在对话结束后快速失效，避免占用内存；短 TTL 覆盖同一对话内的回看场景 |
| **搜索结果缓存** (`search_result`) | **10 分钟** (`QUERY_REWRITE_CACHE_TTL_SEARCH`) | 语义搜索结果（向量检索结果 + LLM 回答）缓存条目 | 搜索结果时效性介于通用知识和上下文依赖之间，10 分钟平衡新鲜度和命中率 |
| **零向量** | **不缓存** | 查询向量化后为零向量（全零向量）的查询 | 零向量通常是 embedding API 失败或空输入的产物，无语义价值，缓存无意义且可能污染语义检索结果 |

**TTL 判定流程**：
```
CacheManager.store(query, result)
  │
  ├── 零向量检查 → 直接跳过，不写入任何缓存
  ├── 通用知识标记 → L2 TTL = 30min，写入 L2
  └── 上下文依赖标记 → L1 TTL = 5min，仅写 L1，不写 L2
```

所有 TTL 均可通过环境变量独立配置，以支持不同场景的调优需求。

#### 知识库指纹（Fingerprint）机制

**问题**：当用户上传新文档、删除旧文档或修改文档内容后，知识库的语义空间发生变化。基于旧知识库生成的缓存答案可能不再准确（例如旧文档中的流程已更新）。当前 L2 语义缓存仅基于查询向量相似度匹配，不感知知识库版本变化，存在返回过时答案的风险。

**方案**：引入知识库指纹（`kb_fingerprint`）——一个反映当前知识库状态的摘要哈希：

```
kb_fingerprint = SHA256(
    sorted([
        doc_id + ":" + updated_at.isoformat()
        for doc in active_documents
    ])
)[:16]
```

**工作原理**：
1. **计算时机**：每次缓存读写时，从数据库查询当前所有活跃文档的 `(id, updated_at)` 列表，计算指纹。指纹计算开销极低（仅查询文档元数据，不扫描内容）。
2. **写入缓存**：`CacheManager.store()` 将当前 `kb_fingerprint` 作为缓存条目的元数据字段一并存储。
3. **读取缓存**：`CacheManager.lookup_l2()` 命中语义相似条目后，**额外校验**缓存条目的 `kb_fingerprint` 是否与当前指纹一致：
   - 一致 → 缓存有效，继续上下文相关性校验
   - 不一致 → **缓存失效**，丢弃该条目（惰性删除），记录 `l2_fingerprint_mismatch` 事件，回退到正常重写管线
4. **指纹变更触发范围**：仅影响 L2 跨会话缓存。L1 精确缓存（会话绑定，TTL 短）不受指纹机制影响——同一会话内知识库不可能在 5-30 分钟内发生变更。

**与 file-upload-storage 的协同**：`file-upload-storage` 模块已实现的 `checksum_sha256` 内容去重机制为本功能提供了数据基础——文档的 `updated_at` 字段在每次上传/替换时更新，指纹随之变化，无需额外修改上传模块。

**配置**：
```
QUERY_REWRITE_CACHE_FINGERPRINT_ENABLED = true   # 指纹机制开关
```

#### 跨会话 L2 缓存的知识库版本感知

在已有 L2 语义缓存跨会话支持的基础上，增加知识库版本感知层：

```
L2 缓存命中判定流程（更新后）：
  query_vector
    │
    ├── 1. 向量余弦距离 ≤ 0.05（语义相似）    ← 原有逻辑
    ├── 2. kb_fingerprint 匹配                  ← 新增：知识库版本感知
    ├── 3. 上下文相关性校验（LLM 轻量判断）     ← 原有逻辑
    └── 4. TTL 未过期（按内容类型动态判定）     ← 新增：动态 TTL
```

只有以上 4 层校验全部通过，L2 缓存才返回命中结果。任一校验失败均回退到正常重写管线。这保证了跨会话复用的缓存答案既语义相关、又版本有效、又上下文安全、又未过期。

#### 性能优化：写入时抽样清理

**问题**：内存 LRU 缓存在长期运行中会积累大量过期条目（TTL 已过期但未被访问的条目）。传统方案是后台定时任务扫描清理，但这会引入后台线程管理复杂度。

**方案**：采用**写入时抽样清理（Write-Time Sampling Cleanup）**——在每次缓存写入时，以概率 P（默认 10%，通过 `QUERY_REWRITE_CACHE_SAMPLING_CLEANUP_RATIO` 配置）触发一次轻量清理扫描：

```
CacheManager.store(query, result):
    cache[key] = entry
    
    if random() < QUERY_REWRITE_CACHE_SAMPLING_CLEANUP_RATIO:  # 默认 0.1
        _cleanup_expired()        # 扫描并移除 TTL 过期条目
        _cleanup_stale_fingerprint()  # 扫描并移除指纹不匹配的条目
```

**清理策略**：
- **TTL 过期清理**：遍历缓存条目，移除 `now - created_at > ttl` 的条目（按条目自身的动态 TTL 判定）
- **指纹过期清理**：移除 `entry.kb_fingerprint != current_fingerprint` 的条目
- **上限保护**：单次清理最多扫描 `QUERY_REWRITE_CACHE_MAX_CLEANUP_SCAN`（默认 500）个条目，防止大规模缓存时清理阻塞写入路径
- **清理耗时**：遍历 500 条目的清理耗时 < 1ms，对写入延迟影响可忽略

**替代方案**：后台定时线程扫描清理。
**拒绝理由**：引入线程管理复杂度、与 asyncio 事件循环的协调成本、多 worker 部署时的重复清理。写入时抽样清理利用写入操作自然分布的时间点，概率性地维持缓存健康度，零额外线程开销。

### 6. 质量评估与回溯：改写安全网

**选择**：采用**三层递进式安全网**（从快到慢、从廉价到昂贵）：

1. **确定性预检查（零 LLM 成本）**：
   - **关键词留存检查**：使用 2-gram 中文分词（双字滑动窗口）+ 拉丁字母单词提取，过滤常见停用词后，通过子串包含判定（``token in rewritten_text``）计算留存率。相比逐字 n-gram 集合交集法，分词后匹配能正确识别"基本"/"操作"等有意义 token，避免"本操"等噪声。
   - **分层阈值**：按意图类型采用不同的关键词留存率阈值。``procedural`` / ``chitchat`` / ``ambiguous`` 允许更低留存率（0.50–0.55），因为补全、规范化本身就是策略目标；``factual`` 使用更高阈值（0.80）防止事实类查询变形；其他意图使用默认值（0.70）。
   - **长度比例检查**：改写长度 / 原始长度 < 0.3 或 > 5.0 → 标记可疑，降低评估通过阈值。

2. **LLM 质量评估（5 维成对比较评分）**：
   - 提示词采用成对比较框架（"改写是否优于原始查询？请对比评分"）而非仅绝对评分——LLM 在成对比较中判断更一致（参考 Chatbot Arena / LMSYS 评测方法）。
   - 5 维度：语义保留度、清晰度提升、信息增量、术语准确性、可检索性。
   - `semantic_preservation < 3` → 自动丢弃（硬约束）。
   - `total_score < 15` → 触发**单次回溯**（最多 1 次，升级策略重新改写）。二次失败直接丢弃，不再重试——避免无限回溯导致延迟爆炸。

3. **降级兜底**：质量评估本身超时或失败时，保守接受改写结果（避免因评估器故障丢弃有效改写）。
  4. **单策略 normalize 降级快速路径**：当仅执行 ``normalize`` 一个策略且确定性预检查失败时，不丢弃结果——接受为 ``quality_fallback``。normalize 只是清理/补全，不应因关键词留存率不足而丢弃其输出。

**理由**：LLM 改写存在"越改越差"的风险——表达更流畅但丢失了关键语义（如将 "JVM Full GC 频繁触发" 改写为 "Java 性能问题" 丢失了 GC 的精确概念）。纯 LLM 质量评估存在"用 LLM 评判 LLM"的循环问题，因此补充确定性预检查作为第一道防线（零成本、零偏差）。成对比较提示词比绝对评分更可靠，因为 LLM 在"判断哪个更好"任务中比"给绝对分数"任务中表现更稳定。分层阈值承认不同意图的改写目标不同——procedural 的补全规范化本身就是目标，不应与 factual 的事实保留使用同一标准。单策略 normalize 快速路径避免清理/补全类改写因形式化预检被误杀。

### 7. 审计日志：仅 structlog 文件输出，不持久化数据库

**选择**：通过 `get_logger(__name__)` 获取 structlog logger，在 `query_rewrite_complete` 事件中输出完整审计信息。**不创建数据库表，不写入数据库**，审计日志仅存在于日志文件中。

**理由**：查询重写日志是性能/质量分析用途，不需要事务性持久化。structlog 已配置了 TraceFilter（注入 trace_id）和文件输出（10MB 轮转 × 5 保留），满足可观测性需求。避免引入不必要的数据库依赖和 migration 成本。后续如需长期持久化分析，可接入 ELK/ClickHouse 消费日志文件，不影响模块架构。

### 8. 前端组件：独立 RewritePanel，集成到 ChatArea

**选择**：创建独立的 `RewritePanel.vue` 组件，在 `ChatArea.vue` 中渲染于 AnswerPanel 上方。组件通过 props 接收 `rewrite_info`，自行管理折叠状态。

**替代方案**：将改写信息嵌入 AnswerPanel——UI 臃肿，违反单一职责。
**理由**：独立组件便于测试、便于后续升级（如异步 SSE 更新）、风格与现有 PromptPreview/ResultsPanel 一致。遵循 knowra v2.0 设计系统规范。

### 9. Prompt 管理：三层降级 + 版本追踪（改进"硬编码"方案）

**原始风险项**：
> Prompt 模板硬编码在策略类中，后续可通过环境变量或配置文件覆盖；审计日志记录每次重写的输入/输出/质量分数，支持数据驱动的 Prompt 迭代。

**评估结论**：该方案核心思路（代码默认值 + 可覆盖 + 审计日志驱动迭代）是可行的，但「环境变量覆盖」部分存在实际可用性问题——多行 Prompt 模板（含换行符、JSON 示例、Markdown 格式）放入环境变量极难维护。以下方案保留原始方案的优点，同时解决其缺陷。

#### 三层 Prompt 降级加载

```
启动时 PromptLoader.load(strategy_name)
    │
    ├── 第 1 层: 环境变量精确覆盖（紧急热修复）
    │   QUERY_REWRITE_PROMPT_PATH=prompts/rewrite_prompts.yaml
    │   QUERY_REWRITE_PROMPT_NORMALIZE="自定义模板..."
    │   优先级最高，但仅用于紧急情况（不含新行的短路径）
    │
    ├── 第 2 层: YAML Prompt Catalog 文件（运维友好）
    │   backend/prompts/rewrite_prompts.yaml
    │   包含每个 Prompt 的版本号、文本、元数据
    │   启动时加载 → 覆盖代码默认值
    │   支持非开发人员修改、Git 追踪变更历史
    │
    └── 第 3 层: 代码默认值（始终可用）
       各策略类中的 DEFAULT_PROMPT_TEMPLATE 常量
       保证系统零配置即可运行
```

#### Prompt Catalog 文件格式

```yaml
# backend/prompts/rewrite_prompts.yaml
version: "1.0"
prompts:
  intent_classification:
    version: "1.2.0"
    description: "意图分类 + 复杂度评分"
    template: |
      你是一个查询意图分类器。分析用户查询，输出 JSON 格式的分类结果。
      ...
  normalize:
    version: "1.0.0"
    description: "规范化重述——口语转书面"
    template: |
      你是一个查询规范化助手...
  # ... 其余策略
```

#### Prompt 版本注入审计日志

仅 **本次调用阶段实际使用** 的、且在 YAML Catalog 中显式配置了非默认版本的 Prompt，其版本号才会注入审计日志（`prompt_versions: {intent_classification: "1.2.0", normalize: "1.0.0"}`）。两个约束缺一不可：

1. **本次调用实际使用**：例如一次 `rewrite()` 只调用了 `intent_classification` + `normalize`，则审计日志的 `prompt_versions` 中只出现这两个，不会出现 `expand`、`term_align` 等未使用的条目。
2. **YAML Catalog 显式配置**：代码默认版本**不**出现在 `prompt_versions` 中——其缺失即为信号："该策略使用了系统默认版本"。

`PromptLoader.all_versions(filter_names=used_names)` 支持按实际使用的名称过滤，`filter_names=None` 时返回全部目录条目（用于调试和健康检查）。避免在每条审计日志中写入冗余的默认版本信息或未使用策略的版本信息，支持对比不同版本 Prompt 下的质量分数变化，真正实现数据驱动的 Prompt 迭代。

#### Prompt 启动验证

`PromptLoader` 在启动时自动验证所有已加载的模板是否包含必需的占位符变量（`{query}`, `{history}`, `{protected_terms}` 等），缺少必需变量时启动失败并给出明确错误信息。

#### 为什么选择 YAML 而非 .env 或 JSON

| 格式 | 多行文本 | 注释支持 | 非开发者友好 | 格式字符串安全 |
|------|---------|---------|-------------|---------------|
| `.env` | ❌ 需要 `\n` 转义 | ❌ | ❌ | ❌ `{}` 与大括号冲突 |
| JSON | ❌ 需要 `\n` 转义 | ❌ | ❌ | ❌ `{}` 与占位符冲突 |
| YAML | ✅ 原生多行 `|` | ✅ `#` | ✅ | ✅ |
| TOML | ✅ 原生多行 `'''` | ✅ `#` | ✅ | ✅ |

YAML 是多行多段落文本编辑的行业标准格式选择（LangChain、DSPy、PromptFlow 等均采用此格式）。

**选择**：YAML Prompt Catalog + 代码默认值三层降级。

**替代方案**：
- A) 仅环境变量覆盖（原方案）——多行 Prompt 无法实用，`.env` 文件中的 `\n` 转义极易出错
- B) 数据库存储 Prompt + 管理后台——Phase 1 过度工程化，引入不必要的数据库依赖和 UI 工作量
- C) 独立的 Prompt 版本管理平台（如 LangSmith、PromptLayer）——Phase 1 引入外部服务依赖和成本

**理由**：YAML Catalog 在「零运维成本」和「可维护性」之间取得最佳平衡。Prompt 变更可以通过编辑一个文件完成，Git diff 清晰可读，不增加外部依赖，不引入新的基础设施。三层降级保证紧急热修复、日常迭代、零配置场景都有对应路径。

### Decision 10: RAG 回答生成的可靠性保障机制

**决策**：在 RAG 管线的 LLM 回答生成环节引入五层可靠性保障机制：关闭 SDK 内部重试由业务层统一管理、搜推分离超时策略、生成快速失败降级返回、流式生成首 token 超时检测、以及 ChatCircuitBreaker 熔断器。

**背景**：RAG 回答生成（SearchService 中调用 ChatAdapter 生成 AI 回答）是整个搜索链路的最终环节，其稳定性和延迟直接影响用户体验。当前存在以下风险：
- OpenAI SDK 默认 `max_retries=2`，与业务层自有的指数退避重试叠加导致超时放大
- 搜索（向量检索）和生成（LLM 回答）共享相同的超时和重试配置，LLM 延迟会阻塞快速检索结果的返回
- LLM 超时后缺少兜底策略，用户可能长时间等待后看到错误而非部分有效结果
- 无流式生成能力，用户需等待完整的 LLM 回复后才能看到内容
- LLM 持续故障时缺乏自动熔断保护，故障请求反复消耗配额和资源

**实现方案**：

1. **关闭 SDK 内部重试**：`ChatAdapter.__init__()` 中 `AsyncOpenAI(max_retries=0)`，将重试逻辑完全收归业务层。业务层重试策略（指数退避 + jitter + 429 Retry-After 支持）相比 SDK 默认重试具有更精确的错误分类（仅对可重试错误如 429/5xx 重试，4xx 不重试）和抗惊群的 jitter 机制。避免 SDK 层 × 业务层双重重试导致不可控的延迟积累。

2. **搜推分离超时策略**：搜索和生成使用独立的超时和重试参数：
   - `chat_request_timeout=15s`：单次 LLM 生成调用超时（区别于通用的 `request_timeout=60s`）
   - `chat_max_retries=1`：业务层仅重试 1 次，总等待上限 30s
   - 搜索（向量检索）超时独立配置，不受 LLM 延迟影响
   - 确保即使 LLM 响应缓慢，检索结果仍可快速返回

3. **LLM 快速失败 + 降级返回**：SearchService 中将 `_generate_answer()` 调用包装在 `asyncio.wait_for(timeout=20s)` 安全网中：
   - 超时或失败时返回降级 SearchResponse
   - `generation_error` 字段描述失败原因（如 "LLM generation timeout after 20s"）
   - `answer` 返回友好提示文案（如 "AI 回答生成超时，请稍后重试或优化查询后重新搜索"）
   - `answer_tokens=0` 且 `chat_model` 仍然返回以反映配置
   - `results` 字段正常返回检索结果（不因生成失败而丢弃检索结果）
   - 核心原则：**搜索结果优先可用，AI 回答尽力而为**

4. **流式生成 + 首 token 超时**：新增 `ChatAdapter.generate_async()` 基于 `stream=True` 的异步生成方法：
   - `chat_first_token_timeout=10s`：若 10s 内未收到首个 token 则判定服务不可用并快速失败
   - 流式接收过程中连接中断或超时同样触发降级
   - 避免用户长时间等待无响应的 LLM 请求
   - 积累到完整内容后返回 `ChatResult`（与同步 generate() 接口一致）
   - 内部通过 `_iter_stream_with_first_timeout()` 实现：首个 chunk 使用 `asyncio.wait_for` 超时监控，后续 chunk 无超时限制

5. **ChatCircuitBreaker 熔断器**：新增独立于查询重写的 LLM 生成熔断器：
   - `ChatCircuitBreaker` 独立追踪 LLM 生成失败计数
   - 连续失败 N 次（配置项 `CHAT_CIRCUIT_BREAKER_THRESHOLD`，默认 5）后自动熔断
   - 冷却期（`CHAT_CIRCUIT_BREAKER_COOLDOWN_SECONDS`，默认 60s）内跳过 LLM 调用直接返回降级响应
   - 冷却期满后进入半开状态，允许 1 次探测请求通过：成功 → 恢复（关闭熔断），失败 → 重新断开
   - 熔断时返回的降级响应中 `generation_error` 描述为 "AI 回答生成暂时不可用（已熔断），请稍后重试"
   - 配置项 `CHAT_CIRCUIT_BREAKER_ENABLED`（默认 true）可全局关闭熔断逻辑
   - 与查询重写熔断器（`QueryRewriteCircuitBreaker`）共享 `CircuitBreaker` 基类但独立追踪状态

**配置项**：
| 配置项 | 默认值 | 说明 |
|---|---|---|
| CHAT_REQUEST_TIMEOUT | 15.0 | 单次生成调用超时（秒），与通用 request_timeout 分离 |
| CHAT_MAX_RETRIES | 1 | 业务层生成重试次数（SDK 已关闭内部重试） |
| CHAT_FIRST_TOKEN_TIMEOUT | 10.0 | 流式生成首 token 超时（秒），超时判定服务不可用 |
| CHAT_CIRCUIT_BREAKER_ENABLED | true | 生成熔断器开关 |
| CHAT_CIRCUIT_BREAKER_THRESHOLD | 5 | 连续失败 N 次后熔断 |
| CHAT_CIRCUIT_BREAKER_COOLDOWN_SECONDS | 60 | 熔断冷却时间（秒） |

**考虑过的替代方案**：
- A) 保持 SDK 默认重试 + 业务层重试：拒绝——双重重试导致超时不可控，故障场景下延迟累积至分钟级
- B) 统一超时（search 和 chat 使用同一个 timeout）：拒绝——无法解耦检索和生成两个独立阶段，LLM 延迟会阻塞检索结果
- C) 熔断器仅覆盖查询重写：不够——LLM 生成同样是外部依赖，故障时需同等保护
- D) 使用同步 `generate()` 而非流式 `generate_async()`：不够——无法感知服务响应延迟，用户需等待完整超时后才能得知服务不可用

**理由**：五层机制构成递进式防护网——SDK 零重试避免延迟不可控 → 搜推分离保证检索独立 → 降级返回保证部分结果可用 → 首 token 超时快速检测故障 → 熔断器避免持续冲击。每层独立生效且向后兼容（熔断和降级逻辑始终生效，不影响未配置流式生成的已有部署）。

## Risks / Trade-offs

- **[延迟增加] 重写模块增加 1-4 次 LLM 调用，P50 延迟增加 ~200-400ms（缓存命中时）至 ~2-4s（全部调用未命中时）**。
  实际延迟取决于 LLM API 响应时间和调用次数。当前项目使用云端 API（`qwen3.5-plus` via `newapi.bytcloud.org`），单次 LLM 往返约 300-800ms，最坏情况下（意图分类 + 上下文融合 + 规范重述 + 术语对齐 + 扩展重述 + 质量评估共 6 次调用）可能达到 2-5s。
  缓解措施（按优先级排序）：
  1. **指代词检测作为零成本第一道门控**：正则检测指代词（零 LLM 成本），无指代词时仅需 1 次意图分类 LLM 调用即可决定是否跳过后续所有重写。complexity ≤ 2 且 intent ∈ {factual, chitchat} 时直接返回原始查询，后续 0 次调用。有指代词时先执行上下文融合（1 次调用），再分类路由——含指代词的查询（如"它怎么配置"）原本就无法独立理解，必须先消解。
  2. **L1/L2 两级缓存**：精确匹配（SHA256）+ 语义匹配（余弦距离 ≤ 0.05）两级缓存，目标命中率 30%+。缓存命中时仅 1 次 LLM 调用（意图分类不在缓存范围内——见下文）。
  3. **微批请求去重**：100ms 时间窗口内相同查询合并，减少并发 LLM 调用。
  4. **流水线级超时保护**：整个 QueryRewriter.rewrite() 设置总超时（`QUERY_REWRITE_PIPELINE_TIMEOUT`，默认 3s），超时后丢弃未完成的重写，使用原始查询继续检索。
  5. **（Phase 4）异步双通道**：原始查询立即用于检索，重写结果异步缓存供后续请求使用——首字节延迟零增加。
  **重要澄清**：意图分类调用本身不在缓存范围内，因为缓存的是重写结果而非分类结果。意图分类始终执行（1 次轻量 LLM 调用），但其延迟是整个流程中最低的（只需返回 JSON 分类结果，token 数少）。上下文融合仅在检测到指代词时执行（正则预检，零成本），含指代词的查询在消解后才能被准确分类，因此先消解再分类一次到位，无需二次分类。

- **[改写质量不稳定] LLM 可能越改越差——流畅但丢失关键语义**。
  三层安全网（从快到慢、从廉价到昂贵）：
  1. **确定性预检查（零 LLM 成本）**：
     - **关键词留存检查**：使用 2-gram 中文分词（双字滑动窗口）+ 子串包含判定计算留存率。留存率 < 意图对应的分层阈值 → 自动丢弃，不进入 LLM 评估。分层阈值：procedural/chitchat/ambiguous → 0.50–0.55；factual → 0.80；其他意图 → 0.70。
     - **长度比例检查**：改写长度 < 原始长度 × 0.3 或 > 原始长度 × 5 → 标记为可疑，降低 LLM 评估通过阈值。
     - **单策略 normalize 快速路径**：仅 normalize 策略执行且预检失败时，接受为 quality_fallback（normalize 只是清理/补全，不改变语义）。
  2. **LLM 质量评估（5 维评分）**：
     - `semantic_preservation < 3` → 自动丢弃（硬约束）
     - `total_score < 15` → 触发单次回溯（最多 1 次，升级策略重新改写），二次失败则丢弃
     - 评估采用**成对比较提示词**（"改写是否优于原始查询？"）而非仅绝对评分——LLM 在成对比较任务中判断更一致（参考 Chatbot Arena / LMSYS 评测方法）
  3. **降级兜底**：任何阶段丢弃改写 → 回退使用原始查询，对用户透明。原始查询至少能产生有意义的检索结果（已验证的基线）。
  **已知局限**：质量评估器本身也是 LLM，存在评估偏差。通过结构化 JSON 输出 + 明确评分锚点（每个分值对应具体行为描述）提高一致性。确定性预检查（第 1 层）不受此局限影响。

- **[LLM 依赖增加] 重写模块依赖独立 ChatAdapter 实例，增加 API 调用量和故障面**。
  当前项目 ChatAdapter 已提供完善的重试（指数退避 + jitter + 429 Retry-After 支持）、超时处理、错误封装。重写模块复用这些能力，但需要额外保障：
  1. **静默降级**（已设计）：LLM 调用失败 → 跳过重写，使用原始查询，不阻塞用户请求。`ChatAPIError` 被捕获后记录日志并返回原始查询。
  2. **熔断器（Circuit Breaker）**：连续 N 次重写失败（建议 5 次）后，自动禁用重写模块 `QUERY_REWRITE_CIRCUIT_BREAKER_COOLDOWN_SECONDS` 秒（建议 30s），期间所有请求使用原始查询。冷却期满后进入半开状态，允许 1 次探测请求通过——成功则恢复，失败则重新断开。推荐使用 `pybreaker` 库或手动实现（避免新增依赖）。
  3. **独立 API Key 支持**：`QUERY_REWRITE_API_KEY` 配置项（为空时复用 `CHAT_API_KEY`）。允许重写使用不同 API Key，避免与主对话共享速率限制配额。
  4. **独立超时控制**：`QUERY_REWRITE_TIMEOUT`（默认 5s）显著短于 `CHAT_REQUEST_TIMEOUT`（60s），确保重写失败快速返回而不影响整体搜索延迟。
  5. **Token 成本透明**：每次重写的 token 消耗记录在审计日志中（`llm_calls` 数组，含每次调用的 prompt_tokens/completion_tokens）。单次典型重写约消耗 500-2000 tokens（含 prompt + completion），按 qwen3.5-plus 公开定价约 $0.001-0.004/次。配合缓存命中率 30%+，实际日均成本可控。
- **[缓存一致性问题] 内存 LRU 缓存在多进程部署时不共享** → 单机 uvicon 部署场景下不影响；后续多 worker 部署时可通过策略控制（L1/L2 使用独立随机时间偏移避免惊群）+ Phase 4 引入 Redis L3 缓存
- **[Prompt 维护成本] 6 个重写 Prompt 模板需要持续迭代优化** → 采用三层降级 Prompt 管理方案（详见 Decision 9）：代码默认值保证零配置可用，YAML Prompt Catalog 支持非开发人员编辑和 Git 追踪，环境变量用于紧急热修复。每个 Prompt 版本号注入审计日志，支持对比不同版本下的质量分数变化，实现数据驱动的 Prompt 迭代。启动时自动验证模板占位符是否完整。
- **[过期数据风险] 审计日志仅输出至文件，不持久化到数据库** → 审计日志规模和查询需求有限（日均数百条），文件日志（10MB 轮转 × 5 保留）足够覆盖几天内的分析需求；后续如需长期分析可接入 ELK/ClickHouse

## Migration Plan

**部署步骤：**

1. **添加环境变量**：在 `.env` 和 `.env.example` 中新增 ~30 个 `QUERY_REWRITE_` 前缀的配置项，默认启用
2. **部署后端代码**：新模块通过 DI 注入 SearchService，无需数据库 migration
3. **验证向后兼容**：设置 `QUERY_REWRITE_ENABLED=false` 后系统行为与部署前一致
4. **渐进式灰度**：先设置 `QUERY_REWRITE_ENABLED=true` 观察日志中的改写质量和缓存命中率，确认稳定后全量开启
5. **前端无感升级**：`rewrite_info` 为可选字段，前端组件仅在字段存在时渲染面板，旧版前端自然兼容

**回滚策略：**
- 立即回滚：设置 `QUERY_REWRITE_ENABLED=false` 并重启服务，重写模块被完全绕过
- 部分回滚：通过策略开关单独禁用某个策略（如 `QUERY_REWRITE_STRATEGY_EXPAND=false`），其他策略继续运作
- 前端回滚：删除 RewritePanel 组件引用后构建部署，不影响回答/检索面板

**配置变更（需同步更新 `.env.example`）：**
| 配置项 | 默认值 | 说明 |
|---|---|---|
| QUERY_REWRITE_ENABLED | true | 总开关 |
| QUERY_REWRITE_MODEL | (空，继承 chat_model) | 重写专用模型 |
| QUERY_REWRITE_API_BASE_URL | (空，继承 document_embedding_api_base_url 或 chat_api_base_url) | 重写专用 API 地址 |
| QUERY_REWRITE_API_KEY | (空，继承 chat_api_key) | 重写专用 API Key，为空时复用 CHAT_API_KEY。允许重写使用独立 Key 避免与主对话共享速率限制配额 |
| QUERY_REWRITE_TEMPERATURE | 0.1 | 低温确保输出稳定 |
| QUERY_REWRITE_MAX_TOKENS | 512 | 重写输出上限 |
| QUERY_REWRITE_TIMEOUT | 5.0 | 单次 LLM 调用超时秒数 |
| QUERY_REWRITE_PIPELINE_TIMEOUT | 3.0 | 整个 rewrite() 管线总超时秒数，超时后丢弃未完成的重写，使用原始查询 |
| QUERY_REWRITE_STRATEGY_NORMALIZE | true | 规范重述开关 |
| QUERY_REWRITE_STRATEGY_EXPAND | true | 扩展重述开关 |
| QUERY_REWRITE_STRATEGY_TERM_ALIGN | true | 术语对齐开关 |
| QUERY_REWRITE_SKIP_MAX_COMPLEXITY | 2 | 跳过重写的复杂度阈值 |
| QUERY_REWRITE_CACHE_L1_TTL_SECONDS | 3600 | L1 缓存 TTL |
| QUERY_REWRITE_CACHE_L2_TTL_SECONDS | 21600 | L2 缓存 TTL（默认值，实际按内容类型动态判定） |
| QUERY_REWRITE_CACHE_TTL_GENERAL_KNOWLEDGE | 1800 | 通用知识缓存 TTL（秒），默认 30 分钟 |
| QUERY_REWRITE_CACHE_TTL_CONTEXT_DEPENDENT | 300 | 上下文依赖缓存 TTL（秒），默认 5 分钟 |
| QUERY_REWRITE_CACHE_TTL_SEARCH | 600 | 搜索结果缓存 TTL（秒），默认 10 分钟 |
| QUERY_REWRITE_CACHE_FINGERPRINT_ENABLED | true | 知识库指纹缓存失效开关，关闭后 L2 缓存不校验知识库版本 |
| QUERY_REWRITE_CACHE_SAMPLING_CLEANUP_RATIO | 0.1 | 写入时抽样清理触发概率，0 表示禁用 |
| QUERY_REWRITE_CACHE_MAX_CLEANUP_SCAN | 500 | 单次抽样清理最大扫描条目数 |
| QUERY_REWRITE_QUALITY_MIN_TOTAL_SCORE | 15 | 质量最低通过分 |
| QUERY_REWRITE_QUALITY_KEYWORD_RETENTION_THRESHOLD | 0.7 | 关键词留存率阈值，低于此值自动丢弃改写（零 LLM 成本） |
| QUERY_REWRITE_QUALITY_MAX_BACKTRACK_ATTEMPTS | 1 | 质量不合格时最大回溯重试次数，防止无限回溯 |
| QUERY_REWRITE_DEDUP_WINDOW_MS | 100 | 去重时间窗口 |
| QUERY_REWRITE_PROTECT_TERMS_CUSTOM_LIST | [] | 自定义保护词列表 |
| QUERY_REWRITE_PROMPT_PATH | prompts/rewrite_prompts.yaml | Prompt Catalog 文件路径（相对于工作目录） |
| QUERY_REWRITE_PROMPT_<NAME> | (空) | 单个 Prompt 的环境变量覆盖（紧急热修复，仅建议用于短 Prompt） |
| QUERY_REWRITE_CIRCUIT_BREAKER_THRESHOLD | 5 | 连续失败 N 次后熔断，禁用重写模块 |
| QUERY_REWRITE_CIRCUIT_BREAKER_COOLDOWN_SECONDS | 30 | 熔断冷却时间，期满后半开探测 |

**数据模型影响：** 无。本次变更不新增数据库表、不修改现有表结构、不需要 Alembic migration。

**生命周期说明：** QueryRewriter 及其内部组件为请求作用域（与 SearchService 同生命周期），由 FastAPI DI 在每个请求中创建，请求结束时由 GC 回收。不持有后台任务、线程池、长连接或文件句柄。缓存（内存 dict）在进程重启时自然清空。不适用 graceful shutdown 语义。
