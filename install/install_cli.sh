#!/usr/bin/env bash
# File purpose:
# - Install the user-level `atr` launcher for this autonomous_researcher checkout.
#
# Inputs/outputs:
# - Input: this repository path, resolved from the script location.
# - Output: ~/.local/bin/atr and an optional shell PATH block.
#
# Modification guide:
# - Safe places to edit: command names and usage text.
# - Risky places to edit: PROJECT_DIR resolution and PATH update logic.

set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd -- "${SCRIPT_DIR}/.." && pwd)"
INSTALL_DIR="${HOME}/.local/bin"
TARGET="${INSTALL_DIR}/atr"
SHELL_NAME="$(basename "${SHELL:-bash}")"
RC_FILE="${HOME}/.bashrc"

if [[ "${SHELL_NAME}" == "zsh" ]]; then
  RC_FILE="${HOME}/.zshrc"
fi

existing_atr="$(command -v atr || true)"
if [[ -n "${existing_atr}" && "${existing_atr}" != "${TARGET}" && "${ATR_FORCE_INSTALL:-0}" != "1" ]]; then
  cat >&2 <<EOF
Refusing to overwrite existing atr command: ${existing_atr}
Set ATR_FORCE_INSTALL=1 to override this check.
EOF
  exit 1
fi

mkdir -p "${INSTALL_DIR}"

cat > "${TARGET}" <<EOF
#!/usr/bin/env bash
# Managed by autonomous_researcher/install/install_cli.sh
set -euo pipefail

PROJECT_DIR="${PROJECT_DIR}"
BASE_URL="\${ATR_URL:-http://127.0.0.1:7860}"
DEFAULT_BACKEND="\${ATR_BACKEND:-vllm}"

usage() {
  cat <<'USAGE'
Usage:
  atr up
  atr down
  atr gui
  atr live
  atr docs
  atr status
  atr events
  atr backend [vllm|nemoclaw|ollama]
  atr graphs
  atr graph show|validate|compile|dry-run|gate|versions <graph-id>
  atr graph version <graph-id> <version-id>
  atr graph export-yaml <graph-id> [output-file]
  atr graph import-yaml <graph-id> <yaml-file>
  atr graph save-yaml <graph-id> <yaml-file> [--no-activate]
  atr graph run <graph-id> [test|live|replay|fault-injection] [goal text...]
  atr run start [test|live|replay|fault-injection] [goal text...]
  atr run pause|resume|stop|safe-stop
  atr gpu clear
  atr models
  atr model load|unload <e4b|e2b|31b|model-alias>
  atr modules
  atr module show|validate|dry-run|load|unload|versions|register-generated <module-id>
  atr module version <module-id> <version-id>
  atr module save-yaml <module-id> <yaml-file> [--no-activate]
  atr module create <python-file> [module-id] [label text...]
  atr chat "message"
  atr chat bootstrap [goal text...]

Commands:
  up          Start the autonomous_researcher GUI server.
  down        Stop this checkout's GUI server process; server shutdown releases LeRobot live subprocesses.
  gui         Open the main GUI URL.
  live        Open the Live GUI URL with auto bootstrap.
  docs        Open FastAPI docs.
  status      Print /api/state.
  events      Print recent structured events.
  backend     Show current state, or switch inference backend when an argument is given.
  graphs      List Runtime IDE graph configs from /api/graphs.
  graph show  Print one active graph payload.
  graph validate
              Validate active graph handlers/modules/routes.
  graph compile
              Compile-check active graph without starting agents or hardware.
  graph dry-run
              Run non-device transition simulation and record active dry-run gate.
  graph gate  Show live dry-run gate status for the active graph.
  graph versions|version
              List/read saved graph versions.
  graph export-yaml|import-yaml|save-yaml
              Round-trip graph YAML through the same Runtime IDE API. save-yaml validates, versions, and activates unless --no-activate is passed.
  graph run   Start a specific saved active graph through /api/graphs/{graph_id}/run.
  run start   Start a workflow through /api/run/start. Default mode is test.
  run pause   Pause the current run.
  run resume  Resume the current run.
  run stop    Stop the current run.
  run safe-stop
              Request safe stop.
  gpu clear   Run the same GPU Clear action as the GUI.
  models      Print managed NemoClaw/vLLM model status.
  model load  Load one managed vLLM model.
  model unload
              Unload one managed vLLM model.
  modules     List Runtime IDE module catalog entries.
  module show Print one module.yaml payload through the API.
  module validate
              Validate one module payload without executing devices.
  module dry-run
              Show configured internal module step order.
  module load|unload
              Load or unload a module in the Module Management workspace state without deleting files.
  module versions|version
              List/read saved module.yaml versions.
  module save-yaml
              Validate, dry-run, version, and activate a module YAML file unless --no-activate is passed.
  module register-generated
              Approve a Module Designer handler.py after static safety checks and activate module.generated_adapter.
  module create
              Upload a Python file to Module Designer; Gemma 31B converts it to ATR protocol and catalogs it.
  Graph CUI commands intentionally use the same /api/graphs endpoints as Runtime IDE, so GUI/CUI state is cross-reflected after reload.
  Module CUI commands intentionally use the same /api/modules endpoints as Module Management Tool, so GUI/CUI state is cross-reflected after reload.
  chat        Send a message to the Live GUI orchestrator session.
  chat bootstrap
              Trigger Live GUI orchestrator bootstrap from the terminal.

Environment:
  ATR_URL       API base URL. Default: http://127.0.0.1:7860
  ATR_BACKEND   Backend used by run/chat commands. Default: vllm
  ATR_DOWN_FORCE
                Set to 0 to avoid SIGKILL fallback when stopping the GUI server.
USAGE
}

