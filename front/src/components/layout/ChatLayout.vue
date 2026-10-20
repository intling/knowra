<script setup lang="ts">
import { nextTick, onMounted, onUnmounted, provide, ref } from "vue"

import { trapTab } from "../../shared/a11y/focus"
import { useAppStore } from "../../stores/app"
import AppSidebar from "../sidebar/AppSidebar.vue"
import MainPanel from "./MainPanel.vue"
import { mobileNavKey } from "./mobileNav"

const appStore = useAppStore()

const isMobile = ref(window.innerWidth < 768)
const mobileSidebarOpen = ref(false)
const drawerRef = ref<HTMLElement | null>(null)
const menuTriggerRef = ref<HTMLButtonElement | null>(null)

function onViewportResize() {
  isMobile.value = window.innerWidth < 768
  if (!isMobile.value) mobileSidebarOpen.value = false
}

async function openMobileSidebar() {
  mobileSidebarOpen.value = true
  await nextTick()
  drawerRef.value?.querySelector<HTMLElement>('[data-testid="new-conversation-btn"]')?.focus()
}

async function closeMobileSidebar() {
  if (!mobileSidebarOpen.value) return
  mobileSidebarOpen.value = false
  await nextTick()
  menuTriggerRef.value?.focus()
}

function handleKeydown(event: KeyboardEvent) {
  if (!mobileSidebarOpen.value || event.defaultPrevented) return
  if (event.key === "Escape") {
    event.preventDefault()
    void closeMobileSidebar()
    return
  }
  trapTab(event, drawerRef.value)
}

provide(mobileNavKey, {
  isMobile,
  isOpen: mobileSidebarOpen,
  open: openMobileSidebar,
  triggerRef: menuTriggerRef,
})

onMounted(() => {
  window.addEventListener("resize", onViewportResize)
  document.addEventListener("keydown", handleKeydown)
})

onUnmounted(() => {
  window.removeEventListener("resize", onViewportResize)
  document.removeEventListener("keydown", handleKeydown)
})
</script>

<template>
  <div class="flex h-dvh overflow-hidden bg-paper text-ink">
    <!-- 桌面端：常驻侧边栏（与移动抽屉互斥，只挂载一个实例） -->
    <aside
      v-if="!isMobile"
      data-testid="desktop-sidebar"
      class="shrink-0 overflow-hidden border-r border-line bg-paper-deep transition-[width] duration-200 ease-out"
      :class="appStore.sidebarCollapsed ? 'w-0 border-r-0' : 'w-68'"
    >
      <AppSidebar />
    </aside>

    <!-- 移动端：抽屉 -->
    <template v-else>
      <Transition name="sidebar-overlay-fade">
        <div
          v-if="mobileSidebarOpen"
          data-testid="sidebar-overlay"
          class="fixed inset-0 z-20 bg-ink/30"
          aria-hidden="true"
          @click="closeMobileSidebar"
        />
      </Transition>
      <div
        id="mobile-sidebar"
        ref="drawerRef"
        data-testid="mobile-sidebar"
        class="fixed inset-y-0 left-0 z-30 w-[min(18rem,86vw)] border-r border-line bg-paper-deep shadow-[var(--shadow-popover)] transition-transform duration-200 ease-out"
        :class="mobileSidebarOpen ? 'translate-x-0' : '-translate-x-full'"
        :role="mobileSidebarOpen ? 'dialog' : undefined"
        :aria-modal="mobileSidebarOpen ? 'true' : undefined"
        :aria-label="mobileSidebarOpen ? '导航' : undefined"
        :aria-hidden="mobileSidebarOpen ? undefined : 'true'"
        :inert="mobileSidebarOpen ? undefined : true"
      >
        <button
          type="button"
          data-testid="mobile-sidebar-close"
          class="absolute top-4 right-3 z-10 flex size-8 items-center justify-center rounded-[var(--radius-button)] text-ink-muted transition-colors hover:bg-paper hover:text-ink"
          aria-label="关闭导航"
          @click="closeMobileSidebar"
        >
          <svg class="size-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" aria-hidden="true">
            <path d="M18 6 6 18M6 6l12 12" />
          </svg>
        </button>
        <AppSidebar @navigate="closeMobileSidebar" />
      </div>
    </template>

    <div class="relative flex min-w-0 flex-1 flex-col overflow-hidden" :inert="mobileSidebarOpen || undefined">
      <MainPanel />
    </div>
  </div>
</template>

<style scoped>
.sidebar-overlay-fade-enter-active,
.sidebar-overlay-fade-leave-active {
  transition: opacity 0.2s ease;
}
.sidebar-overlay-fade-enter-from,
.sidebar-overlay-fade-leave-to {
  opacity: 0;
}
</style>
