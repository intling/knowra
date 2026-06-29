/** Console formatting helpers for the knowra structured logger. */

import type { LogLevel, LogRecord } from "./types"

const LEVEL_ABBREV: Record<LogLevel, string> = {
  debug: "DBG",
  info: "INF",
  warn: "WRN",
  error: "ERR",
}

/** CSS styles applied to console output per log level. */
export const consoleStyles: Record<LogLevel, string> = {
  debug: "color: #9ca3af", // gray-400
  info: "color: #3b82f6", // blue-500
  warn: "color: #f97316; font-weight: bold", // orange-500
  error: "color: #ef4444; font-weight: bold", // red-500
}

/**
 * Format a LogRecord into a human-readable string for console output.
 *
 * Format: `HH:mm:ss.SSS LEVEL [trace_prefix] module — message key=value ...`
 */
export function formatLogRecord(record: LogRecord): string {
  const ts = new Date(record.ts)
  const hh = String(ts.getHours()).padStart(2, "0")
  const mm = String(ts.getMinutes()).padStart(2, "0")
  const ss = String(ts.getSeconds()).padStart(2, "0")
  const ms = String(ts.getMilliseconds()).padStart(3, "0")
  const time = `${hh}:${mm}:${ss}.${ms}`

  const level = LEVEL_ABBREV[record.level] ?? record.level.toUpperCase()
  const tracePrefix = record.trace_id.length >= 6 ? record.trace_id.slice(0, 6) : record.trace_id

  let output = `${time} ${level} [${tracePrefix}] ${record.module} — ${record.message}`

  // Inline extra key=value pairs.
  if (record.extra) {
    const pairs = Object.entries(record.extra).map(
      ([k, v]) => `${k}=${String(v)}`,
    )
    if (pairs.length > 0) {
      output += "  " + pairs.join(" ")
    }
  }

  // Append error details.
  if (record.error) {
    output += `\n  ${record.error.name}: ${record.error.message}`
    if (record.error.stack) {
      output += `\n${record.error.stack
        .split("\n")
        .map((line) => "  " + line)
        .join("\n")}`
    }
  }

  return output
}

/**
 * Return the console method to use for a given log level.
 * Maps "warn" → console.warn, "error" → console.error, everything else → console.log.
 */
export function consoleMethodForLevel(level: LogLevel): "log" | "warn" | "error" {
  if (level === "warn") return "warn"
  if (level === "error") return "error"
  return "log"
}