python_bin() {
  if [[ -x "\${PROJECT_DIR}/.venv/bin/python" ]]; then
    printf '%s\n' "\${PROJECT_DIR}/.venv/bin/python"
    return 0
  fi
  command -v python3 || true
}

require_python() {
  local py
  py="\$(python_bin)"
  if [[ -z "\${py}" ]]; then
    echo "error: python3 or project .venv is required for this command" >&2
    exit 1
  fi
  printf '%s\n' "\${py}"
}

pretty_json() {
  local py
  py="\$(python_bin)"
  if [[ -n "\${py}" ]]; then
    "\${py}" -m json.tool 2>/dev/null || cat
  else
    cat
  fi
}

api_get() {
  curl -fsS "\${BASE_URL}\${1}" | pretty_json
  printf '\n'
}

api_post() {
  local path="\${1}"
  local body="\${2}"
  curl -fsS -X POST "\${BASE_URL}\${path}" -H "Content-Type: application/json" -d "\${body}" | pretty_json
  printf '\n'
}

api_put() {
  local path="\${1}"
  local body="\${2}"
  curl -fsS -X PUT "\${BASE_URL}\${path}" -H "Content-Type: application/json" -d "\${body}" | pretty_json
  printf '\n'
}

api_post_text() {
  local path="\${1}"
  local body="\${2}"
  curl -fsS -X POST "\${BASE_URL}\${path}" -H "Content-Type: application/json" -d "\${body}"
  printf '\n'
}

open_url() {
  local url="\${1}"
  if command -v xdg-open >/dev/null 2>&1; then
    nohup xdg-open "\${url}" >/dev/null 2>&1 &
    echo "Opened: \${url}"
  else
    echo "\${url}"
  fi
}

start_server() {
  cd "\${PROJECT_DIR}"
  if [[ ! -x "\${PROJECT_DIR}/.venv/bin/python" ]]; then
    echo "error: virtualenv python not found: \${PROJECT_DIR}/.venv/bin/python" >&2
    echo "create/install the project virtualenv first, then rerun: atr up" >&2
    exit 1
  fi
  exec "\${PROJECT_DIR}/.venv/bin/python" -m app.serve
}

