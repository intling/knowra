import { afterEach, describe, expect, it, vi } from "vitest"

// Mock the logger module so client.ts can import it without needing initLogger().
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
    getTraceId: () => "01JFZ8TEST-TRACE-ID-000000000000",
  },
}))

const EMBEDDING_JOB_RESPONSE = {
  id: "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
  chunk_job_id: "55555555-5555-5555-5555-555555555555",
  parsed_document_id: "33333333-3333-3333-3333-333333333333",
  owner_user_id: "00000000-0000-0000-0000-000000000001",
  status: "succeeded",
  embedder_name: "openai_compatible",
  model: "Qwen/Qwen3-Embedding-0.6B",
  dimensions: 1024,
  embedding_count: 2,
  attempt_count: 1,
  started_at: "2026-06-12T00:00:02Z",
  finished_at: "2026-06-12T00:00:03Z",
  error_code: null,
  error_message: null,
  config_json: {
    model: "Qwen/Qwen3-Embedding-0.6B",
    dimensions: 1024,
    batch_size: 100,
    encoding_format: "float",
  },
  created_at: "2026-06-12T00:00:02Z",
  updated_at: "2026-06-12T00:00:03Z",
}

const EMBEDDING_RESPONSE = {
  id: "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb",
  chunk_id: "66666666-6666-6666-6666-666666666666",
  embedding_job_id: EMBEDDING_JOB_RESPONSE.id,
  sequence_index: 0,
  model: "Qwen/Qwen3-Embedding-0.6B",
  dimensions: 1024,
  embedding_json: [0.01234, -0.05678, 0.09123],
  token_count: 10,
  created_at: "2026-06-12T00:00:04Z",
}

const EMBEDDING_PAGE_RESPONSE = {
  items: [EMBEDDING_RESPONSE],
  total: 1,
  offset: 0,
  limit: 50,
}

async function getEmbeddingApi() {
  const modulePath = "./embedding"
  return import(/* @vite-ignore */ modulePath)
}

