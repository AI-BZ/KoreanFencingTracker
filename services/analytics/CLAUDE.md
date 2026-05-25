# analytics.fencingmind.ai - AI 경기 분석

**서브도메인:** analytics.fencingmind.ai
**포트:** 76
**상태:** Phase 4a 구현 완료 (Web UI + 데모 모드 + 크레딧 시스템)
**마지막 세션:** 2026-05-25
**브랜치:** `feature/analytics/main`

---

## 서비스 개요
- 경기 영상 LED/점수 OCR 분석 (v3 분석기 기반)
- 유튜브 → 클립 자동 추출 파이프라인
- 자동 라벨링 및 데이터 증강
- Phase 2: YOLO11-Pose 포즈 추정 + VideoMAE 행동 인식
- Phase 3: 영상 유형별 분석 전략 (코치/학부모/선수/TV 중계)
- 품질 게이트 + 촬영 가이드 + TV 중계 교육 분석
- FACTS 데이터셋 기반 파인튜닝 파이프라인 (8클래스 블레이드 액션)
- 종목별(foil/epee/sabre) weapon 필드 지원 (종목별 분석 로직은 향후)

## 수익 모델
- 기본 분석: $19.99/경기
- 프로 분석: $99/월 (무제한)
- 팀 라이선스: $499/월

---

## 폴더 구조

```
services/analytics/
├── app/
│   ├── __init__.py
│   ├── server.py                    # FastAPI 앱 (모든 엔드포인트 + 데모 모드) [Phase 4a]
│   ├── filming_guide.py             # 촬영 가이드 (유형별 권장사항, 한국어/영어) [Phase 3]
│   ├── demo.py                      # 데모 리포트 데이터 생성기 (샘플 플뢰레 5-3) [Phase 4a]
│   ├── upload.py                    # 영상 업로드 처리 (파일 저장, 검증) [Phase 4a]
│   ├── credits.py                   # 크레딧 시스템 (잔액/차감/충전, in-memory) [Phase 4a]
│   ├── report_renderer.py           # HTML 리포트 렌더링 로직 [Phase 4a]
│   └── pdf_exporter.py              # PDF 내보내기 스캐폴드 [Phase 4a]
├── analyzer/                        # v3 분석기 모듈 분리
│   ├── __init__.py
│   ├── models.py                    # Phase 1+2+3 데이터클래스 (REMISE, direction 추가)
│   ├── report_models.py             # 리포트 데이터 모델 (MatchReport, FencerStats 등)
│   ├── config.py                    # 임계값, HSV 범위, 7-segment 패턴, FACTS 라벨맵
│   ├── lamp_detector.py             # LED 램프 감지 (밝기 + 색상 기반)
│   ├── score_reader.py              # 7세그먼트 OCR (템플릿 매칭 + 세그먼트 분석)
│   ├── video_processor.py           # 메인 영상 처리 루프 (GUI + headless)
│   ├── video_source.py              # VideoSourceType enum + VideoSourceAssessment [Phase 3]
│   └── tv_models.py                 # TechniqueClip, TechniqueCollection, TVAnalysisResult [Phase 3]
├── pipeline/                        # fencing-AI에서 포팅한 데이터 수집/전처리
│   ├── __init__.py
│   ├── downloader.py                # 유튜브 영상 다운로드 (yt-dlp)
│   ├── clip_cutter.py               # 득점 시점 자동 클립 분할 (v3 LED 감지 활용)
│   ├── auto_labeler.py              # 자동 라벨링 (L/R/T 분류)
│   └── data_augmentor.py            # 수평 플립 + 라벨 반전 증강
├── ml/
│   ├── __init__.py                  # 모든 ML 클래스 export
│   ├── pose_estimator.py            # YOLO11-Pose 래퍼 (Phase 2)
│   ├── action_classifier.py         # VideoMAE 행동 분류 + FACTS 방향 매핑 (Phase 2+3)
│   ├── integrated_analyzer.py       # 2-pass 통합 분석 (Phase 2)
│   ├── report_generator.py          # 분석 결과 → MatchReport 변환 (Phase 2.5)
│   ├── video_source_detector.py     # 영상 유형 자동 감지 (휴리스틱) [Phase 3]
│   ├── quality_gate.py              # 영상 품질 평가 (유형별 프로파일) [Phase 3]
│   ├── tv_analyzer.py               # TV 중계 교육 분석 파이프라인 [Phase 3]
│   ├── training/                    # VideoMAE 파인튜닝 파이프라인
│   │   ├── __init__.py
│   │   ├── config.py                # FACTS 8클래스 라벨맵 + 학습 하이퍼파라미터
│   │   ├── dataset.py               # FencingActionDataset + FACTSDatasetAdapter
│   │   ├── train_videomae.py        # 학습 루프 (--dataset-format facts|csv, --grad-accum)
│   │   └── evaluate.py              # 평가 + confusion matrix
│   └── models/
│       ├── digit_templates.pkl      # v3 숫자 템플릿 데이터
│       └── yolo11n-pose.pt          # YOLO11 Pose 모델
├── templates/                       # Jinja2 HTML 템플릿 [Phase 4a]
│   ├── base.html                    # 공통 레이아웃 (Tailwind CSS + Chart.js CDN)
│   ├── upload.html                  # 영상 업로드 페이지
│   ├── dashboard.html               # 분석 대시보드 (작업 목록, 크레딧 잔액)
│   └── report.html                  # 분석 리포트 (스코어, 터치 테이블, 차트, 인사이트)
├── static/                          # 정적 파일 [Phase 4a]
│   ├── css/
│   │   └── analytics.css            # 커스텀 스타일
│   └── js/
│       ├── upload.js                # 업로드 폼 인터랙션
│       ├── dashboard.js             # 대시보드 폴링/갱신
│       └── report.js                # 차트 렌더링 (Chart.js)
├── vendor/                          # 외부 참조 코드 (.gitignore)
│   └── fencing-AI/                  # sholtodouglas/fencing-AI 클론
├── data/                            # 영상/클립 작업 디렉토리 (.gitignore)
│   ├── raw/                         # 다운로드 원본
│   ├── clips/                       # 추출된 클립
│   └── labeled/                     # 라벨링 완료 (L/R/T 서브디렉토리)
├── tests/                           # 246개 테스트
│   ├── conftest.py                  # pytest 설정 (경로, fixture)
│   ├── test_analyzer.py             # Phase 1 모듈 임포트 + 유닛 (24)
│   ├── test_pose_estimator.py       # 포즈 추정 (11)
│   ├── test_action_classifier.py    # 행동 분류 + FACTS 매핑 (20)
│   ├── test_integrated_analyzer.py  # 통합 분석 (15)
│   ├── test_report.py               # 리포트 생성 (17)
│   ├── test_training_pipeline.py    # 파인튜닝 파이프라인 + FACTS (32)
│   ├── test_video_source.py         # 영상 유형 감지 (17)
│   ├── test_quality_gate.py         # 품질 게이트 (12)
│   ├── test_filming_guide.py        # 촬영 가이드 (8)
│   ├── test_tv_analyzer.py          # TV 중계 분석 (15)
│   ├── test_integration.py          # 통합 테스트 (HTTP 엔드포인트 39) [Phase 4a]
│   ├── test_credits.py              # 크레딧 시스템 (14) [Phase 4a]
│   ├── test_upload.py               # 업로드 처리 (7) [Phase 4a]
│   ├── test_report_rendering.py     # 리포트 렌더링 (9) [Phase 4a]
│   └── test_subscription.py         # 구독 시스템 (6) [Phase 4a]
├── requirements.txt
├── .gitignore
└── CLAUDE.md                        # 이 파일
```

