<script setup lang="ts">
import {
  computed,
  nextTick,
  onMounted,
  onUnmounted,
  reactive,
  ref,
  watch,
} from "vue"
import {
  activateModel,
  createModel,
  deactivateModel,
  deleteModel,
  listModels,
  updateModel,
  type ModelKind,
  type ModelProfile,
  type ModelWrite,
  getEffectiveModels,
  testModel,
  type ModelProbe,
} from "../api/adminModels"
import AdminDrawer from "../components/shared/AdminDrawer.vue"
import EffectiveModelCards from "../components/shared/EffectiveModelCards.vue"
import AdminError from "../components/shared/AdminError.vue"
import { useAdminResource } from "../shared/useAdminResource"
import { useAdminClock } from "../shared/useAdminClock"
import { errorTrace, formatTime, isCurrentProbe } from "../shared/admin"
import AdminFrame from "../components/shared/AdminFrame.vue"
import ConfirmDialog from "../components/shared/ConfirmDialog.vue"
import { useUserStore } from "../stores/user"

const user = useUserStore()
const now = useAdminClock()
const allowed = computed(() => user.hasPermission("models:manage"))
const kinds: Record<ModelKind, string> = {
  chat: "聊天与回答",
  embedding: "Embedding 向量化",
  rerank: "检索重排",
  query_rewrite: "查询改写",
}
const items = ref<ModelProfile[]>([]),
  total = ref(0),
  offset = ref(0),
  filter = ref<ModelKind | "">("")
const loading = ref(false),
  busy = ref(false),
  error = ref(""),
  success = ref("")
const editing = ref<ModelProfile | null>(null),
  formOpen = ref(false),
  formError = ref("")
const form = reactive({
  name: "",
  kind: "chat" as ModelKind,
  base_url: "",
  model: "",
  api_key: "",
  clear_api_key: false,
  timeout_seconds: 15,
  max_retries: 1,
  api_format: "compatible" as "compatible" | "dashscope",
})
type Action = "activate" | "deactivate" | "delete" | "toggle" | "test"
const pending = ref<{
  profile: ModelProfile
  action: Action
  title: string
  message: string
} | null>(null)
let returnFocus: HTMLElement | null = null
const effective = useAdminResource("models:manage", async () => {
  const data = await getEffectiveModels()
  if (!Array.isArray(data)) throw new Error("生效配置摘要暂不可用")
  return data
})
const probes = ref<Record<string, ModelProbe>>({}),
  testing = reactive<Record<string, boolean>>({}),
  traceId = ref<string | null>(null)
let listRequest = 0,
  alive = true

