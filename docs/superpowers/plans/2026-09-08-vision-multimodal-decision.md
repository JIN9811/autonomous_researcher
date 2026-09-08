---
doc_type: plan
subtype: implementation
status: active
authority: execution
execution_status: completed
governing_design: docs/superpowers/specs/2026-09-07-five-area-agent-restructuring-contract-design.md
audience: [developer, maintainer]
scope: [agents, vision, decision_tools, multimodal]
summary: Shared image forwarding and bounded Vision decisions using existing verification routes.
source_of_truth:
  - agents/vision_decision.py
  - agents/vision_agent.py
  - orchestrator/langgraph_runtime.py
last_verified: 2026-09-08
verified_against: working-tree
related_docs:
  - docs/agents/vision_agent.md
  - docs/superpowers/specs/2026-09-07-five-area-agent-restructuring-contract-design.md
supersedes: []
---

# Vision Multimodal Decision Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [x]`) syntax for tracking.

**Goal:** 공통 이미지 입력을 기존 모듈 LLM 경로에 연결하고 Vision의 국소 판단에 사용한다.

**Architecture:** 기존 `LLMImageInput`을 AgentContext → ModuleRuntimeContext → 등록 backend 전체에 보존한다. Vision은 기존 검출 사실과 동일 캡처에서 얻은 원본/표시 이미지를 검토하고, 엄격히 제한된 로컬 도구를 선택한다. 장비 드라이버와 폐루프 경로는 변경하지 않는다.

**Tech Stack:** Python, pytest, existing OpenAI-compatible API/vLLM clients, Markdown/Graphviz.

**Spec:** `docs/superpowers/specs/2026-09-07-five-area-agent-restructuring-contract-design.md`

## Global Constraints

- 실제 장비 구동, 서비스 재시작, 설정된 모델 변경, 커밋/푸시는 이번 작업에 포함하지 않는다.
- 현재 작업 경로를 유지하고 기존 미커밋 문서 변경을 보존한다.
- 모델은 좌표·검출 임계값·모드·승인·장비 명령을 생성하거나 변경하지 않는다.
- ActiveCam은 이동/촬영/복귀 복합 도구다. 모델 오류로 자동 재실행하지 않는다.
- 진행 중 rollout/replay 감시와 안전 정지를 LLM 응답 뒤로 미루지 않는다.
- 이미지 판단은 캡처에 귀속된다. 기존 신호 TTL을 늘리거나 timestamp를 새로 찍지 않는다.
- 명시적 비LLM TEST 결과는 실제 모델 검증이나 물리 검증으로 표시하지 않는다.

### Task 1: Generic module image input

**Files:** `orchestrator/langgraph_runtime.py`, `backends/llm_backend.py`, `tests/unit/test_module_multimodal.py`.

**Interfaces:** `complete(..., images: list[LLMImageInput] | None = None)` preserves every lease/model/backend fallback; text-only callers retain their original kwargs. Images have ordered labels; mock responses cannot prove visual judgment.

- [x] RED: a backend spy receives the same ordered images after the first backend/model fails; the old module raises `TypeError` before forwarding.
- [x] GREEN: add optional `images` to both module methods and conditionally forward it to backend calls; preserve labels in shared serialization.
- [x] VERIFY: `pytest -q tests/unit/test_llm_multimodal.py tests/unit/test_module_multimodal.py tests/unit/test_langgraph_runtime.py`.

### Task 2: Bounded Vision decisions and existing routes

**Files:** new `agents/vision_decision.py`, `agents/vision_agent.py`, `utils/utm_clear_cycle.py`, new `tests/unit/test_vision_decision.py`.

**Interfaces:** `select_vision_tool(state, ctx, contract_id)` returns an auditable decision, not hardware arguments. `review_visual_evidence(state, ctx, capture, contract_id)` returns `vision_decision.v1` with same-frame image digests, concise model output, status and identity.

- [x] RED: synthetic image fixtures plus a strict model stub prove that both images reach the backend, unsupported tool arguments are rejected, model acceptance cannot change detector values, missing images/stop/scope changes fail closed.
- [x] GREEN: restricted JSON tool selection (`execute_verification`, `accept_visual_evidence`, `return_to_owner`) with one call per checkpoint, bounded timeout, identity/spec snapshot and stop rechecks.
- [x] CONNECT: replace format-only preamble for pickup capture with `execute_verification` before the existing branch. Review pickup images after capture; review placement only after the existing verified stop; review clearance only after replay completion/home verification. Pending monitoring has no model await.
- [x] GUARD: unresolved review suppresses ready/completion/handoff signals and preserves raw detector facts and stop acknowledgement. Never extend evidence expiry. Failed review requests safe stop/review, not automatic ActiveCam motion retry.
- [x] VERIFY: focused Vision, intervention, clearance, archive and module regressions; immutable recorded image probes only, if registered model services are available.

### Task 3: Reference and evidence

**Files:** existing Vision reference, three Vision DOT/SVG figure pairs, five-area design, module manifest.

- [x] Update five-area table, 5–7-line status, ordered raw/annotated image contract, bounded decisions, actual validation and known latency limitations.
- [x] Update existing figures in place and render with `dot -Tsvg`; keep existing entry links.
- [x] Check changed-doc references and `git diff --check`; report actual checks without claiming hardware validation.

## Timing decision

Multimodal review supersedes the earlier text-only proposal. Capture-derived pickup signals keep their original five-second expiry: slow inference can yield review-required rather than executable pickup. Placement stop is a separate safe physical fact and precedes model review; rejection never restarts the stopped rollout. Clearance review begins only after managed replay has completed. No new background supervisor or automatic motion retry is introduced.

