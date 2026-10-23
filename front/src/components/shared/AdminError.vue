<script setup lang="ts">
import { ref } from "vue"
defineProps<{ message: string; traceId?: string | null }>()
const copied = ref(false)
async function copy(value: string) {
  try {
    await navigator.clipboard.writeText(value)
    copied.value = true
  } catch {
    copied.value = false
  }
}
</script>
<template>
  <div
    v-if="message"
    role="alert"
    class="my-4 rounded-xl border border-cite/25 bg-cite/5 p-4 text-sm leading-6 text-cite"
  >
    <p>{{ message }}</p>
    <div v-if="traceId" class="mt-2 flex flex-wrap items-center gap-2 text-xs">
      <span class="break-all">追踪标识：{{ traceId }}</span
      ><button class="underline" @click="copy(traceId)">
        {{ copied ? "已复制" : "复制追踪标识" }}
      </button>
    </div>
    <slot />
  </div>
</template>
