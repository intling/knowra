import { afterEach, expect, it, vi } from "vitest"
const logger = vi.hoisted(() => ({
  debug: vi.fn(),
  info: vi.fn(),
  warn: vi.fn(),
  error: vi.fn(),
}))
vi.mock("../shared/logger", () => ({
  createLogger: () => logger,
  getRingBuffer: () => ({ push: vi.fn() }),
}))
afterEach(() => {
  vi.unstubAllGlobals()
  vi.clearAllMocks()
})
// 验证列表查询携带筛选但日志不保存邮箱，异常保留响应 trace ID 便于排查。
it("账号筛选参数、日志脱敏与 trace", async () => {
  const fetch = vi
    .fn()
    .mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => ({ items: [] }),
    })
  vi.stubGlobal("fetch", fetch)
  const api = await import("./adminUsers")
  await api.listUsers({
    q: "private@example.com",
    role: "member",
    status: "active",
    offset: 20,
  })
  const url = new URL(fetch.mock.calls[0][0], "http://test")
  expect(url.searchParams.get("q")).toBe("private@example.com")
  expect(url.searchParams.get("role")).toBe("member")
  expect(JSON.stringify(logger.debug.mock.calls)).not.toContain(
    "private@example.com",
  )
  fetch.mockResolvedValue({
    ok: false,
    status: 503,
    json: async () => ({ code: "unavailable", detail: "暂不可用" }),
    headers: new Headers({ "X-Trace-ID": "trace-can-copy" }),
  })
  await expect(api.listUsers()).rejects.toMatchObject({
    traceId: "trace-can-copy",
  })
})
// 验证额度与撤销统一使用 Cookie API client 与严格契约。
it("额度与会话操作契约", async () => {
  const fetch = vi
    .fn()
    .mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => ({ revoked_count: 2 }),
    })
  vi.stubGlobal("fetch", fetch)
  const api = await import("./adminUsers")
  await api.setChatLimit("a/b", null)
  expect(fetch.mock.calls[0][0]).toContain("/a%2Fb/chat-limit")
  expect(fetch.mock.calls[0][1].method).toBe("PUT")
  expect(JSON.parse(fetch.mock.calls[0][1].body)).toEqual({
    hourly_limit: null,
  })
  await api.revokeUserSessions("one")
  expect(fetch.mock.calls[1][0]).toContain("/one/revoke-sessions")
})
