---
doc_type: plan
subtype: implementation
status: draft
authority: execution
audience: [developer, maintainer]
scope: [orchestrator, experimental_setup, live_gui, agent_owned_configuration]
summary: 기존 에이전트 설정 소비 경로와 인계 경계를 보존하면서 가용 상태 기반 판단, 동적 Setup 블록, Chat 편집을 단계별로 구현한다.
execution_status: completed
governing_design: docs/superpowers/specs/2026-09-12-orchestrator-dynamic-experimental-setup-design.md
related_docs:
  - docs/superpowers/specs/2026-09-12-orchestrator-dynamic-experimental-setup-design.md
  - docs/superpowers/specs/2026-09-07-five-area-agent-restructuring-contract-design.md
  - docs/agents/orchestrator_agent.md
  - docs/agents/agent_api_connection_matrix.md
  - docs/gui/reference/live_gui_reference_alignment.md
supersedes: []
---

# Orchestrator · Dynamic Experimental Setup Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. 사용자에게 실행 방식을 확인한다. 커밋·태그·푸시는 별도 지시가 있을 때만 수행한다.

**Goal:** 가용 상태를 조회하는 Orchestrator의 실제 판단·툴콜링과, 동일 서버 상태를 공유하는 Setup 블록·Chat 편집을 기존 실행 경로에 연결한다.

**Architecture:** agent-local 판단 서비스와 owner adapter, revision 기반 Setup 저장 모듈을 분리한다. 기존 controller/runtime은 실제 인계와 세션 연결을 유지하고, UI는 서버의 블록 상태를 렌더링한다. 설정 변경은 owner의 검증·readback을 거쳐 다음 새 실행의 실제 입력에 연결한다.

**Tech Stack:** 기존 Python/Pydantic/asyncio/FastAPI, 등록 AgentContext API·vLLM, pytest, Vanilla JavaScript/Node, 기존 브라우저 테스트 도구, Markdown/Graphviz. 새 DB·프런트엔드 프레임워크·모델 서버를 도입하지 않는다.

**Spec:** [승인된 통합 상세 설계](../specs/2026-09-12-orchestrator-dynamic-experimental-setup-design.md).

## Global Constraints

다음 문장은 승인 설계의 전역 경계를 그대로 적용한다.

- “Chat은 실험을 합의하고 수정하는 공간, Experimental Setup은 현재 합의와 실제 적용 상태를 주제별 블록으로 보여주는 공간”
- “설정의 의미·검증·적용은 담당 에이전트에 남기고 실제 소비 경로까지 추적한다.”
- “Orchestrator의 bridge 직접 호출, 임의 설정 파일 편집, 자유 형식 장비 명령.”은 범위 밖이다.
- “Chat의 설정 확정과 장비 실행 승인을 동일하게 처리하는 것.”은 범위 밖이다.
- “짧은 freshness 유효시간을 갖는 관측과 그 소비 사이에는 새 LLM await를 끼우지 않는다.”
- “일반적인 ‘ㅇㅋ’를 임의 설정이나 장비 실행 승인으로 확대 해석하지 않는다.”는 상세안의 확인 계약을 따른다.
- “실행 중 수정은 원칙적으로 다음 실행 대상으로 저장한다. 현재 실행의 snapshot은 보존한다.”
- “공개 Reference·UI·피겨는 영어, 상세 설계와 구현 계획은 한국어로 유지한다.”

추가 실행 규칙:

- 장비·운영 서비스는 건드리지 않는다. 테스트 fixture는 bootstrap보다 먼저 물리 tool/service 시작을 차단한다.
- 현재 작업 트리의 문서 변경과 기존 `output/`을 보존한다. 구현 시작 시 기준 commit/status를 새로 기록한다.
- 각 Task는 red → 최소 구현 → green → diff 자체 검토로 끝낸다. 실패를 통과로 재기록하지 않는다.
- 테스트용 새 직렬 실행기를 만들지 않는다. 실제 controller와 LangGraph를 쓰고 외부 효과만 fixture로 대체한다.
- 범위가 커지면 관련 없는 에이전트·bridge를 수정하는 대신 해당 설정을 read-only로 남긴다.

## File and Interface Map

| 경로 | 책임 |
|---|---|
| 신규 `orchestrator/experimental_setup.py` | 블록·제안·revision·receipt 저장, 충돌 및 재전송 처리 |
| 신규 `agents/orchestrator_capabilities.py` | owner descriptor, 읽기 전용 가용성 투영, 등록 owner callback 조회 |
| 신규 `agents/orchestrator_decision.py` | 제한된 모델 출력 검증·도구 dispatcher, 재평가 가능한 결정 기록 |
| 신규 `orchestrator/setup_application.py` | 확정안의 owner 검증·예약·새 실행 적용·readback 조정 |
| 신규 `orchestrator/orchestrator_checkpoint.py` | 기존 완료 결과와 인계 대기/소비 상태의 idempotent 기록 |
| 기존 `agents/orchestrator_agent.py`, `agents/bo_agent.py` | Orchestrator 연결, 각 owner의 좁은 설정 공개·검증·적용 메서드 |
| 기존 `app/controller.py`, `orchestrator/langgraph_runtime.py`, `orchestrator/supervisor.py` | 실제 Chat·계획·인계 경계의 연결만 추가 |
| 기존 `app/main.py` | additive request/response, Setup action endpoint |
| 신규 `web/static/experimental_setup.js`, `web/static/experimental_setup.css` | 블록 view model·렌더·편집 맥락·접근성 |
| 기존 `web/static/planning.js`, `web/templates/planning.html` | 기존 Chat 열기·전송·snapshot/event와 새 UI 연결 |
| 기존 `graphs/modules/orchestrator/module.yaml` | 실제 제한 도구 및 판단 흐름 설명 |

새 Python 모듈은 import 시 설정 파일·네트워크·장비 상태를 읽거나 작업을 시작하지 않는다.
공통 계약 값은 JSON 호환 `dict`/`list`로 직렬화한다. 함수는 아래 지정한 이름을 사용한다.

## Initial Owner/Consumer Map

첫 write-enabled 목록은 실제 소비 경로를 확인한 아래 항목으로 한정한다.
다른 블록도 구성할 수 있지만 실행 설정을 지원하지 않으면 조회 전용임을 표시한다.

