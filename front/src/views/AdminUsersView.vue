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
  createUser,
  deleteUser,
  listUsers,
  resetUserPassword,
  updateUser,
  type UserUpdate,
  type AdminUserDetail,
  readUser,
  setChatLimit,
  revokeUserSessions,
} from "../api/adminUsers"
import type { User, UserRole } from "../api/users"
import AdminDrawer from "../components/shared/AdminDrawer.vue"
import AdminError from "../components/shared/AdminError.vue"
import { formatTime, errorTrace } from "../shared/admin"
import AdminFrame from "../components/shared/AdminFrame.vue"
import ConfirmDialog from "../components/shared/ConfirmDialog.vue"
import { useUserStore } from "../stores/user"
import { isValidEmail, passwordIssues } from "../shared/auth/passwordPolicy"

const user = useUserStore()
const allowed = computed(() => user.hasPermission("users:manage"))
const items = ref<User[]>([]),
  total = ref(0),
  offset = ref(0),
  limit = 20
const loading = ref(false),
  busyId = ref<string | null>(null),
  error = ref("")
const rowErrors = ref<Record<string, string>>({})
const pending = ref<{
  user: User
  update: UserUpdate
  title: string
  message: string
  deleting?: boolean
  quota?: number | null
  revoke?: boolean
} | null>(null)
const creating = ref(false),
  saving = ref(false),
  formError = ref(""),
  success = ref("")
const resetTarget = ref<User | null>(null)
const form = reactive({
  email: "",
  display_name: "",
  password: "",
  confirm_password: "",
  role: "member" as UserRole,
})
const resetForm = reactive({ new_password: "", confirm_password: "" })
function clearSecrets() {
  form.password =
    form.confirm_password =
    resetForm.new_password =
    resetForm.confirm_password =
      ""
}
function closeForm() {
  if (saving.value) return
  creating.value = false
  resetTarget.value = null
  clearSecrets()
  formError.value = ""
}
function showCreate(event?: Event) {
  ;(event?.currentTarget as HTMLElement | null)?.focus()
  closeForm()
  creating.value = true
  success.value = ""
}
function showReset(target: User) {
  closeForm()
  resetTarget.value = target
  success.value = ""
}
async function submitCreate() {
  if (saving.value || busyId.value || !allowed.value) return
  formError.value = ""
  if (!form.display_name.trim() || form.display_name.trim().length > 100)
    formError.value = "显示名称须为 1–100 个字符"
  else if (!isValidEmail(form.email)) formError.value = "请输入有效邮箱"
  else if (passwordIssues(form.password, form.email).length)
    formError.value = passwordIssues(form.password, form.email).join("；")
  else if (form.password !== form.confirm_password)
    formError.value = "两次输入的密码不一致"
  if (formError.value) return
  saving.value = true
  try {
    const created = await createUser({
      email: form.email.trim(),
      display_name: form.display_name.trim(),
      password: form.password,
      role: form.role,
    })
    clearSecrets()
    creating.value = false
    form.email = form.display_name = ""
    success.value = "用户已创建，可使用初始密码登录。"
    await load(0)
    if (hasFilters.value && !items.value.some((row) => row.id === created.id))
      success.value = "已保存，当前筛选下不可见。"
  } catch (cause) {
    traceId.value = errorTrace(cause)
    formError.value = cause instanceof Error ? cause.message : "新增用户失败"
  } finally {
    saving.value = false
  }
}
async function submitReset() {
  const target = resetTarget.value
  if (!target || saving.value || !allowed.value) return
  formError.value = passwordIssues(
    resetForm.new_password,
    target.email ?? "",
  ).join("；")
  if (!formError.value && resetForm.new_password !== resetForm.confirm_password)
    formError.value = "两次输入的密码不一致"
  if (formError.value) return
  saving.value = true
  try {
    await resetUserPassword(target.id, { new_password: resetForm.new_password })
    clearSecrets()
    resetTarget.value = null
    success.value = `${target.display_name} 的密码已重置，所有设备需要重新登录。`
  } catch (cause) {
    traceId.value = errorTrace(cause)
    formError.value = cause instanceof Error ? cause.message : "重置密码失败"
  } finally {
    saving.value = false
  }
}
function requestDelete(target: User, event: Event) {
  returnFocus = event.currentTarget as HTMLElement
  pending.value = {
    user: target,
    update: {},
    deleting: true,
    title: "删除账号",
    message: `删除 ${target.email ?? target.display_name} 后，该账号立即失效，历史资料与归属会保留。此操作无法在后台恢复，确认删除？`,
  }
}
onUnmounted(clearSecrets)
watch(allowed, (value) => {
  if (!value) {
    clearSecrets()
    listRequest++
    detailRequest++
    items.value = []
    detailId.value = null
    detail.value = null
    pending.value = null
    creating.value = false
    resetTarget.value = null
  }
})
let returnFocus: HTMLElement | null = null
const roleLabels: Record<UserRole, string> = {
  admin: "管理员",
  member: "成员",
  viewer: "只读",
}
const search = ref("")
const roleFilter = ref<UserRole | "">("")
const statusFilter = ref<User["status"] | "">("")
const hasFilters = computed(
  () => !!(search.value.trim() || roleFilter.value || statusFilter.value),
)
const loadedAt = ref(""),
  traceId = ref<string | null>(null)