## Verification Result

- 최종 선택 회귀: 266 passed, 10 existing warnings, 10.55초. Vision/clearance/intervention, artifact probe loader, equipment-vision, 전체 에이전트 loop archive, 공통 multimodal/module/lease, 문서 검증 테스트 포함.
- 별도 공통 모듈 및 전체 LangGraph runtime 회귀: 99 passed, 10 existing warnings, 183.10초. 두 실행은 일부 중복되므로 합산하지 않는다.
- 등록 API 및 vLLM 이미지 fixture probe: 8/8 accepted. 실제 장비 tool 미등록, 원본 fixture hash 불변. 세부 응답시간과 한계는 Vision Reference에 기록한다.
- 추가 기존 아티팩트 교차검증: 자연 입력 8종과 메모리상 모순 입력 5종을 API `gpt-5.5` / 로컬 vLLM `gemma4:31b`에 각각 전달해 총 26회 응답, timeout 없음. 원본 이미지 hash와 과거 timestamp는 보존했다. API 4.061–9.787초, 로컬 6.234–9.964초였다.
- 사전 기대 tool 선택과 일치한 수는 API 8/13, 로컬 9/13이며 정확도나 전체 통과율이 아니다. 둘 다 잘못된 수치 bbox, 다른 카메라 이미지 조합, 압축/비압축 이미지 조합의 모순을 놓쳤다. detector가 clear로 기록한 한 영상에서는 두 모델의 판단이 달랐다. 로컬의 두 반려 응답은 의미상 모순을 지적했지만 `contract_id` 인자를 누락해 schema 검증에서 차단됐다.
- 과거 ActiveCam 입력은 모델 수락 후에도 expired로 차단됐다. detector unknown/occupied를 모델이 수락해도 clearance 완료나 Analysis로 넘어가지 않는 두 회귀 테스트를 추가 확인했다. 이미지 쌍의 출처·좌표 정합성을 LLM 판단만으로 보장하지 않는다. 결과에 맞춘 production prompt/로직 조정은 하지 않았다.
- 코드 리뷰에서 발견한 취소/세션 교체, 시편 metadata 변경, clearance 기한/terminal 상태, STOPPED 정규화, blocked observation 계약을 회귀 테스트로 확인했다.
- 실제 장비 구동과 LIVE 폐루프는 검증하지 않았다. LIVE의 5초 신호 유효시간과 기존 TEST 전용 120초 유예 정책을 변경하지 않았다. 로컬 모델 이미지 검토가 약 8.3초이므로 LIVE에서는 별도 최신 관측이 필요할 수 있다.
- 커밋·태그·푸시 또는 서비스/모델 설정 변경은 수행하지 않았다.

## Approved Generic Prompt Refinement

- 사용자 승인 후 한 후보를 적용했다. 실험별 상수를 제거하고 pair → location → validity → claim 순서로 대조하며, 실제 raster 크기와 기존 validity 사유를 전달한다. 수락/반려 JSON 예시는 모두 필수 `contract_id`를 포함한다.
- 검증 loader의 미지정 재질 기본값을 제거하고 기존 프롬프트부터 같은 조건으로 재측정했다. 기대 판단 일치는 API 10/13 → 12/13, 로컬 9/13 → 12/13이었다. 로컬 유효 응답 계약은 11/13 → 13/13이었다.
- 프롬프트를 고정한 뒤 별도 3개 촬영에서 만든 6종을 확인했다. API 6/6, 로컬 5/6 일치. 로컬은 같은 배경에서 대상 상태만 바뀐 이미지 쌍을 계속 놓쳤다. API는 개발 세트의 detector-labelled clear 영상 하나를 반려해 전부 성공이라고 표현하지 않는다.
- 총 64회 실제 모델 호출, timeout 없음, 원본 이미지 hash 불변. 후속 회귀 271 passed, 10 existing warnings, 14.18초. 프롬프트와 전달 맥락을 함께 개선한 결과이며 독립 정확도·타 실험 일반화·물리 폐루프 검증이 아니다.
- [상세 비교와 근거](../../paper/evidence/2026-09-08-vision-generic-prompt-verification.md). 기존 제어 경로·parser·safety gate·timeout은 변경하지 않았다.

## Release Verification Exception

- 개선 후 프롬프트의 현재 판단 순서, 입력 해석, 수락/반려 JSON 계약은 Vision Reference의 `Current Prompt Contract`에 기록했다.
- 전체 pytest 기본 실행은 기존 `tests/replay/test_lerobot_replay.py`와 `tests/unit/test_lerobot_replay.py`의 동일 모듈명으로 수집에 실패했다.
- `--import-mode=importlib --maxfail=1`로 수집 충돌을 우회한 실행은 `tests/fault_injection/test_fault_mode.py::test_fault_injection_emits_retry_or_error`에서 실패했다. 시작 후 2초 안에 retry/fatal_error 이벤트가 있다는 assertion을 만족하지 못했으며, 이번 변경과의 인과관계는 확인하지 않았다. 전체 suite 통과로 기록하지 않는다.
- 해당 실패를 별도 후속 이슈로 남기고 현재 Vision 변경을 커밋·푸시하는 것을 사용자가 승인했다. 테스트나 기존 제어 경로를 수정해 이 실패를 숨기지 않는다. 릴리스 태그는 `Vision-Agent`이며 기존 에이전트 태그와 `closed-loop-stable`은 유지한다.