| 설정 ID / owner | 검증·적용 | 현재 소비 위치 | 첫 적용 정책 |
|---|---|---|---|
| `research.goal` / Orchestrator | 신규 owner 메서드에서 비어 있지 않은 문자열 검증 | `state.active_goal` → `build_mission_contract` 및 기존 planning prompt | 다음 새 실행; 실행 전에는 준비된 입력임을 표시 |
| `bo.parameter_space` / BO | `BOAgent.normalize_settings`, `_two_variable_parameter_space`, `BOParameterSpace.from_mapping` 재사용 | `bo_settings` → `BOAgent.initial_design_request` / `run` → 기존 Design contract | 다음 새 실행의 LHS/BO 요청 이전 |
| `bo.acquisition` / BO | 기존 defaults/normalize_settings의 허용값 사용 | `bo_settings` → `BOAgent.run` → `run_with_settings` | 다음 새 실행의 BO 입력 |
| Design·제작·관측·로봇·장비·분석 설정 | 기존 agent contract에서 공개 가능한 값만 읽기 | 현재 에이전트 입력/결과 | write 지원 없음 표시; bridge 경로 확장 금지 |

`POST /api/bo/config`는 Workspace 파일 저장 경로이며 현재 run 적용 증명이 아니다.
Setup은 그 endpoint를 호출해 Applied로 표시하지 않는다. 신규 BO owner 메서드가
검증된 새 실행의 `run_metadata['bo_settings']`를 설정하고 readback한다. 저장 위치가
metadata여도 owner 메서드·실제 BO 소비 테스트가 함께 있어야 적용 근거로 인정한다.

기존 normalizer가 입력을 clamp/기본값 대체하면 정규화된 diff를 새 제안으로 보여주고
다시 확인한다. 확인하지 않은 정규화 값으로 몰래 적용하지 않는다. BO/LHS 지정 후보,
이미 발행한 `next_design_request`와 추천 좌표는 수정하지 않는다.

## Task 1: Setup 상태·revision·보관

**Files:** Create `orchestrator/experimental_setup.py`, `tests/unit/test_experimental_setup.py`.

**Interfaces:**

- `SetupStore(root: Path, session_id: str)`; root는 기존 transcript와 같은 검증된 run directory.
- `ensure_block(topic_key: str, owner: str | list[str], values: dict) -> dict`: 없을 때만 최초 블록 생성. 내부에서 owner 목록으로 정규화한다.
- `propose(block_id: str, base_revision: int, values: dict, request_id: str) -> dict`.
- `confirm(proposal_id: str, expected_revision: int, request_id: str, target: str) -> dict`.
- `discard(proposal_id: str, expected_revision: int, request_id: str) -> dict`.
- `record_application(proposal_id: str, owner: str, receipt: dict) -> dict`.
- `snapshot() -> dict`, `proposal(proposal_id: str) -> dict`, `events(after: int) -> list[dict]`.
- 실패 타입 `SetupConflict`, `SetupValidationError`; 정상 dict에는 `revision`, `blocks`, `event_seq` 포함.

- [ ] 실패 테스트를 작성한다. 동일 topic 수정·중복 request·낡은 revision·재로딩·초안/effective 분리를 확인한다.

```python
import pytest
from orchestrator.experimental_setup import SetupStore, SetupConflict

def test_edit_keeps_identity_and_rejects_stale_writer(tmp_path):
    store = SetupStore(tmp_path, session_id="session-a")
    block = store.ensure_block("research.goal", "orchestrator_agent", {"goal": "baseline"})
    proposed = store.propose(block["block_id"], block["revision"], {"goal": "compare"}, "req-a")
    assert proposed["block_id"] == block["block_id"]
    assert store.propose(block["block_id"], block["revision"], {"goal": "compare"}, "req-a") == proposed
    with pytest.raises(SetupConflict):
        store.propose(block["block_id"], block["revision"], {"goal": "other"}, "req-b")
    restored = SetupStore(tmp_path, session_id="session-a")
    assert restored.snapshot() == store.snapshot()
```

- [ ] Run `.venv/bin/python -m pytest tests/unit/test_experimental_setup.py -q`; 새 모듈이 없어서 실패하는지 확인한다.
- [ ] 최소 구현: 하나의 `experimental_setup.json`에 상태·request 결과·이벤트를 원자적으로 저장한다. 같은 request ID로 다른 payload를 보내면 conflict다. 저장 실패 시 메모리 상태도 이전 값으로 유지한다.

```python
# 저장 순서: 같은 lock 안에서 수행하고 이벤트를 별도 파일에 먼저 쓰지 않는다.
from copy import deepcopy

candidate = deepcopy(current)
candidate["revision"] += 1
candidate["events"].append(event)
atomic_write_json(path, candidate)
current = candidate
```

`atomic_write_json(path: Path, payload: dict) -> None`을 같은 모듈 내부 helper로 정의한다.
임시 파일은 같은 부모 경로에 만들고 flush/fsync 후 replace한다. session ID를 임의 파일 경로로 사용하지 않는다.
- [ ] 추가 테스트: applying 상태 복원은 자동 적용하지 않음, 손상 파일은 빈 상태로 덮어쓰지 않음, receipt가 여러 owner의 partial을 보존함.
- [ ] 재실행해 PASS를 확인하고 해당 diff만 검토한다.

## Task 2: 에이전트 소유 설정·가용성 adapter

추가 승인 요구: 목록은 현재 main LangGraph에서 module/handler를 해석해 자동 수집한다.
`OwnerCatalog(registry, graph_config)`로 graph를 주입하고 `describe`가 graph 실행 노드와
module의 admission/result/acceptance/setup 계약을 읽는다. 노드 추가/제거·동일 owner의
복수 노드·계약 버전·시작한 run의 snapshot 보존을 테스트한다. Registry 전체 순회로
활성 목록을 만들지 않는다. fallback으로 에이전트 이름별 조건표를 만들지 않는다.
graph node의 실행 역할은 stage dispatch / 기존 pre-step / overlay로 구분한다.
overlay-only 계약은 설명용이며 실행 후보로 추가하지 않는다. module.handler 우선순위는
기존 runtime과 일치시킨다. `graphs/modules/*/module.yaml`에 additive
`orchestration_contract`를 추가할 수 있지만 이미 있는 검증만 연결하고 새 물리 gate를 만들지 않는다.

