import { afterEach, describe, expect, it, vi } from "vitest"

import { fetchHealth } from "./health"

describe("fetchHealth", () => {
  afterEach(() => {
    vi.unstubAllGlobals()
  })

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
      },
    })
  })
})
