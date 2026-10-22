import { afterEach, describe, expect, it, vi } from "vitest"

import { makeUser } from "../__tests__/fixtures/users"

vi.mock("../shared/logger", () => ({
  createLogger: () => ({
    debug: vi.fn(),
    info: vi.fn(),
    warn: vi.fn(),
    error: vi.fn(),
  }),
  getRingBuffer: () => ({ push: vi.fn(), size: 0, getAll: () => [] }),
}))

function ok(body: unknown, status = 200) {
  return { ok: true, status, json: () => Promise.resolve(body) }
}

describe("auth API", () => {
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  // 测试：登录以 JSON 提交邮箱与密码到 /api/auth/login，并返回用户。
  it("login 提交邮箱密码并返回当前用户", async () => {
    const user = makeUser("member")
    const fetchMock = vi.fn().mockResolvedValue(ok(user))
    vi.stubGlobal("fetch", fetchMock)
    const { login } = await import("./auth")

    await expect(
      login({ email: "member@example.com", password: "Knowra-Pass-2026" }),
    ).resolves.toEqual(user)

    const [url, init] = fetchMock.mock.calls[0]
    expect(url).toBe("/api/auth/login")
    expect(init.method).toBe("POST")
    expect(JSON.parse(init.body)).toEqual({
      email: "member@example.com",
      password: "Knowra-Pass-2026",
    })
  })

  // 测试：注册只提交显示名、邮箱和密码，不提交角色等服务端控制字段。
  it("register 只提交公开注册字段", async () => {
    const fetchMock = vi.fn().mockResolvedValue(ok(makeUser("member"), 201))
    vi.stubGlobal("fetch", fetchMock)
    const { register } = await import("./auth")

    await register({
      display_name: "小张",
      email: "z@example.com",
      password: "Knowra-Pass-2026",
    })

    const [url, init] = fetchMock.mock.calls[0]
    expect(url).toBe("/api/auth/register")
    expect(JSON.parse(init.body)).toEqual({
      display_name: "小张",
      email: "z@example.com",
      password: "Knowra-Pass-2026",
    })
  })

  // 测试：退出请求服务端撤销会话（POST /api/auth/logout，204）。
  it("logout 请求服务端撤销会话", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValue({
        ok: true,
        status: 204,
        json: () => Promise.reject(new Error()),
      })
    vi.stubGlobal("fetch", fetchMock)
    const { logout } = await import("./auth")

    await expect(logout()).resolves.toBeUndefined()
    expect(fetchMock.mock.calls[0][0]).toBe("/api/auth/logout")
    expect(fetchMock.mock.calls[0][1].method).toBe("POST")
  })
})
