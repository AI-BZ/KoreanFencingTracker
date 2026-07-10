# analytics.fencingmind.ai - AI 경기 분석

**서브도메인:** analytics.fencingmind.ai
**포트:** 76
**상태:** Phase 7b 완료 (프레이즈 다름 경계 탐지 6항목 전체 구현), Phase 8 준비
**마지막 세션:** 2026-06-08
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
│   ├── demo.py                      # 데모 리포트 생성 (Pool 5-3 + DE 15-11, 선수 이름) [Phase 4c]
│   ├── tv_report_converter.py       # TVScoreTracker → MatchReport dict 변환 [Phase 5a+/5b]
│   ├── metadata_parser.py           # 무기/성별/연령대 자동 감지 (파일명/제목) [Phase 5b]
│   ├── upload.py                    # 영상 업로드 처리 (파일 저장, 검증) [Phase 4a]
│   ├── credits.py                   # 크레딧 시스템 (잔액/차감/충전, in-memory) [Phase 4a]
│   ├── report_renderer.py           # HTML 리포트 렌더링 로직 [Phase 4a]
│   └── pdf_exporter.py              # PDF 내보내기 스캐폴드 [Phase 4a]
├── analyzer/                        # v3 분석기 모듈 분리
│   ├── __init__.py
│   ├── models.py                    # Phase 1+2+3+5c+7b 데이터클래스 (ActionState, FrameActionState, JointKinematics, FrameKinematics, PhraseAnnotation 추가)
│   ├── report_models.py             # 리포트 데이터 모델 (MatchReport, FencerStats 등)
│   ├── config.py                    # 임계값, HSV 범위, 7-segment 패턴, FACTS 라벨맵, COCO 키포인트, 포즈 분석 상수, 키네마틱/시계 OCR 상수
│   ├── lamp_detector.py             # LED 램프 감지 (밝기 + 색상 기반)
│   ├── score_reader.py              # 7세그먼트 OCR (템플릿 매칭 + 세그먼트 분석)
│   ├── video_processor.py           # 메인 영상 처리 루프 (GUI + headless)
│   ├── video_source.py              # VideoSourceType enum + VideoSourceAssessment [Phase 3]
│   ├── tv_models.py                 # TechniqueClip, TechniqueCollection, TVAnalysisResult [Phase 3]
│   └── tv_overlay_ocr.py            # TVOverlayOCR, TVScoreTracker, OverlayData [Phase 5a]
├── pipeline/                        # fencing-AI에서 포팅한 데이터 수집/전처리
│   ├── __init__.py
│   ├── downloader.py                # 유튜브 영상 다운로드 (yt-dlp)
│   ├── clip_cutter.py               # 득점 시점 자동 클립 분할 (v3 LED 감지 활용)
│   ├── auto_labeler.py              # 자동 라벨링 (L/R/T 분류)
│   ├── data_augmentor.py            # 수평 플립 + 라벨 반전 증강
│   └── tv_data_collector.py         # YouTube TV → OCR → 클립 → 라벨 CSV E2E [Phase 5a]
├── ml/
│   ├── __init__.py                  # 모든 ML 클래스 export
│   ├── pose_estimator.py            # YOLO11-Pose 래퍼 (Phase 2)
│   ├── action_classifier.py         # VideoMAE 행동 분류 + FACTS 방향 매핑 (Phase 2+3)
│   ├── integrated_analyzer.py       # 2-pass 통합 분석 (Phase 2)
│   ├── report_generator.py          # 분석 결과 → MatchReport 변환 (Phase 2.5)
│   ├── video_source_detector.py     # 영상 유형 자동 감지 (휴리스틱) [Phase 3]
│   ├── quality_gate.py              # 영상 품질 평가 (유형별 프로파일) [Phase 3]
│   ├── tv_analyzer.py               # TV 중계 교육 분석 파이프라인 [Phase 3]
│   ├── pose_analyzer.py             # 풋워크/빠라드/거리 분석 (키네마틱 규칙, ML 불필요) [Phase 5c]
│   ├── fencer_profile.py            # FencerProfileBuilder: bout/continuous 결과 집계 [Phase 6]
│   ├── clip_overlay.py             # ClipOverlayGenerator: 포즈 오버레이 클립 생성 [Phase 7a]
│   ├── training/                    # VideoMAE 파인튜닝 파이프라인
│   │   ├── __init__.py
│   │   ├── config.py                # FACTS 8클래스 라벨맵 + 학습 하이퍼파라미터
│   │   ├── dataset.py               # FencingActionDataset + FACTSDatasetAdapter
│   │   ├── train_videomae.py        # 학습 루프 (--dataset-format facts|csv, --grad-accum)
│   │   └── evaluate.py              # 평가 + confusion matrix
│   └── models/
│       ├── digit_templates.pkl      # v3 숫자 템플릿 데이터
│       └── yolo11n-pose.pt          # YOLO11 Pose 모델
├── templates/                       # Jinja2 HTML 템플릿 [Phase 4a+4c]
│   ├── base.html                    # 공통 레이아웃 (Tailwind CSS + Chart.js CDN, 데모 네비)
│   ├── landing.html                 # 랜딩 페이지 (히어로, 3단계 설명, 기능, 가격표) [Phase 4c]
│   ├── upload.html                  # 영상 업로드 페이지
│   ├── dashboard.html               # 분석 대시보드 (작업 목록, 크레딧 잔액)
│   ├── report.html                  # 분석 리포트 (선수 이름, 한국어 동작명, 차트, 인사이트)
│   └── labeling.html                # 포즈 분석 라벨링 UI (거리/풋워크/빠라드 패널, 'A' 수락 단축키) [Phase 5c]
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
├── scripts/                         # 유틸리티 스크립트
│   ├── run_pose_analysis.py         # 배치 포즈 분석 (YOLO11-Pose → PoseAnalyzer → JSON) [Phase 5c]
│   ├── generate_continuous_report.py # 연속 분석 리포트 생성 (영상→포즈→교환→JSON) [Phase 6+7b]
│   ├── generate_phrase_dataset.py   # 프레이즈 경계 어노테이션 데이터셋 생성 [Phase 7b]
│   ├── labeling_server.py           # 웹 라벨링 리뷰 도구 (Pose+Gemini 듀얼 소스) [Phase 5c]
│   ├── gemini_labeler.py            # Gemini Vision 자동 라벨링 (deprecated by PoseAnalyzer)
│   └── active_learning.py           # Active Learning 스크립트
├── tests/                           # 531개 테스트
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
│   ├── test_integration.py          # 통합 테스트 (HTTP + 데모 + DE + 랜딩 52) [Phase 4c]
│   ├── test_credits.py              # 크레딧 시스템 (14) [Phase 4a]
│   ├── test_upload.py               # 업로드 처리 (7) [Phase 4a]
│   ├── test_report_rendering.py     # 리포트 렌더링 (9) [Phase 4a]
│   ├── test_subscription.py         # 구독 시스템 (6) [Phase 4a]
│   ├── test_tv_overlay_ocr.py       # TV 오버레이 OCR + 트래커 + 시계 이벤트 (35) [Phase 5a+7b]
│   ├── test_metadata_parser.py      # 메타데이터 파서 (42) [Phase 5b]
│   ├── test_tv_report_converter.py  # 리포트 변환기 (12) [Phase 5b]
│   ├── test_pose_analyzer.py        # 포즈 분석기 (92) [Phase 5c+6+7b]
│   ├── test_fencer_profile.py       # FencerProfile 테스트 (6) [Phase 6]
│   └── test_clip_overlay.py        # ClipOverlay 테스트 (19) [Phase 7a]
├── docs/                            # 프로젝트 문서
│   └── PRIORITY_1_FACTS_FINETUNING.md  # 🔴 1순위 이슈: FACTS 파인튜닝 절차서
├── requirements.txt
├── .gitignore
└── CLAUDE.md                        # 이 파일
```

## 서버 실행

### 개발 서버 (로컬 테스트)
```bash
cd /Users/gyejinpark/Documents/GitHub/FencingMind-analytics/services/analytics
PYTHONPATH=. .venv/bin/python3 -m uvicorn app.server:app --host 0.0.0.0 --port 76
# → http://localhost:76/
```

### 프로덕션 서버 (analytics.fencingmind.ai)
```bash
# 프로덕션은 같은 디렉토리에서 포트 9076으로 실행
# Nginx(9090) → analytics.fencingmind.ai → localhost:9076
cd /Users/gyejinpark/Documents/GitHub/FencingMind-analytics/services/analytics
PYTHONPATH=. .venv/bin/python3 -m uvicorn app.server:app --host 0.0.0.0 --port 9076
```

### 🔴 프로덕션 배포 절차 (PRODUCTION DEPLOYMENT)
데모 영상 분석 후 갤러리에 추가할 때는 **즉시 프로덕션 배포**까지 완료해야 함.

```bash
# 1. 프로덕션 서버 재시작 (코드 변경 반영)
kill $(lsof -ti:9076) 2>/dev/null
cd /Users/gyejinpark/Documents/GitHub/FencingMind-analytics/services/analytics
PYTHONPATH=. .venv/bin/python3 -m uvicorn app.server:app --host 0.0.0.0 --port 9076 &

# 2. 확인
curl -s -o /dev/null -w "%{http_code}" http://localhost:9076/gallery  # → 200
curl -s http://localhost:9076/gallery | grep "새로_추가한_리포트_ID"     # → 존재 확인
```

**규칙:**
- 데모 영상 분석 완료 시: `gallery.py` 수정 + `data/reports/` JSON 추가 → **프로덕션 서버 재시작**까지 한 번에 완료
- 프로덕션 포트: **9076** (개발: 76)
- 프로덕션 URL: `https://analytics.fencingmind.ai/gallery`
- 프로덕션은 개발과 같은 디렉토리(`services/analytics/`)에서 실행됨 — 코드 변경이 재시작만으로 반영됨

---

## 모듈 설명

### analyzer/ — v3 분석기 (services/data/video/fencing_analyzer_v3.py에서 분해)

| 모듈 | 원본 메서드 | 역할 |
|------|------------|------|
| `models.py` | 데이터클래스들 | Phase 1: ScoreState, StableScore, LampState, MatchEvent / Phase 2: PoseKeypoint, FencerPose, PoseResult, Weapon, FencingAction, ActionPrediction, ActionResult, EnrichedMatchEvent |
| `config.py` | `__init__` 상수들 | HSV 범위, 임계값, 7-segment 패턴맵, POSE_*, ACTION_*, DEVICE_*, ENRICHED_*, COCO KP 인덱스, 거리/풋워크/빠라드 상수 |
| `lamp_detector.py` | `detect_lamp()` | 밝기 + HSV 색상으로 LED ON/OFF 감지 |
| `score_reader.py` | `read_7segment_digit()`, `match_digit_template()`, `get_score_roi_mask()` 등 | 7세그먼트 OCR, 템플릿 학습/매칭, 시계 읽기 |
| `video_processor.py` | `process_video()`, 이벤트 처리 로직 | 메인 루프, ROI 선택, 이벤트 추적, JSON/CSV 저장 |
| `tv_overlay_ocr.py` | Phase 5a 신규 | TVOverlayOCR (Tesseract OCR), TVScoreTracker (디바운스), OverlayData/TVTouchEvent |

### ml/ — ML + 분석 모듈

| 모듈 | 역할 |
|------|------|
| `pose_estimator.py` | YOLO11-Pose 래퍼 (관절 17개 추출) |
| `action_classifier.py` | VideoMAE 행동 분류 + FACTS 방향 매핑 |
| `integrated_analyzer.py` | 2-pass 통합 분석 (LED/OCR + Pose/Action) |
| `report_generator.py` | 분석 결과 → MatchReport 변환 |
| `video_source_detector.py` | 영상 유형 자동 감지 (휴리스틱) |
| `quality_gate.py` | 영상 품질 평가 (유형별 프로파일) |
| `tv_analyzer.py` | TV 중계 교육 분석 파이프라인 |
| `pose_analyzer.py` | **[Phase 5c+7b]** 풋워크/빠라드/거리 분석 + 관절 키네마틱 + 프레임별 동작 상태 분류 (규칙 기반, ML 불필요) |
| `fencer_profile.py` | **[Phase 6]** FencerProfileBuilder: bout/continuous 결과 집계, 강점/약점 자동 생성 |
| `clip_overlay.py` | **[Phase 7a]** ClipOverlayGenerator: YOLO 스켈레톤 + HUD 텍스트 오버레이 mp4 클립 생성 |

### app/ — 웹 서비스 모듈

| 모듈 | 역할 |
|------|------|
| `server.py` | FastAPI 메인 앱, 모든 엔드포인트 + 3-tier broadcast 분석 폴백 |
| `demo.py` | 데모 리포트 생성 (Pool 5-3 + DE 15-11) |
| `tv_report_converter.py` | TVScoreTracker 출력 → MatchReport dict 변환 (OCR 인사이트 포함) [Phase 5a+] |
| `upload.py` | 영상 업로드 처리 (파일 저장, 검증) |
| `credits.py` | 크레딧 시스템 (in-memory) |
| `report_renderer.py` | HTML 리포트 렌더링 |
| `pdf_exporter.py` | PDF 내보내기 스캐폴드 |
| `filming_guide.py` | 촬영 가이드 (유형별, 한국어/영어) |

### pipeline/ — fencing-AI에서 포팅

| 모듈 | 원본 | 주요 변경 |
|------|------|----------|
| `downloader.py` | `1-download_vids.py` | pytube → yt-dlp, anti_bot 옵션, download_bout_clips() |
| `clip_cutter.py` | `2-fast_clip_cutter.py` | logistic classifier → v3의 LampDetector + ScoreReader |
| `auto_labeler.py` | `3-data_labeller.py` | 픽셀 비교 → v3의 LED 감지 + OCR |
| `data_augmentor.py` | `5-data_multiplier.py` | ffmpeg 파이프 → cv2.VideoWriter |
| `tv_data_collector.py` | Phase 5a 신규 | YouTube TV → OCR → 클립 → 라벨 CSV E2E 파이프라인 |

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
- [x] **246개 테스트** (Phase 1-3: 171 + Phase 4a: 75)

### Phase 4b: Auto-ROI + DB 레이어 + 휴리스틱 라벨러 (완료 — 2026-05-26)
- [x] 자동 ROI 감지 — LED/점수판 영역 자동 탐색
- [x] Supabase DB 레이어 — analytics_* 테이블 연결 준비
- [x] 휴리스틱 라벨러 — 규칙 기반 자동 동작 라벨링
- [x] E2E 통합 — 전체 파이프라인 end-to-end 검증

### Phase 4c: 투자자 데모 폴리싱 (완료 — 2026-05-27)
- [x] **선수 이름 표시** — "Left"/"Right" → 김민수/박지현 (데모), 이준호/최서연 (DE)
- [x] **DE 경기 데모** — 에페 15-11, 26터치, 3기간제, `/demo/de` 엔드포인트
- [x] **랜딩 페이지 신규** — 히어로, 3단계 설명, 4대 기능, 가격표, 데모 프리뷰
- [x] **한국어 동작명** — action_ko 매핑 (공격, 리포스트, 카운터어택, 르미즈)
- [x] **코칭 인사이트 업그레이드** — 4개→6개, 선수 이름 타겟, 전문적 내용
- [x] **Chart.js 선수 이름** — 스코어 타임라인·도넛 차트에 선수 이름 반영
- [x] **핵심 지표 바** — 총 터치, 경기 시간, AI 분석 시간, 분석 프레임 수
- [x] **네비게이션 업그레이드** — 로고→/, 데모 네비 링크, 크레딧 block override
- [x] **데모 대시보드** — 크레딧 100, 현실적 파일명/날짜, 3개 작업
- [x] **통합 테스트 확장** — 39→52개 (DE 데모, 랜딩, 선수 이름 검증)
- [x] **259개 테스트** 전체 (Phase 1-3: 171 + Phase 4a: 75 + Phase 4c: +13)

