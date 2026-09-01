# TRAPEZIUMX-V Lab Equipment Agent 운용 레퍼런스

## 목적

이 자료는 Shimadzu TRAPEZIUMX-V 압축시험을 Lab Equipment Agent로 운용하기 위한 작업 순서와 화면 상태를 정리한 레퍼런스다.

원본 영상:

- `../TRAPEZIUMX-V 2026-09-01 02-28-47.mp4`
- 길이: 약 2분 13초
- 화면: 1936 × 1056
- 오디오: 무음

영상은 실제 시편 시험 결과가 아니라 작업자가 손으로 장비 동작을 보여준 시연이다. 따라서 영상에 표시된 Force, Stroke 및 종료 위치는 합격 기준으로 사용하지 않는다. 추출 이미지는 TRAPEZIUMX-V의 UI 상태와 버튼 위치를 확인하는 용도로만 사용한다.

## 장비 데이터의 기준

- Force, Stroke, Height는 장비 센서에서 측정된다.
- 시험 제어와 완료 판정의 권위 데이터는 장비의 Force, Stroke, Height 센서값이다.
- 화면 이미지 판별은 `Ready`, `Testing`, `Tests Completed` 같은 GUI 상태를 교차 확인하는 보조 증거다.
- 카메라는 시편 배치, 로봇 퇴피, 장비의 실제 움직임을 확인하는 안전 보조 수단이다.

## 측정값 정의

| 항목 | 의미 |
|---|---|
| Force | 장비 로드셀에서 측정한 하중 |
| Stroke | 선택된 시험 method가 접촉을 판정한 시점부터 계산하는 상대 압축 이동량 |
| Height | 지그 사이의 절대 위치 또는 절대 높이값 |

Force의 부호, 접촉 판정값, Stroke 영점 및 시험 종료값은 선택된 시험 method가 소유한다. Equipment Agent는 이 값을 자체 상수로 고정하지 않고 현재 method 설정을 읽어 실행해야 한다.

## 현재 적용된 method 값과 의도

아래 숫자는 현재 시연과 시험 준비에 적용된 값이다. 장비 공통 상수나 향후 시험의 고정 합격 기준이 아니다.

| 설정 | 현재 적용값 | 설정 의도 | 소유 주체 |
|---|---:|---|---|
| 로봇 진입 높이 | 150 mm | 로봇이 시편을 안전하게 반입·회수할 수 있는 지그 간격 확보 | 셀 운용 설정 |
| 접촉 판정 하중 | 5 N | platen과 시편의 실제 접촉점을 검출하고 상대 Stroke 기준점을 설정 | 시험 method |
| 시편 기준 높이 | 30 mm | 현재 시편의 치수와 변형량 계산 기준 제공 | 시편 recipe / 시험 method |
| 목표 압축 비율 | 70% | 현재 시험에서 요구하는 목표 변형 수준 지정 | 시험 method |
| 목표 Stroke | 21 mm | 현재 시편 높이와 압축 비율로부터 계산된 상대 이동량 | 시험 method의 파생값 |
| 시험 준비 간격 | 30.5 mm | 시험 시작 전에 platen을 시편 근처의 준비 위치로 이동 | 시험 method |
| 시험 속도 | 1 mm/s | 현재 시연 method의 제어된 하강 속도 | 시험 method |

Equipment Agent가 확인해야 할 핵심은 특정 숫자와 화면 표시값의 일치가 아니라, 현재 선택된 method 값이 장비에 적용됐는지와 각 동작 이후 GUI가 예상 상태로 전환됐는지다.

## 수동 작업 범위

전체 운용에서 작업자가 수동으로 수행하는 단계는 최초 시작 시 지그를 현재 설정된 로봇 진입 높이로 맞추는 작업이다. 현재 적용값은 `Height = 150 mm`다.

