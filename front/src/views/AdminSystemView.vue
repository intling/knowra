<script setup lang="ts">
import { getEffectiveModels } from "../api/adminModels"
import EffectiveModelCards from "../components/shared/EffectiveModelCards.vue"
import AdminError from "../components/shared/AdminError.vue"
import { getSystemStatus } from "../api/adminOperations"
import AdminFrame from "../components/shared/AdminFrame.vue"
import AdminLoadState from "../components/shared/AdminLoadState.vue"
import { useAdminResource } from "../shared/useAdminResource"
import { formatTime, modelKinds, statusLabels } from "../shared/admin"
const { allowed, data, loading, error, traceId, loadedAt, refresh } =
  useAdminResource("operations:read", getSystemStatus)
const models = useAdminResource(
  "models:manage",
  async () => {
    const value = await getEffectiveModels()
    if (!Array.isArray(value)) throw new Error("模型生效摘要暂不可用")
    return value
  },
  () => allowed.value,
)
const names: Record<string, string> = {
  external_models: "外部模型连接",
  database: "数据库",
  pgvector: "pgvector 扩展",
  document_models: "文档处理模型",
  ...Object.fromEntries(
    Object.entries(modelKinds).map(([k, v]) => [`model:${k}`, v]),
  ),
}
</script>
<template>
  <AdminFrame
    title="系统状态"
    subtitle="查看当前实例的依赖与准备状态，区分配置问题和处理故障。"
    ><p v-if="!allowed" role="alert" class="account-card">
      你没有运行管理权限。
    </p>
    <template v-else
      ><AdminLoadState
        :loading="loading"
        :error="error"
        :trace-id="traceId"
        :loaded-at="loadedAt"
        @refresh="refresh"
      />
      <div
        class="mb-5 rounded-xl border border-brand-200 bg-brand-50 p-5 text-sm leading-6 text-brand-800"
      >
        <p class="font-semibold">检查范围：当前实例</p>
        <p class="mt-1">
          文档模型准备状态仅代表本服务进程。此页面依赖有效登录，不能替代外部健康监控。
        </p>
        <p v-if="data" class="mt-2 break-all font-mono text-xs">
          {{ data.instance_id }} · 检查于 {{ formatTime(data.checked_at) }}
        </p>
      </div>
      <div class="grid gap-4 md:grid-cols-2">
        <article
          v-for="component in data?.components"
          :key="component.name"
          class="account-card"
        >
          <div class="flex flex-wrap items-center justify-between gap-3">
            <h2 class="font-semibold">
              {{ names[component.name] ?? component.name }}
            </h2>
            <span
              class="rounded bg-paper-deep px-2 py-1 text-xs"
              :class="{
                'text-cite': ['unavailable', 'degraded'].includes(
                  component.status,
                ),
                'text-brand-700': component.status === 'ok',
              }"
              >{{ statusLabels[component.status] }}</span
            >
          </div>
          <p class="mt-3 text-sm leading-6 text-ink-muted">
            {{ component.detail }}
          </p>
        </article>
      </div>
      <section class="mt-7">
        <h2 class="mb-4 font-display text-lg font-semibold">
          模型来源与最近测试
        </h2>
        <AdminError
          :message="models.error.value"
          :trace-id="models.traceId.value"
        /><EffectiveModelCards
          v-if="models.data.value"
          :models="models.data.value"
        />
      </section>
      <p class="mt-5 text-xs leading-6 text-ink-muted">
        刷新仅执行只读检查，不会自动调用外部模型。模型连通性以最近一次显式测试为参考，可前往<RouterLink
          to="/admin/models"
          class="text-brand-700 underline"
          >模型服务</RouterLink
        >检查。
      </p></template
    ></AdminFrame
  >
</template>