async function load(nextOffset = offset.value) {
  if (!allowed.value) return
  const request = ++listRequest
  loading.value = true
  error.value = ""
  try {
    const page = await listModels({
      offset: nextOffset,
      limit: 20,
      kind: filter.value,
    })
    if (!allowed.value || request !== listRequest) return
    items.value = page.items
    total.value = page.total
    offset.value = nextOffset
  } catch (cause) {
    if (request !== listRequest) return
    traceId.value = errorTrace(cause)
    error.value = cause instanceof Error ? cause.message : "加载模型配置失败"
  } finally {
    if (request === listRequest) loading.value = false
  }
}
function closeForm() {
  if (busy.value) return
  formOpen.value = false
  form.api_key = ""
  form.clear_api_key = false
  formError.value = ""
}
function openForm(profile: ModelProfile | null = null) {
  editing.value = profile
  Object.assign(form, {
    name: profile?.name ?? "",
    kind: profile?.kind ?? "chat",
    base_url: profile?.base_url ?? "",
    model: profile?.model ?? "",
    api_key: "",
    clear_api_key: false,
    timeout_seconds: profile?.timeout_seconds ?? 15,
    max_retries: profile?.max_retries ?? 1,
    api_format: profile?.api_format ?? "compatible",
  })
  formError.value = ""
  formOpen.value = true
  success.value = ""
}
async function save() {
  if (busy.value || !allowed.value) return
  formError.value = ""
  if (!form.name.trim() || !form.model.trim())
    formError.value = "请填写配置名称和模型标识"
  else {
    try {
      const url = new URL(form.base_url)
      if (
        !["http:", "https:"].includes(url.protocol) ||
        url.username ||
        url.password ||
        url.search ||
        url.hash
      )
        formError.value = "API 地址须为 HTTP(S)，不能包含凭据、查询参数或片段"
    } catch {
      formError.value = "请输入有效的 API 地址"
    }
  }
  if (form.timeout_seconds < 1 || form.timeout_seconds > 120)
    formError.value = "超时须为 1–120 秒"
  if (form.clear_api_key && form.api_key)
    formError.value = "不能同时清除和替换密钥"
  if (formError.value) return
  const payload: ModelWrite = {
    name: form.name.trim(),
    base_url: form.base_url.trim(),
    model: form.model.trim(),
    timeout_seconds: Number(form.timeout_seconds),
    max_retries: form.kind === "rerank" ? 0 : Number(form.max_retries),
  }
  if (form.api_key) payload.api_key = form.api_key
  if (editing.value && form.clear_api_key) payload.clear_api_key = true
  if (form.kind === "embedding") payload.dimensions = 2560
  if (form.kind === "rerank") payload.api_format = form.api_format
  busy.value = true
  try {
    if (editing.value) await updateModel(editing.value.id, payload)
    else await createModel({ ...payload, kind: form.kind })
    form.api_key = ""
    formOpen.value = false
    success.value = editing.value?.is_default
      ? "配置已保存，下一次请求生效。"
      : "配置已保存，可设为对应用途的默认模型。"
    if (editing.value && probes.value[editing.value.id])
      probes.value[editing.value.id]!.is_current = false
    await Promise.allSettled([
      load(editing.value ? offset.value : 0),
      effective.refresh(),
    ])
  } catch (cause) {
    formError.value =
      cause instanceof Error ? cause.message : "保存模型配置失败"
  } finally {
    busy.value = false
  }
}
function requestAction(action: Action, profile: ModelProfile, event: Event) {
  returnFocus = event.currentTarget as HTMLElement
  const title = {
    activate: "设为默认模型",
    deactivate: "恢复环境配置",
    delete: "删除模型配置",
    toggle: profile.enabled ? "禁用模型配置" : "启用模型配置",
    test: "测试模型连接",
  }[action]
  pending.value = {
    profile,
    action,
    title,
    message:
      action === "test"
        ? `测试「${profile.name}」已保存的配置版本 ${profile.revision}。会发送少量固定测试内容，可能产生少量费用；不会改变默认模型。`
        : action === "activate"
          ? `将「${profile.name}」设为${kinds[profile.kind]}的默认模型？下一次请求生效，在途请求继续使用原配置。`
          : action === "deactivate"
            ? `取消「${profile.name}」的默认绑定，恢复服务器环境配置？下一次请求生效。`
            : action === "delete"
              ? `确认删除「${profile.name}」？此操作无法恢复。`
              : `确认${title}「${profile.name}」？`,
  }
}
async function close() {
  pending.value = null
  await nextTick()
  returnFocus?.focus()
}
async function confirm() {
  const action = pending.value
  if (!action || busy.value || !allowed.value) return
  pending.value = null
  if (action.action === "test") {
    if (testing[action.profile.id]) return
    testing[action.profile.id] = true
    error.value = ""
    traceId.value = null
    try {
      const result = await testModel(action.profile.id, action.profile.revision)
      if (alive && allowed.value) {
        probes.value[action.profile.id] = result
        await effective.refresh()
      }
    } catch (cause) {
      if (alive) {
        error.value = cause instanceof Error ? cause.message : "测试未完成"
        traceId.value = errorTrace(cause)
      }
    } finally {
      testing[action.profile.id] = false
      await close()
    }
    return
  }
  busy.value = true
  error.value = ""
  try {
    if (action.action === "activate") await activateModel(action.profile.id)
    else if (action.action === "deactivate")
      await deactivateModel(action.profile.id)
    else if (action.action === "delete") await deleteModel(action.profile.id)
    else
      await updateModel(action.profile.id, { enabled: !action.profile.enabled })
    await effective.refresh()
    success.value =
      action.action === "activate" || action.action === "deactivate"
        ? "默认配置已更新，下一次请求生效。"
        : "模型配置已更新。"
    const count =
      action.action === "delete" ? Math.max(0, total.value - 1) : total.value
    await load(
      Math.min(offset.value, Math.max(0, Math.ceil(count / 20) - 1) * 20),
    )
  } catch (cause) {
    traceId.value = errorTrace(cause)
    error.value = cause instanceof Error ? cause.message : "更新模型配置失败"
  } finally {
    busy.value = false
    await close()
  }
}
watch(allowed, (value) => {
  if (!value) {
    form.api_key = ""
    formOpen.value = false
    pending.value = null
    items.value = []
  }
})
onUnmounted(() => {
  alive = false
  listRequest++
  form.api_key = ""
})
onMounted(() => load(0))
</script>

