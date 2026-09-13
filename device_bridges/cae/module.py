"""Describe the installed computational CAE bridge without constructing it."""
import json

from device_bridges.module_contract import BridgeModule


MODULE = BridgeModule("cae", "1.0.0", json.dumps({
    "label": "Computational CAE / CalculiX",
    "classification": "computational",
    "physical_device": False,
    "root": "device_bridges/cae",
    "requirements": "device_bridges/cae/requirements.txt",
    "registrations": [
        "device_bridges.cae.tools.register_cae_tools",
        "device_bridges.cae.calculix_tools.register_calculix_tools",
    ],
    "runtime_bridge_ids": ["cae_bridge", "calculix_bridge"],
    "tools": [
        "cae.health",
        "cae.prepare_static_analysis",
        "cae.run_static_analysis",
        "calculix.health",
        "calculix.postprocess",
        "calculix.prepare_input",
        "calculix.run_job",
        "calculix.solve",
    ],
    "queue": "cae:calculix",
    "providers": [
        {
            "id": "cae",
            "label": "CAE facade",
            "role": "deterministic analysis and guarded CalculiX orchestration",
            "implementation": "device_bridges.cae.bridge.CAEBridge",
            "source": "device_bridges/cae/bridge.py",
        },
        {
            "id": "calculix",
            "label": "CalculiX",
            "role": "prepared native finite-element solver boundary",
            "implementation": "device_bridges.cae.calculix.CalculiXBridge",
            "source": "device_bridges/cae/calculix.py",
        },
    ],
    "storage": {
        "cae_artifacts": "artifacts/cae",
        "calculix_artifacts": "artifacts/calculix",
        "run_artifacts": "runs",
    },
    "configuration": "configs/devices.yaml",
    "shared_components": {
        "pinn": {"status": "inactive", "ownership": "shared", "source": "mcp_tools/pinn_tools.py"},
    },
    "binding_requirements": [],
    "documentation": "device_bridges/cae/README.md",
}, allow_nan=False))
