<script setup lang="ts">
import { ref } from "vue"

const props = withDefaults(
  defineProps<{
    messages?: Record<string, unknown>[]
  }>(),
  {
    messages: () => [],
  },
)

// ── Collapse toggle ──
const isExpanded = ref(false)

function toggleExpand() {
  isExpanded.value = !isExpanded.value
}

// ── Copy ──
const copyLabel = ref("复制")

async function handleCopy() {
  try {
    const text = JSON.stringify(props.messages, null, 2)
    await navigator.clipboard.writeText(text)
    copyLabel.value = "已复制"
    setTimeout(() => {
      copyLabel.value = "复制"
    }, 2000)
  } catch {
    copyLabel.value = "复制失败"
    setTimeout(() => {
      copyLabel.value = "复制"
    }, 2000)
  }
}

// ── Helpers ──
function roleLabel(role: unknown): string {
  if (typeof role !== "string") return String(role)
  const map: Record<string, string> = {
    system: "System",
    user: "User",
    assistant: "Assistant",
  }
  return map[role] ?? role
}

function roleBadgeClass(role: unknown): string {
  if (typeof role !== "string") return "bg-neutral-100 text-neutral-600"
  switch (role) {
    case "system":
      return "bg-brand-100 text-brand-700"
    case "user":
      return "bg-emerald-100 text-emerald-700"
    case "assistant":
      return "bg-purple-100 text-purple-700"
    default:
      return "bg-neutral-100 text-neutral-600"
  }
}

function messageContent(msg: Record<string, unknown>): string {
  const content = msg.content
  if (typeof content === "string") return content
  if (Array.isArray(content)) {
    return content
      .map((part: unknown) => {
        if (typeof part === "object" && part !== null && "text" in part) {
          return (part as Record<string, unknown>).text
        }
        return JSON.stringify(part)
      })
      .join("\n")
  }
  return JSON.stringify(content, null, 2)
}

// Count total chars for summary
function totalChars(): number {
  return props.messages.reduce((sum, msg) => {
    return sum + messageContent(msg).length
  }, 0)
}
</script>

<template>
  <div>
    <!-- Toggle header -->
    <button
      data-testid="prompt-toggle"
      class="flex w-full items-center justify-between px-5 py-3 text-left transition hover:bg-neutral-50"
      type="button"
      @click="toggleExpand"
    >
      <div class="flex items-center gap-2">
        <h3 class="font-display text-sm font-semibold text-neutral-700">
          <span class="mr-1.5" aria-hidden="true">💬</span>提示词预览
        </h3>
        <span
          v-if="messages.length > 0"
          class="rounded-full bg-neutral-100 px-2 py-0.5 text-xs text-neutral-500"
        >
          {{ messages.length }} messages · {{ totalChars().toLocaleString() }} 字符
        </span>
      </div>
      <div class="flex items-center gap-2">
        <button
          v-if="isExpanded && messages.length > 0"
          data-testid="copy-prompt-button"
          class="rounded-md border border-neutral-200 px-2.5 py-1 text-xs text-neutral-500 transition hover:border-neutral-400 hover:text-neutral-700"
          type="button"
          @click.stop="handleCopy"
        >
          {{ copyLabel }}
        </button>
        <svg
          class="size-4 text-neutral-400 transition-transform"
          :class="{ 'rotate-180': isExpanded }"
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          stroke-width="2"
          stroke-linecap="round"
          stroke-linejoin="round"
        >
          <path d="m6 9 6 6 6-6" />
        </svg>
      </div>
    </button>

    <!-- Expanded content -->
    <div v-if="isExpanded" class="border-t border-neutral-100">
      <div
        v-if="messages.length === 0"
        class="px-5 py-10 text-center"
      >
        <p class="text-sm text-neutral-400">暂无提示词数据</p>
      </div>

      <div v-else class="divide-y divide-neutral-100">
        <div
          v-for="(msg, i) in messages"
          :key="i"
          class="px-5 py-3"
        >
          <!-- Role badge -->
          <div class="mb-2 flex items-center gap-2">
            <span
              :class="roleBadgeClass(msg.role)"
              class="inline-flex items-center rounded-full px-2 py-0.5 text-[11px] font-semibold uppercase tracking-wide"
            >
              {{ roleLabel(msg.role) }}
            </span>
            <span class="text-[10px] text-neutral-400">
              {{ messageContent(msg).length.toLocaleString() }} 字符
            </span>
          </div>

          <!-- Content -->
          <pre
            class="overflow-x-auto whitespace-pre-wrap break-words font-mono text-sm leading-6 text-neutral-700"
          >{{ messageContent(msg) }}</pre>
        </div>
      </div>
    </div>
  </div>
</template>
