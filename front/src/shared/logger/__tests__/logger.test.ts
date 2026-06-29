import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"
import { createLogger } from "../logger"
import { RingBuffer } from "../ring-buffer"

// We need to import the traceManager and ensure it returns a stable ID.
import { traceManager } from "../trace-context"

describe("Logger", () => {
  let ringBuffer: RingBuffer

  beforeEach(() => {
    ringBuffer = new RingBuffer(500, "info")
    // Ensure traceManager returns a predictable value for tests.
    vi.spyOn(traceManager, "getTraceId").mockReturnValue("01JFZ8AAAAAA-0000-0000-0000-000000000000")
    vi.spyOn(console, "log").mockImplementation(() => {})
    vi.spyOn(console, "warn").mockImplementation(() => {})
    vi.spyOn(console, "error").mockImplementation(() => {})
  })

  afterEach(() => {
    vi.restoreAllMocks()
  })

  describe("8.1 工厂函数 createLogger", () => {
    it("返回包含 debug/info/warn/error 方法的实例", () => {
      const logger = createLogger("module:test", ringBuffer)
      expect(typeof logger.debug).toBe("function")
      expect(typeof logger.info).toBe("function")
      expect(typeof logger.warn).toBe("function")
      expect(typeof logger.error).toBe("function")
    })
  })

  describe("8.2 日志自动注入 trace_id 和 module", () => {
    it("info 日志自动携带 trace_id 和 module", () => {
      const logger = createLogger("stores:user", ringBuffer)
      logger.info("用户登录成功", { userId: "u_123" })

      const records = ringBuffer.getAll()
      expect(records).toHaveLength(1)
      expect(records[0].trace_id).toBe("01JFZ8AAAAAA-0000-0000-0000-000000000000")
      expect(records[0].module).toBe("stores:user")
      expect(records[0].message).toBe("用户登录成功")
      expect(records[0].extra).toEqual({ userId: "u_123" })
    })

    it("error 日志自动携带 trace_id 和 module", () => {
      const logger = createLogger("api:client", ringBuffer)
      const err = new Error("请求超时")
      logger.error("API 请求失败", err, { url: "/api/users" })

      const records = ringBuffer.getAll()
      expect(records).toHaveLength(1)
      expect(records[0].trace_id).toBe("01JFZ8AAAAAA-0000-0000-0000-000000000000")
      expect(records[0].module).toBe("api:client")
    })
  })

  describe("8.3 logger.error() 自动提取 Error 字段", () => {
    it("从 Error 对象提取 name、message、stack", () => {
      const logger = createLogger("module:test", ringBuffer)
      const err = new Error("something broke")
      err.name = "CustomError"
      logger.error("操作失败", err)

      const records = ringBuffer.getAll()
      expect(records).toHaveLength(1)
      expect(records[0].error).toBeDefined()
      expect(records[0].error!.name).toBe("CustomError")
      expect(records[0].error!.message).toBe("something broke")
      expect(records[0].error!.stack).toBeDefined()
    })

    it("非 Error 对象转为 UnknownError", () => {
      const logger = createLogger("module:test", ringBuffer)
      logger.error("发生了错误", "just a string")

      const records = ringBuffer.getAll()
      expect(records).toHaveLength(1)
      expect(records[0].error).toBeDefined()
      expect(records[0].error!.name).toBe("UnknownError")
      expect(records[0].error!.message).toBe("just a string")
    })
  })

  describe("8.4 LOG_CONSOLE_LEVEL 低于当前级别的日志不输出到控制台", () => {
    it("info 级别下 debug 不输出到 console", () => {
      const logger = createLogger("module:test", ringBuffer, "info") // consoleLevel=info
      logger.debug("调试信息")
      logger.info("常规信息")

      // debug 不应调用 console.log
      const debugCalls = (console.log as ReturnType<typeof vi.fn>).mock.calls.filter(
        (call: string[]) => call[0]?.includes("调试信息"),
      )
      expect(debugCalls).toHaveLength(0)

      // info 应该调用 console.log
      const infoCalls = (console.log as ReturnType<typeof vi.fn>).mock.calls.filter(
        (call: string[]) => call[0]?.includes("常规信息"),
      )
      expect(infoCalls.length).toBeGreaterThanOrEqual(1)
    })

    it("debug 级别下 debug 正常输出到 console", () => {
      const logger = createLogger("module:test", ringBuffer, "debug")
      logger.debug("调试信息")

      const debugCalls = (console.log as ReturnType<typeof vi.fn>).mock.calls.filter(
        (call: string[]) => call[0]?.includes("调试信息"),
      )
      expect(debugCalls.length).toBeGreaterThanOrEqual(1)
    })
  })
})