let listRequest = 0,
  searchTimer: ReturnType<typeof setTimeout> | undefined
async function load(nextOffset = offset.value) {
  if (!allowed.value) return
  const request = ++listRequest
  loading.value = true
  error.value = ""
  try {
    const page = await listUsers({
      offset: nextOffset,
      limit,
      ...(search.value.trim() ? { q: search.value.trim() } : {}),
      ...(roleFilter.value ? { role: roleFilter.value } : {}),
      ...(statusFilter.value ? { status: statusFilter.value } : {}),
    })
    if (!allowed.value || request !== listRequest) return
    items.value = page.items
    total.value = page.total
    offset.value = nextOffset
    loadedAt.value = new Date().toISOString()
  } catch (cause) {
    if (request !== listRequest) return
    traceId.value = errorTrace(cause)
    error.value = cause instanceof Error ? cause.message : "加载用户失败"
  } finally {
    if (request === listRequest) loading.value = false
  }
}
watch(search, () => {
  clearTimeout(searchTimer)
  searchTimer = setTimeout(() => load(0), 300)
})
watch([roleFilter, statusFilter], () => {
  clearTimeout(searchTimer)
  load(0)
})
function resetFilters() {
  search.value = ""
  roleFilter.value = ""
  statusFilter.value = ""
  clearTimeout(searchTimer)
  load(0)
}
const detailId = ref<string | null>(null),
  detail = ref<AdminUserDetail | null>(null),
  detailLoading = ref(false),
  detailError = ref("")
const detailTrigger = ref<HTMLElement | null>(null),
  quotaInput = ref<number | string>(3),
  unlimited = ref(false)
