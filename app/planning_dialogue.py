"""LLM-led research conversation; execution stays in controller admission."""
from copy import deepcopy
import json
import math
import re
from uuid import uuid4
from utils.gyroid_contract import BOUNDS, POLICY, parameter_space, validate_candidate

from agents.core.knowledge.context import build_reference_context, mark_reference_delivered, record_reference_use

PREFIX = "conversation.input."


def missing_inputs(values):
    missing = [key for key in ("goal", "material", "specimen_size_mm") if not values.get(key)]
    if not (values.get("geometry_type") or values.get("experiment_domain")):
        missing.append("geometry_type or experiment_domain (either one, not both)")
    if "gyroid" in str(values.get("geometry_type") or values.get("experiment_domain") or "").lower():
        missing.extend(key for key in BOUNDS if values.get(key) is None)
    return missing


def plain_message(value):
    """Reject internal envelopes in the public chat, rather than prettifying them."""
    if not isinstance(value, str) or not value.strip() or len(value) > 1800:
        raise ValueError("Expected a short conversational message")
    if any(marker in value for marker in ("```", "[Automatic test input]", '"constraints"', '"operation"')):
        raise ValueError("Internal payload is not a conversational message")
    if value.lstrip().startswith(("{", "[")) or re.search(r"(?m)^\s*(?:[-*#]|\d+[.)])\s", value):
        raise ValueError("Use plain conversational paragraphs")
    return value.strip()


