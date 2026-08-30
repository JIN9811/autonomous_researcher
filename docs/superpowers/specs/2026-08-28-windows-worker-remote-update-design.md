# Windows Worker Remote Update Design

## Scope

Linux ATR에서 저장된 Windows Worker별 브릿지 버전을 확인하고, 명시적 사용자 요청으로 업데이트하거나 최근 정상 버전으로 롤백한다. Skill/Program 배포와 브릿지 소프트웨어 업데이트는 분리한다.

## Trust And Integrity

- 최초 4자리 pairing 이후 자동 저장된 Worker별 `internal_key`를 업데이트 API 인증에 사용한다.
- 공개키 전자서명은 사용하지 않는다.
- 각 파일은 SHA-256과 byte size를 검증한다.
- Windows가 허용한 상대경로만 staging과 교체를 허용한다.
- pairing되지 않은 요청, 경로 이탈, hash 불일치, 크기 제한 초과는 fail-closed 처리한다.

## Update Flow

1. Saved Worker의 `Check Update`가 인증된 `/update/status`를 조회한다.
2. Linux는 로컬 release manifest와 파일을 읽어 현재/최신 버전 및 source digest를 비교한다.
3. `Update`는 허용 파일을 base64 package로 구성해 `/update/stage`로 전송한다.
4. Windows는 staging에 저장하고 파일별 hash를 재검증한다.
5. `/update/apply`는 독립 updater 프로세스를 시작하고 기존 브릿지를 정상 종료한다.
6. updater는 기존 파일을 backup하고 staged 파일을 원자적으로 교체한 뒤 같은 실행 인자로 브릿지를 재시작한다.
7. `/health`가 제한 시간 안에 성공하지 않으면 updater가 backup을 복원하고 이전 브릿지를 재시작한다.
8. `Rollback`은 가장 최근 정상 backup에 같은 절차를 적용한다.

## UI

Saved Worker 카드에 현재 버전, latest 버전, update 상태와 `Check Update`, `Update`, `Rollback`을 표시한다. 업데이트 중에는 해당 카드 버튼을 비활성화하며 다른 Worker 카드는 독립적으로 유지한다.

## Runtime Constraints

- Recording 중에는 apply/rollback을 차단한다.
- 업데이트 API는 localhost setup 예외에 포함하지 않고 항상 paired internal key를 요구한다.
- 사용자 데이터 디렉터리, recordings, programs, locators, exports는 교체하지 않는다.
- Linux 운영 서버와 다른 Worker는 재시작하지 않는다.

