<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from "vue"
import { useAppStore } from "../../stores/app"
import AppSidebar from "../sidebar/AppSidebar.vue"
import MainPanel from "./MainPanel.vue"

const appStore = useAppStore()

/** 移动端侧边栏 overlay 展开状态。 */
const mobileSidebarOpen = ref(false)

/** 当前是否为移动端视口 (< 768px)。 */
const isMobile = ref(window.innerWidth < 768)

/** 桌面端侧边栏可见状态：结合全局折叠 + 本地状态。 */
const sidebarVisible = computed(() => !appStore.sidebarCollapsed)

function onViewportResize() {
  isMobile.value = window.innerWidth < 768
}

onMounted(() => {
  window.addEventListener("resize", onViewportResize)
})

onUnmounted(() => {
  window.removeEventListener("resize", onViewportResize)
})

function openMobileSidebar() {
  mobileSidebarOpen.value = true
}

function closeMobileSidebar() {
  mobileSidebarOpen.value = false
}
</script>

<template>
  <div class="flex h-screen overflow-hidden bg-neutral-50">
    <!-- ── 桌面端侧边栏（≥768px 正常流布局）── -->
    <aside
      data-testid="desktop-sidebar"
      class="hidden shrink-0 overflow-hidden border-r border-neutral-200 bg-white transition-all duration-300 ease-in-out md:block"
      :class="sidebarVisible ? 'w-72' : 'w-0 border-r-0'"
    >
      <AppSidebar />
    </aside>

    <!-- ── 移动端侧边栏 overlay ── -->
    <Transition name="sidebar-overlay-fade">
      <div
        v-if="mobileSidebarOpen && isMobile"
        data-testid="sidebar-overlay"
        class="fixed inset-0 z-20 bg-black/30"
        @click="closeMobileSidebar"
      />
    </Transition>
    <aside
      v-if="isMobile"
      data-testid="mobile-sidebar"
      class="fixed inset-y-0 left-0 z-30 w-72 border-r border-neutral-200 bg-white shadow-lg transition-transform duration-300 ease-in-out"
      :class="mobileSidebarOpen ? 'translate-x-0' : '-translate-x-full'"
    >
      <AppSidebar />
    </aside>

    <!-- ── 右侧主区域 ── -->
    <div class="relative flex flex-1 flex-col overflow-hidden">
      <!-- ── 移动端汉堡菜单按钮 ── -->
      <button
        data-testid="hamburger-menu"
        :style="{ display: isMobile ? 'flex' : 'none' }"
        class="absolute left-3 top-3 z-10 size-9 items-center justify-center rounded-md border border-neutral-200 bg-white text-neutral-600 shadow-sm transition hover:bg-neutral-50"
        aria-label="打开侧边栏"
        @click="openMobileSidebar"
      >
        <svg
          data-testid="hamburger-icon"
          class="size-5"
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          stroke-width="2"
          stroke-linecap="round"
          stroke-linejoin="round"
        >
          <line x1="4" y1="6" x2="20" y2="6" />
          <line x1="4" y1="12" x2="20" y2="12" />
          <line x1="4" y1="18" x2="20" y2="18" />
        </svg>
      </button>

      <MainPanel />
    </div>
  </div>
</template>

<style scoped>
/* ── overlay 淡入/淡出 ── */
.sidebar-overlay-fade-enter-active,
.sidebar-overlay-fade-leave-active {
  transition: opacity 0.3s ease-in-out;
}
.sidebar-overlay-fade-enter-from,
.sidebar-overlay-fade-leave-to {
  opacity: 0;
}
</style>
