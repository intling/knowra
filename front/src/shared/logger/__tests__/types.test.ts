import { describe, expect, it } from "vitest"
import type { LogRecord } from "../types"
import { DEFAULT_LOGGER_OPTIONS, LOG_LEVEL_VALUES } from "../types"

describe("LogRecord type constraints", () => {
  it("requires all mandatory fields: ts, level, trace_id, module, message", () => {
    const record: LogRecord = {
      ts: Date.now(),
      level: "info",
      trace_id: "01JFZ8AAAAAA",
      module: "stores:user",
      message: "用户登录成功",
    }
    expect(record.ts).toBeTypeOf("number")
    expect(record.level).toBe("info")
    expect(record.trace_id).toBeTypeOf("string")
    expect(record.module).toBeTypeOf("string")
    expect(record.message).toBeTypeOf("string")
  })

  it("allows optional extra and error fields", () => {
    const record: LogRecord = {
      ts: Date.now(),
      level: "error",
      trace_id: "01JFZ8BBBBBB",
      module: "api:users",
      message: "请求失败",
      extra: { status: 500 },
      error: {
        name: "NetworkError",
        message: "请求超时",
        stack: "at fetchUsers (users.ts:10:5)",
      },
    }
    expect(record.extra).toEqual({ status: 500 })
    expect(record.error?.name).toBe("NetworkError")
    expect(record.error?.message).toBe("请求超时")
    expect(record.error?.stack).toBeDefined()
  })
})

describe("LOG_LEVEL_VALUES", () => {
  it("orders debug < info < warn < error", () => {
    expect(LOG_LEVEL_VALUES.debug).toBeLessThan(LOG_LEVEL_VALUES.info)
    expect(LOG_LEVEL_VALUES.info).toBeLessThan(LOG_LEVEL_VALUES.warn)
    expect(LOG_LEVEL_VALUES.warn).toBeLessThan(LOG_LEVEL_VALUES.error)
  })
})

describe("DEFAULT_LOGGER_OPTIONS", () => {
  it("has sensible defaults", () => {
    expect(DEFAULT_LOGGER_OPTIONS.ringSize).toBe(500)
    expect(DEFAULT_LOGGER_OPTIONS.diskMaxSize).toBe(5 * 1024 * 1024)
    expect(DEFAULT_LOGGER_OPTIONS.flushSize).toBe(100)
    expect(DEFAULT_LOGGER_OPTIONS.consoleLevel).toBe("debug")
    expect(DEFAULT_LOGGER_OPTIONS.bufferLevel).toBe("info")
  })
})
