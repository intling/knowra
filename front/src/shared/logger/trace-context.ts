/** Page-level trace ID generation and management using UUID7 and sessionStorage. */

const STORAGE_KEY = "knowra_trace_id"

/**
 * Generate a UUID7 string (time-ordered, per draft RFC 9562).
 *
 * UUID7 layout (128 bits):
 * - bytes 0-5: 48-bit Unix timestamp (milliseconds, big-endian)
 * - byte  6:   4 bits version (7) + 4 high bits of rand_a
 * - byte  7:   8 bits rand_a
 * - byte  8:   2 bits variant (10xx) + 6 high bits of rand_b
 * - bytes 9-15: remaining rand_b
 */
function generateUuid7(): string {
  const tsMs = Date.now() & 0xffffffffffff // 48 bits
  const randBytes = new Uint8Array(10)
  crypto.getRandomValues(randBytes)

  const hex = new Array<string>(16)

  // Bytes 0-5: timestamp (12 hex chars)
  for (let i = 0; i < 6; i++) {
    hex[i] = ((tsMs >> ((5 - i) * 8)) & 0xff).toString(16).padStart(2, "0")
  }

  // Byte 6: version 7 (0x70 | high 4 bits of rand[0])
  hex[6] = (0x70 | (randBytes[0] & 0x0f)).toString(16).padStart(2, "0")
  // Byte 7: low 8 bits of rand[0]… actually rand[1]
  hex[7] = randBytes[1].toString(16).padStart(2, "0")

  // Byte 8: variant 10xx (0x80 | high 6 bits of rand[2])
  hex[8] = (0x80 | (randBytes[2] & 0x3f)).toString(16).padStart(2, "0")
  // Bytes 9-15: remaining rand[3..9]
  for (let i = 3; i < 10; i++) {
    hex[6 + i] = randBytes[i].toString(16).padStart(2, "0")
  }

  const h = hex.join("")
  return `${h.slice(0, 8)}-${h.slice(8, 12)}-${h.slice(12, 16)}-${h.slice(16, 20)}-${h.slice(20, 32)}`
}

/**
 * Manages page-level trace ID.
 *
 * On first access generates a UUID7, stores it in sessionStorage,
 * and returns it. Subsequent accesses return the stored value.
 */
export class TraceManager {
  private _traceId: string | null = null

  /** Return the current page trace ID, generating one if necessary. */
  getTraceId(): string {
    if (this._traceId) return this._traceId

    // Try sessionStorage first.
    try {
      const stored = sessionStorage.getItem(STORAGE_KEY)
      if (stored) {
        this._traceId = stored
        return stored
      }
    } catch {
      // sessionStorage unavailable (e.g. privacy mode) — silently ignore.
    }

    const newId = generateUuid7()
    this._traceId = newId

    try {
      sessionStorage.setItem(STORAGE_KEY, newId)
    } catch {
      // Non-critical.
    }

    return newId
  }
}

/** Singleton instance for app-wide use. */
export const traceManager = new TraceManager()
