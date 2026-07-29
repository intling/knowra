<script setup lang="ts">
/**
 * SidebarUser — 侧边栏底部用户信息
 *
 * 固定在侧边栏底部，展示当前用户头像与基本信息。
 *
 * 视觉签名：头像使用品牌渐变底色 + Newsreader 衬线体首字母，
 * 与顶部 knowra wordmark 形成视觉呼应——侧边栏从上到下的字体节奏。
 * 这是大多数类 ChatGPT 应用不会做的细节。
 */
import { onMounted } from "vue"
import { useUserStore } from "../../stores/user"

const userStore = useUserStore()

onMounted(() => {
  userStore.loadCurrentUser()
})

/** 从 display_name 提取首字母作为头像回退方案 */
function initials(name: string): string {
  const parts = name.trim().split(/\s+/)
  if (parts.length >= 2) {
    return (parts[0]![0]! + parts[1]![0]!).toUpperCase()
  }
  return name.trim().slice(0, 2).toUpperCase()
}
</script>

<template>
  <footer
    data-testid="sidebar-user"
    class="shrink-0 border-t border-neutral-200"
  >
    <!-- 加载骨架 — 用户信息加载中 -->
    <div
      v-if="userStore.isUserLoading"
      data-testid="sidebar-user-skeleton"
      class="flex items-center gap-3 px-4 py-3"
    >
      <div class="size-8 shrink-0 animate-pulse rounded-full bg-neutral-200" />
      <div class="flex flex-1 flex-col gap-1.5">
        <div class="h-3 w-20 animate-pulse rounded bg-neutral-200" />
        <div class="h-2.5 w-28 animate-pulse rounded bg-neutral-100" />
      </div>
    </div>

    <!-- 加载失败 — 温和降级，不阻断使用 -->
    <div
      v-else-if="userStore.userError"
      data-testid="sidebar-user-error"
      class="flex items-center gap-3 px-4 py-3"
    >
      <div
        class="flex size-8 shrink-0 items-center justify-center rounded-full bg-neutral-100 text-neutral-400"
        aria-hidden="true"
      >
        <svg
          class="size-4"
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          stroke-width="2"
          stroke-linecap="round"
          stroke-linejoin="round"
        >
          <path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2" />
          <circle cx="12" cy="7" r="4" />
        </svg>
      </div>
      <p class="text-xs text-neutral-400">用户信息加载失败</p>
    </div>

    <!-- 用户信息 — 正常展示 -->
    <div
      v-else-if="userStore.currentUser"
      data-testid="sidebar-user-info"
      class="group flex items-center gap-3 px-4 py-3 transition-colors hover:bg-neutral-50"
      role="button"
      tabindex="0"
    >
      <!-- Avatar -->
      <div class="relative shrink-0">
        <!-- 自定义头像图片（如有） -->
        <img
          v-if="userStore.currentUser.avatar_url"
          :src="userStore.currentUser.avatar_url"
          :alt="userStore.currentUser.display_name"
          class="size-8 rounded-full object-cover ring-2 ring-brand-200/60"
        />
        <!-- 品牌渐变 + 衬线体首字母（无头像时的回退） -->
        <div
          v-else
          class="flex size-8 items-center justify-center rounded-full brand-gradient text-xs font-semibold text-white shadow-sm shadow-brand-200/30"
          aria-hidden="true"
        >
          <span class="font-display translate-y-px">
            {{ initials(userStore.currentUser.display_name) }}
          </span>
        </div>
      </div>

      <!-- 用户文字信息 -->
      <div class="min-w-0 flex-1">
        <p class="truncate text-sm font-medium leading-tight text-neutral-800">
          {{ userStore.currentUser.display_name }}
        </p>
        <p
          v-if="userStore.currentUser.email"
          class="truncate text-xs leading-tight text-neutral-500"
        >
          {{ userStore.currentUser.email }}
        </p>
      </div>
    </div>
  </footer>
</template>
