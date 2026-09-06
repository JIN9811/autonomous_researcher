# Agent-Owned Campaign Settings and Continuous BO Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans or, when delegation is authorized, superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 에이전트가 자기 설정을 소유하고, 캠페인은 설정 참조를 묶으며, 변수 변경이 실제 실행 입력까지 전파되는 구조와 BO 연속값 폐루프를 구현한다.

**Architecture:** 기존 에이전트의 설정·검증·실행 입력 생성 경로를 소유자별 adapter로 연결한다. 설정하지 않은 변수는 기존 동작을 보존하는 명시적 기본 설정으로 해석하고, 선택적으로 연결한 변수는 소유 원본의 변경을 전파한다. ORC는 변경 적용을 조정하고 캠페인은 확인된 설정 버전 묶음과 실행 이력을 보존하되 별도 실행 엔진이 되지 않는다.

**Tech Stack:** 기존 Python/Pydantic state, YAML 기본 설정, MainController/ObjectiveService/Equipment Skill 경로, BoTorch, vanilla JS/CSS, pytest/Node 기반 비구동 테스트.

**Spec:** [실험 슬롯·연구 캠페인·BO 연속값 통합 설계안](../specs/2026-09-07-single-compression-experiment-slot-design.md).

**Status:** review / authority: execution / execution_status: planned. 작성일 2026-09-07. 아래 코드는 구현 예정 인터페이스·테스트 예시이며 아직 구현되지 않았다.

## Global Constraints

- 기존 경로 재사용 → 기존 경로 최소 확장 → 불가피한 경우만 신규 추가.
- 설정 스키마·검증·저장·적용의 소유권은 담당 에이전트에 있다.
- 캠페인은 다른 에이전트의 설정 원본이 아니며 ORC가 값의 의미를 독자적으로 결정하지 않는다.
- 변수화와 사용자 설정/연동은 별개다. 사용자 설정이나 캠페인이 없어도 기존 프로필·기본 설정으로 실행 가능해야 한다.
- 실제 제공하는 슬롯은 압축시험 하나뿐이며, 추가 슬롯이 구현되었다고 표시하지 않는다.
- GUI는 영어, 채팅은 사용자 언어, 설계/계획 설명은 한국어로 작성한다.
- 설정 저장은 장비 구동 승인이 아니다. 기존 모드·프로필·Guardian·물리 실행/이젝션/텔레옵/UTM 경로를 보존한다.
- 기존 목적 지표 `energy_density_50pct_MJ_per_m3`의 의미와 과거 기록을 보존한다. 연동형 목표 구간은 별도 지표·목적 버전으로 다룬다.
- 현재 CAE 요청 소유자는 AnalysisAgent다. 없는 CAE agent를 새로 만들지 않는다.
- 기존 아티팩트 경로와 미커밋 작업을 보존한다. 사용자 요청 없이 커밋·푸시하지 않는다.
- 이번 검증은 비구동이다. 운영 서버 호출·재시작, 실제 장비 설정 변경·구동, 실행 중 run 복구를 하지 않는다.

---

## 1. 반드시 함께 완성할 범위

```text
압축시험 슬롯
  └─ 캠페인: 소유 설정 참조·연결·확정 버전 묶음
       ├─ Design: 치수·제조 조건·제조 가능 범위
       ├─ Equipment: 시험 조건·장비 method 입력 매핑
       ├─ Analysis: 계산 구간·지표·CAE 요청 설정
       ├─ BO: 탐색 공간·LHS·seed·수치 최적화 설정
       └─ ORC: 실행 예산·운영 종료 조건
               ↓ 기존 명시적 실행 요청
          기존 LHS → Design → 실제/가상 실험 → Analysis → BO → 반복
```

슬롯/캠페인 UI만 구현하고 연속값이나 실제 변경 전파를 뒤로 빼면 미완료다. 반대로 캠페인 사용을 모든 기존 단독 실행의 필수 조건으로 만들지도 않는다.

### 설정을 하지 않은 경우

- 최초 기본 설정은 현재 코드/저장 프로필의 유효값을 추출해 소유자별 설정으로 옮긴다. 현재 사용자가 저장한 값이 배포 기본값보다 우선한다.
- 기본값을 실행 함수마다 중복 선언하지 않는다. `configs/agent_defaults.yaml`은 소유 에이전트별 섹션을 담는 저장 매체이며 캠페인이나 ORC의 설정 소유권을 뜻하지 않는다.
- 신규 변수에는 값뿐 아니라 타입·단위·소유자·기본 설정 출처·연결 가능 필드를 정의한다. 당장 GUI에서 모든 변수를 편집하게 만들 필요는 없지만 소유 설정 API에서 주소 지정 가능해야 한다.
- 사용자 값이나 연결이 없어도 기존 기본 동작이 유지된다. 설정의 `source=default`를 기록하고 나중에 같은 필드를 `follow`로 연결할 수 있다.
- 명시한 값이 잘못됐거나 활성 연결 원본 조회가 실패하면 기본값으로 숨기지 않는다. 값·프로필·기본 설정 모두 없는 경우에만 미설정 오류다.

### 변경이 연동되는 경우

```text
GUI/채팅/에이전트 workspace 변경 요청
 → 소유 에이전트 검증
 → 선언된 연결 순서로 소비 에이전트 설정 변경
 → 소유자별 버전 저장
 → 각 에이전트의 실제 실행 입력 생성 경로로 다시 읽기·검증
 → 전체 묶음 확인 후 캠페인 참조 확정
 → 다음 허용 실행 경계에서 사용
 → 장비 설정은 기존 실행 요청 안에서 적용·읽기 확인 후 시험 시작
```

## 2. 현재 코드에서 확인한 변경 지점