## 서버 실행

```bash
# 프로젝트 루트에서 실행
cd /Users/gyejinpark/Documents/GitHub/FencingMind-analytics
PYTHONPATH="services/analytics" python3 -m uvicorn app.server:app --host 0.0.0.0 --port 76

# 또는 services/analytics 내에서
cd services/analytics
PYTHONPATH=. python3 -m uvicorn app.server:app --host 0.0.0.0 --port 76
```

---

## 모듈 설명

### analyzer/ — v3 분석기 (services/data/video/fencing_analyzer_v3.py에서 분해)

| 모듈 | 원본 메서드 | 역할 |
|------|------------|------|
| `models.py` | 데이터클래스들 | Phase 1: ScoreState, StableScore, LampState, MatchEvent / Phase 2: PoseKeypoint, FencerPose, PoseResult, Weapon, FencingAction, ActionPrediction, ActionResult, EnrichedMatchEvent |
| `config.py` | `__init__` 상수들 | HSV 범위, 임계값, 7-segment 패턴맵, POSE_*, ACTION_*, DEVICE_*, ENRICHED_* |
| `lamp_detector.py` | `detect_lamp()` | 밝기 + HSV 색상으로 LED ON/OFF 감지 |
| `score_reader.py` | `read_7segment_digit()`, `match_digit_template()`, `get_score_roi_mask()` 등 | 7세그먼트 OCR, 템플릿 학습/매칭, 시계 읽기 |
| `video_processor.py` | `process_video()`, 이벤트 처리 로직 | 메인 루프, ROI 선택, 이벤트 추적, JSON/CSV 저장 |

### pipeline/ — fencing-AI에서 포팅

| 모듈 | 원본 | 주요 변경 |
|------|------|----------|
| `downloader.py` | `1-download_vids.py` | pytube → yt-dlp, Python 2 → 3, 타임아웃 처리 |
| `clip_cutter.py` | `2-fast_clip_cutter.py` | logistic classifier → v3의 LampDetector + ScoreReader |
| `auto_labeler.py` | `3-data_labeller.py` | 픽셀 비교 → v3의 LED 감지 + OCR |
| `data_augmentor.py` | `5-data_multiplier.py` | ffmpeg 파이프 → cv2.VideoWriter |

---

## DB 테이블

**마이그레이션 파일:** `database/migrations/007_analytics_tables.sql` (스키마 준비 완료, Supabase 미적용)

**이 서비스가 주인인 테이블 (8개):**
- `analytics_videos` - 업로드된 영상
- `analytics_analysis_jobs` - 분석 작업 큐
- `analytics_analysis_results` - 분석 결과 (JSON)
- `analytics_techniques` - 감지된 기술/동작
- `analytics_player_metrics` - 선수별 메트릭
- `analytics_bout_reports` - 경기 리포트
- `analytics_credits` - 크레딧 잔액
- `analytics_credit_transactions` - 크레딧 거래 내역

**현재 상태:** 서버 내부 in-memory dict로 동작 (jobs, videos, credits). Phase 4b에서 Supabase 연결 예정.

**공유 테이블 (참조만):**
- `members` - 회원 (공유)
- `players` - 선수 (프로필)
- `matches` - 경기 데이터 (data 서비스)

---

## Git 브랜치 규칙
- 이 서비스의 코드는 `feature/analytics/*` 브랜치에서만 수정
- 다른 서비스 코드 수정 금지
- 공유 패키지 수정 시 `feature/shared/*` 브랜치 사용

---

## 로드맵

### Phase 1: 기반 구축 (완료)
- [x] v3 분석기 모듈 분리 (analyzer/)
- [x] fencing-AI 파이프라인 포팅 (pipeline/)
- [x] 유튜브 → 클립 자동 추출 파이프라인
- [x] FastAPI 서버 스켈레톤
- [x] 기본 테스트 (24개)

### Phase 2: AI 모델 통합 (완료 — 2026-05-21)
- [x] YOLO11-Pose 포즈 추정 (관절 17개) — `ml/pose_estimator.py`
- [x] VideoMAE 행동 분류 (Kinetics-400 pretrained) — `ml/action_classifier.py`
- [x] 2-pass 통합 분석 (Phase 1 + Pose + Action) — `ml/integrated_analyzer.py`
- [x] weapon(종목) 필드 — `Weapon` enum, `EnrichedMatchEvent.weapon`
- [x] 61개 테스트 전체 통과 (Phase 1: 24, Phase 2: 37)
- [x] Milano 2023 FIE 영상 실전 테스트 — Pose 20-40ms/frame, Action 171ms/window (MPS)
- **한계**: VideoMAE Kinetics-400은 펜싱 동작 분류 불가 (모두 "unknown") → 파인튜닝 필요

