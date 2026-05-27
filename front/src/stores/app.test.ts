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

  // 测试：刷新健康状态成功后，store 会保存后端状态、结束加载并记录检查时间。
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

  // 测试：健康状态请求失败时，store 会清空状态并保存可读错误信息。
  it("stores a readable health error when the request fails", async () => {
    fetchHealthMock.mockRejectedValue(new Error("Backend unavailable"))

    const store = useAppStore()
    await store.refreshHealth()

    expect(store.health).toBeNull()
    expect(store.isHealthLoading).toBe(false)
    expect(store.healthError).toBe("Backend unavailable")
  })
})
