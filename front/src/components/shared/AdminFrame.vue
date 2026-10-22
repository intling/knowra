<script setup lang="ts">
import AccountFrame from "./AccountFrame.vue"
defineProps<{ title: string; subtitle?: string }>()
</script>

<template>
  <AccountFrame :title="title" :subtitle="subtitle">
    <nav
      class="mb-6 flex flex-wrap gap-2 border-b border-line pb-4 text-sm"
      aria-label="后台导航"
    >
      <RouterLink
        to="/admin/users"
        class="rounded-lg px-3 py-2 text-ink-muted hover:bg-paper-deep"
        active-class="!bg-brand-50 !text-brand-700"
        >用户管理</RouterLink
      >
      <RouterLink
        to="/admin/models"
        class="rounded-lg px-3 py-2 text-ink-muted hover:bg-paper-deep"
        active-class="!bg-brand-50 !text-brand-700"
        >模型配置</RouterLink
      >
      <RouterLink to="/" class="ml-auto px-3 py-2 text-brand-700"
        >返回知识书房 ↗</RouterLink
      >
    </nav>
    <slot />
  </AccountFrame>
</template>
