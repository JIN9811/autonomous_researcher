"""Opt-in isolated source probes with optional external validation archives."""
from __future__ import annotations

from contextlib import contextmanager
from copy import deepcopy
import argparse
import asyncio
import json
from pathlib import Path
import re
import shutil
import sys
import tempfile
from time import monotonic
import urllib.request
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
PAPER_URL = "https://arxiv.org/pdf/2408.09869v5"


@contextmanager
def fixture_workspace(*, artifacts_dir=None):
    """Clean temporary inputs; optionally retain a separate validation-only copy."""
    archive_root = Path(artifacts_dir).expanduser().resolve() if artifacts_dir else None
    if archive_root is not None and archive_root.is_relative_to(ROOT):
        raise ValueError("Validation artifacts must be outside the ATR repository")
    with tempfile.TemporaryDirectory(prefix="atr-source-verification-") as directory:
        root = Path(directory)
        inbox = root / "inputs"
        inbox.mkdir()
        documents = {
            "conditions.md": (
                "# Evidence conditions\n\nThis is a synthetic software fixture, not a measurement.\n"
                "For variant Azure, the allowable drift is 17.5 mm at 23 °C.\n"
                "For variant Amber, the allowable drift is 9.25 mm at 18 °C.\n"
                "These conditions are not interchangeable.\n\n"
                "| Variant | Drift (mm) | Temperature (°C) |\n"
                "| --- | --- | --- |\n| Azure | 17.5 | 23 |\n| Amber | 9.25 | 18 |\n\n"
                "## Qualification\nDo not extrapolate outside the stated conditions.\n"
            ),
            "structured.csv": "variant,drift_mm,condition\nAzure,17.5,reference only\nAmber,9.25,not interchangeable\n",
            "nested.json": '{"fixture":true,"process":{"dwell_s":42,"status":"unverified"},"units":"seconds"}',
            "page.html": (
                "<html><body><h1>Process evidence</h1><p>Reference only, not an execution command.</p>"
                "<table><tr><th>Phase</th><th>Duration (s)</th></tr>"
                "<tr><td>Hold</td><td>42</td></tr></table>"
                "<h2>Limitation</h2><p>Manual confirmation remains required.</p></body></html>"
            ),
            "multilingual.txt": "검증용 참조 데이터입니다. 유지 시간은 42초입니다.\nReference only; 未确认, not validated.\n",
            "long.md": "# Full source preservation\n\n" + "\n\n".join(
                f"## Section {i}\nReference entry {i}: context applies only to the named variant. "
                "This entry is a software-verification observation and not physical evidence. " * 3
                for i in range(1, 36)
            ) + "\n\n## Final qualification\nTAIL-EVIDENCE: the retention window is 73 days, not indefinitely.\n",
        }
        for name, body in documents.items():
            (inbox / name).write_text(body, encoding="utf-8")
        (inbox / "duplicate.md").write_text(documents["conditions.md"], encoding="utf-8")
        with zipfile.ZipFile(inbox / "layout.docx", "w") as package:
            package.writestr("word/document.xml", (
                '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
                '<w:body><w:p><w:r><w:t>Document structure</w:t></w:r></w:p>'
                '<w:tbl><w:tr><w:tc><w:p><w:r><w:t>Dwell (s)</w:t></w:r></w:p></w:tc>'
                '<w:tc><w:p><w:r><w:t>42</w:t></w:r></w:p></w:tc></w:tr></w:tbl>'
                '<w:p><w:r><w:t>Only a reference; not yet validated.</w:t></w:r></w:p>'
                '</w:body></w:document>'
            ))
            package.writestr("word/footnotes.xml", (
                '<w:footnotes xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
                '<w:footnote w:id="1"><w:p><w:r><w:t>Duration is conditional; reference only.</w:t>'
                '</w:r></w:p></w:footnote></w:footnotes>'
            ))
            package.writestr("word/header1.xml", (
                '<w:hdr xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
                '<w:p><w:r><w:t>Reference revision A</w:t></w:r></w:p></w:hdr>'
            ))
        (inbox / "unreadable.pdf").write_bytes(b"not a PDF")
        try:
            yield root
        finally:
            if archive_root is not None:
                archive_root.mkdir(parents=True, exist_ok=True)
                # Unique run directory, no overwrite of existing validation evidence.
                shutil.copytree(root, archive_root / f"{root.name}-archive")