<template>
  <AdminFrame title="模型配置" subtitle="为问答和资料处理选择合适的模型服务。">
    <p v-if="!allowed" role="alert" class="account-card text-ink-muted">
      你没有模型管理权限。
    </p>
    <template v-else>
      <section class="mb-7">
        <div class="mb-4 flex flex-wrap items-center justify-between gap-3">
          <h2 class="font-display text-lg font-semibold">当前生效用途</h2>
          <button
            class="text-xs text-brand-700 underline"
            :disabled="effective.loading.value"
            @click="effective.refresh()"
          >
            刷新生效配置
          </button>
        </div>
        <AdminError
          :message="effective.error.value"
          :trace-id="effective.traceId.value"
        /><EffectiveModelCards
          v-if="effective.data.value"
          :models="effective.data.value"
        />
        <p
          v-else-if="effective.loading.value"
          class="account-card text-sm text-ink-muted"
        >
          正在读取四用途配置…
        </p>
      </section>
      <div class="mb-5 flex flex-wrap items-end justify-between gap-4">
        <label class="text-sm text-ink-muted"
          >模型用途<select
            v-model="filter"
            class="account-input mt-1"
            :disabled="loading || busy"
            @change="load(0)"
          >
            <option value="">全部用途</option>
            <option v-for="(label, kind) in kinds" :key="kind" :value="kind">
              {{ label }}
            </option>
          </select></label
        >
        <button
          data-testid="admin-create-model"
          class="account-primary"
          :disabled="busy || loading"
          @click="openForm()"
        >
          新增模型配置
        </button>
      </div>
      <p class="mb-5 text-sm leading-6 text-ink-muted">
        每种用途可选一个默认模型。未指定默认模型时使用服务器环境配置；修改默认模型在下一次请求生效。
      </p>
      <p v-if="success" role="status" class="mb-4 text-sm text-brand-700">
        {{ success }}
      </p>
      <AdminDrawer
        :open="formOpen"
        :title="editing ? '编辑模型配置' : '新增模型配置'"
        @close="closeForm"
      >
        <form
          data-testid="admin-model-form"
          class="account-card mb-6 space-y-4"
          novalidate
          :aria-busy="busy"
          @submit.prevent="save"
        >
          <h2 class="font-semibold">
            {{ editing ? "编辑模型配置" : "新增模型配置" }}
          </h2>
          <fieldset :disabled="busy" class="grid min-w-0 gap-4 sm:grid-cols-2">
            <label class="account-label"
              >用途<select
                v-model="form.kind"
                name="kind"
                class="account-input"
                :disabled="!!editing"
              >
                <option
                  v-for="(label, kind) in kinds"
                  :key="kind"
                  :value="kind"
                >
                  {{ label }}
                </option>
              </select></label
            >
            <label class="account-label"
              >配置名称<input
                v-model="form.name"
                name="name"
                class="account-input"
                maxlength="100"
                required
            /></label>
            <label class="account-label sm:col-span-2"
              >API 地址<input
                v-model="form.base_url"
                name="base_url"
                type="url"
                class="account-input"
                placeholder="https://api.example.com/v1"
                maxlength="2048"
                required
            /></label>
            <label class="account-label sm:col-span-2"
              >模型标识<input
                v-model="form.model"
                name="model"
                class="account-input"
                maxlength="255"
                required
            /></label>
            <label class="account-label sm:col-span-2"
              >API Key<input
                v-model="form.api_key"
                name="api_key"
                type="password"
                autocomplete="new-password"
                class="account-input"
                :placeholder="
                  editing?.has_api_key
                    ? '已配置密钥；留空保留原值'
                    : '可选：无鉴权本地服务可留空'
                "
            /></label>
            <label
              v-if="editing?.has_api_key"
              class="flex items-center gap-2 text-sm sm:col-span-2"
              ><input
                v-model="form.clear_api_key"
                type="checkbox"
              />明确清除已有密钥</label
            >
            <label class="account-label"
              >超时（秒）<input
                v-model.number="form.timeout_seconds"
                name="timeout_seconds"
                type="number"
                min="1"
                max="120"
                class="account-input"
            /></label>
            <label v-if="form.kind !== 'rerank'" class="account-label"
              >最大重试次数<input
                v-model.number="form.max_retries"
                name="max_retries"
                type="number"
                min="0"
                max="3"
                class="account-input"
            /></label>
            <label v-if="form.kind === 'embedding'" class="account-label"
              >向量维度<input
                name="dimensions"
                value="2560"
                readonly
                class="account-input"
            /></label>
            <label v-if="form.kind === 'rerank'" class="account-label"
              >重排协议<select
                v-model="form.api_format"
                name="api_format"
                class="account-input"
              >
                <option value="compatible">通用 Rerank</option>
                <option value="dashscope">DashScope</option>
              </select></label
            >
          </fieldset>
          <p
            v-if="form.kind === 'embedding'"
            class="text-xs leading-5 text-ink-muted"
          >
            当前索引支持 2560
            维。已有向量或运行中的任务时，切换地址或模型需要先规划重建索引。
          </p>
          <p v-if="editing" class="text-xs text-ink-muted">
            密钥不会回显；留空保留已有密钥。
          </p>
          <p v-if="formError" role="alert" class="text-sm text-cite">
            {{ formError }}
          </p>
          <div class="flex gap-3">
            <button type="submit" class="account-primary" :disabled="busy">
              {{ busy ? "保存中…" : "保存配置" }}</button
            ><button
              type="button"
              class="account-secondary"
              :disabled="busy"
              @click="closeForm"
            >
              取消
            </button>
          </div>
        </form>
      </AdminDrawer>
      <AdminError v-if="error" :message="error" :trace-id="traceId" />
      <p v-if="error" role="alert" class="mb-4 text-sm text-cite">
        {{ error }}
        <button class="underline" :disabled="loading || busy" @click="load()">
          重新加载
        </button>
      </p>
      <p v-if="loading" role="status" class="py-8 text-sm text-ink-muted">
        正在加载模型配置…
      </p>
      <ul v-else class="space-y-4" aria-label="模型配置列表">
        <li
          v-for="profile in items"
          :key="profile.id"
          data-testid="admin-model-row"
          class="account-card"
        >
          <div class="flex flex-wrap items-center justify-between gap-2">
            <h2 class="min-w-0 font-semibold break-all">{{ profile.name }}</h2>
            <span class="text-xs text-brand-700">{{
              profile.is_default
                ? "默认模型"
                : profile.enabled
                  ? "可用"
                  : "已禁用"
            }}</span>
          </div>
          <p class="mt-2 text-xs text-ink-muted">
            {{ kinds[profile.kind] }} ·
            {{ profile.has_api_key ? "已配置密钥" : "无密钥" }} · 超时
            {{ profile.timeout_seconds }} 秒 · 配置版本 {{ profile.revision }}
          </p>
          <p class="mt-3 text-sm break-all">{{ profile.model }}</p>
          <p class="mt-1 text-sm break-all text-ink-muted">
            {{ profile.base_url }}
          </p>
          <div
            v-if="probes[profile.id]"
            class="mt-4 rounded-lg border border-line bg-paper p-3 text-xs leading-6"
          >
            <p>
              {{ probes[profile.id]!.detail }} ·
              {{
                isCurrentProbe(
                  probes[profile.id]!,
                  profile.revision,
                  probes[profile.id]!.config_revision,
                  now,
                )
                  ? "当前参考"
                  : "已过期"
              }}
            </p>
            <p class="text-ink-muted">
              检查于 {{ formatTime(probes[profile.id]!.checked_at) }} ·
              {{ probes[profile.id]!.latency_ms ?? "—" }} ms
            </p>
          </div>
          <div class="mt-4 flex flex-wrap gap-2">
            <button
              data-testid="admin-model-test"
              class="account-secondary"
              :disabled="busy || testing[profile.id]"
              @click="requestAction('test', profile, $event)"
            >
              {{ testing[profile.id] ? "测试中…" : "测试连接" }}
            </button>
            <button
              data-testid="admin-model-edit"
              class="account-secondary"
              :disabled="busy"
              @click="openForm(profile)"
            >
              编辑
            </button>
            <button
              v-if="!profile.is_default"
              data-testid="admin-model-activate"
              class="account-secondary"
              :disabled="busy || !profile.enabled"
              @click="requestAction('activate', profile, $event)"
            >
              设为默认
            </button>
            <button
              v-else
              class="account-secondary"
              :disabled="busy"
              @click="requestAction('deactivate', profile, $event)"
            >
              恢复环境配置
            </button>
            <button
              class="account-secondary"
              :disabled="busy || profile.is_default"
              @click="requestAction('toggle', profile, $event)"
            >
              {{ profile.enabled ? "禁用" : "启用" }}
            </button>
            <button
              data-testid="admin-model-delete"
              class="account-secondary !text-cite"
              :disabled="busy || profile.is_default"
              @click="requestAction('delete', profile, $event)"
            >
              删除
            </button>
          </div>
        </li>
      </ul>
      <p class="mt-4 text-xs leading-6 text-ink-muted">
        连接测试使用固定短样例，可能产生少量费用。通过仅表示连接与协议检查成功，不能代表回答或检索质量。
      </p>
      <p
        v-if="!loading && !items.length && !error"
        class="account-card text-sm text-ink-muted"
      >
        暂无模型配置。新增配置后可选择默认模型；当前沿用环境配置。
      </p>
      <nav
        class="mt-6 flex flex-wrap items-center justify-between gap-3 text-sm"
        aria-label="模型配置分页"
      >
        <p class="text-ink-muted">
          共 {{ total }} 项 · 第 {{ Math.floor(offset / 20) + 1 }} 页
        </p>
        <div class="flex gap-2">
          <button
            class="account-secondary"
            :disabled="busy || loading || !offset"
            @click="load(offset - 20)"
          >
            上一页</button
          ><button
            class="account-secondary"
            :disabled="busy || loading || offset + 20 >= total"
            @click="load(offset + 20)"
          >
            下一页
          </button>
        </div>
      </nav>
    </template>
    <ConfirmDialog
      :visible="!!pending"
      :title="pending?.title ?? ''"
      :message="pending?.message"
      :danger="pending?.action === 'delete'"
      @confirm="confirm"
      @cancel="close"
    />
  </AdminFrame>
</template>
