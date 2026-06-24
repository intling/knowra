/** Core logger implementation providing the main `createLogger` factory. */

import type { LogLevel, LogRecord } from "./types"
import { LOG_LEVEL_VALUES } from "./types"
import { formatLogRecord, consoleMethodForLevel, consoleStyles } from "./formatter"
import type { RingBuffer } from "./ring-buffer"
import { traceManager } from "./trace-context"

/**
 * A Logger instance bound to a specific module.
 *
 * It automatically injects `trace_id` and `module` into every log record,
 * routes to console (respecting `consoleLevel`) and the ring buffer
 * (respecting `bufferLevel`), and handles error payloads gracefully.
 */
export class Logger {
  constructor(
    private _module: string,
    private _ringBuffer: RingBuffer,
    private _consoleLevel: LogLevel = "debug",
  ) {}

  /** Log a debug-level message. */
  debug(message: string, extra?: Record<string, unknown>): void {
    this._log("debug", message, undefined, extra)
  }

  /** Log an info-level message. */
  info(message: string, extra?: Record<string, unknown>): void {
    this._log("info", message, undefined, extra)
  }

  /** Log a warn-level message. */
  warn(message: string, extra?: Record<string, unknown>): void {
    this._log("warn", message, undefined, extra)
  }

  /**
   * Log an error-level message.
   *
   * @param message - Human-readable description.
   * @param error - An Error instance (optional). Its name/message/stack are extracted automatically.
   * @param extra - Additional structured payload (optional).
   */
  error(message: string, error?: Error | unknown, extra?: Record<string, unknown>): void {
    this._log("error", message, error, extra)
  }

  // ------------------------------------------------------------------
  // Internal
  // ------------------------------------------------------------------

  private _log(
    level: LogLevel,
    message: string,
    err?: Error | unknown,
    extra?: Record<string, unknown>,
  ): void {
    const record = this._buildRecord(level, message, err, extra)

    // Console output.
    if (LOG_LEVEL_VALUES[level] >= LOG_LEVEL_VALUES[this._consoleLevel]) {
      const formatted = formatLogRecord(record)
      const style = consoleStyles[level]
      const method = consoleMethodForLevel(level)
      console[method](`%c${formatted}`, style)
    }

    // Ring buffer (always push — RingBuffer applies its own level gate).
    this._ringBuffer.push(record)
  }

  private _buildRecord(
    level: LogLevel,
    message: string,
    err?: Error | unknown,
    extra?: Record<string, unknown>,
  ): LogRecord {
    const record: LogRecord = {
      ts: Date.now(),
      level,
      trace_id: traceManager.getTraceId(),
      module: this._module,
      message,
    }

    if (extra && Object.keys(extra).length > 0) {
      record.extra = extra
    }

    if (err instanceof Error) {
      record.error = {
        name: err.name,
        message: err.message,
        stack: err.stack ?? undefined,
      }
    } else if (err !== undefined && err !== null) {
      // Non-Error throwable — stringify.
      record.error = {
        name: "UnknownError",
        message: String(err),
      }
    }

    return record
  }
}

/**
 * Create a Logger bound to a module name and a shared RingBuffer.
 *
 * @param module - Module identifier (e.g. "stores:user", "api:client").
 * @param ringBuffer - The shared RingBuffer instance.
 * @param consoleLevel - Minimum level for console output (default "debug").
 */
export function createLogger(
  module: string,
  ringBuffer: RingBuffer,
  consoleLevel?: LogLevel,
): Logger {
  return new Logger(module, ringBuffer, consoleLevel)
}
