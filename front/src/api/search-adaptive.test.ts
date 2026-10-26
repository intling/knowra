import { afterEach, expect, it, vi } from "vitest"

import { searchChunks } from "./search"
import { makeResponse } from "../__tests__/fixtures/search"

vi.mock("../shared/logger", () => ({
  createLogger: () => ({ debug: vi.fn(), info: vi.fn(), warn: vi.fn(), error: vi.fn() }),
  getRingBuffer: () => ({ push: vi.fn(), size: 0, getAll: () => [] }),
}))

afterEach(() => vi.unstubAllGlobals())

// 验证 API 层不会丢弃文档范围；若丢弃，同名总结问题会错误读取全部知识库。
it("向问答入口转发显式文档范围", async () => {
  const fetchRequest = vi.fn().mockResolvedValue({
    ok: true,
    status: 200,
    json: async () => makeResponse(),
  })
  vi.stubGlobal("fetch", fetchRequest)
  const request = {
    query: "总结这些资料的核心观点",
    document_ids: ["11111111-1111-4111-8111-111111111111"],
  }

  await searchChunks(request)

  const options = fetchRequest.mock.calls[0]?.[1] as RequestInit
  const body = JSON.parse(options.body as string) as { document_ids?: string[] }
  expect(body.document_ids).toEqual(["11111111-1111-4111-8111-111111111111"])
})
