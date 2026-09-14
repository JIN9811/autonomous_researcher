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
            return await c.planning_message(message=message, goal=self.goal,
                constraints=deepcopy(self.constraints) if initial else {"live_runtime_followup_queue_only": True},
                session_id=self.session_id, expected_pending_id=pending)
        finally:
            self._submitting = None

    async def answer_pending(self, pending):
        """Choose existing scenario facts; free-form assertions cannot be submitted."""
        c = self.controller
        if pending.get("kind") not in {"planning_boundary", "runtime_boundary"}:
            return False
        before = c._planning_intake_scope()
        facts = {"goal": self.goal, **{k: v for k, v in self.constraints.items()
                 if k not in {"print", "ejection", "execution_policy", "test_mode_profile"}
                 and not any(word in k.lower() for word in ("confirm", "allow", "password", "token", "secret"))}}
        prompt = json.dumps({"operation": "test_scenario_reply", "pending_request": pending,
            "available_scenario_inputs": facts,
            "instruction": "Select only existing scenario input keys that answer the current question. "
                "Return wait for missing facts, device/transfer completion, safety or recovery approval, "
                "credentials, configuration changes, or a failed model decision. Never infer physical evidence. "
                "No free-form answer, tool call, new value or execution approval is permitted.",
            "response_schema": {"action": "reply or wait", "fields": list(facts)}}, ensure_ascii=False)
        response, _ = await c._complete_live_planning_prompt(prompt=prompt)
        choice = json.loads(response.text)
        fields = choice.get("fields")
        if (choice.get("action") != "reply" or not isinstance(fields, list) or not fields
                or not all(isinstance(k, str) and k in facts for k in fields)):
            return False
        if before != c._planning_intake_scope() or self._stopped():
            return False
        reply = "[Automatic test input] 요청한 시나리오 입력값입니다. 현재 요청을 검토해주세요.\n" + json.dumps(
            {k: facts[k] for k in fields}, ensure_ascii=False)
        result = await self._submit(reply, pending=pending["pending_id"])
        return bool(result.get("ok"))

    async def _run(self):
        c = self.controller
        try:
            while c._planning_request_lock.locked():
                await asyncio.sleep(0.05)
            mode = self.constraints.get("printer_test_path", "selection pending")
            result = await self._submit(
                "[Automatic test input] 테스트 모드, " + mode + ". 아래 시나리오로 실험 수행.\n" +
                json.dumps({"goal": self.goal, "constraints": self.constraints}, ensure_ascii=False), initial=True)
            if not result.get("ok"):
                self.status = "waiting"
                return
            run_id = c._state.run_id
            answered = set()
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
