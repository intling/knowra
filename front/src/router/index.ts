import { createRouter, createWebHistory } from "vue-router"

import ChatLayout from "../components/layout/ChatLayout.vue"
import VerificationView from "../views/VerificationView.vue"

const router = createRouter({
  history: createWebHistory(),
  routes: [
    {
      path: "/",
      name: "home",
      component: ChatLayout,
    },
    {
      path: "/verify",
      name: "verify",
      component: VerificationView,
    },
    {
      path: "/home",
      redirect: "/",
    },
    {
      path: "/chat",
      redirect: "/",
    },
  ],
})

export default router
