import { afterEach, describe, expect, it, vi } from "vitest"

import type { RewriteInfo, RewrittenQuery } from "./search"

// Mock the logger module — lazy init pattern in search.ts will create a real logger.
vi.mock("../shared/logger", () => ({
  createLogger: () => ({
    debug: vi.fn(),
    info: vi.fn(),
    warn: vi.fn(),
    error: vi.fn(),
  }),
  getRingBuffer: () =>
    ({
      push: vi.fn(),
      size: 0,
      getAll: () => [],
    }) as unknown as ReturnType<
      typeof import("../shared/logger").getRingBuffer
    >,
}))

// Mock the traceManager to return a stable trace ID.
vi.mock("../shared/logger/trace-context", () => ({
  traceManager: {
    getTraceId: () => "01JFZ8TEST-TRACE-ID-SEARCH00000000",
  },
}))

const SEARCH_RESPONSE = {
  query: "大模型在医疗领域的应用有哪些？",
  query_embedding_preview: [0.0123, -0.0456, 0.0789, 0.0012, -0.0345],
  embedding_model: "Qwen/Qwen3-Embedding-4B",
  embedding_dimensions: 2560,
  top_k: 5,
  total_searched: 100,
  searched_document_count: 3,
  search_time_ms: 45.2,
  results: [
    {
      rank: 1,
      score: 0.12,
      chunk_id: "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
      parsed_document_id: "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb",
      document_name: "医疗AI综述.pdf",
      sequence_index: 3,
      text: "大模型在医疗领域有广泛的应用，包括辅助诊断、药物研发、医学影像分析等方面。近年来，随着深度学习技术的快速发展...",
      contextualized_text: "本文综述了大模型在医疗领域的应用现状...",
      token_count: 150,
      heading_path: ["第三章", "3.1 大模型应用"],
      page_numbers: [12, 13],
    },
    {
      rank: 2,
      score: 0.25,
      chunk_id: "cccccccc-cccc-cccc-cccc-cccccccccccc",
      parsed_document_id: "dddddddd-dddd-dddd-dddd-dddddddddddd",
      document_name: "AI医疗案例研究.pdf",
      sequence_index: 7,
      text: "在实际临床应用中，大模型辅助诊断系统已经展现出显著的效能提升...",
      contextualized_text: "案例研究部分详细分析了多个医院的实践...",
      token_count: 120,
      heading_path: ["案例研究", "医院A"],
      page_numbers: [45],
    },
  ],
  answer:
    "根据提供的文档内容，大模型在医疗领域的应用主要包括以下几个方面：\n\n1. **辅助诊断**：大模型可以分析医学影像和病历数据...\n2. **药物研发**：加速药物筛选和分子设计...",
  answer_tokens: {
    prompt_tokens: 500,
    completion_tokens: 200,
    total_tokens: 700,
  },
  chat_model: "qwen3.5-plus",
  prompt_messages: [
    {
      role: "system",
      content:
        "你是一个知识库助手。请仅根据提供的上下文回答问题，如果上下文不足以回答，请明确说明。回答时请注明信息来源。",
    },
    {
      role: "user",
      content: "## 上下文信息\n\n### 来源1: 医疗AI综述.pdf...\n\n## 问题\n\n大模型在医疗领域的应用有哪些？",
    },
  ],
  chat_config_snapshot: {
    api_base_url: "https://newapi.bytcloud.org",
    model: "qwen3.5-plus",
    temperature: 0.1,
    max_tokens: 1024,
  },
  generation_error: null,
}

/** Full RewriteInfo payload matching the Python RewriteInfo Pydantic model. */
const REWRITE_INFO_PAYLOAD: RewriteInfo = {
  original_query: "它怎么用",
  rewritten_queries: [
    { query: "Python 怎么使用", strategy: "context_fusion" },
    { query: "Python 如何使用", strategy: "normalize" },
  ] as RewrittenQuery[],
  strategies_used: ["context_fusion", "normalize"],
  rewrite_time_ms: 45.2,
  cache_hit: false,
  rewrite_model: "qwen3.5-plus",
}

async function getSearchApi() {
  const modulePath = "./search"
  return import(/* @vite-ignore */ modulePath)
}

