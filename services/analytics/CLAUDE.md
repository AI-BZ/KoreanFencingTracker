# analytics.fencingmind.ai - AI 경기 분석

**서브도메인:** analytics.fencingmind.ai
**포트:** 76
**상태:** Phase 1 구현 완료

---

## 서비스 개요
- 경기 영상 LED/점수 OCR 분석 (v3 분석기 기반)
- 유튜브 → 클립 자동 추출 파이프라인
- 자동 라벨링 및 데이터 증강
- (Phase 2) 포즈 에스티메이션 + 행동 인식

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
│   └── server.py                    # FastAPI 앱 (health, status)
├── analyzer/                        # v3 분석기 모듈 분리
│   ├── __init__.py
│   ├── models.py                    # 데이터클래스 (ScoreState, MatchEvent, LampState 등)
│   ├── config.py                    # 임계값, HSV 범위, 7-segment 패턴
│   ├── lamp_detector.py             # LED 램프 감지 (밝기 + 색상 기반)
│   ├── score_reader.py              # 7세그먼트 OCR (템플릿 매칭 + 세그먼트 분석)
│   └── video_processor.py           # 메인 영상 처리 루프 (GUI + headless)
├── pipeline/                        # fencing-AI에서 포팅한 데이터 수집/전처리
│   ├── __init__.py
│   ├── downloader.py                # 유튜브 영상 다운로드 (yt-dlp)
│   ├── clip_cutter.py               # 득점 시점 자동 클립 분할 (v3 LED 감지 활용)
│   ├── auto_labeler.py              # 자동 라벨링 (L/R/T 분류)
│   └── data_augmentor.py            # 수평 플립 + 라벨 반전 증강
├── ml/
│   ├── __init__.py
│   └── models/
│       └── digit_templates.pkl      # v3 숫자 템플릿 데이터
├── vendor/                          # 외부 참조 코드 (.gitignore)
│   └── fencing-AI/                  # sholtodouglas/fencing-AI 클론
├── data/                            # 영상/클립 작업 디렉토리 (.gitignore)
│   ├── raw/                         # 다운로드 원본
│   ├── clips/                       # 추출된 클립
│   └── labeled/                     # 라벨링 완료 (L/R/T 서브디렉토리)
├── tests/
│   └── test_analyzer.py             # 모듈 임포트 + 유닛 테스트
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
| `models.py` | 데이터클래스들 | ScoreState, StableScore, LampState, MatchEvent, EventType, MatchClock |
| `config.py` | `__init__` 상수들 | HSV 범위, 임계값, 7-segment 패턴맵 |
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

## DB 테이블 (Phase 3에서 생성 예정)

**이 서비스가 주인인 테이블:**
- `analytics_videos` - 업로드된 영상
- `analytics_analysis_jobs` - 분석 작업 큐
- `analytics_analysis_results` - 분석 결과 (JSON)
- `analytics_techniques` - 감지된 기술/동작
- `analytics_player_metrics` - 선수별 메트릭
- `analytics_bout_reports` - 경기 리포트
- `analytics_credits` - 크레딧 잔액

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

### Phase 1: 기반 구축 (현재 — 완료)
- [x] v3 분석기 모듈 분리 (analyzer/)
- [x] fencing-AI 파이프라인 포팅 (pipeline/)
- [x] 유튜브 → 클립 자동 추출 파이프라인
- [x] FastAPI 서버 스켈레톤
- [x] 기본 테스트

### Phase 2: AI 모델 통합
- [ ] YOLO11-Pose 추가 (관절 17개 추적)
- [ ] VideoMAE 파인튜닝 (FACTS 데이터셋 기반, 8가지 동작 분류)
- [ ] 포즈 + 행동인식 + 점수 연동 통합 JSON 출력
- [ ] 클라우드 GPU 학습 파이프라인 (Colab/Lambda)
- [ ] 오디오 터치 감지 검토 (Allez Go 논문: 89.1% 정확도)

### Phase 3: 서비스화
- [ ] 웹 UI (영상 업로드 + 분석 결과 대시보드)
- [ ] DB 테이블 생성 (analytics_*)
- [ ] 구독/크레딧 시스템
- [ ] 리포트 생성 (PDF/웹)
- [ ] 비디오 스트리밍/재생 UI

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

---

## 기술 스택

| 영역 | 현재 (Phase 1) | 예정 (Phase 2) |
|------|---------------|---------------|
| 영상 처리 | OpenCV 4.x | + FFmpeg |
| LED/점수 | 7-segment OCR + 템플릿 매칭 | 유지 |
| 다운로드 | yt-dlp | 유지 |
| 포즈 추정 | — | YOLO11-Pose (ultralytics) |
| 행동 인식 | — | VideoMAE (HuggingFace transformers) |
| 웹 프레임워크 | FastAPI | FastAPI + Jinja2 |
| GPU | — | CUDA / Apple Metal (MPS) |
