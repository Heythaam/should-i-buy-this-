"""Programmatic dev-server launcher: `uv run python run.py`.

On Windows, `uvicorn app.main:app --reload` doesn't reliably pick up
`app/main.py`'s own `WindowsProactorEventLoopPolicy` fix: the CLI's
`--reload` mode runs the actual server in a separate, reloader-spawned
child process, and the policy ends up set too late relative to that
reloader's own event-loop setup -- Playwright's browser launch then still
fails with the Selector-loop `NotImplementedError` this project's Windows
fix exists to prevent (see `deferred-work.md`).

Running this script directly avoids that: the policy below is set in this
one process, before `uvicorn` is even imported, and `reload` is left off so
no separate reloader subprocess is ever spawned -- there is exactly one
process, and it has the right policy before the event loop is created.

This is the recommended way to run the app locally on Windows. On other
platforms, `uvicorn app.main:app --reload` works fine directly; this script
still works there too (the policy-setting below is a no-op), just without
auto-reload.
"""

import asyncio
import sys

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())

import uvicorn

if __name__ == "__main__":
    uvicorn.run("app.main:app", host="127.0.0.1", port=8000)
