import { onMounted, onUnmounted, ref } from "vue"

// 只更新展示时间，不轮询后台或触发模型调用。
export function useAdminClock() {
  const now = ref(Date.now())
  let timer: ReturnType<typeof setInterval> | undefined
  onMounted(() => {
    timer = setInterval(() => {
      now.value = Date.now()
    }, 1000)
  })
  onUnmounted(() => clearInterval(timer))
  return now
}