**Files:** Create `agents/orchestrator_capabilities.py`, `tests/unit/test_orchestrator_capabilities.py`; modify `agents/orchestrator_agent.py`, `agents/bo_agent.py`.

**Interfaces:**

- `OwnerCatalog(registry, graph_config)`는 graph node/module 해석 후 기존 `AgentRegistry.get` 사용. `describe(state, ctx) -> list[dict]`.
- `async inspect(owner: str, capability: str, state, ctx) -> dict`.
- `validate(owner: str, changes: dict, state) -> dict`; `async apply(owner: str, changes: dict, state, request_id: str) -> dict`; `readback(owner: str, state) -> dict`.
- 두 write-enabled owner에 `setup_descriptor()`, `validate_setup(changes, state)`, `apply_setup(changes, state, request_id)`, `read_setup(state)` 추가. 미구현 owner는 쓰기 지원 없음.
- `availability_view(report: dict, now: float) -> dict`는 만료·누락을 unknown으로 바꾸는 순수 함수.

- [ ] 다음 테스트와 미등록 owner, 범위·단위·NaN·잘못된 acquisition 거부 테스트를 추가한다.

```python
from agents.orchestrator_capabilities import availability_view

def test_expired_ready_is_unknown():
    report = {"status": "ready", "observed_at": 10.0, "expires_at": 11.0,
              "owner": "vision_agent", "capability": "inspect", "evidence_refs": ["frame-a"]}
    assert availability_view(report, now=12.0)["status"] == "unknown"
    assert report["status"] == "ready"
```

- [ ] Run `.venv/bin/python -m pytest tests/unit/test_orchestrator_capabilities.py -q`로 red 확인.
- [ ] owner 콜백만 등록한다. 가용 조회에는 `agent.run`, 장비 초기화, 모델 load를 호출하지 않는다. 기존 owner 결과에 시각이 없으면 unknown으로 남긴다.

```python
# BO owner 내부: 변경 키 allowlist 후 기존 normalizer로 검증한다.
allowed = {"parameter_space", "acquisition"}
if set(changes) - allowed:
    raise ValueError("Unsupported BO setup field")
normalized, warnings = BOAgent.normalize_settings({**current_settings, **changes})
return {"values": normalized, "warnings": warnings,
        "requires_confirmation": any(normalized[key] != value for key, value in changes.items())}
```

- [ ] `BOAgent.initial_design_request`의 실제 parameter space와 `run_with_settings`에 전달되는 acquisition을 spy로 확인한다. 기존 BO 소유권 테스트도 실행한다.
- [ ] Run `.venv/bin/python -m pytest tests/unit/test_orchestrator_capabilities.py tests/unit/test_bo_agent.py tests/unit/test_bo_decision.py -q`; 외부 호출 차단 fixture 아래 PASS 확인.

## Task 3: 확정 → 다음 실행 적용 → owner readback

**Files:** Create `orchestrator/setup_application.py`, `tests/unit/test_setup_application.py`.

필요한 범위에서 `orchestrator/experimental_setup.py`와 해당 기존 unit test에
backward-compatible validation metadata CAS 및 confirm의 optional store-revision 검사를
추가한다. owner 호출 전후의 claim/receipt도 같은 원자적 저장 경계를 사용하여
동시 activation 호출이 동일 owner 적용을 중복 실행하지 않게 한다.

**Interfaces:** `SetupApplication(store: SetupStore, owners: OwnerCatalog)`.

- `async confirm(proposal_id: str, revision: int, request_id: str, state) -> dict`: 전체 owner validation 후 `target='next_run'`으로 confirm; 아직 Applied 아님.
- `async activate_for_new_run(state) -> dict`: 새 run 입력 준비 시 호출; owner 적용/readback과 immutable setup snapshot 생성.
- `async reconcile(proposal_id: str, state) -> dict`: 적용 응답 유실 후 읽기 확인만 수행.
- `receipt_status(expected: dict, observed: dict | None) -> str`: `applied/rejected/unknown` 판정.

- [ ] 다음 테스트 및 서로 다른 owner의 부분 적용·확정 중 revision 변경을 추가한다.

```python
from orchestrator.setup_application import receipt_status

def test_missing_readback_is_not_applied():
    assert receipt_status({"goal": "compare"}, None) == "unknown"
    assert receipt_status({"goal": "compare"}, {"goal": "compare"}) == "applied"
    assert receipt_status({"goal": "compare"}, {"goal": "baseline"}) == "rejected"
```

- [ ] Run `.venv/bin/python -m pytest tests/unit/test_setup_application.py -q`로 red 확인.
- [ ] request ID를 owner별로 안정되게 파생한다. 적용 전 applying을 보존하고, readback이 예상값과 같은 owner만 Applied로 기록한다.

복수 owner 블록의 `values`는 descriptor의 설정 ID를 기준으로 owner별 변경 dict로
분리한다. 모델이 전달한 owner 이름으로 임의 재분류하지 않는다. 의존 블록의 저장된
owner/setting revision이 변경되면 `validation_status='stale'`로 표시하되 값은 보존하고
전체 owner 검증을 다시 요구한다. 부분 실패를 고치려고 다른 owner 값을 자동 조정하지 않는다.

```python
owner_request = f"{proposal_id}:{owner}:{state.run_id}"
receipt = await owners.apply(owner, changes, state, owner_request)
observed = owners.readback(owner, state)
receipt["status"] = receipt_status(changes, {key: observed[key] for key in changes if key in observed})
store.record_application(proposal_id, owner, receipt)
```

- [ ] 기존 실행 state를 복사한 테스트에서 confirm 전후 snapshot 동일, 새 run activation 후에만 값 변경을 검증한다. owner apply는 동일 request ID에 동일 receipt를 반환해야 한다.
- [ ] Run `.venv/bin/python -m pytest tests/unit/test_setup_application.py tests/unit/test_experimental_setup.py -q`; diff 검토.

## Task 4: 실제 LLM 판단과 제한 도구 dispatcher

