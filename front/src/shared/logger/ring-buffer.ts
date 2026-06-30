/** Fixed-size in-memory ring buffer for structured log records. */

import type { LogLevel, LogRecord } from "./types"
import { LOG_LEVEL_VALUES } from "./types"

/**
 * Thread-safe ring buffer that stores LogRecords up to a configured capacity.
 * When full, oldest entries are overwritten.
 */
export class RingBuffer {
  private _buffer: (LogRecord | null)[]
  private _writeIndex = 0
  private _count = 0

  constructor(
    private _capacity: number,
    private _minLevel: LogLevel = "info",
  ) {
    this._buffer = new Array(_capacity).fill(null)
  }

  /** Number of entries currently stored. */
  get size(): number {
    return this._count
  }

  /** Maximum entries the buffer can hold. */
  get capacity(): number {
    return this._capacity
  }

  /**
   * Append a log record to the buffer.
   * Records below `_minLevel` are silently dropped.
   * When the buffer is full the oldest entry is overwritten.
   */
  push(record: LogRecord): void {
    if (LOG_LEVEL_VALUES[record.level] < LOG_LEVEL_VALUES[this._minLevel]) {
      return
    }
    this._buffer[this._writeIndex] = record
    this._writeIndex = (this._writeIndex + 1) % this._capacity
    if (this._count < this._capacity) {
      this._count++
    }
  }

  /**
   * Return all entries in chronological order (oldest first).
   */
  getAll(): LogRecord[] {
    if (this._count === 0) return []

    const result: LogRecord[] = []
    // Oldest entry is at writeIndex when buffer is full,
    // or at 0 when buffer is not yet full.
    const start = this._count < this._capacity ? 0 : this._writeIndex

    for (let i = 0; i < this._count; i++) {
      const idx = (start + i) % this._capacity
      const record = this._buffer[idx]
      if (record) result.push(record)
    }

    return result
  }

  /**
   * Flush (remove and return) the oldest *count* entries from the buffer.
   * Returns fewer entries if the buffer contains fewer than *count*.
   */
  flush(count: number): LogRecord[] {
    const entries = this.getAll()
    const toFlush = entries.slice(0, count)
    const remaining = entries.slice(count)

    // Rebuild buffer with remaining entries.
    this._buffer = new Array(this._capacity).fill(null)
    this._writeIndex = 0
    this._count = 0
    for (const record of remaining) {
      this._buffer[this._writeIndex] = record
      this._writeIndex = (this._writeIndex + 1) % this._capacity
      this._count++
    }

    return toFlush
  }

  /** Clear all entries. */
  clear(): void {
    this._buffer = new Array(this._capacity).fill(null)
    this._writeIndex = 0
    this._count = 0
  }
}
