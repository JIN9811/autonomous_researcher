from __future__ import annotations

import importlib.util
from pathlib import Path
from textwrap import dedent

import yaml


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
VALIDATOR_PATH = REPOSITORY_ROOT / "scripts" / "validate_documentation.py"


VALID_REFERENCE = dedent(
    """\
    ---
    doc_type: reference
    subtype: runtime
    status: active
    authority: descriptive
    audience:
      - developer
    scope:
      - runtime
    summary: Current runtime behavior.
    source_of_truth:
      - app/main.py
    last_verified: 2026-08-08
    verified_against: 09bbe32
    related_docs:
      - docs/related.md
    supersedes: []
    ---
    # Runtime Reference
    """
)

VALID_INDEX = dedent(
    """\
    ---
    doc_type: index
    subtype: index
    status: active
    authority: navigation
    audience:
      - developer
    scope:
      - repository
    summary: Repository documentation index.
    related_docs: []
    supersedes: []
    ---
    # Index
    """
)

VALID_SNAPSHOT = VALID_INDEX + dedent(
    """\

    FastAPI APIRoute count: 332
    Total app.routes count: 339
    Graph nodes: 19
    Graph edges: 68
    stage_dispatch edges: 12
    """
)

TEST_AGENT_FIGURES = {
    "orchestrator": (
        "orchestrator_01_closed_loop_handoffs",
        "orchestrator_02_execution_effect_boundary",
    ),
    "design": (
        "design_01_closed_loop_handoffs",
        "design_02_execution_effect_boundary",
    ),
    "specimen": (
        "specimen_01_closed_loop_handoffs",
        "specimen_02_execution_effect_boundary",
        "specimen_03_api_connection_architecture",
    ),
    "vision": (
        "vision_01_closed_loop_handoffs",
        "vision_02_execution_effect_boundary",
        "vision_03_api_connection_architecture",
    ),
    "manipulation": (
        "manipulation_01_closed_loop_handoffs",
        "manipulation_02_execution_effect_boundary",
        "manipulation_03_api_connection_architecture",
    ),
    "equipment": (
        "equipment_01_closed_loop_handoffs",
        "equipment_02_execution_effect_boundary",
        "equipment_03_api_connection_architecture",
    ),
    "analysis": (
        "analysis_01_closed_loop_handoffs",
        "analysis_02_execution_effect_boundary",
        "analysis_03_api_connection_architecture",
    ),
    "knowledge": (
        "knowledge_01_closed_loop_handoffs",
        "knowledge_02_execution_effect_boundary",
        "knowledge_03_api_connection_architecture",
    ),
    "bo": (
        "bo_01_closed_loop_handoffs",
        "bo_02_execution_effect_boundary",
    ),
    "guardian": (
        "guardian_01_closed_loop_handoffs",
        "guardian_02_execution_effect_boundary",
    ),
}

TEST_AGENT_TITLES = {
    "orchestrator": "Orchestrator",
    "design": "Design",
    "specimen": "Specimen",
    "vision": "Vision",
    "manipulation": "Manipulation",
    "equipment": "Equipment",
    "analysis": "Analysis",
    "knowledge": "Knowledge",
    "bo": "BO",
    "guardian": "Guardian",
}