stop_server() {
  local py
  py="\$(require_python)"
  ATR_PROJECT_DIR="\${PROJECT_DIR}" "\${py}" -c 'import os, signal, sys, time

project = os.path.realpath(os.environ["ATR_PROJECT_DIR"])
force = os.environ.get("ATR_DOWN_FORCE", "1") != "0"
targets = []

for name in os.listdir("/proc"):
    if not name.isdigit():
        continue
    pid = int(name)
    if pid in {os.getpid(), os.getppid()}:
        continue
    proc_dir = f"/proc/{pid}"
    try:
        raw = open(os.path.join(proc_dir, "cmdline"), "rb").read()
    except OSError:
        continue
    parts = [part.decode("utf-8", "replace") for part in raw.split(b"\0") if part]
    if not parts:
        continue
    if not ("-m" in parts and "app.serve" in parts):
        continue
    try:
        cwd = os.path.realpath(os.readlink(os.path.join(proc_dir, "cwd")))
    except OSError:
        cwd = ""
    exe_arg = parts[0]
    if os.path.isabs(exe_arg):
        exe = os.path.realpath(exe_arg)
    elif cwd:
        exe = os.path.realpath(os.path.join(cwd, exe_arg))
    else:
        exe = ""
    cmd = " ".join(parts)
    in_project_cwd = cwd == project or cwd.startswith(project + os.sep)
    in_project_venv = exe.startswith(os.path.join(project, ".venv") + os.sep)
    mentions_project = project in cmd
    if in_project_cwd or in_project_venv or mentions_project:
        targets.append(pid)

targets = sorted(set(targets))
if not targets:
    print("No autonomous_researcher GUI server process found.")
    sys.exit(0)

for pid in targets:
    try:
        os.kill(pid, signal.SIGTERM)
    except ProcessLookupError:
        pass
    except PermissionError as exc:
        print(f"error: cannot stop pid {pid}: {exc}", file=sys.stderr)

deadline = time.time() + 5.0
remaining = []
while time.time() < deadline:
    remaining = []
    for pid in targets:
        try:
            os.kill(pid, 0)
            remaining.append(pid)
        except ProcessLookupError:
            pass
    if not remaining:
        break
    time.sleep(0.1)

if remaining and force:
    for pid in remaining:
        try:
            os.kill(pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
    time.sleep(0.2)
    remaining = []
    for pid in targets:
        try:
            os.kill(pid, 0)
            remaining.append(pid)
        except ProcessLookupError:
            pass

if remaining:
    print(f"GUI server stop requested, but still running: {remaining}", file=sys.stderr)
    sys.exit(1)

print("Stopped autonomous_researcher GUI server process(es): " + ", ".join(str(pid) for pid in targets))
'
}

cleanup_lerobot_subprocesses() {
  local py
  py="\$(require_python)"
  ATR_PROJECT_DIR="\${PROJECT_DIR}" "\${py}" -c 'import os, signal, sys, time

project = os.path.realpath(os.environ["ATR_PROJECT_DIR"])
force = os.environ.get("ATR_DOWN_FORCE", "1") != "0"
markers = (
    "lerobot-record",
    "lerobot-teleoperate",
    "lerobot.teleoperate",
    "lerobot.record",
    "lerobot.train",
    "lerobot.rollout",
)
pids_by_group = {}

for name in os.listdir("/proc"):
    if not name.isdigit():
        continue
    pid = int(name)
    if pid in {os.getpid(), os.getppid()}:
        continue
    proc_dir = f"/proc/{pid}"
    try:
        raw = open(os.path.join(proc_dir, "cmdline"), "rb").read()
    except OSError:
        continue
    parts = [part.decode("utf-8", "replace") for part in raw.split(b"\0") if part]
    if not parts:
        continue
    cmd = " ".join(parts)
    if not any(marker in cmd for marker in markers):
        continue
    try:
        cwd = os.path.realpath(os.readlink(os.path.join(proc_dir, "cwd")))
    except OSError:
        cwd = ""
    if not (cwd == project or cwd.startswith(project + os.sep) or project in cmd):
        continue
    try:
        pgid = os.getpgid(pid)
    except ProcessLookupError:
        continue
    if pgid == os.getpgrp():
        continue
    pids_by_group.setdefault(pgid, set()).add(pid)

if not pids_by_group:
    print("No autonomous_researcher LeRobot live subprocess found.")
    sys.exit(0)

for pgid in sorted(pids_by_group):
    try:
        os.killpg(pgid, signal.SIGTERM)
    except ProcessLookupError:
        pass

deadline = time.time() + 5.0
while time.time() < deadline:
    remaining = []
    for pids in pids_by_group.values():
        for pid in pids:
            try:
                os.kill(pid, 0)
                remaining.append(pid)
            except ProcessLookupError:
                pass
    if not remaining:
        break
    time.sleep(0.1)

if force:
    for pgid, pids in sorted(pids_by_group.items()):
        still_running = False
        for pid in pids:
            try:
                os.kill(pid, 0)
                still_running = True
                break
            except ProcessLookupError:
                pass
        if still_running:
            try:
                os.killpg(pgid, signal.SIGKILL)
            except ProcessLookupError:
                pass

items = []
for pgid, pids in sorted(pids_by_group.items()):
    pid_text = ",".join(map(str, sorted(pids)))
    items.append(f"pgid={pgid} pids={pid_text}")
detail = "; ".join(items)
print("Stopped autonomous_researcher LeRobot live subprocess(es): " + detail)
'
}

model_alias() {
  case "\${1}" in
    orchestrator|e4b) printf '%s\n' "gemma4:e4b-it-nvfp4" ;;
    e2b) printf '%s\n' "gemma4:e2b-it-nvfp4" ;;
    31b) printf '%s\n' "gemma4:31b" ;;
    *) printf '%s\n' "\${1}" ;;
  esac
}

