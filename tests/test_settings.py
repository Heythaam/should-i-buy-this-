"""Tests for `Settings.openai_base_url` (llm-synthesis branch, NFR-1).

`scraper_proxy_url`'s own malformed-URL test lives in
`tests/pipeline/sources/test_scraper_tier2.py` (Story 1.1); this file covers
only the new field, which shares the same validator (`_validate_optional_url`).
"""

import pydantic
import pytest

from app.settings import Settings


def test_openai_base_url_defaults_to_none():
    assert Settings(openai_base_url=None).openai_base_url is None


def test_openai_base_url_empty_string_normalizes_to_none():
    assert Settings(openai_base_url="").openai_base_url is None
    assert Settings(openai_base_url="   ").openai_base_url is None


def test_openai_base_url_accepts_a_well_formed_url():
    settings = Settings(openai_base_url="https://api.groq.com/openai/v1")
    assert settings.openai_base_url == "https://api.groq.com/openai/v1"


def test_openai_base_url_strips_surrounding_whitespace():
    settings = Settings(openai_base_url="  https://api.groq.com/openai/v1  ")
    assert settings.openai_base_url == "https://api.groq.com/openai/v1"


def test_settings_rejects_malformed_openai_base_url_at_construction_time():
    with pytest.raises(pydantic.ValidationError):
        Settings(openai_base_url="not a url")
