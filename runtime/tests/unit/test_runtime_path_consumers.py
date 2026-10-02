"""Initial consumers share finalized roots without sibling-directory inference."""
from dataclasses import fields, replace
from pathlib import Path
import json
import os
import shutil
import subprocess
import sys
from copy import deepcopy

import pytest

from utils import runtime_paths as rp


@pytest.fixture
def disposable_paths(tmp_path, monkeypatch):
    root = Path(__file__).resolve().parents[2]
    baseline = rp.load_paths(root / "configs/repository_layout.json")
    return replace(baseline, workspace_root=tmp_path / "workspace", run_root=tmp_path / "run-volume/runs",
                   memory_root=tmp_path / "state-volume/memory", artifact_root=tmp_path / "export-volume/artifacts",
                   output_root=tmp_path / "output-volume", source_inbox_root=tmp_path / "inbox-volume",
                   user_file_root=tmp_path / "user-volume", log_root=tmp_path / "log-volume")


def test_positional_dependency_contract_is_preserved():
    from agents.base_agent import AgentContext
    from app.controller import ControllerDeps
    assert [f.name for f in fields(ControllerDeps)] == ["agent_registry", "orchestrator_agent_name", "agent_context",
        "run_root", "logging_config", "system_config", "runtime_profile", "paths"]
    ctx = AgentContext(None, None, None, None, None, None, None)
    assert ctx.paths is None
    assert fields(AgentContext)[-2].name == "knowledge_principal"
    assert fields(AgentContext)[-1].name == "paths"


@pytest.mark.parametrize("legacy", [None, "operator-runs", "/tmp/absolute-operator-runs"])
def test_bootstrap_shares_effective_paths_and_preserves_legacy_settings(disposable_paths, monkeypatch, legacy):
    from app import bootstrap
    from backends.mock_llm import MockLLMBackend
    from knowledge.rag import LocalRAGIndex
    original_loader = bootstrap._load_configs
    def configs(paths):
        cfg = original_loader(paths)
        if legacy:
            cfg["system"]["system"]["run_root"] = legacy
        return cfg
    monkeypatch.setattr(bootstrap, "_load_configs", configs)
    monkeypatch.setattr(bootstrap, "_build_backend", lambda *a, **kw: MockLLMBackend())
    controller = bootstrap.load_runtime(paths=disposable_paths)
    paths = controller._deps.paths
    ctx = controller._deps.agent_context
    expected_run = (disposable_paths.repository_root / legacy).resolve() if legacy else disposable_paths.run_root
    assert paths is ctx.paths
    assert paths.run_root == controller._deps.run_root == expected_run
    assert ctx.artifact_run_root == str(expected_run)
    assert ctx.knowledge_service.data_root == disposable_paths.memory_root / "knowledge"
    assert controller._test_mode_execution_profiles_path == disposable_paths.memory_root / "test_mode_execution_profiles.json"
    baseline_guide = disposable_paths.system_root / "project/Project_guide.txt"
    expected = LocalRAGIndex.from_file(baseline_guide,
        source_label=str(disposable_paths.repository_root / "docs/project/Project_guide.txt"))
    assert [(c.text, c.source) for c in ctx.rag._local_index._chunks] == [(c.text, c.source) for c in expected._chunks]


@pytest.mark.parametrize("legacy_guide", ["custom-guide.txt", "absolute"])
def test_explicit_legacy_guide_semantics(disposable_paths, tmp_path, monkeypatch, legacy_guide):
    from app import bootstrap
    from backends.mock_llm import MockLLMBackend
    repo = tmp_path / "isolated-repo"
    repo.mkdir()
    guide = (tmp_path / "external-guide.txt") if legacy_guide == "absolute" else repo / legacy_guide
    guide.write_text("Operator supplied guide must remain authoritative.")
    paths = replace(disposable_paths, repository_root=repo)
    original_loader = bootstrap._load_configs
    def configs(paths):
        cfg = original_loader(paths)
        cfg["system"]["system"]["guide_path"] = str(guide) if legacy_guide == "absolute" else legacy_guide
        return cfg
    monkeypatch.setattr(bootstrap, "_load_configs", configs)
    monkeypatch.setattr(bootstrap, "_build_backend", lambda *a, **kw: MockLLMBackend())
    controller = bootstrap.load_runtime(paths=paths)
    assert controller._deps.agent_context.rag._local_index._chunks[0].text == guide.read_text()


