<script setup lang="ts">
import { ref, watch } from "vue"
import { useRoute } from "vue-router"
import {
  getJob,
  listJobs,
  type AdminJob,
  type JobDetail,
} from "../api/adminOperations"
import AdminFrame from "../components/shared/AdminFrame.vue"
import AdminDrawer from "../components/shared/AdminDrawer.vue"
import AdminError from "../components/shared/AdminError.vue"
import AdminLoadState from "../components/shared/AdminLoadState.vue"
import { useAdminResource } from "../shared/useAdminResource"
import {
  errorMessage,
  errorTrace,
  formatTime,
  jobKinds,
  statusLabels,
} from "../shared/admin"
const route = useRoute(),
  kind = ref(String(route.query.kind ?? "")),
  status = ref(String(route.query.status ?? "")),
  owner = ref(""),
  start = ref(""),
  end = ref(""),
  offset = ref(0)
const { allowed, data, loading, error, traceId, loadedAt, refresh } =
  useAdminResource("operations:read", () =>
    listJobs({
      kind: kind.value,
      status: status.value,
      owner_user_id: owner.value.trim(),
      from: start.value ? new Date(start.value).toISOString() : undefined,
      to: end.value ? new Date(end.value).toISOString() : undefined,
      offset: offset.value,
      limit: 20,
    }),
  )
function page(delta: number) {
  offset.value += delta
  refresh()
}
function apply() {
  offset.value = 0
  refresh()
}
watch([kind, status], apply)
const selected = ref<AdminJob | null>(null),
  detail = ref<JobDetail | null>(null),
  detailLoading = ref(false),
  detailError = ref(""),
  detailTrace = ref<string | null>(null),
  trigger = ref<HTMLElement | null>(null)
