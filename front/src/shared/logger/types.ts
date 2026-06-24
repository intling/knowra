/** Shared types for the knowra frontend structured logging module. */

/** Log severity levels, ordered from lowest to highest severity. */
export type LogLevel = "debug" | "info" | "warn" | "error"

/** Numeric representation matching LogLevel for comparisons. */
export const LOG_LEVEL_VALUES: Record<LogLevel, number> = {
  debug: 10,
  info: 20,
  warn: 30,
  error: 40,
}

/** A single structured log entry produced by the logger. */
export interface LogRecord {
  /** Unix timestamp (milliseconds since epoch). */
  ts: number
  /** Severity level of this record. */
  level: LogLevel
  /** Trace ID from the page-level session. */
  trace_id: string
  /** Module identifier (e.g. "stores:user"). */
  module: string
  /** Human-readable log message. */
  message: string
  /** Optional structured payload. */
  extra?: Record<string, unknown>
  /** Error information (populated by logger.error()). */
  error?: {
    name: string
    message: string
    stack?: string
  }
}

/** Configuration knobs for the logging subsystem. */
export interface LoggerOptions {
  /** Maximum number of entries in the in-memory ring buffer. */
  ringSize: number
  /** Maximum total size (bytes) of IndexedDB log storage. */
  diskMaxSize: number
  /** How many entries to flush from ring → IndexedDB at once. */
  flushSize: number
  /** Minimum level for console output. */
  consoleLevel: LogLevel
  /** Minimum level for ring buffer (and therefore disk) storage. */
  bufferLevel: LogLevel
}

/** Default logger options (overridable via env vars). */
export const DEFAULT_LOGGER_OPTIONS: LoggerOptions = {
  ringSize: 500,
  diskMaxSize: 5 * 1024 * 1024, // 5 MB
  flushSize: 100,
  consoleLevel: "debug",
  bufferLevel: "info",
}