let detailRequest = 0
async function loadDetail(id: string) {
  const request = ++detailRequest
  detailLoading.value = true
  detailError.value = ""
  try {
    const data = await readUser(id)
    if (request !== detailRequest || detailId.value !== id || !allowed.value)
      return
    detail.value = data
    quotaInput.value = data.chat_limit.hourly_limit ?? 3
    unlimited.value = data.chat_limit.hourly_limit === null
  } catch (cause) {
    if (request === detailRequest) {
      detailError.value =
        cause instanceof Error ? cause.message : "读取详情失败"
      traceId.value = errorTrace(cause)
    }
  } finally {
    if (request === detailRequest) detailLoading.value = false
  }
}
function openDetail(target: User, event: Event) {
  detailTrigger.value = event.currentTarget as HTMLElement
  detailId.value = target.id
  detail.value = null
  loadDetail(target.id)
}
function closeDetail() {
  detailRequest++
  detailId.value = null
  detail.value = null
  detailError.value = ""
}
function requestQuota(event: Event) {
  if (!detail.value || busyId.value) return
  const value = unlimited.value ? null : Number(quotaInput.value)
  if (
    value !== null &&
    (!Number.isInteger(value) || value < 1 || value > 100000)
  ) {
    detailError.value = "每小时额度须为 1–100000 整数，或选择不限额"
    return
  }
  returnFocus = event.currentTarget as HTMLElement
  pending.value = {
    user: detail.value.user,
    update: {},
    quota: value,
    title: "调整问答额度",
    message: `调整 ${detail.value.user.email} 的最近 60 分钟额度为${value === null ? "不限额" : value}。已有预留会保留；收紧后已接纳请求继续，新请求按新额度准入。`,
  }
}
function requestRevoke(event: Event) {
  if (!detail.value || busyId.value) return
  returnFocus = event.currentTarget as HTMLElement
  pending.value = {
    user: detail.value.user,
    update: {},
    revoke: true,
    title: "退出所有设备",
    message: `确认让 ${detail.value.user.email} 退出所有设备？该用户需要重新登录，密码与资料会保留。`,
  }
}
onUnmounted(() => {
  clearTimeout(searchTimer)
  listRequest++
  detailRequest++
})
function changeRole(target: User, event: Event) {
  const select = event.target as HTMLSelectElement
  const role = select.value as UserRole
  select.value = target.role
  if (role === target.role) return
  returnFocus = select
  pending.value = {
    user: target,
    update: { role },
    title: "变更用户角色",
    message: `将 ${target.display_name} 的角色改为${roleLabels[role]}？权限将在下一次请求生效。`,
  }
}
function toggleStatus(target: User, event: Event) {
  returnFocus = event.currentTarget as HTMLElement
  const status = target.status === "active" ? "disabled" : "active"
  pending.value = {
    user: target,
    update: { status },
    title: status === "disabled" ? "禁用账号" : "启用账号",
    message:
      status === "disabled"
        ? `禁用 ${target.display_name} 后，该账号将立即退出所有设备，资料会保留。`
        : `允许 ${target.display_name} 重新登录？`,
  }
}
async function close() {
  pending.value = null
  await nextTick()
  returnFocus?.focus()
}
async function confirm() {
  const action = pending.value
  if (!action || busyId.value) return
  busyId.value = action.user.id
  rowErrors.value[action.user.id] = ""
  pending.value = null
  let reload = false
  try {
    if (action.revoke) {
      await revokeUserSessions(action.user.id)
      await loadDetail(action.user.id)
      success.value = "设备会话已撤销，该用户需要重新登录。"
    } else if ("quota" in action) {
      const snapshot = await setChatLimit(action.user.id, action.quota ?? null)
      if (detail.value?.user.id === action.user.id)
        detail.value.chat_limit = snapshot
      detailError.value = ""
      success.value = "问答额度已更新，已有预留会保留。"
    } else if (action.deleting) {
      await deleteUser(action.user.id)
      total.value = Math.max(0, total.value - 1)
      reload = true
      success.value = "账号已删除，历史资料已保留。"
    } else {
      const updated = await updateUser(action.user.id, action.update)
      items.value = items.value.map((row) =>
        row.id === updated.id ? updated : row,
      )
      if (updated.id === user.currentUser?.id) user.currentUser = updated
      if (detail.value?.user.id === updated.id) detail.value.user = updated
      if (hasFilters.value) {
        reload = true
        success.value = "已保存，列表已按当前筛选刷新。"
      }
    }
  } catch (cause) {
    traceId.value = errorTrace(cause)
    const message = cause instanceof Error ? cause.message : "更新失败，请重试"
    rowErrors.value[action.user.id] = message
    if (detailId.value === action.user.id) detailError.value = message
  } finally {
    busyId.value = null
    if (reload)
      await load(
        Math.min(
          offset.value,
          Math.max(0, Math.ceil(total.value / limit) - 1) * limit,
        ),
      )
    await close()
  }
}
onMounted(() => load())
</script>

