import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"
import "fake-indexeddb/auto"
import type { LogRecord } from "../types"
import { DiskBuffer } from "../disk-buffer"

const DB_NAME = "knowra_logs"

function makeRecord(overrides: Partial<LogRecord> = {}): LogRecord {
  return {
    ts: Date.now(),
    level: "info",
    trace_id: "01JFZ8AAAAAA-0000-0000-0000-000000000000",
    module: "test:disk",
    message: "disk write test",
    ...overrides,
  }
}

/** Helper to delete the test IndexedDB database. */
function deleteTestDb(): Promise<void> {
  return new Promise((resolve, reject) => {
    const req = indexedDB.deleteDatabase(DB_NAME)
    req.onsuccess = () => resolve()
    req.onerror = () => reject(req.error)
    req.onblocked = () => resolve() // ignore blocked
  })
}

describe("DiskBuffer", () => {
  beforeEach(async () => {
    await deleteTestDb()
  })

  afterEach(async () => {
    await deleteTestDb()
  })

  describe("11.1 write(chunk) 将日志批量写入 IndexedDB", () => {
    it("写入后 readAll 可读取相同条目", async () => {
      const disk = new DiskBuffer(10 * 1024 * 1024)
      const records = [makeRecord({ message: "msg-1" }), makeRecord({ message: "msg-2" })]

      await disk.write(records)

      const all = await disk.readAll()
      expect(all).toHaveLength(2)
      expect(all[0].message).toBe("msg-1")
      expect(all[1].message).toBe("msg-2")
    })
  })

  describe("11.2 总大小超过 LOG_DISK_MAX_SIZE 时删除最旧 chunk", () => {
    it("超过上限时删除最旧 chunk", async () => {
      // Use a small maxSize so eviction triggers.
      const disk = new DiskBuffer(100) // very small

      // Write several chunks — each is well over 100 bytes so eviction
      // will keep trimming.
      for (let i = 0; i < 5; i++) {
        await disk.write([
          makeRecord({ message: `batch-${i}-a` }),
          makeRecord({ message: `batch-${i}-b` }),
        ])
      }

      const all = await disk.readAll()
      // Most recent chunks should survive; older ones evicted.
      // We can't guarantee exact count since sizes vary, but we should
      // have fewer records than total written (10).
      expect(all.length).toBeLessThan(10)
      // The oldest messages should NOT be present.
      const messages = all.map((r) => r.message)
      expect(messages).not.toContain("batch-0-a")
    })
  })

  describe("11.3 IndexedDB 写入失败时静默降级", () => {
    it("写入失败时不抛异常，后续操作正常", async () => {
      const disk = new DiskBuffer(5 * 1024 * 1024)

      // Stub indexedDB.open to fail.
      const origOpen = indexedDB.open.bind(indexedDB)
      vi.spyOn(indexedDB, "open").mockImplementation(() => {
        const req = origOpen("__invalid__")
        // Immediately trigger error on next tick.
        setTimeout(() => {
          Object.defineProperty(req, "error", { value: new DOMException("test", "UnknownError") })
        }, 0)
        return req
      })

      // Should not throw.
      await expect(
        disk.write([makeRecord({ message: "should-be-silent" })]),
      ).resolves.toBeUndefined()

      vi.restoreAllMocks()

      // Subsequent operations should still work.
      const all = await disk.readAll()
      expect(Array.isArray(all)).toBe(true)
    })
  })

  describe("11.4 readAll 按时间顺序返回全部持久化日志", () => {
    it("多个 chunk 按创建时间排序合并返回", async () => {
      const disk = new DiskBuffer(10 * 1024 * 1024)

      await disk.write([makeRecord({ message: "first-batch" })])
      // Small delay to ensure different timestamps.
      await new Promise((r) => setTimeout(r, 10))
      await disk.write([makeRecord({ message: "second-batch" })])

      const all = await disk.readAll()
      expect(all).toHaveLength(2)
      expect(all[0].message).toBe("first-batch")
      expect(all[1].message).toBe("second-batch")
    })
  })

  describe("write with empty records", () => {
    it("空数组不写入任何内容", async () => {
      const disk = new DiskBuffer(5 * 1024 * 1024)
      await disk.write([])
      const all = await disk.readAll()
      expect(all).toHaveLength(0)
    })
  })
})