json_backend() {
  local py="\$(require_python)"
  ATR_BACKEND_VALUE="\${1}" "\${py}" -c 'import json, os; print(json.dumps({"backend": os.environ["ATR_BACKEND_VALUE"]}))'
}

json_model() {
  local py="\$(require_python)"
  ATR_MODEL_VALUE="\${1}" "\${py}" -c 'import json, os; print(json.dumps({"model": os.environ["ATR_MODEL_VALUE"]}))'
}

json_module_create() {
  local py="\$(require_python)"
  ATR_MODULE_FILE="\${1}" ATR_MODULE_ID="\${2}" ATR_MODULE_LABEL="\${3}" ATR_MODULE_CATEGORY_VALUE="\${ATR_MODULE_CATEGORY:-}" ATR_MODULE_HANDLER_VALUE="\${ATR_MODULE_HANDLER:-runtime.step_complete}" "\${py}" -c 'import json, os, pathlib
path = pathlib.Path(os.environ["ATR_MODULE_FILE"])
module_id = os.environ["ATR_MODULE_ID"] or path.stem.replace("-", "_")
label = os.environ["ATR_MODULE_LABEL"] or module_id.replace("_", " ").title()
print(json.dumps({"module_id": module_id, "label": label, "category": os.environ.get("ATR_MODULE_CATEGORY_VALUE", ""), "handler": os.environ.get("ATR_MODULE_HANDLER_VALUE", "runtime.step_complete"), "source_filename": path.name, "source_text": path.read_text(encoding="utf-8"), "notes": "Created from atr module create", "transform_with_llm": True, "transform_model": "gemma4:31b"}, ensure_ascii=False))'
}

json_module_save_yaml() {
  local py="\$(require_python)"
  ATR_MODULE_YAML_FILE="\${1}" ATR_MODULE_ACTIVATE="\${2}" "\${py}" -c 'import json, os, pathlib, yaml; path=pathlib.Path(os.environ["ATR_MODULE_YAML_FILE"]); raw=yaml.safe_load(path.read_text(encoding="utf-8")) or {}; module=raw.get("module", raw) if isinstance(raw, dict) else raw; print(json.dumps({"module": module, "reason": "atr module save-yaml", "author": "atr-cli", "activate": os.environ["ATR_MODULE_ACTIVATE"] != "0"}, ensure_ascii=False))'
}

json_run_start() {
  local py="\$(require_python)"
  ATR_MODE_VALUE="\${1}" ATR_GOAL_VALUE="\${2}" ATR_BACKEND_VALUE="\${3}" "\${py}" -c 'import json, os; print(json.dumps({"mode": os.environ["ATR_MODE_VALUE"], "goal": os.environ["ATR_GOAL_VALUE"], "backend": os.environ["ATR_BACKEND_VALUE"], "fault": "none", "fault_stage": ""}, ensure_ascii=False))'
}

json_graph_dry_run() {
  local py="\$(require_python)"
  ATR_START_STAGE_VALUE="\${1}" ATR_MAX_STEPS_VALUE="\${2}" "\${py}" -c 'import json, os; print(json.dumps({"start_stage": os.environ["ATR_START_STAGE_VALUE"], "max_steps": int(os.environ["ATR_MAX_STEPS_VALUE"])}))'
}

