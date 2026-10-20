<script setup lang="ts">
import ConversationList from "./ConversationList.vue"
import KnowledgeInfo from "./KnowledgeInfo.vue"
import SidebarHeader from "./SidebarHeader.vue"
import SidebarUser from "./SidebarUser.vue"

/** navigate：用户新建或选择了对话（移动端据此收起抽屉）。 */
const emit = defineEmits<{ (e: "navigate"): void }>()
</script>

<template>
  <aside class="flex h-full w-full flex-col bg-paper-deep" aria-label="导航">
    <SidebarHeader @navigate="emit('navigate')" />
    <KnowledgeInfo />
    <div class="mx-4 my-3 border-t border-line" />
    <div class="min-h-0 flex-1 overflow-y-auto scrollbar-thin pb-2">
      <ConversationList @select="emit('navigate')" />
    </div>
    <SidebarUser />
  </aside>
</template>
