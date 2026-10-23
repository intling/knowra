<script setup lang="ts">
import AdminError from "./AdminError.vue"
import { formatTime } from "../../shared/admin"
defineProps<{
  loading: boolean
  error: string
  traceId?: string | null
  loadedAt: string
}>()
defineEmits<{ refresh: [] }>()
</script>
<template>
  <div class="mb-5 flex flex-wrap items-center justify-between gap-3">
    <p class="text-xs text-ink-muted">
      {{
        loadedAt
          ? (error ? "旧数据 · " : "数据截至 ") + formatTime(loadedAt)
          : loading
            ? "正在读取…"
            : "尚未取得数据"
      }}
    </p>
    <button
      data-testid="admin-refresh"
      class="account-secondary"
      :disabled="loading"
      @click="$emit('refresh')"
    >
      {{ loading ? "刷新中…" : "刷新" }}
    </button>
  </div>
  <AdminError :message="error" :trace-id="traceId" />
  <div
    v-if="loading && !loadedAt"
    role="status"
    class="account-card mb-5 animate-pulse text-sm text-ink-muted"
  >
    正在加载管理数据…
  </div>
</template>