### Phase 5a: TV 오버레이 OCR + 파인튜닝 데이터 수집 (완료 — 2026-05-27)
- [x] **TVOverlayOCR** — USA Fencing 스타일 TV 오버레이 바 OCR (`analyzer/tv_overlay_ocr.py`)
  - 점수/이름/시간/period/카드 추출, HSV 색상 필터링 + Tesseract OCR
  - 레이아웃 프리셋 시스템 (`OVERLAY_LAYOUTS`), 해상도 자동 스케일링
  - `_preprocess_region`: 스케일업 + 색상 마스킹 + 모폴로지 연산
- [x] **TVScoreTracker** — 프레임별 점수 추적 + 터치 이벤트 감지
  - 디바운싱 로직 (15프레임=0.5초), OCR 오류 필터링 (점수 감소 무시)
  - `TVTouchEvent` 데이터클래스 (프레임, 타임스탬프, 득점자, 점수 변화)
- [x] **VideoDownloader 강화** — `anti_bot` 옵션 (UA/지연/재시도/쓰로틀링)
  - `download_bout_clips()` 메서드 — 터치 이벤트 기반 클립 자동 분할
- [x] **TVDataCollector** — YouTube → OCR → 클립 → 라벨 CSV E2E 파이프라인
  - `process_video()`, `process_youtube_url()`, `process_playlist()`
  - ActionHeuristicLabeler 통합, labels.csv 자동 생성
- [x] **config.py 확장** — `OVERLAY_*` 상수 18개 (HSV 범위, 임계값, 레이아웃)
- [x] **31개 테스트** — OCR/트래커/직렬화/레이아웃/설정 검증
- [x] **350개 테스트** 전체 (Phase 1-4c: 319 + Phase 5a: 31)

### Phase 5a+: TV OCR 대시보드 연동 + 실제 영상 검증 (완료 — 2026-05-27)
- [x] **tv_report_converter.py** — TVScoreTracker 출력을 MatchReport dict 형식으로 변환 (`app/tv_report_converter.py`)
  - `tv_ocr_to_match_report()`: 이벤트 목록 + summary → report.html/report.js 호환 dict
  - OCR 전용 인사이트 자동 생성: 점수 흐름 분석, 연속 득점 감지, 역전 감지
  - `meta.source_type = "tv_broadcast"`, `meta.analysis_mode = "ocr_only"`
- [x] **server.py 3-tier 폴백** — `_run_broadcast_analysis()` 수정
  - 1순위: TVBroadcastAnalyzer (ML 기반) → 실패 시
  - 2순위: TVOverlayOCR 파이프라인 (Tesseract OCR) → 실패 시
  - 3순위: mock 데이터 (데모용)
  - OCR 진행률 실시간 반영 (`progress_pct` 20~80%)
- [x] **ultralytics 설치 완료** — `.venv`에 `ultralytics>=8.4.0` 설치, 테스트 0 skip
  - `HAS_ULTRALYTICS` skipif 가드 유지 (CI 환경 대응)
- [x] **실제 영상 OCR 검증** — USA Fencing 샘플 (8:49, 1280×720, 30fps)
  - 선수: KHOTLINE Daniel vs GERSTMANN Max
  - 감지: 19 터치, 최종 점수 10-14 (실제 10-15, 마지막 1점 미감지)
  - 이름 OCR: 100% 정확
  - 분석 시간: 1,363초 (~23분) for 15,892 프레임 (Tesseract 병목)
  - GERSTMANN 4연속 터치 감지 (momentum insight)
- [x] **353개 테스트** 전체 (Phase 1-4c: 319 + Phase 5a: 31 + ultralytics 2 복원 + Phase 5a+: 1)

### Phase 5b: 버그 수정 + 매치 타임 + 무기 자동 감지 + 경고 시스템 (완료 — 2026-05-28)
- [x] **동점 승자 버그 수정** — 13-13 동점 시 "Draw" 표시 (기존: 항상 right 선택)
- [x] **match_time_remaining** — TVTouchEvent에 점수판 시간 필드 추가, 리포트에서 점수판 시간 우선 표시
- [x] **영상 잘림 감지** — expected_final_score 대비 최종 점수 미달 시 warning 생성
- [x] **metadata_parser.py** — 파일명/YouTube 제목에서 무기/성별/연령대/bout_type 자동 감지
  - 3종 무기: foil/epee/sabre (영문+한국어)
  - 성별: men/women (영문+한국어, word boundary 처리)
  - 연령대: cadet/junior/senior/veteran/Y10/Y12/Y14
  - 경기 유형: pool(5점)/de(15점) 자동 추론
- [x] **server.py 메타데이터 연동** — OCR 분석 시 파일명에서 무기/성별/연령대 자동 추출 + 리포트 주입
- [x] **DownloadResult.title** — YouTube 제목 추출 (yt-dlp `--print title`)
- [x] **tv_data_collector.py** — labels.csv에 weapon 컬럼 추가
- [x] **report.html** — warnings 섹션 (amber 경고 UI) + 성별/연령대 뱃지 추가
- [x] **테스트 54개** — metadata_parser(42) + tv_report_converter(12)
- [x] **407개 테스트** 전체 (Phase 1-5a+: 353 + Phase 5b: 54)

### Phase 5c: 포즈 기반 라벨링 시스템 (완료 — 2026-05-28)
- [x] **PoseAnalyzer 핵심 모듈** — `ml/pose_analyzer.py` (ML 모델 불필요, 키네마틱 규칙)
  - 거리 계산: Body Height (BH) 단위 — 어깨~발목 높이 기준 상대 거리
  - 5단계 거리 구간: OUT(>1.8), ADV_LUNGE(1.5-1.8), LUNGE(1.2-1.5), EXTENSION(0.8-1.2), INFIGHTING(<0.8)
  - 풋워크 감지: LUNGE(앞발+엉덩이하강), FLECHE(양발전진), ADVANCE, RETREAT, STATIONARY
  - 빠라드 감지: 비득점자 무기팔 손목 Y축 급변위 (사이드뷰 기준)
  - 라벨 제안: 빠라드→riposte, 2초내 재득점→remise, 고속접근→counter_attack, 기본→attack
- [x] **데이터 모델 확장** — `analyzer/models.py`
  - FootworkType, DistanceZone enum
  - FootworkResult, ParryResult, DistanceResult, PoseAnalysisResult dataclass
  - EnrichedMatchEvent에 pose_analysis 필드 추가
- [x] **설정 상수** — `analyzer/config.py`
  - COCO 17 키포인트 인덱스 (KP_LEFT_SHOULDER~KP_RIGHT_ANKLE)
  - 거리 구간/풋워크/빠라드 감지 임계값 14개
- [x] **배치 분석 스크립트** — `scripts/run_pose_analysis.py`
  - YOLO11-Pose → PoseAnalyzer → `data/labeled/pose_analysis_results.json`
  - CLI: `--clips-dir`, `--output`, `--max-clips`
- [x] **라벨링 서버 업데이트** — `scripts/labeling_server.py`
  - 듀얼 데이터 소스: pose_analysis_results.json (primary) + gemini_results.json (fallback)
  - API에 포즈 분석 결과 포함 (거리/풋워크/빠라드/제안)
- [x] **라벨링 UI 업데이트** — `templates/labeling.html`
  - Gemini 박스 → 포즈 분석 패널 (거리 BH+구간 뱃지, 풋워크, 빠라드, 제안 라벨)
  - `A` 키 단축키: 제안 라벨 수락 (액션+방향 자동 입력)
  - Gemini 데이터는 접이식 `<details>` 섹션으로 이동
- [x] **47개 테스트** — `tests/test_pose_analyzer.py` (합성 PoseResult 데이터, 영상 불필요)
  - 거리(13), 풋워크(10), 빠라드(8), 라벨 제안(8), 통합(5), 직렬화(3)
- [x] **454개 테스트** 전체 (Phase 1-5b: 407 + Phase 5c: 47) → Phase 6에서 481개로 확장
- [x] **실제 클립 검증 + 임계값 튜닝** (2026-05-29)
  - **카메라컷 필터링**: `filter_camera_cuts()` — 연속 프레임 간 엉덩이 100px 이상 점프 감지, 잘라낸 프레임만으로 분석
  - **터치 시점 탐색**: `find_touch_moment()` — 클린 프레임 중 최소 거리 프레임을 터치 시점으로 사용
  - **상대 빠라드 변위**: 절대 손목 Y변위 → 상대 변위(손목Δ - 엉덩이Δ)로 전환, 프레임 갭>3 스킵
  - **10클립 테스트**: 거리 정확도 향상 (7/10 out_of_distance → 0/10), 빠라드 오탐 해소 (200-285px → 20-57px)
  - **30클립 검증**: 3개 영상, attack:57% / riposte:40% / counter_attack:3% (Gemini의 100% attack에서 대폭 개선)
  - 알려진 한계: 런지 0건 (hip_drop 임계값 10px이 TV 클립에서 과다), 일부 영상 OOD 8/30

### Phase 5c+: 분석 역량 평가 + 컨설팅 서비스 설계 (2026-05-29)
- [x] **기술 역량 분석 보고서** — 3가지 핵심 질문에 대한 종합 답변:
  - Q1: 실패 공격/방어 성공 분석 → **✅ 구현 완료** (`analyze_continuous()` + 풀 경기 E2E 검증)
  - Q2: 선수별 상세 분석 (거리별 성공률, 자세, 약점) → **✅ 구현 완료** (`FencerProfileBuilder`)
  - Q3: 컨설팅 서비스 (박소윤 분석 + 경쟁 선수 분석) → 인프라 90% 존재, Supabase 연동 필요
- [x] **FencerProfile 컨설팅 서비스 아키텍처 설계 + 구현** — `ml/fencer_profile.py`, 풀 경기 E2E 검증 완료

### Phase 5d: 서비스 연결 + AI 파인튜닝 (예정)
- [ ] **라벨링 세션 실행** — labeling_server.py로 사람 검수 → labels_reviewed.csv 생성
- [ ] Supabase 실적용 — in-memory → DB (analytics_* 8 테이블 실제 적용)
- [ ] 인증 연동 — members 테이블 + 크레딧 실제 결제
- [ ] FACTS 데이터셋 확보 + 실제 파인튜닝 실행 (Mac Studio MPS)
- [x] ~~비디오 스트리밍/재생 + 포즈 오버레이 UI~~ → Phase 7a에서 구현 완료 (clip_overlay.py)
- [ ] PDF 내보내기 실제 구현 (weasyprint 또는 reportlab)

### Phase 6: 고도화 + FencerProfile + 연속 분석 (완료 — 2026-05-29)
- [x] **FencerProfileBuilder** — `ml/fencer_profile.py`: bout/continuous 결과 집계, DistanceStats/FootworkStats/JointAngleStats
  - `add_bout()`: 터치별 PoseAnalysisResult → 거리/풋워크/빠라드/관절 각도 누적
  - `add_continuous()`: ContinuousAnalysisResult → 공격/방어 성공률 누적
  - `build()`: 자동 강점/약점/추천 생성
- [x] **연속 포즈 분석 모델** — `analyzer/models.py` 확장
  - `JointAngles`: hip_angle, front_knee_angle, rear_knee_angle, trunk_lean_deg, arm_extension_ratio
  - `ContinuousAnalysisResult`: exchanges, total_exchanges, my_fencer_summary
  - `NonScoringEventType`: FAILED_ATTACK, SUCCESSFUL_DEFENSE, MUTUAL_RETREAT
  - `ExchangeEvent`: non-scoring 교환 데이터 모델
- [x] **임계값 튜닝** — PoseAnalyzer 카메라컷 필터링 + 상대 빠라드 변위
- [x] **my_fencer 지정** — 특정 선수 분석 모드 (컨설팅 서비스 기반)
- [x] **CLI 확장** — `run_pose_analysis.py` + `run_batch_analysis.py` 배치 처리
- [x] **데모 데이터** — demo.py에 pose_analysis + fencer_profile 포함
- [x] **대시보드 표시** — report.html에 포즈 분석 상세 섹션 (관절 각도, 거리 분포, 풋워크, 강점/약점)
- [x] **27개 신규 테스트** — test_pose_analyzer.py (47→68, +21) + test_fencer_profile.py (6)
- [x] **481개 테스트** 전체 통과
- [x] **실측 검증: 10클립 터치 분석** — 3.3초/클립, attack:1 / riposte:5+3 분포
- [x] **실측 검증: 풀 경기 연속 분석 E2E** (2개 영상):
  - `usaf_7Amgqc5HJR0.mp4` (3.8분): 16 exchanges (11 failed_attack, 5 successful_defense), 51.8초
  - `usaf_3XTpDrDSvUs.mp4` (6.7분): 45 exchanges (34 failed_attack, 11 successful_defense), 73.2초
  - 처리 속도: **0.18-0.2x realtime** (5x 실시간보다 빠름)
  - ~~알려진 한계: 공격 성공률 0%~~ → **해결됨** (Phase 7b Step 2: scoring_frames tolerance 매칭, 64.3% 달성)

### Phase 7a: 리포트 UI 개선 + 영상 구간 재생 (완료 — 2026-05-29)

- [x] **경기 이벤트 탭 UI** — "교환 타임라인" → "경기 이벤트 분석" 탭 구조로 전면 교체
  - 탭 1: 전체 (득점 + 비득점 교환 통합)
  - 탭 2: 어택 성공 (터치/득점만)
  - 탭 3: 어택 실패 (비득점 교환만, 유형별 분포 포함)
- [x] **공격자/방어자 표시** — 교환별 attacker/defender 풋워크 기반 추론 + 선수 이름 표시
- [x] **선수별 교환 통계** — fencer_stats (공격 N회, 방어 N회) 카드, my_fencer 0% 카드 제거
- [x] **OCR 머지 확장** — weapon/bout_type/gender/age_group 필드 OCR 리포트에서 자동 병합
- [x] **포일 영상 분석 완료** — `usaf_hKUXgUsDOKE.mp4` (Jr Foil Final, 11:49)
  - 224 exchanges, 22 OCR touches, 15-7, 167.2초 (0.24x realtime)
- [x] **영상 구간 재생 + 포즈 오버레이** — 이벤트 클릭 시 해당 구간 영상 재생
  - `ml/clip_overlay.py` — ClipOverlayGenerator (YOLO skeleton + cv2 text HUD + mp4 encoding)
  - YOLO `result.plot()` — 관절 스켈레톤 자동 오버레이
  - 거리(BH)/풋워크/빠라드 텍스트 HUD 오버레이 (`cv2.putText`, 반투명 배경)
  - 이벤트당 +-2초 패딩, `data/clips/overlay/` 캐싱
  - `GET /api/analytics/clips/{report_id}/{event_type}/{event_number}` — on-demand 클립 스트리밍
  - `POST /api/analytics/clips/{report_id}/generate` — 배치 클립 생성 (background task)
  - report.html 이벤트 카드에 ▶ 재생 버튼 + 비디오 모달 (로딩/에러/재생 상태)
  - `--with-overlays` / `--overlays-all` CLI 플래그 (`generate_continuous_report.py`)
  - **19개 신규 테스트** — annotation, HUD, clip generation, endpoint, template 검증