class ResearchDialogue:
    """Session-scoped dialogue decisions; no bridge access or alternate pipeline."""

    def __init__(self, controller):
        self.controller = controller
        self.session_id = controller._planning_session_id
        self.pending = None
        self.language = None
        self.test_policy = {}
        controller._research_dialogue = self

    def values(self):
        values = {}
        for block in self.controller._setup_store().snapshot()["blocks"]:
            if block["topic_key"].startswith(PREFIX):
                values.update(deepcopy(block["draft_values"]))
        return values

    def context(self):
        c = self.controller
        catalog = c._planning_setup_catalog()
        owners = catalog.describe(c._state, c._deps.agent_context)
        active = set(c._deps.agent_registry.names())
        graph_owners = {row["owner"] for row in owners} & active
        owners = [{k: row[k] for k in ("owner", "stage", "role", "availability")}
                  for row in owners if row["owner"] in active]
        modules = [{k: m.describe().get(k) for k in ("id", "agent_name", "capabilities", "contract_version")}
                   for m in c._deps.agent_registry.modules() if m.agent_name in graph_owners]
        return {"graph": {"id": catalog.graph_config.id, "label": catalog.graph_config.name},
                "owners": owners, "agent_packages": modules,
                "state": c._planning_state_context(),
                "availability_note": "Registered capabilities are not proof of connected or idle hardware. Only supplied fresh owner evidence can establish readiness."}

    def fields(self):
        """Use installed Design input names; never accept transport/approval flags."""
        c = self.controller
        try:
            agent = c._deps.agent_registry.get("design_agent")
            defaults = agent.DEFAULT_CONSTRAINTS
            geometries = list(agent.SUPPORTED_GEOMETRIES)
        except (KeyError, AttributeError):
            defaults, geometries = {}, []
        fields = {key: {"type": type(value).__name__} for key, value in defaults.items()}
        fields.update(goal={"type": "str"}, specimen_size_mm={"type": "list"},
                      geometry_type={"type": "str", "enum": geometries},
                      experiment_domain={"type": "str"}, objective_type={"type": "str"},
                      objective_direction={"type": "str", "enum": ["maximize", "minimize"]})
        # Minimal controller admission fields remain valid in test-only registries.
        fields.setdefault("material", {"type": "str"})
        fields.update({key: {"type": "list", "description": "Continuous [lower, upper] bounds"} for key in BOUNDS})
        fields.pop("relative_density", None)
        fields.pop("relative_density_bounds", None)
        return fields

    def _updates(self, updates, message, intent):
        if not isinstance(updates, list) or (updates and intent in {"question", "out_of_scope", "unclear"}):
            raise ValueError("A question cannot change experiment inputs")
        fields = self.fields()
        result = {}
        for update in updates:
            if not isinstance(update, dict) or set(update) != {"field", "value", "source_quote"}:
                raise ValueError("Invalid input provenance")
            key, value, quote = update["field"], update["value"], update["source_quote"]
            if key not in fields or not isinstance(quote, str) or not quote.strip() or quote.casefold() not in message.casefold():
                raise ValueError("Input must be grounded in this operator message")
            descriptor = fields[key]
            if type(value).__name__ != descriptor["type"] and not (descriptor["type"] == "float" and type(value) is int):
                raise ValueError("Invalid input type")
            if isinstance(value, str) and (not value.strip() or len(value) > 500):
                raise ValueError("Invalid input text")
            if type(value) in (int, float) and not math.isfinite(value):
                raise ValueError("Non-finite input")
            if descriptor.get("enum") and value not in descriptor["enum"]:
                raise ValueError("Unsupported input option")
            if key in {"specimen_size_mm", "max_specimen_size_mm", "utm_fixture_limit_mm"}:
                if not isinstance(value, list) or len(value) != 3 or not all(type(x) in (int, float) and math.isfinite(x) and x > 0 for x in value):
                    raise ValueError("Invalid dimensions")
            result[key] = value
        parameter_space(result)
        validate_candidate(result)
        return result

    async def turn(self, message, *, intent, goal=None, constraints=None, scope=None, editing=False):
        c = self.controller
        current = self.values()
        before = scope or c._planning_intake_scope()
        reference = build_reference_context(c._deps.agent_context, consumer="orchestrator_agent", query=message,
            include_private=True, run_id=c._state.run_id, loop_id=str(c._state.loop_count))
        allowed_actions = ["answer", "invite", "collect", "review", "decline"]
        if intent == "question":
            allowed_actions = ["answer"] if self.pending else ["answer", "invite", "decline"]
        elif intent in {"unclear", "out_of_scope"}:
            allowed_actions = ["answer", "decline"]
        elif not editing and intent == "confirm_pending" and (self.pending or {}).get("purpose") == "run_review":
            allowed_actions.append("execute")
        if not editing and not missing_inputs(current) and intent in {"confirm_pending", "change_setup"}:
            allowed_actions.remove("collect")
        packet = {"operation": "research_conversation", "message": message, "semantic_intent": intent,
            "allowed_actions": allowed_actions,
            "admission_status": {"missing_inputs": missing_inputs(current),
                "instruction": "If missing_inputs is empty, research conditions are complete: review or answer, do not request optional fields. geometry_type and experiment_domain are alternatives."},
            "language": self.language, "pending": self.pending, "agreed_inputs": current, "editing_only": bool(editing),
            "selected_input": {k: editing[k] for k in ("block_id", "revision", "topic_key", "draft_values")} if editing else None,
            "input_contract": self.fields(), "gyroid_research_policy": POLICY, "registered_context": self.context(),
            "conversation": c._planning_memory_context(limit=10, max_chars=500),
            "reference_only": reference["pack"], "selected_test_policy": self.test_policy,
            "policy": "Converse as AX4LAB's orchestrator, not as a form or a machine log. Determine the language from the user's messages and continue in it (ko/en); a greeting alone is bilingual. "
                "Answer in one or two short sentences (at most 90 words); do not repeatedly announce non-execution or repeat mode/readiness caveats. "
                "Explain the experiment enabled by the ACTIVE GRAPH as a whole, based on its owners and supplied knowledge. Agent packages are components, NOT separate experiment packages. "
                "Describe the experiment and principal equipment in everyday terms, not a catalog of software stages or internal identifiers. "
                "Distinguish an available workflow from live device readiness. Do not invent another package or claim connection readiness. "
                "For package questions answer briefly and optionally invite the researcher to plan that experiment (action invite). Agreement to that invitation begins condition collection, NOT execution. "
                "Action must match the answer: invite when asking whether to plan; collect when asking for values; review when asking whether to run; execute only on execution consent; answer for explanation without a new question. "
                "Example: available-package question -> action invite, answer briefly describes the available experiment and asks whether to plan, updates []. "
                "Example: yes to begin_planning -> action collect, ask the goal and material, updates []. "
                "Example: PLA in response to a material question -> action collect or review with an update {field:material,value:PLA,source_quote:PLA}. "
                "Ask one or two relevant questions at a time, dynamically based on the registered input contract and agreed_inputs. Do not assume saved defaults are the user's research choices. "
                "For initial Design admission collect goal, material, specimen_size_mm, and geometry_type or experiment_domain. For gyroid also collect both continuous ranges in gyroid_research_policy. When required inputs are present, REVIEW; explain the mandatory 0.4 mm wall rejection rule. Do not ask again for accepted inputs. "
                "Extract updates only from actual statements in this message with exact source_quote; never fill unstated values. Questions never change values or authorize execution. "
                "Accept terse answers using the preceding question. Handle system questions mid-discussion and preserve the pending question/inputs. "
                "When required values are agreed, summarize them briefly and ask whether to execute (action review). Execute ONLY with a pending run_review and current execution consent, even if all values were supplied in a first start request. Planning consent never means execution. Editing_only forbids execution. "
                "Do not use JSON, code, internal key names, headers, bullets, emoji, asterisks, arrows or bracketed status tags in answer. Use short natural paragraphs. "
                "Do not request raw printer/bridge settings or fixed trigger keywords. Do not claim measurements, transfers, completed work, or tool execution. "
                "Return the structured response privately; answer alone is displayed.",
            "response_schema": {"action": "answer|invite|collect|review|execute|decline", "answer": "short natural reply",
                "language": "ko|en", "updates": [{"field": "input_contract key", "value": "typed value", "source_quote": "exact text from message"}]}}
        try:
            mark_reference_delivered(c._deps.agent_context, reference)
            for attempt in range(2):
                response, _ = await c._complete_live_planning_prompt(prompt=json.dumps(packet, ensure_ascii=False))
                decision = json.loads(response.text)
                if not isinstance(decision, dict) or decision.get("action") in allowed_actions or attempt:
                    break
                # Correct the model decision before recording messages or values;
                # never translate a planning request into execution ourselves.
                packet["correction"] = {"rejected_action": decision.get("action"),
                    "reason": "Choose only from allowed_actions. Execution requires current execution consent. Questions cannot advance planning. Completed inputs do not require optional fields. If execution is unavailable, review agreed conditions and ask for approval instead; never say a run has started."}
            if not isinstance(decision, dict):
                raise ValueError("Invalid dialogue response")
            if set(decision) != {"action", "answer", "language", "updates"} or decision["language"] not in {"ko", "en"}:
                raise ValueError("Invalid dialogue response")
            action = decision["action"]
            if action not in {"answer", "invite", "collect", "review", "execute", "decline"}:
                raise ValueError("Invalid dialogue action")
            answer = plain_message(decision["answer"])
            updates = self._updates(decision["updates"], message, intent)
            if editing and not set(updates) <= set(editing["draft_values"]):
                raise ValueError("Edit only the selected research input")
            pending = self.pending
            if action == "execute" and (editing or not (intent == "confirm_pending" and pending and pending["purpose"] == "run_review")):
                raise ValueError("No current execution consent")
            if action not in allowed_actions:
                raise ValueError("Action does not match the current conversation state")
            if action in {"collect", "review"} and intent == "question":
                raise ValueError("Questions do not advance input collection")
            if intent == "question" and pending and action != "answer":
                raise ValueError("A question must preserve the pending research decision")
            if intent in {"unclear", "out_of_scope"} and action not in {"answer", "decline"}:
                raise ValueError("No actionable research request")
            if before != c._planning_intake_scope():
                raise ValueError("Conversation scope changed")
            merged = {**current, **updates}
            # Automatic operator prose is model output, not authority to change
            # the scenario's objective. Reject drift before writing Setup/admission.
            driver = c._test_scenario
            if driver.is_submitting() and "goal" in updates:
                from utils.research_objective import uses_sea
                if uses_sea({}, getattr(driver, "goal", "")) and not uses_sea({}, updates["goal"]):
                    raise ValueError("Automatic test reply changed the SEA research objective")
            parameter_space(merged)
            validate_candidate(merged)
            if action in {"execute", "review"} and missing_inputs(merged):
                raise ValueError("Required research inputs are missing")
            self.language = decision["language"]
            for key, value in updates.items():
                store = c._setup_store()
                block = store.ensure_block(PREFIX + key, c._deps.orchestrator_agent_name, {key: None})["block"]
                if block["draft_values"].get(key) != value:
                    store.propose(block["block_id"], block["revision"], {key: value}, str(uuid4()))
            recorded_entry = c._record_planning_message({"role": "operator", "content": message, "conversation_input": True,
                "goal": merged.get("goal"), "constraints": {k:v for k,v in updates.items() if k != "goal"}})
            if action in {"invite", "collect", "review"}:
                purpose = {"invite": "begin_planning", "collect": "provide_inputs", "review": "run_review"}[action]
                self.pending = {"kind": "conversation", "pending_id": str(uuid4()), "purpose": purpose,
                    "description": answer, "request": {"agreed_inputs": merged}}
            elif action == "decline":
                self.pending = None
            # A system question/answer retains the prior pending request unchanged.
            committed_scope = c._planning_intake_scope()
            record_reference_use(c._deps.agent_context, reference, answer, citation_ids=[])
            await c._append_planning_message({"role": "orchestrator", "content": answer,
                "model": response.model, "ok": True, "requires_design_inputs": action == "collect"})
            await c.emit_runtime_event(event_type="planning_setup_changed", message="Conversation inputs updated.",
                payload={"setup": c._planning_setup_projection()})
        except (ValueError, TypeError, KeyError, RuntimeError) as exc:
            self.last_error = {"reason": str(exc), "model_response": getattr(locals().get("response"), "text", "")}
            failure = "Could not complete this conversation turn. Please retry."
            if self.session_id == c._planning_session_id:
                if "recorded_entry" not in locals():
                    c._record_planning_message({"role": "operator", "content": message, "conversation_input": True})
                await c._append_planning_message({"role": "orchestrator", "content": failure, "ok": False})
            return {"ok": False, "message": failure,
                    "error_type": type(exc).__name__, "session": c.planning_snapshot()}
        if action == "execute":
            if committed_scope != c._planning_intake_scope():
                return {"ok": False, "message": "Request changed before execution; review the current conversation."}
            self.pending = None
            admitted = {**(constraints or {}), **{k:v for k,v in merged.items() if k != "goal"}, **self.test_policy}
            return await c._planning_message_locked(message=message, goal=merged.get("goal") or goal,
                constraints=admitted, session_id=c._planning_session_id,
                intake={"intent": "start_run"}, intake_scope=c._planning_intake_scope(), recorded_entry=recorded_entry)
        return {"ok": True, "message": answer, "session": c.planning_snapshot()}


def dialogue_for(controller):
    current = getattr(controller, "_research_dialogue", None)
    if current is None or current.session_id != controller._planning_session_id:
        current = ResearchDialogue(controller)
    return current