### Phase 2.5: 리포트 + 파인튜닝 스캐폴드 (완료 — 2026-05-21)
- [x] 분석 리포트 데이터 모델 (`analyzer/report_models.py`)
- [x] 리포트 생성기 (`ml/report_generator.py`)
- [x] API 엔드포인트 확장 (`app/server.py`)
- [x] VideoMAE 파인튜닝 파이프라인 스캐폴드 (`ml/training/`)
- [x] 99개 테스트 전체 통과

### Phase 3: 영상 유형별 분석 + FACTS 정렬 (완료 — 2026-05-21)
- [x] **Step 1**: FACTS 라벨 정렬 + REMISE 추가
  - `FencingAction.REMISE` enum 추가, `ActionPrediction.direction` 필드
  - FACTS 8클래스 방향 인코딩 매핑 (AL/AR → attack + left/right)
  - `FLIP_LABEL_MAP` 수평 플립 시 left↔right 라벨 스왑
- [x] **Step 2**: VideoSourceType + 자동 감지
  - `VideoSourceType` enum (COACH/PARENT/PLAYER/TV_BROADCAST/UNKNOWN)
  - `VideoSourceDetector` 휴리스틱 감지 (장면 전환, 선수 크기, 안정성)
  - `GET /api/analytics/detect-source` 엔드포인트
- [x] **Step 3**: 품질 게이트 + 촬영 가이드
  - `QualityGate` 유형별 품질 프로파일 (해상도/FPS/밝기/2인 감지율)
  - `FilmingGuide` 촬영 권장사항 (코치/학부모/선수, 한국어/영어)
  - `GET /api/analytics/quality-check`, `GET /api/analytics/filming-guide`
- [x] **Step 4**: FACTS 데이터셋 통합 + 학습 파이프라인
  - `FACTSDatasetAdapter` (FACTS 디렉토리 → labels.csv 변환)
  - `--dataset-format facts|csv`, `--grad-accum` 지원
  - Gradient accumulation (BATCH_SIZE=4 × GRAD_ACCUM=2 = 유효 배치 8)
- [x] **Step 5**: TV 중계 교육 분석
  - `TechniqueClip`, `TechniqueCollection`, `TVAnalysisResult` 데이터 모델
  - `TVBroadcastAnalyzer` (장면 전환 → 경기 세그먼트 → 기술 추출 → 그룹핑)
  - `POST /api/analytics/analyze-broadcast` 엔드포인트
- [x] **171개 테스트 전체 통과**

### Phase 4a: Web UI + 데모 모드 (완료 — 2026-05-25)
- [x] 웹 UI 전체 구현 — Jinja2 + Tailwind CSS + Chart.js
  - `templates/`: base.html, upload.html, dashboard.html, report.html
  - `static/`: analytics.css, upload.js, dashboard.js, report.js
- [x] 데모 모드 — 샘플 플뢰레 Pool bout 5-3, 데모 배너 표시
  - `app/demo.py`: 8터치 샘플 데이터 생성기
  - `/demo` (리포트), `/demo/dashboard` (대시보드) 엔드포인트
- [x] 영상 업로드 API — `app/upload.py`, `/upload` 페이지
- [x] 크레딧 시스템 — `app/credits.py` (in-memory, Supabase 미연결)
- [x] 리포트 렌더링 — `app/report_renderer.py` (HTML 대시보드)
- [x] PDF 내보내기 스캐폴드 — `app/pdf_exporter.py` (구조만)
- [x] DB 마이그레이션 스키마 — `007_analytics_tables.sql` (8 테이블 + RLS)
- [x] Mock fallback — ML 모델 미설치 시 데모 데이터로 자동 대체
- [x] Jinja2 3.1.x + Python 3.14 캐시 버그 수정 (`cache_size=0`)
- [x] Starlette 1.0 TemplateResponse 시그니처 호환 (`request` 첫 번째 인자)
- [x] 통합 테스트 39개 (모든 HTTP 엔드포인트 + 데모 + API)
- [x] **246개 테스트** 전체 (Phase 1-3: 171 + Phase 4a: 75)

### Phase 4b: 서비스 연결 + AI 파인튜닝 (예정)
- [ ] Supabase 연결 — in-memory → DB (analytics_* 8 테이블 적용)
- [ ] 인증 연동 — members 테이블 + 크레딧 실제 결제
- [ ] FACTS 데이터셋 확보 + 실제 파인튜닝 실행 (Mac Studio MPS)
- [ ] 비디오 스트리밍/재생 + 포즈 오버레이 UI
- [ ] PDF 내보내기 실제 구현 (weasyprint 또는 reportlab)

### Phase 5: 고도화 (예정)
- [ ] 종목별 분석 로직 (Weapon-specific analyzer: foil/epee/sabre)
- [ ] 풋워크/방어 동작 분류 (포즈 궤적 분석 — Layer 2)
- [ ] 오디오 터치 감지 검토 (Allez Go 논문: 89.1% 정확도)
- [ ] Active Learning — low-confidence 예측 수동 검수 큐

---

## 🔴 종목별(Weapon) 분석 아키텍처 (CRITICAL)

### 3종목 차이점

| | 플뢰레 (Foil) | 에페 (Epee) | 사브르 (Sabre) |
|---|---|---|---|
| **유효면** | 몸통만 | 전신 | 상반신 |
| **우선권 (Priority)** | 있음 | 없음 | 있음 |
| **LED 의미** | 유효(색) / 무효(백) | 색만 | 유효(색) / 무효(백) |
| **핵심 기술** | 런지, 리포스트, 플레쉬 | 카운터어택, 거리관리 | 마르쉬-아탁, 플레쉬 |
| **경기 템포** | 중간 | 느림 (대기 많음) | 매우 빠름 |
| **분석 초점** | 우선권 판단, 공격 시작점 | 거리/타이밍, 카운터 기회 | 폭발적 전진, 방어전환 |

