<script setup lang="ts">
defineProps<{ title: string; subtitle?: string; compact?: boolean }>()
</script>

<template>
  <main class="min-h-dvh bg-paper px-4 py-8 text-ink sm:py-12">
    <div
      class="mx-auto w-full min-w-0"
      :class="compact ? 'max-w-md' : 'max-w-3xl'"
    >
      <RouterLink
        to="/"
        class="inline-flex items-center gap-2 text-sm font-semibold text-brand-700"
      >
        <span
          class="grid size-8 place-items-center rounded-lg bg-brand-700 font-display text-lg text-white"
          aria-hidden="true"
          >知</span
        >
        知寻 · KNOWRA
      </RouterLink>
      <header class="my-8">
        <h1 class="font-display text-3xl font-semibold">{{ title }}</h1>
        <p v-if="subtitle" class="mt-3 text-sm leading-6 text-ink-muted">
          {{ subtitle }}
        </p>
      </header>
      <slot />
    </div>
  </main>
</template>