def test_two_injected_runtimes_do_not_rebind_process(disposable_paths, tmp_path, monkeypatch):
    from app import bootstrap
    from backends.mock_llm import MockLLMBackend
    monkeypatch.setattr(bootstrap, "_build_backend", lambda *a, **kw: MockLLMBackend())
    before = rp.current_paths()
    other = replace(disposable_paths, memory_root=tmp_path / "other/memory", run_root=tmp_path / "other/runs")
    first = bootstrap.load_runtime(paths=disposable_paths)
    second = bootstrap.load_runtime(paths=other)
    assert first._deps.paths is first._deps.agent_context.paths is disposable_paths
    assert second._deps.paths is second._deps.agent_context.paths is other
    assert first._test_mode_execution_profiles_path != second._test_mode_execution_profiles_path
    assert rp.current_paths() == before


@pytest.mark.asyncio
async def test_rendered_guideline_context_is_unchanged_with_unrelated_run_store(disposable_paths, monkeypatch):
    from app import bootstrap
    from backends.mock_llm import MockLLMBackend
    monkeypatch.setattr(bootstrap, "_build_backend", lambda *a, **kw: MockLLMBackend())
    controller = bootstrap.load_runtime(paths=disposable_paths)
    # Reproduce the pre-migration rendering from the same baseline guide bytes.
    query = ("orchestrator live gui experiment planning existing runtime stages "
             "DesignAgent printer specimen spec Guardian operator approval goal message")
    result = await controller._deps.agent_context.rag.retrieve(query, top_k_local=3)
    lines = [f"[source={c['source']}]\n{c['text'].strip()[:1200]}" for c in result["local_chunks"] if c["text"].strip()]
    guideline = disposable_paths.system_root / "agents/specimen_design_existing_runtime_guideline.txt"
    lines.append("[source=docs/agents/specimen_design_existing_runtime_guideline.txt]\n" + guideline.read_text().strip()[:1800])
    assert await controller._live_guideline_context(operator_message="message", goal="goal") == "\n\n---\n\n".join(lines)
    assert controller._resolve_workspace_source_path("artifacts/a.bin") == disposable_paths.repository_root / "artifacts/a.bin"


def test_main_resources_use_finalized_unrelated_roots(tmp_path):
    from tools.repository_layout.sandbox import require_boundary
    require_boundary()
    root = Path(__file__).resolve().parents[2]
    code = tmp_path / "code-volume/application"
    guides = tmp_path / "guide-volume/reference"
    for suffix in ("web/templates", "web/static", "sim/robotis_omx"):
        (code / suffix).mkdir(parents=True)
    shutil.copytree(root / "configs", code / "configs")
    shutil.copytree(root / "graphs", code / "graphs")
    selected = rp.load_paths(root / "configs/repository_layout.json")
    shutil.copytree(selected.system_root / "project", guides / "project")
    config = tmp_path / "layout.json"
    layout = json.loads((root / "configs/repository_layout.json").read_text())
    layout.update(repository_root=str(root), runtime_root=str(code), system_root=str(guides),
                  workspace_root=str(tmp_path / "workspace"), candidates={})
    config.write_text(json.dumps(layout))
    script = '''
from pathlib import Path
from tools.repository_layout.fixture_server import fixture_application
with fixture_application("import_only") as (app, guard, _):
    p = app.controller._deps.paths
    assert p is app.RUNTIME_PATHS is app.controller._deps.agent_context.paths
    assert p.runtime_root != p.repository_root
    assert p.system_root != p.repository_root / "docs"
    expected = {
        "PLC_CONFIG_PATH": (p.runtime_root, "configs/plc.yaml"),
        "PLC_CONFIG_MEMORY_PATH": (p.memory_root, "plc_bridge_config.json"),
        "PLC_TRANSACTION_STATE_PATH": (p.memory_root, "plc_bridge_state.json"),
        "AGENT_BASELINE_DOC_PATH": (p.system_root, "runtime/agent_program_baseline.md"),
        "BO_WORKSPACE_SETTINGS_PATH": (p.memory_root, "bo_workspace_settings.json"),
        "EQUIPMENT_SKILL_ROOT": (p.memory_root, "equipment_skills"),
        "EQUIPMENT_SKILL_FLOW_PATH": (p.runtime_root, "graphs/modules/equipment/equipment_skill_flows.json"),
        "EQUIPMENT_SKILL_FLOW_RUNTIME_ROOT": (p.memory_root, "equipment_runtime/equipment_skill_flow_latest"),
        "EQUIPMENT_RUNTIME_ROOT": (p.memory_root, "equipment_runtime"),
        "EQUIPMENT_SKILL_AUTHORING_JOB_ROOT": (p.memory_root, "equipment_runtime/skill_authoring_jobs"),
        "EQUIPMENT_WORKSPACE_SETTINGS_PATH": (p.memory_root, "equipment_workspace_settings.json"),
        "KNOWLEDGE_MEMORY_ROOT": (p.memory_root, "knowledge"),
        "RUNTIME_GRAPH_CONFIG_ROOT": (p.runtime_root, "graphs/configs"),
        "RUNTIME_GRAPH_CONFIG_PATH": (p.runtime_root, "graphs/configs/atr_closed_loop.yaml"),
        "RUNTIME_GRAPH_VERSION_ROOT": (p.memory_root, "graph_versions"),
        "RUNTIME_MODULE_ROOT": (p.runtime_root, "graphs/modules"),
        "RUNTIME_MODULE_VERSION_ROOT": (p.memory_root, "module_versions"),
        "API_KEY_SETTINGS_PATH": (p.memory_root, "api_keys.json"),
        "WANDB_LOCAL_API_KEY_SETTINGS_PATH": (p.memory_root, "wandb_local_api_key.json"),
        "TEST_MODE_EXECUTION_PROFILES_PATH": (p.memory_root, "test_mode_execution_profiles.json"),
        "LEROBOT_ACTION_LOG_ROOT": (p.run_root, "lerobot_action_logs"),
        "ACTIVE_ROBOT_CAM_LATEST_RESULT_PATH": (p.run_root, "active_robot_cam/latest_active_robot_cam_result.json"),
        "BAMBU_HTTP_EXPORT_ROOT": (p.artifact_root, "bambu_http_exports"),
    }
    for name, (base, suffix) in expected.items():
        assert getattr(app, name) == base / suffix, name
    assert app.templates.env.loader.searchpath == [str(p.runtime_root / "web/templates")]
    mounts = {r.path: r.app for r in app.app.routes if hasattr(r, "app")}
    assert Path(mounts["/static"].directory) == p.runtime_root / "web/static"
    assert Path(mounts["/assets/robotis-omx"].directory) == p.runtime_root / "sim/robotis_omx"
    assert not guard.denied, guard.denied
'''
    result = subprocess.run([sys.executable, "-S", "-c", script], env={**os.environ, "ATR_LAYOUT_CONFIG": str(config)},
                            capture_output=True, text=True, timeout=60)
    assert result.returncode == 0, result.stdout + result.stderr