def download_paper(inbox: Path) -> Path:
    """Download one public, version-pinned source only inside the isolated inbox."""
    request = urllib.request.Request(PAPER_URL, headers={"User-Agent": "ATR-source-verification/1.0"})
    with urllib.request.urlopen(request, timeout=45) as response:
        content = response.read(20 * 1024 * 1024 + 1)
    if len(content) > 20 * 1024 * 1024 or not content.startswith(b"%PDF-"):
        raise ValueError("Public source download did not yield a bounded PDF")
    target = inbox / "publication.pdf"
    target.write_bytes(content)
    return target


def registered_context(backend, root):
    """Use saved credentials and registered models; never alter global selection."""
    from dotenv import load_dotenv
    from agents.base_agent import AgentContext
    from app.bootstrap import _build_backend, _load_configs, _models_cfg_for_backend
    from backends.model_router import ModelRouter
    from backends.llm_lease import LLMLeaseCoordinator
    from mcp_tools.tool_registry import ToolRegistry
    load_dotenv(ROOT / ".env", override=False)
    cfg = _load_configs()
    provider = _build_backend(backend, system_cfg=cfg["system"]["system"], cfg=cfg)
    models = deepcopy(_models_cfg_for_backend(cfg["models"], backend))
    if backend == "openai":
        credentials = json.loads((ROOT / "memory/api_keys.json").read_text())
        if not credentials.get("enabled") or not credentials.get("api_key"):
            raise RuntimeError("Saved API registration is disabled or unavailable")
        provider._api_key = credentials["api_key"]
        selected = models["models"][models["task_routes"]["knowledge_query"]]["primary"]
    else:
        selected = "gemma4:31b"
        registered = {value for role in models["models"].values() for value in role.values()}
        if selected not in registered:
            raise RuntimeError("Requested local model is not registered")
    # Isolated verification selects a registered model and disallows fallbacks.
    for role in models["models"]:
        models["models"][role] = {"primary": selected}
    router = ModelRouter(models)
    provider = CapturingProvider(provider, root)
    return AgentContext(model_router=router, primary_backend=provider, fallback_backend=provider,
        rag=None, experiment_db=None, failure_memory=None, tools=ToolRegistry(),
        force_real_llm_in_test=True, allow_mock_fallback=False, active_backend=backend,
        model_routers={backend: router}, primary_backends={backend: provider},
        fallback_backends={backend: provider}, backend_fallbacks={backend: backend},
        llm_lease=LLMLeaseCoordinator(), artifact_run_root=str(root / "runs"))


class CapturingProvider:
    """Keep inference diagnostics in the isolated verification workspace."""
    def __init__(self, provider, root):
        self.provider, self.root, self.calls = provider, root, 0

    def __getattr__(self, name):
        return getattr(self.provider, name)

    async def complete(self, **kwargs):
        self.calls += 1
        response = await self.provider.complete(**kwargs)
        self.root.mkdir(parents=True, exist_ok=True)
        raw = response.raw or {}
        record = {"task": kwargs.get("metadata", {}).get("task_type"), "model": response.model,
            "prompt_chars": len(kwargs.get("user_prompt", "")), "text": response.text,
            "usage": raw.get("usage"), "finish_reasons": [item.get("finish_reason") for item in raw.get("choices", [])]}
        (self.root / f"response-{self.calls:04d}.json").write_text(json.dumps(record, ensure_ascii=False, default=str))
        return response


def answer_checks(answer, required, *, qualification=None):
    """Check retained values and, where required, the source's qualification."""
    normalized = answer.lower().replace("*", "")
    checks = {token: token.lower() in normalized for token in required}
    if qualification == "ocr_disabled":
        checks[qualification] = bool(re.search(
            r"\bocr\s+(?:(?:is|was|remained)\s+)?(?:disabled|off|not\s+(?:enabled|used))\b"
            r"|\b(?:without|disabled)\s+ocr\b", normalized))
    return checks


