/** IndexedDB-backed persistent storage for log records with size-based rolling. */

import type { LogRecord } from "./types"

const DB_NAME = "knowra_logs"
const DB_VERSION = 1
const STORE_NAME = "log_chunks"

interface LogChunk {
  id: number
  records: LogRecord[]
  byteSize: number
  createdAt: number
}

/** Estimate the byte size of a serialized chunk (approximate). */
function estimateSize(records: LogRecord[]): number {
  try {
    return new Blob([JSON.stringify(records)]).size
  } catch {
    // Fallback: character count as rough estimate.
    return JSON.stringify(records).length
  }
}

/** Open (or create) the IndexedDB database. */
function openDb(): Promise<IDBDatabase> {
  return new Promise((resolve, reject) => {
    const req = indexedDB.open(DB_NAME, DB_VERSION)
    req.onupgradeneeded = () => {
      const db = req.result
      if (!db.objectStoreNames.contains(STORE_NAME)) {
        db.createObjectStore(STORE_NAME, { keyPath: "id", autoIncrement: true })
      }
    }
    req.onsuccess = () => resolve(req.result)
    req.onerror = () => reject(req.error)
  })
}

/**
 * Persistence layer that stores log chunks in IndexedDB.
 * Total size is bounded by a configurable max; oldest chunks are
 * deleted when the limit is exceeded.  All errors are silently caught.
 */
export class DiskBuffer {
  constructor(private _maxSize: number = 5 * 1024 * 1024) {}

  /**
   * Write a batch of log records as a new chunk.
   * Silently degrades on failure (e.g. IndexedDB unavailable in privacy mode).
   */
  async write(records: LogRecord[]): Promise<void> {
    if (records.length === 0) return

    try {
      const db = await openDb()
      const byteSize = estimateSize(records)

      const chunk: Omit<LogChunk, "id"> = {
        records,
        byteSize,
        createdAt: Date.now(),
      }

      await new Promise<void>((resolve, reject) => {
        const tx = db.transaction(STORE_NAME, "readwrite")
        const store = tx.objectStore(STORE_NAME)
        store.add(chunk)
        tx.oncomplete = () => resolve()
        tx.onerror = () => reject(tx.error)
      })

      db.close()

      // Enforce size limit.
      await this._evictIfNeeded()
    } catch {
      // Silently degrade — caller continues without persistence.
    }
  }

  /** Read all stored chunks and return their records in insertion order. */
  async readAll(): Promise<LogRecord[]> {
    try {
      const db = await openDb()
      const chunks = await new Promise<LogChunk[]>((resolve, reject) => {
        const tx = db.transaction(STORE_NAME, "readonly")
        const store = tx.objectStore(STORE_NAME)
        const req = store.getAll()
        req.onsuccess = () => resolve(req.result)
        req.onerror = () => reject(req.error)
      })
      db.close()

      // Sort by creation time, then flatten.
      const sorted = chunks.sort((a, b) => a.createdAt - b.createdAt)
      return sorted.flatMap((c) => c.records)
    } catch {
      return []
    }
  }

  /** Delete excess chunks until total size ≤ maxSize. */
  private async _evictIfNeeded(): Promise<void> {
    try {
      const db = await openDb()

      const chunks = await new Promise<LogChunk[]>((resolve, reject) => {
        const tx = db.transaction(STORE_NAME, "readonly")
        const store = tx.objectStore(STORE_NAME)
        const req = store.getAll()
        req.onsuccess = () => resolve(req.result)
        req.onerror = () => reject(req.error)
      })

      const sorted = chunks.sort((a, b) => a.createdAt - b.createdAt)
      let totalSize = sorted.reduce((sum, c) => sum + c.byteSize, 0)

      const toDelete: number[] = []
      for (const chunk of sorted) {
        if (totalSize <= this._maxSize) break
        toDelete.push(chunk.id)
        totalSize -= chunk.byteSize
      }

      db.close()

      if (toDelete.length > 0) {
        const db2 = await openDb()
        await new Promise<void>((resolve, reject) => {
          const tx = db2.transaction(STORE_NAME, "readwrite")
          const store = tx.objectStore(STORE_NAME)
          for (const id of toDelete) {
            store.delete(id)
          }
          tx.oncomplete = () => resolve()
          tx.onerror = () => reject(tx.error)
        })
        db2.close()
      }
    } catch {
      // Best-effort eviction.
    }
  }
}
