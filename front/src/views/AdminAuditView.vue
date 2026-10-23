<script setup lang="ts">
import { ref, watch } from "vue"
import { listAuditEvents } from "../api/adminOperations"
import AdminFrame from "../components/shared/AdminFrame.vue"
import AdminLoadState from "../components/shared/AdminLoadState.vue"
import { useAdminResource } from "../shared/useAdminResource"
import { actionLabels, formatTime, statusLabels } from "../shared/admin"
const action = ref(""),
  result = ref(""),
  actor = ref(""),
  trace = ref(""),
  start = ref(""),
  end = ref(""),
  offset = ref(0),
  copied = ref("")
const { allowed, data, loading, error, traceId, loadedAt, refresh } =
  useAdminResource("audit:read", () =>
    listAuditEvents({
      action: action.value,
      result: result.value,
      actor_user_id: actor.value.trim(),
      trace_id: trace.value.trim(),
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
watch([action, result], apply)
function display(value: unknown) {
  return value === null
    ? "无"
    : typeof value === "boolean"
      ? value
        ? "是"
        : "否"
      : String(value)
}
function change(value: unknown) {
  return value !== null &&
    typeof value === "object" &&
    "before" in value &&
    "after" in value
    ? `${display(value.before)} → ${display(value.after)}`
    : display(value)
}
const fields: Record<string, string> = {
  role: "角色",
  status: "状态",
  hourly_limit: "每小时额度",
  revoked_count: "已撤销会话数",
  secret_changed: "密钥变更",
  endpoint_changed: "地址变更",
  profile_revision: "测试配置版本",
  revision: "配置版本",
  default_profile_id: "默认配置",
  binding_revision: "绑定版本",
  latency_ms: "测试耗时（ms）",
  code: "结果码",
  model: "模型",
  kind: "用途",
  enabled: "启用",
  deleted: "已删除",
  dimensions: "向量维度",
  timeout_seconds: "超时（秒）",
  max_retries: "重试次数",
  api_format: "协议",
}
async function copy(value: string) {
  try {
    await navigator.clipboard.writeText(value)
    copied.value = value
  } catch {
    copied.value = ""
  }
}
</script>
<template>
  <AdminFrame
    title="操作审计"
    subtitle="追溯管理员对账号、额度、会话和模型配置的操作。记录仅包含安全变更字段。"
    ><p v-if="!allowed" role="alert" class="account-card">
      你没有审计读取权限。
    </p>
    <template v-else
      ><AdminLoadState
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
          >动作<select v-model="action" class="account-input mt-2">
            <option value="">全部动作</option>
            <option
              v-for="(label, key) in actionLabels"
              :key="key"
              :value="key"
            >
              {{ label }}
            </option>
          </select></label
        ><label class="account-label"
          >结果<select
            v-model="result"
            data-testid="admin-audit-result"
            class="account-input mt-2"
          >
            <option value="">全部结果</option>
            <option value="success">成功</option>
            <option value="denied">已拒绝</option>
            <option value="failed">失败</option>
          </select></label
        ><label class="account-label"
          >操作者 ID<input
            v-model="actor"
            class="account-input mt-2"
            placeholder="可选：账号 UUID" /></label
        ><label class="account-label"
          >追踪标识<input
            v-model="trace"
            maxlength="64"
            class="account-input mt-2" /></label
        ><label class="account-label"
          >时间从<input
            v-model="start"
            type="datetime-local"
            class="account-input mt-2" /></label
        ><label class="account-label"
          >时间至<input
            v-model="end"
            type="datetime-local"
            class="account-input mt-2" /></label
        ><button
          class="account-secondary justify-self-start"
          :disabled="loading"
        >
          应用查询
        </button>
        <p class="text-xs leading-6 text-ink-muted sm:col-span-2">
          默认最近 7 天，最长 31 天；时间区间不包含结束时间。台账只读。
        </p>
      </form>
      <ol class="space-y-4" aria-label="管理操作记录">
        <li v-for="event in data?.items" :key="event.id" class="account-card">
          <div class="flex flex-wrap items-center justify-between gap-3">
            <h2 class="text-sm font-semibold">
              {{ actionLabels[event.action] ?? event.action }}
            </h2>
            <span
              class="rounded bg-paper-deep px-2 py-1 text-xs"
              :class="{ 'text-cite': event.result !== 'success' }"
              >{{ statusLabels[event.result] }}</span
            >
          </div>
          <p class="mt-2 text-xs text-ink-muted">
            {{ formatTime(event.created_at) }}
          </p>
          <dl class="mt-4 grid min-w-0 gap-3 text-xs sm:grid-cols-2">
            <div>
              <dt class="text-ink-muted">操作者 ID</dt>
              <dd class="mt-1 break-all font-mono">
                {{ event.actor_user_id }}
              </dd>
            </div>
            <div>
              <dt class="text-ink-muted">
                {{ event.resource_type === "user" ? "账号" : "模型" }}对象 ID
              </dt>
              <dd class="mt-1 break-all font-mono">{{ event.resource_id }}</dd>
            </div>
          </dl>
          <dl
            v-if="Object.keys(event.changes_json).length"
            class="mt-4 grid gap-2 border-t border-line pt-4 text-sm"
          >
            <div
              v-for="(value, key) in event.changes_json"
              :key="key"
              class="flex flex-wrap items-baseline justify-between gap-2"
            >
              <dt class="text-xs text-ink-muted">{{ fields[key] ?? key }}</dt>
              <dd class="break-all font-mono text-xs">{{ change(value) }}</dd>
            </div>
          </dl>
          <p v-else class="mt-4 text-xs text-ink-muted">
            此动作没有可展示的字段变更。
          </p>
          <p v-if="event.error_code" class="mt-3 break-all text-xs text-cite">
            {{ event.error_code }}
          </p>
          <div
            class="mt-4 flex flex-wrap items-center gap-3 border-t border-line pt-3 text-xs text-ink-muted"
          >
            <span class="break-all font-mono">{{ event.trace_id }}</span
            ><button
              class="text-brand-700 underline"
              @click="copy(event.trace_id)"
            >
              {{ copied === event.trace_id ? "已复制" : "复制追踪标识" }}
            </button>
          </div>
        </li>
      </ol>
      <p
        v-if="data && !data.items.length && !loading"
        class="account-card text-sm text-ink-muted"
      >
        暂无匹配的管理操作。
      </p>
      <nav
        aria-label="审计分页"
        class="mt-5 flex flex-wrap items-center justify-between gap-3 text-sm"
      >
        <span>共 {{ data?.total ?? "—" }} 条</span>
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
      </nav></template
    ></AdminFrame
  >
</template>