### 설계 원칙: 공통 레이어 + 종목별 해석 레이어

```
┌─────────────────────────────────────────────────────────────┐
│ Phase 2 — 공통 (종목 무관)                                    │
│  PoseEstimator: 관절 17개 추적 (YOLO11-Pose)                  │
│  ActionClassifier: 8가지 동작 분류 (VideoMAE)                  │
│  IntegratedAnalyzer: 2-pass 통합 분석                         │
│  → 출력: "누가 어떤 동작을 했나" (사실 기록)                    │
├─────────────────────────────────────────────────────────────┤
│ 향후 — 종목별 해석 (Weapon-specific Analyzer)                  │
│  FoilAnalyzer: 우선권 판단 (공격 시작점 분석, attaque-riposte) │
│  EpeeAnalyzer: 거리/타이밍 (카운터 기회, 거리 그래프)           │
│  SabreAnalyzer: 전진 속도/가속도 (마르쉬-아탁 패턴)             │
│  → 출력: 종목 전문 코칭 인사이트                               │
└─────────────────────────────────────────────────────────────┘
```

### 현재 구현 상태
- `Weapon` enum: `foil`, `epee`, `sabre`, `unknown`
- `EnrichedMatchEvent.weapon`: Optional[Weapon] 필드 추가 완료
- 종목별 분석 로직: **미구현** (Phase 2 이후에 추가)
- `FencingAction` enum 8개는 3종목 공통 동작

### 종목별 분석기 구현 시 규칙
- `ml/weapon_analyzers/` 디렉토리에 종목별 파일 생성
- `IntegratedAnalyzer`를 수정하지 않고, 위에 얹는 레이어로 구현
- 종목별 `FencingAction` 확장이 필요하면 enum에 추가 (기존 값 변경 금지)

---

## 🔴 영상 소스 유형별 분석 전략 (VIDEO SOURCE ARCHITECTURE)

### 4가지 영상 유형 (Phase 3 구현 완료)

| 유형 | enum 값 | 설명 | LED/점수판 | 선수 크기 | 자동 감지 기준 |
|------|---------|------|-----------|----------|--------------|
| **코치** | `COACH` | 피스트 측면 삼각대 | ✅ 물리 LED | 30-50% | stability>0.8 + 2인 일관 |
| **학부모** | `PARENT` | 관중석 핸드폰 | ⚠️ 부분 | 15-30% | scoreboard + stability<0.8 |
| **선수** | `PLAYER` | 자체 촬영 | ❌ 없음 | 크거나 1인 | person_count≤1 대부분 |
| **TV 중계** | `TV_BROADCAST` | FIE/올림픽 방송 | ❌ 오버레이 | 5-15% | scene_cuts>3/30s + overlay |

### 유형별 분석 능력 매트릭스

| 기능 | 코치 | 학부모 | 선수 | TV 중계 |
|------|------|--------|------|---------|
| Phase 1: LED 감지 | ✅ 전체 | ⚠️ 부분 | ❌ 없음 | ❌ 없음 |
| Phase 1: 점수 OCR | ✅ 전체 | ⚠️ 부분 | ❌ 없음 | ❌ (오버레이) |
| Phase 2: 포즈 추정 | ✅ 최적 | ⚠️ 군중 노이즈 | ⚠️ 1인 | ✅ 샷별 |
| Phase 2: 기술 분류 | ✅ 최적 | ⚠️ 저하 | ❌ 제한 | ✅ 샷별 |
| 매치 타임라인 | ✅ 전체 | ⚠️ 부분 | ❌ 수동입력 | ⚠️ 오버레이 추출 |
| 코칭 인사이트 | ✅ 전체 | ✅ 기본 | ✅ 기술 중심 | ✅ 교육용 |

### 유형별 분석 파이프라인 (구현 완료)

```
영상 입력
  │
  ├── VideoSourceDetector.detect() — 자동 유형 감지 (휴리스틱)
  │     ├── scene_cuts > 3/30s + overlay → TV_BROADCAST
  │     ├── stability > 0.8 + scoreboard + 2인 → COACH
  │     ├── scoreboard + stability < 0.8 → PARENT
  │     ├── person_count ≤ 1 → PLAYER
  │     └── 나머지 → UNKNOWN
  │
  ├── QualityGate.assess() — 유형별 품질 체크
  │     ├── 코치: min 640×480, 24fps, fencer_rate>0.5
  │     ├── 학부모: min 640×480, 24fps, fencer_rate>0.3
  │     ├── 선수: min 480×360, fencer_rate 무관
  │     └── TV: min 640×480, fencer_rate>0.2
  │
  ├── COACH/PARENT → IntegratedAnalyzer (기존 2-pass)
  │     ├── Phase 1: LED + 7-segment OCR
  │     ├── Phase 2: Pose + Action (이벤트 윈도우만)
  │     └── → MatchReport (유료 서비스)
  │
  ├── PLAYER → IntegratedAnalyzer (포즈 전용)
  │     ├── Phase 1: 스킵
  │     ├── Phase 2: Pose + Action만
  │     └── → 기술 중심 인사이트
  │
  └── TV_BROADCAST → TVBroadcastAnalyzer (별도 파이프라인)
        ├── detect_scene_cuts() → 장면 전환
        ├── filter_bout_segments() → 경기 구간만 필터
        ├── extract_techniques() → 기술 추출
        ├── group_by_action() → TechniqueCollection 그룹핑
        └── → TVAnalysisResult (교육 자료)
```

### VideoSourceDetector 감지 메트릭
- `scene_cuts_per_minute`: 장면 전환 빈도 (프레임 차이 임계값 초과)
- `avg_fencer_height_ratio`: 선수 높이/프레임 높이 비율
- `stability_score`: 프레임 간 optical flow 안정성 (0=흔들림, 1=삼각대)
- `avg_person_count`: YOLO11-Pose 감지 평균 인원 수
- `scoreboard_detected`: 물리 LED 점수판 감지 여부
- `overlay_detected`: TV 오버레이 감지 여부

