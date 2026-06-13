import { afterEach, describe, expect, it, vi } from "vitest"

const CHUNK_JOB_RESPONSE = {
  id: "55555555-5555-5555-5555-555555555555",
  parsed_document_id: "33333333-3333-3333-3333-333333333333",
  owner_user_id: "00000000-0000-0000-0000-000000000001",
  status: "succeeded",
  chunker_name: "docling_hybrid",
  chunker_version: "docling-core",
  chunk_config_json: {
    max_tokens: 512,
    tokenizer_model: "Qwen/Qwen2-7B",
    merge_peers: true,
    repeat_table_header: true,
    inline_text_max_bytes: 2048,
  },
  chunk_count: 2,
  attempt_count: 1,
  started_at: "2026-06-12T00:00:01Z",
  finished_at: "2026-06-12T00:00:02Z",
  error_code: null,
  error_message: null,
  created_at: "2026-06-12T00:00:00Z",
  updated_at: "2026-06-12T00:00:02Z",
}

const CHUNK_RESPONSE = {
  id: "66666666-6666-6666-6666-666666666666",
  chunk_job_id: CHUNK_JOB_RESPONSE.id,
  parsed_document_id: CHUNK_JOB_RESPONSE.parsed_document_id,
  owner_user_id: CHUNK_JOB_RESPONSE.owner_user_id,
  sequence_index: 0,
  text: "Chunk 0",
  contextualized_text: "Course Notes\nChunk 0",
  token_count: 10,
  heading_path: ["Course Notes", "Retrieval"],
  page_numbers: [1],
  chunk_type: "text",
  source_segment_indices: [0],
  metadata: { docling_ref: "#/texts/0" },
  created_at: "2026-06-12T00:00:02Z",
}

async function getDocumentChunkingApi() {
  const modulePath = "./documentChunking"
  return import(/* @vite-ignore */ modulePath)
}

describe("document chunking api", () => {
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  // 测试：分块 API client 读取作业、parsed document 最新作业、分页 chunks 和 chunk 详情时继续使用 /api 前缀。
  it("reads chunk jobs, latest parsed-document chunk job, paginated chunks, and chunk detail", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce({
        ok: true,
        json: () => Promise.resolve(CHUNK_JOB_RESPONSE),
      })
      .mockResolvedValueOnce({
        ok: true,
        json: () =>
          Promise.resolve({
            ...CHUNK_JOB_RESPONSE,
            status: "running",
            finished_at: null,
          }),
      })
      .mockResolvedValueOnce({
        ok: true,
        json: () =>
          Promise.resolve({
            items: [CHUNK_RESPONSE],
            total: 1,
            offset: 0,
            limit: 10,
          }),
      })
      .mockResolvedValueOnce({
        ok: true,
        json: () => Promise.resolve(CHUNK_RESPONSE),
      })
    vi.stubGlobal("fetch", fetchMock)
    const {
      getDocumentChunkJob,
      getLatestParsedDocumentChunkJob,
      getParsedDocumentChunks,
      getDocumentChunk,
    } = await getDocumentChunkingApi()

    await expect(getDocumentChunkJob(CHUNK_JOB_RESPONSE.id)).resolves.toEqual(
      CHUNK_JOB_RESPONSE,
    )
    await expect(
      getLatestParsedDocumentChunkJob(CHUNK_JOB_RESPONSE.parsed_document_id),
    ).resolves.toMatchObject({ status: "running", finished_at: null })
    await expect(
      getParsedDocumentChunks(CHUNK_JOB_RESPONSE.parsed_document_id, {
        offset: 0,
        limit: 10,
      }),
    ).resolves.toMatchObject({ total: 1, offset: 0, limit: 10 })
    await expect(getDocumentChunk(CHUNK_RESPONSE.id)).resolves.toEqual(
      CHUNK_RESPONSE,
    )

    expect(fetchMock.mock.calls.map((call) => call[0])).toEqual([
      "/api/document-chunk-jobs/55555555-5555-5555-5555-555555555555",
      "/api/parsed-documents/33333333-3333-3333-3333-333333333333/chunk-job",
      "/api/parsed-documents/33333333-3333-3333-3333-333333333333/chunks?offset=0&limit=10",
      "/api/document-chunks/66666666-6666-6666-6666-666666666666",
    ])
  })

  // 测试：重新分块会向 parsed document 资源提交 JSON 参数，并保留 202 作业响应。
  it("triggers rechunk with optional config overrides", async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      status: 202,
      json: () =>
        Promise.resolve({
          ...CHUNK_JOB_RESPONSE,
          status: "queued",
          chunk_config_json: {
            ...CHUNK_JOB_RESPONSE.chunk_config_json,
            max_tokens: 256,
            merge_peers: false,
          },
        }),
    })
    vi.stubGlobal("fetch", fetchMock)
    const { rechunkParsedDocument } = await getDocumentChunkingApi()

    await expect(
      rechunkParsedDocument(CHUNK_JOB_RESPONSE.parsed_document_id, {
        max_tokens: 256,
        merge_peers: false,
      }),
    ).resolves.toMatchObject({
      id: CHUNK_JOB_RESPONSE.id,
      status: "queued",
      chunk_config_json: expect.objectContaining({
        max_tokens: 256,
        merge_peers: false,
      }),
    })

    expect(fetchMock).toHaveBeenCalledWith(
      "/api/parsed-documents/33333333-3333-3333-3333-333333333333/rechunk",
      expect.objectContaining({
        method: "POST",
        headers: expect.objectContaining({
          "Content-Type": "application/json",
        }),
        body: JSON.stringify({ max_tokens: 256, merge_peers: false }),
      }),
    )
  })

  // 测试：409 响应会保留已有运行中分块作业，页面可据此禁用重复触发。
  it("preserves running chunk job context from 409 rechunk responses", async () => {
    const conflictPayload = {
      detail: "Document chunk job already running",
      job: {
        ...CHUNK_JOB_RESPONSE,
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
    const { rechunkParsedDocument } = await getDocumentChunkingApi()

    await expect(
      rechunkParsedDocument(CHUNK_JOB_RESPONSE.parsed_document_id),
    ).rejects.toMatchObject({
      status: 409,
      detail: "Document chunk job already running",
      job: conflictPayload.job,
    })
  })
})
