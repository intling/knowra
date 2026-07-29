<script setup lang="ts">
import ConversationList from "./ConversationList.vue"
import SidebarHeader from "./SidebarHeader.vue"
import SidebarUser from "./SidebarUser.vue"
</script>

<template>
  <aside
    class="flex h-full w-72 shrink-0 flex-col border-r border-neutral-200 bg-white"
  >
    <SidebarHeader />
    <div class="flex-1 overflow-y-auto py-2">
      <ConversationList />
    </div>
    <SidebarUser />
  </aside>
</template>
