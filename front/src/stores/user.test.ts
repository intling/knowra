import { createPinia, setActivePinia } from "pinia"
import { beforeEach, describe, expect, it, vi } from "vitest"

import { getCurrentUser } from "../api/users"
import { useUserStore } from "./user"

vi.mock("../api/users", () => ({
  getCurrentUser: vi.fn(),
}))

vi.mock("../shared/logger", () => ({
  createLogger: () => ({
    debug: vi.fn(),
    info: vi.fn(),
    warn: vi.fn(),
    error: vi.fn(),
  }),
  getRingBuffer: () => ({ push: vi.fn(), size: 0, getAll: () => [] }),
}))

const getCurrentUserMock = vi.mocked(getCurrentUser)

describe("useUserStore", () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    getCurrentUserMock.mockReset()
  })

  // 测试：当前用户加载成功后，store 会保存用户信息并清除加载和错误状态。
  it("loads and stores the current user", async () => {
    getCurrentUserMock.mockResolvedValue({
      id: "00000000-0000-0000-0000-000000000001",
      display_name: "Default User",
      email: null,
      avatar_url: null,
      status: "active",
      deleted_at: null,
      created_at: "2026-05-23T00:00:00Z",
      updated_at: "2026-05-23T00:00:00Z",
    })

    const store = useUserStore()
    await store.loadCurrentUser()

    expect(store.currentUser?.display_name).toBe("Default User")
    expect(store.isUserLoading).toBe(false)
    expect(store.userError).toBeNull()
  })

  // 测试：当前用户请求失败时，store 会清空用户并保存可读错误信息。
  it("stores a readable error when the current user request fails", async () => {
    getCurrentUserMock.mockRejectedValue(new Error("Current user is unavailable"))

    const store = useUserStore()
    await store.loadCurrentUser()

    expect(store.currentUser).toBeNull()
    expect(store.isUserLoading).toBe(false)
    expect(store.userError).toBe("Current user is unavailable")
  })
})
