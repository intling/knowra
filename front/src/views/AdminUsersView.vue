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
} from "../api/adminUsers"
import type { User, UserRole } from "../api/users"
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
function showCreate() {
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
    await createUser({
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
  } catch (cause) {
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
async function load(nextOffset = offset.value) {
  if (!allowed.value || loading.value || busyId.value) return
  loading.value = true
  error.value = ""
  try {
    const page = await listUsers({ offset: nextOffset, limit })
    if (!allowed.value) return
    items.value = page.items
    total.value = page.total
    offset.value = nextOffset
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : "加载用户失败"
  } finally {
    loading.value = false
  }
}
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
    if (action.deleting) {
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
    }
  } catch (cause) {
    rowErrors.value[action.user.id] =
      cause instanceof Error ? cause.message : "更新失败，请重试"
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
      <form
        v-if="creating"
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
            >角色<select v-model="form.role" name="role" class="account-input">
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
      <p v-if="error" role="alert" class="mb-4 text-sm text-cite">
        {{ error }} <button class="underline" @click="load()">重试</button>
      </p>
      <p v-if="loading" role="status" class="py-6 text-sm text-ink-muted">
        正在加载用户…
      </p>
      <ul v-else class="space-y-3" aria-label="用户列表">
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
                class="text-sm text-brand-700"
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
        暂无账号。
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
    <ConfirmDialog
      :visible="!!pending"
      :title="pending?.title ?? ''"
      :message="pending?.message"
      :danger="pending?.deleting || pending?.update.status === 'disabled'"
      @confirm="confirm"
      @cancel="close"
    />
  </AdminFrame>
</template>
