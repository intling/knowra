import { afterEach, describe, expect, it, vi } from "vitest"

import { makeUser } from "../__tests__/fixtures/users"
import { changeMyPassword, getCurrentUser, updateMyProfile } from "./users"

vi.mock("../shared/logger", () => ({
  createLogger: () => ({
    debug: vi.fn(),
    info: vi.fn(),
    warn: vi.fn(),
    error: vi.fn(),
  }),
  getRingBuffer: () => ({ push: vi.fn(), size: 0, getAll: () => [] }),
}))

describe("users API", () => {
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  // 测试：获取当前用户使用配置的 API 基础路径、JSON 接收头并携带会话 Cookie，返回角色与权限。
  it("requests the current user through the configured API base path", async () => {
    const user = makeUser("viewer")
    const fetchMock = vi
      .fn()
      .mockResolvedValue({
        ok: true,
        status: 200,
        json: () => Promise.resolve(user),
      })
    vi.stubGlobal("fetch", fetchMock)

    await expect(getCurrentUser()).resolves.toEqual(user)
    expect(fetchMock).toHaveBeenCalledWith("/api/users/me", {
      credentials: "include",
      headers: {
        Accept: "application/json",
        "X-Trace-ID": expect.any(String) as string,
      },
    })
  })

  // 测试：修改资料只提交 display_name。
  it("updateMyProfile 以 PATCH 提交显示名", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValue({
        ok: true,
        status: 200,
        json: () => Promise.resolve(makeUser("member")),
      })
    vi.stubGlobal("fetch", fetchMock)

    await updateMyProfile({ display_name: "新名字" })

    const [url, init] = fetchMock.mock.calls[0]
    expect(url).toBe("/api/users/me")
    expect(init.method).toBe("PATCH")
    expect(JSON.parse(init.body)).toEqual({ display_name: "新名字" })
  })

  // 测试：修改密码提交当前密码和新密码，204 无返回体。
  it("changeMyPassword 提交当前密码与新密码", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValue({
        ok: true,
        status: 204,
        json: () => Promise.reject(new Error("no body")),
      })
    vi.stubGlobal("fetch", fetchMock)

    await expect(
      changeMyPassword({
        current_password: "Old-Pass-2026",
        new_password: "New-Pass-2027",
      }),
    ).resolves.toBeUndefined()

    const [url, init] = fetchMock.mock.calls[0]
    expect(url).toBe("/api/users/me/password")
    expect(init.method).toBe("POST")
    expect(JSON.parse(init.body)).toEqual({
      current_password: "Old-Pass-2026",
      new_password: "New-Pass-2027",
    })
  })
})