@pytest.fixture
def split_bridge_runtime(disposable_paths, tmp_path, monkeypatch):
    from app import bootstrap
    from backends.mock_llm import MockLLMBackend
    paths = replace(disposable_paths, repository_root=tmp_path / "legacy-volume/repository",
                    runtime_root=tmp_path / "source-volume/runtime")
    configs = {"system": {"system": {}}, "models": {}, "devices": {"devices": {}}, "lerobot": {}}
    monkeypatch.setattr(bootstrap, "_load_configs", lambda paths: configs)
    monkeypatch.setattr(bootstrap, "_build_backend", lambda *a, **kw: MockLLMBackend())
    return paths, configs


@pytest.mark.parametrize("artifact_setting", [None, "artifacts/custom-pinn", "absolute"])
def test_pinn_storage_preserves_explicit_paths_and_uses_typed_default(split_bridge_runtime, tmp_path, artifact_setting):
    from app import bootstrap
    paths, configs = split_bridge_runtime
    pinn = {"enabled": True, "active_model_id": "existing-model", "runtime_training_enabled": False}
    if artifact_setting is not None:
        pinn["artifact_dir"] = str(tmp_path / "external-pinn") if artifact_setting == "absolute" else artifact_setting
    configs["devices"]["devices"]["pinn"] = pinn
    before = deepcopy(configs)
    controller = bootstrap.load_runtime(paths=paths)
    bridge = controller._deps.agent_context.tools.resource("pinn_bridge")
    expected = (tmp_path / "external-pinn" if artifact_setting == "absolute" else
                paths.repository_root / "artifacts/custom-pinn" if artifact_setting else paths.artifact_root / "pinn")
    assert bridge.config.artifact_dir == expected
    assert expected.is_dir()
    assert bridge.config.active_model_id == "existing-model"
    assert bridge.config.runtime_training_enabled is False
    assert configs == before
    assert not (paths.runtime_root / "artifacts").exists()


@pytest.mark.parametrize("devices_config", [
    {"devices": {"pinn": None}},
    {"devices": {"pinn": "unconfigured"}},
    {"devices": {"pinn": []}},
    {"devices": {"pinn": ["ignored"]}},
    {"devices": {"pinn": False}},
    {"pinn": 42},
    {"devices": None, "pinn": {"enabled": False, "active_model_id": "must-be-ignored"}},
    {"devices": "ignored", "pinn": {"runtime_training_enabled": True}},
    {"devices": [], "pinn": {"mode": "must-be-ignored"}},
    {"devices": 42},
    None,
    "ignored",
    ["ignored"],
])
def test_pinn_bootstrap_tolerates_non_object_optional_sections(split_bridge_runtime, devices_config):
    from app import bootstrap
    paths, configs = split_bridge_runtime
    configs["devices"] = deepcopy(devices_config)
    before = deepcopy(configs)
    controller = bootstrap.load_runtime(paths=paths)
    config = controller._deps.agent_context.tools.resource("pinn_bridge").config
    assert (config.enabled, config.mode, config.active_model_id, config.runtime_training_enabled) == (True, "test", "", False)
    assert config.artifact_dir == paths.artifact_root / "pinn"
    assert config.artifact_dir.is_dir()
    assert configs == before


