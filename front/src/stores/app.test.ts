import { createPinia, setActivePinia } from "pinia"
import { beforeEach, describe, expect, it, vi } from "vitest"

import { fetchHealth } from "../api/health"
import { useAppStore } from "./app"

vi.mock("../api/health", () => ({
  fetchHealth: vi.fn(),
}))

const fetchHealthMock = vi.mocked(fetchHealth)

describe("useAppStore", () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    fetchHealthMock.mockReset()
  })

  it("loads and stores backend health status", async () => {
    fetchHealthMock.mockResolvedValue({
      status: "ok",
      app_name: "knowra",
      environment: "local",
    })

    const store = useAppStore()
    await store.refreshHealth()

    expect(store.health).toEqual({
      status: "ok",
      app_name: "knowra",
      environment: "local",
    })
    expect(store.isHealthLoading).toBe(false)
    expect(store.healthError).toBeNull()
    expect(store.lastHealthCheckedAt).toBeInstanceOf(Date)
  })

  it("stores a readable health error when the request fails", async () => {
    fetchHealthMock.mockRejectedValue(new Error("Backend unavailable"))

    const store = useAppStore()
    await store.refreshHealth()

    expect(store.health).toBeNull()
    expect(store.isHealthLoading).toBe(false)
    expect(store.healthError).toBe("Backend unavailable")
  })
})