describe("search api client", () => {
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  // ── 正常响应解析 ────────────────────────────────────────────────

  it("parses normal search response with all fields", async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      json: () => Promise.resolve(SEARCH_RESPONSE),
    })
    vi.stubGlobal("fetch", fetchMock)
    const { searchChunks } = await getSearchApi()

    const result = await searchChunks({
      query: "大模型在医疗领域的应用有哪些？",
      top_k: 5,
    })

    expect(result).toEqual(SEARCH_RESPONSE)
    expect(result.results).toHaveLength(2)
    expect(result.results[0].rank).toBe(1)
    expect(result.results[0].document_name).toBe("医疗AI综述.pdf")
    expect(result.query).toBe("大模型在医疗领域的应用有哪些？")
    expect(result.search_time_ms).toBe(45.2)

    // Verify the POST request was sent correctly
    expect(fetchMock).toHaveBeenCalledWith(
      "/api/search",
      expect.objectContaining({
        method: "POST",
        headers: expect.objectContaining({
          "Content-Type": "application/json",
          Accept: "application/json",
        }),
        body: JSON.stringify({
          query: "大模型在医疗领域的应用有哪些？",
          top_k: 5,
        }),
      }),
    )
  })

  it("uses default top_k=5 when not specified", async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      json: () => Promise.resolve(SEARCH_RESPONSE),
    })
    vi.stubGlobal("fetch", fetchMock)
    const { searchChunks } = await getSearchApi()

    await searchChunks({ query: "测试查询" })

    expect(fetchMock).toHaveBeenCalledWith(
      "/api/search",
      expect.objectContaining({
        body: JSON.stringify({ query: "测试查询", top_k: 5 }),
      }),
    )
  })

  // ── answer 字段解析 ──────────────────────────────────────────────

  it("parses answer field with markdown content", async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      json: () => Promise.resolve(SEARCH_RESPONSE),
    })
    vi.stubGlobal("fetch", fetchMock)
    const { searchChunks } = await getSearchApi()

    const result = await searchChunks({ query: "测试" })

    expect(result.answer).toContain("大模型在医疗领域的应用")
    expect(result.answer_tokens).toEqual({
      prompt_tokens: 500,
      completion_tokens: 200,
      total_tokens: 700,
    })
    expect(result.chat_model).toBe("qwen3.5-plus")
  })

  it("parses answer_tokens as null when chat is disabled", async () => {
    const disabledResponse = {
      ...SEARCH_RESPONSE,
      answer: "AI 回答生成功能未启用，请联系管理员配置对话模型。以下为检索到的相关内容。",
      answer_tokens: null,
      chat_model: null,
      generation_error: "Chat generation is disabled",
    }
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      json: () => Promise.resolve(disabledResponse),
    })
    vi.stubGlobal("fetch", fetchMock)
    const { searchChunks } = await getSearchApi()

    const result = await searchChunks({ query: "测试" })

    expect(result.answer).toContain("未启用")
    expect(result.answer_tokens).toBeNull()
    expect(result.chat_model).toBeNull()
    expect(result.generation_error).toBe("Chat generation is disabled")
  })

  // ── HTTP 错误处理 ────────────────────────────────────────────────

  it("throws SearchApiError on HTTP 4xx with detail from backend", async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: false,
      status: 404,
      json: () =>
        Promise.resolve({
          detail:
            "知识库中暂无任何已向量化的文档。请先上传文档并完成向量化后再提问。",
        }),
    })
    vi.stubGlobal("fetch", fetchMock)

    // We need to import the error class to test it
    const { searchChunks } = await getSearchApi()

    await expect(
      searchChunks({ query: "测试查询" }),
    ).rejects.toMatchObject({
      status: 404,
      detail:
        "知识库中暂无任何已向量化的文档。请先上传文档并完成向量化后再提问。",
    })
  })

  it("throws SearchApiError on HTTP 422 validation error", async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: false,
      status: 422,
      json: () =>
        Promise.resolve({
          detail: [
            {
              type: "string_too_short",
              loc: ["body", "query"],
              msg: "String should have at least 1 character",
            },
          ],
        }),
    })
    vi.stubGlobal("fetch", fetchMock)
    const { searchChunks } = await getSearchApi()

    await expect(
      searchChunks({ query: "" }),
    ).rejects.toMatchObject({
      status: 422,
      detail: "请求失败：422",
    })
  })

  it("throws SearchApiError on HTTP 502 bad gateway", async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: false,
      status: 502,
      json: () =>
        Promise.resolve({
          detail: "Failed to embed query",
        }),
    })
    vi.stubGlobal("fetch", fetchMock)
    const { searchChunks } = await getSearchApi()

    await expect(
      searchChunks({ query: "测试" }),
    ).rejects.toMatchObject({
      status: 502,
      detail: "Failed to embed query",
    })
  })

  // ── 网络错误处理 ──────────────────────────────────────────────────

  it("throws SearchApiError on network fetch failure", async () => {
    const networkError = new TypeError("Failed to fetch")
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(networkError))
    const { searchChunks } = await getSearchApi()

    await expect(
      searchChunks({ query: "测试查询" }),
    ).rejects.toMatchObject({
      status: 0,
      detail: "Failed to fetch",
    })
  })

  it("throws SearchApiError on connection refused (TypeError)", async () => {
    const connectionError = new TypeError(
      "fetch failed: connect ECONNREFUSED",
    )
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(connectionError))
    const { searchChunks } = await getSearchApi()

    await expect(
      searchChunks({ query: "测试查询" }),
    ).rejects.toMatchObject({
      status: 0,
      detail: "fetch failed: connect ECONNREFUSED",
    })
  })

  // ── rewrite_info 字段解析（Phase 1） ───────────────────────────────

  it("parses rewrite_info with basic info when rewriting not enabled", async () => {
    const basicRewriteInfo: RewriteInfo = {
      original_query: "测试查询",
      rewritten_queries: [] as RewrittenQuery[],
      strategies_used: [],
      rewrite_time_ms: 0.0,
      cache_hit: false,
    }
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      json: () => Promise.resolve({ ...SEARCH_RESPONSE, rewrite_info: basicRewriteInfo }),
    })
    vi.stubGlobal("fetch", fetchMock)
    const { searchChunks } = await getSearchApi()

    const result = await searchChunks({ query: "测试查询" })

    // rewrite_info is always present (never null)
    expect(result.rewrite_info).not.toBeNull()
    expect(result.rewrite_info.original_query).toBe("测试查询")
    expect(result.rewrite_info.rewritten_queries).toHaveLength(0)
    expect(result.rewrite_info.rewrite_time_ms).toBe(0.0)
  })

  it("parses complete rewrite_info with all fields present", async () => {
    const responseWithRewrite = {
      ...SEARCH_RESPONSE,
      rewrite_info: REWRITE_INFO_PAYLOAD,
    }
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      json: () => Promise.resolve(responseWithRewrite),
    })
    vi.stubGlobal("fetch", fetchMock)
    const { searchChunks } = await getSearchApi()

    const result = await searchChunks({ query: "它怎么用" })

    expect(result.rewrite_info).not.toBeNull()
    const ri = result.rewrite_info!
    expect(ri.original_query).toBe("它怎么用")
    expect(ri.rewritten_queries).toHaveLength(2)
    expect(ri.strategies_used).toEqual(["context_fusion", "normalize"])
    expect(ri.rewrite_time_ms).toBe(45.2)
    expect(ri.cache_hit).toBe(false)
  })

  it("parses RewrittenQuery with query and strategy fields", async () => {
    const responseWithRewrite = {
      ...SEARCH_RESPONSE,
      rewrite_info: REWRITE_INFO_PAYLOAD,
    }
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      json: () => Promise.resolve(responseWithRewrite),
    })
    vi.stubGlobal("fetch", fetchMock)
    const { searchChunks } = await getSearchApi()

    const result = await searchChunks({ query: "它怎么用" })

    const queries = result.rewrite_info!.rewritten_queries
    expect(queries).toHaveLength(2)

    // First rewritten query
    expect(queries[0].query).toBe("Python 怎么使用")
    expect(queries[0].strategy).toBe("context_fusion")

    // Second rewritten query
    expect(queries[1].query).toBe("Python 如何使用")
    expect(queries[1].strategy).toBe("normalize")
  })

  it("parses RewrittenQuery with strategy=null gracefully", async () => {
    const payloadNoStrategy: RewriteInfo = {
      original_query: "测试查询",
      rewritten_queries: [
        { query: "改写测试", strategy: null },
      ] as RewrittenQuery[],
      strategies_used: [],
      rewrite_time_ms: 5.0,
      cache_hit: true,
    }
    const responseWithRewrite = {
      ...SEARCH_RESPONSE,
      rewrite_info: payloadNoStrategy,
    }
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      json: () => Promise.resolve(responseWithRewrite),
    })
    vi.stubGlobal("fetch", fetchMock)
    const { searchChunks } = await getSearchApi()

    const result = await searchChunks({ query: "测试查询" })

    expect(result.rewrite_info!.rewritten_queries[0].strategy).toBeNull()
    expect(result.rewrite_info!.cache_hit).toBe(true)
    expect(result.rewrite_info!.rewrite_time_ms).toBe(5.0)
  })

  it("parses rewrite_info with rewritten_queries as empty array", async () => {
    const payloadEmptyQueries: RewriteInfo = {
      original_query: "简单查询",
      rewritten_queries: [] as RewrittenQuery[],
      strategies_used: [],
      rewrite_time_ms: 0.0,
      cache_hit: true,
    }
    const responseWithRewrite = {
      ...SEARCH_RESPONSE,
      rewrite_info: payloadEmptyQueries,
    }
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      json: () => Promise.resolve(responseWithRewrite),
    })
    vi.stubGlobal("fetch", fetchMock)
    const { searchChunks } = await getSearchApi()

    const result = await searchChunks({ query: "简单查询" })

    expect(result.rewrite_info!.rewritten_queries).toHaveLength(0)
    expect(result.rewrite_info!.strategies_used).toEqual([])
    expect(result.rewrite_info!.cache_hit).toBe(true)
  })

  it("rewrite_info field types match expected schema", async () => {
    const responseWithRewrite = {
      ...SEARCH_RESPONSE,
      rewrite_info: REWRITE_INFO_PAYLOAD,
    }
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      json: () => Promise.resolve(responseWithRewrite),
    })
    vi.stubGlobal("fetch", fetchMock)
    const { searchChunks } = await getSearchApi()

    const result = await searchChunks({ query: "它怎么用" })
    const ri = result.rewrite_info!

    // Field type assertions
    expect(typeof ri.original_query).toBe("string")
    expect(Array.isArray(ri.rewritten_queries)).toBe(true)
    expect(Array.isArray(ri.strategies_used)).toBe(true)
    expect(typeof ri.rewrite_time_ms).toBe("number")
    expect(typeof ri.cache_hit).toBe("boolean")

    // RewrittenQuery sub-type assertions
    const rq = ri.rewritten_queries[0]
    expect(typeof rq.query).toBe("string")
    expect(typeof rq.strategy).toBe("string")
  })

  // ── rewrite_info error 字段 ──────────────────────────────────────────

  it("parses rewrite_info with error field when rewrite failed", async () => {
    const failedRewriteInfo: RewriteInfo = {
      original_query: "失败查询",
      rewritten_queries: [] as RewrittenQuery[],
      strategies_used: [],
      rewrite_time_ms: 12.3,
      cache_hit: false,
      error: "Query rewriter timeout",
    }
    const responseWithRewriteError = {
      ...SEARCH_RESPONSE,
      rewrite_info: failedRewriteInfo,
    }
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      json: () => Promise.resolve(responseWithRewriteError),
    })
    vi.stubGlobal("fetch", fetchMock)
    const { searchChunks } = await getSearchApi()

    const result = await searchChunks({ query: "失败查询" })

    expect(result.rewrite_info).not.toBeNull()
    expect(result.rewrite_info!.error).toBe("Query rewriter timeout")
    // generation_error should still be null (rewrite failure ≠ generation failure)
    expect(result.generation_error).toBeNull()
    expect(result.answer).toBe(SEARCH_RESPONSE.answer)
  })

  it("parses rewrite_info with error=null when rewrite succeeded", async () => {
    const responseWithRewrite = {
      ...SEARCH_RESPONSE,
      rewrite_info: REWRITE_INFO_PAYLOAD,
    }
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      json: () => Promise.resolve(responseWithRewrite),
    })
    vi.stubGlobal("fetch", fetchMock)
    const { searchChunks } = await getSearchApi()

    const result = await searchChunks({ query: "它怎么用" })

    // error field should be undefined (not present) for successful rewrites
    expect(result.rewrite_info!.error).toBeUndefined()
  })

  // ── history 参数传递 ──────────────────────────────────────────────

  it("passes history to backend when provided in SearchRequest", async () => {
    const basicRewriteInfo: RewriteInfo = {
      original_query: "它怎么用",
      rewritten_queries: [] as RewrittenQuery[],
      strategies_used: [],
      rewrite_time_ms: 0.0,
      cache_hit: false,
    }
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      json: () => Promise.resolve({ ...SEARCH_RESPONSE, rewrite_info: basicRewriteInfo }),
    })
    vi.stubGlobal("fetch", fetchMock)
    const { searchChunks } = await getSearchApi()

    const history = [
      { role: "user", content: "什么是 Python？" },
      { role: "assistant", content: "Python 是一种编程语言。" },
    ]

    await searchChunks({ query: "它怎么用", history })

    const body = JSON.parse(fetchMock.mock.calls[0][1].body)
    expect(body.history).toEqual(history)
    expect(body.history).toHaveLength(2)
  })

  it("does not include history in request body when not provided", async () => {
    const basicRewriteInfo: RewriteInfo = {
      original_query: "普通查询",
      rewritten_queries: [] as RewrittenQuery[],
      strategies_used: [],
      rewrite_time_ms: 0.0,
      cache_hit: false,
    }
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      json: () => Promise.resolve({ ...SEARCH_RESPONSE, rewrite_info: basicRewriteInfo }),
    })
    vi.stubGlobal("fetch", fetchMock)
    const { searchChunks } = await getSearchApi()

    await searchChunks({ query: "普通查询" })

    const body = JSON.parse(fetchMock.mock.calls[0][1].body)
    expect(body.query).toBe("普通查询")
    expect(body.top_k).toBe(5)
    // history should not appear in the serialized body at all
    expect(body).not.toHaveProperty("history")
  })
})
