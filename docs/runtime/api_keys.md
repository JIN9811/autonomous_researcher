# API Key Setup

This repository must not store real API keys.

Use `.env.example` only as a tracked list of supported environment variable
names. Keep real values in `.env`, which is ignored by Git.

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
