<script setup lang="ts">
defineProps<{
  visible: boolean
  title: string
  message?: string
  confirmText?: string
  cancelText?: string
  danger?: boolean
}>()

const emit = defineEmits<{
  confirm: []
  cancel: []
}>()

function handleOverlayClick(event: MouseEvent) {
  // Only close if clicking the overlay itself, not the dialog content
  if ((event.target as HTMLElement).dataset.testid === "confirm-dialog-overlay") {
    emit("cancel")
  }
}
</script>

<template>
  <div
    v-if="visible"
    data-testid="confirm-dialog-overlay"
    class="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4"
    @click="handleOverlayClick"
  >
    <div
      class="w-full max-w-sm rounded-lg bg-white shadow-lg"
      @click.stop
    >
      <!-- Header -->
      <div class="border-b border-neutral-100 px-5 py-4">
        <h3 class="font-display text-base font-semibold text-neutral-900">{{ title }}</h3>
      </div>

      <!-- Body -->
      <div class="px-5 py-4">
        <slot>
          <p v-if="message" class="text-sm leading-6 text-neutral-600">{{ message }}</p>
        </slot>
      </div>

      <!-- Footer -->
      <div class="flex justify-end gap-2.5 border-t border-neutral-100 px-5 py-4">
        <button
          data-testid="confirm-dialog-cancel-btn"
          class="rounded-md border border-neutral-200 bg-white px-4 py-2 text-sm font-medium text-neutral-700 transition-colors hover:bg-neutral-50 active:bg-neutral-100"
          @click="emit('cancel')"
        >
          {{ cancelText ?? "取消" }}
        </button>
        <button
          data-testid="confirm-dialog-confirm-btn"
          class="rounded-md px-4 py-2 text-sm font-medium text-white transition-colors"
          :class="danger ? 'bg-red-600 hover:bg-red-700 active:bg-red-800' : 'bg-brand-700 hover:bg-brand-800 active:bg-brand-900'"
          @click="emit('confirm')"
        >
          {{ confirmText ?? "确认" }}
        </button>
      </div>
    </div>
  </div>
</template>