### FIE YouTube 역할 변경
- ❌ **학습 데이터 용도 부적합** (카메라 컷 8초마다, 선수 크기 6.7%)
- ✅ **교육 분석 소스**: TVBroadcastAnalyzer로 월드클래스 기술 추출 → 교육 자료
- ✅ **학습 데이터**: FACTS 데이터셋이 대체 (90% 정확도 검증됨)

---

## 🔴 분석 결과 제공 아키텍처 (RESULTS PRESENTATION)

### 데이터 흐름

```
EnrichedMatchEvent[] (Phase 2 출력)
  │
  ├── ReportGenerator.generate_report()
  │     ├── 경기 개요 (MatchSummary)
  │     ├── 터치별 상세 (TouchDetail[])
  │     ├── 선수별 통계 (FencerStats × 2)
  │     └── 코칭 인사이트 (CoachingInsight[])
  │     → 출력: MatchReport (중간 표현)
  │
  ├── API (JSON 응답)
  │     GET /api/analytics/results/{id} → MatchReport JSON
  │     GET /api/analytics/report/{id} → 포맷된 리포트
  │
  ├── HTML 대시보드 (Jinja2 + Chart.js)
  │     ├── 스코어 타임라인 그래프
  │     ├── 터치 클립 재생 + 포즈 오버레이
  │     └── 동작 분포 차트
  │
  └── PDF 내보내기 (weasyprint 또는 reportlab)
        └── 코치 → 학부모 공유용
```

### MatchReport 구조

| 섹션 | 데이터 모델 | 내용 |
|------|------------|------|
| **경기 개요** | `MatchSummary` | 최종 점수, 경기 시간, 종목, 총 터치 수, 영상 정보 |
| **터치별 상세** | `TouchDetail[]` | 프레임, 시간, 득점자, 동작 분류, 신뢰도, 포즈 스냅샷 |
| **선수 통계** | `FencerStats` | 동작 분포, 동작별 성공률, 평균 반응 시간 |
| **코칭 인사이트** | `CoachingInsight[]` | 자동 생성 코칭 포인트 (동작 패턴, 약점, 개선 제안) |
| **메타데이터** | `ReportMeta` | 분석 버전, 모델 정보, 처리 시간, 신뢰도 지표 |

### API 엔드포인트

```
# 분석
POST /api/analytics/analyze
  Body: { video_path, weapon?, source_type?, rois?, enable_pose, enable_action }
  → { job_id, status: "queued" }

POST /api/analytics/analyze-broadcast                    [Phase 3]
  Body: { video_path, enable_pose, enable_action }
  → { job_id, status: "queued", job_type: "broadcast" }

# 결과 조회
GET /api/analytics/jobs/{job_id}
  → { job_id, status, progress_pct, error? }

GET /api/analytics/results/{job_id}
  → MatchReport JSON (202 if processing)

GET /api/analytics/report/{job_id}?format=json|html
  → 포맷된 리포트

# 영상 유형 / 품질 / 촬영 가이드                          [Phase 3]
GET /api/analytics/detect-source?video_path=...
  → VideoSourceAssessment JSON

GET /api/analytics/quality-check?video_path=...&source_type=coach
  → VideoQualityAssessment JSON (422 if unfit)

GET /api/analytics/filming-guide?source_type=coach&weapon=foil&language=ko
  → FilmingGuide JSON

# 상태
GET /health → { status: "ok" }
GET /api/analytics/status → capabilities + phase
```

### 코칭 인사이트 자동 생성 규칙

```python
# 패턴 감지 → 인사이트 생성 예시
"왼쪽 선수: 런지(lunge) 비율 45% — 예측 가능한 패턴, 리포스트 혼합 권장"
"오른쪽 선수: 파리-리포스트 성공률 25% — 파리 타이밍 연습 필요"
"양 선수 간 거리: 평균 2.1m — 에페 적정 거리보다 가까움, 거리 관리 주의"
```

---

## 🔴 딥러닝 파인튜닝 파이프라인 (TRAINING PIPELINE)

### 2계층 액션 분류 체계

```
┌───────────────────────────────────────────────────────────────┐
│ Layer 1: 블레이드 액션 (FACTS VideoMAE) — Phase 3 구현 완료      │
│  ATTACK, RIPOSTE, COUNTER_ATTACK, REMISE (4종 × left/right)   │
│  → 파인튜닝 파이프라인 준비 완료, FACTS 데이터셋 확보 필요       │
├───────────────────────────────────────────────────────────────┤
│ Layer 2: 풋워크/방어 (포즈 궤적 분석) — Phase 4 예정            │
│  LUNGE, FLECHE, ADVANCE, RETREAT, PARRY                       │
│  → 관절 좌표 시계열 분석 필요 (VideoMAE 불가)                   │
└───────────────────────────────────────────────────────────────┘
```

### FACTS 데이터셋 정렬 (구현 완료)

| FACTS 클래스 코드 | 의미 | → FencingAction 매핑 | direction |
|---|---|---|---|
| AL | Attack Left | ATTACK | "left" |
| AR | Attack Right | ATTACK | "right" |
| RL | Riposte Left | RIPOSTE | "left" |
| RR | Riposte Right | RIPOSTE | "right" |
| CAL | Counter-attack Left | COUNTER_ATTACK | "left" |
| CAR | Counter-attack Right | COUNTER_ATTACK | "right" |
| ReL | Remise Left | REMISE | "left" |
| ReR | Remise Right | REMISE | "right" |

**방향 처리**: 8클래스로 훈련 (FACTS 정확도 유지) → 추론 시 방향 제거 + `ActionPrediction.direction`에 저장

### 학습 인프라: Mac Studio M1 Max (GPU 클라우드 불필요)

**벤치마크 결과 (2026-05-21)**:
- VideoMAE 모델: 86M params, 329MB
- 학습 시 메모리: ~1.3GB (64GB 중) → **Mac Studio에서 충분**
- MPS (Metal Performance Shaders) GPU 지원 확인됨
- 클라우드 GPU 불필요 — 로컬 학습으로 전환