최초 준비 이후의 접근, 시험, 복귀, 데이터 내보내기, 다음 시험 전환 및 150 mm 재개방은 Lab Equipment Agent 자동화 범위다.

## 로봇과 Lab Equipment Agent의 인계

1. 지그가 현재 설정된 로봇 진입 높이로 열려 있다. 현재 적용값은 `Height = 150 mm`다.
2. 로봇이 시편을 platen 위에 놓는다.
3. 로봇이 Home 위치로 완전히 퇴피한다.
4. 시편 배치와 로봇 Home 상태가 확인되면 Lab Equipment Agent가 작업을 인계받는다.
5. 로봇이 시험 장비 작업 영역에 남아 있으면 장비 동작을 시작하지 않는다.

## GUI 화면 흐름과 단계 완료 신호

숫자 자체보다 다음 화면 전환을 우선 확인한다. 각 단계의 완료는 클릭 성공이 아니라 GUI 변화, 센서 변화 및 필요한 외부 artifact가 함께 충족됐을 때 확정한다.

| 단계 | 실행 전 화면 | 실행 또는 진행 중 변화 | 단계 종료 화면과 활성 요소 | 완료 증거 |
|---|---|---|---|---|
| 로봇 배치 대기 | 지그가 현재 로봇 진입 높이에 있고 장비가 정지 | 로봇이 시편을 배치하고 Home으로 퇴피 | 장비 화면은 정지 상태 유지 | 로봇 Home 및 시편 배치 확인 |
| 시험 준비 접근 | 전체 화면을 캡처하고 `Height = 150 mm`인지 확인 | `Move jigs for the next specimen` → `Confirm crosshead movement` → OK → 지그 이동 관찰 → `Position zero reset` → OK | 이동이 멈추고 녹색 `Start Test`가 활성화 | 초기 150 mm 확인, 두 확인창 처리, Height 안정, 이동 상태 해제, Start Test 활성 |
| 시험 시작 | 녹색 `Start Test` 활성 | Start 실행 후 좌측 상태가 청록색 `Testing`으로 바뀌고 Start가 비활성화되며 Pause와 Stop이 활성화 | 시험 종료 시 `Tests Completed.` 표시, Return 활성, 결과 작업 버튼 표시 | Testing 전환과 Force/Stroke/Height 갱신 후 Tests Completed 전환 |
| 자동복귀 | `Tests Completed.`이 표시되고 시험 종료 위치에 있음 | Return 동작 중 Height가 절대 위치값으로 변함 | Height 변화가 멈추고 설정된 복귀 위치에 안정 | Tests Completed 유지, Height 안정, 장비 정지 |
| Raw CSV 회수 | 완료 화면에서 `Save Raw Data to CSV File` 사용 가능 | 영상에는 저장 결과를 나타내는 확실한 GUI 전환이 없음 | 화면 변화만으로 저장 성공을 판정하지 않음 | CSV 파일 생성, 크기 안정화, 필수 열과 데이터 행 확인 |
| 다음 시험 전환 | 완료 화면에서 `Next test` 사용 가능 | 실행 직후 `Loading Main screen...` 표시 | 완료 문구가 사라지고 녹색 Start가 다시 활성화된 새 시험 Ready 화면 | Loading 종료 및 Ready UI 복귀 |
| 다음 로봇 진입 준비 | 새 시험 Ready 화면, 현재 시험 준비 위치 | 지그 개방 명령 실행 후 주황색 `Jig distance` 표시와 Height 증가 | 현재 설정된 로봇 진입 높이에서 움직임 정지 | Height 안정 및 지그 이동 상태 해제 후 로봇에 Ready 전달 |

## 자동 시험 사이클

