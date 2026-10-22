<script setup lang="ts">
import { computed, ref } from "vue"
import { useRouter } from "vue-router"
import AccountFrame from "../components/shared/AccountFrame.vue"
import { uniqueId } from "../shared/a11y/focus"
import { passwordIssues } from "../shared/auth/passwordPolicy"
import { useUserStore } from "../stores/user"

const user = useUserStore(),
  router = useRouter()
const roleLabel = computed(
  () =>
    ({ admin: "管理员", member: "成员", viewer: "只读" })[
      user.currentUser?.role ?? "member"
    ],
)
const name = ref(user.currentUser?.display_name ?? "")
const current = ref(""),
  next = ref(""),
  confirm = ref("")
const profileError = ref(""),
  profileStatus = ref(""),
  passwordError = ref(""),
  logoutError = ref("")
const saving = ref(false),
  changing = ref(false),
  leaving = ref(false)
const ids = {
  name: uniqueId("profile-name"),
  current: uniqueId("password-current"),
  next: uniqueId("password-next"),
  confirm: uniqueId("password-confirm"),
  profileError: uniqueId("profile-error"),
  passwordError: uniqueId("password-error"),
}
const message = (cause: unknown) =>
  cause instanceof Error ? cause.message : "操作失败，请重试"
async function saveProfile() {
  if (saving.value) return
  profileError.value = profileStatus.value = ""
  if (!name.value.trim() || Array.from(name.value.trim()).length > 100) {
    profileError.value = "显示名称须为 1–100 个字符"
    return
  }
  saving.value = true
  try {
    await user.updateProfile({ display_name: name.value.trim() })
    profileStatus.value = "已保存"
  } catch (cause) {
    profileError.value = message(cause)
  } finally {
    saving.value = false
  }
}
async function savePassword() {
  if (changing.value) return
  passwordError.value = ""
  const issues = passwordIssues(next.value, user.currentUser?.email ?? "")
  if (!current.value) passwordError.value = "请输入当前密码"
  else if (issues.length) passwordError.value = issues.join("；")
  else if (next.value !== confirm.value)
    passwordError.value = "两次输入的密码不一致"
  if (passwordError.value) return
  changing.value = true
  try {
    await user.changePassword({
      current_password: current.value,
      new_password: next.value,
    })
    current.value = next.value = confirm.value = ""
    await router.replace({
      name: "login",
      query: { reason: "password_changed" },
    })
  } catch (cause) {
    passwordError.value = message(cause)
  } finally {
    changing.value = false
  }
}
async function logout() {
  if (leaving.value) return
  leaving.value = true
  logoutError.value = ""
  try {
    await user.logout()
    await router.replace({ name: "login", query: { reason: "logged_out" } })
  } catch (cause) {
    logoutError.value = message(cause)
  } finally {
    leaving.value = false
  }
}
</script>

<template>
  <AccountFrame title="账户设置" subtitle="管理你的个人信息和登录方式。">
    <nav
      class="mb-6 flex flex-wrap gap-4 text-sm text-brand-700"
      aria-label="账户导航"
    >
      <RouterLink to="/">← 返回知识书房</RouterLink>
      <RouterLink v-if="user.hasPermission('users:manage')" to="/admin/users"
        >用户管理</RouterLink
      >
    </nav>
    <div class="space-y-6">
      <section class="account-card">
        <h2 class="text-lg font-semibold">你的账户</h2>
        <dl class="mt-4 grid min-w-0 gap-3 text-sm sm:grid-cols-2">
          <div>
            <dt class="text-ink-muted">邮箱</dt>
            <dd class="mt-1 break-all">{{ user.currentUser?.email }}</dd>
          </div>
          <div>
            <dt class="text-ink-muted">角色</dt>
            <dd data-testid="account-role" class="mt-1">{{ roleLabel }}</dd>
          </div>
        </dl>
      </section>
      <form
        data-testid="profile-form"
        class="account-card space-y-4"
        novalidate
        :aria-busy="saving"
        @submit.prevent="saveProfile"
      >
        <h2 class="text-lg font-semibold">个人资料</h2>
        <div>
          <label :for="ids.name" class="account-label">显示名称</label
          ><input
            :id="ids.name"
            v-model="name"
            data-testid="profile-name"
            class="account-input"
            autocomplete="nickname"
            :aria-invalid="!!profileError"
            :aria-describedby="profileError ? ids.profileError : undefined"
          />
        </div>
        <p
          v-if="profileError"
          :id="ids.profileError"
          role="alert"
          class="text-sm text-cite"
        >
          {{ profileError }}
        </p>
        <div class="flex items-center gap-3">
          <button class="account-primary" :disabled="saving">
            {{ saving ? "保存中…" : "保存资料" }}</button
          ><span
            data-testid="profile-status"
            role="status"
            class="text-sm text-brand-700"
            >{{ profileStatus }}</span
          >
        </div>
      </form>
      <form
        data-testid="password-form"
        class="account-card space-y-4"
        novalidate
        :aria-busy="changing"
        @submit.prevent="savePassword"
      >
        <h2 class="text-lg font-semibold">修改密码</h2>
        <p class="text-sm text-ink-muted">
          修改成功后，所有设备都需要使用新密码重新登录。
        </p>
        <div>
          <label :for="ids.current" class="account-label">当前密码</label
          ><input
            :id="ids.current"
            v-model="current"
            data-testid="current-password"
            class="account-input"
            type="password"
            autocomplete="current-password"
            :aria-invalid="!!passwordError"
            :aria-describedby="passwordError ? ids.passwordError : undefined"
          />
        </div>
        <div>
          <label :for="ids.next" class="account-label">新密码</label
          ><input
            :id="ids.next"
            v-model="next"
            data-testid="new-password"
            class="account-input"
            type="password"
            autocomplete="new-password"
            :aria-invalid="!!passwordError"
            :aria-describedby="passwordError ? ids.passwordError : undefined"
          />
          <p class="mt-2 text-xs text-ink-muted">
            10–128 个字符，包含字母和数字，不能与邮箱或邮箱用户名相同。
          </p>
        </div>
        <div>
          <label :for="ids.confirm" class="account-label">确认新密码</label
          ><input
            :id="ids.confirm"
            v-model="confirm"
            data-testid="confirm-password"
            class="account-input"
            type="password"
            autocomplete="new-password"
            :aria-invalid="!!passwordError"
            :aria-describedby="passwordError ? ids.passwordError : undefined"
          />
        </div>
        <p
          v-if="passwordError"
          :id="ids.passwordError"
          role="alert"
          class="text-sm text-cite"
        >
          {{ passwordError }}
        </p>
        <button class="account-primary" :disabled="changing">
          {{ changing ? "更新中…" : "更新密码" }}
        </button>
      </form>
      <section
        class="account-card flex flex-wrap items-center justify-between gap-4"
      >
        <div>
          <h2 class="text-lg font-semibold">退出登录</h2>
          <p class="mt-1 text-sm text-ink-muted">
            你的对话会保留在此浏览器中，供下次登录查看。
          </p>
        </div>
        <button
          data-testid="account-logout"
          class="account-secondary"
          :disabled="leaving"
          @click="logout"
        >
          {{ leaving ? "退出中…" : "退出登录" }}
        </button>
        <p v-if="logoutError" role="alert" class="w-full text-sm text-cite">
          {{ logoutError }}
        </p>
      </section>
    </div>
  </AccountFrame>
</template>