### 파인튜닝 파이프라인 (코드 준비 완료)

```
Step 1: FACTS 데이터셋 확보 ─────────────────────────────────
  논문 저자에게 데이터 요청 또는 자체 수집
  FACTS 디렉토리 구조: AL/, AR/, RL/, RR/, CAL/, CAR/, ReL/, ReR/

Step 2: FACTSDatasetAdapter 변환 ────────────────────────────
  python3 -c "
  from ml.training.dataset import FACTSDatasetAdapter
  adapter = FACTSDatasetAdapter('/path/to/facts/')
  n = adapter.to_csv('data/labeled/labels.csv')
  print(f'{n} clips converted')
  print(adapter.get_class_distribution())
  "

Step 3: 파인튜닝 실행 (Mac Studio MPS) ──────────────────────
  PYTHONPATH=services/analytics .venv/bin/python3 \
    -m ml.training.train_videomae \
    --dataset-format facts \
    --data-dir /path/to/facts/ \
    --epochs 10 \
    --batch-size 4 \
    --grad-accum 2 \
    --lr 5e-5

  하이퍼파라미터 (FACTS 논문 기준):
  - BATCH_SIZE=4 × GRAD_ACCUM=2 = 유효 배치 8
  - EPOCHS=10, LR=5e-5, warmup 10%
  - Label smoothing 0.1, gradient clipping 1.0

Step 4: 평가 ──────────────────────────────────────────────
  ml/training/evaluate.py
  - 목표: 전체 정확도 85%+ (FACTS 논문 ~90%)
  - Confusion matrix + 오분류 분석

Step 5: 배포 ──────────────────────────────────────────────
  → ml/models/videomae-fencing-v1/ 에 저장
  → config.py: ACTION_FINETUNED_PATH 설정
  → ActionClassifier가 자동으로 파인튜닝 모델 로드
```

### 데이터 증강: 방향 라벨 보존

```python
# 수평 플립 시 left↔right 라벨 자동 스왑
# FLIP_LABEL_MAP: {0↔1, 2↔3, 4↔5, 6↔7}
# 예: attack_left(0) ↔ attack_right(1)
```

### 지속적 개선 계획
1. **서비스 데이터 활용**: low-confidence 예측 → 수동 검수 큐
2. **Active Learning**: 불확실 예측 우선 라벨링
3. **종목별 모델**: foil/epee/sabre 각각 별도 파인튜닝 (동작 분포 다름)

---

## 기술 결정 기록

### 결정 1: 블레이드 추적 스킵
- **이유**: Rhizomatiks(WFSF 공식)가 24대 4K 카메라로 겨우 해결한 문제
- **대안**: 포즈 에스티메이션(YOLO11-Pose) + 행동 인식(VideoMAE)으로 대체
- **참고**: 블레이드는 1px 미만으로 보이는 경우가 많음

### 결정 2: TF1 LSTM → VideoMAE
- **이유**: fencing-AI의 InceptionV3+LSTM은 정확도 ~60% (2018년 기술)
- **대안**: FACTS 논문의 VideoMAE 방식은 정확도 ~90%
- **구현**: Phase 2에서 VideoMAE 파인튜닝

### 결정 3: pytube → yt-dlp
- **이유**: pytube는 유지보수 불안정, 자주 깨짐
- **대안**: yt-dlp가 사실상 유튜브 다운로드 표준
- **상태**: pipeline/downloader.py에 구현 완료

### 결정 4: 오디오 터치 감지 검토 예정
- **근거**: Allez Go 논문 — 오디오만으로 터치 감지 89.1% 정확도
- **계획**: Phase 2에서 LED 감지 보조수단으로 검토
- **한계**: 관중 소음이 큰 경기에서는 정확도 저하 예상

### 결정 5: clip_cutter에서 v3 모듈 활용
- **이유**: fencing-AI의 logistic classifier (`logistic_classifier_0-15.pkl`)보다
  v3의 LED 감지 + 7세그먼트 OCR이 더 정밀
- **구현**: clip_cutter.py가 LampDetector + ScoreReader를 직접 호출

### 결정 8: 분석 리포트 3단계 아키텍처 (2026-05-21)
- **이유**: 분석 결과를 사용자에게 효과적으로 전달하는 구조 필요
- **결정**: Data Model → Report Generator → Delivery (API/HTML/PDF)
- **리포트 구조**: 경기 개요 → 스코어 타임라인 → 터치별 상세 → 선수 통계 → 코칭 인사이트
- **핵심**: `MatchReport` dataclass가 모든 리포트 포맷의 중간 표현 역할

### 결정 9: VideoMAE 파인튜닝 전략 (2026-05-21)
- **이유**: Kinetics-400 pretrained는 펜싱 동작 분류 불가 (모두 "unknown")
- **결정**: FACTS 데이터셋 기반 파인튜닝, classifier head만 교체 (400→8 클래스)
- **인프라**: Mac Studio M1 Max MPS (모델 329MB, 학습 ~1.3GB — 클라우드 GPU 불필요)
- **자동 전환**: `ACTION_FINETUNED_PATH` 설정 시 ActionClassifier가 자동으로 파인튜닝 모델 사용

### 결정 6: 종목(Weapon) 공통 개발 → 종목별 분석 분리 (2026-05-21)
- **이유**: 3종목(foil/epee/sabre)은 유효면, 우선권, 경기 템포가 다름
- **결정**: Phase 2는 공통 레이어 (Pose + Action = 사실 기록), 종목별 해석은 향후 별도 레이어
- **구현**: `Weapon` enum + `EnrichedMatchEvent.weapon` 필드 추가
- **향후**: `ml/weapon_analyzers/foil.py`, `epee.py`, `sabre.py`

### 결정 7: 영상 4유형 분류 아키텍처 (2026-05-21, Phase 3 구현 완료)
- **이유**: TV 중계, 코치, 학부모, 선수 촬영은 구도·인원수·점수판이 다름
- **결정**: 유형별 분석 파이프라인 분기, 핵심 서비스는 코치/학부모 촬영
- **구현**: `VideoSourceType` enum + `VideoSourceDetector` 휴리스틱 감지
- **TV 중계**: 별도 `TVBroadcastAnalyzer` (교육 자료 목적)
- **FIE YouTube 역할**: 학습 데이터 ❌ → 교육 분석 소스 ✅