<template>
  <AdminFrame
    title="用户管理"
    subtitle="维护账号、角色与访问状态。管理员权限不包含读取他人的私有资料。"
  >
    <div
      v-if="!allowed"
      data-testid="admin-forbidden"
      role="alert"
      class="account-card text-ink-muted"
    >
      你没有用户管理权限。
    </div>
    <template v-else>
      <div
        class="account-card mb-5 grid gap-4 sm:grid-cols-[minmax(0,1fr)_auto_auto]"
      >
        <label class="account-label !mb-0"
          >搜索账号<input
            v-model="search"
            data-testid="admin-user-search"
            class="account-input mt-2"
            type="search"
            maxlength="100"
            placeholder="邮箱或显示名称"
            autocomplete="off"
        /></label>
        <label class="account-label !mb-0"
          >角色<select
            v-model="roleFilter"
            data-testid="admin-role-filter"
            class="account-input mt-2"
          >
            <option value="">全部角色</option>
            <option value="admin">管理员</option>
            <option value="member">成员</option>
            <option value="viewer">只读</option>
          </select></label
        >
        <label class="account-label !mb-0"
          >状态<select
            v-model="statusFilter"
            data-testid="admin-status-filter"
            class="account-input mt-2"
          >
            <option value="">全部状态</option>
            <option value="active">正常</option>
            <option value="disabled">已停用</option>
          </select></label
        >
        <button
          v-if="hasFilters"
          class="justify-self-start text-xs text-brand-700"
          @click="resetFilters"
        >
          重置筛选
        </button>
      </div>
      <div class="mb-5 flex flex-wrap items-center justify-between gap-3">
        <p class="text-sm text-ink-muted">共 {{ total }} 个账号</p>
        <button
          data-testid="admin-create-user"
          class="account-primary"
          :disabled="loading || !!busyId || saving"
          @click="showCreate"
        >
          新增用户
        </button>
      </div>
      <p v-if="success" role="status" class="mb-4 text-sm text-brand-700">
        {{ success }}
      </p>
      <AdminDrawer :open="creating" title="新增用户" @close="closeForm">
        <form
          data-testid="admin-create-form"
          class="account-card mb-6 space-y-4"
          novalidate
          :aria-busy="saving"
          @submit.prevent="submitCreate"
        >
          <h2 class="font-semibold">新增用户</h2>
          <fieldset :disabled="saving" class="grid gap-4 sm:grid-cols-2">
            <label class="account-label"
              >邮箱<input
                v-model="form.email"
                name="email"
                type="email"
                autocomplete="off"
                class="account-input"
                required
            /></label>
            <label class="account-label"
              >显示名称<input
                v-model="form.display_name"
                name="display_name"
                maxlength="100"
                class="account-input"
                required
            /></label>
            <label class="account-label"
              >初始密码<input
                v-model="form.password"
                name="password"
                type="password"
                autocomplete="new-password"
                class="account-input"
                required
            /></label>
            <label class="account-label"
              >确认密码<input
                v-model="form.confirm_password"
                name="confirm_password"
                type="password"
                autocomplete="new-password"
                class="account-input"
                required
            /></label>
            <label class="account-label"
              >角色<select
                v-model="form.role"
                name="role"
                class="account-input"
              >
                <option value="member">成员</option>
                <option value="viewer">只读</option>
                <option value="admin">管理员</option>
              </select></label
            >
          </fieldset>
          <p class="text-xs text-ink-muted">
            密码为 10–128 个字符，须同时包含字母和数字。
          </p>
          <p v-if="formError" role="alert" class="text-sm text-cite">
            {{ formError }}
          </p>
          <div class="flex gap-3">
            <button type="submit" class="account-primary" :disabled="saving">
              {{ saving ? "创建中…" : "创建账号" }}</button
            ><button
              type="button"
              class="account-secondary"
              :disabled="saving"
              @click="closeForm"
            >
              取消
            </button>
          </div>
        </form>
      </AdminDrawer>
      <AdminDrawer :open="!!resetTarget" title="重置密码" @close="closeForm">
        <form
          v-if="resetTarget"
          data-testid="admin-reset-form"
          class="account-card mb-6 space-y-4"
          novalidate
          :aria-busy="saving"
          @submit.prevent="submitReset"
        >
          <h2 class="font-semibold">重置 {{ resetTarget.email }} 的密码</h2>
          <p class="text-sm text-ink-muted">
            确认重置后，该用户的全部设备将退出，需要使用新密码重新登录。
          </p>
          <fieldset :disabled="saving" class="grid gap-4 sm:grid-cols-2">
            <label class="account-label"
              >新密码<input
                v-model="resetForm.new_password"
                name="new_password"
                type="password"
                autocomplete="new-password"
                class="account-input"
                required
            /></label>
            <label class="account-label"
              >确认新密码<input
                v-model="resetForm.confirm_password"
                name="confirm_password"
                type="password"
                autocomplete="new-password"
                class="account-input"
                required
            /></label>
          </fieldset>
          <p v-if="formError" role="alert" class="text-sm text-cite">
            {{ formError }}
          </p>
          <div class="flex gap-3">
            <button type="submit" class="account-primary" :disabled="saving">
              {{ saving ? "重置中…" : "确认重置密码" }}</button
            ><button
              type="button"
              class="account-secondary"
              :disabled="saving"
              @click="closeForm"
            >
              取消
            </button>
          </div>
        </form>
      </AdminDrawer>
      <p v-if="error" role="alert" class="mb-4 text-sm text-cite">
        {{ error }} <button class="underline" @click="load()">重试</button>
      </p>
      <p v-if="loadedAt" class="mb-3 text-xs text-ink-muted">
        {{ error ? "旧数据 · " : "数据截至 " }}{{ formatTime(loadedAt) }}
      </p>
      <p v-if="traceId" class="text-xs text-ink-muted">
        <AdminError
          message="请求未完成，可复制追踪标识排查"
          :trace-id="traceId"
        />
      </p>
      <p v-if="loading" role="status" class="py-6 text-sm text-ink-muted">
        正在加载用户…
      </p>
      <ul class="space-y-3" aria-label="用户列表">
        <li
          v-for="target in items"
          :key="target.id"
          data-testid="admin-user-row"
          class="account-card"
          :aria-busy="busyId === target.id"
        >
          <div
            class="flex flex-col items-stretch justify-between gap-4 sm:flex-row sm:items-start"
          >
            <div class="min-w-0 flex-1">
              <p class="font-medium break-all">
                {{ target.display_name }}
                <span
                  v-if="target.id === user.currentUser?.id"
                  class="text-xs text-brand-700"
                  >（你）</span
                >
              </p>
              <p class="mt-1 text-sm break-all text-ink-muted">
                {{ target.email ?? "未设置邮箱" }}
              </p>
              <p class="mt-2 text-xs text-ink-muted">
                创建于 {{ formatTime(target.created_at) }}
              </p>
              <p
                class="mt-2 text-xs"
                :class="
                  target.status === 'active' ? 'text-brand-700' : 'text-cite'
                "
              >
                {{ target.status === "active" ? "正常" : "已停用" }}
              </p>
            </div>
            <div class="flex flex-wrap items-end gap-3">
              <label class="text-xs text-ink-muted"
                >角色<select
                  :value="target.role"
                  :aria-label="`${target.display_name} 的角色`"
                  class="account-input mt-1 !w-auto"
                  :disabled="!!busyId"
                  @change="changeRole(target, $event)"
                >
                  <option value="admin">管理员</option>
                  <option value="member">成员</option>
                  <option value="viewer">只读</option>
                </select></label
              >
              <button
                data-testid="admin-user-detail-open"
                class="account-secondary"
                @click="openDetail(target, $event)"
              >
                查看详情
              </button>
              <button
                data-testid="status-toggle"
                class="account-secondary"
                :disabled="!!busyId || target.id === user.currentUser?.id"
                @click="toggleStatus(target, $event)"
              >
                {{
                  busyId === target.id
                    ? "更新中…"
                    : target.status === "active"
                      ? "禁用"
                      : "启用"
                }}
              </button>
              <RouterLink
                v-if="target.id === user.currentUser?.id"
                to="/account"
                class="account-secondary"
                >修改我的密码</RouterLink
              >
              <button
                v-else
                data-testid="admin-user-reset"
                class="account-secondary"
                :disabled="!!busyId || saving"
                @click="showReset(target)"
              >
                重置密码
              </button>
              <button
                data-testid="admin-user-delete"
                class="account-secondary !text-cite"
                :disabled="
                  !!busyId || saving || target.id === user.currentUser?.id
                "
                @click="requestDelete(target, $event)"
              >
                删除
              </button>
            </div>
          </div>
          <p
            v-if="rowErrors[target.id]"
            role="alert"
            class="mt-3 text-sm text-cite"
          >
            {{ rowErrors[target.id] }}
          </p>
        </li>
      </ul>
      <p
        v-if="!loading && !items.length && !error"
        class="py-8 text-sm text-ink-muted"
      >
        {{ hasFilters ? "无匹配账号，请调整筛选。" : "暂无账号。" }}
      </p>
      <nav
        class="mt-6 flex flex-wrap items-center justify-between gap-3 text-sm"
        aria-label="用户列表分页"
      >
        <p class="text-ink-muted">
          共 {{ total }} 个账号 · 第 {{ Math.floor(offset / limit) + 1 }} 页
        </p>
        <div class="flex gap-2">
          <button
            class="account-secondary"
            :disabled="loading || !!busyId || offset === 0"
            @click="load(Math.max(0, offset - limit))"
          >
            上一页</button
          ><button
            data-testid="admin-next-page"
            class="account-secondary"
            :disabled="loading || !!busyId || offset + limit >= total"
            @click="load(offset + limit)"
          >
            下一页
          </button>
        </div>
      </nav>
    </template>
    <AdminDrawer
      :open="!!detailId"
      title="用户详情"
      :trigger="detailTrigger"
      @close="closeDetail"
    >
      <p v-if="detailLoading" role="status" class="text-sm text-ink-muted">
        正在读取账号详情…
      </p>
      <AdminError :message="detailError" :trace-id="traceId"
        ><button
          v-if="detailId"
          class="underline"
          @click="loadDetail(detailId)"
        >
          重新读取详情
        </button></AdminError
      >
      <template v-if="detail">
        <h3 class="font-display text-2xl font-semibold break-all">
          {{ detail.user.display_name }}
        </h3>
        <p class="mt-2 break-all text-sm text-ink-muted">
          {{ detail.user.email }}
        </p>
        <dl
          class="my-6 grid grid-cols-2 gap-4 border-y border-line py-5 text-sm"
        >
          <div>
            <dt class="text-ink-muted">角色</dt>
            <dd class="mt-1">{{ roleLabels[detail.user.role] }}</dd>
          </div>
          <div>
            <dt class="text-ink-muted">状态</dt>
            <dd class="mt-1">
              {{ detail.user.status === "active" ? "正常" : "已停用" }}
            </dd>
          </div>
          <div>
            <dt class="text-ink-muted">有效设备会话</dt>
            <dd data-testid="admin-live-sessions" class="mt-1 text-xl">
              {{ detail.active_session_count }}
            </dd>
          </div>
          <div>
            <dt class="text-ink-muted">创建时间</dt>
            <dd class="mt-1">{{ formatTime(detail.user.created_at) }}</dd>
          </div>
        </dl>
        <section class="space-y-4">
          <h3 class="font-semibold">问答额度</h3>
          <p class="text-sm text-ink-muted">
            最近 60 分钟已占用额度（含处理中）：<strong class="text-ink">{{
              detail.chat_limit.occupied_slots ?? "不限额"
            }}</strong
            >；剩余 {{ detail.chat_limit.remaining ?? "不限额" }}
          </p>
          <p class="text-xs leading-6 text-ink-muted">
            失败请求会释放预留。不限额期间不补记，切换额度会保留未过期预留。这不是历史请求量或账单。
          </p>
          <label class="flex items-center gap-2 text-sm"
            ><input
              v-model="unlimited"
              type="checkbox"
              :disabled="!!busyId"
            />不限额</label
          ><label class="account-label"
            >每小时额度<input
              v-model="quotaInput"
              data-testid="admin-quota-input"
              type="number"
              min="1"
              max="100000"
              step="1"
              :disabled="unlimited || !!busyId"
              class="account-input mt-2" /></label
          ><button
            data-testid="admin-quota-save"
            class="account-primary"
            :disabled="!!busyId"
            @click="requestQuota"
          >
            保存额度
          </button>
          <p class="text-xs text-ink-muted">
            额度快照 {{ formatTime(detail.chat_limit.observed_at) }}
          </p>
        </section>
        <section class="mt-7 border-t border-line pt-6">
          <h3 class="mb-3 font-semibold">设备访问</h3>
          <RouterLink
            v-if="detail.user.id === user.currentUser?.id"
            data-testid="admin-own-sessions"
            to="/account"
            class="account-secondary"
            >前往账户页面管理自己的会话</RouterLink
          ><button
            v-else
            data-testid="admin-revoke-sessions"
            class="account-secondary"
            :disabled="!!busyId"
            @click="requestRevoke"
          >
            退出所有设备
          </button>
          <p class="mt-3 text-xs text-ink-muted">
            撤销会话不会修改密码、角色或私有资料。
          </p>
        </section>
        <p v-if="success" role="status" class="mt-5 text-sm text-brand-700">
          {{ success }}
        </p>
      </template>
    </AdminDrawer>
    <ConfirmDialog
      :visible="!!pending"
      :title="pending?.title ?? ''"
      :message="pending?.message"
      :danger="pending?.deleting || pending?.update.status === 'disabled'"
      :confirmation-text="
        pending?.deleting ? (pending.user.email ?? pending.user.id) : undefined
      "
      :confirmation-label="
        pending?.user.email ? undefined : '输入完整账号 UUID 以确认'
      "
      @confirm="confirm"
      @cancel="close"
    />
  </AdminFrame>
</template>
