import { createRouter, createWebHistory } from "vue-router"

import HomeView from "../views/HomeView.vue"
import VerificationView from "../views/VerificationView.vue"
import ChatView from "../views/ChatView.vue"

const router = createRouter({
  history: createWebHistory(),
  routes: [
    {
      path: "/",
      name: "home",
      component: HomeView,
    },
    {
      path: "/verify",
      name: "verify",
      component: VerificationView,
    },
    {
      path: "/chat",
      name: "chat",
      component: ChatView,
    },
  ],
})

export default router
