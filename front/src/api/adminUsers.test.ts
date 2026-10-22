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

describe("admin users API", () => {
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  // 测试：分页查询用户列表使用 offset/limit 查询参数。
  it("listUsers 使用 offset 与 limit 分页", async () => {
    const page = { items: [makeUser("admin")], total: 1, offset: 20, limit: 20 }
    const fetchMock = vi
      .fn()
      .mockResolvedValue({
        ok: true,
        status: 200,
        json: () => Promise.resolve(page),
      })
    vi.stubGlobal("fetch", fetchMock)
    const { listUsers } = await import("./adminUsers")

    await expect(listUsers({ offset: 20, limit: 20 })).resolves.toEqual(page)
    expect(fetchMock.mock.calls[0][0]).toBe(
      "/api/admin/users?offset=20&limit=20",
    )
  })

  // 测试：更新用户只提交变更的角色或状态字段。
  it("updateUser 以 PATCH 提交角色或状态", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValue({
        ok: true,
        status: 200,
        json: () => Promise.resolve(makeUser("viewer")),
      })
    vi.stubGlobal("fetch", fetchMock)
    const { updateUser } = await import("./adminUsers")

    await updateUser("user-1", { status: "disabled" })

    const [url, init] = fetchMock.mock.calls[0]
    expect(url).toBe("/api/admin/users/user-1")
    expect(init.method).toBe("PATCH")
    expect(JSON.parse(init.body)).toEqual({ status: "disabled" })
  })
})
