import { buildApiUrl } from "./client"
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
}

export interface RewriteInfo {
  original_query: string
  rewritten_queries: RewrittenQuery[]
  strategies_used: string[]
  rewrite_time_ms: number
  cache_hit: boolean
  error?: string | null
  rewrite_model?: string | null
}

export interface SearchRequest {
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

export interface SearchResponse {
  query: string
  query_embedding_preview: number[]
  embedding_model: string
  embedding_dimensions: number
  top_k: number
  total_searched: number
  searched_document_count: number
  search_time_ms: number
  rewrite_info: RewriteInfo
  results: SearchResultItem[]
  answer: string
  answer_tokens: AnswerTokens | null
  chat_model: string | null
  prompt_messages: Record<string, unknown>[]
  chat_config_snapshot: Record<string, unknown> | null
  generation_error: string | null
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
): Promise<SearchResponse> {
  const start = performance.now()
  const body = JSON.stringify({
    query: request.query,
    top_k: request.top_k ?? 5,
    ...(request.history != null ? { history: request.history } : {}),
    ...(request.session_id != null ? { session_id: request.session_id } : {}),
  })

  let response: Response
  try {
    response = await fetch(buildApiUrl("/search"), {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Accept: "application/json",
      },
      body,
    })
  } catch (error) {
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

  log().info("Search API 请求完成", {
    status: response.status,
    duration: Math.round(performance.now() - start),
  })
  return response.json() as Promise<SearchResponse>
}
