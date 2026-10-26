"""Application configuration.

All scraper/pipeline configuration loads from environment variables via this
single `Settings` object (NFR-1) -- nothing is hardcoded, and config is never
scattered across `os.getenv` calls elsewhere.

`Settings` grows per-branch over time (see AD-11); this story only adds the
field the Tier 2 scraper needs.
"""

from urllib.parse import urlparse

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    scraper_proxy_url: str | None = None

    @field_validator("scraper_proxy_url")
    @classmethod
    def _validate_scraper_proxy_url(cls, value: str | None) -> str | None:
        """Fail fast here, at construction time, rather than deep inside
        Playwright's `browser.launch()` in `_render` when the value turns
        out to be malformed (missing scheme, stray whitespace, etc.).

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
            raise ValueError(
                f"SCRAPER_PROXY_URL is not a valid URL (missing scheme or host): {value!r}"
            )
        return value
