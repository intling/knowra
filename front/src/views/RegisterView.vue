<script setup lang="ts">
import { ref } from "vue"
import { useRouter } from "vue-router"
import AccountFrame from "../components/shared/AccountFrame.vue"
import { uniqueId } from "../shared/a11y/focus"
import { isValidEmail, passwordIssues } from "../shared/auth/passwordPolicy"
import { useUserStore } from "../stores/user"

const user = useUserStore(),
  router = useRouter()
const name = ref(""),
  email = ref(""),
  password = ref(""),
  confirm = ref("")
const error = ref(""),
  busy = ref(false)
const ids = {
  name: uniqueId("register-name"),
  email: uniqueId("register-email"),
  password: uniqueId("register-password"),
  confirm: uniqueId("register-confirm"),
  error: uniqueId("register-error"),
}
async function submit() {
  if (busy.value) return
  error.value = ""
  if (!name.value.trim() || Array.from(name.value.trim()).length > 100)
    error.value = "显示名称须为 1–100 个字符"
  else if (!isValidEmail(email.value)) error.value = "请输入有效邮箱"
  else if (passwordIssues(password.value, email.value).length)
    error.value = passwordIssues(password.value, email.value).join("；")
  else if (password.value !== confirm.value)
    error.value = "两次输入的密码不一致"
  if (error.value) return
  busy.value = true
  try {
    await user.register({
      display_name: name.value.trim(),
      email: email.value.trim(),
      password: password.value,
    })
    password.value = confirm.value = ""
    await router.replace("/")
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : "注册失败，请重试"
    password.value = confirm.value = ""
  } finally {
    busy.value = false
  }
}
</script>

<template>
  <AccountFrame
    compact
    title="开始积累你的知识"
    subtitle="让讲义、论文和笔记，成为随时可以提问的资料库。"
  >
    <form
      data-testid="register-form"
      class="account-card space-y-5"
      novalidate
      :aria-busy="busy"
      @submit.prevent="submit"
    >
      <div>
        <label :for="ids.name" class="account-label">显示名称</label>
        <input
          :id="ids.name"
          v-model="name"
          data-testid="register-name"
          class="account-input"
          autocomplete="nickname"
          required
          :aria-invalid="!!error"
          :aria-describedby="error ? ids.error : undefined"
        />
      </div>
      <div>
        <label :for="ids.email" class="account-label">邮箱</label>
        <input
          :id="ids.email"
          v-model="email"
          data-testid="register-email"
          type="email"
          class="account-input"
          autocomplete="email"
          required
          :aria-invalid="!!error"
          :aria-describedby="error ? ids.error : undefined"
        />
      </div>
      <div>
        <label :for="ids.password" class="account-label">密码</label>
        <input
          :id="ids.password"
          v-model="password"
          data-testid="register-password"
          type="password"
          class="account-input"
          autocomplete="new-password"
          required
          :aria-invalid="!!error"
          :aria-describedby="ids.error"
        />
        <p class="mt-2 text-xs text-ink-muted">
          10–128 个字符，包含字母和数字，不能与邮箱或邮箱用户名相同。
        </p>
      </div>
      <div>
        <label :for="ids.confirm" class="account-label">确认密码</label>
        <input
          :id="ids.confirm"
          v-model="confirm"
          data-testid="register-confirm"
          type="password"
          class="account-input"
          autocomplete="new-password"
          required
          :aria-invalid="!!error"
          :aria-describedby="error ? ids.error : undefined"
        />
      </div>
      <p v-if="error" :id="ids.error" role="alert" class="text-sm text-cite">
        {{ error }}
      </p>
      <button class="account-primary w-full" :disabled="busy">
        {{ busy ? "创建中…" : "创建账号" }}
      </button>
    </form>
    <p class="mt-6 text-center text-sm text-ink-muted">
      已有账号？
      <RouterLink
        data-testid="go-login"
        to="/login"
        class="font-medium text-brand-700 underline underline-offset-4"
        >前往登录</RouterLink
      >
    </p>
  </AccountFrame>
</template>