```text
INITIAL_MANUAL_ROBOT_CLEARANCE
  -> ROBOT_PLACE_SPECIMEN
  -> ROBOT_HOME_VERIFIED
  -> CAPTURE_FULL_SCREEN_AND_VERIFY_HEIGHT_150_MM
  -> MOVE_JIGS_FOR_NEXT_SPECIMEN
  -> CONFIRM_CROSSHEAD_MOVEMENT_AND_OK
  -> OBSERVE_JIG_MOTION
  -> POSITION_ZERO_RESET_AND_OK
  -> TEST_READY_UI
  -> TESTING_UI
  -> METHOD_DEFINED_CONTACT_DETECTED
  -> METHOD_DEFINED_COMPRESSION_COMPLETE
  -> TESTS_COMPLETED_UI
  -> AUTO_RETURN_COMPLETE
  -> RAW_CSV_EXPORTED_AND_VERIFIED
  -> NEXT_TEST_WITHOUT_SAVING_CURRENT_TEST
  -> READY_UI_RELOADED
  -> AUTO_OPEN_TO_CURRENT_ROBOT_CLEARANCE
  -> READY_FOR_NEXT_ROBOT_PLACEMENT
```

### 예외 처리 원칙

- Start를 눌렀지만 `Testing`으로 바뀌지 않으면 시험 시작 실패다.
- 센서값이 갱신되지 않거나 method가 정의한 접촉 및 종료 조건을 충족하지 못하면 완료 처리하지 않는다.
- `Tests Completed.`가 표시돼도 자동복귀와 CSV 검증이 끝나기 전에는 다음 시험으로 넘어가지 않는다.
- CSV 저장은 GUI 클릭 응답이 아니라 실제 파일 artifact로 확인한다.
- `Next test` 후 `Loading Main screen...`이 사라지고 Ready UI가 돌아오지 않으면 지그를 열지 않는다.
- 로봇 Home이 확인되지 않으면 어떤 지그 이동이나 시험도 시작하지 않는다.

## 이미지 사용 지침

- `images/01_...`부터 `07_...`: 기존 120 mm 녹화의 전체 화면 참고 프레임
- `images/08_live_entry_height_150mm.png`: 현재 150 mm 설정의 실제 Worker 전체 화면
- `images/transitions/`: 단계 전, 진행 중, 완료 후의 추가 전체 화면 프레임
- `images/locators/entry_height_150mm.png`: 준비 스킬 시작 시 확인하는 현재 적용 로봇 진입 높이
- `images/locators/confirm_crosshead_movement_dialog.png`: 실제 Worker 화면에서 캡처한 crosshead 이동 확인창
- `images/locators/confirm_crosshead_movement_ok.png`, `confirm_crosshead_movement_ok_focused.png`: 포커스 전/후 crosshead 이동 확인창의 OK 버튼
- `images/locators/position_zero_reset_dialog.png`: 실제 Worker의 Position Zero-Reset 확인창
- `images/locators/position_zero_reset_yes.png`: Position Zero-Reset 확인창의 한국어 `예(Y)` 버튼
- `images/locators/jig_distance_moving_state.png`: 지그 이동 중 주황색 상태
- `images/locators/toolbar_testing_controls.png`: 시험 중 Pause와 Stop 활성 상태
- `images/locators/toolbar_completed_controls.png`: 시험 완료 후 Return 활성 상태
- `images/locators/tests_completed_state.png`: `Tests Completed.` 문구
- `images/locators/loading_main_screen_state.png`: `Next test` 전환 중 로딩 문구
- `images/locators/toolbar_ready_after_next_test.png`: 새 시험 Ready 화면의 Start 활성 상태
- `images/locators/export_and_next_test_controls.png`: Raw CSV 및 Next test 버튼 영역

이미지에 보이는 수치는 손으로 만든 시연 당시 값이다. 상태 분류기는 전체 숫자 화면을 템플릿으로 고정하지 말고 상태 색상, 문구, 버튼 활성·비활성 및 아이콘 변화를 우선 사용해야 한다.

준비 스킬은 레퍼런스의 Height, 이동 상태, Ready 상태 이미지와 확인창 및 OK 이미지를 순서대로 사용한다.
