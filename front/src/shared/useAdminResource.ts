import { computed, onMounted, onUnmounted, ref, shallowRef, watch } from "vue"
import { useUserStore } from "../stores/user"
import { errorMessage, errorTrace } from "./admin"
/** 请求代次保证筛选竞态、卸载及权限变更时不会回填旧数据。 */
export function useAdminResource<T>(
  permission: string,
  loader: () => Promise<T>,
  enabled: () => boolean = () => true,
) {
  const user = useUserStore(),
    allowed = computed(() => user.hasPermission(permission) && enabled())
  const data = shallowRef<T | null>(null),
    loading = ref(false),
    error = ref(""),
    traceId = ref<string | null>(null),
    loadedAt = ref("")
  let request = 0
  async function refresh() {
    if (!allowed.value) return
    const current = ++request
    loading.value = true
    error.value = ""
    traceId.value = null
    try {
      const value = await loader()
      if (current === request && allowed.value) {
        data.value = value
        loadedAt.value = new Date().toISOString()
      }
      return current === request ? value : undefined
    } catch (cause) {
      if (current === request) {
        error.value = errorMessage(cause)
        traceId.value = errorTrace(cause)
      }
    } finally {
      if (current === request) loading.value = false
    }
  }
  watch(allowed, (value) => {
    if (!value) {
      request++
      data.value = null
      error.value = ""
      loading.value = false
    } else refresh()
  })
  onMounted(refresh)
  onUnmounted(() => {
    request++
    data.value = null
  })
  return { allowed, data, loading, error, traceId, loadedAt, refresh }
}
