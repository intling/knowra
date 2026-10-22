import { watch } from "vue"
import type { Router } from "vue-router"

import { setUnauthorizedHandler } from "../api/client"
import { sanitizeRedirect } from "../shared/auth/redirect"
import { LOGOUT_SIGNAL_KEY, useUserStore } from "../stores/user"

export function installAuthHandling(router: Router): () => void {
  const user = useUserStore()
  function toLogin(reason = "expired") {
    const route = router.currentRoute.value
    if (
      route.meta.guestOnly ||
      route.name === "login" ||
      route.name === "register"
    )
      return
    void router.replace({
      name: "login",
      query: { redirect: sanitizeRedirect(route.fullPath), reason },
    })
  }
  function unauthorized() {
    user.handleUnauthorized()
    toLogin()
  }
  setUnauthorizedHandler(unauthorized)
  const stop = watch(
    () => user.status,
    (status) => {
      if (status === "anonymous" && router.currentRoute.value.meta.requiresAuth)
        toLogin()
    },
  )
  function storage(event: StorageEvent) {
    if (event.key === LOGOUT_SIGNAL_KEY && event.newValue) unauthorized()
  }
  window.addEventListener("storage", storage)
  return () => {
    stop()
    setUnauthorizedHandler(null)
    window.removeEventListener("storage", storage)
  }
}
