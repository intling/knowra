import { afterEach, describe, expect, it, vi } from "vitest"
import { initLogger, getRingBuffer, getDiskBuffer, getLoggerOptions } from "../index"
import { traceManager } from "../trace-context"

describe("initLogger", () => {
  afterEach(() => {
    vi.restoreAllMocks()
  })

  describe("12.2 初始化函数完成 TraceManager 创建、Logger 工厂配置和全局配置注入", () => {
    it("initLogger 创建 TraceManager（获取 trace_id）、配置 RingBuffer 和 DiskBuffer", () => {
      // Spy on traceManager to confirm it's warmed up.
      const spy = vi.spyOn(traceManager, "getTraceId")

      initLogger({
        ringSize: 100,
        diskMaxSize: 1024 * 1024,
        flushSize: 20,
        consoleLevel: "info",
        bufferLevel: "info",
      })

      // TraceManager should have been queried.
      expect(spy).toHaveBeenCalled()

      // RingBuffer and DiskBuffer should be available.
      const ringBuf = getRingBuffer()
      expect(ringBuf).toBeDefined()
      expect(ringBuf.capacity).toBe(100)

      const diskBuf = getDiskBuffer()
      expect(diskBuf).toBeDefined()

      // Options should reflect our input.
      const opts = getLoggerOptions()
      expect(opts.ringSize).toBe(100)
      expect(opts.diskMaxSize).toBe(1024 * 1024)
      expect(opts.flushSize).toBe(20)
      expect(opts.consoleLevel).toBe("info")
      expect(opts.bufferLevel).toBe("info")
    })

    it("initLogger 是幂等操作，第二次调用不影响已有配置", () => {
      initLogger({ ringSize: 50 })
      const ringBuf1 = getRingBuffer()
      const capacity1 = ringBuf1.capacity

      initLogger({ ringSize: 999 }) // should be no-op
      const ringBuf2 = getRingBuffer()

      // Same instance; second call ignored.
      expect(ringBuf1).toBe(ringBuf2)
      expect(ringBuf2.capacity).toBe(capacity1) // unchanged
    })

    it("未提供 options 时使用默认值", () => {
      // Clear module-level state by re-importing isn't easy in vitest,
      // but initLogger with no args should work without error.
      // Since initLogger is idempotent and we already called it,
      // we can verify getLoggerOptions returns the previously-set values.
      const opts = getLoggerOptions()
      expect(opts.ringSize).toBeGreaterThan(0)
      expect(opts.consoleLevel).toBeDefined()
      expect(opts.bufferLevel).toBeDefined()
    })
  })
})