| 위치 | 현재 사실 | 구현 시 필요한 변경 |
|---|---|---|
| `agents/analysis_agent.py::_metrics` | 적분 한계 0.5, 면적/높이 fallback이 함수 내부에 있음 | 소유 설정으로 해석한 필수 계산 인자 전달, 기본값은 설정 계층으로 이동 |
| 같은 파일 `::_cae_payload` | `cae_target_strain`/`target_strain`, 마지막 0.5 fallback | 소유 설정에서 계산한 실제 target strain 사용 |
| `agents/design_agent.py::_resolve_constraints` | BO/ORC 셀 크기의 이산 membership 제한 | 타입에 따른 범위/이산 검증과 실제 형상 생성까지 연속값 전달 |
| `learning/bo_parameter_space.py::from_mapping` | 두 숫자 배열을 연속 범위로 추론 | 명시적 타입 표현 수용; 이산 두 값과 연속 범위를 구분 |
| `agents/equipment_agent.py::_run_equipment_skill_flow` | 기존 flow/skill을 호출, `run_context` 전달 | 캠페인 scope의 Equipment 유효 설정을 실행 입력에 결합 |
| 같은 파일 `::_run_equipment_skill` | workflow placeholder에 맞는 `runtime_values` 전달 | 선언된 method 입력의 값·버전·출처도 전달하고 증거 확인 |
| `utm_monitor_contact_and_run@1.0.6` | method-controlled 완료를 기다림 | 기다리기만 해서는 method 변경이 아님. 시작 전 설정 쓰기/읽기 확인 필요 |
| `app/main.py` Equipment profile settings | 현재 주로 vision link preference | 여기에 숫자만 저장하고 시험 설정이 바뀌었다고 주장하지 않음 |
| Windows server `paste_runtime_value` | 현재 CSV/robot clearance 키 중심의 allowlist | 시험 입력 키와 수치/단위 검증을 명시적으로 추가 |
| 기존 ObjectiveService | 목적함수 검증/승인/활성화 존재 | 연동형 분석 지표 버전을 같은 경로로 처리 |

현재 Equipment의 Start Height 32 mm, robot-entry clearance와 시편 압축 변위는 서로 다른 물리량이다. 예시 `height=30 mm`, `strain=0.4`에서 압축 변위는 12 mm지만, 지그 `Height`에 12 또는 18을 무조건 넣지 않는다.

## 3. 공통 계약 — 값의 소유권을 옮기지 않는 연결

신규 계약은 `experiments/campaigns.py`에 정의하되 소유자의 값 검증 로직은 넣지 않는다.

```python
from typing import Any, Protocol, TypedDict


class SettingsRef(TypedDict):
    owner: str
    scope_id: str
    revision: int
    sha256: str
    storage_ref: str


class SettingsReceipt(TypedDict):
    ref: SettingsRef
    status: str
    runtime_input_sha256: str
    value_sources: dict[str, str]


class OwnerSettingsPort(Protocol):
    def prepare(self, patch: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]: ...
    def persist(self, prepared: dict[str, Any], *, operation_id: str) -> SettingsRef: ...
    def read_effective(self, ref: SettingsRef, context: dict[str, Any]) -> dict[str, Any]: ...
```

`prepare`는 실제 소유 스키마로 검증하고 연결값/기본값을 계산한다. `persist`는 해당 scope의 비활성 설정 revision을 소유자 저장 경로에 남긴다. `read_effective`는 요청 dict를 되돌려주는 함수가 아니라 저장한 참조를 읽어 실제 agent/skill/tool 입력 builder로 생성한 입력을 돌려준다. `operation_id` 재요청은 같은 내용이면 같은 참조를 반환하고, 다른 내용이면 충돌 오류다.

저장 revision에는 해석된 값과 그때의 upstream 참조/해시도 고정한다. `read_effective`가 이미 고정된 revision의 `follow`를 현재 최신 원본으로 다시 계산하면 안 된다. 원본 변경은 새 revision에서만 전파한다. 실제 실행 context는 고정된 upstream snapshot을 사용한다.

기존 저장소가 있는 항목은 그 저장소와 serializer를 사용한다. 없는 항목만 `utils/agent_settings.py`의 작은 owner-scoped revision store를 사용한다. 기본 디렉터리는 `memory/agent_settings/<owner>/<scope_id>/`이며 controller 주입 경로와 테스트 임시 경로를 지원한다. 캠페인에는 값의 별도 수정 가능한 사본을 두지 않고 참조와 재현용 snapshot만 둔다.

입력 binding은 세 가지다.

| 모드 | 실제 값 출처 | 변경 동작 |
|---|---|---|
| `default` | 기존 저장 프로필, 없으면 소유 기본 설정 | 캠페인 미설정/미연결로도 동작 |
| `value` | 사용자가 명시한 값 | 소유자가 검증·저장. 잘못된 값은 오류 |
| `follow` | 명시한 소유 원본 필드/버전 + 소비자 변환 | 원본 변경 시 소비자 실제 설정도 변경. 원본 실패는 오류 |

서로 다른 모드를 동시에 적용하지 않는다. `follow` 필드에 직접 값을 넣으려면 명시적으로 `value`로 바꾸거나 원본을 수정하게 안내한다. 연결 변환은 등록된 소유 함수만 사용하고 문자열 `eval`이나 무제한 양방향 동기화를 만들지 않는다.

---

## Task 1: 기본 설정 변수화·슬롯·소유 참조 계약

**Files:** Create `experiments/slots.py`, `experiments/campaigns.py`, `utils/agent_settings.py`, `configs/agent_defaults.yaml`; Test `tests/unit/test_agent_settings.py`, `tests/unit/test_experimental_slots.py`.

**Interfaces:** 3절의 `SettingsRef`, `SettingsReceipt`, `OwnerSettingsPort` 정의를 실제 모듈에 둔다. `resolve_setting(binding, *, default, profile, sources) -> dict[str, Any]`는 `{value, source}`를 반환하며 I/O/장비 접근이 없다. `slot_for_graph(graph_id: str) -> dict[str, Any] | None`는 압축시험 정의 하나만 반환한다.

- [ ] 기본 설정/연결/잘못된 연결의 실패 테스트를 작성한다.