추가 승인 요구: `classify_chat_request`를 같은 모듈에 두고 등록 모델의 구조화된
intake 판단을 사용한다. 분류는 `question/change_setup/start_run/confirm_pending/out_of_scope/unclear`이며
`intent`, `reason`, `pending_id`만 허용한다. 모호하거나 모델 호출이 실패한 intake는
`unclear`로 응답하고 부작용을 일으키지 않는다. 현재 pending ID는 서버가 제공하고
모델이 미등록 ID를 승인 근거로 만들 수 없다. 구체적인 mode/장비/조건 인자는 기존 owner가 검증한다.
일반 질문의 답변은 기존 Chat 생성 경로를 사용하되 범위 안내 정책을 prompt에 포함한다.

**Files:** Create `agents/orchestrator_decision.py`, `tests/unit/test_orchestrator_decision.py`; modify `agents/orchestrator_agent.py`, `backends/prompt_registry.py`, `graphs/modules/orchestrator/module.yaml`.

**Interfaces:**

- `validate_choice(payload: dict, allowed_tools: set[str], evidence_ids: set[str]) -> dict`.
- `async decide_orchestration(state, ctx, *, context: dict, handlers: dict) -> dict`.
- handler는 `async (arguments: dict) -> dict`; 이름은 상세안의 6개 도구만 사용.
- 결과에는 `decision_id`, `status`, `tool`, `arguments`, `reason`, `evidence_refs`, `model`, `trace`, `scope` 포함. status는 `prepared/deferred/review_required/proposed/failed`.

- [ ] 정상 조회 후 인계, 추가 조회 후 보류, unknown tool/인자/근거, 예산 소진, 취소, 늦은 scope 변경 테스트 작성.

```python
import pytest
from agents.orchestrator_decision import validate_choice

def test_model_cannot_call_a_bridge():
    with pytest.raises(ValueError):
        validate_choice({"tool": "bridge.execute", "arguments": {}, "reason": "ready",
                         "evidence_refs": ["context:a"]}, {"inspect_context"}, {"context:a"})
```

- [ ] Run `.venv/bin/python -m pytest tests/unit/test_orchestrator_decision.py -q`로 red 확인.
- [ ] 기존 `ctx.complete('orchestrator_plan', ...)`를 사용한다. 정상 valid 요청은 actual model+tool effect가 있어야 성공한다. `inspect_*`는 결과를 다음 모델 입력에 포함하고 terminal tool에서 종료한다.

```python
choice = validate_choice(parsed_response, set(handlers), evidence_ids)
effect = await handlers[choice["tool"]](choice["arguments"])
trace.append({"choice": choice, "result": effect})
```

`parsed_response`는 JSON object만 허용한다. 도구별 인자 schema, evidence membership,
현재 scope를 실행 직전 검사한다. 테스트에서는 응답을 JSON으로 주입하며 생산경로에
fake 선택 로직을 추가하지 않는다. tool 실행 오류를 모델 호출 retry로 감싸 중복 실행하지 않는다.
- [ ] 기존 Orchestrator 반환 필드·archive 유지, deterministic test 명시, model timeout·취소 전파 검증.
- [ ] Run `.venv/bin/python -m pytest tests/unit/test_orchestrator_decision.py tests/unit/test_orchestrator_supervisor.py -q`; diff 검토.

## Task 5: 실제 런타임 인계와 재개 경계

**Files:** Create `orchestrator/orchestrator_checkpoint.py`, `tests/unit/test_orchestrator_checkpoint.py`; modify `orchestrator/langgraph_runtime.py`, `orchestrator/supervisor.py`, `app/controller.py`, `tests/unit/test_langgraph_runtime.py`, `tests/unit/test_controller_planning.py`.

공통 호출 경계는 `orchestrator/handoff_boundary.py`로 분리하여 controller/runtime의
context·handler·scope 검증 중복을 피한다. 실행기는 기존 것을 유지한다.
Task6가 사용할 `_setup_store()`의 최소 factory는 새 실행 activation 의존성 때문에
이 Task에서 먼저 연결할 수 있다.
새 판단층은 현재 graph에 Orchestrator의 실행 stage_dispatch 또는 enabled pre_execution
binding이 선언된 경우에 연결한다. overlay-only 설명 노드는 실행 권한이 아니다.
Orchestrator가 없는 custom graph는 기존 실행을 보존하고, 선언됐지만 구현이 누락된
경우는 오류/보류로 구분한다. registry 전체 목록으로 참여를 추정하지 않는다.

**Interfaces:** `handoff_checkpoint(metadata: dict, key: str, *, action: str, payload: dict | None = None) -> dict`; action은 `prepare/defer/consume/read`.

- [ ] prepare→defer→consume→중복 consume 시 result/effect가 한 번만 소비되는 테스트 작성.

```python
from orchestrator.orchestrator_checkpoint import handoff_checkpoint

def test_consumption_is_once():
    metadata = {}
    handoff_checkpoint(metadata, "run:1:task:result-1", action="prepare", payload={"next_stage": "design"})
    first = handoff_checkpoint(metadata, "run:1:task:result-1", action="consume")
    second = handoff_checkpoint(metadata, "run:1:task:result-1", action="consume")
    assert first["consume_now"] is True
    assert second["consume_now"] is False
```

- [ ] Run `.venv/bin/python -m pytest tests/unit/test_orchestrator_checkpoint.py -q`로 red 확인.
- [ ] 다음 대응표 위치에서 연결한다. graph 파일의 node/edge는 바꾸지 않는다.

| 경계 | 연결 지점 | 보존할 행동 |
|---|---|---|
| 일반 task 위임 | runtime module pre-step와 기존 stage dispatch 경계 | 같은 task에서 Orchestrator 두 번 호출 금지 |
| 결과 인계 | `next_stage`/candidate 계산 후 기존 `_record_orchestrator_transition` 전 | 준비된 handoff만 실제 transition에 소비 |
| 짧은 관측→소비 | 해당 복합 task를 시작하기 전 | 기존 capture/신호 소비 사이 추가 모델 await 없음 |
| planning Design | `_handoff_planning_to_design`, `_run_planning_langgraph_stage` 호출자 | 기존 controller/LangGraph 경로; 단독 shortcut 신설 금지 |
| 실행 중 문의 | `_queue_runtime_operator_followup` 및 runtime drain | 작업 완료를 기다리는 기존 경계에서 처리 |
| 새 실행 설정 | 기존 새 run state 생성·reset 이후, `_seed_initial_bo_design_constraints` 이전 | activation은 run당 한 번; 기존 BO 추천 우선순위 보존 |

