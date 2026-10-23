<script setup lang="ts">
import type { EffectiveModel } from "../../api/adminModels"
import { useAdminClock } from "../../shared/useAdminClock"
import {
  formatTime,
  isCurrentProbe,
  modelKinds,
  statusLabels,
} from "../../shared/admin"
defineProps<{ models: EffectiveModel[] }>()
const now = useAdminClock()
</script>
<template>
  <div class="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
    <article
      v-for="model in models"
      :key="model.kind"
      data-testid="effective-model-card"
      class="min-w-0 rounded-xl border border-line bg-surface p-4"
    >
      <h3 class="text-sm font-semibold">{{ modelKinds[model.kind] }}</h3>
      <p class="mt-3 text-xs text-ink-muted">
        {{ model.source === "profile" ? "后台默认" : "环境配置"
        }}<span class="ml-2 rounded bg-paper-deep px-2 py-1">{{
          !model.enabled
            ? "未启用"
            : model.configuration_status === "unavailable"
              ? "配置不可用"
              : "已启用"
        }}</span>
      </p>
      <p class="my-3 text-sm break-all">{{ model.model || "未配置模型" }}</p>
      <p class="text-xs text-ink-muted">
        {{
          model.profile_revision !== null
            ? `配置 v${model.profile_revision} · `
            : ""
        }}绑定 v{{ model.binding_revision }}
      </p>
      <div
        class="mt-3 border-t border-line pt-3 text-xs leading-6 text-ink-muted"
      >
        <template v-if="model.latest_probe"
          ><p>
            {{
              statusLabels[model.latest_probe.status] ??
              model.latest_probe.status
            }}
            ·
            {{
              isCurrentProbe(model.latest_probe, undefined, undefined, now)
                ? "当前参考"
                : "已过期"
            }}
          </p>
          <p>{{ formatTime(model.latest_probe.checked_at) }}</p></template
        >
        <p v-else>
          {{ model.enabled ? "未测试，连接状态未知" : "此用途未启用" }}
        </p>
      </div>
    </article>
  </div>
</template>
