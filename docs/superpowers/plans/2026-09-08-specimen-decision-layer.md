---
doc_type: plan
subtype: implementation
status: active
authority: execution
execution_status: completed
governing_design: docs/superpowers/specs/2026-09-07-five-area-agent-restructuring-contract-design.md
audience: [developer, maintainer]
scope: [agents, specimen, decision_tools]
summary: Bounded fabrication suitability decisions and tool dispatch on the existing printer route.
source_of_truth:
  - agents/specimen_agent.py
  - agents/specimen_decision.py
last_verified: 2026-09-08
verified_against: working-tree
related_docs:
  - docs/agents/specimen_agent.md
  - docs/superpowers/specs/2026-09-07-five-area-agent-restructuring-contract-design.md
supersedes: []
---

# Specimen Decision Layer Implementation Plan

> For agentic workers: use test-driven implementation and verification before completion.

## Goal and Constraints

Design의 JSON 사양을 받아 제작 적합성을 판단하고, LLM의 제한된 도구 호출로
기존 제작 경로를 실행한다. 실제 장비는 이번 작업에서 구동하거나 연결하지 않는다.
기존 작업 디렉터리에서 수정하며 커밋·푸시는 별도 요청 전 수행하지 않는다.

- `experiment.evaluate → printer.prepare → provider` 및 기존 모드, 승인,
  슬라이싱, 출력, 오토이젝션, 완료 판정 경로를 유지한다.
- 모델은 사양, 장비 연결 정보, G-code, 승인 조건을 변경할 수 없다.
- 결정층은 근거 조회 / 제작 실행 / 소유자 반환만 제공한다. 모든 단계에 LLM을 넣지 않는다.
- Geometry 및 제조성 검사는 코드 소유 필수 선행 조건이다.
- 모델 오류·시간초과·잘못된 호출·정지 요청은 제작을 시작하지 않는다.
- 명시적 결정론적 TEST 하네스는 구분해서 기록하고 실제 LLM 성공으로 계산하지 않는다.

## Task 1: Decision Contract and Existing-Route Integration

1. RED: 잘못된 JSON, 미등록 도구, 사양 변경 시도, 반환, 조회 후 실행, 시간초과,
   중단, 실행 중 예외, 호출 예산, 비밀정보 제외를 테스트한다.
2. `agents/specimen_decision.py`에 `specimen_decision.v1` 및 제한된 로컬 디스패처를 구현한다.
   도구는 `inspect_fabrication_evidence`, `execute_fabrication`, `return_to_owner`이다.
3. Specimen의 기존 보고용 LLM 문구 호출을 대체한다. 준비된 기존 evaluation payload를
   실행 콜백으로 넘기며, 콜백은 정확히 한 번 기존 도구 레지스트리를 호출한다.
4. `specimen_reasoning` 역할을 기존 등록 백엔드·모듈·프롬프트·출력 예산에 연결한다.
5. GREEN: 기존 Specimen 및 모드/완료 판정 테스트와 새로운 계약 테스트를 실행한다.

## Task 2: Non-Actuating Integration Verification

1. 실제 geometry 및 검사 경로, virtual bridge 제작 경로를 검증한다.
2. installed-printer / physical-print 경로의 기존 출력·이젝션 인자를 캡처하여 유지됨을 확인한다.
   실제 장비 호출은 금지 경계로 대체한다.
3. 가능하면 등록 API와 vLLM의 실제 모델 응답을 새 판단층에 적용한다.
   서비스·GUI 설정은 변경하지 않고, 실제 사용 모델과 결과를 기록한다.
4. 기존 비구동 폐루프 테스트를 실행하여 다음 단계로의 계약을 확인한다.
   가상 결과를 물리 실증으로 표기하지 않는다.

## Task 3: Documentation and Review

1. Design과 같은 Status at a Glance, 5영역 책임 표, 워크플로, API/설정,
   안전/복구, 아티팩트/검증 구조로 현재 Specimen 문서를 갱신한다.
2. 기존 세 SVG/DOT를 새 결정층 및 기존 실행 경로와 맞춘다.
3. 공통 설계안에 Specimen 적용 상태와 검증 범위를 갱신한다.
4. 독립 코드 검토 및 변경 문서 검증 후 결과를 보고한다.

## Execution Record

- Implementation, independent review and scoped non-actuating verification completed.
  No physical validation claimed; no commit, push or live-server restart performed.