```python
import pytest
from utils.agent_settings import resolve_setting


def test_unconfigured_setting_uses_owned_default():
    result = resolve_setting({"mode": "default"}, default=0.5, profile=None, sources={})
    assert result == {"value": 0.5, "source": "default"}


def test_later_connection_changes_the_same_variable():
    result = resolve_setting(
        {"mode": "follow", "source": "equipment.test.target_strain"},
        default=0.5, profile=None, sources={"equipment.test.target_strain": 0.4},
    )
    assert result == {"value": 0.4, "source": "equipment.test.target_strain"}


def test_broken_explicit_link_does_not_fall_back():
    with pytest.raises(ValueError, match="SETTING_SOURCE_UNAVAILABLE"):
        resolve_setting({"mode": "follow", "source": "equipment.test.target_strain"},
                        default=0.5, profile=None, sources={})
```

- [ ] Run `.venv/bin/python -m pytest tests/unit/test_agent_settings.py tests/unit/test_experimental_slots.py -q`; 신규 모듈이 없는 상태의 실패를 확인한다.
- [ ] resolver의 핵심을 아래 의미로 구현한다. 이 단계는 수치 유효성을 판단하지 않으며 그 책임은 다음 Task의 소유자에 있다.

```python
def resolve_setting(binding, *, default, profile, sources):
    mode = binding.get("mode", "default")
    if mode == "value":
        if "value" not in binding:
            raise ValueError("SETTING_VALUE_REQUIRED")
        return {"value": binding["value"], "source": "explicit"}
    if mode == "follow":
        source = binding.get("source")
        if source not in sources:
            raise ValueError("SETTING_SOURCE_UNAVAILABLE")
        return {"value": sources[source], "source": source}
    if mode != "default":
        raise ValueError("SETTING_BINDING_INVALID")
    if profile is not None:
        return {"value": profile, "source": "profile"}
    if default is None:
        raise ValueError("SETTING_VALUE_REQUIRED")
    return {"value": default, "source": "default"}
```

- [ ] `agent_defaults.yaml`에 소유자별 초기값을 옮긴다. 현재 저장 프로필을 덮어쓰지 않는다. Design 치수/도메인, Analysis 계산/CAE, BO LHS/seed, ORC 예산의 기존 기본 결과를 변경 전 characterization assertion으로 고정한 후 설정 출처만 바꾼다. 장비에서만 알 수 있는 method 값은 임의 숫자로 채우지 않고 기존 method 사용 모드를 보존한다.
- [ ] 슬롯에는 id/label/기존 그래프 및 소유 설정 계약 참조만 둔다. `atr_closed_loop`가 아니면 미연결, 조회 실패는 unavailable이다. 슬롯이 캠페인 설정 원본이 되지 않게 한다.
- [ ] 같은 테스트 PASS와 변경 전 기본 동작 동일성을 확인한다. 커밋하지 않는다.

## Task 2: 소유 에이전트의 설정 서비스와 실제 실행 입력 연결

**Files:** Create `agents/design_settings.py`, `agents/equipment_settings.py`, `agents/analysis_settings.py`, `agents/bo_settings.py`, `orchestrator/campaign_settings.py`; Modify `agents/design_agent.py`, `agents/equipment_agent.py`, `agents/analysis_agent.py`, `agents/bo_agent.py`, `app/controller.py`; Test `tests/unit/test_agent_owned_settings.py`.

**Interfaces:** 각 소유 모듈은 `OwnerSettingsPort`를 구현한다. 클래스명은 각각 `DesignSettings`, `EquipmentSettings`, `AnalysisSettings`, `BOSettings`, `OrchestrationSettings`다. `read_effective` 결과는 기존 runtime payload에 사용하는 동일 builder의 입력이다. 현재 검증 함수를 이동/공유할 수는 있지만 캠페인 전용 복제 검증기는 만들지 않는다.

- [ ] `prepare → persist → read_effective`가 실제 저장 참조를 사용한다는 실패 테스트를 작성한다.

```python
from agents.analysis_settings import AnalysisSettings


def test_analysis_owner_reads_saved_effective_input(tmp_path):
    owner = AnalysisSettings(root=tmp_path, defaults={"evaluation_strain": 0.5})
    context = {"scope_id": "campaign-a", "sources": {"equipment.test.target_strain": 0.4}}
    prepared = owner.prepare(
        {"evaluation_strain": {"mode": "follow", "source": "equipment.test.target_strain"}}, context)
    ref = owner.persist(prepared, operation_id="change-1")
    owner_again = AnalysisSettings(root=tmp_path, defaults={"evaluation_strain": 0.5})
    effective = owner_again.read_effective(ref, context)
    assert effective["evaluation_strain"] == 0.4
    assert effective["value_sources"]["evaluation_strain"] == "equipment.test.target_strain"
    changed_context = {**context, "sources": {"equipment.test.target_strain": 0.7}}
    assert owner_again.read_effective(ref, changed_context)["evaluation_strain"] == 0.4
```

- [ ] Run `.venv/bin/python -m pytest tests/unit/test_agent_owned_settings.py -q`; 신규 소유 설정 서비스 부재로 FAIL인지 확인한다.
- [ ] 생성자와 저장 계약을 구현한다.

```python
# 모든 소유 adapter의 생성자 계약. 기존 store가 있으면 내부 위임한다.
# __init__(self, *, root: Path, defaults: dict[str, Any]) -> None
# persist 결과의 content hash는 정렬된 canonical JSON으로 계산한다.
# read_effective는 ref.sha256과 저장 데이터 일치를 검증한 뒤 실제 입력 builder를 호출한다.
```

소유 경계는 아래처럼 연결한다.

| 소유자 | 실제 실행 소비 지점 |
|---|---|
| Design | `_resolve_constraints`와 실제 geometry 생성 입력. 치수와 제조 가능 범위 검증 |
| Equipment | `_equipment_skill_flow`, `_run_equipment_skill_flow`, `_run_equipment_skill`의 method/runtime 입력 |
| Analysis | `_cae_payload`, `_metrics`의 geometry/계산 구간, ObjectiveService 연계 |
| BO | `run`과 `run_with_settings` 공통 유효 설정·관측·parameter space |
| ORC | 기존 planning cycle budget/종료 조건·초기 설계 호출 |