- [x] **500개 테스트** 전체 통과 (481 + 19)

### Phase 7b: 리포트 2-패널 + 클립 인라인 + 프레이즈 다름 경계 탐지 (완료 — 2026-06-01)
- [x] **2-패널 레이아웃 재설계** — `report.html` 전면 교체
  - 왼쪽 패널(440px sticky): 경기 영상 + 인라인 클립 재생
  - 오른쪽 패널(flex-1): 분석 콘텐츠 (summary, chart, table, stats, events)
  - `max-w-[1600px] flex flex-col lg:flex-row lg:gap-8` 외곽 그리드
  - `lg:sticky lg:top-20 lg:self-start lg:max-h-[calc(100vh-6rem)]` 왼쪽 패널 고정
- [x] **모바일 sticky 수정** — `lg:sticky` → `sticky top-16 lg:top-20`
  - 모바일: `max-h-[60vh]` (영상이 화면 60% 차지)
  - 데스크톱: `max-h-[calc(100vh-6rem)]` (navbar 제외)
  - `z-10` stacking context 추가
- [x] **클립 인라인 재생** — 모달 방식 → 왼쪽 패널 인라인 재생으로 전환
  - `<div id="clip-player-container">` 인라인 비디오 플레이어
  - `fetch(url)` GET + blob URL 패턴 (HEAD 미지원 문제 해결)
  - 서버 에러 JSON 파싱, 로딩/에러 상태 표시
  - ▶ 클릭 시 `scrollIntoView({ behavior: 'smooth' })` 자동 스크롤
- [x] **영상 타이틀 제거** — sticky 상태에서 공간 확보 (`p-4` → `p-2`)
- [x] **CSS 업데이트** — `static/css/analytics.css`
  - `.report-left-panel` 스크롤바 스타일 (4px, 반투명)
  - `@media print` 단일 컬럼 오버라이드
- [x] **클립 플레이어 검증** — Playwright 브라우저 테스트
  - 2-패널 레이아웃 데스크톱/모바일 확인
  - ▶ 클릭 → YOLO 포즈 오버레이 클립 인라인 재생 확인
  - 405 에러 수정 (HEAD → GET + blob URL)
