<script setup lang="ts">
import { computed, nextTick, onMounted, onUnmounted, ref } from "vue"
import { useRouter } from "vue-router"
import { uniqueId } from "../../shared/a11y/focus"
import { useUserStore } from "../../stores/user"

const userStore = useUserStore(),
  router = useRouter()
const open = ref(false),
  busy = ref(false),
  error = ref("")
const trigger = ref<HTMLButtonElement | null>(null),
  root = ref<HTMLElement | null>(null)
const menuId = uniqueId("user-menu")
const roleLabel = computed(
  () =>
    ({ admin: "管理员", member: "成员", viewer: "只读" })[
      userStore.currentUser?.role ?? "member"
    ],
)
async function close() {
  open.value = false
  await nextTick()
  trigger.value?.focus()
}
async function toggle() {
  open.value = !open.value
  if (open.value) {
    await nextTick()
    root.value?.querySelector<HTMLElement>("a")?.focus()
  }
}
function outside(event: MouseEvent) {
  if (root.value && !root.value.contains(event.target as Node))
    open.value = false
}
onMounted(() => document.addEventListener("click", outside))
onUnmounted(() => document.removeEventListener("click", outside))
async function logout() {
  if (busy.value) return
  busy.value = true
  try {
    await userStore.logout()
    await router.replace({ name: "login", query: { reason: "logged_out" } })
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : "退出失败，请重试"
  } finally {
    busy.value = false
  }
}
</script>

<template>
  <footer
    ref="root"
    data-testid="sidebar-user"
    class="relative shrink-0 border-t border-line"
    @keydown.esc.stop.prevent="close"
  >
    <div
      v-if="userStore.isUserLoading"
      data-testid="sidebar-user-skeleton"
      class="p-4 text-sm text-ink-muted"
    >
      正在加载账户…
    </div>
    <p
      v-else-if="userStore.userError"
      data-testid="sidebar-user-error"
      class="p-4 text-sm text-cite"
    >
      {{ userStore.userError }}
    </p>
    <template v-else-if="userStore.currentUser">
      <div
        v-if="open"
        :id="menuId"
        class="absolute right-3 bottom-full left-3 mb-2 rounded-lg border border-line bg-surface p-2 shadow-[var(--shadow-popover)]"
      >
        <RouterLink
          data-testid="menu-account"
          to="/account"
          class="block rounded-lg px-3 py-2 text-sm text-ink hover:bg-paper-deep"
          @click="open = false"
          >账户设置</RouterLink
        >
        <RouterLink
          v-if="userStore.hasPermission('users:manage')"
          data-testid="menu-admin"
          to="/admin"
          class="block rounded-lg px-3 py-2 text-sm text-ink hover:bg-paper-deep"
          @click="open = false"
          >后台管理</RouterLink
        >
        <button
          data-testid="menu-logout"
          class="w-full rounded-lg px-3 py-2 text-left text-sm text-cite hover:bg-paper-deep"
          :disabled="busy"
          @click="logout"
        >
          {{ busy ? "退出中…" : "退出登录" }}
        </button>
        <p v-if="error" role="alert" class="px-3 text-sm text-cite">
          {{ error }}
        </p>
      </div>
      <button
        ref="trigger"
        data-testid="user-menu-button"
        class="flex w-full items-center gap-3 px-4 py-3 text-left hover:bg-paper-deep"
        :aria-expanded="open"
        :aria-controls="menuId"
        aria-label="账户菜单"
        @click="toggle"
      >
        <span
          v-if="!userStore.currentUser.avatar_url"
          class="grid size-8 shrink-0 place-items-center rounded-full bg-brand-700 text-xs font-semibold text-white"
          aria-hidden="true"
          >{{ userStore.currentUser.display_name.slice(0, 2) }}</span
        >
        <img
          v-else
          :src="userStore.currentUser.avatar_url"
          alt=""
          class="size-8 rounded-full"
        />
        <span data-testid="sidebar-user-info" class="min-w-0 flex-1"
          ><span class="block truncate text-sm font-medium text-ink">{{
            userStore.currentUser.display_name
          }}</span
          ><span
            data-testid="sidebar-user-role"
            class="block text-xs text-ink-muted"
            >{{ roleLabel }}</span
          ></span
        >
        <span aria-hidden="true" class="text-ink-faint">⌃</span>
      </button>
    </template>
  </footer>
</template>
