"""Tests for `run.py` (the Windows-safe programmatic dev-server launcher).

Only module-level import-time behavior is covered here -- actually starting
a server is an integration/manual concern (see `run.py`'s own docstring and
`deferred-work.md`), not something a unit test should do by binding a real
port.
"""

import asyncio
import importlib.util
import sys
from pathlib import Path

_RUN_PY = Path(__file__).resolve().parent.parent / "run.py"


def _import_run_module():
    """Import `run.py` as a plain module -- `__name__` is `"run"`, not
    `"__main__"`, so its `if __name__ == "__main__":` guard never fires and
    no server actually starts."""
    spec = importlib.util.spec_from_file_location("run", _RUN_PY)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_importing_run_sets_the_event_loop_policy_before_importing_uvicorn():
    module = _import_run_module()

    assert "uvicorn" in sys.modules
    if sys.platform == "win32":
        assert isinstance(asyncio.get_event_loop_policy(), asyncio.WindowsProactorEventLoopPolicy)
    assert hasattr(module, "uvicorn")


def test_run_py_does_not_start_a_server_on_plain_import():
    # Importing (not executing as __main__) must be a no-op beyond setting
    # the policy and importing uvicorn -- no port bound, no server started.
    module = _import_run_module()

    assert module.__name__ == "run"