def test_pinn_bootstrap_preserves_valid_nondefault_options(split_bridge_runtime):
    from app import bootstrap
    paths, configs = split_bridge_runtime
    configs["devices"] = {"pinn": {"enabled": False, "mode": "live", "active_model_id": "configured-model",
                                   "runtime_training_enabled": True}}
    before = deepcopy(configs)
    controller = bootstrap.load_runtime(paths=paths)
    config = controller._deps.agent_context.tools.resource("pinn_bridge").config
    assert (config.enabled, config.mode, config.active_model_id, config.runtime_training_enabled) == (False, "live", "configured-model", True)
    assert config.artifact_dir == paths.artifact_root / "pinn"
    assert configs == before


def test_changed_mixed_bridge_arguments_keep_legacy_storage_base(split_bridge_runtime, monkeypatch):
    from app import bootstrap
    from mcp_tools import printer_tools
    paths, configs = split_bridge_runtime
    configs["devices"]["devices"] = {
        "utm_vision_runtime": {"log_dir": "custom/utm-logs"},
        "specimen_pose_tracker": {"log_dir": "custom/pose-logs", "artifact_dir": "custom/pose-runs",
                                  "script_path": "scripts/custom-pose.sh"},
        "printer": {"connection_memory_path": "custom/printer.json"},
        "equipment": {"windows_pyautogui": {"artifact_dir": "custom/equipment",
                        "connection_memory_path": "custom/equipment.json"}},
    }
    configs["lerobot"] = {"lerobot": {"session_memory_path": "custom/sessions.json", "output_root": "custom/training"}}
    captured = {}
    def observe_factory(owner, name, key):
        original = getattr(owner, name)
        def capture(*args, **kwargs):
            result = original(*args, **kwargs)
            captured[key] = result
            return result
        monkeypatch.setattr(owner, name, capture)
    observe_factory(bootstrap, "get_utm_runtime_manager", "utm")
    observe_factory(bootstrap, "get_specimen_pose_tracker_bridge", "pose")
    observe_factory(printer_tools.PrinterDeviceBridgeManager, "from_devices_config", "printer")
    controller = bootstrap.load_runtime(paths=paths)
    registry = controller._deps.agent_context.tools
    equipment = registry.resource("equipment.bridge").config
    lerobot = registry.resource("lerobot.bridge").config
    actual = {
        "utm_log": captured["utm"].config.log_dir,
        "utm_memory": captured["utm"].config.camera_config.memory_path,
        "pose_log": captured["pose"].config.log_dir,
        "pose_artifact": captured["pose"].config.artifact_dir,
        "pose_script": captured["pose"].config.script_path,
        "printer_memory": captured["printer"].config.connection_memory_path,
        "equipment_artifact": equipment.artifact_dir,
        "equipment_memory": equipment.connection_memory_path,
        "equipment_profile": equipment.utm_profile_memory_path,
        "lerobot_memory": lerobot.session_memory_path,
        "lerobot_output": lerobot.output_root,
        "lerobot_logs": lerobot.session_log_root,
    }
    suffixes = {
        "utm_log": "custom/utm-logs", "utm_memory": "memory/device_bridge/utm_camera_config.json",
        "pose_log": "custom/pose-logs", "pose_artifact": "custom/pose-runs", "pose_script": "scripts/custom-pose.sh",
        "printer_memory": "custom/printer.json", "equipment_artifact": "custom/equipment",
        "equipment_memory": "custom/equipment.json", "equipment_profile": "memory/equipment_utm_profile.json",
        "lerobot_memory": "custom/sessions.json", "lerobot_output": "custom/training", "lerobot_logs": "runs/lerobot_sessions",
    }
    expected = {name: paths.repository_root / suffix for name, suffix in suffixes.items()}
    expected["utm_memory"] = paths.memory_root / "device_bridge/utm_camera_config.json"
    expected["equipment_profile"] = paths.memory_root / "equipment_utm_profile.json"
    expected["lerobot_logs"] = paths.run_root / "lerobot_sessions"
    assert actual == expected
    assert lerobot.artifact_run_root == paths.run_root
    # The direct UTM test handler is software-only and writes a synthetic CSV.
    result = registry.call("utm.run_protocol", {"mode": "test", "run_id": "binding-check", "specimen_id": "fixture"})
    assert Path(result["result_file"]).is_relative_to(paths.artifact_root / "equipment/binding-check/utm")
    assert Path(result["result_file"]).is_file()
    assert not paths.runtime_root.exists()
