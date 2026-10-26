"""Shared test fixtures for `tests/pipeline/*` (used by both
`test_orchestrator.py` and `test_synthesis.py`, which previously each
defined their own verbatim copy of this stub).
"""

import pytest


class StubLLMClient:
    """An `LLMClient` stub returning pre-set responses in call order."""

    def __init__(self, responses) -> None:
        self._responses = list(responses)
        self.calls: list[dict] = []

    async def complete(self, *, system_prompt, user_prompt, response_model, model):
        self.calls.append(
            {
                "system_prompt": system_prompt,
                "user_prompt": user_prompt,
                "response_model": response_model,
                "model": model,
            }
        )
        return self._responses.pop(0)


@pytest.fixture
def stub_llm_client():
    """Returns the `StubLLMClient` class so tests can construct it with
    whatever per-test response sequence they need, e.g.
    `llm = stub_llm_client([...])`.
    """
    return StubLLMClient
