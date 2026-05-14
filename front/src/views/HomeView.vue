<script setup lang="ts">
import { computed, onMounted } from "vue"

import { useAppStore } from "../stores/app"

const appStore = useAppStore()

const statusLabel = computed(() => {
  if (appStore.isHealthLoading) {
    return "检查中"
  }

  if (appStore.health?.status === "ok") {
    return "正常"
  }

  return "未连接"
})

onMounted(() => {
  void appStore.refreshHealth()
})
</script>

<template>
  <section class="grid gap-6">
    <div class="grid gap-2">
      <p class="text-sm font-medium text-zinc-500">个人知识库 AI 助手</p>
      <h1 class="text-3xl font-semibold tracking-normal text-zinc-950">
        knowra
      </h1>
    </div>

    <div
      class="max-w-xl rounded-lg border border-zinc-200 bg-white p-5 shadow-sm"
    >
      <div class="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h2 class="text-base font-semibold text-zinc-950">后端服务</h2>
          <p class="mt-1 text-sm text-zinc-500">
            环境：{{ appStore.health?.environment ?? "local" }}
          </p>
        </div>
        <span
          class="rounded-full px-3 py-1 text-sm font-medium"
          :class="
            appStore.health?.status === 'ok'
              ? 'bg-emerald-50 text-emerald-700'
              : 'bg-zinc-100 text-zinc-600'
          "
        >
          {{ statusLabel }}
        </span>
      </div>

      <p v-if="appStore.healthError" class="mt-4 text-sm text-red-600">
        {{ appStore.healthError }}
      </p>

      <div class="mt-5 flex items-center gap-3">
        <button
          class="rounded-md bg-zinc-950 px-4 py-2 text-sm font-medium text-white transition hover:bg-zinc-800 disabled:cursor-not-allowed disabled:bg-zinc-400"
          type="button"
          :disabled="appStore.isHealthLoading"
          @click="appStore.refreshHealth"
        >
          刷新状态
        </button>
        <p v-if="appStore.lastHealthCheckedAt" class="text-sm text-zinc-500">
          {{ appStore.lastHealthCheckedAt.toLocaleTimeString() }}
        </p>
      </div>
    </div>
  </section>
</template>
