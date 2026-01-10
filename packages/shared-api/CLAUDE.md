# shared-api - 공유 API 클라이언트 패키지

**경로:** packages/shared-api/
**상태:** 📋 구현 예정

---

## 패키지 개요
서브도메인 간 API 호출을 위한 클라이언트

## 폴더 구조
```
packages/shared-api/
├── fencing-data/        # data.fencingmind.ai API 클라이언트
│   ├── client.py        # API 클라이언트
│   ├── competitions.py  # 대회 API
│   ├── players.py       # 선수 API
│   └── rankings.py      # 랭킹 API
└── member/              # 회원 API 클라이언트
    ├── client.py        # API 클라이언트
    ├── auth.py          # 인증 API
    └── profile.py       # 프로필 API
```

---

## 사용 예시
```python
# shop 서비스에서 data API 호출
from shared_api.fencing_data import client as data_client

# 선수 정보 조회 (장비 추천용)
player = await data_client.get_player(player_id="KOP00001")
weapon = player.weapon  # "foil" | "epee" | "sabre"
```

---

## Git 브랜치 규칙
🔴 **CRITICAL**: 이 패키지 수정 시 `feature/shared/*` 브랜치 사용

## 중요 규칙
⚠️ 서브도메인 간 직접 import 금지!
- ❌ `from services.data.app.server import ...`
- ✅ `from shared_api.fencing_data import ...`
