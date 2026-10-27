import { afterEach, describe, expect, it, vi } from "vitest"

import { searchChunks, type SearchResponse } from "./search"
import { makeResponse } from "../__tests__/fixtures/search"

vi.mock("../shared/logger", () => ({
  createLogger: () => ({ debug: vi.fn(), info: vi.fn(), warn: vi.fn(), error: vi.fn() }),
  getRingBuffer: () => ({ push: vi.fn(), size: 0, getAll: () => [] }),
}))
vi.mock("../shared/logger/trace-context", () => ({
  traceManager: { getTraceId: () => "stream-test-trace" },
}))

type StreamEvent = {
  type: string
  stage?: string
  delta?: string
  response?: SearchResponse
}

const encoder = new TextEncoder()
const frame = (event: string, data: unknown) =>
  `event: ${event}\ndata: ${JSON.stringify(data)}\n\n`

function respond(chunks: Uint8Array[], cancel = vi.fn()) {
  const response = new Response(
    new ReadableStream<Uint8Array>({
      start(controller) {
        for (const chunk of chunks) controller.enqueue(chunk)
        controller.close()
      },
      cancel,
    }),
    { headers: { "Content-Type": "text/event-stream; charset=utf-8" } },
  )
  const fetch = vi.fn().mockResolvedValue(response)
  vi.stubGlobal("fetch", fetch)
  return fetch
}

afterEach(() => vi.unstubAllGlobals())