- [x] **프레이즈 다름(Phrase d'armes) 경계 탐지 — 6항목 전체 구현** (2026-05-31~06-01)
  - **Step 2: scoring_frames 연동** — OCR 터치 이벤트 → `analyze_continuous(scoring_frames=...)` 전달
    - tolerance 기반 매칭: `SCORING_FRAME_TOLERANCE_SEC = 2.0` (OCR 점수 변화가 실제 터치보다 0.5-2초 지연)
    - `generate_continuous_report.py`: OCR 리포트 로드 → scoring_frames 추출 → 샘플링 보정 → 전달
    - 공격 성공률 0% → 64.3% (PRIMUS vs KOVALEV 검증)
  - **Step 3: 짧은 SEPARATION 병합** — `EXCHANGE_MERGE_SEPARATION_FRAMES = 10`
    - `_detect_exchanges()` 상태 기계에서 10프레임 이내 재접근 → 같은 교환으로 병합
    - 연속 공격(마르쉬→런지→리포스트) 시퀀스가 하나의 교환으로 유지됨
  - **Step 4: 시계 OCR → Allez/Halt 감지** — `TVScoreTracker._update_clock_state()`
    - `CLOCK_RUNNING_CONFIRM_FRAMES = 3`, `CLOCK_STOPPED_CONFIRM_FRAMES = 5`
    - 시계 상태 기계: unknown → running(Allez) → stopped(Halt) 전환
    - `get_clock_events()` → `[{"frame": N, "event": "allez"|"halt", "time": "M:SS"}]`
    - 파이프라인 전파: `tv_data_collector.py` → `server.py` → 리포트 JSON
  - **Step 5: 관절별 속도/가속도 프로파일** — `JointKinematics`, `FrameKinematics` dataclass
    - `compute_joint_kinematics()`: 8개 관절 (양쪽 wrist/ankle/hip/shoulder)
    - velocity_px (px/frame), velocity_bh (BH/frame), acceleration_px (px/frame²)
    - 카메라컷 필터링 적용 (hip 점프 > 100px → 스킵)
  - **Step 6: 프레임별 동작 상태 분류** — `ActionState` enum (9가지 + UNKNOWN)
    - EN_GARDE, MARCHE, RETRAITE, FENTE, FLECHE, PARADE, RIPOSTE, PREPARATION, RECOVERY
    - `classify_frame_action()`: kinematics + footwork + parry 조합 → 프레임별 상태 결정
    - `classify_action_sequence()`: 전체 시퀀스 분류
    - `analyze_continuous()`에서 양쪽 선수 action_state_summary 자동 계산
  - **Step 7: Phrase 경계 annotated 데이터셋** — `scripts/generate_phrase_dataset.py`
    - `PhraseAnnotation` dataclass: video_id, phrase_id, start/end_frame, trigger, outcome, action_sequence
    - continuous report JSON → exchange 경계 → phrase 어노테이션 JSON 변환
    - `data/datasets/phrase_boundaries.json` 출력
  - **E2E 검증**: PRIMUS vs KOVALEV (B6k6SoJFAr8) 재분석 완료
    - scoring_frames: 22개, 공격 성공률: 64.3% (left), 방어 성공률: 42.9%
    - action_state_summary: left(en_garde 52.1%), right(en_garde 34.5%)
    - 프로덕션 배포 완료 (port 9076)
- [x] **531개 테스트** 전체 통과 (500 + 31 신규)
  - test_pose_analyzer.py: 68→92 (+24: scoring_frames 4개, SEPARATION 병합 4개, kinematics 4개, action_state 8개, phrase 4개)
  - test_tv_overlay_ocr.py: 31→35 (+4: clock state tracking)
  - test_integration.py: +3 (clock events 연동)

### Phase 8: 미구현 항목 (예정)
- [ ] 종목별 분석 로직 (Weapon-specific analyzer: foil/epee/sabre)
- [ ] Active Learning — low-confidence 예측 수동 검수 큐
- [ ] Supabase 실적용 — in-memory → DB (analytics_* 8 테이블)
- [ ] 인증 연동 — members 테이블 + 크레딧 실제 결제
- [ ] FACTS 데이터셋 확보 + 실제 파인튜닝 실행 (Mac Studio MPS)
- [ ] PDF 내보내기 실제 구현 (weasyprint 또는 reportlab)

### Phase 7b 연구: 프레이즈 다름(Phrase d'armes) 경계 탐지 (2026-05-31, 구현 완료 2026-06-01)

**문제 정의**: 클립 재생 시 점수 변화 프레임 기준 ±2초 대칭 패딩 → 실제 공격 동작이 아닌 선수 복귀 장면이 재생됨

> **상태**: 3-tier 모두 구현 완료 (Step 2~7). Tier 1(Clock OCR) + Tier 2(거리/속도 상태 기계) + scoring_frames 연동 + 키네마틱 + 프레임별 동작 분류 + 데이터셋 생성까지 전체 파이프라인 구축됨.

**타임라인 분석**:
```
실제 시간 순서:
  선수 접근(Allez) → 연속 동작(마르쉬/런지/팡트 etc) → 램프 점등 → 심판 판정 → 점수 변경(OCR 감지) → 복귀
  ────────── 분석 대상 ──────────── ← 0.5-2초 → ← OCR 감지 시점

현재 클립 패딩:
  [OCR프레임 - 2초] ─────── [OCR프레임] ─────── [OCR프레임 + 2초]
                                  ↑ 점수 변화 시점 기준
                    ← 복귀 장면 포함 →        ← 완전히 복귀 장면 →
```

**연구 결과 — 3-tier 하이브리드 접근법**:

| Tier | 방법 | 정확도 | 적용 조건 |
|------|------|--------|----------|
| **1** | Clock OCR (Allez/Halt 프록시) | 높음 | TV 중계 (점수판에 시계 표시) |
| **2** | 거리/속도 기반 상태 기계 | 중간 | 모든 영상 (보편적 폴백) |
| **3** | 비대칭 패딩 (경험적) | 낮음 | 즉시 적용 가능 |

**Tier 1: Clock OCR (TV 중계 전용)**
- TV 점수판의 시계가 움직이는 구간 = 경기 진행 중 (Allez 이후)
- 시계 정지 = Halt (프레이즈 종료)
- TVOverlayOCR에 이미 시간 읽기 기능 있음 → `is_clock_running()` 메서드 추가 가능
- 한계: 시계 해상도 1초, OCR 오류 가능

**Tier 2: 거리/속도 기반 상태 기계 (보편적)**
- PoseAnalyzer의 `compute_distance_series()` 활용
- 상태: IDLE → APPROACH (closing_speed > threshold) → ACTION (min distance) → SEPARATION
- 프레이즈 시작 = IDLE→APPROACH 전환점 (접근 시작)
- 프레이즈 종료 = 램프 점등 or 최소 거리 후 급격한 분리
- 실패 공격: APPROACH → 최소 거리 미달 → 바로 SEPARATION
- 한계: 비가시적 동작(플뢰레 내선/외선), 느린 접근 구별 어려움

**Tier 3: 비대칭 패딩 (즉시 적용)**
- 현재: `pad_seconds = 2.0` (대칭, `clip_overlay.py`)
- 개선: `pad_before = 3.0`, `pad_after = 0.5` (비대칭)
- 근거: 점수 변화는 실제 터치보다 0.5-2초 후에 발생 → 앞으로 더 많이 패딩
- 즉시 구현 가능, 완벽하지 않지만 현재보다 확실히 개선

**구현 우선순위** (전체 완료 2026-06-01):
1. ~~Tier 3 (비대칭 패딩)~~ — 비대칭 패딩 대신 scoring_frames tolerance 기반 매칭으로 대체 (Step 2)
2. ~~Tier 2 (거리 기반)~~ — ✅ SEPARATION 병합 + 키네마틱 + 프레임별 동작 분류 구현 (Step 3,5,6)
3. ~~Tier 1 (Clock OCR)~~ — ✅ `TVScoreTracker._update_clock_state()` + `get_clock_events()` 구현 (Step 4)

**분석 대상 케이스 분류**:
| 케이스 | 현상 | 분석 대상 |
|--------|------|----------|
| 공격 성공 | 점수 올라감 + 색 램프 | 프레이즈 시작 → 램프 점등 |
| 공격 실패 (백색 램프) | 점수 불변 + 백 램프 | 프레이즈 시작 → 백 램프 |
| Halt (점수 불변) | 점수 불변 + 심판 정지 | 프레이즈 시작 → Halt |
| 연속 교환 | 빠른 공격-방어-리포스트 | 전체 프레이즈 (다중 동작) |

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
│ Layer 2: 풋워크/방어 (포즈 궤적 분석) — Phase 5c 구현 완료       │
│  LUNGE, FLECHE, ADVANCE, RETREAT, STATIONARY + PARRY 감지      │
│  → PoseAnalyzer: COCO 키포인트 궤적 분석 (ML 불필요, 규칙 기반) │
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

### 결정 15: TV 중계 분석 3-tier 폴백 (2026-05-27)
- **이유**: ML 모델(TVBroadcastAnalyzer)이 불안정할 때 사용자에게 빈 결과를 보여주면 안 됨
- **결정**: ML → OCR → mock 순서의 graceful degradation
  - 1순위: TVBroadcastAnalyzer (VideoMAE + Pose) — 정밀 동작 분류 가능
  - 2순위: TVOverlayOCR (Tesseract) — 점수/이름만, 동작 분류 불가
  - 3순위: mock 데이터 — 데모 데이터로 UI 동작 확인용
- **근거**: 실제 서비스에서 OCR만으로도 유의미한 분석 제공 가능 (점수 흐름, 연속 득점, 역전 등)

### 결정 16: OCR 모드에서 동작 분류 불가 수용 (2026-05-27)
- **이유**: TV 오버레이 OCR은 점수판 숫자만 읽을 수 있음, 선수의 블레이드 동작은 영상 분석 필요
- **결정**: OCR 결과의 action 필드를 "unknown"으로 설정, report.html에서 빈 차트 정상 표시
- **해결 경로**: FACTS 데이터셋 → VideoMAE 파인튜닝 → OCR + ML 결합 → 동작 분류 활성화

### 결정 17: Gemini Vision → PoseAnalyzer 전환 (2026-05-28)
- **이유**: Gemini Vision이 30개 클립 전부 "attack" (100%)로 분류 — 블레이드 접촉(빠라드)을 시각적으로 구별 못함
- **근본 원인**: 득점자의 최종 동작만 보면 attack이든 riposte든 시각적으로 동일
- **결정**: Gemini 대신 YOLO11-Pose 관절 좌표의 키네마틱 분석으로 전환
  - 비득점자가 빠라드 → 득점자 액션은 riposte
  - 같은 선수 2초 내 재득점 → remise
  - 양쪽 고속 접근 → counter_attack 가능성
- **구현**: `ml/pose_analyzer.py` — ML 모델 없이 규칙 기반 (풋워크 + 빠라드 + 거리)
- **검증 완료** (2026-05-29): 30클립 검증 — attack:57%, riposte:40%, counter_attack:3%

### 결정 18: 카메라컷 필터링 + 상대 빠라드 변위 (2026-05-29)
- **이유**: 실제 TV 클립 검증 시 두 가지 문제 발견
  1. 카메라 전환 시 관절 좌표 점프 → 거리/풋워크/빠라드 전부 왜곡
  2. 빠라드 감지에서 절대 손목 변위 사용 → 접근 중 신체 이동이 200+px로 오탐
- **결정 1 (카메라컷)**: `filter_camera_cuts()` — 연속 프레임 간 hip_center 100px 이상 점프 = 카메라컷으로 마킹
  - `find_touch_moment()` — 클린 프레임 중 최소 거리 프레임을 터치 시점으로 사용
  - 거리 정확도: 7/10 out_of_distance → 0/10
- **결정 2 (상대 변위)**: `detect_parry()` 내에서 absolute wrist_y → relative (wrist_delta - hip_delta)로 변경
  - 프레임 갭 > 3인 쌍 스킵 (카메라컷 잔여 영향 방지)
  - 빠라드 오탐: 200-285px → 20-57px로 대폭 감소
- **실측 결과 (30클립)**: attack:17(57%), riposte:12(40%), counter_attack:1(3%)
- **알려진 한계**:
  - 런지 0건 (hip_drop_min=10px이 TV 클립에서 과다 — 향후 튜닝)
  - 일부 영상(0qllx-vYhGE)에서 8/30 out_of_distance 잔존

### 결정 19: 클립 인라인 재생 + fetch GET + blob URL (2026-05-31)
- **이유**: 기존 모달 방식은 분석 컨텍스트를 가리고, video 엘리먼트의 onerror가 HTTP 404/500을 안정적으로 처리하지 못함
- **결정 1 (모달→인라인)**: 클립을 `fixed inset-0` 모달 대신 왼쪽 패널 내 인라인 비디오로 재생
- **결정 2 (HEAD→GET)**: FastAPI `@app.get`이 HEAD 미지원(405) → `fetch(url)` GET + blob URL 패턴
  - `const blob = await resp.blob(); const blobUrl = URL.createObjectURL(blob);`
  - 서버 에러 시 JSON 파싱 (`resp.json().detail`) → 사용자 친화적 에러 메시지
- **검증**: Playwright 브라우저 테스트로 YOLO 포즈 오버레이 클립 인라인 재생 확인

### 결정 20: 프레이즈 다름 경계 탐지 — 3-tier 하이브리드 접근법 (2026-05-31)
- **이유**: 클립 재생이 점수 변화 시점 기준 ±2초 대칭 패딩 → 복귀 장면만 보임
- **근본 원인**: OCR 점수 변화 = 심판이 점수판 업데이트 시점 (실제 터치보다 0.5-2초 후)
- **결정**: 3단계 점진적 개선 전략
  - Tier 3 (즉시): 비대칭 패딩 (`pad_before=3.0, pad_after=0.5`)
  - Tier 2 (중기): 거리/속도 상태 기계 (`detect_phrase_boundaries()`)
  - Tier 1 (장기): Clock OCR로 Allez/Halt 구간 추적
- **참고 논문**: Allez Go (2024) — 오디오 Allez/Halt 감지 89.1%
- **한계**: 시각적 방법만으로는 연속 동작의 시작점 정확 탐지 어려움 (마르쉬→런지→팡트 연속)

### 결정 21: 2-패널 리포트 레이아웃 (2026-05-31)
- **이유**: 단일 컬럼에서 영상→분석 스크롤이 너무 김, 영상 참조하면서 분석 읽기 불가
- **결정**: 왼쪽(440px sticky 영상) + 오른쪽(flex-1 분석) 2-패널 레이아웃
- **모바일**: `< lg`에서 `flex-col` → 영상 상단 60vh sticky, 분석 하단
- **데스크톱**: `>= lg`에서 `flex-row` → 영상 왼쪽 고정, 분석 스크롤

### 결정 22: scoring_frames tolerance 매칭 (2026-06-01)
- **이유**: OCR 점수 변화 감지 시점이 실제 터치보다 0.5-2초 늦음 (심판 판정 → 점수판 업데이트 지연)
- **결정**: `SCORING_FRAME_TOLERANCE_SEC = 2.0` — 교환의 min_dist_frame 기준 ±2초 윈도우 내에 scoring_frame이 있으면 매칭
- **구현**: `_build_my_fencer_summary()`와 `_classify_exchange()`에서 tolerance 기반 매칭 적용
- **결과**: 공격 성공률 0% → 64.3% (PRIMUS vs KOVALEV 검증)
- **trade-off**: 2초 윈도우가 넓으면 false positive 가능 → 실측에서 문제 없음 확인

### 결정 23: 짧은 SEPARATION 병합 (2026-06-01)
- **이유**: `_detect_exchanges()` 상태 기계에서 연속 공격(마르쉬→런지→리포스트) 시퀀스가 여러 개의 짧은 교환으로 쪼개짐
- **결정**: `EXCHANGE_MERGE_SEPARATION_FRAMES = 10` — 10프레임(~0.3초) 이내 재접근 시 같은 교환으로 병합
- **구현**: SEPARATION 상태에서 거리가 다시 줄기 시작할 때 분리 지속 시간 체크 → 짧으면 APPROACH 복귀
- **근거**: 실제 프레이즈 다름은 2-5초 지속, 0.3초 분리는 동일 프레이즈 내 전환

### 결정 24: Clock OCR 상태 기계 (2026-06-01)
- **이유**: TV 중계에서 시계가 움직이는 구간 = Allez(경기 진행), 시계 정지 = Halt(프레이즈 종료)
- **결정**: `CLOCK_RUNNING_CONFIRM_FRAMES = 3`, `CLOCK_STOPPED_CONFIRM_FRAMES = 5` — 연속 N프레임 확인 후 상태 전환
- **구현**: `TVScoreTracker._update_clock_state()` — unknown/running/stopped 상태 기계, 디바운싱 적용
- **파이프라인**: tv_data_collector → server.py → continuous report JSON에 `clock_events` 저장
- **한계**: 시계 해상도 1초, OCR 오류 시 spurious 이벤트 가능 → confirm_frames로 완화

### 결정 25: 규칙 기반 프레임별 동작 분류 — ML 미사용 (2026-06-01)
- **이유**: VideoMAE 파인튜닝 없이도 프레이즈 경계 탐지에 필요한 동작 분류 가능
- **결정**: kinematics(관절 속도/가속도) + footwork(전진/후퇴/런지) + parry 조합으로 9가지 ActionState 분류
- **분류 규칙**:
  - EN_GARDE: velocity_max < threshold AND 적정 거리
  - FENTE: 앞발 전진 + hip drop (런지 패턴)
  - PARADE: 비득점자 손목 횡방향 급변위
  - RIPOSTE: 파라드 직후 전진
- **구현**: `classify_frame_action()` + `classify_action_sequence()` → `analyze_continuous()`에서 호출
- **한계**: threshold 기반이므로 영상 스타일/거리에 따라 정확도 변동 → 향후 ML 모델로 대체 가능

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

### TV OCR 분석 모드 (Phase 5a+ 실측)

TVOverlayOCR + TVScoreTracker를 이용한 TV 중계 영상 점수 추적:

| 영상 | 길이 | 프레임 | sample_interval | 분석 시간 | 배율 | 결과 |
|------|------|--------|----------------|----------|------|------|
| USA Fencing 샘플 | 8:49 | 15,892 | 5 | 1,363초 (~23분) | 2.6x | 19터치, 10-14 (실제 10-15) |

- **병목**: Tesseract OCR (~85ms/프레임, sample_interval=5이면 매 5프레임마다)
- **정확도**: 이름 100%, 점수 76% 읽기율, 최종 점수 1점 차이
- **최적화 기회**: EasyOCR 전환, sample_interval 증가(10~15), ROI 캐싱

### 연속 포즈 분석 모드 (Phase 6 실측, 2026-05-29)

`PoseAnalyzer.analyze_continuous()` — 매 sample_every_n 프레임 YOLO11-Pose 실행:

| 영상 | 길이 | 샘플 프레임 | 교환 감지 | 처리 시간 | 배율 |
|------|------|-----------|----------|----------|------|
| usaf_7Amgqc5HJR0 | 3.8분 (228초) | 2,282 | 16 교환 | 51.8초 | **0.23x** |
| usaf_3XTpDrDSvUs | 6.7분 (404초) | 4,036 | 45 교환 | 73.2초 | **0.18x** |

→ **5x 실시간보다 빠름** — 풀 경기 6.7분을 73초에 분석
→ sample_every_n=3 (매 3프레임), YOLO11-Pose batch 처리

**Phase 7b 이후 (scoring_frames + kinematics + action_state 포함)**:

| 영상 | 길이 | 교환 | 공격 성공률 | 처리 시간 | 추가 데이터 |
|------|------|------|----------|----------|-----------|
| usaf_B6k6SoJFAr8 (PRIMUS vs KOVALEV) | 9:35 | 63교환 | 64.3% (left) | ~120초 | scoring_frames:22, action_state_summary, kinematics |

→ scoring_frames 연동으로 공격 성공률 정상 계산 (이전 0% → 64.3%)

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

| 영역 | Phase 1 | Phase 2 | Phase 3 | Phase 4a | Phase 5a+ | Phase 5c | Phase 6 | Phase 7b (현재) |
|------|---------|---------|---------|----------|----------------|-------------|-------------|-------------|
| 영상 처리 | OpenCV 4.x | 유지 | 유지 | 유지 | + Tesseract OCR | 유지 | 유지 | 유지 |
| LED/점수 | 7-segment OCR | 유지 | 유지 | 유지 | + TV 오버레이 OCR | 유지 | 유지 | + **Clock OCR (Allez/Halt)** |
| 포즈 추정 | — | YOLO11-Pose | 유지 | 유지 | 유지 | + PoseAnalyzer | 유지 | 유지 |
| 행동 인식 | — | VideoMAE (K400) | FACTS 정렬 | Mock fallback | 유지 | 유지 | 유지 | + **ActionState 분류 (규칙 기반)** |
| 풋워크/빠라드 | — | — | — | — | — | **PoseAnalyzer** | 유지 | + **SEPARATION 병합** |
| 키네마틱 | — | — | — | — | — | — | JointAngles | + **JointKinematics (속도/가속도)** |
| 선수 프로필 | — | — | — | — | — | — | **FencerProfileBuilder** | + scoring_frames 연동 |
| 프레이즈 경계 | — | — | — | — | — | — | — | **PhraseAnnotation + 데이터셋** |
| TV 분석 | — | — | TVBroadcastAnalyzer | 유지 | + TVOverlayOCR | 유지 | 유지 | + **clock_events 파이프라인** |
| 웹 UI | — | — | — | Jinja2/Tailwind/Chart.js | 유지 | + 라벨링 UI | + 포즈 상세 | + **2-패널 + 인라인 클립** |
| DB | — | — | — | in-memory (스키마) | 유지 | 유지 | 유지 | 유지 |
| GPU | — | Apple Metal (MPS) | 유지 | 유지 | 유지 | 유지 | 유지 | 유지 |

---

## 🔴 분석 역량 평가 + 컨설팅 서비스 아키텍처 (2026-05-29)

### 현재 분석 가능 범위 vs 확장 가능 범위

| 분석 항목 | 현재 상태 | 난이도 | 필요 작업 |
|-----------|----------|--------|----------|
| 득점 시점 분석 (who scored) | ✅ 동작 | — | 완료 |
| 풋워크/빠라드/거리 (터치별) | ✅ 동작 | — | 30클립 검증 완료 |
| 실패 공격 감지 | ✅ 구현 완료 | — | `analyze_continuous()` — 풀 경기 E2E 검증 완료 |
| 방어 성공 (비득점) 감지 | ✅ 구현 완료 | — | `analyze_continuous()` — 풀 경기 E2E 검증 완료 |
| 선수별 거리별 성공률 | ✅ 구현 완료 | — | `FencerProfileBuilder` — DistanceStats 집계 |
| 선수별 풋워크 패턴 | ✅ 구현 완료 | — | `FencerProfileBuilder` — FootworkStats 집계 |
| 페이크 vs 진짜 공격 구분 | ❌ 미구현 | 높음 | 관절 속도 프로파일 분석 필요 |
| 경쟁 선수 분석 (상대 프로필) | ⚠️ 코드 준비됨 | 중간 | FencerProfile 완료, Supabase 연동 필요 |

### Q1: 실패 공격 / 방어 성공 분석 — ✅ 구현 완료

**구현 완료**: `PoseAnalyzer.analyze_continuous()` — 풀 경기 연속 포즈 분석

```
분석 방식: ████████████████████████████████████  ← 전체 경기
           ████████████████████████████████████  ← 매 N프레임 포즈 분석
           → 접근(closing_speed >0) → 빠른 후퇴 = 실패 공격
           → 빠라드 감지 + 후퇴 = 방어 성공
```

**구현 내용**:
- `PoseAnalyzer.analyze_continuous()` — 매 sample_every_n 프레임 포즈 분석
- `_detect_exchanges()` — 상태 기계 (IDLE→APPROACH→SEPARATION)로 교환 감지
- `_classify_exchange()` — failed_attack, successful_defense, mutual_retreat, off_target 분류
- `_build_my_fencer_summary()` — 특정 선수 관점 공격/방어 통계

**풀 경기 E2E 실측 결과 (2026-05-29)**:
| 영상 | 길이 | 교환 | failed_attack | successful_defense | 처리 시간 | 배율 |
|------|------|------|---------------|-------------------|----------|------|
| usaf_7Amgqc5HJR0 | 3.8분 | 16 | 11 | 5 | 51.8초 | 0.23x |
| usaf_3XTpDrDSvUs | 6.7분 | 45 | 34 | 11 | 73.2초 | 0.18x |

~~**알려진 한계**: scoring_frames 데이터 미연동 → 공격 성공률이 0%로 표시.~~ → **Phase 7b Step 2에서 해결** (tolerance 기반 scoring_frames 매칭, PRIMUS vs KOVALEV 검증: 공격 성공률 64.3%)

### Q2: 선수별 상세 분석 — ✅ 구현 완료

**구현 완료**: `ml/fencer_profile.py` — `FencerProfileBuilder` 클래스

PoseAnalyzer 수집 데이터 → FencerProfileBuilder가 집계:
- `DistanceStats`: zone_distribution, zone_success_rate, preferred_zone, avg_closing_speed
- `FootworkStats`: type_distribution, type_success_rate, preferred_footwork
- `JointAngleStats`: avg_hip_angle, avg_front_knee, avg_trunk_lean, avg_arm_extension
- `parry_rate`, `parry_success_to_riposte`
- 자동 생성: `strengths`, `weaknesses`, `recommendations` (한국어)

**사용법**:
```python
builder = FencerProfileBuilder("left")
builder.add_bout(result, scored=True)   # 터치별 결과 누적
builder.add_continuous(continuous_result) # 연속 분석 결과 누적
profile = builder.build()               # 프로필 생성 + 자동 인사이트
```

### Q3: 컨설팅 서비스 아키텍처

**서비스 대상**: 박소윤 (예시) → 본인 분석 + 경쟁 선수 분석

**구현 로드맵**:
```
Phase A: 본인 분석 (인프라 70% 존재)
  ├── 영상 수집: TVDataCollector로 박소윤 경기 클립 수집
  ├── 포즈 분석: run_pose_analysis.py로 배치 처리
  ├── 프로필 생성: FencerProfile 집계 → Supabase 저장
  └── 리포트: 거리별 성공률, 풋워크 패턴, 빠라드 반응, 약점/개선점

Phase B: 경쟁 선수 분석 (추가 개발 필요)
  ├── 경쟁 선수 영상 수집 (대한펜싱협회 대회 결과 → 상위 선수 특정)
  ├── 동일 파이프라인 처리
  ├── 대조 분석: 박소윤 vs 경쟁 선수 FencerProfile 비교
  └── 전략 리포트: 상대 약점, 공략 포인트, 주의점

Phase C: 대회 전 브리핑
  ├── 대진표 공개 → 상대 선수 FencerProfile 자동 조회
  ├── 상대별 맞춤 전략 제안 (거리 관리, 풋워크 대응)
  └── 코치/선수 앱에서 실시간 열람
```

**핵심 의존성**:
1. Supabase `analytics_player_metrics` 테이블 활성화
2. 선수 식별: `players` 테이블과 영상 내 선수 매칭 (OCR 이름 or 수동)
3. 최소 5경기 이상 데이터 축적 → 통계적 유의미성

### 30클립 포즈 분석 검증 결과 (실측, 2026-05-29)

```
영상 3개 × 10클립씩 = 30클립 (USA Fencing TV 중계)
  - usaf_0HeqT9us5wA (10클립): 주로 infighting
  - usaf_0qllx-vYhGE (11클립): OOD 집중 (카메라 스타일 다름)
  - usaf_6MCRWT7GmaU (9클립): 다양한 거리 분포

라벨 분포:
  attack_left:  7 (23%)     riposte_left:  7 (23%)
  attack_right: 10 (33%)    riposte_right: 5 (17%)
                            counter_attack_right: 1 (3%)
  → attack: 17 (57%), riposte: 12 (40%), counter_attack: 1 (3%)

거리 분포 (터치 시점):
  infighting: 11 (37%) | extension: 5 (17%) | lunge: 3 (10%)
  advance_lunge: 3 (10%) | out_of_distance: 8 (27%)

풋워크 분포 (양 선수 합산 60):
  fleche: 20 (33%) | unknown: 13 (22%) | stationary: 12 (20%)
  retreat: 9 (15%) | advance: 6 (10%) | lunge: 0 (0%)

빠라드:
  감지 비율: ~40% 클립에서 최소 한쪽 감지
  오탐 개선: 절대 변위 200-285px → 상대 변위 20-57px

알려진 이슈:
  - 런지 0건: FOOTWORK_LUNGE_HIP_DROP_MIN=10px이 TV 클립에서 과다 (hip_drop이 음수인 경우 다수)
  - OOD 8건: 0qllx-vYhGE 영상에 집중 (카메라 각도/거리가 다른 방송 스타일)
  - fleche 과다: 양발 전진 임계값 20px이 너무 낮을 수 있음
```

---

## 세션 재개 가이드 (2026-06-03 기준)

### 현재 상태 요약
- **브랜치**: `feature/analytics/main`
- **Phase 7b 완료**: 2-패널 레이아웃 + 클립 인라인 재생 + 프레이즈 다름 경계 탐지 6항목 전체 구현
- **프레이즈 다름 구현 완료** (Step 2~7):
  - scoring_frames tolerance 매칭 (공격 성공률 0% → 64.3%)
  - 짧은 SEPARATION 병합 (10프레임 이내 재접근 = 같은 교환)
  - Clock OCR Allez/Halt 감지 (시계 상태 기계)
  - 관절별 키네마틱 (8개 관절 속도/가속도)
  - 프레임별 동작 상태 분류 (EN_GARDE~RECOVERY 9가지)
  - Phrase 경계 어노테이션 데이터셋 생성 스크립트
- **E2E 검증 완료**: PRIMUS vs KOVALEV (B6k6SoJFAr8) 재분석 + 프로덕션 배포
- **테스트**: 531개 전체 통과
- **프로덕션 서버**: port 9076 동작 중 (analytics.fencingmind.ai)

### 작동하는 것 (투자자 데모 플로우)
| 기능 | 상태 | 엔드포인트 |
|------|------|-----------|
| 랜딩 페이지 | ✅ | `GET /` — 히어로, 3단계 설명, 가격표, 데모 프리뷰 |
| 데모 리포트 (Pool) | ✅ | `GET /demo` — 김민수vs박지현, 플뢰레 5-3, 8터치, 선수 이름 |
| 데모 리포트 (DE) | ✅ | `GET /demo/de` — 이준호vs최서연, 에페 15-11, 26터치 |
| 데모 대시보드 | ✅ | `GET /demo/dashboard` — 100 크레딧, 현실적 파일명, 3작업 |
| 영상 업로드 페이지 | ✅ | `GET /upload` |
| 분석 대시보드 | ✅ | `GET /dashboard` |
| Health/Status API | ✅ | `GET /health`, `GET /api/analytics/status` |
| 촬영 가이드 API | ✅ | `GET /api/analytics/filming-guide` |
| TV OCR 분석 (실제) | ✅ | `POST /api/analytics/analyze-broadcast` — OCR 폴백으로 실제 점수 추적 |
| TV OCR 리포트 | ✅ | `GET /report/{job_id}` — 선수 이름, 스코어 타임라인, 인사이트 렌더링 |
| 갤러리 (6개 데모 리포트) | ✅ | `GET /gallery` — 실제 분석 리포트 6개 (포일/에페/사브르) |
| 연속 분석 리포트 | ✅ | `GET /report/saved/{id}` — scoring_frames + action_state_summary 포함 |
| Mock fallback | ✅ | ML/OCR 모두 실패 시 자동으로 데모 데이터 반환 |

### 데모 플로우 (투자자/고객 프레젠테이션)
```
/ (랜딩) → "데모 보기" → /demo (Pool 5-3, 김민수 vs 박지현)
                        → /demo/de (DE 15-11, 이준호 vs 최서연)
                        → /demo/dashboard (100 크레딧, 3 작업)
                        → /upload (실제 업로드 시연)

실제 분석 플로우:
  POST /api/analytics/analyze-broadcast {"video_path": "data/raw/usa_fencing_sample_0HeqT9us5wA.mp4"}
  → job_id 반환 → OCR 분석 (~23분) → /report/{job_id} (실제 선수 이름 + 스코어 + 인사이트)
```

### 스캐폴드 (구조만 있고 실제 동작 X)
| 기능 | 이유 | 해결 방법 |
|------|------|----------|
| 동작 분류 | VideoMAE가 모두 "unknown" 반환 (OCR은 점수만 읽음) | FACTS 파인튜닝 필요 |
| DB 영속성 | in-memory dict 사용 중 | 007 마이그레이션 Supabase 적용 |
| 크레딧 결제 | 메모리 잔액만, 결제 없음 | Stripe/토스 연동 필요 |
| PDF 내보내기 | 함수 시그니처만 존재 | weasyprint/reportlab 구현 필요 |
| 인증 | 없음, 공개 접근 | members 테이블 + JWT 연동 |

### 동작하는 것 (실제 분석)
| 기능 | 상태 | 비고 |
|------|------|------|
| TV 오버레이 OCR | ✅ | 점수/이름/시간 읽기, USA Fencing 레이아웃 |
| 터치 이벤트 감지 | ✅ | 디바운싱, 점수 증가만 인정 |
| Clock OCR (Allez/Halt) | ✅ | 시계 상태 기계, running→stopped 이벤트 생성 |
| 3-tier 폴백 | ✅ | ML → OCR → mock 순서 |
| 리포트 렌더링 | ✅ | OCR 결과도 report.html에서 정상 표시 |
| 포즈 분석 (30클립 검증) | ✅ | 카메라컷 필터링, 상대 빠라드 변위, 라벨 분포 57/40/3 |
| 연속 분석 (풀 경기 E2E) | ✅ | scoring_frames 연동, 공격 성공률 64.3% (이전 0%) |
| 프레임별 동작 분류 | ✅ | ActionState 9가지, 양쪽 선수 action_state_summary |
| 관절 키네마틱 | ✅ | 8개 관절 속도/가속도, BH 정규화, 카메라컷 필터링 |
| FencerProfile 생성 | ✅ | 거리/풋워크/관절각도 집계, 강점/약점/추천 자동 생성 |
| 라벨링 UI (포즈 패널) | ✅ | BH 거리, 풋워크, 빠라드, 제안 라벨 + 'A' 수락 단축키 |
| 2-패널 리포트 레이아웃 | ✅ | 왼쪽(영상 sticky) + 오른쪽(분석), 모바일/데스크톱 반응형 |
| 클립 인라인 재생 | ✅ | 모달 제거, fetch GET + blob URL, YOLO 오버레이 확인됨 |
| Phrase 데이터셋 생성 | ✅ | continuous report → phrase_boundaries.json 변환 |

### 핵심 블로커
1. ~~**PoseAnalyzer 실제 클립 검증 미완**~~ → **해결됨** (2026-05-29, 30클립 검증 + 카메라컷/빠라드 수정)
2. **🔴 FACTS 데이터셋 미확보 (PRIORITY #1)** — 논문 저자 연락 또는 USA Fencing 스트림에서 자체 수집 (TVDataCollector 준비됨) → 상세: [`docs/PRIORITY_1_FACTS_FINETUNING.md`](docs/PRIORITY_1_FACTS_FINETUNING.md)
3. **Supabase 마이그레이션 미적용** — `007_analytics_tables.sql` 준비됨, 적용 필요
4. ~~**ultralytics 미설치**~~ → **해결됨** (2026-05-27)
5. ~~**Gemini Vision attack 100% 문제**~~ → **해결됨** (2026-05-28, PoseAnalyzer로 전환)
6. ~~**런지 감지 미동작**~~ → **튜닝 완료** (2026-05-29, Phase 6 임계값 조정)
7. ~~**FencerProfile 집계 모듈 미구현**~~ → **구현 완료** (2026-05-29, ml/fencer_profile.py)
8. ~~**연속 분석 미검증**~~ → **E2E 검증 완료** (2026-05-29, 풀 경기 2개 → 16+45 교환 감지)
9. ~~**연속 분석 + OCR/LED 통합 미완**~~ → **해결됨** (2026-06-01, scoring_frames tolerance 매칭, 공격 성공률 64.3%)
10. ~~**클립 타이밍 부정확**~~ → **해결됨** (2026-06-01, 프레이즈 다름 경계 탐지 6항목 구현 + Clock OCR)
11. ~~**클립 인라인 재생 미동작**~~ → **해결됨** (2026-05-31, fetch GET + blob URL 패턴)

### 다음 세션 우선순위
1. **클립 타이밍 개선** — 프레이즈 경계 데이터를 클립 패딩에 활용
   - Clock OCR allez/halt 이벤트 → 클립 시작/종료를 프레이즈 경계에 맞춤
   - 거리 기반 APPROACH 시작 → 클립 시작점으로 사용
   - 현재 ±2초 대칭 패딩 → 프레이즈 기반 동적 패딩으로 전환
2. **라벨링 세션 실행** — labeling_server.py → http://localhost:7600
   - 포즈 분석 결과 기반으로 사람이 30개 클립 검수 (ground truth 확립)
   - labels_reviewed.csv 생성 → 학습 데이터
3. **USA Fencing YouTube 대량 수집** — TVDataCollector로 플레이리스트 처리 (`process_playlist()`)
   - USA Fencing 채널 → OCR → 클립 추출 → heuristic labels → labels.csv
4. **FACTS 파인튜닝** — 수집된 데이터 + FACTS 데이터셋으로 VideoMAE 파인튜닝 (Mac Studio MPS)
5. **Supabase 연결** — 007 마이그레이션 적용 → server.py의 in-memory를 DB로 교체
6. **인증** — members 연동, 크레딧 실제 소유자 연결
7. **종목별 분석기** — FoilAnalyzer, EpeeAnalyzer, SabreAnalyzer 구현
8. **PDF 내보내기** — weasyprint 또는 reportlab 구현

### 커밋 이력 (이 브랜치)
```
1f931e6 Merge branch 'feature/shared/i18n-theme' into feature/analytics/main
7ffbf7b Add shared packages: i18n, auth, UI design system, logos
2a39131 Fix clip player: use GET+blob URL instead of HEAD, parse server error JSON
3242b9d Add 2-panel report layout with mobile sticky and inline clip player
a69cf12 Add Phase 4c+5a+5a+: TV OCR dashboard, broadcast analysis fallback, ultralytics fix
6e90480 Add analytics Phase 4b: auto-ROI detection, Supabase DB layer, heuristic labeler, E2E integration
ea2f969 Update CLAUDE.md: Phase 4a completion status and session resume guide
2837ff5 Fix Jinja2 template rendering on Python 3.14
e9795e2 Add demo mode and integration tests for analytics web service
6a17f02 Add analytics Phase 4: Web UI, upload API, credit system, report rendering, DB migration
7cb88b4 Add analytics Phase 2-3: AI models, video source detection, TV analysis, FACTS pipeline
79264a8 Set up unified test environment and Phase 2 dependencies
2ab7054 Add analytics service Phase 1: v3 analyzer refactor + fencing-AI pipeline
e0ec750 Refactor to monorepo structure for FencingMind multi-subdomain architecture
```

> **참고**: Phase 7b 프레이즈 다름 구현(Step 2~7)은 아직 미커밋 상태. 커밋 필요.

### 서버 실행 커맨드
```bash
cd /Users/gyejinpark/Documents/GitHub/FencingMind-analytics/services/analytics

# 메인 서버 (분석 + 데모)
PYTHONPATH=. .venv/bin/python3 -m uvicorn app.server:app --host 0.0.0.0 --port 76
# 브라우저: http://localhost:76/
# 데모 플로우: http://localhost:76/demo → /demo/de → /demo/dashboard

# 라벨링 서버 (포즈 분석 기반 검수)
PYTHONPATH=. .venv/bin/python3 scripts/labeling_server.py
# 브라우저: http://localhost:7600/
# 사전 필요: data/labeled/pose_analysis_results.json (run_pose_analysis.py로 생성)

# 배치 포즈 분석 (클립 → 포즈 분석 결과)
PYTHONPATH=. .venv/bin/python3 scripts/run_pose_analysis.py --clips-dir data/clips

# 연속 분석 리포트 재생성 (영상 → 포즈 → 교환 → JSON)
PYTHONPATH=. .venv/bin/python3 scripts/generate_continuous_report.py \
    data/raw/jr_saber_final_primus_kovalev_B6k6SoJFAr8.mp4 \
    --my-fencer left --sample-every 3 \
    --merge-ocr data/reports/B6k6SoJFAr8_report.json

# 프레이즈 경계 데이터셋 생성
PYTHONPATH=. .venv/bin/python3 scripts/generate_phrase_dataset.py data/reports/
```

### 갤러리 데모 리포트 (6개)
| ID | 영상 | 종목 | 점수 | 터치 | 교환 |
|----|------|------|------|------|------|
| usaf_hKUXgUsDOKE | Jr Foil Final (USA Fencing) | foil | 15-7 | 22 | 224 |
| usaf_Jiq1kQLftjw | Sabre DE Thriller | sabre | 15-14 | 29 | 88 |
| gdOdpDyaWrw | Women's Y14 Foil | foil | 15-13 | 28 | — |
| VzlH8O7EsCM | Sabre Comeback | sabre | 14-15 | 27 | — |
| usaf_UzQ8Ci7lft8 | Div 1 Epee Final | epee | 13-15 | 22 | 334 |
| usaf_B6k6SoJFAr8 | Jr Sabre Final (PRIMUS vs KOVALEV) | sabre | 10-15 | 22 | 63 |

### 알려진 호환성 이슈
- **Python 3.14.4** + **Jinja2 3.1.x**: LRU 캐시 해싱 버그 → `cache_size=0`으로 해결됨
- **Starlette 1.0.1**: TemplateResponse 시그니처 변경 → `(request, name, context)` 형식으로 수정됨
- **Tesseract OCR 병목**: ~85ms/프레임, 8분 영상에 ~23분 소요 → EasyOCR 전환 또는 sample_interval 조정 검토 필요

### OCR 분석 실측 결과 (2026-05-27)
```
영상: USA Fencing 샘플 (0HeqT9us5wA, 8:49, 1280×720, 30fps)
선수: KHOTLINE Daniel vs GERSTMANN Max
결과: 19 터치 감지, 최종 10-14 (실제 10-15)
정확도: 이름 100%, 점수 읽기율 76%
인사이트: GERSTMANN 4연속 터치 (momentum), 점수 흐름 분석
소요: 1,363초 (15,892프레임, sample_interval=5)
meta: source_type=tv_broadcast, analysis_mode=ocr_only
```

### 포즈 분석 실측 결과 (2026-05-29)
```
대상: 3개 USA Fencing TV 영상 × 10클립 = 30클립
  - usaf_0HeqT9us5wA: 10클립 (epee)
  - usaf_0qllx-vYhGE: 11클립
  - usaf_6MCRWT7GmaU: 9클립

수정 사항:
  1. 카메라컷 필터링 (filter_camera_cuts, find_touch_moment)
  2. 상대 빠라드 변위 (wristΔ - hipΔ, 프레임갭>3 스킵)

결과 라벨 분포:
  attack: 17/30 (57%) — attack_left:7, attack_right:10
  riposte: 12/30 (40%) — riposte_left:7, riposte_right:5
  counter_attack: 1/30 (3%) — counter_attack_right:1
  → Gemini Vision의 100% attack 대비 대폭 개선

거리 (터치 시점): infighting:11, extension:5, lunge:3, adv_lunge:3, OOD:8
풋워크 (60건): fleche:20, unknown:13, stationary:12, retreat:9, advance:6, lunge:0
빠라드: ~40% 클립에서 최소 한쪽 감지, 변위 범위 20-57px (이전: 200-285px)

알려진 한계:
  - 런지 0건 (hip_drop 임계값 과다)
  - OOD 8건 (특정 영상에 집중)
  - fleche 과감지 (양발전진 임계값 20px 낮음)
```

### 풀 경기 연속 분석 E2E 실측 결과 (2026-05-29)
```
대상: 2개 USA Fencing 풀 경기 영상 (다운로드 원본)

영상 1: usaf_7Amgqc5HJR0.mp4 (3.8분, 8.5MB)
  샘플링: 매 3프레임 → 2,282 프레임 분석
  교환 감지: 16 exchanges
    - failed_attack: 11 (69%)
    - successful_defense: 5 (31%)
  Left fencer: 공격 9회 시도/0 성공, 방어 1회 시도/0 성공
  처리 시간: 51.8초 (0.23x realtime)

영상 2: usaf_3XTpDrDSvUs.mp4 (6.7분, 14.5MB)
  샘플링: 매 3프레임 → 4,036 프레임 분석
  교환 감지: 45 exchanges
    - failed_attack: 34 (76%)
    - successful_defense: 11 (24%)
  Left fencer: 공격 27회 시도/0 성공, 방어 8회 시도/2 성공 (25%)
  처리 시간: 73.2초 (0.18x realtime)

핵심 발견:
  1. 연속 분석 교환 감지 정상 동작 — 거리 기반 상태 기계 작동
  2. ~~공격 성공률 0% 문제~~ → Phase 7b Step 2에서 해결 (scoring_frames tolerance 매칭)
  3. 처리 속도 우수 — 0.18-0.23x realtime (5x 실시간보다 빠름)
  4. FencerProfile 생성 확인 — 실제 데이터에서 강점/약점/추천 자동 생성
```

### Phase 7b 프레이즈 다름 구현 후 검증 (2026-06-01)
```
대상: usaf_B6k6SoJFAr8 (PRIMUS vs KOVALEV, Jr Sabre Final, 9:35)

scoring_frames 연동 결과:
  OCR 터치: 22개 (scoring_frames)
  tolerance: SCORING_FRAME_TOLERANCE_SEC = 2.0
  my_fencer (left): 공격 성공률 64.3% (9/14), 방어 성공률 42.9% (3/7)

action_state_summary:
  Left: en_garde 52.1%, marche 12.3%, preparation 10.8%, retraite 9.4%, ...
  Right: en_garde 34.5%, marche 15.2%, preparation 13.1%, ...

clock_events: 0 (이 영상에서는 시계 OCR 불가 — 레이아웃 미매칭)

generate_continuous_report.py 버그 수정:
  video_stem → video_path.stem (line 141, UnboundLocalError 수정)
```

---

## 🔬 영상 분석 기술 종합 보고서 (A-to-Z Technical Deep Dive, 2026-06-07)

### 0. 전체 파이프라인 아키텍처

```
┌─────────────────────────────────────────────────────────────────────────┐
│ INPUT: 펜싱 경기 영상 (코치/학부모/선수 촬영 or TV 중계)                    │
└───────┬─────────────────────────────────────────────────────────────────┘
        │
        ▼
┌───────────────────────── [A] 영상 유형 감지 ─────────────────────────────┐
│  VideoSourceDetector — 휴리스틱 (장면전환 빈도, 선수 크기, 안정성, 점수판)   │
│  → COACH / PARENT / PLAYER / TV_BROADCAST                               │
└───────┬──────────────────────────────────────────────────────────────────┘
        │
   ┌────┴────────────────┬─────────────────────┐
   ▼                     ▼                      ▼
[B] 물리 LED 경로    [C] TV OCR 경로       [D] 포즈 전용 경로
(코치/학부모)        (TV 중계)             (선수 촬영)
   │                     │                      │
   ▼                     ▼                      │
[E] LED 감지         [F] TV 오버레이 OCR        │
[G] 7-Segment OCR    [H] TVScoreTracker         │
   │                     │                      │
   ▼                     ▼                      │
[I] 이벤트 감지 (MatchEvent / TVTouchEvent)     │
   │                     │                      │
   └──────┬──────────────┘                      │
          ▼                                     ▼
[J] YOLO11-Pose 포즈 추정 ◄────────────────────┘
          │
          ▼
[K] 연속 분석 (PoseAnalyzer.analyze_continuous)
├─ [L] 거리 계산 (Body Height 정규화)
├─ [M] 풋워크 감지 (런지/플레쉬/전진/후퇴)
├─ [N] 빠라드 감지 (손목 상대 변위)
├─ [O] 교환 감지 (거리 기반 상태 기계)
├─ [P] 관절 키네마틱 (8관절 속도/가속도)
├─ [Q] 프레임별 동작 분류 (ActionState 9종)
├─ [R] 시계 OCR → Allez/Halt 이벤트
└─ [S] scoring_frames 연동 (OCR 지연 보정)
          │
          ▼
[T] FencerProfile 집계 (DistanceStats, FootworkStats, JointAngleStats)
          │
          ▼
[U] 리포트 생성 (MatchReport + 코칭 인사이트)
          │
          ▼
[V] 클립 오버레이 (YOLO 스켈레톤 + HUD)
          │
          ▼
[W] 2-패널 HTML 리포트 (Jinja2 + Chart.js + 인라인 클립 재생)
          │
          ▼
[X] VideoMAE 행동 분류 (FACTS 파인튜닝 대기)
```

---

### [A] 영상 유형 감지 (Video Source Detection)

**기술 정의**: 입력 영상의 촬영 환경을 자동 분류하여 최적 분석 파이프라인을 선택하는 전처리 단계

**학술 참조**:
- 장면 전환 감지: Histogram difference + threshold (Boreczky & Rowe, 1996)
- 카메라 안정성: Optical flow magnitude variance (Lucas-Kanade)

**우리 구현** (`ml/video_source_detector.py`):
- `scene_cuts_per_minute`: 인접 프레임 히스토그램 차이 > 임계값
- `avg_fencer_height_ratio`: YOLO11-Pose bbox 높이 / 프레임 높이
- `stability_score`: 프레임간 optical flow의 분산 (0=흔들림, 1=삼각대)
- `scoreboard_detected`: 물리 LED 점수판 유무
- `overlay_detected`: TV 오버레이 바 유무

**분류 규칙 (캐스케이드)**:
```
scene_cuts > 3/30s + overlay → TV_BROADCAST
stability > 0.8 + scoreboard + 2인 → COACH
scoreboard + stability < 0.8 → PARENT
person_count ≤ 1 → PLAYER
나머지 → UNKNOWN
```

**개선 필요**:
- 현재 휴리스틱 기반 → 영상 유형 라벨 데이터 축적 후 경량 분류기(SVM/RF)로 대체 가능
- UNKNOWN 비율 추적 필요 (현재 메트릭 없음)
- 다양한 방송국 레이아웃(FIE, KFF 등) 지원 필요

---

### [B~D] 분석 경로 분기 (Routing)

| 영상 유형 | 경로 | Phase 1 | 포즈 | 연속분석 | 비고 |
|-----------|------|---------|------|---------|------|
| COACH | 물리 LED | ✅ LED+OCR | ✅ 이벤트 윈도우 | ⚠️ 선택 | 최적 소스 |
| PARENT | 물리 LED | ⚠️ 부분 | ✅ 이벤트 윈도우 | ⚠️ 선택 | 군중 노이즈 |
| TV_BROADCAST | TV OCR | ✅ Tesseract | ✅ 연속 | ✅ | 프로덕션 메인 |
| PLAYER | 없음 | ❌ 스킵 | ✅ 포즈만 | ✅ | 기술 중심 |

---

### [E] LED 감지 (Lamp Detection)

**기술 정의**: 펜싱 전자 채점기의 빨간/초록 LED 점등을 프레임 단위로 감지

**학술 참조**:
- HSV 색공간 분리: Hue-Saturation-Value가 조명 변화에 강인 (Gonzalez & Woods, Digital Image Processing)
- 임계값 기반 이진화: Otsu's method의 변형 (고정 threshold 200)

**우리 구현** (`analyzer/lamp_detector.py`):
- **Method 1 (밝기 기반)**: BGR→Gray, threshold=200으로 밝은 픽셀 카운트
- **Method 2 (색상 기반)**: BGR→HSV, 빨강(0-15, 160-180 hue) / 초록(35-85 hue) 범위 마스킹
- **합산**: 밝기 픽셀 + 색상 픽셀 > `LAMP_PIXEL_THRESHOLD(300)` → ON

**특이 설계**:
- 빨간 HSV 범위를 2구간으로 분리 (hue wrap-around: 0~15, 160~180)
- 높은 밝기 + 낮은 채도 마스크 별도 추가 (LED 과포화 시 흰색으로 보이는 현상 대응)

**개선 필요**:
- 환경광 적응: 현재 고정 임계값 → 첫 N프레임에서 자동 calibration
- ROI 자동 검출: 현재 수동 ROI 지정 or ScoreboardDetector (Phase 4b)

---

### [F~G] 점수 판독 (Score Reading)

#### [F] TV 오버레이 OCR (`analyzer/tv_overlay_ocr.py`)

**기술 정의**: TV 중계 영상의 점수판 오버레이에서 선수명, 점수, 시간, 카드 정보를 추출

**학술 참조**:
- OCR 엔진: Tesseract 4+ (LSTM 기반, Smith 2007: "An Overview of the Tesseract OCR Engine")
- 전처리: 색상 마스킹 + 모폴로지 연산 (erosion/dilation for noise removal)

**우리 구현**:
1. **레이아웃 프리셋**: `OVERLAY_LAYOUTS["usa_fencing"]` — 1280x720 기준 각 영역 x좌표 (이름, 점수, 시간)
2. **전처리 파이프라인**: ROI 추출 → 3배 업스케일 → HSV 색상 마스킹(흰색/빨강/초록/파랑) → 모폴로지 → Tesseract
3. **디바운싱**: `OVERLAY_SCORE_DEBOUNCE=15` 프레임(~0.5초) 동안 같은 점수 유지해야 확정
4. **에러 필터링**: 점수 감소 무시, 한 번에 3점 이상 변화 무시

**성능**: ~85ms/프레임 (Tesseract 병목), 점수 읽기율 76%, 이름 정확도 100%

**개선 필요 (높은 우선순위)**:
- **Tesseract → EasyOCR/PaddleOCR 전환**: Tesseract가 최대 병목 (8분 영상에 23분 소요)
- **레이아웃 자동 감지**: 현재 USA Fencing 전용 → 다른 방송국(FIE, KFF) 레이아웃 자동 감지
- **sample_interval 최적화**: 현재 5프레임마다 OCR → 10~15로 올리면 정확도 trade-off
- **GPU OCR**: Tesseract CPU-only → GPU 가속 OCR 엔진

#### [G] 7-Segment OCR (`analyzer/score_reader.py`)

**기술 정의**: 물리 전자 채점기의 7-세그먼트 LED 숫자를 패턴 매칭으로 판독

**학술 참조**:
- 7-Segment Display Recognition: 템플릿 매칭 (Brunelli, "Template Matching Techniques in Computer Vision")
- 세그먼트 패턴 룩업: (a,b,c,d,e,f,g) 7개 세그먼트 ON/OFF → 숫자 매핑

**우리 구현**:
1. **ROI에서 빨간 LED 마스킹**: HSV (0-15, 165-180 hue, sat>80, val>80)
2. **컨투어 → 자릿수 분리**: cv2.findContours → 바운딩 박스 정렬
3. **이중 인식 전략**:
   - 방법 A: 7-세그먼트 영역별 활성화 비율 → `SEVEN_SEGMENT_PATTERNS` 룩업
   - 방법 B: 저장된 템플릿과 NCC(Normalized Cross-Correlation) 매칭
4. **학습**: 새 샘플이 높은 confidence로 인식되면 `digit_templates.pkl`에 자동 추가
5. **자릿수 "1" 특별 처리**: aspect ratio < 0.65이면 "1"로 직접 판정

**정확도**: ~95% (클린 LED 디스플레이), 30프레임 디바운싱으로 오류 완화

**개선 필요**:
- 2자리 숫자(10-15) 분리 정확도 개선 필요 (간혹 "1"과 "5"가 붙어보임)
- 시계(M:SS) 읽기에서 콜론(:) 오인식 문제

---

### [H] TVScoreTracker — 상태 추적 + 시계 OCR

**기술 정의**: 프레임별 OCR 결과를 상태 기계로 추적하여 노이즈를 제거하고 이벤트를 생성

**학술 참조**:
- Finite State Machine (FSM) for event detection (Hopcroft, Motwani, Ullman)
- Debouncing: 시그널 처리의 디지털 필터 개념 적용

**우리 구현** (`analyzer/tv_overlay_ocr.py: TVScoreTracker`):
1. **점수 상태 기계**: `confirmed_score` → `pending_score`(변화 감지) → N프레임 유지 → `confirmed_score` 전환
2. **시계 상태 기계**: `unknown` → `running`(시간 감소 3프레임 연속) → `stopped`(시간 유지 5프레임 연속)
3. **이벤트 생성**: 점수 확정 시 `TVTouchEvent`, 시계 전환 시 `clock_event` (allez/halt 프록시)

**개선 필요**:
- 시계 해상도가 1초 → 짧은 halt(2초 미만) 감지 불안정
- period 전환 감지 로직 미구현 (1기→2기→3기)

---

### [I] 이벤트 감지 + 디바운싱

**기술 정의**: 점수 변화를 확인하고 실제 터치 이벤트로 확정하는 시간적 필터링

**핵심 파라미터**:
| 파라미터 | 값 | 의미 |
|---------|---|------|
| `DEBOUNCE_FRAMES` | 30 (~1초) | 물리 LED 연속 이벤트 최소 간격 |
| `OVERLAY_SCORE_DEBOUNCE` | 15 (~0.5초) | TV OCR 점수 확인 프레임 수 |
| `SCORE_WAIT_SECONDS` | 15 | LED 점등 후 점수 변화 대기 시간 |
| `SCORING_FRAME_TOLERANCE_SEC` | 2.0 | OCR 점수 지연과 실제 터치 매칭 허용 범위 |

---

### [J] YOLO11-Pose 포즈 추정 (Pose Estimation)

**기술 정의**: 단일 프레임에서 인체 17개 관절(COCO format) 좌표를 실시간 추정

**학술 참조**:
- YOLOv8-Pose / YOLO11-Pose: Ultralytics (2024), "Real-Time Pose Estimation"
- COCO Keypoint format: 17 joints (Lin et al., "Microsoft COCO: Common Objects in Context", ECCV 2014)
- Top-down vs Bottom-up: Top-down 방식 (person detect → keypoint) 사용

**COCO 17 관절**:
```
0: Nose, 1-2: Eyes, 3-4: Ears
5-6: Shoulders, 7-8: Elbows, 9-10: Wrists
11-12: Hips, 13-14: Knees, 15-16: Ankles
```

**우리 구현** (`ml/pose_estimator.py`):
- **모델**: `yolo11n-pose.pt` (nano variant, ~26MB)
- **입력**: BGR 720p 프레임
- **출력**: `PoseResult` (최대 2명의 `FencerPose`, 각 17 `PoseKeypoint`(x,y,confidence))
- **좌우 할당**: bbox x-center 비교 → 왼쪽/오른쪽 자동 배정
- **GPU**: MPS(Metal Performance Shaders) 우선 → CUDA → CPU 폴백
- **임계값**: person confidence ≥ 0.5, keypoint confidence ≥ 0.3
- **Lazy loading**: 첫 호출 시 모델 로드

**성능**: 150ms/프레임 (720p, MPS GPU)

**개선 필요**:
- **1인 감지 시 사이드 추정**: 현재 무조건 "left" → 프레임 중앙 기준 또는 이전 프레임 tracking 필요
- **Tracking 미구현**: 프레임간 ID 유지 안됨 → ByteTrack/BoT-SORT 통합 필요
  - 현재: 매 프레임 독립적으로 좌/우 할당 → 교차 시 swap 발생
  - 해결: Object tracking으로 일관된 ID 유지
- **모델 업그레이드**: nano → small/medium으로 정확도 향상 가능 (지연시간 trade-off)
- **Occlusion 처리**: 두 선수가 겹칠 때 keypoint 혼동 → 이전 프레임 정보로 보정 필요

---

### [K] 연속 분석 (Continuous Analysis)

**기술 정의**: 전체 경기 영상을 서브샘플링하여 프레임별 포즈를 분석하고, 교환/비득점/동작 상태를 추출

**우리 구현** (`ml/pose_analyzer.py: analyze_continuous()`):
```python
def analyze_continuous(
    pose_sequence,           # YOLO11-Pose 결과 시퀀스
    scoring_frames=None,     # OCR에서 감지된 득점 프레임 (지연 보정용)
    fps=30.0,
    my_fencer="left",
    sample_every_n=5,
):
```

**서브샘플링**: 매 `sample_every_n`(기본 5) 프레임마다 YOLO 실행 → 처리량 5배 향상

**성능**:
| 영상 길이 | 샘플 프레임 | 처리 시간 | 배율 |
|----------|-----------|----------|------|
| 3.8분 | 2,282 | 51.8초 | 0.23x realtime |
| 6.7분 | 4,036 | 73.2초 | 0.18x realtime |
| 9.5분 | ~5,700 | ~120초 | ~0.21x realtime |

---

### [L] 거리 계산 (Distance in Body Height Units)

**기술 정의**: 두 펜서 간 거리를 체고(Body Height) 단위로 정규화하여 카메라 거리/줌에 독립적인 측정

**학술 참조**:
- Body Height normalization: 스포츠 생체역학에서 표준 방법 (Winter, "Biomechanics and Motor Control of Human Movement")
- 카메라 독립 거리 측정: 단안 카메라에서 절대 거리 추정의 일반적 접근법

**우리 구현**:
1. **체고 계산**: `compute_body_height()` — shoulder_center ~ ankle_center 픽셀 거리
2. **거리 계산**: `compute_distance_bh()` — hip_center 간 X축 거리 / 평균 체고
3. **이동 평균**: `smooth_distances()` — 5프레임 윈도우로 노이즈 제거
4. **5단계 거리 구간**:

| 구간 | BH 범위 | 펜싱 의미 |
|------|---------|----------|
| OUT_OF_DISTANCE | > 1.8 BH | 거리 밖 (안전) |
| ADVANCE_LUNGE | 1.5-1.8 BH | 전진+런지 필요 |
| LUNGE | 1.2-1.5 BH | 런지 가능 거리 |
| EXTENSION | 0.8-1.2 BH | 팔만 뻗으면 닿는 거리 |
| INFIGHTING | < 0.8 BH | 인파이팅 (매우 가까움) |

**개선 필요**:
- **X축만 사용**: 사이드뷰 가정 → 비스듬한 카메라 각도에서 오차 증가 → Y축 가중 병합 필요
- **체고 캘리브레이션**: 한 선수가 숙이면 체고 변동 → en garde 시 체고를 기준으로 고정
- **임계값 보정**: 현재 고정 BH 비율 → 종목별(사브르는 더 가까움) 동적 조정

---

### [M] 풋워크 감지 (Footwork Detection)

**기술 정의**: 관절 궤적 분석으로 펜서의 풋워크 유형을 분류

**학술 참조**:
- 펜싱 풋워크 분류: Gholipour et al., "Biomechanical Analysis of Fencing Lunge" (Sports Biomechanics, 2008)
- 엉덩이 하강(hip drop): 런지의 핵심 생체역학 지표

**우리 구현** (`pose_analyzer.py: detect_footwork()`):

| 풋워크 | 감지 조건 | 관련 상수 |
|--------|----------|----------|
| **LUNGE** | 앞발 전진 + 뒷발 정지 + 엉덩이 하강 | `HIP_DROP_RATIO_MIN=0.005 BH` |
| **FLECHE** | 양발 모두 전진 (>50px) + 비율 < 2.5 | `FLECHE_BOTH_ADVANCE_MIN_TUNED=50px` |
| **ADVANCE** | 양발 전진, 엉덩이 하강 없음 | `MIN_DISPLACEMENT_PX=15` |
| **RETREAT** | 양발 후퇴 | 방향 반전으로 감지 |
| **STATIONARY** | 변위 < 15px | `FOOTWORK_MIN_DISPLACEMENT_PX=15` |

**분석 윈도우**: 터치 시점 이전 15프레임 (`FOOTWORK_ANALYSIS_WINDOW`)

**실측 결과 (30클립)**:
```
fleche: 20(33%), unknown: 13(22%), stationary: 12(20%),
retreat: 9(15%), advance: 6(10%), lunge: 0(0%)
```

**개선 필요 (중간 우선순위)**:
- **런지 0건 문제**: `HIP_DROP_RATIO_MIN=0.005 BH`가 TV 클립에서도 감지 실패 → hip_drop이 실제로 음수인 케이스 다수 (TV 카메라 각도 때문)
  - 해결 방향: 앞무릎 각도(front_knee < 130°) 보조 조건 추가
- **fleche 과감지**: 양발 전진 조건이 너무 관대 → 빠른 전진+런지를 fleche로 오분류
  - 해결 방향: 양발 교차 여부(ankle 좌표 swap) 확인 추가
- **비율 기반 hip drop**: `FOOTWORK_USE_RATIO_BASED_HIP_DROP=True` → 절대 px가 아닌 BH 비율 사용 중이지만 여전히 미흡

---

### [N] 빠라드 감지 (Parry Detection)

**기술 정의**: 비득점자의 무기팔 손목 급변위를 감지하여 방어 동작을 추론

**학술 참조**:
- 빠라드(Parry): 상대의 공격 블레이드를 옆으로 치는 방어 동작 (Czajkowski, "Understanding Fencing")
- 상대 변위(relative displacement): 전신 이동과 국소 변위를 분리하는 기법

**우리 구현** (`pose_analyzer.py: detect_parry()`):
1. **절대 → 상대 변위 전환** (결정 18):
   - 초기: `|wrist_y[t] - wrist_y[t-1]|` → 전신 접근 시 200+px 오탐
   - 현재: `(wrist_delta) - (hip_delta)` → 순수 손목 동작만 감지 (20-57px 범위)
2. **카메라컷 보정**: 프레임 갭 > 3인 쌍은 스킵
3. **감지 윈도우**: 터치 전 10프레임 (`PARRY_DETECTION_WINDOW`)
4. **임계값**: 횡변위 > 20px (`PARRY_WRIST_LATERAL_MIN_PX`) + 속도 > 8px/frame (`PARRY_WRIST_SPEED_MIN_PX`)

**한계 & 개선 필요**:
- **Y축 변위만 사용**: 사이드뷰 가정 → 정면 카메라에서는 X축도 필요
- **블레이드 접촉 미확인**: 손목 변위 ≠ 실제 빠라드 (페이크 빠라드 구분 불가)
- **종목별 빠라드 차이**: 사브르(머리 위 빠라드 5번) vs 플뢰레(가슴 빠라드 4번) → 종목별 임계값 필요

---

### [O] 교환 감지 (Exchange Detection)

**기술 정의**: 두 펜서의 거리 변화를 상태 기계로 추적하여 공방 교환의 시작/종료를 감지

**학술 참조**:
- State Machine for temporal event segmentation (FSM 기반 활동 인식)
- "Phrase d'armes" (검술 구절): FIE 규칙서의 경기 단위 개념

**우리 구현** (`pose_analyzer.py: _detect_exchanges()`):

```
상태 기계: IDLE → APPROACH → SEPARATION → IDLE
                                    ↓ (10프레임 내 재접근)
                                 APPROACH (병합)
```

- **IDLE → APPROACH**: 거리 감소가 3프레임 연속 (`EXCHANGE_MIN_APPROACH_FRAMES`)
- **APPROACH → SEPARATION**: 거리 증가 시작 (최소 거리 도달 후)
- **SEPARATION 병합**: 10프레임 내 재접근 시 같은 교환으로 병합 (`EXCHANGE_MERGE_SEPARATION_FRAMES`)
- **교환 분류**: `_classify_exchange()`
  - 득점 연동 (`scoring_frames` tolerance ±2초)
  - `failed_attack` / `successful_defense` / `mutual_retreat` / `off_target`

**개선 필요**:
- **느린 접근 미감지**: 매우 천천히 접근하는 경우 (에페 특유) 교환으로 미인식
- **다중 교환 세분화**: 하나의 긴 교환 내에서 여러 액션(공격-빠라드-리포스트)을 세분화
- **득점 교환과 비득점 교환 비율 모니터링**: 현재는 감지만 하고 전술적 해석은 미구현

---

### [P] 관절 키네마틱 (Joint Kinematics)

**기술 정의**: 8개 관절의 프레임간 속도(px/frame, BH/frame)와 가속도(px/frame²)를 계산

**학술 참조**:
- 스포츠 생체역학 키네마틱: Winter, "Biomechanics and Motor Control of Human Movement", 4th ed.
- 관절 속도/가속도: 1차/2차 유한 차분 (finite difference) 방법

**우리 구현** (`pose_analyzer.py: compute_joint_kinematics()`):
- **추적 관절**: 양쪽 wrist, ankle, hip, shoulder (8개)
- **velocity_px**: `|pos[t] - pos[t-1]|` (프레임당 픽셀)
- **velocity_bh**: velocity_px / body_height (체고 정규화)
- **acceleration_px**: `|vel[t] - vel[t-1]|` (프레임당 픽셀 변화)
- **카메라컷 필터링**: hip 점프 > 100px → 해당 프레임 스킵

**개선 필요**:
- **노이즈 필터링**: Savitzky-Golay 필터 또는 Kalman 필터 적용 필요 (현재 raw 차분)
- **각속도 미구현**: 관절 각도의 시간 변화율 (angular velocity) → 런지/플레쉬 특성화에 중요
- **BH 정규화 일관성**: 프레임마다 BH가 변동 → 영상 시작 시 1회 calibration으로 고정

---

### [Q] 프레임별 동작 상태 분류 (Action State Classification)

**기술 정의**: 매 프레임의 키네마틱 + 풋워크 + 빠라드 정보를 조합하여 9가지 동작 상태 중 하나를 할당

**학술 참조**:
- Rule-based action recognition: 규칙 기반 접근법 (Bobick & Davis, "The Recognition of Human Movement Using Temporal Templates", PAMI 2001)
- 펜싱 동작 분류 체계: FIE 규칙서 t.7-t.17 "Method of Making a Hit"

**9가지 ActionState**:
| 상태 | 의미 | 분류 조건 |
|------|------|----------|
| EN_GARDE | 기본 자세 | velocity_max < threshold, 적정 거리 |
| MARCHE | 전진 | 양발 전진, hip drop 없음 |
| RETRAITE | 후퇴 | 양발 후퇴 |
| FENTE | 런지 | 앞발 전진 + hip drop |
| FLECHE | 플레쉬 | 양발 고속 전진, 교차 |
| PARADE | 빠라드 | 비득점자 손목 급변위 |
| RIPOSTE | 리포스트 | 빠라드 직후 전진 |
| PREPARATION | 준비 동작 | 중간 속도, 거리 조절 |
| RECOVERY | 복귀 | 공격 후 기본 자세 복귀 |

**실측 결과 (PRIMUS vs KOVALEV)**:
```
Left: en_garde 52.1%, marche 12.3%, preparation 10.8%, retraite 9.4%
Right: en_garde 34.5%, marche 15.2%, preparation 13.1%
```

**개선 필요 (높은 우선순위)**:
- **ML 대체 필요**: 규칙 기반은 임계값 민감 → LSTM/Transformer 시퀀스 분류기로 업그레이드
- **종목별 상태 세분화**: 사브르의 balestra, flunge / 플뢰레의 disengage / 에페의 remise 등
- **Ground truth 부재**: 현재 검증 데이터 없음 → 라벨링 세션으로 GT 구축 필요

---

### [R] 시계 OCR → Allez/Halt 이벤트

**기술 정의**: TV 점수판의 시계 변화를 추적하여 경기 진행(Allez)과 중단(Halt)을 간접 감지

**학술 참조**:
- Allez Go (2024): Meinecke et al., "Audio-based Allez/Halt detection in fencing" — 오디오 기반 89.1% 정확도
- 우리 접근: 시각적 시계 OCR (오디오 대신 점수판 시계 변화 추적)

**우리 구현** (`tv_overlay_ocr.py: TVScoreTracker._update_clock_state()`):
- `running`: 시간 값이 3프레임 연속 감소 → Allez (경기 진행)
- `stopped`: 시간 값이 5프레임 연속 동일 → Halt (경기 중단)
- 디바운싱으로 OCR 오류에 의한 spurious 전환 방지

**한계**: 시계 해상도 1초, 방송국별 시계 위치/형식 다름

**개선 필요**:
- **오디오 Allez/Halt 감지 추가**: Allez Go 논문 방식 (오디오 기반 89.1%) → 시각+오디오 융합
- **단일 프레이즈 시간 분석**: Allez~Halt 구간 = 1 프레이즈 → 평균 프레이즈 시간, 공방 밀도 분석 가능

---

### [S] scoring_frames 연동 (OCR 지연 보정)

**기술 정의**: OCR 점수 변화 시점과 실제 터치 시점 간의 시간차를 tolerance 기반으로 보정

**문제**:
```
실제 타임라인: 런지 → 터치(실제) → 심판 판정 → 점수판 업데이트 → OCR 감지
              ─────────────── 0.5 ~ 2.0초 지연 ──────────────────
```

**우리 구현** (`pose_analyzer.py: _build_my_fencer_summary()`):
- `SCORING_FRAME_TOLERANCE_SEC = 2.0`: 교환의 min_dist_frame 기준 ±2초 윈도우 내에 scoring_frame이 있으면 매칭
- 매칭 성공 → 해당 교환을 "득점 교환"으로 분류
- 매칭 실패 → "비득점 교환" (failed_attack 등)

**결과**: 공격 성공률 0% → 64.3% (PRIMUS vs KOVALEV 실측)

**개선 필요**:
- **2초 윈도우 동적 조정**: 대회마다 심판 반응 속도 다름 → 자동 calibration
- **양방향 매칭**: 현재 교환→scoring_frame 단방향 → scoring_frame→가장 가까운 교환 역방향 매칭 추가

---

### [T] FencerProfile 집계

**기술 정의**: 다수의 경기/교환 분석 결과를 집계하여 선수별 종합 프로필을 생성

**우리 구현** (`ml/fencer_profile.py: FencerProfileBuilder`):

| 집계 항목 | 데이터 소스 | 출력 |
|-----------|-----------|------|
| DistanceStats | 터치별 distance_zone | zone_distribution, zone_success_rate |
| FootworkStats | 터치별 footwork_type | type_distribution, type_success_rate |
| JointAngleStats | 터치별 joint_angles | avg_hip/knee/trunk/arm |
| ParryStats | 터치별 parry_detected | parry_rate, parry_to_riposte |
| Handedness | arm extension 비대칭 | right/left/None + confidence |
| 자동 인사이트 | 위 모든 데이터 | strengths[], weaknesses[], recommendations[] |

**손잡이 감지** (미커밋 신규 기능):
- 양팔 신전 비율(arm extension ratio) 비대칭 분석
- 무기팔이 더 펴져 있음 → 해당 손이 dominant hand
- 임계값: 5% 차이 미만 → 판별 불가, 15% 차이 → confidence 1.0

**개선 필요**:
- **경기 간 일관성 검증**: 동일 선수의 다른 경기에서 프로필 일관성 확인 필요
- **시계열 추세**: 대회 기간 동안의 컨디션 변화 추적 (피로도 등)
- **상대 전적 분석**: 특정 상대에 대한 성적/패턴 비교

---

### [U~V] 리포트 + 클립 오버레이

**리포트 구조** (`MatchReport`):
- MatchSummary (점수, 시간, 종목)
- TouchDetail[] (프레임, 득점자, 동작, 신뢰도)
- FencerStats × 2 (동작 분포, 성공률)
- CoachingInsight[] (자동 생성 코칭 포인트)
- exchanges[] (교환 타임라인)
- fencer_profiles (거리/풋워크/관절 통계)

**클립 오버레이** (`ml/clip_overlay.py: ClipOverlayGenerator`):
- YOLO `result.plot()` → 17-joint 스켈레톤 자동 그리기
- `cv2.putText()` → HUD 텍스트 (거리 BH, 풋워크, 빠라드)
- 비대칭 패딩: `pad_before` / `pad_after` 독립 설정
- 스마트 클립 경계: 교환 시작점 or Allez 시점 or 3초 전(폴백)

**개선 필요**:
- **스켈레톤 시각화**: 현재 YOLO 기본 → 펜싱 특화 시각화 (무기팔 강조, 거리선 표시)
- **슬로우모션 지원**: 핵심 구간(터치 직전) 0.5x 슬로모션 → 코치/선수 교육용

---

### [W] 2-패널 HTML 리포트

**기술 스택**: Jinja2 + Tailwind CSS + Chart.js + fetch/blob URL

**레이아웃**:
- 왼쪽(440px, sticky): 경기 전체 영상 + 인라인 클립 플레이어
- 오른쪽(flex-1, scroll): 분석 콘텐츠 (summary → charts → events → stats)
- 모바일: flex-col, 영상 상단 60vh sticky

---

### [X] VideoMAE 행동 분류 (FACTS 파인튜닝 대기)

**기술 정의**: 비디오 클립에서 블레이드 액션(공격/리포스트/카운터/르미즈)을 분류하는 딥러닝 모델

**학술 참조**:
- VideoMAE: Tong et al., "VideoMAE: Masked Autoencoders are Data-Efficient Learners for Self-Supervised Video Pre-Training" (NeurIPS 2022)
- FACTS: Martinent et al., "Fencing Action Classification with Temporal Segments" — 90% 정확도
- Kinetics-400: Kay et al., "The Kinetics Human Action Video Dataset" (CVPR 2017)

**우리 구현** (`ml/action_classifier.py`):
- **모델**: MCG-NJU/videomae-base-finetuned-kinetics (86M params, 329MB)
- **입력**: 16프레임 윈도우 (224×224 RGB)
- **현재 상태**: Kinetics-400 pretrained → 펜싱 동작 "unknown" 반환 (89번 "fencing_sport"만 매핑)
- **FACTS 파인튜닝 준비 완료**: `ml/training/` 파이프라인 (dataset, train, evaluate)

**FACTS 8클래스**:
| 코드 | 동작 | 방향 |
|------|------|------|
| AL/AR | Attack | Left/Right |
| RL/RR | Riposte | Left/Right |
| CAL/CAR | Counter-attack | Left/Right |
| ReL/ReR | Remise | Left/Right |

**현재 상태**: **파인튜닝 데이터 미확보** → VideoMAE가 사실상 비활성

**개선 필요 (최고 우선순위)**:
- **FACTS 데이터셋 확보**: 논문 저자 연락 or USA Fencing 스트림에서 자체 수집 (TVDataCollector 준비됨)
- **자체 데이터 생성**: labeling_server.py로 인간 검수 → labels_reviewed.csv → 파인튜닝
- **파인튜닝 실행**: `train_videomae.py --dataset-format facts --epochs 10` (Mac Studio MPS)

---

### 기술별 성숙도 + 개선 우선순위 매트릭스

| 기술 | 성숙도 | 정확도 | 개선 우선순위 | 예상 효과 |
|------|--------|--------|-------------|----------|
| LED 감지 | ★★★★☆ | ~95% | 낮음 | 환경광 적응 |
| 7-Segment OCR | ★★★★☆ | ~95% | 낮음 | 2자리 분리 개선 |
| TV 오버레이 OCR | ★★★☆☆ | 76% (점수) | **높음** | EasyOCR 전환 → 속도 5x+ |
| 영상 유형 감지 | ★★★☆☆ | 미측정 | 낮음 | ML 분류기 전환 |
| YOLO11-Pose | ★★★★☆ | 높음 | 중간 | Tracking 추가 |
| 거리 계산 (BH) | ★★★★☆ | 높음 | 낮음 | 체고 calibration |
| 풋워크 감지 | ★★☆☆☆ | 런지0% | **중간** | 무릎 각도 보조 조건 |
| 빠라드 감지 | ★★★☆☆ | ~40% | 중간 | 종목별 임계값 |
| 교환 감지 | ★★★★☆ | 높음 | 낮음 | 안정적 |
| 관절 키네마틱 | ★★★☆☆ | — | 중간 | Kalman 필터 |
| 동작 상태 분류 | ★★☆☆☆ | 미측정 | **높음** | ML 모델 전환 |
| 시계 OCR | ★★☆☆☆ | 미측정 | 중간 | 오디오 융합 |
| scoring_frames | ★★★★☆ | 64.3% | 중간 | 양방향 매칭 |
| FencerProfile | ★★★☆☆ | — | 중간 | 경기 간 일관성 검증 |
| VideoMAE | ★☆☆☆☆ | 0% (미파인튜닝) | **최고** | FACTS 파인튜닝 |
| 클립 오버레이 | ★★★★☆ | — | 낮음 | 슬로모션 |
| 리포트 UI | ★★★★☆ | — | 낮음 | 안정적 |

---

### 참조 논문/기술 전체 목록

| # | 논문/기술 | 우리 시스템에서의 활용 |
|---|----------|---------------------|
| 1 | **YOLO11-Pose** (Ultralytics, 2024) | 17-joint 포즈 추정 — `pose_estimator.py` |
| 2 | **VideoMAE** (Tong et al., NeurIPS 2022) | 비디오 액션 분류 기반 모델 — `action_classifier.py` |
| 3 | **FACTS** (Martinent et al.) | 8클래스 펜싱 액션 분류 데이터셋 → 파인튜닝 목표 |
| 4 | **Kinetics-400** (Kay et al., CVPR 2017) | VideoMAE pretrained 데이터셋 |
| 5 | **COCO Keypoint** (Lin et al., ECCV 2014) | 17-joint 인체 관절 표준 포맷 |
| 6 | **Tesseract OCR** (Smith, 2007) | TV 오버레이 텍스트 인식 — `tv_overlay_ocr.py` |
| 7 | **HSV Color Space** (Gonzalez & Woods) | LED 감지, 오버레이 색상 분리 |
| 8 | **7-Segment Pattern Matching** (Brunelli) | 물리 점수판 숫자 인식 — `score_reader.py` |
| 9 | **Body Height Normalization** (Winter) | 거리 정규화 — `pose_analyzer.py` |
| 10 | **Allez Go** (Meinecke et al., 2024) | 오디오 Allez/Halt 감지 참조 (향후 구현 예정) |
| 11 | **fencing-AI** (sholtodouglas, GitHub) | 초기 파이프라인 참조 (InceptionV3+LSTM → 우리는 VideoMAE로 대체) |
| 12 | **Biomechanics of Fencing Lunge** (Gholipour et al., 2008) | 풋워크 감지 임계값 설계 |
| 13 | **Finite State Machine** (Hopcroft et al.) | 교환 감지, 시계 상태, 점수 추적 |
| 14 | **yt-dlp** (yt-dlp project) | YouTube 영상 다운로드 |
| 15 | **Rhizomatiks × WFSF** | 블레이드 추적 불가 판단 근거 (24대 4K 카메라 필요) |

---

## 🗺️ Phase 8+ 로드맵 (2026-06-07 업데이트)

### 최고 우선순위 (사업적 임팩트 최대)

#### 8-1. VideoMAE FACTS 파인튜닝 (블레이드 액션 분류 활성화) 🔴 PRIORITY #1
- **상세 문서**: [`docs/PRIORITY_1_FACTS_FINETUNING.md`](docs/PRIORITY_1_FACTS_FINETUNING.md)
- **문제**: 현재 모든 동작이 "unknown" → 리포트 핵심 가치 미제공
- **작업**: FACTS 데이터 확보 → `train_videomae.py` 실행 → 모델 배포
- **자체 데이터 확보 대안**: TVDataCollector → labeling_server.py 검수 → labels_reviewed.csv
- **목표**: 8클래스 분류 정확도 85%+
- **의존**: FACTS 데이터셋 or 자체 4,000+ 라벨링 클립
- **코드 준비**: 100% 완료 (학습/평가/배포 전체 파이프라인), 데이터만 필요

#### 8-2. OCR 엔진 교체 (Tesseract → EasyOCR/PaddleOCR)
- **문제**: 8분 영상에 23분 소요 (Tesseract 병목)
- **목표**: 5x+ 속도 개선 (영상 길이 이하로 분석 시간 단축)
- **검토 대상**: EasyOCR(GPU 지원), PaddleOCR(정확도 높음), MMOCR

#### 8-3. Supabase DB 실적용
- **문제**: in-memory dict → 서버 재시작 시 모든 작업 소실
- **작업**: `007_analytics_tables.sql` 마이그레이션 적용 → server.py DB 연결
- **테이블**: analytics_videos, analytics_analysis_jobs, analytics_analysis_results 등 8개

### 높은 우선순위 (분석 품질 향상)

#### 8-4. Object Tracking 통합 (ByteTrack/BoT-SORT)
- **문제**: 매 프레임 독립적 좌/우 할당 → 교차 시 ID swap
- **작업**: YOLO11 내장 tracker 활성화 또는 ByteTrack 통합
- **효과**: 선수 일관성 ↑, 프로필 정확도 ↑

#### 8-5. 풋워크 감지 개선
- **런지 문제**: hip_drop 조건 외에 front_knee_angle < 130° 보조 조건 추가
- **fleche 과감지**: ankle 교차 여부 확인 추가
- **목표**: 런지 감지율 0% → 60%+

#### 8-6. 동작 상태 분류 ML 전환
- **문제**: 규칙 기반 ActionState 분류가 임계값 민감
- **작업**: 현재 규칙으로 pseudo-label 생성 → LSTM/Transformer 시퀀스 분류기 학습
- **입력**: (keypoints, kinematics) per frame → ActionState

#### 8-7. 종목별 분석기 (Weapon-specific Analyzer)
- **플뢰레**: 우선권 판정 (공격 시작점 분석)
- **에페**: 카운터어택 기회 감지, 거리 관리 분석
- **사브르**: 전진 가속도 분석, 마르쉬-아탁 패턴
- **구현 위치**: `ml/weapon_analyzers/{foil,epee,sabre}.py`

### 중간 우선순위 (사용자 경험 + 인프라)

#### 8-8. 오디오 Allez/Halt 감지
- **참조**: Allez Go 논문 (89.1% 정확도)
- **방법**: librosa로 오디오 특징 추출 → 이진 분류기 (allez/halt/noise)
- **효과**: 프레이즈 경계 정확도 대폭 향상 (시각+오디오 융합)

#### 8-9. 인증 + 결제 연동
- **인증**: members 테이블 + JWT/카카오 로그인
- **결제**: Stripe or 토스 → analytics_credits 실결제

#### 8-10. PDF 내보내기
- **도구**: weasyprint 또는 reportlab
- **용도**: 코치 → 학부모 공유, 인쇄 가능한 리포트

#### 8-11. 다중 방송국 레이아웃 자동 감지
- **현재**: USA Fencing 전용 → FIE, KFF(대한펜싱협회), 올림픽 방송 지원 필요
- **방법**: 오버레이 영역 히스토그램 분석 → 레이아웃 템플릿 매칭

### 장기 비전

#### 9-1. 실시간 분석 (클럽 대회)
- WebSocket 스트리밍 → 프레임 단위 분석 → 실시간 대시보드
- 지연시간 목표: < 500ms (포즈 추정 150ms + 분석 50ms + 렌더링)

#### 9-2. 선수 자동 식별 (Face/Body Recognition)
- 경기 영상에서 선수를 자동 식별하여 FencerProfile에 자동 연결
- OCR 이름 매칭 (TV) + 체형/키 매칭 (코치 촬영)

#### 9-3. 대회 전 상대 분석 브리핑
- 대진표 공개 → 상대 FencerProfile 자동 조회 → 전략 리포트 자동 생성
- 의존: 선수별 최소 5경기 데이터 축적

#### 9-4. 모바일 앱 (iOS/Android)
- React Native or Flutter → 현장 촬영 + 즉시 분석 요청
- 오프라인 모드: YOLO-Pose만 on-device 실행

---

## 미커밋 변경사항 요약 (2026-06-07 기준)

### 신규 기능 (미커밋)
1. **손잡이(Handedness) 감지** — `pose_analyzer.py` + `fencer_profile.py` + `report.html` + `generate_continuous_report.py`
2. **스마트 클립 경계** — `server.py: _compute_touch_clip_bounds()` + `clip_overlay.py` 비대칭 패딩
3. **갤러리 추가** — `gallery.py`: NAC Y12 LEE vs ESAKI 리포트
4. **버그 픽스** — `tv_overlay_ocr.py`: 빈 문자열 파싱
5. **테스트** — `test_pose_analyzer.py`(+116줄), `test_clip_overlay.py`(+125줄)