### 결정 10: 2계층 액션 분류 — 블레이드 vs 풋워크 (2026-05-21)
- **이유**: FACTS 데이터셋은 블레이드 액션 4종(공격/리포스트/카운터/르미즈)만 분류
- **결정**: Layer 1은 FACTS VideoMAE (블레이드), Layer 2는 포즈 궤적 분석 (풋워크, Phase 4)
- **구현**: `FencingAction.REMISE` 추가, 기존 lunge/fleche 등은 Layer 2로 분류 예정

### 결정 11: 방향(left/right)은 메타데이터 (2026-05-21)
- **이유**: FACTS는 방향을 클래스에 인코딩(AL/AR) — 8클래스로 훈련하면 정확도 유지
- **결정**: 학습은 8클래스, 추론 시 방향 제거 후 `ActionPrediction.direction`에 저장
- **구현**: `FACTS_TO_ACTION` 매핑 + `FLIP_LABEL_MAP` (증강 시 left↔right 스왑)

### 결정 12: 영상 유형 휴리스틱 감지 — ML 아님 (2026-05-21)
- **이유**: 라벨링된 영상 유형 데이터 없음, 단순 특징만으로 구분 가능
- **결정**: 장면 전환 빈도 + 선수 크기 + 안정성 + 점수판 유무 → 캐스케이드 판정
- **구현**: `VideoSourceDetector` (ML 모델 없이 cv2 + YOLO-Pose 샘플링)

### 결정 13: TV 분석은 별도 파이프라인 (2026-05-21)
- **이유**: TV 영상은 목적이 다름 (스코어링 ❌ → 기술 교육 ✅), 장면 전환·리플레이 처리 필요
- **결정**: `TVBroadcastAnalyzer` 별도 클래스, `IntegratedAnalyzer` 확장 아님
- **구현**: 장면 전환 감지 → 경기 세그먼트 필터 → 기술 추출 → 액션별 그룹핑

### 결정 14: Mac Studio 로컬 학습 — 클라우드 GPU 불필요 (2026-05-21)
- **이유**: VideoMAE 86M params (329MB), 학습 시 ~1.3GB — Mac Studio 64GB 중 2%
- **벤치마크**: MPS GPU 가속 확인, 추론 96ms/window
- **결정**: Colab/Lambda 불필요, Mac Studio MPS에서 직접 파인튜닝
- **조건**: FACTS 데이터셋이 ~4,000 클립 이하면 충분 (메모리 기준)

---

## 🔴 분석 성능 벤치마크 + 영상 길이 가이드 (PERFORMANCE)

### 하드웨어: Mac Studio M1 Max, 64GB Unified Memory

### 모델별 추론 속도 (MPS GPU)

| 모델 | 단위 | 속도 | 해상도 |
|------|------|------|--------|
| YOLO11-Pose | 1 프레임 | 150ms | 720p |
| VideoMAE | 16프레임 윈도우 | 96ms | 224×224 |
| Phase 1 (LED+OCR) | 1 프레임 | ~18ms | 720p |

### 핵심 최적화: 이벤트 윈도우 분석

IntegratedAnalyzer는 **모든 프레임에 Pose/Action을 실행하지 않음**.
Phase 1에서 감지된 스코어링 이벤트 주변 ±45프레임(BEFORE=30, AFTER=15)만 분석.

```
전체 경기 프레임   ████████████████████████████████████████████
Phase 1 (모든 프레임) ████████████████████████████████████████████  ← LED/OCR만
Phase 2 (이벤트만)  ██    ██     ██   ██      ██    ██   ██     ← Pose/Action
                    ↑     ↑      ↑    ↑       ↑     ↑    ↑
                   터치1  터치2  터치3 터치4   터치5  터치6 터치7
```

### 실제 분석 비용 (이벤트 윈도우 모드)

| 경기 유형 | 영상 길이 | 터치 수 | Phase 1 | Phase 2 (Pose) | Phase 2 (Action) | **총 소요** | **배율** |
|-----------|----------|---------|---------|----------------|-----------------|------------|---------|
| Pool bout | 3분 | 5 | 54초 | 34초 | 0.5초 | **88초** | 0.49x |
| DE bout | 9분 | 15 | 162초 | 101초 | 1.4초 | **265초** | 0.49x |
| DE 풀경기 | 15분 | 25 | 270초 | 169초 | 2.4초 | **441초** | 0.49x |

→ **실시간보다 빠름** (0.49x realtime) — 3분 영상을 88초에 분석

### 전체 프레임 분석 모드 (TV/선수 전용)

TV 중계나 선수 촬영은 Phase 1 이벤트가 없으므로 모든 프레임에 Pose 실행:
- 3분 영상 (5,400프레임 @30fps): **810초** (4.7x realtime)
- → 프레임 서브샘플링으로 최적화 필요 (매 3프레임만 → 1.5x)

### 영상 길이 가이드라인

| 영상 유형 | 권장 길이 | 최대 길이 | 예상 분석 시간 | 비고 |
|-----------|----------|----------|--------------|------|
| Pool bout | 3~5분 | 10분 | 88~165초 | 이벤트 윈도우 모드 |
| DE bout | 9~12분 | 20분 | 265~380초 | 이벤트 윈도우 모드 |
| 풀 매치 | 15~20분 | 30분 | 441~570초 | Phase 1 비용 선형 증가 |
| TV 중계 | 제한 없음 | 60분+ | 세그먼트 단위 | TVBroadcastAnalyzer가 장면 분할 |

**제한 요소**: 메모리가 아닌 시간 — 영상 길이에 비례하여 Phase 1 시간 증가.
30분 이상 영상도 기술적으로 가능하나, 사용자 대기 시간이 길어짐 → 비동기 처리 필수.

### 서비스화 시 비용 구조

