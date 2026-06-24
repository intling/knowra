import { defineStore } from "pinia"

import { createLogger, getRingBuffer } from "../shared/logger"
import { getCurrentUser, type User } from "../api/users"

/** Lazy logger — getRingBuffer() is only available after main.ts initLogger(). */
let _logger: ReturnType<typeof createLogger> | null = null
function log() {
  if (!_logger) _logger = createLogger("stores:user", getRingBuffer())
  return _logger
}

interface UserState {
  currentUser: User | null
  isUserLoading: boolean
  userError: string | null
}

export const useUserStore = defineStore("user", {
  state: (): UserState => ({
    currentUser: null,
    isUserLoading: false,
    userError: null,
  }),
  actions: {
    async loadCurrentUser() {
      this.isUserLoading = true
      this.userError = null
      log().info("开始加载当前用户")

      try {
        this.currentUser = await getCurrentUser()
        log().info("当前用户加载成功", {
          userId: this.currentUser.id,
          displayName: this.currentUser.display_name,
        })
      } catch (error) {
        this.currentUser = null
        this.userError =
          error instanceof Error ? error.message : "Unable to load current user"
        log().error("当前用户加载失败", error)
      } finally {
        this.isUserLoading = false
      }
    },
  },
})
