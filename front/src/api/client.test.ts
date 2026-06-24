import { afterEach, describe, expect, it, vi } from "vitest"
import { apiGet, apiPostForm } from "./client"

// Mock the logger module so client.ts can import it without needing initLogger().
vi.mock("../shared/logger", () => ({
  createLogger: () => ({
    debug: vi.fn(),
    info: vi.fn(),
    warn: vi.fn(),
    error: vi.fn(),
  }),
  getRingBuffer: () => ({ push: vi.fn(), size: 0, getAll: () => [] } as unknown as ReturnType<typeof import("../shared/logger").getRingBuffer>),
}))

// Mock the traceManager to return a stable trace ID.
// Must use the SAME import path as client.ts uses.
vi.mock("../shared/logger/trace-context", () => ({
  traceManager: {
    getTraceId: () => "01JFZ8TEST-TRACE-ID-000000000000",
  },
}))

const TRACE_HEADER = "X-Trace-ID"

describe("API Client X-Trace-ID 注入", () => {
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  describe("13.1 apiGet 调用时请求头包含 X-Trace-ID", () => {
    it("apiGet 请求自动注入 X-Trace-ID 头", async () => {
      const fetchMock = vi.fn().mockResolvedValue({
        ok: true,
        json: () => Promise.resolve({ data: "test" }),
      })
      vi.stubGlobal("fetch", fetchMock)

      await apiGet("/api/users/me")

      expect(fetchMock).toHaveBeenCalledTimes(1)
      const url = fetchMock.mock.calls[0][0]
      const options = fetchMock.mock.calls[0][1]

      expect(url).toContain("/api/users/me")
      expect(options.headers).toBeDefined()

      // Headers can be a Headers object or a plain object.
      const headers =
        options.headers instanceof Headers
          ? Object.fromEntries(options.headers.entries())
          : options.headers

      expect(headers[TRACE_HEADER]).toBe("01JFZ8TEST-TRACE-ID-000000000000")
      expect(headers["Accept"]).toBe("application/json")
    })
  })

  describe("13.1 apiPostForm 调用时请求头包含 X-Trace-ID", () => {
    it("apiPostForm 请求自动注入 X-Trace-ID 头", async () => {
      const fetchMock = vi.fn().mockResolvedValue({
        ok: true,
        json: () => Promise.resolve({ data: "test" }),
      })
      vi.stubGlobal("fetch", fetchMock)

      const formData = new FormData()
      formData.append("file", new Blob(["content"]), "test.txt")

      await apiPostForm("/api/uploads", formData)

      expect(fetchMock).toHaveBeenCalledTimes(1)
      const options = fetchMock.mock.calls[0][1]

      const headers =
        options.headers instanceof Headers
          ? Object.fromEntries(options.headers.entries())
          : options.headers

      expect(headers[TRACE_HEADER]).toBe("01JFZ8TEST-TRACE-ID-000000000000")
    })
  })
})