json_graph_run() {
  local py="\$(require_python)"
  ATR_MODE_VALUE="\${1}" ATR_GOAL_VALUE="\${2}" ATR_BACKEND_VALUE="\${3}" "\${py}" -c 'import json, os; print(json.dumps({"mode": os.environ["ATR_MODE_VALUE"], "goal": os.environ["ATR_GOAL_VALUE"], "backend": os.environ["ATR_BACKEND_VALUE"], "fault": "none", "fault_stage": ""}, ensure_ascii=False))'
}

json_graph_yaml_import() {
  local py="\$(require_python)"
  ATR_GRAPH_YAML_FILE="\${1}" "\${py}" -c 'import json, os, pathlib; print(json.dumps({"yaml_text": pathlib.Path(os.environ["ATR_GRAPH_YAML_FILE"]).read_text(encoding="utf-8")}, ensure_ascii=False))'
}

json_graph_save_yaml() {
  local py="\$(require_python)"
  ATR_GRAPH_YAML_FILE="\${1}" ATR_GRAPH_ACTIVATE="\${2}" "\${py}" -c 'import json, os, pathlib, yaml; path=pathlib.Path(os.environ["ATR_GRAPH_YAML_FILE"]); raw=yaml.safe_load(path.read_text(encoding="utf-8")) or {}; graph=raw.get("graph", raw) if isinstance(raw, dict) else raw; print(json.dumps({"graph": graph, "reason": "atr graph save-yaml", "author": "atr-cli", "activate": os.environ["ATR_GRAPH_ACTIVATE"] != "0"}, ensure_ascii=False))'
}

json_chat_message() {
  local py="\$(require_python)"
  ATR_MESSAGE_VALUE="\${1}" ATR_BACKEND_VALUE="\${2}" "\${py}" -c 'import json, os; print(json.dumps({"message": os.environ["ATR_MESSAGE_VALUE"], "goal": "Terminal Live GUI session", "backend": os.environ["ATR_BACKEND_VALUE"], "session_id": "atr-cli", "constraints": {"runtime_contract": "existing_stage_enum_only", "require_operator_approval": True}}, ensure_ascii=False))'
}

json_chat_bootstrap() {
  local py="\$(require_python)"
  ATR_GOAL_VALUE="\${1}" ATR_BACKEND_VALUE="\${2}" "\${py}" -c 'import json, os; print(json.dumps({"goal": os.environ["ATR_GOAL_VALUE"], "backend": os.environ["ATR_BACKEND_VALUE"], "session_id": "atr-cli", "constraints": {"runtime_contract": "existing_stage_enum_only", "require_operator_approval": True}}, ensure_ascii=False))'
}

if [[ "\$#" -eq 0 ]]; then
  usage
  exit 0
fi

if [[ "\${1:-}" == "-h" || "\${1:-}" == "--help" || "\${1:-}" == "help" ]]; then
  usage
  exit 0
fi

