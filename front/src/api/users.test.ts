import { afterEach, describe, expect, it, vi } from "vitest"

import { getCurrentUser } from "./users"

describe("getCurrentUser", () => {
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it("requests the current user through the configured API base path", async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      json: () =>
        Promise.resolve({
          id: "00000000-0000-0000-0000-000000000001",
          display_name: "Default User",
          email: null,
          avatar_url: null,
          status: "active",
          deleted_at: null,
          created_at: "2026-05-23T00:00:00Z",
          updated_at: "2026-05-23T00:00:00Z",
        }),
    })
    vi.stubGlobal("fetch", fetchMock)

    await expect(getCurrentUser()).resolves.toEqual({
      id: "00000000-0000-0000-0000-000000000001",
      display_name: "Default User",
      email: null,
      avatar_url: null,
      status: "active",
      deleted_at: null,
      created_at: "2026-05-23T00:00:00Z",
      updated_at: "2026-05-23T00:00:00Z",
    })
    expect(fetchMock).toHaveBeenCalledWith("/api/users/me", {
      headers: {
        Accept: "application/json",
      },
    })
  })
})
