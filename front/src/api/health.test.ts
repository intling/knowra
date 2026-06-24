import { afterEach, describe, expect, it, vi } from "vitest"

import { fetchHealth } from "./health"

vi.mock("../shared/logger", () => ({
  createLogger: () => ({
    debug: vi.fn(),
    info: vi.fn(),
    warn: vi.fn(),
    error: vi.fn(),
  }),
  getRingBuffer: () => ({ push: vi.fn(), size: 0, getAll: () => [] }),
}))

describe("fetchHealth", () => {
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  // 测试：获取后端健康状态时会使用配置的 API 基础路径，并带上 JSON 接收头。
  it("requests backend health through the configured API base path", async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      json: () =>
        Promise.resolve({
          status: "ok",
          app_name: "knowra",
          environment: "local",
        }),
    })
    vi.stubGlobal("fetch", fetchMock)

    await expect(fetchHealth()).resolves.toEqual({
      status: "ok",
      app_name: "knowra",
      environment: "local",
    })
    expect(fetchMock).toHaveBeenCalledWith("/api/health", {
      headers: {
        Accept: "application/json",
        "X-Trace-ID": expect.any(String) as string,
      },
    })
  })
})
