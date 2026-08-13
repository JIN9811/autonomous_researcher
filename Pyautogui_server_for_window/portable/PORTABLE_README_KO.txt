ATR Equipment Agent Bridge - Windows x64 포터블판
===================================================

사용 순서
1. ZIP 전체를 Windows PC의 원하는 폴더에 압축 해제합니다.
2. START_EQUIPMENT_BRIDGE.cmd를 더블클릭합니다.
3. 최초 실행만 로컬 runtime 구성 때문에 시간이 걸립니다.
4. PowerShell 창과 브라우저 GUI가 열리면 Bridge token을 GUI에 입력합니다.
5. Linux ATR에서 bridge Health를 실행하면 Windows가 인증된 ATR 주소를 검증하고 저장합니다.
6. 자동 연결이 안 되면 GUI의 Discover ATR 또는 Controller URL의 Verify & Save를 사용합니다.
7. 종료할 때 STOP_EQUIPMENT_BRIDGE.cmd를 더블클릭합니다.

중요
- 인터넷 연결이나 별도 Python 설치가 필요하지 않습니다.
- 관리자 권한을 요구하지 않습니다.
- 폴더를 이동할 때 bridge가 실행 중이면 먼저 중지하십시오.
- 토큰, 프로그램, 녹화, locator, UTM export, 로그는 모두 data 폴더에 저장됩니다.
- data 폴더를 유지하면 설정이 유지되고, 삭제하면 새 배포 상태로 초기화됩니다.
- 검증된 Linux ATR 주소는 data\controller_connection.json에 저장되며 token/API key는 저장하지 않습니다.
- Windows 서비스가 아니라 로그인한 사용자의 대화형 데스크톱에서 실행해야 합니다.
- PyAutoGUI fail-safe가 활성화됩니다. 비상 중지는 마우스를 화면 왼쪽 위 모서리로 이동합니다.

오프라인 OCR 제한
- pytesseract Python 연동은 포함되지만 Tesseract OCR 실행 파일은 포함하지 않습니다.
- OCR locator가 필요한 경우 Windows에 Tesseract를 별도로 설치하고 PATH를 설정하십시오.

문제 확인
- data\logs\portable-bootstrap.log: 최초 구성/시작 로그
- data\artifacts\bridge_requests.jsonl: 브릿지 요청 감사 로그
- 브라우저 GUI의 Health/Request Log: 연결 및 요청 상태