- [ ] scope별 저장을 구현한다. 새 설정은 캠페인/다음 실행 scope에만 저장하며 다른 캠페인이나 실행 중 run의 전역 프로필을 덮어쓰지 않는다. 활성 run은 고정 ref로 실행한다. 각 workspace가 현재 캠페인 scope를 편집할 때 같은 adapter를 사용한다.
- [ ] 직접 workspace 수정도 소유 revision을 증가시키고 기존 event 경로로 알려 관련 캠페인을 stale/draft로 표시한다. 신규 캠페인 저장소로 값만 복제해서 변경이 단절되지 않도록 한다.
- [ ] 무설정 direct agent 실행, 서로 다른 두 scope 격리, stale hash, 동일 operation 재시도 테스트를 추가하고 PASS를 확인한다. 실제 장비를 호출하지 않는다.

## Task 3: Equipment 시험 설정을 실제 method 입력에 적용

**Files:** Modify `agents/equipment_settings.py`, `agents/equipment_agent.py`, `utils/equipment_skill_runtime.py`, `utils/equipment_skill_workflow.py`, `device_bridges/windows_pyautogui_bridge.py`, `Pyautogui_server_for_window/bridge/windows_pyautogui_bridge_server.py`; Create `utils/equipment_method_settings.py`; Test `tests/unit/test_equipment_method_settings.py`, `tests/unit/test_equipment_campaign_runtime_values.py`.

**Interfaces:** `compression_displacement_mm(initial_height_mm: float, target_strain: float) -> float`; `validate_method_readback(expected: dict, observed: dict, tolerances: dict) -> None`. method 필드 이름·물리량·단위·허용 범위·UI locator·입력 skill 참조는 Equipment 소유 매핑이다.

- [ ] 40% 변경과 지그 높이 혼동 방지 테스트를 먼저 작성한다.

```python
import pytest
from utils.equipment_method_settings import compression_displacement_mm, validate_method_readback


@pytest.mark.parametrize("height,strain,expected", [(30.0, 0.4, 12.0), (32.0, 0.35, 11.2)])
def test_displacement_uses_variables(height, strain, expected):
    assert compression_displacement_mm(height, strain) == pytest.approx(expected)


def test_ack_without_matching_readback_is_not_verified():
    with pytest.raises(ValueError, match="METHOD_READBACK_MISMATCH"):
        validate_method_readback({"stroke_mm": 12.0}, {"stroke_mm": 15.0}, {"stroke_mm": 0.01})
```

- [ ] Run `.venv/bin/python -m pytest tests/unit/test_equipment_method_settings.py tests/unit/test_equipment_campaign_runtime_values.py -q`; 신규 경로 부재의 FAIL을 확인한다.
- [ ] 파생값 계산은 아래처럼 구현하고, 장비별 상한은 소유 profile 검증으로 별도 적용한다.

```python
import math


def compression_displacement_mm(initial_height_mm, target_strain):
    if isinstance(initial_height_mm, bool) or isinstance(target_strain, bool):
        raise ValueError("COMPRESSION_SETTINGS_INVALID")
    h, e = float(initial_height_mm), float(target_strain)
    if not math.isfinite(h) or not math.isfinite(e) or h <= 0 or not 0 < e < 1:
        raise ValueError("COMPRESSION_SETTINGS_INVALID")
    return h * e


def validate_method_readback(expected, observed, tolerances):
    for field, value in expected.items():
        if field not in observed or field not in tolerances:
            raise ValueError("METHOD_READBACK_REQUIRED")
        got, wanted, tolerance = float(observed[field]), float(value), float(tolerances[field])
        if not all(math.isfinite(x) for x in (got, wanted, tolerance)) or tolerance < 0:
            raise ValueError("METHOD_READBACK_INVALID")
        if abs(got - wanted) > tolerance:
            raise ValueError("METHOD_READBACK_MISMATCH")
```

- [ ] 기존 `runtime_context → runtime_values → equipment.pyautogui.run`에 아래 명시적 수치 키를 연결한다.

```json
{
  "runtime_values": {
    "specimen_initial_height_mm": 30.0,
    "utm_target_strain": 0.4,
    "utm_target_displacement_mm": 12.0
  }
}
```

위 값은 테스트 사례이며 기본값이 아니다. 허용 키·타입·단위를 skill schema와 Windows server allowlist 양쪽에서 일치시킨다. `{placeholder}` 문자열 발견만으로 허용하지 않고 Equipment 소유 입력 계약으로 검사한다. robot clearance와 CSV 값은 기존 동작을 유지한다.
- [ ] 기존 시험 시작 checkpoint 내부에서 `method 설정 → 저장 → 실제 필드 읽기 확인 → 기존 start_test` 순서를 연결한다. 기존 UTM top-level stage/agentic block 순서는 유지하고 새로운 실험 실행 경로를 만들지 않는다. 등록된 정확한 skill 버전을 사용하고 deployed package를 덮어쓰지 않는다.
- [ ] **현재 확인한 패키지는 method 변경을 보장하지 않는다.** `utm_monitor_contact_and_run@1.0.6`은 완료 대기이고 `utm_start_test@1.0.11`은 기존 시작 경로다. method 입력 capability가 없으면 새 버전의 기존 시작/설정 skill에 입력·저장·readback을 추가해야 한다. 시각 locator는 기존 검증된 녹화 자산을 사용하며 임의 좌표·OCR 수치를 만들어내지 않는다. 필요한 실제 UI 자산이 없으면 그 항목은 `METHOD_SETTING_CAPABILITY_UNAVAILABLE`로 미완료를 보고한다. 이 경우 계약 단위 테스트 통과를 실제 장비 연동 완료로 주장하지 않는다.
- [ ] `configured`, `runtime_prepared`, `device_verified`를 구분한다. Setup 저장 시 장비를 호출하지 않는다. 기존 실행 요청 후 장비 설정 단계가 실제 값을 읽었을 때만 `device_verified`로 표시한다. 읽기 확인 실패는 기존 시작을 차단한다. 설정을 변경하지 않은 기존 method 사용 경로는 보존한다.
- [ ] readback 증거는 동일 profile/method와 현재 실행 sequence·설정 revision에 연결하고 입력 저장 이후 촬영/조회된 것인지 확인한다. 이전 스크린샷이나 요청값을 복사한 ACK는 읽기 확인으로 인정하지 않는다. 수치 비교 전에 단위를 소유 매핑으로 일치시킨다.
- [ ] skill package/브릿지 배포물은 기존 `Pyautogui_server_for_window` 배포 구조를 갱신 대상으로 한다. 다른 위치에 임의 zip을 만들지 않는다. 계획 실행 중에도 별도 승인 없이 실제 Windows 배포·장비 설정은 하지 않는다.
- [ ] fake pyautogui/스크린 증거 fixture로 입력값 변경·단위 오류·readback 불일치·start 미호출을 검증한다. mocked evidence에는 simulated 표시를 남긴다.

