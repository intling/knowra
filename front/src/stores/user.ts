import { defineStore } from "pinia"

import { getCurrentUser, type User } from "../api/users"

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

      try {
        this.currentUser = await getCurrentUser()
      } catch (error) {
        this.currentUser = null
        this.userError =
          error instanceof Error ? error.message : "Unable to load current user"
      } finally {
        this.isUserLoading = false
      }
    },
  },
})
