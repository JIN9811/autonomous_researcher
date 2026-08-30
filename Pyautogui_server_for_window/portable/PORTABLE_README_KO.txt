ATR Windows PyAutoGUI Bridge 포터블 실행법

1. 이 폴더 전체를 Windows PC의 로컬 디스크에 복사합니다.
2. START_PORTABLE_BRIDGE.cmd를 더블클릭합니다.
3. 첫 실행은 폴더 안에 Python과 의존성을 자동 구성하므로 잠시 기다립니다.
4. 브라우저에 Bridge Status, Program Manager, Recording, Latest Local Result가 표시됩니다.
5. Bridge Status의 임시 4자리 숫자를 확인합니다.
6. Linux ATR의 Lab Equipment Workspace에서 Scan 후 장치를 선택합니다.
7. 4자리 코드를 Pair & Save에 입력하고 장치 alias를 저장합니다.
8. 다음 실행부터는 저장된 내부 인증키를 사용하므로 코드를 다시 입력하지 않습니다.

기본 데이터 위치
- data\artifacts: 화면, 요청 로그, 실행 결과, 내부 페어링 파일
- data\locators: 이미지 locator
- data\programs: 로컬 초안과 ATR 배포 캐시
- data\recordings: 입력 녹화와 제한된 시각 증거
- data\utm_exports: UTM Profile 결과 폴더

주의
- 폴더 내부 data와 runtime을 삭제하면 페어링 및 로컬 데이터가 초기화됩니다.
- 장기 인증키를 사용자가 복사하거나 파일에 입력하지 않습니다.
- Windows Bridge는 LLM, 실험 완료 판정, Analysis handoff를 수행하지 않습니다.
- 물리 장비 실행 전 Linux ATR의 Profile/Guardian 절차를 확인하십시오.