TEST_DEVICE_BRIDGE_REFERENCES = {
    "printer_fleet": (
        "docs/device_bridges/printer_fleet_bridge.md",
        "Printer Fleet",
        (
            "printer_fleet_01_system_handoffs",
            "printer_fleet_02_execution_effect_boundary",
            "printer_fleet_03_api_connection_architecture",
        ),
    ),
    "bambu_x2d": (
        "docs/device_bridges/bambu_x2d_bridge.md",
        "Bambu X2D",
        (
            "bambu_x2d_01_system_handoffs",
            "bambu_x2d_02_execution_effect_boundary",
            "bambu_x2d_03_api_connection_architecture",
        ),
    ),
    "prusa_mk4s": (
        "docs/device_bridges/prusa_mk4s_bridge.md",
        "Prusa MK4S",
        (
            "prusa_mk4s_01_system_handoffs",
            "prusa_mk4s_02_execution_effect_boundary",
            "prusa_mk4s_03_api_connection_architecture",
        ),
    ),
    "lerobot": (
        "docs/device_bridges/lerobot_bridge.md",
        "LeRobot",
        (
            "lerobot_01_system_handoffs",
            "lerobot_02_execution_effect_boundary",
            "lerobot_03_api_connection_architecture",
        ),
    ),
    "windows_pyautogui": (
        "docs/device_bridges/windows_pyautogui_bridge.md",
        "Windows PyAutoGUI",
        (
            "windows_pyautogui_01_system_handoffs",
            "windows_pyautogui_02_execution_effect_boundary",
            "windows_pyautogui_03_api_connection_architecture",
        ),
    ),
    "utm_vision": (
        "docs/device_bridges/utm_vision_bridge.md",
        "UTM Vision",
        (
            "utm_vision_01_system_handoffs",
            "utm_vision_02_execution_effect_boundary",
            "utm_vision_03_api_connection_architecture",
        ),
    ),
    "cae_computation": (
        "docs/device_bridges/cae_computation_bridges.md",
        "CAE Computation",
        (
            "cae_computation_01_system_handoffs",
            "cae_computation_02_execution_effect_boundary",
            "cae_computation_03_api_connection_architecture",
        ),
    ),
    "base_simulator": (
        "docs/device_bridges/base_simulator_bridges.md",
        "Base Simulator",
        (
            "base_simulator_01_system_handoffs",
            "base_simulator_02_execution_effect_boundary",
            "base_simulator_03_api_connection_architecture",
        ),
    ),
}

TEST_DEVICE_BRIDGE_SECTIONS = (
    "Summary",
    "Scope",
    "Source of Truth",
    "Actual Role",
    "System Position and Agent Handoffs",
    "Inputs, Commands, and Outputs",
    "Internal Execution",
    "API Surface",
    "Tools and Registry Integration",
    "Connections and Protocols",
    "Configuration and Secrets",
    "State, Events, Artifacts, and Evidence",
    "Runtime Modes and Fallbacks",
    "Safety, Approval, and Effect Boundary",
    "Errors, Timeouts, and Recovery",
    "Operator and GUI Surfaces",
    "Current Verification",
    "Limitations and Known Gaps",
    "Related Documents",
)

TEST_DEVICE_BRIDGE_SOURCE_CONTRACTS = {
    "printer_fleet": (
        ("mcp_tools/printer_tools.py", 'registry.register("printer.prepare"'),
        ("app/main.py", '@app.get("/api/printer/fleet")'),
    ),
    "bambu_x2d": (
        ("device_bridges/bambu_bridge.py", "class PrinterDeviceBridgeManager:"),
        ("app/main.py", '@app.post("/api/printer/bambu-prestart-check")'),
    ),
    "prusa_mk4s": (
        ("device_bridges/prusa_bridge.py", "class PrinterAgenticWorkflow:"),
        ("mcp_tools/printer_tools.py", 'selected_provider(normalized) == "prusa_mk4s"'),
    ),
    "lerobot": (
        ("mcp_tools/lerobot_tools.py", 'registry.register("lerobot.rollout.start"'),
        ("app/main.py", '@app.post("/api/lerobot/rollout/start")'),
    ),
    "windows_pyautogui": (
        ("mcp_tools/equipment_tools.py", 'registry.register("equipment.pyautogui.run"'),
        ("app/main.py", '@app.post("/api/equipment/windows/run-program")'),
    ),
    "utm_vision": (
        ("device_bridges/utm_runtime_bridge.py", "class UTMRuntimeProcessManager:"),
        ("app/main.py", '@app.get("/api/equipment/utm-runtime/status")'),
    ),
    "cae_computation": (
        ("mcp_tools/calculix_tools.py", 'registry.register("calculix.run_job"'),
        ("mcp_tools/pinn_tools.py", 'registry.register("pinn.predict"'),
        ("app/main.py", '@app.post("/api/cae/run")'),
    ),
    "base_simulator": (
        ("device_bridges/base_bridge.py", "class BaseBridge(ABC):"),
        ("device_bridges/simulator/printer_sim.py", "class PrinterSimulator(BaseBridge):"),
    ),
}


def _write(root: Path, relative_path: str, content: str = "") -> Path:
    path = root / relative_path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