- User added multi-flow absorption coverage: Design/LHS and BO redesign contracts,
  user process/placement settings, virtual/ejection-only/physical/preflight paths,
  missing inputs, blocked decisions, and unchanged next-stage handoff contracts.

### Completed Checks

- Baseline: `.venv/bin/python -m pytest -q tests/unit/test_specimen_agent.py tests/unit/test_specimen_execution_status.py`
  → **42 passed** before implementation.
- TDD: decision tests failed on missing dispatcher before implementation; stale-mode
  regression failed before the identity guard included mode/stage; intent-projection
  test failed before print/ejection/path evidence was added. Focused tests passed
  after implementation. No hardware was invoked.
- Independent review found the stale-mode gap and an insufficient operator-size
  fixture. Both were corrected: supported `max_specimen_size_mm` is used, with
  explicit material/dimension assertions before and after Specimen dispatch.
- `node --test tests/js/specimen_lifecycle.test.cjs` → **13 passed**.
- Changed documentation passed `validate_document`; `git diff --check` passed.
- Combined regression command:

  ```bash
  .venv/bin/python -m pytest -q \
    tests/unit/test_specimen_decision.py tests/unit/test_specimen_agent.py \
    tests/unit/test_specimen_execution_status.py tests/unit/test_specimen_placement.py \
    tests/unit/test_design_agent.py tests/unit/test_design_decision.py \
    tests/unit/test_model_router.py tests/unit/test_openai_backend.py \
    tests/unit/test_langgraph_runtime.py tests/unit/test_documentation_validation.py \
    tests/integration/test_all_agent_loop_archives.py
  ```

  Result: **239 passed, 3 skipped**, 226.01 s. Existing schema/deprecation warnings
  were emitted. This is the selected regression suite, not the entire repository.
- Final fixture refinement (explicit density assertion and Bambu profile for manual
  placement) was followed by `.venv/bin/python -m pytest -q tests/unit/test_specimen_agent.py -k 'design_json or absorbs'`
  → **9 passed, 19 deselected**. No production code changed after the combined run.
- Downstream regression:

  ```bash
  .venv/bin/python -m pytest -q tests/integration/test_controller_run.py::test_safe_physical_printer_preflight_completes_twenty_redesign_cycles_without_actuation
  ```

  Result: **1 passed**, 879.33 s. The existing preflight tail completed **20 cycles**
  and applied **19 BO recommendations** to subsequent fixture specifications.
  Camera/robot/equipment execution tools were tripwires. This test uses existing
  Design/Specimen fixture stages and real downstream preflight/Analysis/CAE/BO
  handlers; it is not a 20-cycle run of the new LLM decision layer. Actual
  Design-to-Specimen handler tests and the model matrix establish that boundary
  separately. Local artifacts: `runs/run-20260908T122455Z-7359dd/`.

### Registered Model / Flow Matrix

Executed `.venv/bin/python /tmp/atr-specimen-verify-rHkdne/probe.py --matrix`.
The script uses ATR's registered builders/router and actual ModuleRuntimeContext,
Specimen handler, geometry/checks and experiment runtime. Only the printer tool is
replaced by an explicit non-actuating boundary; no hardware provider is registered.
Each case produced one valid `execute_fabrication` and exactly one boundary call.

| Incoming execution intent | API `gpt-5.5` | Registered vLLM `gemma4:31b` |
|---|---|---|
| Virtual bridge | Pass · 4.290 s | Pass · 8.554 s |
| Installed printer / ejection-only | Pass · 4.238 s | Pass · 8.110 s |
| Full physical-print intent | Pass · 3.689 s | Pass · 7.992 s |
| Installed printer / explicit no-start profile | Pass · 4.234 s | Pass · 8.128 s |
| Physical print / explicit no-start profile | Pass · 4.795 s | Pass · 8.200 s |
| Physical-print preflight | Pass · 4.263 s | Pass · 8.172 s |

These are **12/12 non-actuating model/tool-routing checks**, not physical tests or
a latency benchmark. The local model uses the existing E4B → 31B model fallback;
this does not establish E4B-primary availability. Saved production model options,
services and GUI selections were not changed. Detailed local evidence:
`/tmp/atr-specimen-verify-rHkdne/matrix-results.json` and per-case result/archives.

Design-origin regression cases separately use actual Design JSON serialization
for LHS-supplied owner-request fixtures, BO recommendation fixtures and user
material/dimension constraints. They test handoff/ownership preservation, not
new LHS/BO algorithms or unrestricted support for additional experiment types.
