import { afterEach, describe, expect, it, vi } from "vitest"

import { uploadFile } from "./uploads"

const UPLOAD_RESPONSE = {
  id: "11111111-1111-1111-1111-111111111111",
  owner_user_id: "00000000-0000-0000-0000-000000000001",
  original_filename: "course-notes.pdf",
  content_type: "application/pdf",
  byte_size: 5,
  storage_key:
    "uploads/00000000-0000-0000-0000-000000000001/11111111-1111-1111-1111-111111111111/original.pdf",
  checksum_sha256: "a".repeat(64),
  status: "stored",
  error_message: null,
  deleted_at: null,
  created_at: "2026-05-25T00:00:00Z",
  updated_at: "2026-05-25T00:00:00Z",
}

describe("uploadFile", () => {
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  // 测试：上传文件时会通过 /api/uploads 提交 multipart 表单，并且不会把 owner_user_id 放入请求体。
  it("uploads multipart form data without submitting owner_user_id", async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      json: () => Promise.resolve(UPLOAD_RESPONSE),
    })
    vi.stubGlobal("fetch", fetchMock)

    const file = new File(["notes"], "course-notes.pdf", {
      type: "application/pdf",
    })

    await expect(uploadFile(file)).resolves.toEqual(UPLOAD_RESPONSE)

    expect(fetchMock).toHaveBeenCalledOnce()
    const [url, init] = fetchMock.mock.calls[0]
    expect(url).toBe("/api/uploads")
    expect(init.method).toBe("POST")
    expect(init.headers).toBeUndefined()
    expect(init.body).toBeInstanceOf(FormData)
    expect(init.body.get("file")).toBe(file)
    expect(init.body.has("owner_user_id")).toBe(false)
  })

  // 测试：后端返回错误响应时，uploadFile 会抛出包含后端 detail 的可诊断错误。
  it("throws a diagnostic error from backend error responses", async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: false,
      status: 413,
      json: () => Promise.resolve({ detail: "File size exceeds max_upload_bytes" }),
    })
    vi.stubGlobal("fetch", fetchMock)

    const file = new File(["large"], "large.txt", {
      type: "text/plain",
    })

    await expect(uploadFile(file)).rejects.toThrow("File size exceeds max_upload_bytes")
  })
})