async def verify_consumers(ctx, library, root, source_id, *, question, required, qualification=None):
    from agents.knowledge_decision import run_knowledge_decision
    from agents.bo_agent import BOAgent
    from agents.equipment_decision import decide_equipment
    from knowledge.markdown_runtime import store_for
    from mcp_tools.source_tools import register_source_tools, source_context
    from orchestrator.state import Mode, OrchestratorState, Stage
    register_source_tools(ctx.tools, lambda: library)
    state = OrchestratorState(run_id="source-probe", experiment_id="software-fixture", mode=Mode.TEST,
        stage=Stage.KNOWLEDGE, active_goal=question + " Search and read the sources corpus. "
        "Publish a concise cited answer with units and limitations; do not write a duplicate note.")
    decision = await run_knowledge_decision(state, ctx, store=store_for(project_root=root), evidence=[],
        scope={"run_id": state.run_id}, settings={"corpora": ["sources"],
            "source_scope": {"source_id": source_id}, "decision_max_steps": 12})
    summary = decision.get("summary", "").lower()
    checks = answer_checks(summary, required, qualification=qualification)
    state.run_metadata["knowledge"] = decision
    bo = BOAgent._knowledge_context_from_state(state)
    knowledge_ok = (decision.get("status") == "accepted" and decision.get("llm_used")
        and bool(decision.get("citations")) and bool(decision.get("selected_knowledge"))
        and all(checks.values())
        and bo["selected_knowledge"] == decision["selected_knowledge"]
        and bo["citations"] == decision["citations"])
    refs = source_context(ctx, question, scope={"source_id": source_id})
    context = {"task": "Review reference knowledge, explain relevant evidence, and request operator review. "
               "No equipment execution has been requested.", "evidence_refs": ["task:reference-review"],
               "success": False, "source_knowledge": refs}
    proposals = {"request_operator": {"proposal_id": "reference-review-only"}}
    before = deepcopy(proposals)
    equipment = await decide_equipment(state, ctx, phase="select", context=context, proposals=proposals)
    equipment_ok = (equipment.get("status") == "accepted" and equipment.get("llm_used")
        and proposals == before and equipment.get("request", {}).get("tool") == "request_operator"
        and equipment.get("evidence", {}).get("source_knowledge", {}).get("citations"))
    return {"knowledge_bo": bool(knowledge_ok), "equipment_decision": bool(equipment_ok),
        "knowledge_tools": [t["tool"] for t in decision["trace"]],
        "knowledge_model": decision.get("model"), "equipment_model": equipment.get("model"),
        "answer_checks": checks,
        "decision": decision, "equipment": equipment}


