<a id="api-key-setup"></a>

# Choose a model route and configure API keys

Use the Main GUI to choose whether inference starts with the external API or
the local model. Saving a key and enabling its use are related but distinct
actions. No real key belongs in the repository or in a screenshot.

## Set up the API from the GUI

In **Current Models**, open **API Key**, enter the key, and save it. Then choose
the route you want:

| Control | Result |
|---|---|
| **Loading** | Enables the saved key and makes the OpenAI API the first inference route |
| **Unloading** | Disables runtime API use and restores local-first inference; keeps the key for later |

Check the registration and loading state after saving. The response reports
states such as `registered`, not the key characters. The local store is
`memory/api_keys.json`, which Git ignores.

A loaded GUI key takes precedence over the static fallback order in
`configs/models.yaml`. If that API request fails or returns an empty response,
the runtime tries local Gemma/vLLM and then the local model fallback. Unloading
the key does not install or start a missing local model; prepare the local
backend through the normal model controls.

### What survives a refresh or restart?

The server applies the saved setting at startup, before the first browser
status request. Refreshing status also reapplies it silently; neither action
emits a new load/unload event. If `OPENAI_API_KEY` already exists in the local
`.env` or root `env` file, the first GUI status load imports it and marks it
enabled. Check this state when you intended to use local inference only.

<a id="main-gui-api-key-store"></a>

## Configure the environment instead

Use `.env.example` as the tracked list of supported names, not a place to put
credentials. Create the ignored local file:

```bash
cp .env.example .env
```

In Windows PowerShell:

```powershell
Copy-Item .env.example .env
```

For an explicit external route:

```text
AUTONOMOUS_BACKEND=openai
OPENAI_API_KEY=<your-key-here>
OPENAI_BASE_URL=https://api.openai.com/v1
```

For local-first Linux development:

```text
AUTONOMOUS_BACKEND=vllm
OPENAI_API_KEY=<your-key-here>
```

With only the static fallback configuration active, the second example uses
OpenAI after the local backend and local model fallback fail. A loaded GUI key
changes that ordering as described above. Do not infer the active route solely
from the backend name in an environment file.

<a id="local-env"></a>

## Supported variables

Use only the variables needed for the services you have chosen:

- `OPENAI_API_KEY`, `OPENAI_BASE_URL`
- `OPENAI_ORG_ID`, `OPENAI_PROJECT_ID`
- `TAVILY_API_KEY`, `SERPER_API_KEY`

## Keep credentials local

The ignored `.env`, root `env`, and `memory/api_keys.json` stores are local
configuration. Device credentials, PrusaLink credentials, bridge tokens, and
passwords also belong in ignored local configuration, never in public docs.

If you need private notes about which account or project a key belongs to,
`docs/runtime/api_keys.local.md` is ignored for that purpose. Do not commit it.

<a id="local-only-key-notes"></a>

Continue with the [first-run tutorial](../tutorials/first_autonomous_run.en.md)
or return to the [user manual](../tutorials/user_manual.en.md).
