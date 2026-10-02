"""Synthetic, non-actuating decision transport reused by Task 5 provider probes."""
from __future__ import annotations

import json
from types import SimpleNamespace


class KnowledgeDeliveryTransport:
    force_real_llm_in_test = True
    active_backend = "vllm"
    backend_fallbacks = {"vllm": "vllm"}
    tools = None

    def __init__(self, service, *, query_case: str) -> None:
        self.knowledge_service = service
        self.knowledge_principal = None
        self.query_case = query_case
        self.prompts = []
        self._knowledge_step = 0

    async def complete(self, task_type, prompt, **kwargs):
        self.prompts.append((task_type, prompt, kwargs))
        if task_type == "design_reasoning":
            response = {"tool": "return_to_owner", "arguments": {}, "reason": "Synthetic owner review.", "evidence_refs": ["context:request"]}
        elif task_type == "specimen_reasoning":
            response = {"tool": "return_to_owner", "arguments": {}, "reason": "Synthetic owner review.", "evidence_refs": ["context:request"]}
        elif task_type == "vision_observation":
            context = json.loads(prompt.split("\nCONTEXT:\n")[-1])
            response = {"tool": "return_to_owner", "arguments": {"contract_id": context["contract_id"]}, "reason": "Synthetic owner review.", "evidence_refs": ["context:task"]}
        elif task_type == "manipulation_plan":
            context = json.loads(prompt.split("\nCONTEXT:\n")[-1])
            response = {"tool": "return_to_owner", "arguments": {"proposal_id": context["proposal_id"]}, "reason": "Synthetic owner review.", "evidence_refs": ["task:configured"]}
        elif task_type == "equipment_workflow_decision":
            context = json.loads(prompt.split("CONTEXT:\n")[-1])
            tool = "request_operator" if "request_operator" in context["tools"] else next(iter(context["tools"]))
            response = {"tool": tool, "arguments": context["tools"][tool], "reason": "Synthetic owner review.", "evidence_refs": context["evidence_refs"]}
        elif task_type == "analysis_reasoning":
            context = json.loads(prompt)
            response = {"option_id": context["response_options"][0]["option_id"], "reason": "Synthetic evidence choice."}
        elif task_type == "orchestrator_plan":
            context = json.loads(prompt)
            response = {"tool": "defer", "arguments": {"condition": "Synthetic owner review"}, "reason": "Synthetic owner review.", "evidence_refs": list(context["evidence"])}
        elif task_type == "bo_policy":
            response = {"tool": "return_to_owner", "arguments": {}, "reason": "Synthetic owner review.", "evidence_refs": ["context:request"]}
        elif task_type == "knowledge_query":
            self._knowledge_step += 1
            response = ({"tool": "inspect_evidence", "arguments": {}} if self._knowledge_step == 1 else
                        {"tool": "publish_context", "arguments": {"summary": "", "source_ids": [], "no_knowledge_reason": "Synthetic no reusable context."}})
        elif task_type == "guardian_reasoning":
            return SimpleNamespace(text="Synthetic policy note.", model="synthetic", raw={})
        else:
            raise AssertionError(task_type)
        return SimpleNamespace(text=json.dumps(response), model="synthetic", raw={})


def reference_pack_from_prompt(task_type: str, prompt: str) -> dict:
    """Extract the real packet field at each consumer's established prompt shape."""
    if task_type in {"design_reasoning", "specimen_reasoning"}:
        return json.loads(prompt[prompt.index('{"context"'):])["context"]["reference_only"]
    if task_type in {"vision_observation", "manipulation_plan", "equipment_workflow_decision"}:
        return json.loads(prompt.split("CONTEXT:\n")[-1])["reference_only"]
    if task_type in {"analysis_reasoning", "orchestrator_plan", "knowledge_query"}:
        value = json.loads(prompt)
        return (value.get("reference_only") or value.get("context", {}).get("reference_only") or value["intro"]["reference_only"])
    if task_type == "bo_policy":
        return json.loads(prompt[prompt.index('{"context"'):])["context"]["reference_only"]
    if task_type == "guardian_reasoning":
        marker = "reference_only="
        return json.loads(prompt.split(marker, 1)[1])
    raise AssertionError(task_type)
