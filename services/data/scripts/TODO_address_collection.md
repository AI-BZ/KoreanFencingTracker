# 주소 수집 계획 (카카오 로컬 API)

## 상태: 보류 - 카카오 앱 설정 필요

## 선행 작업
1. developers.kakao.com > tradops.ai 앱 > 제품 설정 > 카카오맵(지도/로컬) **활성화** 필요
2. 활성화 후 REST API 키는 이미 .env에 설정됨: `KAKAO_REST_API_KEY`

## 수집 대상 (107개)
- club: 90개
- high: 9개
- middle: 8개

## 실행 방법
```bash
cd services/data

# 테스트 (DB 저장 안 함)
PYTHONPATH="." python scripts/collect_addresses_kakao.py --dry-run

# 실제 수집 + DB 저장
PYTHONPATH="." python scripts/collect_addresses_kakao.py

# 특정 유형만
PYTHONPATH="." python scripts/collect_addresses_kakao.py --type club
```

## 스크립트 위치
- `scripts/collect_addresses_kakao.py` (신규 생성 완료)

## 기존 실패 원인
- `scraper/backup/address_collector.py`: Playwright로 카카오맵 웹 스크래핑 → UI 변경/타이밍 문제로 파싱 실패 다수
- 투셰펜싱클럽: status=collected인데 road_address 빈 값 (저장 검증 누락 버그)
- 송도펜싱클럽: 카카오맵 검색은 되지만 웹 스크래핑으로 주소 추출 실패

## 나중에 수집할 그룹
- professional: 43개 (도청/시청)
- university: 31개
- association: 16개
- international_school: 16개
