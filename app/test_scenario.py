"""Automatic operator input; never dispatches agents or changes execution state."""
from __future__ import annotations

import asyncio
from copy import deepcopy
import json


class TestScenarioInput:
    """One session-scoped input producer for the ordinary planning chat."""

    __test__ = False

    def __init__(self, controller):
        self.controller = controller
        self.task = None
        self._submitting = None
        self.status = "idle"
        self.admission_task = None
        self.admission_run_id = None

    @property
    def active(self):
        return self.task is not None and not self.task.done()

    def is_submitting(self):
        try:
            return self._submitting is not None and self._submitting is asyncio.current_task()
        except RuntimeError:
            return False

    def cancel(self):
        if self.active:
            self.task.cancel()
        self.status = "stopped"

    def start(self, *, goal, constraints, trigger_message=""):
        if self.active:
            return False
        self.goal = goal
        self.trigger_message = trigger_message
        self.constraints = deepcopy(constraints)
        self.session_id = self.controller._planning_session_id
        self.admission_task = None
        self.admission_run_id = None
        self._revision = self.controller._test_input_revision
        state = self.controller._state
        self._start_stop_flags = (state.stop_requested, state.safe_stop_requested)
        self.status = "running"
        self.task = asyncio.create_task(self._run())
        return True

    def track_admission(self, task):
        """Retain this input's admitted scope after the controller clears its task."""
        self.admission_task = task
        revision = self.controller._test_input_revision
        session = self.session_id
        def completed(done):
            c = self.controller
            if (done is self.admission_task and not done.cancelled()
                    and revision == c._test_input_revision and session == c._planning_session_id):
                self.admission_run_id = c._state.run_id
        task.add_done_callback(completed)

    def _stopped(self):
        s = self.controller._state
        flags = (s.stop_requested, s.safe_stop_requested)
        if not any(flags):
            self._start_stop_flags = flags
        return (s.emergency_stop_requested
                or getattr(self, "_revision", self.controller._test_input_revision) != self.controller._test_input_revision
                or (any(flags) and flags != getattr(self, "_start_stop_flags", (False, False))))

    async def _submit(self, message, *, initial=False, pending=None):
        c = self.controller
        if c._planning_session_id != self.session_id or self._stopped():
            return {"ok": False}
        self._submitting = asyncio.current_task()
        try:
            return await c.planning_message(message=message,
                constraints={"live_runtime_followup_queue_only": True} if pending and (c._planning_pending_request() or {}).get("kind") != "conversation" else {},
                session_id=self.session_id, expected_pending_id=pending)
        finally:
            self._submitting = None

    async def answer_pending(self, pending):
        """Answer in natural language using only private scenario facts."""
        c = self.controller
        if pending.get("kind") not in {"planning_boundary", "runtime_boundary", "conversation"}:
            return False
        before = c._planning_intake_scope()
        facts = {"goal": self.goal, **{k: v for k, v in self.constraints.items()
                 if k not in {"print", "ejection", "execution_policy", "test_mode_profile"}
                 and not any(word in k.lower() for word in ("confirm", "allow", "password", "token", "secret"))}}
        prompt = json.dumps({"operation": "test_scenario_reply", "pending_request": pending,
            "available_scenario_inputs": facts,
            "conversation": c._planning_memory_context(limit=12, max_chars=900),
            "trigger_message": getattr(self, "trigger_message", ""),
            "instruction": "Act as the researcher in this test conversation, in the language of the trigger message. "
                "Write a short natural reply to the orchestrator's last question, using only requested facts from available_scenario_inputs. "
                "Do not dump the scenario, JSON, field names, internal mode keys, bullets, emoji or status tags. "
                "For a conversation invitation agree to plan; for condition questions supply only the requested values. "
                "The research goal is available_scenario_inputs.goal: preserve that scientific objective, "
                "including SEA and its J/g units when supplied. Agreeing to plan describes the current conversation phase, "
                "NOT a replacement goal. Never change the goal into planning-only, pre-execution validation or a dry run. "
                "For conversation run_review approve the agreed test experiment. Select fields used, or [] for simple agreement. "
                "A runtime planning_boundary/runtime_boundary is NOT permission to start a new experiment: answer factual questions only. "
                "Return wait for missing facts, device/transfer completion, safety or recovery approval, "
                "credentials, configuration changes, or a failed model decision. Never infer physical evidence. "
                "Do not invent new values or claim real actions have happened.",
            "response_schema": {"action": "reply or wait", "fields": "list of scenario keys used", "message": "natural researcher reply"}}, ensure_ascii=False)
        response, _ = await c._complete_live_planning_prompt(prompt=prompt)
        choice = json.loads(response.text)
        fields = choice.get("fields")
        if (choice.get("action") != "reply" or not isinstance(fields, list)
                or not all(isinstance(k, str) and k in facts for k in fields)):
            return False
        if pending["kind"] != "conversation" and not fields:
            return False
        if before != c._planning_intake_scope() or self._stopped():
            return False
        from app.planning_dialogue import plain_message
        if pending["kind"] == "conversation":
            reply = plain_message(choice.get("message"))
        else:
            # Runtime holds can unblock physical stages. Only the model-selected
            # existing facts enter that route, never its free-form assertions.
            def factual_text(value):
                if isinstance(value, (str, int, float)) and not isinstance(value, bool):
                    return str(value)
                if isinstance(value, list) and all(type(v) in (int, float) for v in value):
                    return ", ".join(map(str, value))
                raise ValueError("Unsupported runtime fact shape")
            reply = " ".join(f"{key.replace('_', ' ').capitalize()} is {factual_text(facts[key])}." for key in fields)
        result = await self._submit(reply, pending=pending["pending_id"])
        return bool(result.get("ok"))

    async def _run(self):
        c = self.controller
        try:
            while c._planning_request_lock.locked():
                await asyncio.sleep(0.05)
            from app.planning_dialogue import plain_message
            response, _ = await c._complete_live_planning_prompt(prompt=json.dumps({
                "operation": "test_scenario_opening", "trigger_message": self.trigger_message,
                "instruction": "Speak as a researcher, not the orchestrator. In the trigger message's language, "
                    "ask which experiment packages are currently available. One short natural question only. "
                    "Do not provide research conditions, JSON, mode identifiers, status tags, bullets or emoji. Return plain text only."}, ensure_ascii=False))
            result = await self._submit(plain_message(response.text), initial=True)
            if not result.get("ok"):
                self.status = "waiting"
                return
            run_id = c._state.run_id
            answered = set()
            conversation_turns = 0
            while not self._stopped() and c._planning_session_id == self.session_id:
                if c._state.run_id != run_id:
                    # Only our own shared admission task may allocate the run
                    # (e.g. when activating a confirmed Setup snapshot).
                    if (c._state.run_id != self.admission_run_id
                            and (self.admission_task is None or c._planning_handoff_task is not self.admission_task)):
                        break
                    run_id = c._state.run_id
                pending = c._planning_pending_request()
                if pending and pending["pending_id"] not in answered:
                    answered.add(pending["pending_id"])
                    self.status = "running" if await self.answer_pending(pending) else "waiting"
                    if pending["kind"] == "conversation":
                        conversation_turns += 1
                        if self.status == "waiting" or conversation_turns >= 24:
                            self.status = "waiting"
                            return
                        continue
                if not c._planning_handoff_active() and not (c._run_task and not c._run_task.done()):
                    self.status = "waiting" if c._planning_pending_request() else "complete"
                    return
                await asyncio.sleep(0.25)
            self.status = "stopped"
        except asyncio.CancelledError:
            self.status = "stopped"
            raise
        except Exception as exc:
            self.status = "failed"
            await c._append_planning_message({"role": "system", "ok": False,
                "content": f"Automatic test input paused: {type(exc).__name__}. Continue through chat.",
                "input_source": "test_scenario"})
