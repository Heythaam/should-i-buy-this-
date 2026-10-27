"""The `LLMClient` port (AD-3-style, AD-9) and its OpenAI implementation.

Mirrors `ProductSource`'s mockable-port pattern (AD-3): `synthesis.py` only
ever depends on the `LLMClient` Protocol, never on `openai` directly, so
tests exercise it against a stub implementation with no live network calls
(this story's own "no live OpenAI calls in tests" rule).

`OpenAIClient.complete()` never raises (AD-4, AD-9): any failure -- network
error, timeout, a malformed response -- degrades to `LLMCallFailure`, the
same timeout/retry pattern as `ScraperTier2Source` (one retry after a short
delay, then give up). It is not itself unit-tested against a live API,
mirroring `ScraperTier2Source._render()`'s own untested-via-live-network
status (see this story's Design Notes).
"""

import asyncio
import logging
from typing import Protocol, TypeVar

from openai import AsyncOpenAI
from pydantic import BaseModel

from app.models.llm import LLMCallFailure
from app.settings import Settings

logger = logging.getLogger(__name__)

T = TypeVar("T", bound=BaseModel)

_CALL_TIMEOUT_SECONDS = 30.0
_MAX_ATTEMPTS = 2  # first attempt + one retry (AD-9)
_RETRY_DELAY_SECONDS = 1.0


class LLMClient(Protocol):
    """A source of schema-validated structured completions."""

    async def complete(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        response_model: type[T],
        model: str,
    ) -> T | LLMCallFailure:
        """Complete `user_prompt` under `system_prompt`, parsed into `response_model`.

        Never raises (AD-4, AD-9): any failure -- network error, timeout, a
        malformed response -- degrades to `LLMCallFailure` instead of
        propagating an exception.
        """
        ...


class OpenAIClient:
    """`LLMClient` backed by `openai.AsyncOpenAI().chat.completions.parse()`."""

    def __init__(self, settings: Settings | None = None) -> None:
        self._settings = settings if settings is not None else Settings()
        # Constructed lazily, inside complete()'s own try/except below,
        # rather than here: `AsyncOpenAI(...)` itself raises
        # `openai.OpenAIError` when `openai_api_key` is unset, and
        # `OpenAIClient` must never raise out of either `__init__` or
        # `complete()` (AD-4, AD-9) -- a missing/invalid key degrades to the
        # same `LLMCallFailure` as any other call failure instead of
        # crashing construction.
        self._client: AsyncOpenAI | None = None

    def _get_client(self) -> AsyncOpenAI:
        if self._client is None:
            self._client = AsyncOpenAI(
                api_key=self._settings.openai_api_key,
                base_url=self._settings.openai_base_url,
            )
        return self._client

    async def complete(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        response_model: type[T],
        model: str,
    ) -> T | LLMCallFailure:
        last_error: Exception | None = None
        for attempt in range(1, _MAX_ATTEMPTS + 1):
            try:
                client = self._get_client()
                response = await asyncio.wait_for(
                    client.chat.completions.parse(
                        model=model,
                        messages=[
                            {"role": "system", "content": system_prompt},
                            {"role": "user", "content": user_prompt},
                        ],
                        response_format=response_model,
                    ),
                    timeout=_CALL_TIMEOUT_SECONDS,
                )
                parsed = response.choices[0].message.parsed
                if parsed is None:
                    raise ValueError("OpenAI response had no parsed structured content")
                return parsed
            except Exception as exc:  # noqa: BLE001 -- AD-4: complete() never raises out
                last_error = exc
                logger.warning(
                    "OpenAIClient.complete attempt %s/%s failed for model %s: %s",
                    attempt,
                    _MAX_ATTEMPTS,
                    model,
                    exc,
                )
                if attempt < _MAX_ATTEMPTS:
                    await asyncio.sleep(_RETRY_DELAY_SECONDS)

        logger.error(
            "OpenAIClient.complete giving up after %s attempts for model %s: %s",
            _MAX_ATTEMPTS,
            model,
            last_error,
        )
        return LLMCallFailure(
            reason="llm_call_failed",
            detail=str(last_error) if last_error else "unknown error",
        )
