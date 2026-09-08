"""Opt-in registered-model Vision probes; fixture images only, no hardware tools.

Run from the repository root with .venv/bin/python scripts/verify_vision_multimodal.py
--execute. Saved credentials are read in memory and never included in reports.
No provider/model configuration, deployment, camera, or equipment is changed.
"""
from __future__ import annotations

import argparse
import asyncio
from copy import deepcopy
from dataclasses import asdict
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def load_artifact_cases(manifest_path):
    """Load existing capture pairs without rewriting evidence or refreshing time.

    Repository paths beginning runs/ or artifacts/ resolve against ROOT; other
    relative paths resolve against the manifest directory. Perturbations may
    replace detector facts or the annotation reference, never source images.
    """
    manifest_path = Path(manifest_path).resolve(strict=True)
    entries = json.loads(manifest_path.read_text())
    if not isinstance(entries, list) or not entries:
        raise ValueError("artifact manifest must be a nonempty list")
    detector_fields = {"ok", "detected", "specimen_detected", "status", "detector",
                       "bbox_xyxy", "center_px", "roi_xyxy", "confidence", "clear_confirmed"}
    cases = []
    for entry in entries:
        if not isinstance(entry, dict) or not entry.get("case"):
            raise ValueError("artifact case needs a case name")
        if entry.get("contract_id") not in {"pickup", "active_cam", "placement", "clearance"}:
            raise ValueError("unsupported artifact contract")
        if entry.get("expected_tool") not in {None, "accept_visual_evidence", "return_to_owner"}:
            raise ValueError("unsupported expected tool")
        metadata_path = Path(entry["metadata_path"])
        if not metadata_path.is_absolute():
            metadata_path = (ROOT if metadata_path.parts[0] in {"runs", "artifacts"}
                             else manifest_path.parent) / metadata_path
        metadata_path = metadata_path.resolve(strict=True)
        metadata_bytes = metadata_path.read_bytes()
        document = json.loads(metadata_bytes)
        capture = deepcopy(document.get("data", {}).get("observation", {}).get("raw_capture", document))
        source = capture.get("active_cam_ejection_check") or capture
        source_hashes = {}
        for alternatives in (("raw_capture_path", "raw_frame_path"),
                             ("annotated_capture_path", "annotated_frame_path")):
            path_value = next((source[key] for key in alternatives if source.get(key)), None)
            if not path_value:
                raise ValueError("artifact requires existing raw and annotated image paths")
            path = Path(path_value)
            if not path.is_absolute():
                path = ROOT / path if path.parts[0] in {"runs", "artifacts"} else metadata_path.parent / path
            path = path.resolve(strict=True)
            source_hashes[str(path)] = hashlib.sha256(path.read_bytes()).hexdigest()
            source[next(key for key in alternatives if source.get(key))] = str(path)
        perturbation = deepcopy(entry.get("perturbation") or {})
        if not isinstance(perturbation, dict) or set(perturbation) - detector_fields - {"detector_facts", "annotated_frame_path"}:
            raise ValueError("unsupported artifact perturbation")
        facts = perturbation.get("detector_facts", {})
        if not isinstance(facts, dict) or set(facts) - detector_fields:
            raise ValueError("unsupported detector perturbation")
        source.update(deepcopy(facts))
        source.update({key: deepcopy(value) for key, value in perturbation.items() if key in detector_fields})
        if "annotated_frame_path" in perturbation:
            alternative = Path(perturbation["annotated_frame_path"])
            if not alternative.is_absolute():
                alternative = (ROOT if alternative.parts[0] in {"runs", "artifacts"}
                               else manifest_path.parent) / alternative
            alternative = alternative.resolve(strict=True)
            source_hashes[str(alternative)] = hashlib.sha256(alternative.read_bytes()).hexdigest()
            source["annotated_capture_path" if source.get("annotated_capture_path") else "annotated_frame_path"] = str(alternative)
        state_path = metadata_path.parent / "input.json"
        archived_state = json.loads(state_path.read_text()).get("state", {}) if state_path.is_file() else {}
        cases.append({**deepcopy(entry), "metadata_path": str(metadata_path), "capture": capture,
                      "archived_state": archived_state, "synthetic_perturbation": bool(perturbation),
                      "source_metadata_sha256": hashlib.sha256(metadata_bytes).hexdigest(),
                      "source_image_sha256": source_hashes})
    return cases