case "\${1:-}" in
  up)
    if [[ "\$#" -eq 1 ]]; then
      start_server
    fi
    ;;
  down)
    if [[ "\$#" -eq 1 ]]; then
      stop_server
      cleanup_lerobot_subprocesses
      exit 0
    fi
    ;;
  gui)
    open_url "\${BASE_URL}/"
    exit 0
    ;;
  live)
    open_url "\${BASE_URL}/live?auto=1&backend=\${DEFAULT_BACKEND}"
    exit 0
    ;;
  docs)
    open_url "\${BASE_URL}/docs"
    exit 0
    ;;
  status)
    api_get "/api/state"
    exit 0
    ;;
  events)
    api_get "/api/events/recent"
    exit 0
    ;;
  backend)
    if [[ "\$#" -eq 1 ]]; then
      api_get "/api/state"
    elif [[ "\$#" -eq 2 ]]; then
      api_post "/api/runtime/backend" "\$(json_backend "\${2}")"
    else
      usage
      exit 2
    fi
    exit 0
    ;;
  graphs)
    api_get "/api/graphs"
    exit 0
    ;;
  graph)
    case "\${2:-}" in
      show)
        [[ -n "\${3:-}" && "\$#" -eq 3 ]] || { usage; exit 2; }
        api_get "/api/graphs/\${3}"
        exit 0
        ;;
      validate)
        [[ -n "\${3:-}" && "\$#" -eq 3 ]] || { usage; exit 2; }
        api_post "/api/graphs/\${3}/validate" "{}"
        exit 0
        ;;
      compile)
        [[ -n "\${3:-}" && "\$#" -eq 3 ]] || { usage; exit 2; }
        api_post "/api/graphs/\${3}/compile" "{}"
        exit 0
        ;;
      dry-run)
        [[ -n "\${3:-}" ]] || { usage; exit 2; }
        start_stage="\${4:-idle}"
        max_steps="\${5:-24}"
        [[ "\$#" -le 5 ]] || { usage; exit 2; }
        api_post "/api/graphs/\${3}/dry-run" "\$(json_graph_dry_run "\${start_stage}" "\${max_steps}")"
        exit 0
        ;;
      gate)
        [[ -n "\${3:-}" && "\$#" -eq 3 ]] || { usage; exit 2; }
        api_get "/api/graphs/\${3}/dry-run-gate"
        exit 0
        ;;
      versions)
        [[ -n "\${3:-}" && "\$#" -eq 3 ]] || { usage; exit 2; }
        api_get "/api/graphs/\${3}/versions"
        exit 0
        ;;
      version)
        [[ -n "\${3:-}" && -n "\${4:-}" && "\$#" -eq 4 ]] || { usage; exit 2; }
        api_get "/api/graphs/\${3}/versions/\${4}"
        exit 0
        ;;
      export-yaml)
        [[ -n "\${3:-}" ]] || { usage; exit 2; }
        [[ "\$#" -le 4 ]] || { usage; exit 2; }
        if [[ -n "\${4:-}" ]]; then
          curl -fsS -X POST "\${BASE_URL}/api/graphs/\${3}/export-yaml" -H "Content-Type: application/json" -d "{}" -o "\${4}"
          echo "Wrote graph YAML: \${4}"
        else
          api_post_text "/api/graphs/\${3}/export-yaml" "{}"
        fi
        exit 0
        ;;
      import-yaml)
        [[ -n "\${3:-}" && -n "\${4:-}" && "\$#" -eq 4 ]] || { usage; exit 2; }
        api_post "/api/graphs/\${3}/import-yaml" "\$(json_graph_yaml_import "\${4}")"
        exit 0
        ;;
      save-yaml)
        [[ -n "\${3:-}" && -n "\${4:-}" ]] || { usage; exit 2; }
        [[ "\$#" -le 5 ]] || { usage; exit 2; }
        activate="1"
        if [[ "\${5:-}" == "--no-activate" ]]; then
          activate="0"
        elif [[ -n "\${5:-}" ]]; then
          usage
          exit 2
        fi
        api_put "/api/graphs/\${3}" "\$(json_graph_save_yaml "\${4}" "\${activate}")"
        exit 0
        ;;
      run)
        [[ -n "\${3:-}" ]] || { usage; exit 2; }
        mode="\${4:-test}"
        if [[ "\$#" -ge 5 ]]; then
          goal="\${*:5}"
        else
          goal=""
        fi
        api_post "/api/graphs/\${3}/run" "\$(json_graph_run "\${mode}" "\${goal}" "\${DEFAULT_BACKEND}")"
        exit 0
        ;;
      *)
        usage
        exit 2
        ;;
    esac
    ;;
  run)
    case "\${2:-}" in
      start)
        mode="\${3:-test}"
        if [[ "\$#" -ge 4 ]]; then
          goal="\${*:4}"
        else
          goal=""
        fi
        api_post "/api/run/start" "\$(json_run_start "\${mode}" "\${goal}" "\${DEFAULT_BACKEND}")"
        ;;
      pause)
        api_post "/api/run/pause" "{}"
        ;;
      resume)
        api_post "/api/run/resume" "{}"
        ;;
      stop)
        api_post "/api/run/stop" "{}"
        ;;
      safe-stop)
        api_post "/api/run/safe-stop" "{}"
        ;;
      *)
        usage
        exit 2
        ;;
    esac
    exit 0
    ;;
  gpu)
    if [[ "\${2:-}" == "clear" && "\$#" -eq 2 ]]; then
      api_post "/api/runtime/gpu-clear" "{}"
      exit 0
    fi
    ;;
  models)
    api_get "/api/runtime/models"
    exit 0
    ;;
  model)
    if [[ "\${2:-}" == "load" && -n "\${3:-}" && "\$#" -eq 3 ]]; then
      api_post "/api/runtime/models/load" "\$(json_model "\$(model_alias "\${3}")")"
      exit 0
    fi
    if [[ "\${2:-}" == "unload" && -n "\${3:-}" && "\$#" -eq 3 ]]; then
      api_post "/api/runtime/models/unload" "\$(json_model "\$(model_alias "\${3}")")"
      exit 0
    fi
    ;;
  modules)
    api_get "/api/modules"
    exit 0
    ;;
  module)
    case "\${2:-}" in
      show)
        [[ -n "\${3:-}" && "\$#" -eq 3 ]] || { usage; exit 2; }
        api_get "/api/modules/\${3}"
        exit 0
        ;;
      validate)
        [[ -n "\${3:-}" && "\$#" -eq 3 ]] || { usage; exit 2; }
        api_post "/api/modules/\${3}/validate" "{}"
        exit 0
        ;;
      dry-run)
        [[ -n "\${3:-}" && "\$#" -eq 3 ]] || { usage; exit 2; }
        api_post "/api/modules/\${3}/dry-run" "{}"
        exit 0
        ;;
      load)
        [[ -n "\${3:-}" && "\$#" -eq 3 ]] || { usage; exit 2; }
        api_post "/api/modules/\${3}/load" "{}"
        exit 0
        ;;
      unload)
        [[ -n "\${3:-}" && "\$#" -eq 3 ]] || { usage; exit 2; }
        api_post "/api/modules/\${3}/unload" "{}"
        exit 0
        ;;
      versions)
        [[ -n "\${3:-}" && "\$#" -eq 3 ]] || { usage; exit 2; }
        api_get "/api/modules/\${3}/versions"
        exit 0
        ;;
      version)
        [[ -n "\${3:-}" && -n "\${4:-}" && "\$#" -eq 4 ]] || { usage; exit 2; }
        api_get "/api/modules/\${3}/versions/\${4}"
        exit 0
        ;;
      save-yaml)
        [[ -n "\${3:-}" && -n "\${4:-}" ]] || { usage; exit 2; }
        [[ "\$#" -le 5 ]] || { usage; exit 2; }
        activate="1"
        if [[ "\${5:-}" == "--no-activate" ]]; then
          activate="0"
        elif [[ -n "\${5:-}" ]]; then
          usage
          exit 2
        fi
        api_put "/api/modules/\${3}" "\$(json_module_save_yaml "\${4}" "\${activate}")"
        exit 0
        ;;
      register-generated)
        [[ -n "\${3:-}" && "\$#" -eq 3 ]] || { usage; exit 2; }
        api_post "/api/modules/\${3}/register-generated" "{}"
        exit 0
        ;;
      create)
        [[ -n "\${3:-}" ]] || { usage; exit 2; }
        file="\${3}"
        module_id="\${4:-}"
        if [[ "\$#" -ge 5 ]]; then
          label="\${*:5}"
        else
          label=""
        fi
        api_post "/api/modules" "\$(json_module_create "\${file}" "\${module_id}" "\${label}")"
        exit 0
        ;;
      *)
        usage
        exit 2
        ;;
    esac
    ;;
  chat)
    if [[ "\${2:-}" == "bootstrap" ]]; then
      shift 2 || true
      goal="\${*:-Terminal Live GUI session}"
      api_post "/api/planning/bootstrap" "\$(json_chat_bootstrap "\${goal}" "\${DEFAULT_BACKEND}")"
      exit 0
    fi
    if [[ "\$#" -ge 2 ]]; then
      shift 1
      api_post "/api/planning/message" "\$(json_chat_message "\$*" "\${DEFAULT_BACKEND}")"
      exit 0
    fi
    ;;
esac

usage
exit 2
EOF

chmod +x "${TARGET}"

path_line='export PATH="$HOME/.local/bin:$PATH"'
if [[ ! -f "${RC_FILE}" ]]; then
  touch "${RC_FILE}"
fi

if ! grep -Fq 'HOME/.local/bin' "${RC_FILE}"; then
  cat >> "${RC_FILE}" <<EOF

# autonomous_researcher CLI PATH
${path_line}
# end autonomous_researcher CLI PATH
EOF
  path_updated="yes"
else
  path_updated="no"
fi

cat <<EOF
Installed atr launcher:
  ${TARGET}

Project bound to:
  ${PROJECT_DIR}

PATH rc file:
  ${RC_FILE} (updated: ${path_updated})

Usage:
  atr up
  atr down
  atr status
  atr models
EOF
