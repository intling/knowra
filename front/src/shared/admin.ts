import { ApiError } from "../api/client"
export const modelKinds = {
  chat: "聊天与回答",
  embedding: "Embedding 向量化",
  rerank: "检索重排",
  query_rewrite: "查询改写",
} as const
export const jobKinds = {
  parse: "解析",
  chunk: "分块",
  embedding: "向量化",
} as const
export const statusLabels: Record<string, string> = {
  ok: "正常",
  degraded: "需要关注",
  unavailable: "无法使用",
  unknown: "无法确认",
  disabled: "未启用",
  queued: "排队中",
  running: "处理中",
  succeeded: "已成功",
  failed: "已失败",
  superseded: "已被替代",
  passed: "测试通过",
  interrupted: "已中断",
  success: "成功",
  denied: "已拒绝",
}
export const actionLabels: Record<string, string> = {
  "user.create": "创建账号",
  "user.update": "更新账号",
  "user.delete": "删除账号",
  "user.reset_password": "重置密码",
  "user.chat_limit.update": "调整问答额度",
  "user.sessions.revoke": "撤销设备会话",
  "model.create": "创建模型配置",
  "model.update": "编辑模型配置",
  "model.delete": "删除模型配置",
  "model.activate": "切换默认模型",
  "model.deactivate": "恢复环境模型",
  "model.test": "测试模型连接",
}
export function formatTime(value: string | null | undefined) {
  if (!value) return "—"
  const date = new Date(value)
  return Number.isNaN(date.valueOf())
    ? "无法获取"
    : date.toLocaleString("zh-CN", { hour12: false })
}
export function formatBytes(value: number | null | undefined) {
  if (value == null) return "无法获取"
  if (value < 1024) return `${value} B`
  const unit = value < 1024 ** 2 ? 1 : value < 1024 ** 3 ? 2 : 3
  return `${(value / 1024 ** unit).toFixed(1)} ${["B", "KB", "MB", "GB"][unit]}`
}
export function errorMessage(cause: unknown, fallback = "读取失败，请重试") {
  return cause instanceof Error ? cause.message : fallback
}
export function errorTrace(cause: unknown) {
  return cause instanceof ApiError ? cause.traceId : null
}
export function isCurrentProbe(
  probe: { is_current: boolean; checked_at: string },
  revision?: number,
  configRevision?: number,
  now = Date.now(),
) {
  return (
    probe.is_current &&
    (revision === undefined || revision === configRevision) &&
    now - new Date(probe.checked_at).getTime() <= 15 * 60 * 1000
  )
}