def state_for_case(case, *, backend, timeout_s):
    """Build an isolated TEST context retaining recorded experiment identity."""
    from orchestrator.state import Mode, OrchestratorState, Stage

    capture = case.get("capture") or {}
    source = capture.get("active_cam_ejection_check") or capture
    archived = case.get("archived_state") or {}
    run_id = capture.get("run_id") or archived.get("run_id")
    if not run_id:
        run_id = next((part for part in Path(case.get("metadata_path", "")).parts if part.startswith("run-")),
                      f"fixture-vision-{backend}")
    spec = deepcopy(archived.get("current_experiment_spec") or {})
    spec["specimen_id"] = capture.get("specimen_id") or source.get("specimen_id") or spec.get("specimen_id") or "fixture-specimen"
    metadata = {"vision_decision_settings": {"timeout_s": timeout_s}}
    for key in ("manipulation_result", "robot_task_result", "utm_clear_execution"):
        original = (archived.get("run_metadata") or {}).get(key) or {}
        if "session_id" in original:
            metadata[key] = {"session_id": original["session_id"]}
    if source.get("session_id") and not any(key in metadata for key in ("manipulation_result", "robot_task_result", "utm_clear_execution")):
        metadata["utm_clear_execution" if case.get("contract_id") == "clearance" else "manipulation_result"] = {"session_id": source["session_id"]}
    return OrchestratorState(
        run_id=run_id, experiment_id=capture.get("experiment_id") or archived.get("experiment_id") or "nonactuating-fixture-probe",
        loop_count=capture.get("loop_id", capture.get("loop_index", archived.get("loop_count", 0))),
        mode=Mode.TEST, stage=Stage.VISION, current_experiment_spec=spec, run_metadata=metadata,
    )


def decision_outcome(decision, expected_tool=None):
    """Separate the model's semantic choice from stale/invalid final gate state."""
    request = decision.get("request") or {}
    if not request and decision.get("response"):
        output = decision["response"].strip()
        if output.startswith("```json") and output.endswith("```"):
            output = output[7:-3].strip()
        try:
            parsed = json.loads(output)
            request = parsed if isinstance(parsed, dict) else {}
        except (ValueError, TypeError):
            pass
    model_tool = request.get("tool")
    return {"model_tool": model_tool, "model_accepted": model_tool == "accept_visual_evidence",
            "final_status": decision.get("status"),
            "semantic_expectation_met": model_tool == expected_tool if expected_tool is not None else None}


