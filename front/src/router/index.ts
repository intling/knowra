import { createRouter, createWebHistory } from "vue-router"

import HomeView from "../views/HomeView.vue"
import VerificationView from "../views/VerificationView.vue"

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
  ],
})

export default router