새 run reset 전에 확정 proposal ID와 canonical SetupStore 참조를 확보하고,
reset 후 새 state에 적용한다. 기존 run의 metadata를 통째로 복사하지 않는다.
새 실행에는 immutable snapshot과 원본 proposal 참조를 보관한다. 기존 run 복구/조회는
새 run activation을 호출하지 않는다. 다음 cycle의 기존 BO 추천은 새 run 설정과 구별한다.

현행 Chat의 `_handoff_planning_to_design`은 state를 새로 만들지 않는다. 따라서 확정된
next_run 제안이 있고 사용자가 새 planning series를 시작할 때만 이 진입점에서 fresh
state를 만든다. 제안 없는 기존 경로, 다음 cycle 및 모든 resume 경로는 유지한다.
명시적 mode/profile/input만 좁게 전달하고 과거 승인·관측·평가·추천 metadata는 복사하지 않는다.
해당 경우 `_run_test_mode_planning`의 이른 LHS seed는 생략하고 activation 이후 한 번만
seed한다. canonical session/transcript/store는 보존하고 확정된 목표를 생성된 기본 goal로
덮어쓰지 않는다. 이 동작과 no-pending 동작을 각각 회귀 검사한다.

```python
# 기존 완료 결과 처리 경계: 보류 결과를 다음 tick에서 agent.run으로 보내지 않는다.
record = handoff_checkpoint(state.run_metadata, checkpoint_key, action="read")
if record.get("status") == "deferred":
    return
```

재평가는 해당 owner 상태 변경/명시적 응답에서 prepare 상태로 바꾸고 인계 검토만 수행한다.
프리뷰 UI 조회는 재평가 trigger가 아니다. 기록·counter 갱신 후 결정 실패가 나도
기존 stage 완료를 다시 처리하지 않는다.

관측 후 실행 입력이 변경되어 관측 승인이 무효화된 경우에는 무한 대기로 남기지 않는다.
기존 runtime followup/dispatch에서 held checkpoint/run/loop/specimen에 결부된 명시적
`refresh_observation` 요청만 수용하여 기존 Vision 관측 경계로 재진입한다. 완료된
Manipulation·장비 결과·counter는 보존하며 관측 승인과 미소비 전이만 대체한다.
새 판단은 새 촬영 전에 수행하고, 일반 대화·폴링은 재촬영이나 물리 재실행을 유발하지 않는다.
대화 reply revision은 판단 재평가에 사용하되 그 자체를 실행 입력 변경으로 취급하지 않는다.
기존 시편 미검출 intervention/rollout stop/카메라 반환 근거를 가짜로 생성하지 않는다.
- [ ] 모델 지연·취소·실패를 주입하고 post-placement, clearance, Guardian 정지, loop count,
  기존 가상 planning 인계·BO→Design 좌표를 검사한다. 코드 위치별 await 목록도 리뷰한다.
- [ ] Run `.venv/bin/python -m pytest tests/unit/test_orchestrator_checkpoint.py tests/unit/test_langgraph_runtime.py tests/unit/test_controller_planning.py -q`; 물리 차단 fixture가 없으면 먼저 추가한다.

## Task 6: Chat·설정 action·세션 snapshot 연결

기존 substring 실행 분기 전에 Task4 intake를 연결한다. `start_run`만 기존 start 경로,
`confirm_pending`만 서버의 현재 pending 요청과 결부된 선택 경로로 전달한다.
질문/부정/인용/out_of_scope/unclear는 실제 실행·설정 변경 0회여야 한다. 기존 정상
명시적 실행/프린터 선택 문장은 유지한다. STOP/긴급정지는 이 LLM 분류를 기다리지 않는다.

**Files:** Modify `app/controller.py`, `app/main.py`; create `app/planning_setup.py`, `tests/unit/test_planning_setup_api.py`.

`app/planning_setup.py`는 graph 기반 블록 투영과 제한된 변경안 handler 구성만 담당한다.
세션·입력 분류·action·실행 권한은 기존 controller에 유지하며 별도 상태 저장소나 실행기를 만들지 않는다.

**Interfaces:** controller에 `_setup_store() -> SetupStore`, `async planning_setup_action(action: dict) -> dict` 추가.
`PlanningMessageRequest`에 optional `setup_context: dict | None = None` 추가; 일반 constraints를 설정 write 권한으로 사용하지 않는다.
`POST /api/planning/setup/actions`는 `action`, `proposal_id`, `expected_revision`, `request_id`, `session_id`, `target='next_run'`를 검사한다.
응답은 `{ok, setup, message}`; conflict HTTP409, scope 불일치403, validation422.

- [ ] 기본 Chat 호환성, 편집 요청의 Design 명령 오인 방지, client running=false 위조, stale revision, 클릭만으로 실행 없음 테스트 작성.

```python
from app.main import PlanningMessageRequest

def test_chat_context_is_optional_and_explicit():
    old = PlanningMessageRequest(message="Explain this result")
    edit = PlanningMessageRequest(message="Revise the next design", setup_context={"block_id": "b1", "revision": 2})
    assert old.setup_context is None
    assert edit.setup_context["block_id"] == "b1"
```

- [ ] Run `.venv/bin/python -m pytest tests/unit/test_planning_setup_api.py -q`로 red 확인. API import에 의한 startup effects를 fixture에서 차단한다.
- [ ] controller Chat에서 setup_context를 먼저 검증하여 편집 경로로 분리한다. 기존 문자열 trigger보다 우선하며 기존 일반 질문·명시적 실행 흐름은 유지한다.

```python
# API에서 typed request를 검증한 뒤 controller가 서버 최신값으로 scope를 재검증한다.
if setup_context is not None:
    block = next(item for item in store.snapshot()["blocks"] if item["block_id"] == setup_context["block_id"])
    if block["revision"] != setup_context["revision"]:
        raise SetupConflict("Setup changed; refresh the proposal")
```

미존재 block은 validation error로 반환한다. 세션은 `_bind_planning_session`의 공유
세션 동작을 유지하고 canonical server session을 응답한다. 새 탭의 임의 local ID가
다른 세션의 블록 접근 권한이 되지 않으며, UI는 응답의 canonical ID를 사용한다.
- [ ] 일반 Chat에서 설정 수정을 제안할 때도 Task4의 `propose_setup_change`만 사용한다.
  server proposal이 없는 일반 확인 문장은 적용하지 않는다. proposal 단일 연결 시 같은 action 함수 사용.
