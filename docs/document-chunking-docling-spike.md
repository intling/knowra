# Document Chunking Docling Spike

Date: 2026-06-12

Change: `add-document-chunking-docling`

## Findings

- `HybridChunker` is available from `docling.chunking`.
- The exported class is `docling_core.transforms.chunker.hybrid_chunker.HybridChunker`.
- The compatibility import `docling_core.transforms.chunker.hybrid_chunker.HybridChunker` is also available.
- `HybridChunker.chunk(dl_doc)` returns an iterator of Docling chunk objects.
- `HybridChunker.contextualize(chunk)` accepts one Docling chunk and returns contextualized text.
- `transformers`, `tokenizers`, and `huggingface_hub` are already installed in the backend environment.
- `docling_core.transforms.chunker.tokenizer.huggingface.HuggingFaceTokenizer` is available and accepts a preloaded `transformers` tokenizer plus `max_tokens`.
- `Qwen/Qwen2-7B` is not present in an empty local cache. `AutoTokenizer.from_pretrained(..., local_files_only=True)` fails with `LocalEntryNotFoundError`, so first use requires a populated Hugging Face cache or network access.
- Constructing `HybridChunker()` without an explicit tokenizer attempts to load the Docling default tokenizer (`sentence-transformers/all-MiniLM-L6-v2`) and may try to reach Hugging Face. Default unit tests should inject a fake chunker/tokenizer instead of downloading models.

## Dependency Decision

No new Python package dependency appears required for the first implementation because Docling, transformers, tokenizers, and huggingface_hub are already present.

Implementation still needs configuration and documentation for tokenizer cache preparation. The chunker adapter should pass an explicit `HuggingFaceTokenizer` built from `AutoTokenizer.from_pretrained(settings.document_chunk_tokenizer_model, cache_dir=...)` instead of relying on `HybridChunker()` defaults.

## Test Fixture Decision

Default tests should use:

- Markdown and TXT string fixtures for fallback and UI/API payload checks.
- A small in-memory `DoclingDocument` built with `DoclingDocument(name=...)`, `add_title(...)`, `add_heading(...)`, and `add_text(...)`.
- Fake tokenizer/chunker objects for adapter/service tests so RED/GREEN does not depend on OCR, PDFs, large files, or network downloads.