describe("Search SSE 客户端", () => {
  // 验证真实流拆包：中文跨 UTF-8 字节、SSE 跨块、多帧合并和 CRLF 均保持正文准确。
  it.each(["\n", "\r\n"])("按单字节拆包仍准确处理中文与事件（%j）", async (newline) => {
    const metadata = makeResponse({ answer: "", answer_tokens: null })
    const final = makeResponse({ answer: "你好，世界🌏。" })
    const text = (
      ": keep-alive\n\n" +
      frame("status", { stage: "searching" }) +
      frame("metadata", metadata) +
      frame("delta", { delta: "你好，" }) +
      frame("delta", { delta: "世界🌏。" }) +
      frame("done", final)
    ).replaceAll("\n", newline)
    const bytes = encoder.encode(text)
    const fetch = respond(Array.from(bytes, (byte) => Uint8Array.of(byte)))
    const events: StreamEvent[] = []
    const abort = new AbortController()

    const result = await searchChunks(
      { query: "你好", session_id: "conversation-1", document_ids: ["doc-a"] },
      { onEvent: (event: StreamEvent) => events.push(event), signal: abort.signal },
    )

    expect(result).toEqual(final)
    expect(events.map((event) => event.type)).toEqual(["status", "metadata", "delta", "delta"])
    expect(events[1]?.response).toEqual(metadata)
    expect(events.filter((event) => event.type === "delta").map((event) => event.delta).join(""))
      .toBe("你好，世界🌏。")
    expect(fetch).toHaveBeenCalledWith("/api/search", expect.objectContaining({
      credentials: "include",
      signal: abort.signal,
      headers: expect.objectContaining({
        Accept: "text/event-stream",
        "X-Trace-ID": "stream-test-trace",
      }),
    }))
    expect(JSON.parse(fetch.mock.calls[0]![1].body)).toMatchObject({
      session_id: "conversation-1",
      document_ids: ["doc-a"],
    })
  })

  // 验证增量回调在请求未结束前触发，避免只把完整响应伪装成逐段显示。
  it("模型未结束时已经通知首个正文增量", async () => {
    let controller!: ReadableStreamDefaultController<Uint8Array>
    const response = new Response(new ReadableStream<Uint8Array>({
      start(value) { controller = value },
    }), { headers: { "Content-Type": "text/event-stream" } })
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(response))
    const onEvent = vi.fn()
    let completed = false
    const pending = searchChunks({ query: "你好" }, { onEvent })
    void pending.then(() => { completed = true }, () => {})
    controller.enqueue(encoder.encode(frame("delta", { delta: "第一段" })))
    try {
      await vi.waitFor(() => expect(onEvent).toHaveBeenCalledWith({
        type: "delta", delta: "第一段",
      }), { timeout: 500 })
      expect(completed).toBe(false)
    } finally {
      controller.enqueue(encoder.encode(frame("done", makeResponse({ answer: "第一段" }))))
      controller.close()
      await pending.catch(() => {})
    }
  })

  // 验证多行 data 与未知扩展帧不破坏解析，最终仍返回权威 done 响应。
  it("兼容多行 JSON data 并忽略未知扩展事件", async () => {
    const final = makeResponse({ answer: "完成" })
    const pretty = JSON.stringify(final, null, 2).split("\n").map((line) => `data: ${line}`).join("\n")
    respond([encoder.encode(frame("future-extension", { value: 1 }) + `event: done\n${pretty}\n\n`)])
    expect(await searchChunks({ query: "你好" }, { onEvent: vi.fn() })).toEqual(final)
  })

  // 验证没有 done 时不能将部分正文当作成功，即使底层连接正常 EOF。
  it("缺少终帧时保留已通知增量并报告连接中断", async () => {
    respond([encoder.encode(frame("delta", { delta: "部分正文" }))])
    const onEvent = vi.fn()
    await expect(searchChunks({ query: "你好" }, { onEvent })).rejects.toMatchObject({
      name: "SearchApiError", detail: expect.stringMatching(/中断|未完成/),
    })
    expect(onEvent).toHaveBeenCalledWith({ type: "delta", delta: "部分正文" })
  })

  // 验证流内错误与格式错误均成为可读业务错误，不静默完成或追加 undefined。
  it.each([
    [frame("error", { detail: "检索暂不可用，请稍后重试。" }), /检索暂不可用/],
    ["event: delta\ndata: not-json\n\n", /格式|解析/],
    [frame("delta", { delta: 123 }), /格式|解析/],
  ])("拒绝错误或畸形事件（%s）", async (text, message) => {
    respond([encoder.encode(text)])
    await expect(searchChunks({ query: "你好" }, { onEvent: vi.fn() })).rejects.toMatchObject({
      name: "SearchApiError", detail: expect.stringMatching(message),
    })
  })

  // 验证终帧之后不等待连接关闭，主动取消 reader，避免保留无用长连接。
  it("收到 done 后立即返回并关闭仍打开的响应流", async () => {
    const cancel = vi.fn()
    const final = makeResponse()
    let controller!: ReadableStreamDefaultController<Uint8Array>
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(new ReadableStream({
      start(value) {
        controller = value
        controller.enqueue(encoder.encode(frame("done", final)))
      },
      cancel,
    }), { headers: { "Content-Type": "text/event-stream" } })))
    const pending = searchChunks({ query: "你好" }, { onEvent: vi.fn() })
    let settled = false
    void pending.then(() => { settled = true }, () => {})
    try {
      await vi.waitFor(() => expect(settled).toBe(true), { timeout: 500 })
      expect(await pending).toEqual(final)
      expect(cancel).toHaveBeenCalledOnce()
    } finally {
      if (!cancel.mock.calls.length) controller.close()
      await pending.catch(() => {})
    }
  })

  // 回归守护：流开始前的额度错误保留服务端明确原因，并经统一 Cookie 客户端请求。
  it("开始前的 429 仍返回具体额度原因", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(
      JSON.stringify({ detail: "最近 60 分钟问答额度已用尽，请稍后重试。" }),
      { status: 429, headers: { "Content-Type": "application/json", "Retry-After": "30" } },
    )))
    await expect(searchChunks({ query: "你好" }, { onEvent: vi.fn() })).rejects.toMatchObject({
      status: 429, detail: "最近 60 分钟问答额度已用尽，请稍后重试。",
    })
  })

  // 回归守护：旧调用方仍可读取 JSON；新前端与旧后端联调也能读取完整 JSON。
  it("未协商 SSE 的调用保持原 JSON 行为", async () => {
    const final = makeResponse()
    const fetch = vi.fn().mockResolvedValue(new Response(JSON.stringify(final), {
      headers: { "Content-Type": "application/json" },
    }))
    vi.stubGlobal("fetch", fetch)
    expect(await searchChunks({ query: "你好" })).toEqual(final)
    expect(fetch.mock.calls[0]![1].headers.Accept).toBe("application/json")
  })
})