- [ ] `_planning_state_payload` compact 경로에 setup summary/revision 포함; 새 상태 이벤트는 기존 broadcast 사용.
  transcript와 동일 run directory에서 reload하되 새 실행으로 자동 resume하지 않는다.
- [ ] Run `.venv/bin/python -m pytest tests/unit/test_planning_setup_api.py tests/unit/test_controller_planning.py -q`; diff 검토.

## Task 7: 동적 블록·Chat 편집 맥락 UI

**Files:** Create `web/static/experimental_setup.js`, `web/static/experimental_setup.css`, `tests/js/experimental_setup.test.cjs`; modify `web/static/planning.js`, `web/templates/planning.html`; create `tests/ui/experimental_setup_browser_audit.py`.

**Interfaces:** browser global/CommonJS `ExperimentalSetup` export.
`beginEdit(block: object) -> object` returns `{block_id, revision}`;
`acceptSnapshot(current: object, incoming: object) -> object` ignores older revision;
`renderBlocks(root, snapshot, callbacks) -> void`; callbacks `onEdit`, `onConfirm`, `onDiscard`.

- [ ] 다음 Node 테스트와 HTML escape, stable ID, draft/effective 분리, unsupported readonly 표시 테스트 작성.

```javascript
const test = require('node:test');
const assert = require('node:assert/strict');
const {beginEdit, acceptSnapshot} = require('../../web/static/experimental_setup.js');
test('editing selects context without sending a command', () => {
  assert.deepEqual(beginEdit({block_id:'b1', revision:3}), {block_id:'b1', revision:3});
});
test('old event cannot overwrite a newer block state', () => {
  const current = {revision:4, blocks:[]};
  assert.equal(acceptSnapshot(current, {revision:3, blocks:[]}), current);
});
```

- [ ] Run `node --test tests/js/experimental_setup.test.cjs`로 red 확인.
- [ ] approved UX 그대로 구현한다. 입력폼 직수정·과거 transcript 이동은 추가하지 않는다.

```javascript
function onEditSetupBlock(block) {
  liveSetupEditContext = ExperimentalSetup.beginEdit(block);
  setLiveChatTargetMode('orchestrator');
  setLiveChatCollapsed(false, {resetUnread:false});
  planningMessageInput.focus();
}
```

`liveSetupEditContext`는 `planning.js`의 세션 로컬 변수로 선언하고 전송 payload의
`setup_context`에만 붙인다. 함수는 이벤트 handler로 등록하며 클릭 시 fetch하지 않는다.
Exit editing에서 null로 초기화한다. 다른 세션/삭제된 블록으로 바뀌면 편집 맥락도 해제한다.
- [ ] Setup과 Chat은 같은 원본 상태를 유지한다. 기존 collapsed panel 동작을 재사용하고
  Chat에서 변경하면 접힌 Setup에도 상태가 반영된다. 새 메시지마다 전체 카드 DOM을 교체해
  포커스·열린 상세를 잃지 않도록 block ID/revision 기준 갱신한다.
- [ ] 블록 편집 UI는 기존 Experimental Setup 영역을 대체한다. 별도 패널을 추가하거나
  Chat/주변 카드의 배치를 밀어내지 않는다. 세로 공간이 부족하면 해당 Setup 영역 내부에서
  `overflow-y: auto`로 스크롤하며, 기존 접기/펼치기와 키보드 접근을 유지한다.
- [ ] 템플릿에 새 script를 planning.js 앞에 로드하고 CSS는 Setup 범위로 제한한다.
  title/status/owner/apply time, Editing 대상, 변경 diff, readonly 이유, 확인/폐기 UI를 영어로 작성한다.
- [ ] static fixture 페이지로 데스크톱·좁은 화면, 키보드 focus, 두 탭 충돌, reconnect,
  상태 이벤트 도착 중 입력 보존을 브라우저에서 검사한다. 운영 GUI에는 연결하지 않는다.
  높이가 작은 화면과 블록이 많은 상태에서 Setup 내부 스크롤로 마지막 블록의
  Edit/Confirm/Discard에 접근 가능한지, 주변 Chat 배치가 유지되는지도 검사한다.
- [ ] Run `node --test tests/js/experimental_setup.test.cjs`; `node --check web/static/planning.js`; 브라우저 스크린샷 보관 및 diff 검토.

## Task 8: 기존 경로·실제 모델·비구동 루프 검증

**현재 상태:** bounded implementation/aggregate acceptance 완료. Task 8의 상세
검증 근거는 task ledger와 [verification evidence](../../runtime/evidence/2026-09-12-orchestrator-dynamic-setup-verification.md)에 있으며, 장비·20-cycle·model-driven whole-cycle 완료는 아니다.

사용자 우선순위: 검증을 기능 구현의 최종 부록이 아니라 인수 기준으로 삼는다.
현재 `utils/test_mode_execution_profiles.py`의 profile resolver와 기존 controller 진입을
그대로 사용하고 다음 matrix를 각각 검사한다. `configs/test_modes.yaml`의 dry_run/replay/
fault_injection과 프린터 실행 profile을 혼동하지 않는다.

| 경로 | 보존할 동작 | 새 기능 인수 기준 |
|---|---|---|
| virtual_bridge | 네 장비 경계 preflight_only | Setup→LHS→Design→후속 BO 연결, 실제 장비 호출 0 |
| installed_printer | 실제 장비 정책, 출력·냉각 skip, auto_ejection 유지 | 기존 gcode/인계 결정이 새 설정·LLM으로 바뀌지 않음 |
| physical_print | 출력·냉각 execute, auto_ejection 유지 | 실제 출력 요청 경로까지 기존 코드로 생성, 전송 경계에서만 비구동 대체 |
| virtual manipulation + real equipment | operator_teleop 인계 | 사용자 확인 전 장비 시험 진입 없음, 확인 시 기존 teleop-stop 이후 vision 검증 |
| real manipulation + virtual equipment | 기존 real manipulation 정책 | 가상 장비 때문에 로봇 정책이나 기존 검증을 임의 생략하지 않음 |
| 나머지 허용 real/virtual 조합 | 네 agent 경계의 기존 resolver 결과 | 조합별 정책·scope snapshot 보존; 금지 조합은 기존 validator가 거부 |
| dry_run / replay / fault_injection | 각 기존 실행·재생·오류 주입 계약 | 새 Setup revision/가용성 판단이 기존 mode를 변경하거나 성공 작업을 재실행하지 않음 |

