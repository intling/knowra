<script setup lang="ts">
import { RouterLink, RouterView } from "vue-router"
</script>

<template>
  <div class="min-h-screen overflow-x-hidden bg-zinc-50 text-zinc-950">
    <header class="border-b border-zinc-200 bg-white">
      <div
        class="mx-auto flex h-14 max-w-6xl items-center justify-between px-4"
      >
        <RouterLink class="text-base font-semibold" to="/">knowra</RouterLink>
      </div>
    </header>
    <main class="mx-auto max-w-6xl overflow-hidden px-4 py-8">
      <RouterView />
    </main>
  </div>
</template>