def _write_manifest(
    root: Path,
    documents: list[str],
    *,
    snapshot_expected: dict[str, int] | None = None,
) -> Path:
    manifest: dict[str, object] = {
        "version": 1,
        "documents": documents,
        "legacy_scope": {
            "status": "migration_debt",
            "note": "Remaining Markdown is migrated in later batches.",
        },
    }
    if snapshot_expected is not None:
        manifest["snapshot"] = {
            "document": "docs/runtime/current_code_snapshot.md",
            "expected": snapshot_expected,
        }
    return _write(
        root,
        "docs/document_manifest.yaml",
        yaml.safe_dump(manifest, sort_keys=False),
    )


def _write_agent_reference(
    root: Path,
    agent_id: str,
    *,
    figure_count: int | None = None,
) -> Path:
    _write(root, "app/main.py")
    _write(root, "docs/related.md", "# Related\n")
    stems = TEST_AGENT_FIGURES[agent_id]
    if figure_count is not None:
        stems = stems[:figure_count]
    title = TEST_AGENT_TITLES[agent_id]
    figures: list[str] = []
    for index, stem in enumerate(stems, start=1):
        _write(root, f"docs/agents/assets/figures/{stem}.dot", "digraph G {}\n")
        _write(root, f"docs/agents/assets/figures/{stem}.svg", "<svg/>\n")
        figures.extend(
            (
                f"![{title} figure {index}](assets/figures/{stem}.svg)",
                f"**Figure {title}-{index}.** Inspection-backed architecture scope.",
            )
        )
    body = VALID_REFERENCE + "\n" + "\n\n".join(figures) + "\n"
    return _write(root, f"docs/agents/{agent_id}_agent.md", body)


def _write_device_bridge_reference(root: Path, bridge_id: str) -> Path:
    for source_path, token in TEST_DEVICE_BRIDGE_SOURCE_CONTRACTS[bridge_id]:
        path = root / source_path
        existing = path.read_text(encoding="utf-8") if path.is_file() else ""
        if token not in existing:
            _write(root, source_path, existing + token + "\n")
    _write(root, "docs/related.md", "# Related\n")
    path, title, stems = TEST_DEVICE_BRIDGE_REFERENCES[bridge_id]
    figures: list[str] = []
    for index, stem in enumerate(stems, start=1):
        _write(root, f"docs/device_bridges/assets/figures/{stem}.dot", "digraph G {}\n")
        _write(root, f"docs/device_bridges/assets/figures/{stem}.svg", "<svg/>\n")
        figures.extend(
            (
                f"![{title} figure {index}](assets/figures/{stem}.svg)",
                f"**Figure {title}-{index}.** Inspection-backed architecture scope.",
            )
        )
    sections = "\n\n".join(f"## {heading}\n\nCurrent inspected behavior." for heading in TEST_DEVICE_BRIDGE_SECTIONS)
    body = VALID_REFERENCE + "\n" + sections + "\n\n" + "\n\n".join(figures) + "\n"
    return _write(root, path, body)