## Task 4: Analysis·CAE·BO 목적 계약의 실제 변수화

**Files:** Modify `agents/analysis_settings.py`, `agents/analysis_agent.py`, `objectives/metric_registry.py`, `objectives/service.py`, `objectives/evaluator.py`; Verify/extend only when required `objectives/compiler.py`; Verify `mcp_tools/cae_tools.py`, `utils/calculix_quasistatic.py`; Test `tests/unit/test_analysis_campaign_settings.py`, 기존 `tests/unit/test_analysis_agent.py`, `tests/unit/test_calculix_quasistatic.py`.

**Interfaces:** `_metrics(curve, geometry, *, evaluation_strain: float) -> dict`; `_cae_payload`는 Analysis 소유의 `cae_target_strain` 유효값을 소비한다. 신규 지표는 `energy_density_at_target_strain_MJ_per_m3`, 구간 필드는 `evaluation_strain`이다. 기존 50% 지표는 정의를 바꾸지 않는다.

- [ ] 실제 계산 결과가 설정에 따라 달라지는 테스트를 추가한다.

```python
import pytest
from agents.analysis_agent import AnalysisAgent


def test_analysis_integrates_the_selected_fraction():
    curve = [{"displacement_mm": float(i), "force_N": float(i * 100)} for i in range(16)]
    geometry = {"cross_section_area_mm2": 100.0, "gauge_length_mm": 30.0, "mass_g": 1.0}
    a = AnalysisAgent()._metrics(curve, geometry, evaluation_strain=0.4)
    b = AnalysisAgent()._metrics(curve, geometry, evaluation_strain=0.5)
    assert a["energy_density_at_target_strain_MJ_per_m3"] == pytest.approx(2.4)
    assert b["energy_density_at_target_strain_MJ_per_m3"] == pytest.approx(3.75)
    assert a["energy_density_50pct_MJ_per_m3"] == b["energy_density_50pct_MJ_per_m3"]
```

- [ ] Run `.venv/bin/python -m pytest tests/unit/test_analysis_campaign_settings.py -q`; 신규 계산 인자 부재로 FAIL을 확인한다.
- [ ] 분석 함수의 구간·geometry fallback을 제거하고 호출 직전에 `AnalysisSettings.read_effective`로 기본값/명시값/연결값을 해석한다. 신규 함수 호출 인자는 명시적으로 전달한다.

```python
settings = analysis_settings.read_effective(settings_ref, context)
metrics = self._metrics(curve, geometry, evaluation_strain=settings["evaluation_strain"])
cae_loading["target_strain"] = settings["cae_target_strain"]
```

위 세 변수는 기존 실행 context에서 주입한다. method/Analysis/CAE의 `follow` 관계를 활성화한 경우에만 함께 변경한다. 무설정 legacy는 기본 설정 50% 등 기존 의미를 유지한다. Geometry는 기존 Design/실제 제작 계약에서 우선 가져오고, 기존 기본 치수가 적용된 실행도 그 해석 결과와 출처를 남긴다.
- [ ] 요청 구간의 에너지·최대하중과 전체 구간 지표를 분리한다. 과거 `_50pct` 키는 언제나 50%의 값이며 목표 40%의 값을 넣지 않는다. 측정이 50%에 미달하면 기존 50% 지표는 유효값이 아닌 것으로 남긴다. 부피/단위 변환과 목표 구간 도달 여부를 검증한다.
- [ ] `MetricRegistry`에 신규 연동형 지표를 등록한다. ObjectiveSpec의 metadata에 Analysis 설정 ref·계산 구간/프로토콜을 넣고 canonical objective hash 및 evaluator의 관측 일치 검사에 포함한다. metadata가 hash에 포함되는지 테스트로 확인하고 빠져 있으면 기존 compiler canonicalization을 최소 확장한다.
- [ ] BO가 소비할 목적을 기존 ObjectiveService의 검증·승인·활성화로 갱신한다. 연결형 목적의 구간 변경은 미리보기에서 드러내고 기존 확인 경로를 사용한다. 고정 50% 목적을 몰래 바꾸지 않는다. 변경 전후 관측의 목적/구간이 다르면 자동 혼합하지 않는다.
- [ ] CAE tool 입력과 생성 deck의 목표 압축량까지 검증한다. solver/장비를 실행할 필요는 없다. 실제 shape 높이·gauge 정의 불일치는 오류로 처리하고 숨은 치수로 보정하지 않는다.
- [ ] 신규·기존 Analysis/CalculiX 단위 테스트 PASS를 확인한다. 현재 목적값/곡선 계산 회귀를 별도로 보고한다.

## Task 5: ORC 변경 전파·캠페인 저장·실행 바인딩

**Files:** Create `app/campaign_service.py`; Modify `app/controller.py`, `app/main.py`; Test `tests/unit/test_campaign_service.py`, `tests/unit/test_controller_campaign.py`.

