import { createRouter, createWebHistory, type RouterHistory } from "vue-router"

import ChatLayout from "../components/layout/ChatLayout.vue"
import VerificationView from "../views/VerificationView.vue"
import LoginView from "../views/LoginView.vue"
import RegisterView from "../views/RegisterView.vue"
import AccountView from "../views/AccountView.vue"
import AdminUsersView from "../views/AdminUsersView.vue"
import AdminModelsView from "../views/AdminModelsView.vue"
import AdminOverviewView from "../views/AdminOverviewView.vue"
import AdminJobsView from "../views/AdminJobsView.vue"
import AdminAuditView from "../views/AdminAuditView.vue"
import AdminSystemView from "../views/AdminSystemView.vue"
import { useUserStore } from "../stores/user"
import { sanitizeRedirect } from "../shared/auth/redirect"

export function createAppRouter(history: RouterHistory = createWebHistory()) {
  const router = createRouter({
    history,
    routes: [
      {
        path: "/admin",
        redirect: "/admin/overview",
        meta: { requiresAuth: true },
      },
      ...[
        {
          path: "/admin/overview",
          name: "admin-overview",
          component: AdminOverviewView,
          permission: "operations:read",
        },
        {
          path: "/admin/jobs",
          name: "admin-jobs",
          component: AdminJobsView,
          permission: "operations:read",
        },
        {
          path: "/admin/audit",
          name: "admin-audit",
          component: AdminAuditView,
          permission: "audit:read",
        },
        {
          path: "/admin/system",
          name: "admin-system",
          component: AdminSystemView,
          permission: "operations:read",
        },
      ].map(({ permission, ...route }) => ({
        ...route,
        meta: { requiresAuth: true, permission },
      })),
      {
        path: "/admin/models",
        name: "admin-models",
        component: AdminModelsView,
        meta: { requiresAuth: true, permission: "models:manage" },
      },
      {
        path: "/",
        name: "home",
        component: ChatLayout,
        meta: { requiresAuth: true },
      },
      {
        path: "/verify",
        name: "verify",
        component: VerificationView,
        meta: { requiresAuth: true },
      },
      {
        path: "/account",
        name: "account",
        component: AccountView,
        meta: { requiresAuth: true },
      },
      {
        path: "/admin/users",
        name: "admin-users",
        component: AdminUsersView,
        meta: { requiresAuth: true, permission: "users:manage" },
      },
      {
        path: "/login",
        name: "login",
        component: LoginView,
        meta: { guestOnly: true },
      },
      {
        path: "/register",
        name: "register",
        component: RegisterView,
        meta: { guestOnly: true },
      },
      { path: "/home", redirect: "/" },
      { path: "/chat", redirect: "/" },
    ],
  })
  router.beforeEach(async (to) => {
    const user = useUserStore()
    await user.ensureSession()
    if (user.status === "anonymous" && to.meta.requiresAuth) {
      return {
        name: "login",
        query: { redirect: sanitizeRedirect(to.fullPath) },
      }
    }
    if (user.status === "authenticated" && to.meta.guestOnly) return "/"
    return true
  })
  return router
}
export default createAppRouter()