프로필 정책 해석만 검사한 결과를 풀 사이클 검증으로 부르지 않는다. 세 built-in 및
주요 hybrid 경로는 실제 runtime transition trace를 검사하고, 실제/가상 조합 전체는
resolver와 admission 계약을 parameterize하여 검사한다. 테스트 대역은 장비 I/O 경계에
두고 실제 기존 stage/agent/인계 경로를 유지한다. background solver 및 서비스 시작도
fixture 설치 이후에만 bootstrap하여 차단한다. 실장비 실증으로 보고하지 않는다.

최소 36개 intake prompt fixture를 구성한다: 정상 실험/설정 요청 8개, 관련 질문 6개,
한국어 오타·축약 4개, 부정·인용·설명 요청 6개, 무관/무의미 요청 4개,
모호한 승인·stale pending 4개, 미지원 키/직접 bridge/권한 우회 4개.
각 fixture에 수작업으로 허용 intent 집합과 허용 effect 집합을 지정한다.
두 backend 모두 같은 fixture를 검사하고 miss를 분류해 prompt를 보완한 후 전체를 재실행한다.
표현만 바꾼 별도 holdout 12개도 추가하여 정확한 문자열 암기만으로 통과하지 않도록 한다.
`테스트 모드가 뭐야?`, `실험 수행하지 말고 설명해`, `출력 품질 알려줘`는 어떤 pending
상태에서도 실험/출력 시작으로 이어지면 실패다. `ㅇㅋ`는 연결된 proposal/request 없이 효과가 없어야 한다.

**Files:** Create `tests/integration/test_orchestrator_setup_loop.py`, `scripts/verify_orchestrator_setup.py`; modify the new tests only to add reusable fixtures.

**Interfaces:** verification script는 `--backend openai|vllm` (repeatable), `--execute`, optional `--output PATH`를 받는다.
execute 없이 fixture 목록·차단 경계만 출력한다. 등록 provider/router와 `orchestrator_plan`을 사용한다.
`verification_report.v1`에 backend/model, scope, case, status, latency, tool trace, setup revision,
handoff IDs, physical_call_count, evidence_class를 기록한다. secret은 제외한다.

- [ ] integration fixture에서 모델은 controlled JSON, 실제 controller/runtime/BO는 기존 구현을 사용한다.
  API lifespan의 서비스 시작을 차단하고 물리 tool/bridge callback은 호출 즉시 테스트 실패로 만든다.

```python
def forbidden_physical_call(*args, **kwargs):
    raise AssertionError("Physical tool invocation is forbidden in setup verification")
```

등록된 모든 물리 tool, bridge backend의 네트워크 명령 경로, 서비스 시작 callback에
동일 sentinel을 주입한다. LLM HTTP 호출은 실제 모델 fixture에서만 별도로 허용한다.
비구동 tool 결과도 기존 필수 handoff/CSV/identity 계약을 충족해야 한다.
실제 실행 정책인 profile의 경로 검증에는 필요한 장비 I/O 경계만 명시적인 비구동
대역으로 교체하여 요청과 합성 응답을 기록한다. 원본 물리 transport 및 허용 목록 외
호출은 sentinel이 거부한다. `simulated_boundary_requests`와 `physical_call_count`를
구분한다. 전자는 해당 모드가 요청한 출력/이젝션/인계를 증명하고 후자는 항상 0이다.
agent.run 전체를 고정 성공으로 바꿔 통과시키지 않는다.
- [ ] 실패 테스트: setup 변경을 확정한 뒤 기존 `/api/planning/message`/실행 entry를 사용해
  새 run을 시작하고 `bo_settings`→초기 LHS→Design 요청→다음 BO/Design 연결을 검증한다.
  current snapshot 불변, caller 실행횟수, model/tool trace를 함께 assert한다.

```python
# 실제 기존 루프에서 모은 증거의 필수 assertion.
assert evidence["physical_call_count"] == 0
assert evidence["initial_lhs_space"] == evidence["applied_bo_space"]
assert evidence["design_requested_parameters"] == evidence["bo_selected_parameters"]
assert evidence["duplicate_completed_task_calls"] == 0
assert evidence["setup_revision"] == evidence["execution_setup_revision"]
```

`evidence` dict는 integration test가 owner spy, controller snapshot, agent tool trace에서
작성한다. assertion을 통과시키려고 모델·전문 에이전트 결과를 위 필드 값으로 대체하지 않는다.
- [ ] Run `.venv/bin/python -m pytest tests/integration/test_orchestrator_setup_loop.py -q`로 red 확인 후 실제 연결 누락만 수정한다.
- [ ] 실제 모델 fixture는 ready, busy, unknown/stale, 설정 변경 제안, unsupported 설정,
  완료 결과의 보류/재개 6종을 각 backend에 전달한다. 정상 사례에는 실제 tool 효과가 필수다.
  모델별 다른 타당한 선택은 허용하고 정답 문자열 하나를 강제하지 않는다.
- [ ] `.venv/bin/python scripts/verify_orchestrator_setup.py --execute --backend openai --backend vllm` 실행.
  output 생략 시 기존 `system.run_root` 아래 `validation-orchestrator-setup-` 접두사의 고유 run directory를 생성한다.
  그 안의 `orchestrator_setup_verification.json`에 보관하고 절대 경로를 출력한다. 동일 파일을 덮어쓰지 않는다.
  앱의 저장된 등록 설정만 사용한다. provider 미가용은 blocked로 기록하며 서버를 임의로 시작하지 않는다.
- [ ] mock/controlled 테스트와 API/vLLM 테스트를 분리해 결과를 기록한다. 시간 민감 구간의 모델
  지연, stop/cancel, 응답 유실, 부분 적용, restart/reconnect를 재실행한다. 각 CASE는 동일효과 재전송 0회.
