import { defineStore } from "pinia"

import { createLogger, getRingBuffer } from "../shared/logger"
import { fetchHealth, type HealthStatus } from "../api/health"

/** Lazy logger — getRingBuffer() is only available after main.ts initLogger(). */
let _logger: ReturnType<typeof createLogger> | null = null
function log() {
  if (!_logger) _logger = createLogger("stores:app", getRingBuffer())
  return _logger
}

interface AppState {
  appName: string
  health: HealthStatus | null
  isHealthLoading: boolean
  healthError: string | null
  lastHealthCheckedAt: Date | null
}

export const useAppStore = defineStore("app", {
  state: (): AppState => ({
    appName: "knowra",
    health: null,
    isHealthLoading: false,
    healthError: null,
    lastHealthCheckedAt: null,
  }),
  actions: {
    async refreshHealth() {
      this.isHealthLoading = true
      this.healthError = null
      log().info("开始检查后端健康状态")

      try {
        this.health = await fetchHealth()
        this.lastHealthCheckedAt = new Date()
        log().info("后端健康检查通过", this.health as unknown as Record<string, unknown>)
      } catch (error) {
        this.health = null
        this.healthError =
          error instanceof Error ? error.message : "无法获取后端健康状态"
        log().error("后端健康检查失败", error)
      } finally {
        this.isHealthLoading = false
      }
    },
  },
})
