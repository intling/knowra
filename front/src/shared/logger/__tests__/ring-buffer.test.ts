import { beforeEach, describe, expect, it } from "vitest"
import type { LogRecord } from "../types"
import { RingBuffer } from "../ring-buffer"

function makeRecord(overrides: Partial<LogRecord> = {}): LogRecord {
  return {
    ts: Date.now(),
    level: "info",
    trace_id: "01JFZ8AAAAAA-0000-0000-0000-000000000000",
    module: "test:module",
    message: "test message",
    ...overrides,
  }
}

describe("RingBuffer", () => {
  let buffer: RingBuffer

  beforeEach(() => {
    buffer = new RingBuffer(5, "info")
  })

  describe("10.1 追加和 getAll 按时间排序", () => {
    it("追加日志条目后 getAll 返回按插入顺序的条目列表", () => {
      const r1 = makeRecord({ message: "first", ts: 100 })
      const r2 = makeRecord({ message: "second", ts: 200 })
      const r3 = makeRecord({ message: "third", ts: 300 })

      buffer.push(r1)
      buffer.push(r2)
      buffer.push(r3)

      const all = buffer.getAll()
      expect(all).toHaveLength(3)
      expect(all[0].message).toBe("first")
      expect(all[1].message).toBe("second")
      expect(all[2].message).toBe("third")
    })
  })

  describe("10.2 缓冲区满时丢弃最旧条目", () => {
    it("超过 capacity 时保留最新的 N 条", () => {
      const cap = 3
      const buf = new RingBuffer(cap, "info")

      buf.push(makeRecord({ message: "oldest" }))
      buf.push(makeRecord({ message: "middle" }))
      buf.push(makeRecord({ message: "newest" }))
      buf.push(makeRecord({ message: "overflow" })) // oldest should be dropped

      const all = buf.getAll()
      expect(all).toHaveLength(cap)
      expect(all[0].message).toBe("middle")
      expect(all[1].message).toBe("newest")
      expect(all[2].message).toBe("overflow")
    })
  })

  describe("10.3 debug 级别不入缓冲区", () => {
    it("debug 级别（低于 LOG_BUFFER_LEVEL=info）的条目不被追加", () => {
      buffer.push(makeRecord({ level: "info", message: "info msg" }))
      buffer.push(makeRecord({ level: "debug", message: "debug msg" }))
      buffer.push(makeRecord({ level: "warn", message: "warn msg" }))

      const all = buffer.getAll()
      expect(all).toHaveLength(2)
      expect(all[0].message).toBe("info msg")
      expect(all[1].message).toBe("warn msg")
    })
  })

  describe("10.4 flush 返回最旧 count 条并从缓冲区移除", () => {
    it("flush 后缓冲区条目减少", () => {
      buffer.push(makeRecord({ message: "a" }))
      buffer.push(makeRecord({ message: "b" }))
      buffer.push(makeRecord({ message: "c" }))
      buffer.push(makeRecord({ message: "d" }))

      const flushed = buffer.flush(2)
      expect(flushed).toHaveLength(2)
      expect(flushed[0].message).toBe("a")
      expect(flushed[1].message).toBe("b")

      const remaining = buffer.getAll()
      expect(remaining).toHaveLength(2)
      expect(remaining[0].message).toBe("c")
      expect(remaining[1].message).toBe("d")
    })

    it("flush 请求数量大于缓冲区条目数时返回全部", () => {
      buffer.push(makeRecord({ message: "only" }))
      const flushed = buffer.flush(100)
      expect(flushed).toHaveLength(1)
      expect(buffer.getAll()).toHaveLength(0)
    })
  })

  describe("clear", () => {
    it("清空所有条目", () => {
      buffer.push(makeRecord())
      buffer.push(makeRecord())
      buffer.clear()
      expect(buffer.getAll()).toHaveLength(0)
    })
  })
})
