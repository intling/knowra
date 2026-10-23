<script setup lang="ts">
import { computed, ref } from "vue"
import { useRoute } from "vue-router"
import { useUserStore } from "../../stores/user"
import AdminDrawer from "./AdminDrawer.vue"
defineProps<{ title: string; subtitle?: string }>()
const route = useRoute(),
  user = useUserStore(),
  menuOpen = ref(false),
  trigger = ref<HTMLElement | null>(null)
const links = [
  ["overview", "运行总览", "operations:read", "01"],
  ["users", "用户管理", "users:manage", "02"],
  ["models", "模型服务", "models:manage", "03"],
  ["jobs", "处理任务", "operations:read", "04"],
  ["audit", "操作审计", "audit:read", "05"],
  ["system", "系统状态", "operations:read", "06"],
]
const navigation = computed(() =>
  links.filter(([, , permission]) => user.hasPermission(permission!)),
)
</script>
<template>
  <div class="min-h-dvh bg-paper text-ink">
    <header class="border-b border-line bg-surface/90 px-4 sm:px-7">
      <div
        class="mx-auto flex min-h-18 max-w-[1440px] flex-wrap items-center justify-between gap-3 py-3"
      >
        <RouterLink to="/admin" class="flex items-center gap-3"
          ><span
            class="grid size-10 place-items-center rounded-xl bg-brand-700 font-display text-xl text-white"
            aria-hidden="true"
            >知</span
          ><span class="font-display text-lg font-semibold"
            >知寻
            <span
              class="ml-2 border-l border-line pl-3 font-sans text-sm font-normal text-ink-muted"
              >管理后台</span
            ></span
          ></RouterLink
        >
        <div class="flex items-center gap-4 text-sm">
          <RouterLink to="/" class="text-brand-700">返回知识书房 ↗</RouterLink
          ><RouterLink to="/account" class="max-w-32 truncate text-ink-muted"
            >账户</RouterLink
          ><button
            ref="trigger"
            data-testid="admin-menu-toggle"
            class="account-secondary lg:hidden"
            :aria-expanded="menuOpen"
            aria-label="打开后台导航"
            @click="menuOpen = true"
          >
            菜单
          </button>
        </div>
      </div>
    </header>
    <div
      class="mx-auto grid max-w-[1440px] min-w-0 lg:grid-cols-[224px_minmax(0,1fr)]"
    >
      <aside
        class="hidden min-h-[calc(100dvh-73px)] border-r border-line px-4 py-8 lg:block"
      >
        <p class="mb-4 px-3 text-xs tracking-widest text-ink-muted">
          工作空间 / WORKSPACE
        </p>
        <nav class="space-y-1.5" aria-label="后台导航">
          <RouterLink
            v-for="[path, label, , number] in navigation"
            :key="path"
            data-testid="admin-nav-link"
            :to="`/admin/${path}`"
            :aria-current="route.path === `/admin/${path}` ? 'page' : undefined"
            class="flex items-center gap-3 rounded-xl border border-transparent px-3 py-3 text-sm text-ink-muted hover:bg-paper-deep"
            :class="{
              '!border-brand-200 !bg-brand-50 !text-brand-800':
                route.path === `/admin/${path}`,
            }"
            ><span class="font-mono text-xs opacity-60">{{ number }}</span
            >{{ label
            }}<span
              v-if="route.path === `/admin/${path}`"
              class="ml-auto text-brand-600"
              aria-hidden="true"
              >●</span
            ></RouterLink
          >
        </nav>
        <div
          class="mt-12 border-t border-line px-3 pt-5 text-xs leading-6 text-ink-muted"
        >
          运行维护与访问管理<br />私有资料始终按账号隔离
        </div>
      </aside>
      <main
        id="admin-content"
        class="min-w-0 px-4 py-7 sm:px-7 lg:px-9 lg:py-9"
      >
        <header class="mb-7">
          <p class="mb-3 text-xs text-ink-muted">
            管理后台 <span class="mx-2 opacity-50">/</span>{{ title }}
          </p>
          <h1 class="font-display text-3xl font-semibold tracking-tight">
            {{ title }}
          </h1>
          <p
            v-if="subtitle"
            class="mt-3 max-w-3xl text-sm leading-6 text-ink-muted"
          >
            {{ subtitle }}
          </p>
        </header>
        <slot />
      </main>
    </div>
    <AdminDrawer
      :open="menuOpen"
      title="后台导航"
      :trigger="trigger"
      @close="menuOpen = false"
      ><nav aria-label="窄屏后台导航" class="space-y-2">
        <RouterLink
          v-for="[path, label] in navigation"
          :key="path"
          :to="`/admin/${path}`"
          class="block rounded-lg px-4 py-3 text-sm hover:bg-paper-deep"
          :aria-current="route.path === `/admin/${path}` ? 'page' : undefined"
          @click="menuOpen = false"
          >{{ label }}</RouterLink
        >
      </nav></AdminDrawer
    >
  </div>
</template>
