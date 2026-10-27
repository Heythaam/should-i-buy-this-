"""Tests for `OpenAIClient`'s `base_url` wiring (llm-synthesis branch, NFR-1).

Only `_get_client()`'s resulting `AsyncOpenAI` object construction is
covered here -- no live call to `.chat.completions.parse()` is made, so this
needs no network access (`AsyncOpenAI(...)` itself never makes a request).
`OpenAIClient.complete()`'s retry/timeout/failure behavior is covered
elsewhere via a stub `LLMClient` (see `tests/pipeline/test_synthesis.py`),
mirroring `ScraperTier2Source._render()`'s own untested-via-live-network
status.
"""

from app.pipeline.llm_client import OpenAIClient
from app.settings import Settings


def test_get_client_uses_the_openai_sdk_default_base_url_when_unset():
    client = OpenAIClient(Settings(openai_api_key="sk-test", openai_base_url=None))

    sdk_client = client._get_client()

    assert str(sdk_client.base_url) == "https://api.openai.com/v1/"


def test_get_client_uses_the_configured_base_url_when_set():
    client = OpenAIClient(
        Settings(openai_api_key="sk-test", openai_base_url="https://api.groq.com/openai/v1")
    )

    sdk_client = client._get_client()

    assert str(sdk_client.base_url) == "https://api.groq.com/openai/v1/"


def test_get_client_caches_the_constructed_client_across_calls():
    client = OpenAIClient(Settings(openai_api_key="sk-test"))

    first = client._get_client()
    second = client._get_client()

    assert first is second
