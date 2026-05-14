import { defineStore } from "pinia"

import { fetchHealth, type HealthStatus } from "../api/health"

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

      try {
        this.health = await fetchHealth()
        this.lastHealthCheckedAt = new Date()
      } catch (error) {
        this.health = null
        this.healthError =
          error instanceof Error ? error.message : "无法获取后端健康状态"
      } finally {
        this.isHealthLoading = false
      }
    },
  },
})
