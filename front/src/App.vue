<script setup lang="ts">
import { computed } from "vue"
import { RouterView, useRoute } from "vue-router"
import { useUserStore } from "./stores/user"

const user = useUserStore()
const route = useRoute()
const canRender = computed(
  () => !route.meta.requiresAuth || user.status === "authenticated",
)
</script>

<template>
  <RouterView v-if="canRender" v-slot="{ Component }">
    <component :is="Component" :key="user.currentUser?.id ?? 'guest'" />
  </RouterView>
  <main v-else class="grid min-h-dvh place-items-center bg-paper px-4 text-ink">
    <div class="max-w-md text-center">
      <template v-if="user.status === 'error'">
        <h1 class="font-display text-2xl">暂时无法连接知识书房</h1>
        <p role="alert" class="my-4 text-sm text-ink-muted">
          {{ user.userError }}
        </p>
        <button
          data-testid="session-retry"
          class="account-primary"
          :disabled="user.isUserLoading"
          @click="user.ensureSession({ force: true })"
        >
          {{ user.isUserLoading ? "连接中…" : "重试" }}
        </button>
      </template>
      <p v-else role="status" class="text-sm text-ink-muted">
        正在确认登录状态…
      </p>
    </div>
  </main>
</template>
