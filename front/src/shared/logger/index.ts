/** Unified entry point for the knowra frontend structured logging module. */

import type { LoggerOptions, LogLevel } from "./types"
import { DEFAULT_LOGGER_OPTIONS } from "./types"
import { RingBuffer } from "./ring-buffer"
import { DiskBuffer } from "./disk-buffer"
import { traceManager } from "./trace-context"

// Re-export public API.
export { createLogger, Logger } from "./logger"
export { RingBuffer } from "./ring-buffer"
export { DiskBuffer } from "./disk-buffer"
export { traceManager, TraceManager } from "./trace-context"
export { formatLogRecord, consoleStyles } from "./formatter"
export type { LogRecord, LogLevel, LoggerOptions } from "./types"
export { LOG_LEVEL_VALUES, DEFAULT_LOGGER_OPTIONS } from "./types"

// ---------------------------------------------------------------------------
// Global state
// ---------------------------------------------------------------------------

let globalRingBuffer: RingBuffer | null = null
let globalDiskBuffer: DiskBuffer | null = null
let globalOptions: LoggerOptions = { ...DEFAULT_LOGGER_OPTIONS }

// ---------------------------------------------------------------------------
// Initialization
// ---------------------------------------------------------------------------

/** Read a numeric env var with fallback. */
function readEnvInt(key: string, fallback: number): number {
  try {
    const raw = (import.meta.env[key] as string | undefined) ?? ""
    if (raw !== "") {
      const n = parseInt(raw, 10)
      if (!isNaN(n) && n > 0) return n
    }
  } catch {
    // import.meta.env not available (test environment).
  }
  return fallback
}

/** Read a log-level env var with fallback. */
function readEnvLevel(key: string, fallback: LogLevel): LogLevel {
  try {
    const raw = (import.meta.env[key] as string | undefined) ?? ""
    const normalized = raw.trim().toLowerCase()
    if (["debug", "info", "warn", "error"].includes(normalized)) {
      return normalized as LogLevel
    }
  } catch {
    // import.meta.env not available.
  }
  return fallback
}

/**
 * Initialize the logging subsystem.
 *
 * Reads configuration from Vite env vars (with defaults) and sets up the
 * global RingBuffer and DiskBuffer instances.  Safe to call multiple times
 * (subsequent calls are no-ops).
 */
export function initLogger(options?: Partial<LoggerOptions>): void {
  // Idempotent.
  if (globalRingBuffer) return

  globalOptions = {
    ringSize:
      options?.ringSize ??
      readEnvInt("VITE_LOG_RING_SIZE", DEFAULT_LOGGER_OPTIONS.ringSize),
    diskMaxSize:
      options?.diskMaxSize ??
      readEnvInt("VITE_LOG_DISK_MAX_SIZE", DEFAULT_LOGGER_OPTIONS.diskMaxSize),
    flushSize:
      options?.flushSize ??
      readEnvInt("VITE_LOG_FLUSH_SIZE", DEFAULT_LOGGER_OPTIONS.flushSize),
    consoleLevel:
      options?.consoleLevel ??
      readEnvLevel("VITE_LOG_CONSOLE_LEVEL", DEFAULT_LOGGER_OPTIONS.consoleLevel),
    bufferLevel:
      options?.bufferLevel ??
      readEnvLevel("VITE_LOG_BUFFER_LEVEL", DEFAULT_LOGGER_OPTIONS.bufferLevel),
  }

  globalRingBuffer = new RingBuffer(globalOptions.ringSize, globalOptions.bufferLevel)
  globalDiskBuffer = new DiskBuffer(globalOptions.diskMaxSize)

  // Wire up the flush handler: when ring buffer is full, flush to disk.
  const origPush = globalRingBuffer.push.bind(globalRingBuffer)
  globalRingBuffer.push = function (record) {
    origPush(record)
    if (globalRingBuffer!.size >= globalOptions.flushSize) {
      const flushed = globalRingBuffer!.flush(globalOptions.flushSize)
      if (flushed.length > 0 && globalDiskBuffer) {
        globalDiskBuffer.write(flushed).catch(() => {
          // Silently degrade — entries are already removed from ring,
          // but this is acceptable per the design (disk is best-effort).
        })
      }
    }
  }

  // Warm up TraceManager (generates/stores trace_id).
  traceManager.getTraceId()
}

/** Return the shared RingBuffer (must call initLogger first). */
export function getRingBuffer(): RingBuffer {
  if (!globalRingBuffer) throw new Error("Logger not initialized. Call initLogger() first.")
  return globalRingBuffer
}

/** Return the shared DiskBuffer (must call initLogger first). */
export function getDiskBuffer(): DiskBuffer {
  if (!globalDiskBuffer) throw new Error("Logger not initialized. Call initLogger() first.")
  return globalDiskBuffer
}

/** Return current logger options. */
export function getLoggerOptions(): LoggerOptions {
  return { ...globalOptions }
}