describe("embedding api client", () => {
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  // 测试：查询单个向量化作业时使用正确的路径和返回数据结构。
  it("reads a single embedding job by id", async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      json: () => Promise.resolve(EMBEDDING_JOB_RESPONSE),
    })
    vi.stubGlobal("fetch", fetchMock)
    const { getDocumentEmbeddingJob } = await getEmbeddingApi()

    await expect(
      getDocumentEmbeddingJob(EMBEDDING_JOB_RESPONSE.id),
    ).resolves.toEqual(EMBEDDING_JOB_RESPONSE)

    expect(fetchMock).toHaveBeenCalledWith(
      "/api/document-embedding-jobs/aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
      expect.objectContaining({
        headers: expect.objectContaining({ Accept: "application/json" }),
      }),
    )
  })

  // 测试：查询分块作业最新的向量化作业使用正确的路径。
  it("reads the latest embedding job for a chunk job", async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      json: () => Promise.resolve(EMBEDDING_JOB_RESPONSE),
    })
    vi.stubGlobal("fetch", fetchMock)
    const { getChunkJobLatestEmbeddingJob } = await getEmbeddingApi()

    await expect(
      getChunkJobLatestEmbeddingJob(
        EMBEDDING_JOB_RESPONSE.chunk_job_id,
      ),
    ).resolves.toEqual(EMBEDDING_JOB_RESPONSE)

    expect(fetchMock).toHaveBeenCalledWith(
      "/api/document-chunk-jobs/55555555-5555-5555-5555-555555555555/embedding-job",
      expect.objectContaining({
        headers: expect.objectContaining({ Accept: "application/json" }),
      }),
    )
  })

  // 测试：分页查询向量结果时路径包含 chunk_job_id 和分页参数。
  it("reads paginated embeddings for a chunk job ordered by sequence_index", async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      json: () => Promise.resolve(EMBEDDING_PAGE_RESPONSE),
    })
    vi.stubGlobal("fetch", fetchMock)
    const { getChunkJobEmbeddings } = await getEmbeddingApi()

    await expect(
      getChunkJobEmbeddings(EMBEDDING_JOB_RESPONSE.chunk_job_id, {
        offset: 0,
        limit: 10,
      }),
    ).resolves.toEqual(EMBEDDING_PAGE_RESPONSE)

    expect(fetchMock).toHaveBeenCalledWith(
      "/api/document-chunk-jobs/55555555-5555-5555-5555-555555555555/embeddings?offset=0&limit=10",
      expect.objectContaining({
        headers: expect.objectContaining({ Accept: "application/json" }),
      }),
    )
  })

  // 测试：使用默认分页参数时不传 offset 和 limit。
  it("uses default pagination when offset and limit are omitted", async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      json: () => Promise.resolve(EMBEDDING_PAGE_RESPONSE),
    })
    vi.stubGlobal("fetch", fetchMock)
    const { getChunkJobEmbeddings } = await getEmbeddingApi()

    await getChunkJobEmbeddings(EMBEDDING_JOB_RESPONSE.chunk_job_id)

    expect(fetchMock).toHaveBeenCalledWith(
      "/api/document-chunk-jobs/55555555-5555-5555-5555-555555555555/embeddings?offset=0&limit=50",
      expect.any(Object),
    )
  })

  // 测试：查询单个 chunk 的向量详情使用正确的路径。
  it("reads a single chunk embedding detail", async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      json: () => Promise.resolve(EMBEDDING_RESPONSE),
    })
    vi.stubGlobal("fetch", fetchMock)
    const { getChunkEmbedding } = await getEmbeddingApi()

    await expect(
      getChunkEmbedding(EMBEDDING_RESPONSE.chunk_id),
    ).resolves.toEqual(EMBEDDING_RESPONSE)

    expect(fetchMock).toHaveBeenCalledWith(
      "/api/document-chunks/66666666-6666-6666-6666-666666666666/embedding",
      expect.objectContaining({
        headers: expect.objectContaining({ Accept: "application/json" }),
      }),
    )
  })

  // 测试：重新向量化成功返回 202 时解析为新创建的作业。
  it("triggers reembed and returns 202 new job", async () => {
    const newJob = {
      ...EMBEDDING_JOB_RESPONSE,
      id: "cccccccc-cccc-cccc-cccc-cccccccccccc",
      status: "queued",
      finished_at: null,
    }
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      status: 202,
      json: () => Promise.resolve(newJob),
    })
    vi.stubGlobal("fetch", fetchMock)
    const { reembedChunkJob } = await getEmbeddingApi()

    await expect(
      reembedChunkJob(EMBEDDING_JOB_RESPONSE.chunk_job_id, {
        model: "Qwen/Qwen3-Embedding-0.6B",
        dimensions: 1024,
      }),
    ).resolves.toMatchObject({
      id: "cccccccc-cccc-cccc-cccc-cccccccccccc",
      status: "queued",
      finished_at: null,
    })

    expect(fetchMock).toHaveBeenCalledWith(
      "/api/document-chunk-jobs/55555555-5555-5555-5555-555555555555/re-embed",
      expect.objectContaining({
        method: "POST",
        headers: expect.objectContaining({
          "Content-Type": "application/json",
        }),
        body: JSON.stringify({
          model: "Qwen/Qwen3-Embedding-0.6B",
          dimensions: 1024,
        }),
      }),
    )
  })

  // 测试：重新向量化不传参数时发送空 JSON 体（使用服务端默认值）。
  it("sends empty body for reembed when no overrides are provided", async () => {
    const newJob = {
      ...EMBEDDING_JOB_RESPONSE,
      id: "cccccccc-cccc-cccc-cccc-cccccccccccc",
      status: "queued",
      finished_at: null,
    }
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      status: 202,
      json: () => Promise.resolve(newJob),
    })
    vi.stubGlobal("fetch", fetchMock)
    const { reembedChunkJob } = await getEmbeddingApi()

    await reembedChunkJob(EMBEDDING_JOB_RESPONSE.chunk_job_id)

    expect(fetchMock).toHaveBeenCalledWith(
      expect.any(String),
      expect.objectContaining({
        body: JSON.stringify({}),
      }),
    )
  })

  // 测试：409 响应返回冲突作业信息，便于调用方展示已有运行中作业。
  it("preserves running job context from 409 conflict responses", async () => {
    const conflictPayload = {
      detail: "Embedding job already running",
      job: {
        ...EMBEDDING_JOB_RESPONSE,
        status: "running",
        finished_at: null,
      },
    }
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({
        ok: false,
        status: 409,
        json: () => Promise.resolve(conflictPayload),
      }),
    )
    const { reembedChunkJob } = await getEmbeddingApi()

    await expect(
      reembedChunkJob(EMBEDDING_JOB_RESPONSE.chunk_job_id),
    ).rejects.toMatchObject({
      status: 409,
      detail: "Embedding job already running",
      job: conflictPayload.job,
    })
  })

  // 测试：503 响应表示服务关闭中，返回可读错误信息。
  it("rejects with 503 when server is shutting down", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({
        ok: false,
        status: 503,
        json: () => Promise.resolve({ detail: "Service unavailable" }),
      }),
    )
    const { reembedChunkJob } = await getEmbeddingApi()

    await expect(
      reembedChunkJob(EMBEDDING_JOB_RESPONSE.chunk_job_id),
    ).rejects.toMatchObject({
      status: 503,
      detail: "服务正在关闭，请稍后重试",
    })
  })

  // 测试：其他非 2xx/409/503 错误通过 parseErrorResponse 解析为 EmbeddingApiError。
  it("rejects with parsed error for non-2xx responses other than 409/503", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({
        ok: false,
        status: 404,
        json: () =>
          Promise.resolve({ detail: "Document chunk job not found" }),
      }),
    )
    const { reembedChunkJob } = await getEmbeddingApi()

    await expect(
      reembedChunkJob(EMBEDDING_JOB_RESPONSE.chunk_job_id),
    ).rejects.toMatchObject({
      status: 404,
      detail: "Document chunk job not found",
    })
  })
})
