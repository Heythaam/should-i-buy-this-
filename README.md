# should-i-buy-this-

## Running locally

```bash
uv sync
uv run playwright install chromium
```

**Windows:**

```bash
uv run python run.py
```

`uvicorn app.main:app --reload`'s `--reload` mode doesn't reliably apply
this project's `WindowsProactorEventLoopPolicy` fix (Playwright's browser
launch needs it to create subprocesses) -- the reloader runs the actual
server in a separate child process, too late for the policy to take effect
there. `run.py` sets the policy and starts `uvicorn` programmatically, in
one process, with no reloader. See `run.py`'s own docstring and
`_bmad-output/implementation-artifacts/deferred-work.md` for the full story.

**macOS/Linux:**

```bash
uv run uvicorn app.main:app --reload
```

Either way, copy `.env.example` to `.env` and fill in `OPENAI_API_KEY` first.