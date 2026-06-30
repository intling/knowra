import { afterEach, describe, expect, it, vi } from "vitest"

const JOB_RESPONSE = {
  id: "22222222-2222-2222-2222-222222222222",
  uploaded_file_id: "11111111-1111-1111-1111-111111111111",
  owner_user_id: "00000000-0000-0000-0000-000000000001",
  status: "queued",
  parser_name: "docling",
  parser_version: null,
  attempt_count: 0,
  started_at: null,
  finished_at: null,
  error_code: null,
  error_message: null,
  created_at: "2026-06-05T00:00:00Z",
  updated_at: "2026-06-05T00:00:00Z",
}

const PARSED_DOCUMENT_RESPONSE = {
  id: "33333333-3333-3333-3333-333333333333",
  uploaded_file_id: "11111111-1111-1111-1111-111111111111",
  parse_job_id: "22222222-2222-2222-2222-222222222222",
  owner_user_id: "00000000-0000-0000-0000-000000000001",
  source_checksum_sha256: "a".repeat(64),
  markdown_storage_key: "parsed/u/f/j/content.md",
  text_storage_key: "parsed/u/f/j/content.txt",
  docling_json_storage_key: "parsed/u/f/j/docling.json",
  title: "Lecture",
  page_count: 1,
  metadata: { parser: "docling" },
  segment_count: 1,
  created_at: "2026-06-05T00:00:00Z",
}

async function getDocumentParsingApi() {
  const modulePath = "./documentParsing"
  return import(/* @vite-ignore */ modulePath)
}

describe("document parsing api", () => {
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  // 测试：创建解析作业会调用 POST /api/uploads/{upload_id}/parse 并返回状态模型。
  it("creates a document parse job for an uploaded file", async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      json: () => Promise.resolve(JOB_RESPONSE),
    })
    vi.stubGlobal("fetch", fetchMock)
    const { createDocumentParseJob } = await getDocumentParsingApi()

    await expect(
      createDocumentParseJob("11111111-1111-1111-1111-111111111111"),
    ).resolves.toEqual(JOB_RESPONSE)

    expect(fetchMock).toHaveBeenCalledWith(
      "/api/uploads/11111111-1111-1111-1111-111111111111/parse",
      expect.objectContaining({ method: "POST" }),
    )
  })

  // 测试：解析作业、解析结果和结构片段读取 API 继续使用 /api 前缀。
  it("reads parse jobs, parsed documents, and paginated segments", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce({
        ok: true,
        json: () => Promise.resolve(JOB_RESPONSE),
      })
      .mockResolvedValueOnce({
        ok: true,
        json: () => Promise.resolve(PARSED_DOCUMENT_RESPONSE),
      })
      .mockResolvedValueOnce({
        ok: true,
        json: () =>
          Promise.resolve({
            items: [
              {
                id: "44444444-4444-4444-4444-444444444444",
                parsed_document_id: "33333333-3333-3333-3333-333333333333",
                owner_user_id: "00000000-0000-0000-0000-000000000001",
                sequence_index: 0,
                segment_type: "paragraph",
                page_no: 1,
                heading_path: ["Lecture"],
                text: "Body",
                metadata: { docling_ref: "#/texts/0" },
                created_at: "2026-06-05T00:00:00Z",
              },
            ],
            total: 1,
            offset: 0,
            limit: 20,
          }),
      })
    vi.stubGlobal("fetch", fetchMock)
    const {
      getDocumentParseJob,
      getParsedDocumentForUpload,
      getParsedDocumentSegments,
    } = await getDocumentParsingApi()

    await expect(getDocumentParseJob(JOB_RESPONSE.id)).resolves.toEqual(JOB_RESPONSE)
    await expect(
      getParsedDocumentForUpload(PARSED_DOCUMENT_RESPONSE.uploaded_file_id),
    ).resolves.toEqual(PARSED_DOCUMENT_RESPONSE)
    await expect(
      getParsedDocumentSegments(PARSED_DOCUMENT_RESPONSE.id, { offset: 0, limit: 20 }),
    ).resolves.toMatchObject({ total: 1, offset: 0, limit: 20 })

    expect(fetchMock.mock.calls.map((call) => call[0])).toEqual([
      "/api/document-parse-jobs/22222222-2222-2222-2222-222222222222",
      "/api/uploads/11111111-1111-1111-1111-111111111111/parsed-document",
      "/api/parsed-documents/33333333-3333-3333-3333-333333333333/segments?offset=0&limit=20",
    ])
  })

  // 测试：409 重复运行中作业会保留已有作业和上传文档信息，便于页面展示。
  it("preserves duplicate running job context from 409 responses", async () => {
    const conflictPayload = {
      detail: "Document parse job already running",
      job: { ...JOB_RESPONSE, status: "running" },
      uploaded_file: {
        id: "11111111-1111-1111-1111-111111111111",
        original_filename: "course-notes.pdf",
        content_type: "application/pdf",
        byte_size: 128,
        status: "stored",
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
    const { createDocumentParseJob } = await getDocumentParsingApi()

    await expect(
      createDocumentParseJob("11111111-1111-1111-1111-111111111111"),
    ).rejects.toMatchObject({
      status: 409,
      detail: "Document parse job already running",
      job: conflictPayload.job,
      uploadedFile: conflictPayload.uploaded_file,
    })
  })
})
