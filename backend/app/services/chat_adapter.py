"""封装 OpenAI 兼容的对话补全端点。

提供 ``POST /v1/chat/completions`` 的薄适配层，包含重试、错误处理和
结构化返回类型 —— 遵循与 ``EmbeddingAdapter`` 相同的模式，但用于对话领域。

支持两种调用模式：
- ``generate()``：同步调用，用于向后兼容和简单场景。
- ``generate_async()``：异步流式调用，支持首 token 超时检测，
  避免因服务不可用导致长时间阻塞。推荐 RAG 答案生成场景使用。
"""

import asyncio
import random
import time
from dataclasses import dataclass

from openai import APIConnectionError, APIStatusError, APITimeoutError, AsyncOpenAI, OpenAI

from app.core.logging import get_logger
from app.services.chat_config import ChatConfig
from app.services.query_rewrite_config import QueryRewriteConfig  # noqa: F401


class ChatError(Exception):
    """所有对话操作的基础异常。"""

    pass


class ChatAPIError(ChatError):
    """对话 API 调用在重试耗尽后抛出此异常。"""

    def __init__(
        self,
        message: str,
        status_code: int | None = None,
        response_body: str | None = None,
        request_id: str | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.response_body = response_body
        self.request_id = request_id

    def __str__(self) -> str:
        parts = []
        if self.status_code is not None:
            parts.append(f"[HTTP {self.status_code}]")
        parts.append(super().__str__())
        return " ".join(parts)


@dataclass(frozen=True)
class ChatResult:
    """API 返回的单次对话补全结果。

    Attributes:
        content: 模型生成的文本回复。
        model: 生成此补全所使用的模型。
        prompt_tokens: 提示词的 token 数。
        completion_tokens: 生成回复的 token 数。
        total_tokens: 总 token 消耗（prompt + completion）。
    """

    content: str
    model: str
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int


class ChatAdapter:
    """封装 OpenAI 兼容的 ``POST /v1/chat/completions`` 端点。

    适配器处理指数退避重试与错误包装。不向调用方暴露任何第三方 SDK 类型 ——
    所有返回值均为项目内部 dataclass。
    """

    def __init__(
        self,
        *,
        config: ChatConfig | QueryRewriteConfig,
        client: object | None = None,
    ) -> None:
        self.config = config
        if client is not None:
            self._client = client
        else:
            if not config.api_key:
                raise ChatAPIError(
                    "Chat API key is not configured. Set CHAT_API_KEY in your .env file."
                )
            self._client = OpenAI(
                base_url=config.api_base_url,
                api_key=config.api_key,
                timeout=config.request_timeout,
                max_retries=0,  # 关闭 SDK 内部重试，由 ChatAdapter 层统一管理
            )
        self._logger = get_logger(__name__)

    # ── 公共 API ──────────────────────────────────────────────────────────

    def generate(
        self,
        messages: list[dict],
        *,
        stream: bool = False,
        model: str | None = None,
        request_timeout: float | None = None,
        max_retries: int | None = None,
    ) -> ChatResult:
        """为 *messages* 生成对话补全。

        Args:
            messages: 消息字典列表，每项含 ``role`` 与 ``content``。
            stream: 为 Phase 2 预留。设为 ``True`` 时抛出 ``NotImplementedError``。
            model: 可选的模型覆盖。为 ``None`` 时使用 ``config.model``。
            request_timeout: 可选的调用级 HTTP 超时（秒）。为 ``None`` 时使用
                             ``config.request_timeout``。允许调用方（如
                             StrategyRouter）设置比全局配置更短的超时。
            max_retries: 可选的重试次数覆盖。为 ``None`` 时使用
                         ``config.max_retries``。设为 0 可完全禁用重试。

        Returns:
            包含生成内容与 token 用量统计的 ChatResult。

        Raises:
            NotImplementedError: ``stream=True`` 时（为 Phase 2 预留）。
            ChatAPIError: API 调用在重试耗尽后失败。
        """
        if stream:
            raise NotImplementedError("Streaming will be implemented in Phase 2")

        effective_model = model or self.config.model
        effective_timeout = request_timeout if request_timeout is not None else self.config.request_timeout
        effective_max_retries = max_retries if max_retries is not None else self.config.max_retries

        self._logger.info(
            "chat_generate_request",
            model=effective_model,
            message_count=len(messages),
            max_tokens=self.config.max_tokens,
            request_timeout=effective_timeout,
            max_retries=effective_max_retries,
        )

        # 当调用级超时与配置不同时，创建临时客户端（OpenAI 客户端超时在构造时设定）
        if request_timeout is not None and request_timeout != self.config.request_timeout:
            client = OpenAI(
                base_url=self.config.api_base_url,
                api_key=self.config.api_key,
                timeout=effective_timeout,
                max_retries=0,  # 由 ChatAdapter 层管理重试，避免双重重试放大延迟
            )
        else:
            client = self._client

        last_exception: Exception | None = None

        for attempt in range(effective_max_retries + 1):
            try:
                response = client.chat.completions.create(
                    model=effective_model,
                    messages=messages,
                    temperature=self.config.temperature,
                    max_tokens=self.config.max_tokens,
                )
                return self._parse_response(response)
            except Exception as exc:
                last_exception = exc
                if not self._should_retry(exc, attempt, effective_max_retries):
                    break
                if attempt < effective_max_retries:
                    delay = self._compute_delay(exc, attempt)
                    self._logger.warning(
                        "chat_retry",
                        attempt=attempt + 1,
                        max_retries=effective_max_retries,
                        delay=round(delay, 2),
                        error=str(exc),
                    )
                    time.sleep(delay)

        raise self._wrap_error(last_exception)

    # ── 异步流式 API（RAG 答案生成推荐） ──────────────────────────────────

    @property
    def _async_client(self) -> AsyncOpenAI:
        """懒初始化异步 OpenAI 客户端，与同步客户端共享配置。"""
        if not hasattr(self, "_async_client_cache"):
            self._async_client_cache = AsyncOpenAI(
                base_url=self.config.api_base_url,
                api_key=self.config.api_key,
                timeout=self.config.request_timeout,
                max_retries=0,  # 关闭 SDK 内部重试，由本层统一管理
            )
        return self._async_client_cache

    async def generate_async(
        self,
        messages: list[dict],
        *,
        model: str | None = None,
        request_timeout: float | None = None,
        max_retries: int | None = None,
        first_token_timeout: float | None = None,
    ) -> ChatResult:
        """异步流式生成对话补全，支持首 token 超时检测。

        与 ``generate()`` 的关键区别：
        1. **首 token 超时**：首个 token 在 ``first_token_timeout`` 秒内
           未到达则判定服务不可用，快速抛出 ``asyncio.TimeoutError``。
           一旦首 token 到达即表明模型在工作，后续收集不受此限制。
        2. **流式收集**：使用 SSE 流式接收，避免因生成慢而被误杀。
           调用方可用 ``asyncio.wait_for`` 设置整体超时兜底。
        3. **异步非阻塞**：不阻塞事件循环，适合 FastAPI 异步路由。

        Args:
            messages: 消息字典列表，每项含 ``role`` 与 ``content``。
            model: 可选的模型覆盖。为 ``None`` 时使用 ``config.model``。
            request_timeout: 可选的 HTTP 超时（秒）。为 ``None`` 时使用
                             ``config.request_timeout``。
            max_retries: 可选的重试次数覆盖。为 ``None`` 时使用
                         ``config.max_retries``。
            first_token_timeout: 首 token 超时（秒）。为 ``None`` 时使用
                                 ``config.first_token_timeout``。

        Returns:
            包含生成内容与 token 用量统计的 ChatResult。

        Raises:
            asyncio.TimeoutError: 首 token 未在超时内到达。
            ChatAPIError: API 调用在重试耗尽后失败。
        """
        effective_model = model or self.config.model
        effective_timeout = request_timeout if request_timeout is not None else self.config.request_timeout
        effective_max_retries = max_retries if max_retries is not None else self.config.max_retries
        effective_first_token_timeout = (
            first_token_timeout if first_token_timeout is not None else self.config.first_token_timeout
        )

        self._logger.info(
            "chat_generate_async_request",
            model=effective_model,
            message_count=len(messages),
            max_tokens=self.config.max_tokens,
            request_timeout=effective_timeout,
            max_retries=effective_max_retries,
            first_token_timeout=effective_first_token_timeout,
        )

        # 当调用级超时与配置不同时，创建临时异步客户端
        if request_timeout is not None and request_timeout != self.config.request_timeout:
            client = AsyncOpenAI(
                base_url=self.config.api_base_url,
                api_key=self.config.api_key,
                timeout=effective_timeout,
                max_retries=0,
            )
        else:
            client = self._async_client

        last_exception: Exception | None = None

        for attempt in range(effective_max_retries + 1):
            try:
                stream = await client.chat.completions.create(
                    model=effective_model,
                    messages=messages,
                    temperature=self.config.temperature,
                    max_tokens=self.config.max_tokens,
                    stream=True,
                    stream_options={"include_usage": True},
                )
                return await self._collect_stream(
                    stream,
                    effective_model,
                    first_token_timeout=effective_first_token_timeout,
                )
            except asyncio.TimeoutError:
                last_exception = asyncio.TimeoutError(
                    f"First token not received within {effective_first_token_timeout}s"
                )
                if not self._should_retry(last_exception, attempt, effective_max_retries):
                    break
                if attempt < effective_max_retries:
                    delay = self._compute_delay(last_exception, attempt)
                    self._logger.warning(
                        "chat_first_token_timeout_retry",
                        attempt=attempt + 1,
                        max_retries=effective_max_retries,
                        delay=round(delay, 2),
                        first_token_timeout=effective_first_token_timeout,
                    )
                    await asyncio.sleep(delay)
            except Exception as exc:
                last_exception = exc
                if not self._should_retry(exc, attempt, effective_max_retries):
                    break
                if attempt < effective_max_retries:
                    delay = self._compute_delay(exc, attempt)
                    self._logger.warning(
                        "chat_async_retry",
                        attempt=attempt + 1,
                        max_retries=effective_max_retries,
                        delay=round(delay, 2),
                        error=str(exc),
                    )
                    await asyncio.sleep(delay)

        raise self._wrap_error(last_exception)

    async def _collect_stream(
        self,
        stream,
        model: str,
        *,
        first_token_timeout: float,
    ) -> ChatResult:
        """从异步流中收集全部 token，首 token 含超时检测。

        流式收集策略：
        1. 首个 chunk：使用 ``asyncio.wait_for`` 硬限时，
           超时则服务不可用 → 快速失败。
        2. 后续 chunks：无单独时限（由调用方的 ``asyncio.wait_for`` 总超时兜底），
           一旦模型在工作就不再因"慢"而误杀。
        3. Usage 信息从流末 chunk 提取（需要 ``stream_options={"include_usage": True}``）。
        """
        content_parts: list[str] = []
        prompt_tokens = 0
        completion_tokens = 0
        total_tokens = 0
        first_chunk_received = False

        async for chunk in self._iter_stream_with_first_timeout(
            stream, first_token_timeout
        ):
            if not first_chunk_received:
                first_chunk_received = True
                self._logger.debug("chat_first_token_received", model=model)

            try:
                choices = chunk.choices
                if choices and len(choices) > 0:
                    delta = choices[0].delta
                    if delta and delta.content:
                        content_parts.append(delta.content)
            except (AttributeError, IndexError):
                pass

            # Usage 信息通常包含在流的最后一个 chunk 中
            try:
                usage = getattr(chunk, "usage", None)
                if usage is not None:
                    prompt_tokens = getattr(usage, "prompt_tokens", 0) or 0
                    completion_tokens = getattr(usage, "completion_tokens", 0) or 0
                    total_tokens = getattr(usage, "total_tokens", 0) or 0
            except Exception:
                pass

        content = "".join(content_parts)

        if not first_chunk_received:
            raise ChatAPIError("Stream completed without any content chunks")

        return ChatResult(
            content=content,
            model=model,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=total_tokens,
        )

    async def _iter_stream_with_first_timeout(self, stream, first_token_timeout: float):
        """包装异步流迭代器，对首个元素施加超时检测。

        首个元素使用 ``asyncio.wait_for`` 硬限时 —— 超时则服务不可用。
        后续元素不做单独限时，由调用方整体超时兜底。
        """
        aiter = stream.__aiter__()

        # 首个 chunk：硬超时检测
        try:
            first = await asyncio.wait_for(aiter.__anext__(), timeout=first_token_timeout)
        except asyncio.TimeoutError:
            self._logger.warning(
                "chat_first_token_timeout",
                timeout=first_token_timeout,
            )
            raise

        yield first

        # 后续 chunks：无单独时限
        async for chunk in aiter:
            yield chunk

    # ── 内部实现 ──────────────────────────────────────────────────────────

    def _should_retry(self, exception: Exception, attempt: int, max_retries: int | None = None) -> bool:
        """判断 *exception* 是否值得再试一次。"""
        effective_max_retries = max_retries if max_retries is not None else self.config.max_retries
        if attempt >= effective_max_retries:
            return False

        # 超时 —— 总是重试。
        if isinstance(exception, APITimeoutError):
            return True

        # 连接错误（DNS、TCP、TLS）—— 重试。
        if isinstance(exception, APIConnectionError):
            return True

        if isinstance(exception, APIStatusError):
            # 429 限流与 5xx —— 临时性错误，重试。
            # 其他 4xx —— 永久性错误，快速失败。
            return exception.status_code == 429 or 500 <= exception.status_code < 600

        # 未知错误 —— 快速失败（不理解的不重试）。
        return False

    def _compute_delay(self, exception: Exception, attempt: int) -> float:
        """为第 *attempt* 次重试计算退避延迟（含抖动与上限）。

        对于包含 ``Retry-After`` 头的 429 响应，使用服务端建议的等待时间
        （限制在 [0.5, 60] 秒范围内）。否则应用完全抖动的指数退避::

            delay = random.uniform(0, min(2 ** attempt, 60))

        60 秒上限防止 ``max_retries`` 配置较大时出现病态等待时间。
        """
        if isinstance(exception, APIStatusError) and exception.status_code == 429:
            retry_after = self._parse_retry_after(exception)
            if retry_after is not None:
                return max(0.5, min(retry_after, 60.0))

        # 完全抖动 —— 避免多客户端同时重试造成的惊群效应
        # （参考：AWS Architecture Blog — "Exponential Backoff and Jitter"）。
        return random.uniform(0, min(2**attempt, 60.0))

    @staticmethod
    def _parse_retry_after(exception: APIStatusError, /) -> float | None:
        """从响应头中提取 ``Retry-After`` 秒数。

        头缺失或不可解析时返回 ``None``。
        """
        headers: dict = getattr(exception.response, "headers", {}) or {}
        value = headers.get("Retry-After") or headers.get("retry-after")
        if value is None:
            return None
        # 优先按整数秒解析（RFC 7231 §7.1.3）。
        try:
            return float(value)
        except ValueError, TypeError:
            return None

    @staticmethod
    def _parse_response(response: object) -> ChatResult:
        """解析 API 响应并提取 ``ChatResult``。"""
        if isinstance(response, str):
            # API 返回了非 JSON 正文（HTML、纯文本等）——
            # 通常由于 api_base_url 配置错误缺少 /v1 路径前缀所致。
            raise ChatAPIError(
                f"Chat API returned unexpected text instead of JSON: {response[:200]}"
            )

        try:
            choice = response.choices[0]
        except (AttributeError, IndexError, TypeError) as exc:
            raise ChatAPIError(
                f"Chat API response missing expected 'choices' field: {exc}"
            ) from exc

        content = choice.message.content or ""

        usage = getattr(response, "usage", None)
        if usage is not None:
            prompt_tokens = getattr(usage, "prompt_tokens", 0) or 0
            completion_tokens = getattr(usage, "completion_tokens", 0) or 0
            total_tokens = getattr(usage, "total_tokens", 0) or 0
        else:
            prompt_tokens = 0
            completion_tokens = 0
            total_tokens = 0

        model = getattr(response, "model", "") or ""

        return ChatResult(
            content=content,
            model=model,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=total_tokens,
        )

    @staticmethod
    def _wrap_error(exception: Exception | None) -> ChatAPIError:
        """将第三方异常转换为项目异常，提取响应体中可用于诊断的信息。"""
        if exception is None:
            return ChatAPIError("Unknown chat API error")

        if isinstance(exception, APIStatusError):
            # 提取 API 响应中的错误详情，便于排查内容审查等问题
            response_body: str | None = None
            request_id: str | None = None
            try:
                response = getattr(exception, "response", None)
                if response is not None:
                    response_body = getattr(response, "text", None)
                    if response_body is not None and len(response_body) > 2000:
                        response_body = response_body[:2000]
                    headers = getattr(response, "headers", {}) or {}
                    request_id = (
                        headers.get("x-request-id")
                        or headers.get("X-Request-Id")
                        or headers.get("cf-ray")
                    )
            except Exception:
                pass

            return ChatAPIError(
                str(exception),
                status_code=exception.status_code,
                response_body=response_body,
                request_id=request_id,
            )
        return ChatAPIError(str(exception))
