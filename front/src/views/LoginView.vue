<script setup lang="ts">
import { computed, ref } from "vue"
import { useRoute, useRouter } from "vue-router"
import AccountFrame from "../components/shared/AccountFrame.vue"
import { uniqueId } from "../shared/a11y/focus"
import { parseDemoFragment } from "../shared/auth/demoLink"
import { isValidEmail } from "../shared/auth/passwordPolicy"
import { sanitizeRedirect } from "../shared/auth/redirect"
import { useUserStore } from "../stores/user"

const user = useUserStore()
const route = useRoute()
const router = useRouter()
const demo = parseDemoFragment(route.hash)
if (route.hash.startsWith("#demo=")) {
  void router.replace({ path: route.path, query: route.query, hash: "" })
}
const emailId = uniqueId("login-email"),
  passwordId = uniqueId("login-password"),
  errorId = uniqueId("login-error")
const email = ref(demo?.email ?? ""),
  password = ref(demo?.password ?? ""),
  error = ref(""),
  busy = ref(false)
// 填表完成后只由密码输入框持有凭据，提示状态不保留密码副本。
if (demo) demo.password = ""
const notice = computed(
  () =>
    ({
      expired: "登录已过期，请重新登录。",
      password_changed: "密码已更新，请使用新密码登录。",
      logged_out: "已安全退出。",
    })[String(route.query.reason)] ?? "",
)
async function submit() {
  if (busy.value) return
  error.value = ""
  if (!isValidEmail(email.value) || !password.value) {
    error.value = "请填写有效邮箱和密码"
    return
  }
  busy.value = true
  try {
    await user.login({ email: email.value.trim(), password: password.value })
    password.value = ""
    await router.replace(sanitizeRedirect(route.query.redirect))
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : "登录失败，请重试"
    password.value = ""
  } finally {
    busy.value = false
  }
}
</script>

<template>
  <AccountFrame
    compact
    title="回到你的知识书房"
    subtitle="登录知寻，继续从自己的资料中寻找答案。"
  >
    <p
      v-if="demo"
      data-testid="demo-notice"
      role="status"
      class="mb-5 rounded-lg border border-line bg-surface p-3 text-sm text-brand-700"
    >
      欢迎体验知寻。演示账号最近 60 分钟最多成功问答 3 次，所有访客共享额度。
    </p>
    <p
      v-if="notice"
      data-testid="login-notice"
      role="status"
      class="mb-5 rounded-lg border border-line bg-surface p-3 text-sm text-brand-700"
    >
      {{ notice }}
    </p>
    <form
      data-testid="login-form"
      class="account-card space-y-5"
      novalidate
      :aria-busy="busy"
      @submit.prevent="submit"
    >
      <div>
        <label :for="emailId" class="account-label">邮箱</label>
        <input
          :id="emailId"
          v-model="email"
          class="account-input"
          type="email"
          autocomplete="email"
          required
          :aria-invalid="!!error"
          :aria-describedby="error ? errorId : undefined"
        />
      </div>
      <div>
        <label :for="passwordId" class="account-label">密码</label>
        <input
          :id="passwordId"
          v-model="password"
          class="account-input"
          type="password"
          autocomplete="current-password"
          required
          :aria-invalid="!!error"
          :aria-describedby="error ? errorId : undefined"
        />
      </div>
      <p v-if="error" :id="errorId" role="alert" class="text-sm text-cite">
        {{ error }}
      </p>
      <button
        data-testid="login-submit"
        class="account-primary w-full"
        :disabled="busy"
      >
        {{ busy ? "登录中…" : "登录" }}
      </button>
    </form>
    <p class="mt-6 text-center text-sm text-ink-muted">
      还没有账号？
      <RouterLink
        data-testid="go-register"
        to="/register"
        class="font-medium text-brand-700 underline underline-offset-4"
        >创建账号</RouterLink
      >
    </p>
    <p class="mt-8 text-center text-xs leading-5 text-ink-faint">
      忘记密码时，请联系管理员重置。
    </p>
  </AccountFrame>
</template>
