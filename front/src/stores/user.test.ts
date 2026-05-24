import { createPinia, setActivePinia } from "pinia"
import { beforeEach, describe, expect, it, vi } from "vitest"

import { getCurrentUser } from "../api/users"
import { useUserStore } from "./user"

vi.mock("../api/users", () => ({
  getCurrentUser: vi.fn(),
}))

const getCurrentUserMock = vi.mocked(getCurrentUser)

describe("useUserStore", () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    getCurrentUserMock.mockReset()
  })

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

  it("stores a readable error when the current user request fails", async () => {
    getCurrentUserMock.mockRejectedValue(new Error("Current user is unavailable"))

    const store = useUserStore()
    await store.loadCurrentUser()

    expect(store.currentUser).toBeNull()
    expect(store.isUserLoading).toBe(false)
    expect(store.userError).toBe("Current user is unavailable")
  })
})