**Interfaces:** `CampaignService(owners: dict[str, OwnerSettingsPort], store)`; `apply_change(campaign_id: str, *, expected_revision: int, operation_id: str, changes: dict) -> dict`. store는 기존 기록 체계 안에 캠페인 참조 묶음을 저장하며 `publish(campaign_id, expected_revision, bundle)`은 revision 비교 후 원자적으로 현재 참조를 변경한다.

- [ ] 새 revision이 부분 반영 상태로 공개되지 않는 테스트를 작성한다. 아래 테스트용 owner는 실제 적용 확인 실패를 재현한다.

```python
class FailingReadbackOwner:
    def prepare(self, patch, context):
        return {"values": patch, "scope_id": context["scope_id"]}
    def persist(self, prepared, *, operation_id):
        return {"owner": "analysis", "scope_id": prepared["scope_id"], "revision": 2,
                "sha256": "fixture", "storage_ref": "fixture://analysis/2"}
    def read_effective(self, ref, context):
        raise ValueError("SETTING_READBACK_MISMATCH")


def test_failed_owner_readback_does_not_publish(tmp_path):
    import pytest
    from app.campaign_service import CampaignService, CampaignReferenceStore
    store = CampaignReferenceStore(tmp_path)
    store.publish("campaign-a", 0, {"revision": 1, "owner_refs": {}, "bindings": []})
    service = CampaignService(owners={"analysis": FailingReadbackOwner()}, store=store)
    with pytest.raises(ValueError, match="SETTING_READBACK_MISMATCH"):
        service.apply_change("campaign-a", expected_revision=1, operation_id="op-2",
                             changes={"analysis": {"evaluation_strain": 0.4}})
    assert store.read("campaign-a")["revision"] == 1
```

- [ ] Run `.venv/bin/python -m pytest tests/unit/test_campaign_service.py tests/unit/test_controller_campaign.py -q`; FAIL을 확인한다.
- [ ] 위 API와 `CampaignReferenceStore.read(campaign_id) -> dict`, `publish(...) -> dict`를 구현한다. 실행 알고리즘은 `현재 revision 확인 → 영향 연결 계산/순환 검사 → 모든 소유자 prepare → 비활성 revision persist → 저장 참조로 read_effective → 실행 입력/목적 호환 검사 → bundle publish`다. 계산된 값의 단위 변환은 소비 소유자 함수가 수행한다.

```python
# apply_change 내부의 공개 경계; prepared_refs는 owner 저장 참조다.
bundle = {
    "revision": expected_revision + 1,
    "owner_refs": prepared_refs,
    "bindings": resolved_bindings,
    "receipts": verified_receipts,
    "operation_id": operation_id,
}
return self.store.publish(campaign_id, expected_revision, bundle)
```

- [ ] 실패 시 이전 active bundle을 유지하고 실패 owner/reason/준비된 ref를 기록한다. 실제 장비에 보상 동작을 보내는 자동 rollback은 하지 않는다. 비활성 revision은 진단에 보존한다. 실행 중 run은 이전 고정 bundle을 계속 사용하고 새 bundle은 다음 명시적 허용 경계에서 적용한다.
- [ ] 기존 planning action/채팅 경로에 설정 변경 intent를 추가하고 같은 service를 호출한다. 동기화는 기존 lock/revision 경로를 재사용한다. 별도 캠페인 서버·모든 단계 승인·runtime 상태 머신을 만들지 않는다.
- [ ] `planning_snapshot`에 현재 슬롯/캠페인/소유 설정 source/적용 상태를 작게 투영한다. 읽기에는 persist/start 부작용이 없다. 최초 ORC 안내는 기존 transcript에서 멱등 처리한다.
- [ ] 기존 `start`, `_handoff_planning_to_design`, 초기 LHS 및 다음 Design 경계에서 현재 유효 bundle을 참조하도록 연결한다. 캠페인이 없으면 소유 기본 설정으로 구성한 runtime snapshot을 사용한다. 기존 safety 검사·mode·cycle 흐름은 변경하지 않는다.
- [ ] 변경 중 stale revision, 동일 operation 중복, 다른 payload의 operation 재사용, owner 일부 실패, 준비 완료 뒤 start 전 revision drift를 각각 검사한다. 저장된 것과 실제 tool 입력에 사용된 것을 별도로 기록한다.

## Task 6: BO 연속값·설정 가능한 LHS·Design 끝단 연결

**Files:** Modify `agents/bo_settings.py`, `agents/bo_agent.py`, `agents/design_settings.py`, `agents/design_agent.py`, `learning/bo_parameter_space.py`, `app/controller.py`; Verify `learning/botorch_backend.py`; Test `tests/unit/test_campaign_continuous_bo.py`, 기존 `tests/unit/test_bo_agent.py`, `tests/unit/test_bo_parameter_space.py`.

**Interfaces:** 기존 `BOParameterSpace.from_mapping`이 `{kind, bounds/values/value}` 형태를 추가 수용한다. 과거 배열 API의 의미는 그대로 유지한다. 캠페인 신규 타입 표현을 배열로 납작하게 바꿔 이산 두 값을 연속으로 오인하지 않는다.

- [ ] 타입과 연속 후보 보존 테스트를 먼저 작성한다.

```python
from learning.bo_parameter_space import BOParameterSpace


def test_two_discrete_values_are_not_a_continuous_interval():
    space = BOParameterSpace.from_mapping({"cell_size_mm": {"kind": "discrete", "values": [5, 10]}})
    assert space.dimensions[0].kind == "discrete"


def test_non_grid_continuous_candidate_round_trips():
    space = BOParameterSpace.from_mapping({
        "cell_size_mm": {"kind": "continuous", "bounds": [5, 10]},
        "relative_density": {"kind": "continuous", "bounds": [0.20, 0.48]},
    })
    point = {"cell_size_mm": 6.37, "relative_density": 0.317}
    restored = space.decode(space.encode(point))
    assert abs(restored["cell_size_mm"] - point["cell_size_mm"]) < 1e-10
```