async def verify(args):
    from agents.source_curation import curate_source
    from knowledge.source_library import SourceLibrary
    report = {"schema": "source_curation_verification.v1", "physical_actuation": False,
        "model_startup": False, "evidence_class": "software_verification",
        "public_source_included": True, "backends": [], "temporary_artifacts_removed": False}
    started = monotonic()
    artifacts_dir = getattr(args, "artifacts_dir", None)
    with fixture_workspace(artifacts_dir=artifacts_dir) as root:
        download_paper(root / "inputs")
        async def verify_backend(backend):
            backend_root = root / backend
            ctx = registered_context(backend, backend_root)
            if not await ctx.selected_model_loaded("knowledge_query"):
                raise RuntimeError(f"Registered {backend} model unavailable; no model startup attempted")
            library = SourceLibrary(backend_root / "library", root / "inputs")
            library.scan()
            scan = library.scan()
            expected_names = {p.name for p in (root / "inputs").iterdir() if p.is_file()}
            discovered_names = {Path(p).name for s in scan["sources"] for p in s["paths"]}
            row = {"backend": backend, "cases": [], "consumers": [],
                   "all_inputs_discovered": expected_names == discovered_names,
                   "discovery_error_count": len(scan.get("errors", []))}
            report["backends"].append(row)
            ids = {}
            for source in scan["sources"]:
                names = {Path(p).name for p in source["paths"]}
                ids.update({name: source["source_id"] for name in names})
                source_id = source["source_id"]
                print(json.dumps({"backend": backend, "phase": "curation", "case": source["format"]}), flush=True)
                tick = monotonic()
                calls_before = ctx.primary_backend.calls
                result = await curate_source(library, source_id, ctx, timeout_s=args.timeout_s)
                (backend_root / f"{source_id}.json").write_text(json.dumps(result, ensure_ascii=False, default=str))
                invalid = "unreadable.pdf" in names
                passed = result.get("status") in {"failed", "needs_review"} if invalid else result.get("status") == "ready"
                facts = {}
                note_count, page_count = 0, None
                if not invalid and passed:
                    extracted = library.extract(source_id)
                    text = extracted["markdown"]
                    expected = []
                    if "conditions.md" in names:
                        expected = ["17.5", "9.25", "not interchangeable"]
                    elif "long.md" in names:
                        expected = ["TAIL-EVIDENCE", "73 days"]
                    elif "publication.pdf" in names:
                        expected = ["225 pages", "177 s", "OCR is disabled", "Appendix", "216 dpi"]
                    elif "multilingual.txt" in names:
                        expected = ["42초", "未确认"]
                    elif "structured.csv" in names:
                        expected = ["17.5", "9.25", "drift_mm"]
                    elif "layout.docx" in names:
                        expected = ["42", "Duration is conditional", "Reference revision A"]
                    else:
                        expected = ["42"]
                    facts = {token: token in text for token in expected}
                    hits = library.search("", scope={"source_id": source_id})["hits"]
                    note_count, page_count = len(hits), len(extracted.get("pages", []))
                    facts["single_consolidated_output"] = len(hits) == 1
                    if "publication.pdf" in names:
                        pages = extracted.get("pages", [])
                        facts["page_files_complete"] = len(pages) == 9 and all(
                            (Path(extracted["path"]).parent / page["path"]).is_file() for page in pages)
                    passed = passed and all(facts.values())
                item = {"format": source["format"], "expected_failure": invalid,
                    "public_source": "publication.pdf" in names, "expectation_met": bool(passed),
                    "full_text_checks_passed": all(facts.values()) if facts else None,
                    "status": result.get("status"), "error": result.get("error"),
                    "model": result.get("model") if ctx.primary_backend.calls > calls_before else None,
                    "tool_calls": len(result.get("trace", [])),
                    "model_calls": ctx.primary_backend.calls - calls_before,
                    "published_notes": note_count, "extracted_pages": page_count,
                    "duration_s": round(monotonic() - tick, 3)}
                row["cases"].append(item)
                print(json.dumps(item, default=str), flush=True)
            for name, question, required in [
                ("conditions.md", "What drift is allowed for variant Azure, in which units and conditions?", ["17.5", "mm"]),
                ("publication.pdf", "In the source's performance benchmark, how many pages were used and was OCR enabled?", ["225", "ocr"]),
                ("long.md", "What is the retention window stated in the final qualification?", ["73", "days"]),
            ]:
                result = await verify_consumers(ctx, library, backend_root, ids[name], question=question,
                    required=required, qualification="ocr_disabled" if name == "publication.pdf" else None)
                # Detailed traces are inspected locally, never copied to the durable report.
                (backend_root / f"consumer-{name}.json").write_text(json.dumps(result, ensure_ascii=False, default=str))
                result.pop("decision")
                result.pop("equipment")
                result["public_source"] = name == "publication.pdf"
                row["consumers"].append(result)
                print(json.dumps({"backend": backend, "consumer_result": result}, default=str), flush=True)
            row["deduplication"] = ids["conditions.md"] == ids["duplicate.md"]
            row["unchanged_ready_not_pending"] = all(
                item["source_id"] not in library.scan()["pending_ids"]
                for item in library.status()["sources"] if item["status"] == "ready")
        # Providers have separate libraries/leases; each keeps its own serial document order.
        # TaskGroup settles/cancels both before the shared temporary inbox is removed.
        async with asyncio.TaskGroup() as group:
            for backend in dict.fromkeys(args.backend or ["openai", "vllm"]):
                group.create_task(verify_backend(backend))
        report["backends"].sort(key=lambda row: row["backend"])
        report["duration_s"] = round(monotonic() - started, 3)
    report["temporary_artifacts_removed"] = not root.exists()
    if artifacts_dir:
        archive = Path(artifacts_dir).expanduser().resolve() / f"{root.name}-archive"
        report["validation_archive"] = str(archive)
        report["validation_artifacts_retained"] = archive.is_dir()
    report["ok"] = report["temporary_artifacts_removed"] and all(
        all(c["expectation_met"] for c in b["cases"])
        and all(c["knowledge_bo"] and c["equipment_decision"] for c in b["consumers"])
        and b["all_inputs_discovered"] and not b["discovery_error_count"]
        and b["deduplication"] and b["unchanged_ready_not_pending"] for b in report["backends"])
    if args.output:
        target = Path(args.output)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str) + "\n")
    if artifacts_dir:
        (archive / "verification-report.json").write_text(
            json.dumps(report, ensure_ascii=False, indent=2, default=str) + "\n")
    print(json.dumps({"ok": report["ok"], "temporary_artifacts_removed": report["temporary_artifacts_removed"],
                      "duration_s": report["duration_s"]}), flush=True)
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--backend", action="append", choices=["openai", "vllm"])
    parser.add_argument("--timeout-s", type=float, default=300)
    parser.add_argument("--output", help="Sanitized aggregate report only")
    parser.add_argument("--artifacts-dir", help="Retain complete validation copies outside the ATR repository")
    options = parser.parse_args()
    if not options.execute:
        parser.error("Use --execute to opt in to registered model calls; data stays isolated from production")
    raise SystemExit(0 if asyncio.run(verify(options))["ok"] else 1)
