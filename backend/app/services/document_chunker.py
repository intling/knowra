from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any


class DocumentChunkingError(Exception):
    pass


@dataclass(frozen=True)
class DocumentChunkingConfig:
    tokenizer_model: str = "Qwen/Qwen2-7B"
    max_tokens: int = 512
    merge_peers: bool = True
    repeat_table_header: bool = True
    inline_text_max_bytes: int = 2048
    tokenizer_cache_dir: str | None = None

    def snapshot(self) -> dict[str, Any]:
        return {
            "tokenizer_model": self.tokenizer_model,
            "max_tokens": self.max_tokens,
            "merge_peers": self.merge_peers,
            "repeat_table_header": self.repeat_table_header,
            "inline_text_max_bytes": self.inline_text_max_bytes,
        }


@dataclass(frozen=True)
class NormalizedChunk:
    sequence_index: int
    text: str
    contextualized_text: str
    token_count: int | None = None
    heading_path: list[str] | None = None
    page_numbers: list[int] | None = None
    chunk_type: str = "text"
    source_segment_indices: list[int] | None = None
    metadata_json: dict[str, Any] = field(default_factory=dict)


class DoclingChunkerAdapter:
    def __init__(
        self,
        *,
        config: DocumentChunkingConfig,
        hybrid_chunker_cls: type | None = None,
        tokenizer_factory: Callable[..., Any] | None = None,
    ) -> None:
        self.config = config
        self.hybrid_chunker_cls = hybrid_chunker_cls or load_hybrid_chunker_cls()
        self.tokenizer_factory = tokenizer_factory or make_huggingface_tokenizer

    def chunk(self, document: object) -> list[NormalizedChunk]:
        try:
            tokenizer = self.tokenizer_factory(
                model_name=self.config.tokenizer_model,
                max_tokens=self.config.max_tokens,
                cache_dir=self.config.tokenizer_cache_dir,
            )
            chunker = self.hybrid_chunker_cls(
                tokenizer=tokenizer,
                merge_peers=self.config.merge_peers,
                repeat_table_header=self.config.repeat_table_header,
            )
            return [
                self._normalize_chunk(
                    sequence_index=index,
                    chunker=chunker,
                    tokenizer=tokenizer,
                    chunk=chunk,
                )
                for index, chunk in enumerate(chunker.chunk(document))
            ]
        except DocumentChunkingError:
            raise
        except Exception as exc:
            raise DocumentChunkingError(str(exc)) from exc

    def _normalize_chunk(
        self,
        *,
        sequence_index: int,
        chunker: object,
        tokenizer: object,
        chunk: object,
    ) -> NormalizedChunk:
        text = str(getattr(chunk, "text", "") or "")
        contextualized = str(chunker.contextualize(chunk))
        meta = getattr(chunk, "meta", None)
        return NormalizedChunk(
            sequence_index=sequence_index,
            text=text,
            contextualized_text=contextualized,
            token_count=count_tokens(getattr(chunker, "tokenizer", None) or tokenizer, text, text),
            heading_path=normalize_headings(meta),
            page_numbers=normalize_page_numbers(meta),
            chunk_type=str(getattr(chunk, "chunk_type", None) or "text"),
            source_segment_indices=normalize_source_segment_indices(meta),
            metadata_json=normalize_metadata(meta),
        )


def load_hybrid_chunker_cls():
    try:
        from docling.chunking import HybridChunker
    except ImportError as exc:
        raise DocumentChunkingError("Docling HybridChunker is not available") from exc

    return HybridChunker


def make_huggingface_tokenizer(*, model_name: str, max_tokens: int, cache_dir: str | None = None):
    try:
        from docling_core.transforms.chunker.tokenizer.huggingface import HuggingFaceTokenizer
        from transformers import AutoTokenizer
    except ImportError as exc:
        raise DocumentChunkingError("HuggingFace tokenizer dependencies are not available") from exc

    kwargs: dict[str, Any] = {}
    if cache_dir is not None:
        kwargs["cache_dir"] = cache_dir

    tokenizer = AutoTokenizer.from_pretrained(model_name, **kwargs)
    return HuggingFaceTokenizer(tokenizer=tokenizer, max_tokens=max_tokens)


def count_tokens(tokenizer: object | None, contextualized_text: str, text: str) -> int | None:
    for candidate in (contextualized_text, text):
        if hasattr(tokenizer, "count_tokens"):
            return int(tokenizer.count_tokens(candidate))
        if hasattr(tokenizer, "tokenizer"):
            encoded = tokenizer.tokenizer.encode(candidate)
            if hasattr(encoded, "ids"):
                return len(encoded.ids)
            return len(encoded)
    return None


def normalize_headings(meta: object | None) -> list[str] | None:
    headings = getattr(meta, "headings", None)
    if headings is None:
        headings = get_mapping_value(meta, "headings")
    if not headings:
        return None
    return [str(heading) for heading in headings]


def normalize_page_numbers(meta: object | None) -> list[int] | None:
    page_numbers: set[int] = set()
    for doc_item in getattr(meta, "doc_items", []) or []:
        for prov in getattr(doc_item, "prov", []) or []:
            page_no = getattr(prov, "page_no", None)
            if page_no is not None:
                page_numbers.add(int(page_no))
    mapped_pages = get_mapping_value(meta, "page_numbers")
    if mapped_pages:
        page_numbers.update(int(page) for page in mapped_pages)
    return sorted(page_numbers) or None


def normalize_source_segment_indices(meta: object | None) -> list[int] | None:
    indices = get_mapping_value(meta, "source_segment_indices")
    if not indices:
        return None
    return [int(index) for index in indices]


def normalize_metadata(meta: object | None) -> dict[str, Any]:
    if meta is None:
        return {}
    if isinstance(meta, dict):
        return dict(meta)

    metadata: dict[str, Any] = {}
    origin = getattr(meta, "origin", None)
    if origin is not None:
        metadata["origin"] = origin
    if hasattr(meta, "model_dump"):
        try:
            dumped = meta.model_dump(mode="json")
            if isinstance(dumped, dict):
                metadata.update(dumped)
        except Exception:
            pass
    return metadata


def get_mapping_value(meta: object | None, key: str):
    if isinstance(meta, dict):
        return meta.get(key)
    return None
