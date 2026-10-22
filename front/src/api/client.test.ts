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
  getRingBuffer: () =>
    ({ push: vi.fn(), size: 0, getAll: () => [] }) as unknown as ReturnType<
      typeof import("../shared/logger").getRingBuffer
    >,
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

// ── 用户体系：统一认证语义 ─────────────────────────────────────────────────

describe("API Client 认证与错误语义", () => {
  afterEach(async () => {
    vi.unstubAllGlobals()
    const { setUnauthorizedHandler } = await import("./client")
    setUnauthorizedHandler(null)
  })

  function jsonResponse(status: number, body: unknown) {
    return {
      ok: status >= 200 && status < 300,
      status,
      json: () => Promise.resolve(body),
    }
  }

  // 测试：所有请求都携带会话 Cookie（credentials: include），以便 HttpOnly 会话随请求发送。
  it("apiGet 与 apiPostForm 携带 credentials: include", async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse(200, {}))
    vi.stubGlobal("fetch", fetchMock)
    const { apiGet, apiPostForm } = await import("./client")

    await apiGet("/users/me")
    await apiPostForm("/uploads", new FormData())

    expect(fetchMock.mock.calls[0][1].credentials).toBe("include")
    expect(fetchMock.mock.calls[1][1].credentials).toBe("include")
  })

  // 测试：非 2xx 响应抛出 ApiError，保留 HTTP 状态、机器码与后端中文原因。
  it("非 2xx 响应抛出带 status/code/detail 的 ApiError", async () => {
    vi.stubGlobal(
      "fetch",
      vi
        .fn()
        .mockResolvedValue(
          jsonResponse(409, {
            detail: "不能移除最后一位有效管理员",
            code: "last_admin",
          }),
        ),
    )
    const { apiPatchJson, ApiError } = await import("./client")

    const error = await apiPatchJson("/admin/users/u-1", {
      role: "member",
    }).catch((e) => e)

    expect(error).toBeInstanceOf(ApiError)
    expect(error).toMatchObject({
      status: 409,
      code: "last_admin",
      detail: "不能移除最后一位有效管理员",
      message: "不能移除最后一位有效管理员",
    })
  })

  // 测试：FastAPI 默认 422 列表 detail 取第一条 msg 作为可读原因；非 JSON 响应回退到状态码文案。
  it("ApiError 解析 422 列表 detail 与非 JSON 响应", async () => {
    vi.stubGlobal(
      "fetch",
      vi
        .fn()
        .mockResolvedValueOnce(
          jsonResponse(422, {
            detail: [{ msg: "Field required", loc: ["body", "email"] }],
          }),
        )
        .mockResolvedValueOnce({
          ok: false,
          status: 500,
          json: () => Promise.reject(new SyntaxError("not json")),
        }),
    )
    const { apiPostJson } = await import("./client")

    await expect(apiPostJson("/auth/register", {})).rejects.toMatchObject({
      status: 422,
      code: null,
      detail: "Field required",
    })
    await expect(apiPostJson("/auth/register", {})).rejects.toMatchObject({
      status: 500,
      detail: "请求失败：500",
    })
  })

  // 测试：apiPostJson / apiPatchJson 发送 JSON 请求体，204 响应返回 undefined 而不解析正文。
  it("JSON 写请求设置方法、Content-Type 与请求体，204 返回 undefined", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce({
        ok: true,
        status: 204,
        json: () => Promise.reject(new Error("no body")),
      })
      .mockResolvedValueOnce(jsonResponse(200, { id: "u-1" }))
    vi.stubGlobal("fetch", fetchMock)
    const { apiPatchJson, apiPostJson } = await import("./client")

    await expect(apiPostJson("/auth/logout")).resolves.toBeUndefined()
    await expect(
      apiPatchJson("/users/me", { display_name: "新名字" }),
    ).resolves.toEqual({ id: "u-1" })

    const [logoutUrl, logoutInit] = fetchMock.mock.calls[0]
    expect(logoutUrl).toBe("/api/auth/logout")
    expect(logoutInit.method).toBe("POST")
    const [patchUrl, patchInit] = fetchMock.mock.calls[1]
    expect(patchUrl).toBe("/api/users/me")
    expect(patchInit.method).toBe("PATCH")
    expect(patchInit.headers["Content-Type"]).toBe("application/json")
    expect(patchInit.body).toBe(JSON.stringify({ display_name: "新名字" }))
    expect(patchInit.credentials).toBe("include")
  })

  // 测试：业务接口返回 401 时触发统一的会话失效回调，并仍以 ApiError 拒绝。
  it("业务请求 401 触发 unauthorized 回调", async () => {
    vi.stubGlobal(
      "fetch",
      vi
        .fn()
        .mockResolvedValue(
          jsonResponse(401, { detail: "登录已失效", code: "auth_required" }),
        ),
    )
    const { apiGet, setUnauthorizedHandler } = await import("./client")
    const handler = vi.fn()
    setUnauthorizedHandler(handler)

    await expect(apiGet("/parsed-documents")).rejects.toMatchObject({
      status: 401,
    })

    expect(handler).toHaveBeenCalledTimes(1)
  })

  // 测试：/auth/* 与显式跳过的请求（如会话探测 /users/me）返回 401 时不触发全局跳转。
  it("认证接口与 skipAuthRedirect 请求的 401 不触发回调", async () => {
    vi.stubGlobal(
      "fetch",
      vi
        .fn()
        .mockResolvedValue(
          jsonResponse(401, {
            detail: "邮箱或密码错误",
            code: "invalid_credentials",
          }),
        ),
    )
    const { apiGet, apiPostJson, setUnauthorizedHandler } =
      await import("./client")
    const handler = vi.fn()
    setUnauthorizedHandler(handler)

    await expect(
      apiPostJson("/auth/login", { email: "a@b.co", password: "x" }),
    ).rejects.toMatchObject({
      code: "invalid_credentials",
    })
    await expect(
      apiGet("/users/me", { skipAuthRedirect: true }),
    ).rejects.toMatchObject({
      status: 401,
    })

    expect(handler).not.toHaveBeenCalled()
  })

  // 测试：独立 fetch 的模块改用 apiFetch 后同样触发 401 回调（覆盖检索等返回原始 Response 的调用）。
  it("apiFetch 返回原始响应并在 401 时触发回调", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(jsonResponse(401, { code: "auth_required" })),
    )
    const { apiFetch, setUnauthorizedHandler } = await import("./client")
    const handler = vi.fn()
    setUnauthorizedHandler(handler)

    const response = await apiFetch("/search", { method: "POST" })

    expect(response.status).toBe(401)
    expect(handler).toHaveBeenCalledTimes(1)
  })
})
