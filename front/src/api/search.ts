import { apiFetch } from "./client"
import { createLogger, getRingBuffer } from "../shared/logger"

/** Lazy logger — getRingBuffer() is only available after main.ts initLogger(). */
let _logger: ReturnType<typeof createLogger> | null = null
function log() {
  if (!_logger) _logger = createLogger("api:search", getRingBuffer())
  return _logger
}

// ── TypeScript 类型定义 ──────────────────────────────────────────────

export interface RewrittenQuery {
  query: string
  strategy?: string | null
  duration_ms?: number | null
  tokens?: number | null
}

export interface QualityScores {
  semantic_preservation: number
  clarity_improvement: number
  information_gain: number
  term_accuracy: number
  retrievability: number
  total_score: number
  verdict: "excellent" | "good" | "marginal" | "poor"
  issues: string[]
}

export interface RewriteInfo {
  original_query: string
  rewritten_queries: RewrittenQuery[]
  strategies_used: string[]
  rewrite_time_ms: number
  cache_hit: boolean
  error?: string | null
  rewrite_model?: string | null
  intent?: string | null
  complexity?: number | null
  cache_level?: "L1" | "L2" | null
  quality_scores?: QualityScores | null
  backtrack_triggered?: boolean
  backtrack_strategy?: string | null
}

export interface SearchRequest {
  document_ids?: string[] | null
  query: string
  top_k?: number
  /** Optional conversation history for pronoun resolution during query rewriting. */
  history?: Record<string, unknown>[] | null
  /** Stable session identifier for L1 cache binding (same conversation = same id). */
  session_id?: string | null
}

export interface AnswerTokens {
  prompt_tokens: number
  completion_tokens: number
  total_tokens: number
}

export interface SearchResultItem {
  rank: number
  score: number
  chunk_id: string
  parsed_document_id: string
  document_name: string
  sequence_index: number
  text: string
  contextualized_text: string
  token_count: number | null
  heading_path: string[] | null
  page_numbers: number[] | null
}

export interface SummaryCoverage {
  document_count: number
  included_document_count: number
  total_chunks: number
  included_chunks: number
  truncated: boolean
}

export interface SearchResponse {
  /** 可选，以兼容已保存的旧对话。 */
  answer_mode?: "general" | "rag" | "summary" | "clarification"
  retrieval_status?: "skipped" | "matched" | "no_match" | "empty" | "unavailable"
  summary_coverage?: SummaryCoverage | null
  query: string
  query_embedding_preview: number[]
  embedding_model: string
  embedding_dimensions: number
  top_k: number
  total_searched: number
  searched_document_count: number
  search_time_ms: number
  rewrite_info: RewriteInfo | null
  results: SearchResultItem[]
  answer: string
  /** 已有正文未完整生成；旧记录缺少此字段。 */
  answer_incomplete?: boolean
  answer_tokens: AnswerTokens | null
  chat_model: string | null
  prompt_messages: Record<string, unknown>[]
  chat_config_snapshot: Record<string, unknown> | null
  generation_error: string | null
}

export type SearchStreamEvent =
  | { type: "status"; stage: "searching" | "generating" }
  | { type: "metadata"; response: SearchResponse }
  | { type: "delta"; delta: string }

export interface SearchStreamOptions {
  onEvent: (event: SearchStreamEvent) => void
  signal?: AbortSignal
}

// ── 错误类型 ────────────────────────────────────────────────────────

export class SearchApiError extends Error {
  constructor(
    public status: number,
    public detail: string,
  ) {
    super(detail)
    this.name = "SearchApiError"
  }
}

// ── 错误解析 ────────────────────────────────────────────────────────

async function parseErrorResponse(response: Response): Promise<SearchApiError> {
  try {
    const payload = (await response.json()) as { detail?: unknown }
    if (typeof payload.detail === "string" && payload.detail.length > 0) {
      return new SearchApiError(response.status, payload.detail)
    }
  } catch {
    // Fall through to the status-based message when the server response is not JSON.
  }

  return new SearchApiError(response.status, `请求失败：${response.status}`)
}

