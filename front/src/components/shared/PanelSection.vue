<script setup lang="ts">
/**
 * PanelSection — 回答区信息面板的统一外壳。
 *
 * 可折叠时，头部是一个 div 行：折叠按钮（`${testid}-toggle`）与 actions 区并列，
 * 避免把复制等按钮嵌套在折叠按钮内部。
 * variant="flat" 用于「检索详情」内的平铺子面板（无卡片描边/阴影）。
 */
import { ref } from "vue"

import { uniqueId } from "../../shared/a11y/focus"

const props = withDefaults(
  defineProps<{
    title: string
    collapsible?: boolean
    defaultExpanded?: boolean
    testid?: string
    variant?: "card" | "flat"
  }>(),
  {
    collapsible: false,
    defaultExpanded: true,
    testid: "panel-section",
    variant: "card",
  },
)

const emit = defineEmits<{
  (e: "toggle", expanded: boolean): void
}>()

const isExpanded = ref(props.defaultExpanded)
const bodyId = uniqueId("panel")

function toggle() {
  if (!props.collapsible) return
  isExpanded.value = !isExpanded.value
  emit("toggle", isExpanded.value)
}
</script>

<template>
  <section
    :data-testid="testid"
    class="min-w-0 overflow-hidden"
    :class="
      variant === 'card'
        ? 'rounded-[var(--radius-card)] border border-line bg-surface shadow-card'
        : 'border-t border-line first:border-t-0'
    "
  >
    <div class="flex items-center gap-2" :class="{ 'pr-3': $slots.actions }">
      <component
        :is="collapsible ? 'button' : 'div'"
        :type="collapsible ? 'button' : undefined"
        :data-testid="`${testid}-toggle`"
        :aria-expanded="collapsible ? isExpanded : undefined"
        :aria-controls="collapsible ? bodyId : undefined"
        class="flex w-full min-w-0 items-center justify-between gap-2 px-4 py-2.5 text-left"
        :class="{ 'transition-colors hover:bg-neutral-50': collapsible }"
        @click="toggle"
      >
        <span class="flex min-w-0 items-center gap-2">
          <span class="flex size-5 shrink-0 items-center justify-center text-brand-700" aria-hidden="true">
            <slot name="icon" />
          </span>
          <h3 :data-testid="`${testid}-title`" class="font-display text-sm font-semibold text-neutral-700">
            {{ title }}
          </h3>
          <slot name="badge" />
        </span>
        <svg
          v-if="collapsible"
          :data-testid="`${testid}-chevron`"
          class="size-4 shrink-0 text-neutral-400 transition-transform"
          :class="{ 'rotate-180': isExpanded }"
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          stroke-width="2"
          stroke-linecap="round"
          stroke-linejoin="round"
          aria-hidden="true"
        >
          <path d="m6 9 6 6 6-6" />
        </svg>
      </component>
      <div v-if="$slots.actions" class="flex shrink-0 items-center gap-2">
        <slot name="actions" />
      </div>
    </div>

    <div v-if="!collapsible || isExpanded" :id="bodyId" class="border-t border-line/70">
      <slot />
    </div>
  </section>
</template>