let request = 0
async function open(job: AdminJob, event: Event) {
  const current = ++request
  selected.value = job
  trigger.value = event.currentTarget as HTMLElement
  detail.value = null
  detailLoading.value = true
  detailError.value = ""
  try {
    const result = await getJob(job.kind, job.id)
    if (current === request && allowed.value) detail.value = result
  } catch (cause) {
    if (current === request) {
      detailError.value = errorMessage(cause)
      detailTrace.value = errorTrace(cause)
    }
  } finally {
    if (current === request) detailLoading.value = false
  }
}
function close() {
  request++
  selected.value = null
  detail.value = null
}
watch(allowed, (value) => {
  if (!value) close()
})
</script>
<template>
  <AdminFrame
    title="处理任务"
    subtitle="按解析、分块和向量化阶段定位问题。仅展示运行元数据与安全故障说明。"
    ><p v-if="!allowed" role="alert" class="account-card">
      你没有运行管理权限。
    </p>
    <template v-else>
      <AdminLoadState
        :loading="loading"
        :error="error"
        :trace-id="traceId"
        :loaded-at="loadedAt"
        @refresh="refresh"
      />
      <form
        class="account-card mb-5 grid gap-4 sm:grid-cols-2 xl:grid-cols-3"
        @submit.prevent="apply"
      >
        <label class="account-label"
          >阶段<select
            v-model="kind"
            data-testid="admin-job-kind"
            class="account-input mt-2"
          >
            <option value="">全部阶段</option>
            <option v-for="(label, key) in jobKinds" :key="key" :value="key">
              {{ label }}
            </option>
          </select></label
        ><label class="account-label"
          >状态<select v-model="status" class="account-input mt-2">
            <option value="">全部状态</option>
            <option
              v-for="s in [
                'queued',
                'running',
                'succeeded',
                'failed',
                'superseded',
              ]"
              :key="s"
              :value="s"
            >
              {{ statusLabels[s] }}
            </option>
          </select></label
        ><label class="account-label"
          >所属账号 ID<input
            v-model="owner"
            class="account-input mt-2"
            placeholder="可选：账号 UUID" /></label
        ><label class="account-label"
          >创建时间从<input
            v-model="start"
            type="datetime-local"
            class="account-input mt-2" /></label
        ><label class="account-label"
          >创建时间至<input
            v-model="end"
            type="datetime-local"
            class="account-input mt-2" /></label
        ><button class="account-secondary self-center" :disabled="loading">
          应用时间与账号条件
        </button>
        <p class="text-xs leading-5 text-ink-muted sm:col-span-2">
          默认最近 24 小时；按创建时间筛选，结束时间不包含在内，最长 31 天。
        </p>
      </form>
      <ul class="space-y-3" aria-label="处理任务列表">
        <li
          v-for="job in data?.items"
          :key="job.kind + job.id"
          data-testid="admin-job-row"
          class="account-card"
        >
          <div
            class="grid min-w-0 gap-4 md:grid-cols-[minmax(0,1fr)_auto_auto]"
          >
            <div class="min-w-0">
              <p
                class="flex flex-wrap items-center gap-2 text-sm font-semibold"
              >
                {{ jobKinds[job.kind]
                }}<span
                  class="rounded bg-paper-deep px-2 py-1 text-xs font-normal"
                  :class="{ 'text-cite': job.status === 'failed' }"
                  >{{ statusLabels[job.status] ?? "无法确认" }}</span
                >
              </p>
              <p class="mt-2 break-all font-mono text-xs text-ink-muted">
                任务 {{ job.id }}
              </p>
              <p class="mt-2 text-xs text-ink-muted">
                {{ job.owner_label }} · 创建于 {{ formatTime(job.created_at) }}
              </p>
            </div>
            <div class="text-xs leading-6 text-ink-muted">
              <p>尝试计数 {{ job.attempt_count }}</p>
              <p>
                耗时
                {{
                  job.duration_ms === null
                    ? "—"
                    : (job.duration_ms / 1000).toFixed(1) + " 秒"
                }}
              </p>
            </div>
            <button
              data-testid="admin-job-open"
              class="account-secondary self-start"
              @click="open(job, $event)"
            >
              查看详情
            </button>
          </div>
          <p v-if="job.error_detail" class="mt-3 text-xs leading-6 text-cite">
            {{ job.error_detail }} · {{ job.error_code }}
          </p>
        </li>
      </ul>
      <p
        v-if="data && !data.items.length && !loading"
        class="account-card text-sm text-ink-muted"
      >
        暂无匹配的处理任务。
      </p>
      <nav
        class="mt-5 flex flex-wrap items-center justify-between gap-3 text-sm"
        aria-label="任务分页"
      >
        <p>共 {{ data?.total ?? "—" }} 项</p>
        <div class="flex gap-2">
          <button
            class="account-secondary"
            :disabled="loading || !offset"
            @click="page(-20)"
          >
            上一页</button
          ><button
            class="account-secondary"
            :disabled="loading || !data || offset + 20 >= data.total"
            @click="page(20)"
          >
            下一页
          </button>
        </div>
      </nav> </template
    ><AdminDrawer
      :open="!!selected"
      title="处理任务详情"
      :trigger="trigger"
      @close="close"
      ><p v-if="detailLoading" role="status">正在读取时间线…</p>
      <AdminError :message="detailError" :trace-id="detailTrace" /><template
        v-if="detail"
        ><dl class="space-y-3 text-sm">
          <div>
            <dt class="text-ink-muted">上传 ID</dt>
            <dd class="mt-1 break-all font-mono text-xs">
              {{ detail.job.uploaded_file_id }}
            </dd>
          </div>
          <div>
            <dt class="text-ink-muted">所属账号</dt>
            <dd class="mt-1 break-all">
              {{ detail.job.owner_label }} · {{ detail.job.owner_user_id }}
            </dd>
          </div>
        </dl>
        <h3 class="mt-7 mb-4 font-semibold">阶段与尝试记录</h3>
        <ol class="space-y-4">
          <li
            v-for="item in detail.timeline"
            :key="item.kind + item.id"
            class="border-l-2 border-brand-200 py-1 pl-4"
          >
            <p class="text-sm font-medium">
              {{ jobKinds[item.kind] }} · {{ statusLabels[item.status] }}
            </p>
            <p class="mt-2 break-all font-mono text-xs text-ink-muted">
              {{ item.id }}
            </p>
            <p class="mt-2 text-xs text-ink-muted">
              开始 {{ formatTime(item.started_at) }}<br />结束
              {{ formatTime(item.finished_at) }}
            </p>
            <p
              v-if="item.status === 'running'"
              class="mt-2 text-xs text-ink-muted"
            >
              处理中；若长时间没有变化，建议检查运行日志。
            </p>
            <p v-if="item.error_code" class="mt-2 text-xs leading-6 text-cite">
              {{ item.error_detail }}<br />{{ item.error_code }}
            </p>
          </li>
          <li
            v-for="missing in detail.missing_kinds"
            :key="missing"
            class="border-l-2 border-line pl-4 text-sm text-ink-muted"
          >
            {{ jobKinds[missing] }} · 尚未创建
          </li>
        </ol></template
      ></AdminDrawer
    ></AdminFrame
  >
</template>