- [ ] Run `.venv/bin/python -m pytest tests/integration/test_orchestrator_setup_loop.py tests/integration/test_objective_compiler_closed_loop.py tests/integration/test_all_agent_loop_archives.py -q`; 전체 trace 검토.

## Task 9: 문서·SVG·최종 인수

**현재 상태:** 관련 문서 scoped 검증과 최종 검토가 완료되었다. Task 8 aggregate
acceptance와 Task 9 문서 인수는 bounded scope에서 완료되었으며, 장비·20-cycle·model-driven
whole-cycle 완료를 뜻하지 않는다.

**Files:** Modify `docs/agents/orchestrator_agent.md`, `docs/agents/README.md`, `docs/agents/agent_api_connection_matrix.md`, `docs/gui/reference/live_gui_reference_alignment.md`, `docs/runtime/runtime_ide.md` (실제 변경된 연결만), 승인 상세안과 본 계획, `scripts/validate_documentation.py`.
`docs/standards/documentation_standard.md`는 현재 승인된 Status at a Glance 표 형식과
Orchestrator의 세 번째 API/connection figure 목록만 맞춘다. 다른 문서 규칙 개편은 하지 않는다.
Modify existing `docs/agents/assets/figures/orchestrator_01_closed_loop_handoffs.dot/.svg`, `orchestrator_02_execution_effect_boundary.dot/.svg`.
Create `docs/agents/assets/figures/orchestrator_03_api_connection_architecture.dot/.svg`.

**Interfaces:** 기존 Status at a Glance 및 5영역 Reference 구조 유지. validator의 Orchestrator figure inventory에 새 세 번째 basename 추가.

- [x] 검증기 inventory에 세 번째 figure를 요구하는 단위 테스트를 먼저 추가하고 파일이 없을 때 실패를 확인한다.
- [x] 현재 구현만 문서에 반영한다: owner별 write/read-only 범위, Chat 편집, availability unknown,
  실제 LLM 도구, 기존 런타임 소비 위치, 설정 적용 시점, 모델별 검증 결과·남은 gap.
- [x] Graphviz source를 갱신하고 SVG를 재생성한다.

```bash
dot -Tsvg docs/agents/assets/figures/orchestrator_03_api_connection_architecture.dot -o docs/agents/assets/figures/orchestrator_03_api_connection_architecture.svg
```

기존 두 도표도 동일 명령 형태로 각각 재생성한다. 그림 내용은 새 실행 stage를 다섯 개로
표현하지 않고, 기존 runtime과 owner 경계·Setup/Chat 동일상태를 표시한다.
- [x] 관련 문서 검증, SVG XML/시각검사·링크 검사 후 모델/loop evidence를 연결했다. 최종 문서 검토 전의 scoped 결과는 46 passed, paper publication passed, DOT/SVG reproduction·XML·link-element checks passed이며 global validator는 unrelated 27 baseline findings을 유지했다.

```bash
.venv/bin/python -m pytest tests/unit/test_documentation_validation.py tests/unit/test_paper_publication_validation.py -q
.venv/bin/python scripts/validate_documentation.py
.venv/bin/python scripts/validate_paper_publication.py
git diff --check
```

전체 문서 validator의 기존 결함은 기준 실행과 비교해 별도 보고한다. 관련 없는 문서를
이번 작업에 끌어들이지 않으며 전체 검증 실패를 PASS로 표현하지 않는다.
- [x] 실제 장비 미구동, 운영 서비스 미변경, 사용자 변경·`output/` 보존, 관련 파일만 수정했는지 확인했다. Task 8/9 report와 verification evidence는 physical call/denied attempt 0, nonactuating simulated lifecycle 한 건, 서비스·hardware·`output/` 미변경 경계를 기록한다.
- [ ] 사용자에게 범위별 결과를 보고한다. 커밋·태그·푸시는 별도 지시 이후에만 수행한다.

## Completion Criteria

| 상세안 AC | 담당 Task |
|---|---|
| 01 실제 API/vLLM 판단·효과 | 4, 5, 8 |
| 02 가용 상태·stale 구분 | 2, 4, 8 |
| 03 상태 변경과 수용 확인 | 2, 5, 8 |
| 04 완료 효과·counter 중복 방지 | 5, 8 |
| 05 동적 descriptor 블록 | 1, 2, 7 |
| 06 Chat/블록 동일 맥락·클릭 비실행 | 6, 7 |
| 07 합의/적용 분리 | 1, 3, 7 |
| 08 실제 owner 소비 경로 | 2, 3, 5, 8 |
| 09 현재 실행 불변·다음 실행 적용 | 3, 5, 8 |
| 10 충돌·재시작·중복·응답 유실 | 1, 3, 6, 7, 8 |
| 11 partial·의존성 invalidation | 1, 3, 7, 8 |
| 12 기존 루프와 다음 Design | 5, 8 |
| 13 시간 민감·정지 보존 | 5, 8 |
| 14 문서·SVG·결과 구분 | 9 |

## Limitations and Known Gaps

- 첫 쓰기 범위는 Goal과 BO의 검증 가능한 설정이다. 전체 장비 파라미터 연동을 의미하지 않는다.
- 첫 적용 정책은 다음 새 run이다. 실행 중 현재 loop나 다음 cycle을 직접 변경하는 기능은 추가하지 않는다.
- 구현된 owner가 없거나 timestamp 없는 상태는 unknown/read-only다. UI 표시를 위해 준비 상태를 조작하지 않는다.
- 완료된 bounded provider aggregate는 모델 구동 전체 cycle·20-cycle campaign·장비 실증이 아니다. 실제 통과 근거와 capture/postprocessor epoch은 [공개 verification evidence](../../runtime/evidence/2026-09-12-orchestrator-dynamic-setup-verification.md)에 분리한다.

## Plan Review

승인 설계의 AC-01~14를 Task에 대응시켰다. Task 1~8의 구현·bounded acceptance는
각 task ledger와 corrected aggregate evidence로, Task 9의 문서·SVG 인수는 scoped
검증과 최종 review로 확인되었다. 위 체크박스는 실제 task별 증거가 있는 항목만
갱신했으며, 사용자 결과 보고 항목은 전달 시점까지 열린 상태로 둔다. 이 완료 표시는
장비·서비스·20-cycle 또는 model-driven whole-cycle 완료를 뜻하지 않는다.
