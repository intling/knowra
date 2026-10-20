/**
 * 测试夹具：完整镜像后端 `SearchResponse` / `SearchResultItem` / `ParsedDocument` 结构。
 *
 * 只被测试文件引用；字段保持与 `src/api/*.ts` 中的类型完全一致，
 * 避免部分 mock 导致下游读取缺失字段时静默通过。
 */
import type { SearchResponse, SearchResultItem } from "../../api/search"
import type { ParsedDocument } from "../../api/documentParsing"

export function makeResult(overrides: Partial<SearchResultItem> = {}): SearchResultItem {
  return {
    rank: 1,
    score: 0.2,
    chunk_id: "chunk-1",
    parsed_document_id: "doc-a",
    document_name: "线性代数讲义.pdf",
    sequence_index: 12,
    text: "特征值是满足 Av = λv 的标量 λ。",
    contextualized_text: "第三章 特征值\n特征值是满足 Av = λv 的标量 λ。",
    token_count: 24,
    heading_path: ["第三章", "特征值"],
    page_numbers: [3],
    ...overrides,
  }
}

export function makeResponse(overrides: Partial<SearchResponse> = {}): SearchResponse {
  return {
    query: "什么是特征值",
    query_embedding_preview: [0.1, 0.2, 0.3],
    embedding_model: "text-embedding-3-small",
    embedding_dimensions: 1536,
    top_k: 5,
    total_searched: 240,
    searched_document_count: 3,
    search_time_ms: 120,
    rewrite_info: null,
    results: [makeResult()],
    answer: "特征值是满足 **Av = λv** 的标量。",
    answer_tokens: { prompt_tokens: 500, completion_tokens: 200, total_tokens: 700 },
    chat_model: "deepseek-chat",
    prompt_messages: [
      { role: "system", content: "你是一个基于知识库文档的 AI 助手。" },
      { role: "user", content: "什么是特征值" },
    ],
    chat_config_snapshot: null,
    generation_error: null,
    ...overrides,
  }
}

export function makeParsedDocument(overrides: Partial<ParsedDocument> = {}): ParsedDocument {
  return {
    id: "pd-001",
    uploaded_file_id: "up-001",
    parse_job_id: "job-001",
    owner_user_id: "user-001",
    source_checksum_sha256: null,
    markdown_storage_key: "parsed/pd-001.md",
    text_storage_key: "parsed/pd-001.txt",
    docling_json_storage_key: "parsed/pd-001.json",
    title: "线性代数讲义",
    page_count: 42,
    metadata: null,
    segment_count: 120,
    created_at: "2026-10-01T00:00:00Z",
    ...overrides,
  }
}