- [ ] Run `.venv/bin/python -m pytest tests/unit/test_campaign_continuous_bo.py -q`; 신규 typed mapping 경로가 없어 FAIL인지 확인한다.
- [ ] ParameterDimension을 생성하는 기존 parser를 타입별로 확장한다. `continuous`는 finite ascending bounds, `discrete`는 고유 값 목록, `fixed`는 단일 값으로 검증한다. bool/NaN/inf와 잘못된 명시값을 기본값으로 교체하지 않는다.
- [ ] BO의 숨은 도메인 교체·clamp·후보 잠금을 캠페인 활성변수/고정변수 설정으로 대체한다. settings 미설정은 `agent_defaults.yaml`과 기존 프로필에서 현재 기본 도메인을 읽는다. 사용자 범위나 활성 연결이 잘못된 경우에만 실패한다.
- [ ] LHS 크기/seed를 BO 소유 변수로 소비한다. backend의 알고리즘상 최소 샘플 제약은 유지하되 8을 플랫폼 고정 예산으로 사용하지 않는다. 초기 데이터 없이 기존 LHS 진입이 되고, 유효한 고유 관측만 warm-up 진척으로 센다.
- [ ] 아래 불변식을 실제 BO→ORC→Design 경로 테스트에 적용한다.

```python
assert bo_result["next_design_request"]["constraints"]["cell_size_mm"] == selected["cell_size_mm"]
assert design_request["requested_parameters"]["cell_size_mm"] == selected["cell_size_mm"]
assert generated_candidate["parameters"]["cell_size_mm"] == selected["cell_size_mm"]
```

각 변수는 기존 경로의 실제 반환값에서 가져온다. Design은 해당 타입의 범위/제조 가능성을 검증하고 거부 사유를 반환할 수 있지만 가까운 이산값으로 바꾸지는 않는다. 생성 STL의 형상 메타데이터와 실제 사용 파라미터까지 확인한다.
- [ ] 관측에 objective/analysis 구간·fidelity·실제 파라미터·캠페인 ref를 연결한다. 수치 최적화 실패는 기존 실패 경로로 반환하고 LLM/임의 후보로 대체하지 않는다. 이산/연속 혼합 최적화도 보존한다.
- [ ] 기존 BoTorch 엔진 파일은 재구현하지 않는다. 타입/초기 설계 설정을 소비하는 최소 경계 확장이 필요한 경우에만 수정하고 기존 GP/LogEI 수학은 유지한다.

## Task 7: Setup·에이전트 workspace·채팅의 동일 설정 반영

**Files:** Modify `web/static/planning.js`, `web/static/styles.css`, `app/main.py`, `web/static/equipment_skill_workflow_editor.js`; Test `tests/unit/test_planning_campaign_js.py`, `tests/integration/test_campaign_settings_api.py`.

**Interfaces:** `currentCampaignModel(session)`는 현재 서버의 `experimental_slot`, `campaign`, `owner_settings`를 읽는다. 과거 보고서 선택 상태를 읽지 않는다. UI의 설정 action은 소유/field/scope/revision/mode/value 또는 source ref를 전송한다.

- [ ] 현재 설정과 과거 report가 섞이지 않고 무설정 상태를 오류로 취급하지 않는 JS 실행 테스트를 작성한다. 기존 Node helper 추출/실행 패턴을 사용한다.

```javascript
function currentCampaignModel(session) {
  const s = session || {};
  return {
    slot: s.experimental_slot || {status: "unavailable"},
    campaign: s.campaign || null,
    owners: s.owner_settings || {},
  };
}
```

테스트는 `campaign:null`이더라도 owners의 기본 설정이 보이고 `Use defaults` 상태임을 확인한다. selected report의 값으로 owners를 덮어쓰면 실패해야 한다.
- [ ] 기존 Setup 위에 Compression Test 카드 하나를 추가한다. 클릭은 Setup을 열기만 하고 실행/설정 저장 요청을 보내지 않는다. 기존 graph에 연결되지 않으면 압축시험으로 임의 기본 연결하지 않는다.
- [ ] Setup 내부를 소유자별 설정 그룹으로 표시한다. 값 옆에 `Default`, `Profile`, `Explicit`, `Linked` 출처와 연결 원본을 보여준다. 모든 값을 필수 입력으로 만들지 않는다. 나중에 연결할 수 있도록 같은 필드에서 binding mode를 바꿀 수 있게 한다.
- [ ] 적용 상태는 `Draft`, `Configured`, `Runtime prepared`, `Device verification pending`, `Device verified`, `Failed`로 분리한다. 일부 owner 실패나 단순 ACK를 전체 Applied로 표시하지 않는다. 이 상태는 UI/증거 투영이며 새 실행 상태 머신이 아니다.
- [ ] GUI 편집과 채팅은 같은 소유 서비스 호출 경로를 사용한다. 에이전트 workspace에서 설정해도 현재 campaign scope라면 같은 상태가 보인다. 기존 Equipment profile/skill-flow endpoints는 같은 소유 validation을 위임하도록 확장한다.
- [ ] 클릭/Enter/Space, 설정 저장, 채팅 변경에서 hardware/start API가 호출되지 않는지 mock/spy로 확인한다. 기존 실행 버튼만 기존 start 경로를 사용한다.

## Task 8: 기존 비구동 폐루프 회귀·문서 갱신

**Files:** Create `tests/integration/test_campaign_closed_loop.py`; Extend `tests/unit/test_controller_campaign.py`; Modify after implementation `docs/runtime/autonomous_experiment_runtime.md`, `docs/agents/orchestrator_agent.md`, `docs/agents/analysis_agent.md`, `docs/agents/bo_agent.md`, `docs/agents/equipment_agent.md`, `README.md`, `README.en.md`, `README.ko.md`. README 기존 문서 표는 runtime 문서로 연결한다.

**Interfaces:** 기존 runtime/controller/agent 경로를 실행하고 외부 장비·LLM·무거운 solver 경계만 mock한다. 핵심 handoff 함수 전체를 성공 반환으로 바꾸지 않는다. evidence에는 비구동/simulated 범위를 명시한다.

