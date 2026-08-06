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

프로덕션 서버는 **launchd**가 관리한다 (`com.fencingmind.analytics`, KeepAlive=true).
터미널에서 `uvicorn ... &`로 직접 띄우지 말 것 — 그 프로세스는 띄운 셸/세션이
끝나면 SIGTERM으로 함께 죽어서 502가 난다 (2026-08-06 실제 발생).

```bash
# 1. 프로덕션 재시작 (코드 변경 반영)
launchctl kickstart -k gui/$(id -u)/com.fencingmind.analytics

# 2. 확인
curl -s -o /dev/null -w "%{http_code}\n" http://localhost:9076/gallery   # → 200
curl -s http://localhost:9076/gallery | grep "새로_추가한_리포트_ID"        # → 존재 확인
curl -s -o /dev/null -w "%{http_code}\n" https://analytics.fencingmind.ai/gallery  # → 200
```

**규칙:**
- 데모 영상 분석 완료 시: `gallery.py` 수정 + `data/reports/` JSON 추가 → **프로덕션 재시작**까지 한 번에 완료
- 프로덕션 포트: **9076** (개발: 76)
- 프로덕션 URL: `https://analytics.fencingmind.ai/gallery`
- 프로덕션은 개발과 같은 디렉토리(`services/analytics/`)에서 실행됨 — 코드 변경이 재시작만으로 반영됨
- launchd 정의: `~/Library/LaunchAgents/com.fencingmind.analytics.plist` → `~/opt/fencingmind/scripts/start-analytics.sh`
- 로그: `~/Library/Logs/FencingMind/analytics-server.{log,error.log}`
- 상태 확인: `launchctl list | grep fencingmind.analytics` (2번째 열이 마지막 종료 코드)
- ⚠️ **PATH 주의**: launchd는 `/usr/bin:/bin:/usr/sbin:/sbin`만 넘겨준다. 클립 생성이
  `ffmpeg`/`ffprobe`를 셸로 호출하므로 기동 스크립트에서 `/opt/homebrew/bin`을
  PATH에 넣어줘야 한다. 빠지면 서버는 정상인데 클립만
  `Clip generation failed: [Errno 2] No such file or directory: 'ffmpeg'`로 실패한다
  (2026-08-06 실제 발생). 기동 스크립트는 저장소 밖(`~/opt/...`)에 있으니 재설치 시 주의.

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

> 각 Phase의 **상세 완료 항목 체크리스트**, **세션별 실측 검증 기록**, **기술 결정 로그(결정 1~25)**, **분석 역량/컨설팅 서비스 설계**, **세션 재개 가이드**, **영상 분석 기술 종합 보고서(A-to-Z Technical Deep Dive)** 는 아카이브로 분리되었습니다 → **[docs/HISTORY.md](docs/HISTORY.md)**

### 완료된 Phase (요약)

| Phase | 내용 | 완료일 |
|-------|------|--------|
| 1 | 기반 구축 — v3 분석기 분리, fencing-AI 파이프라인 포팅, FastAPI 스켈레톤 | 완료 |
| 2 | AI 모델 통합 — YOLO11-Pose + VideoMAE + 2-pass 통합 분석 | 2026-05-21 |
| 2.5 | 리포트 데이터 모델 + VideoMAE 파인튜닝 스캐폴드 | 2026-05-21 |
| 3 | 영상 유형별 분석 + FACTS 정렬 (VideoSourceType, 품질 게이트, TV 분석) | 2026-05-21 |
| 4a | Web UI + 데모 모드 (Jinja2/Tailwind/Chart.js) | 2026-05-25 |
| 4b | Auto-ROI + Supabase DB 레이어 + 휴리스틱 라벨러 | 2026-05-26 |
| 4c | 투자자 데모 폴리싱 (선수 이름, DE 데모, 랜딩 페이지) | 2026-05-27 |
| 5a | TV 오버레이 OCR + 파인튜닝 데이터 수집 (TVDataCollector) | 2026-05-27 |
| 5a+ | TV OCR 대시보드 연동 + 3-tier 폴백 + 실제 영상 검증 | 2026-05-27 |
| 5b | 버그 수정 + 매치 타임 + 무기 자동 감지 + 경고 시스템 | 2026-05-28 |
| 5c | 포즈 기반 라벨링 시스템 (PoseAnalyzer, 키네마틱 규칙) | 2026-05-28 |
| 5c+ | 분석 역량 평가 + 컨설팅 서비스 설계 (FencerProfile) | 2026-05-29 |
| 6 | 고도화 + FencerProfileBuilder + 연속 분석 (analyze_continuous) | 2026-05-29 |
| 7a | 리포트 UI 개선 + 영상 구간 재생 (clip_overlay) | 2026-05-29 |
| 7b | 리포트 2-패널 + 클립 인라인 + 프레이즈 다름(Phrase d'armes) 경계 탐지 | 2026-06-01 |

- **누적 테스트**: 531개 전체 통과 (Phase 7b 기준). Phase별 증가 내역은 HISTORY.md 참조.
- **미착수 예정 항목(Phase 5d/8)**: 라벨링 세션 실행, Supabase 실적용, 인증/결제 연동, FACTS 실제 파인튜닝, PDF 내보내기. 우선순위별 상세는 아래 **Phase 8+ 로드맵** 참조.

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

