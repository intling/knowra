import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"

describe("main.ts 全局错误处理集成测试", () => {
  beforeEach(async () => {
    vi.resetModules()

    // Ensure traceManager returns a predictable ID.
    const { traceManager } = await import("../shared/logger/trace-context")
    vi.spyOn(traceManager, "getTraceId").mockReturnValue("01JFZ8INTEGRATION-TEST-000000000000")

    // Suppress console output during tests.
    vi.spyOn(console, "error").mockImplementation(() => {})
    vi.spyOn(console, "log").mockImplementation(() => {})
    vi.spyOn(console, "warn").mockImplementation(() => {})

    // Create #app div so Vue can mount.
    document.body.innerHTML = '<div id="app"></div>'
  })

  afterEach(() => {
    vi.restoreAllMocks()
    document.body.innerHTML = ""
  })

  describe("14.3 全局错误处理集成", () => {
    it("Vue errorHandler 将组件错误记录到 ring buffer 并携带 trace_id 和堆栈", async () => {
      const { initLogger, getRingBuffer, createLogger } = await import("../shared/logger")

      initLogger()
      const ringBuffer = getRingBuffer()

      // Simulate what main.ts's app.config.errorHandler does.
      const logger = createLogger("app:vue", ringBuffer)
      const error = new Error("组件渲染失败")
      error.name = "RenderError"

      // This is exactly what the errorHandler callback does in main.ts.
      const info = "render"
      logger.error(`Vue 组件错误 (${info})`, error, { componentInfo: info })

      const records = ringBuffer.getAll()
      expect(records.length).toBeGreaterThan(0)
      const lastRecord = records[records.length - 1]
      expect(lastRecord.level).toBe("error")
      expect(lastRecord.trace_id).toBe("01JFZ8INTEGRATION-TEST-000000000000")
      expect(lastRecord.module).toBe("app:vue")
      expect(lastRecord.error).toBeDefined()
      expect(lastRecord.error!.name).toBe("RenderError")
      expect(lastRecord.error!.message).toBe("组件渲染失败")
      expect(lastRecord.error!.stack).toBeDefined()
      expect(lastRecord.extra).toEqual({ componentInfo: info })
    })

    it("unhandledrejection 事件将 Promise 拒绝记录到 ring buffer", async () => {
      const { initLogger, getRingBuffer, createLogger } = await import("../shared/logger")

      initLogger()
      const ringBuffer = getRingBuffer()
      const logger = createLogger("app:vue", ringBuffer)

      // Register the unhandledrejection handler (same as main.ts).
      window.addEventListener("unhandledrejection", (event) => {
        const reason = event.reason
        if (reason instanceof Error) {
          logger.error("未捕获的 Promise 拒绝", reason)
        } else {
          logger.error("未捕获的 Promise 拒绝", undefined, { reason: String(reason) })
        }
      })

      // Dispatch an unhandled rejection.
      const reason = new Error("网络请求超时")
      reason.name = "TimeoutError"
      window.dispatchEvent(
        new PromiseRejectionEvent("unhandledrejection", {
          promise: Promise.reject(reason).catch(() => {}),
          reason,
        }),
      )

      const records = ringBuffer.getAll()
      expect(records.length).toBeGreaterThan(0)
      const lastRecord = records[records.length - 1]
      expect(lastRecord.level).toBe("error")
      expect(lastRecord.error).toBeDefined()
      expect(lastRecord.error!.name).toBe("TimeoutError")
      expect(lastRecord.error!.message).toBe("网络请求超时")
      expect(lastRecord.message).toContain("Promise")
    })

    it("unhandledrejection 处理非 Error 类型的 reason", async () => {
      const { initLogger, getRingBuffer, createLogger } = await import("../shared/logger")

      initLogger()
      const ringBuffer = getRingBuffer()
      const logger = createLogger("app:vue", ringBuffer)

      window.addEventListener("unhandledrejection", (event) => {
        const reason = event.reason
        if (reason instanceof Error) {
          logger.error("未捕获的 Promise 拒绝", reason)
        } else {
          logger.error("未捕获的 Promise 拒绝", undefined, { reason: String(reason) })
        }
      })

      window.dispatchEvent(
        new PromiseRejectionEvent("unhandledrejection", {
          promise: Promise.reject("plain string error").catch(() => {}),
          reason: "plain string error",
        }),
      )

      const records = ringBuffer.getAll()
      expect(records.length).toBeGreaterThan(0)
      const lastRecord = records[records.length - 1]
      expect(lastRecord.level).toBe("error")
      expect(lastRecord.extra).toEqual({ reason: "plain string error" })
    })
  })
})
