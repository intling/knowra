import { describe, expect, it } from "vitest"
import type { LogRecord } from "../types"
import { formatLogRecord, consoleStyles, consoleMethodForLevel } from "../formatter"

function makeRecord(overrides: Partial<LogRecord> = {}): LogRecord {
  return {
    ts: new Date("2026-06-24T12:34:56.789Z").getTime(),
    level: "info",
    trace_id: "01JFZ8AAAAAA-0000-0000-0000-000000000000",
    module: "stores:user",
    message: "用户登录成功",
    ...overrides,
  }
}

describe("formatLogRecord", () => {
  describe("9.1 格式化输出包含完整字段信息", () => {
    it("输出包含时间戳（HH:mm:ss.SSS）、级别缩写、trace_id 前缀、模块名和消息", () => {
      const record = makeRecord()
      const output = formatLogRecord(record)

      // Time: 12:34:56.789 (UTC → in local it might differ; we check the format)
      expect(output).toMatch(/\d{2}:\d{2}:\d{2}\.\d{3}/)
      // Level abbreviation
      expect(output).toContain("INF")
      // trace_id prefix (first 6 chars)
      expect(output).toContain("01JFZ8")
      // Module
      expect(output).toContain("stores:user")
      // Message
      expect(output).toContain("用户登录成功")
    })

    it("输出内联 extra 字段 key=value", () => {
      const record = makeRecord({ extra: { userId: "u_123", status: 200 } })
      const output = formatLogRecord(record)

      expect(output).toContain("userId=u_123")
      expect(output).toContain("status=200")
    })
  })

  describe("9.2 不同日志级别使用不同 CSS 样式", () => {
    it("ERROR 级别使用红色样式", () => {
      expect(consoleStyles.error).toContain("#ef4444")
    })

    it("WARN 级别使用橙色样式", () => {
      expect(consoleStyles.warn).toContain("#f97316")
    })

    it("INFO 级别使用蓝色样式", () => {
      expect(consoleStyles.info).toContain("#3b82f6")
    })

    it("DEBUG 级别使用灰色样式", () => {
      expect(consoleStyles.debug).toContain("#9ca3af")
    })
  })
})

describe("consoleMethodForLevel", () => {
  it("warn → console.warn", () => {
    expect(consoleMethodForLevel("warn")).toBe("warn")
  })
  it("error → console.error", () => {
    expect(consoleMethodForLevel("error")).toBe("error")
  })
  it("info → console.log", () => {
    expect(consoleMethodForLevel("info")).toBe("log")
  })
  it("debug → console.log", () => {
    expect(consoleMethodForLevel("debug")).toBe("log")
  })
})