- [ ] 다음 matrix를 parameterized fixture로 준비한다. fixture는 임시 설정 store와 가짜 method 읽기 결과/측정 CSV를 사용하며 실제 운영 서버를 호출하지 않는다.

| 사례 | 확인할 실제 결과 |
|---|---|
| 캠페인/사용자 설정/연결 없음 | 기존 저장 프로필·기본값으로 같은 실행 입력, 새 필수 문답 없음 |
| 30 mm·40%, 모든 관련 필드 follow | Equipment 12 mm method 요청, CAE 0.4, Analysis 0.4 적분, BO 연동 목적 ref 일치 |
| 32 mm·35%, follow | 11.2 mm로 계산, 30/40/12 하드코딩이 없음 |
| 분석 구간 fixed 50%, 시험 40% | 50% 의미 유지, 불충분한 목적 조건을 명시하고 가짜 40% 목적값으로 학습 안 함 |
| 연결 원본 실패/잘못된 사용자 값 | 기본값으로 숨기지 않고 오류, 새 revision 공개 없음 |
| owner apply 성공/실제 readback 실패 | 캠페인 적용 완료로 표시 안 함; 장비 시작은 미호출 |
| runtime 준비 완료/장비 미접속 | Configured와 Device verified 구분; 편집 시 장비 호출 없음 |
| 실행 중 변경 | 현재 run의 고정 refs 유지, 다음 허용 경계에만 적용 |
| 두 숫자 이산/연속/고정 변수 | 타입 유지, 연속 6.37이 형상 생성/관측까지 보존 |
| LHS 설정·예산 변경 | owner 설정을 사용, 유효 고유 관측/시도/반복을 구분 |
| 기존 테스트·실제 프린터 모드 | 기존 장비 프로필/출력 skip/이젝션/안전 latch·UTM 흐름 보존 |
| 과거 보고서·기록 재조회 | 현재 설정 안 바뀜, 과거 50% 지표 의미와 아티팩트 경로 유지 |

- [ ] 다음 실제 경계 assertion을 통합 fixture의 captured 입력에 적용한다.

```python
assert equipment_call["runtime_values"]["utm_target_displacement_mm"] == 12.0
assert cae_call["loading"]["target_strain"] == 0.4
assert analysis_result["metrics"]["evaluation_strain"] == 0.4
assert observation["objective_hash"] == active_objective["objective_hash"]
assert campaign_bundle["owner_refs"]["analysis"] == run_binding["owner_refs"]["analysis"]
```

테스트용 12/0.4는 별도 32/0.35 사례에서도 바뀌어야 한다. 원래 50% 지표를 현재 target 변수의 별칭으로 재사용하지 않는다.
- [ ] 단계별 신규 테스트를 먼저 실행하고 기존 관련 테스트를 실행한다. 명령은 계획 실행 때 사용할 것이며 이 문서 작성으로 수행한 테스트가 아니다.

```bash
.venv/bin/python -m pytest tests/unit/test_agent_settings.py tests/unit/test_agent_owned_settings.py tests/unit/test_experimental_slots.py tests/unit/test_campaign_service.py tests/unit/test_controller_campaign.py -q
.venv/bin/python -m pytest tests/unit/test_equipment_method_settings.py tests/unit/test_equipment_campaign_runtime_values.py tests/unit/test_analysis_campaign_settings.py tests/unit/test_campaign_continuous_bo.py -q
.venv/bin/python -m pytest tests/unit/test_planning_campaign_js.py tests/integration/test_campaign_settings_api.py tests/integration/test_campaign_closed_loop.py -q
.venv/bin/python -m pytest tests/unit/test_analysis_agent.py tests/unit/test_bo_agent.py tests/unit/test_bo_parameter_space.py tests/unit/test_calculix_quasistatic.py tests/unit/test_agent_artifact_archive.py -q
node --check web/static/planning.js
git diff --check
```

- [ ] 기존 controller planning 테스트 중 printer mode/profile·초기 LHS·BO redesign·safety latch 회귀도 해당 fixture의 외부 호출 mock 여부를 확인한 뒤 실행한다. 관련 없는 기존 실패와 신규 실패를 구분하고 미실행은 `not run`으로 남긴다.
- [ ] 구현 완료 후 reference 문서에 소유권 표, 기본값→명시값/연결값의 출처, 실제 변경 전파 도표, 적용/장비 확인 상태, 연속 BO/목적 구간 호환성, 설정 없는 사용 방법을 추가한다. 현재 계획을 구현 사실이나 물리 실증으로 적지 않는다.
- [ ] UTM method 설정용 검증된 UI 자산/배포 capability가 확보되지 않았으면 해당 항목은 미완료로 명시한다. 나머지 설정 변수화·offline 적용 테스트를 할 수 있어도 이를 전체 완료로 대신하지 않는다.
- [ ] 변경 파일·비구동 검증 결과·실장비 미검증 범위를 보고한다. 커밋/푸시/운영 반영은 별도 요청을 기다린다.

## 4. 자체 검토 기준

- 슬롯·연구 캠페인·연속값이 모두 구현 범위에 있다.
- 소유 에이전트가 값을 실제 적용하고 캠페인은 그 참조를 묶는다. ORC가 모든 설정의 주인이 되지 않는다.
- 기존 설정 없는 실행은 기본 설정으로 유지한다. 변수화가 사용자의 필수 입력 증가가 되지 않는다.
- 나중에 연결하는 변수도 동일 소유 API/field id를 사용한다. 연결을 켠 뒤의 실패는 기본값으로 숨기지 않는다.
- 40% 예시는 설정 저장뿐 아니라 method 요청·CAE·Analysis 실제 계산·BO 목적 일치까지 검증한다.
- 기존 50% 과학 지표·장비 안전 한계·사용자가 고정한 값은 의미를 보존한다.
- 실제 장비 확인과 mocked 확인을 구분하며 사용자가 승인하지 않은 장비 동작을 수행하지 않는다.
- 이 계획은 문서 검토용이다. 코드 수정·실장비 테스트·커밋은 아직 수행하지 않았다.
