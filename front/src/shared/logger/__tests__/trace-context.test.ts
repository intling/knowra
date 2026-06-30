import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"
import { TraceManager } from "../trace-context"

const STORAGE_KEY = "knowra_trace_id"

describe("TraceManager", () => {
  beforeEach(() => {
    sessionStorage.clear()
    vi.unstubAllGlobals()
  })

  afterEach(() => {
    sessionStorage.clear()
  })

  describe("首次调用（sessionStorage 为空）", () => {
    it("7.1 生成 UUID7 格式字符串并写入 sessionStorage", () => {
      const tm = new TraceManager()
      const traceId = tm.getTraceId()

      // UUID format: 8-4-4-4-12 hex
      expect(traceId).toMatch(
        /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/,
      )
      expect(sessionStorage.getItem(STORAGE_KEY)).toBe(traceId)
    })
  })

  describe("sessionStorage 已有值时", () => {
    it("7.2 复用已有 trace_id，不生成新值", () => {
      sessionStorage.setItem(STORAGE_KEY, "01JFZ8AAAAAA-0000-0000-0000-000000000000")
      const tm = new TraceManager()
      const traceId = tm.getTraceId()

      expect(traceId).toBe("01JFZ8AAAAAA-0000-0000-0000-000000000000")
    })
  })

  describe("UUID7 格式验证", () => {
    it("7.3 生成的 UUID7 版本标识字符为 '7' 且长度符合 UUID 规范", () => {
      const tm = new TraceManager()
      const traceId = tm.getTraceId()

      // UUID7: positions 14 is the version char '7'
      // Format: xxxxxxxx-xxxx-7xxx-xxxx-xxxxxxxxxxxx
      expect(traceId).toHaveLength(36)
      expect(traceId[14]).toBe("7")
    })
  })

  describe("sessionStorage 不可用时降级", () => {
    it("当 sessionStorage 不可用时仍能生成并返回 trace_id", () => {
      // Stub sessionStorage getItem to throw.
      vi.spyOn(sessionStorage, "getItem").mockImplementation(() => {
        throw new Error("quota exceeded")
      })

      const tm = new TraceManager()
      const traceId = tm.getTraceId()

      expect(traceId).toMatch(
        /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/,
      )
    })
  })
})