async function readSearchStream(
  response: Response,
  onEvent: SearchStreamOptions["onEvent"],
): Promise<SearchResponse> {
  if (!response.body) throw new SearchApiError(0, "无法读取流式回答，请重新发送。")
  const reader = response.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ""
  const invalidFrame = () => new SearchApiError(0, "流式回答格式异常，请重新发送。")
  try {
    while (true) {
      const { value, done } = await reader.read()
      buffer += done ? decoder.decode() : decoder.decode(value, { stream: true })
      const frames = buffer.split(/\r?\n\r?\n/)
      buffer = frames.pop() ?? ""
      for (const frame of frames) {
        const lines = frame.split(/\r?\n/)
        const event = lines.find((line) => line.startsWith("event:"))?.slice(6).trim()
        if (!event || !["status", "metadata", "delta", "done", "error"].includes(event)) continue
        let data: Record<string, unknown>
        try {
          data = JSON.parse(lines.filter((line) => line.startsWith("data:"))
            .map((line) => line.slice(5).trimStart()).join("\n"))
        } catch {
          throw invalidFrame()
        }
        if (!data || typeof data !== "object") throw invalidFrame()
        if (event === "error") {
          if (typeof data.detail !== "string") throw invalidFrame()
          throw new SearchApiError(0, data.detail)
        }
        if (event === "delta") {
          if (typeof data.delta !== "string") throw invalidFrame()
          onEvent({ type: "delta", delta: data.delta })
        } else if (event === "status") {
          if (data.stage !== "searching" && data.stage !== "generating") throw invalidFrame()
          onEvent({ type: "status", stage: data.stage })
        } else {
          if (typeof data.answer !== "string" || !Array.isArray(data.results)) throw invalidFrame()
          const result = data as unknown as SearchResponse
          if (event === "done") return result
          onEvent({ type: "metadata", response: result })
        }
      }
      if (done) throw new SearchApiError(0, "回答连接已中断，已保留生成内容，请重试。")
    }
  } catch (error) {
    if (error instanceof SearchApiError || (error instanceof Error && error.name === "AbortError")) {
      throw error
    }
    throw new SearchApiError(0, "回答连接已中断，已保留生成内容，请重试。")
  } finally {
    await reader.cancel().catch(() => {})
    reader.releaseLock()
  }
}

// ── API 函数 ────────────────────────────────────────────────────────

/** 发送语义搜索 + LLM 生成请求。
 *
 * 向后端 POST /api/search 发送自然语言查询，跨所有已向量化文档进行语义搜索，
 * 并返回检索结果与 AI 生成的 Markdown 回答。
 *
 * @param request.query - 自然语言查询文本（1–2000 字符）
 * @param request.top_k - 返回的最相似分块数量（1–50，默认 5）
 * @param request.history - 可选的多轮对话历史，用于查询重写时的指代词消解
 * @returns 包含检索结果、AI 回答、Token 统计和 prompt messages 的完整响应
 * @throws {SearchApiError} 后端返回错误响应或网络请求失败时抛出
 */
export async function searchChunks(
  request: SearchRequest,
  options?: SearchStreamOptions,
): Promise<SearchResponse> {
  const start = performance.now()
  const body = JSON.stringify({
    ...(request.document_ids != null ? { document_ids: request.document_ids } : {}),
    query: request.query,
    top_k: request.top_k ?? 5,
    ...(request.history != null ? { history: request.history } : {}),
    ...(request.session_id != null ? { session_id: request.session_id } : {}),
  })

  let response: Response
  try {
    response = await apiFetch("/search", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Accept: options ? "text/event-stream" : "application/json",
      },
      body,
      signal: options?.signal,
    })
  } catch (error) {
    if (options?.signal?.aborted) throw error
    const message =
      error instanceof Error ? error.message : "Unknown network error"
    log().error("Search API 网络请求失败", error, { query: request.query })
    throw new SearchApiError(0, message)
  }

  if (!response.ok) {
    log().warn("Search API 返回非 2xx 状态", {
      status: response.status,
      duration: Math.round(performance.now() - start),
    })
    throw await parseErrorResponse(response)
  }

  const result = options && response.headers?.get("Content-Type")?.includes("text/event-stream")
    ? await readSearchStream(response, options.onEvent)
    : await response.json() as SearchResponse
  log().info("Search API 请求完成", {
    status: response.status,
    duration: Math.round(performance.now() - start),
  })
  return result
}
