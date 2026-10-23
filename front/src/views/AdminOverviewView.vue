<script setup lang="ts">
import { computed } from "vue"
import { getOverview, listAuditEvents } from "../api/adminOperations"
import { getEffectiveModels } from "../api/adminModels"
import AdminFrame from "../components/shared/AdminFrame.vue"
import AdminLoadState from "../components/shared/AdminLoadState.vue"
import AdminError from "../components/shared/AdminError.vue"
import EffectiveModelCards from "../components/shared/EffectiveModelCards.vue"
import { useAdminResource } from "../shared/useAdminResource"
import {
  actionLabels,
  formatBytes,
  formatTime,
  jobKinds,
  statusLabels,
} from "../shared/admin"
const { allowed, data, loading, error, traceId, loadedAt, refresh } =
  useAdminResource("operations:read", getOverview)
const models = useAdminResource(
  "models:manage",
  async () => {
    const value = await getEffectiveModels()
    if (!Array.isArray(value)) throw new Error("模型生效摘要暂不可用")
    return value
  },
  () => allowed.value,
)
const audit = useAdminResource(
  "audit:read",
  () => listAuditEvents({ limit: 5 }),
  () => allowed.value,
)
const queued = computed(() =>
  data.value?.jobs_by_kind.some((j) => j.queued === null)
    ? null
    : data.value?.jobs_by_kind.reduce((n, j) => n + (j.queued ?? 0), 0),
)
const failed = computed(() =>
  data.value?.jobs_by_kind.some((j) => j.failed_24h === null)
    ? null
    : data.value?.jobs_by_kind.reduce((n, j) => n + (j.failed_24h ?? 0), 0),
)
async function refreshAll() {
  await Promise.allSettled([refresh(), models.refresh(), audit.refresh()])
}
</script>
<template>
  <AdminFrame
    title="运行总览"
    subtitle="了解平台当前运行情况，从需要关注的事项开始处理。"
    ><p v-if="!allowed" role="alert" class="account-card">
      你没有运行管理权限。
    </p>
    <template v-else
      ><AdminLoadState
        :loading="loading"
        :error="error"
        :trace-id="traceId"
        :loaded-at="loadedAt"
        @refresh="refreshAll"
      />
      <div class="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
        <RouterLink
          to="/admin/users"
          class="account-card !p-5 transition-colors hover:border-brand-300"
          ><p class="text-xs text-ink-muted">有效账号</p>
          <p
            data-testid="overview-users-total"
            class="my-4 font-display text-3xl font-semibold"
          >
            {{ data?.users.total ?? "无法获取" }}
          </p>
          <p class="text-xs text-ink-muted">
            允许登录 {{ data?.users.active ?? "—" }} · 已停用
            {{ data?.users.disabled ?? "—" }}
          </p></RouterLink
        >
        <article class="account-card !p-5">
          <p class="text-xs text-ink-muted">有效资料</p>
          <p
            data-testid="overview-uploads-total"
            class="my-4 font-display text-3xl font-semibold"
          >
            {{ data?.uploads.total ?? "无法获取" }}
          </p>
          <p class="text-xs text-ink-muted">
            原文件逻辑容量 {{ formatBytes(data?.uploads.logical_bytes) }}
          </p>
        </article>
        <RouterLink
          to="/admin/jobs?status=queued"
          class="account-card !p-5 hover:border-brand-300"
          ><p class="text-xs text-ink-muted">当前排队任务</p>
          <p class="my-4 font-display text-3xl font-semibold">
            {{ queued ?? "无法获取" }}
          </p>
          <p class="text-xs text-ink-muted">三个阶段独立任务之和</p></RouterLink
        ><RouterLink
          to="/admin/jobs?status=failed"
          class="account-card !p-5 hover:border-brand-300"
          ><p class="text-xs text-ink-muted">最近 24 小时失败任务</p>
          <p
            class="my-4 font-display text-3xl font-semibold"
            :class="{ 'text-cite': failed }"
          >
            {{ failed ?? "无法获取" }}
          </p>
          <p class="text-xs text-ink-muted">按任务完成时间统计</p></RouterLink
        >
      </div>
      <section class="mt-7 account-card !p-5">
        <div class="flex flex-wrap items-center justify-between gap-3">
          <h2 class="font-display text-lg font-semibold">需要关注</h2>
          <RouterLink to="/admin/system" class="text-xs text-brand-700"
            >查看系统状态 ↗</RouterLink
          >
        </div>
        <ul
          v-if="data?.attention_items.length"
          class="mt-4 divide-y divide-line"
        >
          <li
            v-for="(item, index) in data.attention_items"
            :key="item.code + index"
          >
            <RouterLink
              :to="item.href"
              class="flex flex-wrap items-center justify-between gap-3 py-3 text-sm"
              ><span
                ><span class="mr-2 text-cite" aria-hidden="true">●</span
                >{{ item.detail
                }}<span v-if="item.count" class="ml-2 text-cite">{{
                  item.count
                }}</span></span
              ><span class="text-xs text-brand-700">查看 →</span></RouterLink
            >
          </li>
        </ul>
        <p v-else class="mt-4 text-sm text-ink-muted">
          {{ data ? "当前快照没有待关注事项。" : "状态尚未获取。" }}
        </p>
        <p
          v-for="model in models.data.value?.filter(
            (m) =>
              m.configuration_status === 'unavailable' ||
              (m.latest_probe?.is_current &&
                m.latest_probe.status === 'failed'),
          )"
          :key="model.kind"
          class="mt-3 text-sm text-cite"
        >
          模型用途 {{ model.kind }} 需要检查 ·
          <RouterLink to="/admin/models" class="underline"
            >查看模型服务</RouterLink
          >
        </p>
      </section>
      <section class="mt-7">
        <div class="mb-4 flex items-center justify-between">
          <h2 class="font-display text-lg font-semibold">当前模型用途</h2>
          <RouterLink to="/admin/models" class="text-xs text-brand-700"
            >管理模型 ↗</RouterLink
          >
        </div>
        <AdminError
          :message="models.error.value"
          :trace-id="models.traceId.value"
        />
        <p
          v-if="models.loading.value && !models.data.value"
          class="account-card text-sm text-ink-muted"
        >
          正在读取模型来源…
        </p>
        <EffectiveModelCards
          v-if="models.data.value"
          :models="models.data.value"
        />
      </section>
      <div class="mt-7 grid gap-6 xl:grid-cols-[minmax(0,1.1fr)_minmax(0,1fr)]">
        <section class="account-card !p-5">
          <h2 class="font-display text-lg font-semibold">分阶段任务</h2>
          <p class="mt-2 text-xs leading-6 text-ink-muted">
            最近 24 小时按完成时间统计；阶段成功率不代表整条资料处理链成功率。
          </p>
          <ul class="mt-4 divide-y divide-line">
            <li v-for="job in data?.jobs_by_kind" :key="job.kind" class="py-4">
              <div class="flex items-center justify-between gap-3">
                <RouterLink
                  :to="`/admin/jobs?kind=${job.kind}`"
                  class="text-sm font-medium text-brand-700"
                  >{{ jobKinds[job.kind] }} ↗</RouterLink
                ><span class="text-xs text-ink-muted"
                  >成功率
                  {{
                    job.success_rate_24h === null
                      ? "暂无数据"
                      : (job.success_rate_24h * 100).toFixed(0) + "%"
                  }}</span
                >
              </div>
              <dl class="mt-3 grid grid-cols-4 gap-2 text-xs">
                <div>
                  <dt class="text-ink-muted">排队</dt>
                  <dd class="mt-1">{{ job.queued ?? "无法获取" }}</dd>
                </div>
                <div>
                  <dt class="text-ink-muted">处理中</dt>
                  <dd class="mt-1">{{ job.running ?? "无法获取" }}</dd>
                </div>
                <div>
                  <dt class="text-ink-muted">成功</dt>
                  <dd class="mt-1">{{ job.succeeded_24h ?? "无法获取" }}</dd>
                </div>
                <div>
                  <dt class="text-ink-muted">失败</dt>
                  <dd class="mt-1">{{ job.failed_24h ?? "无法获取" }}</dd>
                </div>
              </dl>
            </li>
          </ul>
        </section>
        <section class="account-card !p-5">
          <div class="flex items-center justify-between gap-3">
            <h2 class="font-display text-lg font-semibold">最近管理操作</h2>
            <RouterLink to="/admin/audit" class="text-xs text-brand-700"
              >全部记录 ↗</RouterLink
            >
          </div>
          <AdminError
            :message="audit.error.value"
            :trace-id="audit.traceId.value"
          />
          <ol class="mt-3 divide-y divide-line">
            <li
              v-for="event in audit.data.value?.items"
              :key="event.id"
              class="py-3"
            >
              <p class="flex flex-wrap justify-between gap-2 text-sm">
                {{ actionLabels[event.action] ?? event.action
                }}<span class="text-xs text-ink-muted">{{
                  statusLabels[event.result]
                }}</span>
              </p>
              <p class="mt-2 text-xs text-ink-muted">
                {{ formatTime(event.created_at) }}
              </p>
              <p class="mt-1 break-all font-mono text-xs text-ink-muted">
                操作者 {{ event.actor_user_id.slice(0, 8) }}
              </p>
            </li>
          </ol>
          <p
            v-if="audit.data.value && !audit.data.value.items.length"
            class="mt-5 text-sm text-ink-muted"
          >
            暂无管理操作。
          </p>
        </section>
      </div>
      <p v-if="data" class="mt-6 text-xs leading-6 text-ink-muted">
        统计快照
        {{
          formatTime(data.snapshot_at)
        }}。有效账号与资料排除软删除记录；原文件逻辑容量不含衍生文件、向量和数据库开销。
      </p>
    </template></AdminFrame
  >
</template>
