# API Key Setup

This repository must not store real API keys.

Use `.env.example` only as a tracked list of supported environment variable
names. Keep real values in `.env` or the local root `env` file, which are
ignored by Git.

## Local `.env`

Create a local `.env` from the example:

```bash
cp .env.example .env
```

On Windows PowerShell:

```powershell
Copy-Item .env.example .env
```

Then set only the keys you actually use:

```text
AUTONOMOUS_BACKEND=openai
OPENAI_API_KEY=<your-key-here>
OPENAI_BASE_URL=https://api.openai.com/v1
```

For local-first Linux development, keep the local backend and use OpenAI only as
the final fallback:

```text
AUTONOMOUS_BACKEND=vllm
OPENAI_API_KEY=<your-key-here>
```

The backend fallback order is configured in `configs/models.yaml`.

## Main GUI API Key Store

The Main GUI `Current Models` panel includes an `API Key` control. Use it when
this checkout does not have a local `.env` yet or when a new operator needs to
set the OpenAI fallback key from the browser.

- `API Key` opens a small local input dialog.
- `Loading` enables the saved key and makes OpenAI API the first inference route.
- `Unloading` disables runtime API use, restores local inference as the first
  route, and keeps the saved key for later.
- Status refreshes only report and silently reapply the stored setting; they do
  not emit runtime load/unload events.
- Server startup also silently applies the saved setting before the first
  browser status request, so first-call inference uses the saved API route when
  it is loaded.
- If the API route fails or returns an empty response, local Gemma/vLLM is tried
  next, followed by the local model fallback.
- The key is stored in `memory/api_keys.json`, which is ignored by Git.
- If `OPENAI_API_KEY` is already present in `.env` or the local root `env`
  file, the first GUI status load imports it into `memory/api_keys.json` and
  marks it enabled.
- API responses only return registration state such as `registered`; key
  characters are never sent back to the browser after saving.

## Local-Only Key Notes

If you want a written note of which key belongs to which machine or project,
create:

```text
docs/runtime/api_keys.local.md
```

That file is ignored by Git. Do not commit it.

## Supported Variables

- `OPENAI_API_KEY`
- `OPENAI_BASE_URL`
- `OPENAI_ORG_ID`
- `OPENAI_PROJECT_ID`
- `TAVILY_API_KEY`
- `SERPER_API_KEY`

Device bridge credentials, PrusaLink credentials, tokens, and passwords should
also stay in ignored local files such as `.env`, `memory/*.json`, or bridge-local
configuration files.
