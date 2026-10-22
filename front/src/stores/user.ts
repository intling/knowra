import { defineStore } from "pinia"
import { ref } from "vue"

import * as authApi from "../api/auth"
import { ApiError } from "../api/client"
import {
  changeMyPassword,
  getCurrentUser,
  updateMyProfile,
  type User,
} from "../api/users"
import { useChatStore } from "./chat"

export const LOGOUT_SIGNAL_KEY = "knowra:auth:logout"
export const useUserStore = defineStore("user", () => {
  const status = ref<"unknown" | "authenticated" | "anonymous" | "error">(
    "unknown",
  )
  const currentUser = ref<User | null>(null)
  const userError = ref<string | null>(null)
  const isUserLoading = ref(false)
  let pending: Promise<void> | null = null
  let epoch = 0

  function acceptUser(user: User) {
    currentUser.value = user
    status.value = "authenticated"
    userError.value = null
    useChatStore().bindUser(user.id)
  }
  function handleUnauthorized() {
    epoch++
    currentUser.value = null
    status.value = "anonymous"
    userError.value = null
    useChatStore().bindUser(null)
  }
  function broadcastLogout() {
    try {
      localStorage.setItem(LOGOUT_SIGNAL_KEY, `${Date.now()}:${Math.random()}`)
    } catch {
      /* Storage may be unavailable. */
    }
  }
  async function ensureSession({ force = false } = {}): Promise<void> {
    if (pending) return pending
    if (!force && status.value !== "unknown") return
    const requestEpoch = epoch
    isUserLoading.value = true
    pending = (async () => {
      try {
        const user = await getCurrentUser()
        if (requestEpoch === epoch) acceptUser(user)
      } catch (error) {
        if (requestEpoch !== epoch) return
        if (error instanceof ApiError && error.status === 401)
          handleUnauthorized()
        else {
          currentUser.value = null
          useChatStore().bindUser(null)
          status.value = "error"
          userError.value =
            error instanceof Error
              ? error.message
              : "暂时无法确认登录状态，请重试"
        }
      } finally {
        pending = null
        isUserLoading.value = false
      }
    })()
    return pending
  }
  async function login(payload: authApi.LoginRequest) {
    const requestEpoch = ++epoch
    const user = await authApi.login(payload)
    if (requestEpoch === epoch) acceptUser(user)
  }
  async function register(payload: authApi.RegisterRequest) {
    const requestEpoch = ++epoch
    const user = await authApi.register(payload)
    if (requestEpoch === epoch) acceptUser(user)
  }
  async function logout() {
    await authApi.logout()
    handleUnauthorized()
    broadcastLogout()
  }
  async function updateProfile(payload: { display_name: string }) {
    const requestEpoch = epoch
    const user = await updateMyProfile(payload)
    if (requestEpoch === epoch) acceptUser(user)
  }
  async function changePassword(payload: {
    current_password: string
    new_password: string
  }) {
    await changeMyPassword(payload)
    handleUnauthorized()
    broadcastLogout()
  }
  function hasPermission(permission: string) {
    return currentUser.value?.permissions.includes(permission) ?? false
  }
  return {
    status,
    currentUser,
    userError,
    isUserLoading,
    ensureSession,
    login,
    register,
    logout,
    updateProfile,
    changePassword,
    handleUnauthorized,
    hasPermission,
    loadCurrentUser: () => ensureSession({ force: true }),
  }
})