async def main(args):
    from dotenv import load_dotenv
    from PIL import Image
    import yaml

    from agents.base_agent import AgentContext
    from agents.vision_decision import review_visual_evidence, select_vision_tool
    from app.bootstrap import _build_backend, _load_configs, _models_cfg_for_backend
    from backends.llm_lease import LLMLeaseCoordinator
    from backends.model_router import ModelRouter
    from mcp_tools.tool_registry import ToolRegistry
    from orchestrator.langgraph_runtime import ModuleRuntimeContext
    from orchestrator.state import Stage
    from utils.utm_specimen_presence import inspect_specimen_presence_path

    load_dotenv(ROOT / ".env", override=False)
    cfg = _load_configs()
    output = Path(tempfile.mkdtemp(prefix="atr-vision-multimodal-"))
    cases = load_artifact_cases(args.artifact_manifest) if args.artifact_manifest else []
    original_digests = {}
    if cases:
        for case in cases:
            original_digests.update(case["source_image_sha256"])
    else:
        cases.append({"case": "tool_selection", "contract_id": "active_cam"})
        fixture_root = ROOT / "tests/fixtures/utm_clear"
        fixture_paths = {name: fixture_root / f"{name}_raw.png" for name in ("upright", "compressed")}
        synthetic = output / "synthetic_empty_raw.png"
        Image.new("RGB", (640, 480), (210, 210, 210)).save(synthetic)
        fixture_paths["synthetic_empty"] = synthetic
        for name, path in fixture_paths.items():
            original_digests[str(path)] = hashlib.sha256(path.read_bytes()).hexdigest()
            capture = inspect_specimen_presence_path(
                path, output_dir=output / "evidence" / name,
                specimen_id="fixture-specimen", frame_id=name,
            )
            cases.append({"case": name, "capture": capture, "synthetic": name == "synthetic_empty",
                          "contract_id": "clearance" if name == "synthetic_empty" else "placement"})
    module = yaml.safe_load((ROOT / "graphs/modules/vision/module.yaml").read_text())["module"]
    report = {
        "schema": "registered_vision_probe.v1", "output_dir": str(output),
        "physical_actuation": False, "hardware_tools_registered": False,
        "synthetic_empty_notice": "Uniform gray synthetic fixture, not a physical UTM clearance proof.",
        "timeout_s": args.timeout_s, "fixture_sha256": original_digests,
        "artifact_manifest": str(Path(args.artifact_manifest).resolve()) if args.artifact_manifest else None,
        "interpretation": "Semantic expectations are declared comparisons, not benchmark accuracy or physical validation.",
        "branches": [],
    }
    secrets = []

    def save_report():
        serialized = json.dumps(report, indent=2, ensure_ascii=False, default=str)
        for secret in secrets:
            if secret:
                serialized = serialized.replace(secret, "[REDACTED]")
        (output / "results.json").write_text(serialized)

    for name in args.backend or ["openai", "vllm"]:
        provider = _build_backend(name, system_cfg=cfg["system"]["system"], cfg=cfg)
        if name == "openai":
            credentials_path = ROOT / "memory/api_keys.json"
            credentials = json.loads(credentials_path.read_text()) if credentials_path.is_file() else {}
            enabled = bool(credentials.get("enabled") and credentials.get("api_key"))
            provider._api_key = credentials.get("api_key", "") if enabled else ""
            if not enabled:
                report["branches"].append({"backend": name, "status": "skipped", "reason": "saved API not enabled"})
                save_report()
                continue
        secrets.append(provider._api_key)
        router = ModelRouter(_models_cfg_for_backend(cfg["models"], name))
        selection = router.select(module.get("llm_role") or "vision_observation")
        branch = {"backend": name, "registered_route": asdict(selection), "cases": []}
        report["branches"].append(branch)
        calls = []
        started = time.perf_counter()

        async def on_call(**event):
            calls.append({**event, "elapsed_s": round(time.perf_counter() - started, 3)})

        ctx = AgentContext(
            model_router=router, primary_backend=provider, fallback_backend=provider,
            rag=None, experiment_db=None, failure_memory=None, tools=ToolRegistry(),
            force_real_llm_in_test=True, active_backend=name,
            model_routers={name: router}, primary_backends={name: provider},
            fallback_backends={name: provider}, backend_fallbacks={name: name},
            llm_lease=LLMLeaseCoordinator(), on_model_call=on_call,
            artifact_run_root=str(output),
        )
        selected_module = {**module, "llm": {**module.get("llm", {}), "backend": name}}
        for source_case in cases:
            case_name = source_case["case"]
            state = state_for_case(source_case, backend=name, timeout_s=args.timeout_s)
            module_ctx = ModuleRuntimeContext(ctx, selected_module, Stage.VISION, state=state)
            calls.clear()
            started = time.perf_counter()
            print(json.dumps({"started": name, "case": case_name, "registered_route": asdict(selection)}), flush=True)
            if "capture" not in source_case:
                decision = await select_vision_tool(state, module_ctx, "active_cam")
            else:
                decision = await review_visual_evidence(
                    state, module_ctx, source_case["capture"], source_case["contract_id"],
                )
            case = {**{key: value for key, value in source_case.items() if key not in {"capture", "archived_state"}},
                    "duration_s": round(time.perf_counter() - started, 3),
                    "model_calls": list(calls), "decision": decision,
                    "source_identity": {"run_id": state.run_id, "loop_id": state.loop_count,
                                        "specimen_id": state.current_experiment_spec["specimen_id"]},
                    **decision_outcome(decision, source_case.get("expected_tool"))}
            branch["cases"].append(case)
            save_report()
            print(json.dumps({"backend": name, "case": case_name, "duration_s": case["duration_s"],
                              "status": decision.get("status"), "model": decision.get("model"),
                              "report": str(output / "results.json")}), flush=True)
    report["source_fixtures_unchanged"] = all(
        hashlib.sha256(Path(path).read_bytes()).hexdigest() == digest
        for path, digest in original_digests.items()
    )
    save_report()
    print(json.dumps({"report": str(output / "results.json"),
                      "source_fixtures_unchanged": report["source_fixtures_unchanged"]}), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--execute", action="store_true", help="Opt in to actual registered API/vLLM model calls.")
    parser.add_argument("--backend", action="append", choices=["openai", "vllm"])
    parser.add_argument("--timeout-s", type=float, default=45.0)
    parser.add_argument("--artifact-manifest", help="JSON list of archived capture cases; replaces built-in cases.")
    arguments = parser.parse_args()
    if not arguments.execute:
        parser.error("Actual model calls require --execute; no probe was run.")
    if not 0 < arguments.timeout_s <= 300:
        parser.error("--timeout-s must be greater than zero and at most 300.")
    asyncio.run(main(arguments))
