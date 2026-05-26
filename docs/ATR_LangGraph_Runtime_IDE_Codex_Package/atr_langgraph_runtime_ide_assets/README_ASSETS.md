# ATR Runtime IDE Icon Assets

Concept 기준의 네온 다크 UI용 아이콘 세트입니다.

## 권장 사용
- Node 내부 아이콘: SVG 24px 또는 28px 렌더링
- Node icon container: 34px × 34px, border-radius 10px
- Sidebar list icon: 18px 또는 20px
- Inspector header icon: 40px
- Status/action button icon: 18px

## 효과
- SVG 자체에 glow filter 포함
- React/CSS에서 hover 시 scale(1.04), box-shadow, border glow 추가 권장
- active node는 pulse ring을 CSS animation으로 적용

## 폴더
- icons/: 원본 SVG
- icons_png/: 32/64/128 PNG 변환본
- icon_manifest.json: 색상/크기/사용 지침