def _load_validator():
    assert VALIDATOR_PATH.exists(), "documentation validator script is missing"
    spec = importlib.util.spec_from_file_location(
        "validate_documentation", VALIDATOR_PATH
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_split_front_matter_returns_metadata_and_body() -> None:
    module = _load_validator()

    metadata, body = module.split_front_matter(
        "---\ndoc_type: index\nstatus: active\n---\n# Index\n"
    )

    assert metadata["doc_type"] == "index"
    assert metadata["status"] == "active"
    assert body == "# Index\n"


def test_active_reference_requires_verification_fields(tmp_path: Path) -> None:
    module = _load_validator()
    document = _write(
        tmp_path,
        "docs/runtime.md",
        VALID_REFERENCE.replace("source_of_truth:\n  - app/main.py\n", "")
        .replace("last_verified: 2026-08-08\n", "")
        .replace("verified_against: 09bbe32\n", ""),
    )

    errors = module.validate_document(document, tmp_path)

    assert any("source_of_truth" in error for error in errors)
    assert any("last_verified" in error for error in errors)
    assert any("verified_against" in error for error in errors)


def test_source_and_related_paths_must_exist(tmp_path: Path) -> None:
    module = _load_validator()
    document = _write(tmp_path, "docs/runtime.md", VALID_REFERENCE)

    errors = module.validate_document(document, tmp_path)

    assert any("missing source_of_truth path: app/main.py" in error for error in errors)
    assert any("missing related_docs path: docs/related.md" in error for error in errors)


def test_valid_reference_has_no_errors(tmp_path: Path) -> None:
    module = _load_validator()
    _write(tmp_path, "app/main.py")
    _write(tmp_path, "docs/related.md")
    document = _write(tmp_path, "docs/runtime.md", VALID_REFERENCE)

    assert module.validate_document(document, tmp_path) == []


def test_document_rejects_missing_local_markdown_link(tmp_path: Path) -> None:
    module = _load_validator()
    document = _write(
        tmp_path,
        "docs/index.md",
        VALID_INDEX + "\n[Missing Guide](guides/missing.md)\n",
    )

    errors = module.validate_document(document, tmp_path)

    assert any("missing local link: guides/missing.md" in error for error in errors)


def test_document_accepts_existing_local_and_external_links(tmp_path: Path) -> None:
    module = _load_validator()
    _write(tmp_path, "docs/guides/ready.md", "# Ready\n")
    document = _write(
        tmp_path,
        "docs/index.md",
        VALID_INDEX
        + "\n[Ready](guides/ready.md#start)\n"
        + "[API](http://localhost:7860/docs)\n",
    )

    assert module.validate_document(document, tmp_path) == []


def test_simple_agent_reference_requires_two_complete_figure_pairs(tmp_path: Path) -> None:
    module = _load_validator()
    document = _write_agent_reference(tmp_path, "orchestrator")

    assert module.validate_document(document, tmp_path) == []

    source = (
        tmp_path
        / "docs/agents/assets/figures/orchestrator_01_closed_loop_handoffs.dot"
    )
    source.unlink()
    errors = module.validate_document(document, tmp_path)

    assert any("missing agent figure source" in error for error in errors)


def test_complex_agent_reference_requires_third_figure(tmp_path: Path) -> None:
    module = _load_validator()
    document = _write_agent_reference(tmp_path, "specimen", figure_count=2)

    errors = module.validate_document(document, tmp_path)

    assert any(
        "specimen_03_api_connection_architecture" in error for error in errors
    )


def test_agent_reference_rejects_missing_rendering_link_and_caption(
    tmp_path: Path,
) -> None:
    module = _load_validator()
    document = _write_agent_reference(tmp_path, "design")
    rendering = (
        tmp_path
        / "docs/agents/assets/figures/design_01_closed_loop_handoffs.svg"
    )
    rendering.unlink()
    text = document.read_text(encoding="utf-8")
    text = text.replace(
        "![Design figure 2](assets/figures/design_02_execution_effect_boundary.svg)\n\n",
        "",
    )
    text = text.replace("**Figure Design-2.**", "**Execution boundary.**")
    document.write_text(text, encoding="utf-8")

    errors = module.validate_document(document, tmp_path)

    assert any("missing agent figure rendering" in error for error in errors)
    assert any("missing agent figure link" in error for error in errors)
    assert any("missing agent figure caption" in error for error in errors)


def test_manifest_requires_root_readme_links_for_all_canonical_agents(
    tmp_path: Path,
) -> None:
    module = _load_validator()
    _write(tmp_path, "README.md", VALID_INDEX)
    documents = ["README.md"]
    for agent_id in TEST_AGENT_FIGURES:
        document = _write_agent_reference(tmp_path, agent_id)
        documents.append(document.relative_to(tmp_path).as_posix())
    manifest = _write_manifest(tmp_path, documents)

    errors = module.validate_manifest(tmp_path, manifest)

    assert len(
        [error for error in errors if "missing root README agent link" in error]
    ) == 10


def test_manifest_accepts_root_readme_links_for_all_canonical_agents(
    tmp_path: Path,
) -> None:
    module = _load_validator()
    links = "\n".join(
        f"[{agent_id}](docs/agents/{agent_id}_agent.md)"
        for agent_id in TEST_AGENT_FIGURES
    )
    _write(tmp_path, "README.md", VALID_INDEX + "\n" + links + "\n")
    documents = ["README.md"]
    for agent_id in TEST_AGENT_FIGURES:
        document = _write_agent_reference(tmp_path, agent_id)
        documents.append(document.relative_to(tmp_path).as_posix())
    manifest = _write_manifest(tmp_path, documents)

    assert module.validate_manifest(tmp_path, manifest) == []


def test_device_bridge_reference_requires_all_sections_in_order(tmp_path: Path) -> None:
    module = _load_validator()
    document = _write_device_bridge_reference(tmp_path, "printer_fleet")
    text = document.read_text(encoding="utf-8").replace(
        "## Configuration and Secrets\n\nCurrent inspected behavior.\n\n",
        "",
    )
    document.write_text(text, encoding="utf-8")

    errors = module.validate_document(document, tmp_path)

    assert any("missing device bridge section: Configuration and Secrets" in error for error in errors)


def test_device_bridge_reference_requires_figure_source_and_rendering(tmp_path: Path) -> None:
    module = _load_validator()
    document = _write_device_bridge_reference(tmp_path, "bambu_x2d")
    source = tmp_path / "docs/device_bridges/assets/figures/bambu_x2d_01_system_handoffs.dot"
    rendering = tmp_path / "docs/device_bridges/assets/figures/bambu_x2d_02_execution_effect_boundary.svg"
    source.unlink()
    rendering.unlink()

    errors = module.validate_document(document, tmp_path)

    assert any("missing device bridge figure source" in error for error in errors)
    assert any("missing device bridge figure rendering" in error for error in errors)


def test_device_bridge_reference_requires_figure_embed_and_caption(tmp_path: Path) -> None:
    module = _load_validator()
    document = _write_device_bridge_reference(tmp_path, "prusa_mk4s")
    text = document.read_text(encoding="utf-8")
    text = text.replace(
        "![Prusa MK4S figure 3](assets/figures/prusa_mk4s_03_api_connection_architecture.svg)\n\n",
        "",
    )
    text = text.replace("**Figure Prusa MK4S-2.**", "**Execution boundary.**")
    document.write_text(text, encoding="utf-8")

    errors = module.validate_document(document, tmp_path)

    assert any("missing device bridge figure link" in error for error in errors)
    assert any("missing device bridge figure caption" in error for error in errors)


def test_device_bridge_reference_detects_registered_tool_or_api_drift(tmp_path: Path) -> None:
    module = _load_validator()
    document = _write_device_bridge_reference(tmp_path, "lerobot")
    source = tmp_path / "mcp_tools/lerobot_tools.py"
    source.write_text("# registration removed\n", encoding="utf-8")

    errors = module.validate_document(document, tmp_path)

    assert any("missing device bridge source contract" in error for error in errors)
    assert any("lerobot.rollout.start" in error for error in errors)


def test_manifest_requires_root_readme_links_for_all_device_bridges(tmp_path: Path) -> None:
    module = _load_validator()
    _write(tmp_path, "README.md", VALID_INDEX)
    documents = ["README.md"]
    for bridge_id in TEST_DEVICE_BRIDGE_REFERENCES:
        document = _write_device_bridge_reference(tmp_path, bridge_id)
        documents.append(document.relative_to(tmp_path).as_posix())
    manifest = _write_manifest(tmp_path, documents)

    errors = module.validate_manifest(tmp_path, manifest)

    assert len([error for error in errors if "missing root README device bridge link" in error]) == 8


def test_manifest_requires_device_bridge_index_reference_and_figure_links(tmp_path: Path) -> None:
    module = _load_validator()
    _write(tmp_path, "README.md", VALID_INDEX)
    _write(tmp_path, "docs/device_bridges/README.md", VALID_INDEX)
    documents = ["README.md", "docs/device_bridges/README.md"]
    for bridge_id in TEST_DEVICE_BRIDGE_REFERENCES:
        document = _write_device_bridge_reference(tmp_path, bridge_id)
        documents.append(document.relative_to(tmp_path).as_posix())
    manifest = _write_manifest(tmp_path, documents)

    errors = module.validate_manifest(tmp_path, manifest)

    assert len([error for error in errors if "missing device bridge index reference link" in error]) == 8
    assert len([error for error in errors if "missing device bridge index figure link" in error]) == 24


def test_manifest_rejects_duplicate_device_bridge_root_table_row(tmp_path: Path) -> None:
    module = _load_validator()
    rows = [
        f"| [{bridge_id}]({path}) | role | entry | protocol | effect | details | figures |"
        for bridge_id, (path, _title, _stems) in TEST_DEVICE_BRIDGE_REFERENCES.items()
    ]
    root_body = VALID_INDEX + "\n## Device Bridge References\n\n" + "\n".join(rows + [rows[0]]) + "\n"
    _write(tmp_path, "README.md", root_body)
    documents = ["README.md"]
    for bridge_id in TEST_DEVICE_BRIDGE_REFERENCES:
        document = _write_device_bridge_reference(tmp_path, bridge_id)
        documents.append(document.relative_to(tmp_path).as_posix())
    manifest = _write_manifest(tmp_path, documents)

    errors = module.validate_manifest(tmp_path, manifest)

    assert any("root README device bridge table must contain exactly 8 rows" in error for error in errors)


def test_manifest_rejects_undeclared_device_bridge_figure_assets(tmp_path: Path) -> None:
    module = _load_validator()
    links = "\n".join(
        f"[{bridge_id}]({path})"
        for bridge_id, (path, _title, _stems) in TEST_DEVICE_BRIDGE_REFERENCES.items()
    )
    _write(tmp_path, "README.md", VALID_INDEX + "\n" + links + "\n")
    documents = ["README.md"]
    for bridge_id in TEST_DEVICE_BRIDGE_REFERENCES:
        document = _write_device_bridge_reference(tmp_path, bridge_id)
        documents.append(document.relative_to(tmp_path).as_posix())
    _write(tmp_path, "docs/device_bridges/assets/figures/untracked_figure.dot", "digraph G {}\n")
    _write(tmp_path, "docs/device_bridges/assets/figures/untracked_figure.svg", "<svg/>\n")
    manifest = _write_manifest(tmp_path, documents)

    errors = module.validate_manifest(tmp_path, manifest)

    assert any("undeclared device bridge figure source" in error for error in errors)
    assert any("undeclared device bridge figure rendering" in error for error in errors)


def test_manifest_rejects_duplicate_documents(tmp_path: Path) -> None:
    module = _load_validator()
    _write(tmp_path, "README.md", VALID_INDEX)
    manifest = _write_manifest(tmp_path, ["README.md", "README.md"])

    errors = module.validate_manifest(tmp_path, manifest)

    assert any("duplicate document: README.md" in error for error in errors)


def test_manifest_rejects_missing_documents(tmp_path: Path) -> None:
    module = _load_validator()
    manifest = _write_manifest(tmp_path, ["docs/missing.md"])

    errors = module.validate_manifest(tmp_path, manifest)

    assert any("missing manifest document: docs/missing.md" in error for error in errors)


def test_manifest_rejects_unknown_schema_version(tmp_path: Path) -> None:
    module = _load_validator()
    manifest = _write_manifest(tmp_path, [])
    manifest.write_text(
        manifest.read_text(encoding="utf-8").replace("version: 1", "version: 2"),
        encoding="utf-8",
    )

    errors = module.validate_manifest(tmp_path, manifest)

    assert any("version must be 1" in error for error in errors)


def test_manifest_rejects_stale_snapshot_values(tmp_path: Path) -> None:
    module = _load_validator()
    _write(
        tmp_path,
        "docs/runtime/current_code_snapshot.md",
        VALID_SNAPSHOT.replace("Graph nodes: 19", "Graph nodes: 18"),
    )
    manifest = _write_manifest(
        tmp_path,
        ["docs/runtime/current_code_snapshot.md"],
        snapshot_expected={
            "api_routes": 332,
            "app_routes": 339,
            "graph_nodes": 19,
            "graph_edges": 68,
            "stage_dispatch_edges": 12,
        },
    )

    errors = module.validate_manifest(tmp_path, manifest)

    assert any("Graph nodes: expected 19, found 18" in error for error in errors)


def test_valid_manifest_has_no_errors(tmp_path: Path) -> None:
    module = _load_validator()
    _write(tmp_path, "docs/runtime/current_code_snapshot.md", VALID_SNAPSHOT)
    manifest = _write_manifest(
        tmp_path,
        ["docs/runtime/current_code_snapshot.md"],
        snapshot_expected={
            "api_routes": 332,
            "app_routes": 339,
            "graph_nodes": 19,
            "graph_edges": 68,
            "stage_dispatch_edges": 12,
        },
    )

    assert module.validate_manifest(tmp_path, manifest) == []