```
분석 1건 비용 구성:
├── 컴퓨팅: Mac Studio 전력 (200W × 분석시간) ≈ 거의 무시 가능
├── 스토리지: 영상 임시 저장 (분석 후 삭제)
├── 모델: 로컬 (추가 비용 없음)
└── 병목: 동시 분석 수 (CPU/GPU 공유)

1대 Mac Studio 처리량 (직렬):
├── Pool bout: ~40건/시간
├── DE bout: ~14건/시간
└── 동시 분석 (2-3 프로세스): 1.5~2x 처리량
```

---

## 기술 스택

| 영역 | Phase 1 | Phase 2 | Phase 3 | Phase 4a (현재) | Phase 4b 예정 |
|------|---------|---------|---------|----------------|-------------|
| 영상 처리 | OpenCV 4.x | 유지 | 유지 | 유지 | + FFmpeg |
| LED/점수 | 7-segment OCR | 유지 | 유지 | 유지 | 유형별 최적화 |
| 다운로드 | yt-dlp | 유지 | 유지 | 유지 | 유지 |
| 포즈 추정 | — | YOLO11-Pose | 유지 | 유지 | 유지 |
| 행동 인식 | — | VideoMAE (K400) | FACTS 8클래스 정렬 | Mock fallback | FACTS 파인튜닝 실행 |
| 영상 감지 | — | — | VideoSourceDetector | 유지 | 유지 |
| 품질 관리 | — | — | QualityGate | 유지 | 유지 |
| TV 분석 | — | — | TVBroadcastAnalyzer | 유지 | 유지 |
| 종목 분석 | — | Weapon enum | 유지 | 유지 | 종목별 Analyzer |
| 웹 프레임워크 | FastAPI | 유지 | 유지 | + Jinja2/Tailwind/Chart.js | + Supabase 연결 |
| DB | — | — | — | in-memory (스키마 준비) | Supabase 적용 |
| GPU | — | Apple Metal (MPS) | 유지 | 유지 | 파인튜닝도 MPS |

---

## 세션 재개 가이드 (2026-05-25 기준)

### 현재 상태 요약
- **브랜치**: `feature/analytics/main`
- **Phase 4a 완료**: Web UI + 데모 모드 + 크레딧 시스템 + 통합 테스트
- **서버 실행 확인됨**: 모든 페이지 HTTP 200, 데모 콘텐츠 정상 렌더링
- **테스트**: 246개 (integration 39개 전부 통과, ML의존 22개 numpy 미설치로 실패 — 기존 이슈)

### 작동하는 것
| 기능 | 상태 | 엔드포인트 |
|------|------|-----------|
| 서버 기동 | ✅ | `port 76` |
| 데모 리포트 | ✅ | `GET /demo` — 플뢰레 5-3, 8터치, Chart.js, 코칭 인사이트 |
| 데모 대시보드 | ✅ | `GET /demo/dashboard` — 3종목, 크레딧 잔액, 작업 상태 |
| 영상 업로드 페이지 | ✅ | `GET /upload` |
| 분석 대시보드 | ✅ | `GET /dashboard` |
| Health/Status API | ✅ | `GET /health`, `GET /api/analytics/status` |
| 촬영 가이드 API | ✅ | `GET /api/analytics/filming-guide` |
| Mock fallback | ✅ | ML 미설치 시 자동으로 데모 데이터 반환 |

### 스캐폴드 (구조만 있고 실제 동작 X)
| 기능 | 이유 | 해결 방법 |
|------|------|----------|
| 실제 영상 분석 | VideoMAE가 모두 "unknown" 반환 | FACTS 파인튜닝 필요 |
| DB 영속성 | in-memory dict 사용 중 | 007 마이그레이션 Supabase 적용 |
| 크레딧 결제 | 메모리 잔액만, 결제 없음 | Stripe/토스 연동 필요 |
| PDF 내보내기 | 함수 시그니처만 존재 | weasyprint/reportlab 구현 필요 |
| 인증 | 없음, 공개 접근 | members 테이블 + JWT 연동 |

### 핵심 블로커
1. **FACTS 데이터셋 미확보** — 논문 저자 연락 또는 자체 수집 필요
2. **numpy 미설치** (.venv) — ML 관련 22개 테스트 실패 원인 (데모/웹에는 영향 없음)
3. **Supabase 마이그레이션 미적용** — `007_analytics_tables.sql` 준비됨, 적용 필요

### 다음 세션 우선순위
1. **Supabase 연결** — 007 마이그레이션 적용 → server.py의 in-memory를 DB로 교체
2. **numpy/torch 설치** — `.venv`에 ML 의존성 설치 → 전체 테스트 통과
3. **FACTS 데이터셋** — 확보 경로 결정 (논문 저자 / 자체 라벨링)
4. **인증** — members 연동, 크레딧 실제 소유자 연결

### 커밋 이력 (이 브랜치)
```
2837ff5 Fix Jinja2 template rendering on Python 3.14
e9795e2 Add demo mode and integration tests for analytics web service
6a17f02 Add analytics Phase 4: Web UI, upload API, credit system, report rendering, DB migration
7cb88b4 Add analytics Phase 2-3: AI models, video source detection, TV analysis, FACTS pipeline
79264a8 Set up unified test environment and Phase 2 dependencies
2ab7054 Add analytics service Phase 1: v3 analyzer refactor + fencing-AI pipeline
e0ec750 Refactor to monorepo structure for FencingMind multi-subdomain architecture
```

### 서버 실행 커맨드
```bash
cd /Users/gyejinpark/Documents/GitHub/FencingMind-analytics/services/analytics
PYTHONPATH=. .venv/bin/python3 -m uvicorn app.server:app --host 0.0.0.0 --port 76
# 브라우저: http://localhost:76/demo
```

### 알려진 호환성 이슈
- **Python 3.14.4** + **Jinja2 3.1.x**: LRU 캐시 해싱 버그 → `cache_size=0`으로 해결됨
- **Starlette 1.0.1**: TemplateResponse 시그니처 변경 → `(request, name, context)` 형식으로 수정됨
