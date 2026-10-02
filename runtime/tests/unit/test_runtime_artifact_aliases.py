from copy import deepcopy

from orchestrator.langgraph_runtime import LangGraphRunLoop
from orchestrator.state import Stage


def test_artifact_aliases_deduplicate_nested_handoff_evidence():
    artifact = {"path": "/capture.png", "status": "stored", "evidence": {"large": [1, 2]}}
    data = {"artifact": artifact, "handoff": [deepcopy(artifact) for _ in range(100)]}
    aliases = LangGraphRunLoop._artifact_payloads(None, Stage.VISION, data)
    assert len(aliases) == 1
    assert aliases[0]["value"] == {"path": "/capture.png", "status": "stored"}
    assert data["artifact"]["evidence"] == {"large": [1, 2]}


def test_nested_distinct_files_remain_discoverable():
    data = {"artifacts": {"nested": {"frame_path": "/a.png"}, "other": {"path": "/b.csv"}}}
    data["self"] = data
    aliases = LangGraphRunLoop._artifact_payloads(None, Stage.VISION, data)
    assert len(aliases) == 2
