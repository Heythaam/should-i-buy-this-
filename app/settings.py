"""Application configuration.

All scraper/pipeline configuration loads from environment variables via this
single `Settings` object (NFR-1) -- nothing is hardcoded, and config is never
scattered across `os.getenv` calls elsewhere.

`Settings` grows per-branch over time (see AD-11); this story only adds the
field the Tier 2 scraper needs.
"""

from urllib.parse import urlparse

from pydantic import ValidationInfo, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    scraper_proxy_url: str | None = None
    playwright_executable_path: str | None = None

    # llm-synthesis branch (Story 1.7, NFR-1): the OpenAI API key and both
    # model names load only from here -- never hardcoded, never logged.
    openai_api_key: str | None = None
    llm_cheap_model: str = "gpt-4o-mini"
    llm_strong_model: str = "gpt-4o"

    # Optional override of the OpenAI SDK's default base URL, so an
    # OpenAI-compatible API (Groq, etc.) can be used by setting this in
    # `.env` alone -- wired into `OpenAIClient`'s `AsyncOpenAI(...)`
    # construction in `pipeline/llm_client.py`. `None` keeps the SDK's own
    # default (api.openai.com).
    openai_base_url: str | None = None

    @field_validator("scraper_proxy_url", "openai_base_url")
    @classmethod
    def _validate_optional_url(cls, value: str | None, info: ValidationInfo) -> str | None:
        """Fail fast here, at construction time, rather than deep inside
        Playwright's `browser.launch()` or the OpenAI SDK's HTTP client when
        the value turns out to be malformed (missing scheme, stray
        whitespace, etc.). Shared by every optional-URL setting field.

        Note: `pydantic.AnyUrl` was considered instead of this validator but
        rejected -- it parses a scheme-less value like "proxy.example.com:8080"
        by treating "proxy.example.com" as the scheme, so it would silently
        accept exactly the malformed case this is meant to catch.
        """
        if value is None:
            return None
        value = value.strip()
        if not value:
            return None
        parsed = urlparse(value)
        if not parsed.scheme or not parsed.netloc:
            env_var = info.field_name.upper()
            raise ValueError(f"{env_var} is not a valid URL (missing scheme or host): {value!r}")
        return value

    @field_validator("openai_api_key")
    @classmethod
    def _validate_openai_api_key(cls, value: str | None) -> str | None:
        """Normalize an empty/whitespace-only value to `None`, matching
        `_validate_optional_url`'s normalize-to-`None` pattern -- an env var
        set to "" should behave the same as it being unset, not as a truthy
        empty key."""
        if value is None:
            return None
        value = value.strip()
        return value or None
