# 🔴 PRIORITY #1: FACTS 파인튜닝 — 블레이드 액션 분류 활성화

**상태:** 미해결 (코드 100% 완료, 데이터 미확보)
**생성일:** 2026-06-08
**담당:** TBD
**연관:** `CLAUDE.md` → Phase 8+ 로드맵 → 8-1

---

## 왜 1순위인가?

현재 시스템의 **3계층 동작 분석** 중 가장 핵심인 Layer 1(블레이드 액션)이 완전히 비활성 상태:

| 계층 | 분석 대상 | 작동 여부 | 비고 |
|------|----------|----------|------|
| **Layer 1** | 블레이드 액션 (공격/리포스트/카운터/르미즈) | ❌ 100% "unknown" | **이 문서의 대상** |
| Layer 2 | 풋워크 (런지/플레쉬/전진/후퇴/정지) + 빠라드 | ✅ 작동 중 | 규칙 기반 (PoseAnalyzer) |
| Layer 3 | 프레임별 동작 상태 (앙가르드/마르쉬/팡트 등) | ✅ 작동 중 | 규칙 기반 (ActionState) |

**사업적 영향:**
- 리포트에서 "어떤 동작을 했는지" 표시 불가 → **핵심 분석 가치 미제공**
- Layer 2/3가 작동해도, 블레이드 액션 없이는 전술 분석이 불완전
- 유료 고객에게 제공할 수 있는 차별화된 인사이트의 근간

---

## 현재 상태 (코드 vs 데이터)

### ✅ 완료된 것 (코드 — 즉시 실행 가능)

| 구성요소 | 파일 | 상태 |
|----------|------|------|
| 학습 설정 | `ml/training/config.py` | ✅ FACTS 8클래스, 하이퍼파라미터 정의 |
| 데이터셋 로더 | `ml/training/dataset.py` | ✅ FencingActionDataset + FACTSDatasetAdapter |
| 학습 루프 | `ml/training/train_videomae.py` | ✅ gradient accumulation, cosine LR, best model save |
| 평가 스크립트 | `ml/training/evaluate.py` | ✅ confusion matrix, per-class precision/recall/F1 |
| 추론 모듈 | `ml/action_classifier.py` | ✅ 파인튜닝 모델 자동 로드 + FACTS 방향 매핑 |
| 데이터 수집기 | `pipeline/tv_data_collector.py` | ✅ YouTube TV → OCR → 클립 → 라벨 CSV 파이프라인 |
| 라벨링 도구 | `scripts/labeling_server.py` | ✅ 웹 UI에서 수동 검수 |
| 테스트 | `tests/test_training_pipeline.py` | ✅ 32개 테스트 통과 |
| 데이터 증강 | `FLIP_LABEL_MAP` | ✅ 수평 플립 시 left↔right 라벨 자동 스왑 |

### ❌ 미완료 (데이터 — 유일한 블로커)

| 필요 항목 | 설명 | 최소 요구량 |
|-----------|------|------------|
| **학습 데이터** | 8클래스 라벨링된 펜싱 동작 클립 | 4,000+ 클립 |

---

## FACTS 8클래스 정의

```
┌─────────────────────────────────────────────────────┐
│  FACTS 코드 │  의미              │  FencingAction    │
├─────────────┼────────────────────┼───────────────────┤
│  AL         │  Attack Left       │  ATTACK (left)    │
│  AR         │  Attack Right      │  ATTACK (right)   │
│  RL         │  Riposte Left      │  RIPOSTE (left)   │
│  RR         │  Riposte Right     │  RIPOSTE (right)  │
│  CAL        │  Counter-Atk Left  │  COUNTER_ATTACK   │
│  CAR        │  Counter-Atk Right │  COUNTER_ATTACK   │
│  ReL        │  Remise Left       │  REMISE (left)    │
│  ReR        │  Remise Right      │  REMISE (right)   │
└─────────────┴────────────────────┴───────────────────┘
```

- **방향 인코딩**: 8클래스로 훈련 (FACTS 논문 정확도 유지) → 추론 시 방향 분리하여 `ActionPrediction.direction`에 저장
- **수평 플립 증강**: `FLIP_LABEL_MAP` — left↔right 라벨 자동 스왑 (0↔1, 2↔3, 4↔5, 6↔7)
- **FACTS 논문 보고 정확도**: ~90%

---

## 데이터 확보 방법 (2가지)

### 방법 A: FACTS 원본 데이터셋 확보

**논문**: Martinent et al., "Fencing Action Classification with Temporal Segments"

- 논문 저자에게 이메일로 데이터셋 공유 요청
- 학술 연구 목적 + 상업적 사용 라이선스 확인 필요
- 데이터가 제공되면 즉시 파인튜닝 실행 가능

**디렉토리 구조** (예상):
```
data/facts/
├── AL/          # Attack Left
│   ├── clip_001.mp4
│   └── ...
├── AR/          # Attack Right
├── RL/          # Riposte Left
├── RR/          # Riposte Right
├── CAL/         # Counter-Attack Left
├── CAR/         # Counter-Attack Right
├── ReL/         # Remise Left
└── ReR/         # Remise Right
```

### 방법 B: 자체 데이터 수집 (TVDataCollector)

이미 구현된 파이프라인으로 USA Fencing YouTube 스트림에서 자동 수집:

```
YouTube 영상 → TVDataCollector → OCR 점수 추적 → 득점 시점 클립 자동 추출
         → heuristic labels (L/R/T) → labels.csv → labeling_server.py 검수
```

**실행 순서:**
```bash
cd /Users/gyejinpark/Documents/GitHub/FencingMind-analytics/services/analytics

# 1. YouTube 플레이리스트에서 대량 클립 수집
PYTHONPATH=. .venv/bin/python3 -c "
from pipeline.tv_data_collector import TVDataCollector
collector = TVDataCollector()
collector.process_playlist('PLAYLIST_URL')
"

# 2. 라벨링 서버에서 수동 검수
PYTHONPATH=. .venv/bin/python3 scripts/labeling_server.py
# → http://localhost:7600 에서 웹 UI로 라벨 검수

# 3. 검수 완료 후 labels_reviewed.csv 생성
```

**주의사항:**
- heuristic label은 정확하지 않으므로 반드시 수동 검수 필요
- 클래스 불균형 가능성 높음 (attack >> remise)
- 최소 클래스당 300+ 클립 확보 권장 (총 4,000+)

---

## 파인튜닝 실행 절차

### Step 1: 데이터 준비

**방법 A (FACTS 원본):**
```bash
cd /Users/gyejinpark/Documents/GitHub/FencingMind-analytics/services/analytics

# FACTS 디렉토리 구조 확인
ls data/facts/
# → AL/  AR/  RL/  RR/  CAL/  CAR/  ReL/  ReR/

# FACTSDatasetAdapter로 labels.csv 변환
PYTHONPATH=. .venv/bin/python3 -c "
from ml.training.dataset import FACTSDatasetAdapter
adapter = FACTSDatasetAdapter('data/facts/')
n = adapter.to_csv('data/facts/labels.csv')
print(f'{n} clips converted')
print(adapter.get_class_distribution())
"
```

**방법 B (자체 수집):**
```bash
# labels_reviewed.csv가 data/labeled/labels.csv에 위치하면 됨
# 형식: clip_path,action_label
# 예: clips/clip_001.mp4,attack_left
```

### Step 2: 파인튜닝 실행

```bash
cd /Users/gyejinpark/Documents/GitHub/FencingMind-analytics/services/analytics

# FACTS 원본 사용 시
PYTHONPATH=. .venv/bin/python3 -m ml.training.train_videomae \
    --dataset-format facts \
    --data-dir data/facts/ \
    --epochs 10 \
    --batch-size 4 \
    --grad-accum 2 \
    --lr 5e-5

# 자체 수집 CSV 사용 시
PYTHONPATH=. .venv/bin/python3 -m ml.training.train_videomae \
    --dataset-format csv \
    --data-dir data/labeled/ \
    --epochs 10 \
    --batch-size 4 \
    --grad-accum 2 \
    --lr 5e-5
```

**하이퍼파라미터 (FACTS 논문 기준):**

| 파라미터 | 값 | 설명 |
|----------|------|------|
| Base Model | MCG-NJU/videomae-base-finetuned-kinetics | 86M params, 329MB |
| Batch Size | 4 × 2 (grad accum) = 유효 8 | Mac Studio 메모리 내 |
| Learning Rate | 5e-5 | AdamW, weight_decay=0.05 |
| Epochs | 10 | FACTS 논문: 10 + early stopping |
| Warmup | 3 epochs | linear warmup → cosine decay |
| Label Smoothing | 0.1 | 과적합 방지 |
| Gradient Clipping | 1.0 | 학습 안정성 |
| Frames per Clip | 16 | uniform sampling or last-frame padding |
| Data Split | 70/15/15 | train/val/test (seed=42) |
| Augmentation | 50% 수평 플립 + 20% color jitter | FLIP_LABEL_MAP으로 방향 보존 |

**Mac Studio M1 Max 실행 환경:**
- GPU: MPS (Metal Performance Shaders)
- 메모리: ~1.3GB (64GB 중) → 충분
- 클라우드 GPU 불필요 — 로컬 학습 가능

### Step 3: 평가

```bash
PYTHONPATH=. .venv/bin/python3 -m ml.training.evaluate \
    --model-dir ml/models/videomae-fencing-v1/ \
    --data-dir data/facts/ \
    --dataset-format facts
```

**기대 출력:**
```
=== Evaluation Results ===
Overall Accuracy: 0.XXX
Per-class:
  attack_left:         P=0.XX  R=0.XX  F1=0.XX
  attack_right:        P=0.XX  R=0.XX  F1=0.XX
  riposte_left:        P=0.XX  R=0.XX  F1=0.XX
  riposte_right:       P=0.XX  R=0.XX  F1=0.XX
  counter_attack_left:  P=0.XX  R=0.XX  F1=0.XX
  counter_attack_right: P=0.XX  R=0.XX  F1=0.XX
  remise_left:         P=0.XX  R=0.XX  F1=0.XX
  remise_right:        P=0.XX  R=0.XX  F1=0.XX

Confusion Matrix:
  ...
```

**성공 기준:**
- 전체 정확도 85%+ (FACTS 논문 ~90%)
- 모든 클래스 F1 > 0.70
- 특히 attack과 riposte 혼동률 < 15%

### Step 4: 배포 (자동)

파인튜닝 완료 시 모델이 `ml/models/videomae-fencing-v1/`에 자동 저장됨.

**배포는 코드 변경 없이 자동:**
1. `train_videomae.py`가 best model을 `ml/models/videomae-fencing-v1/`에 저장
2. `ActionClassifier._load_model()` (action_classifier.py:67)이 해당 경로 확인
3. 파일 존재 시 → Kinetics-400 대신 파인튜닝 모델 자동 로드
4. `_map_finetuned_prediction()`이 8클래스 출력 → `FencingAction` + `direction`으로 변환

```python
# action_classifier.py:75-81 — 자동 전환 로직
if self.finetuned_path and self.finetuned_path.exists():
    self._model = VideoMAEForVideoClassification.from_pretrained(
        str(self.finetuned_path)
    )
    self._processor = VideoMAEImageProcessor.from_pretrained(
        str(self.finetuned_path)
    )
```

---

## 액션 아이템

### 즉시 실행 가능
- [ ] FACTS 논문 저자에게 데이터셋 요청 이메일 발송
- [ ] USA Fencing YouTube 플레이리스트 URL 수집
- [ ] TVDataCollector로 파일럿 수집 (1개 영상) 테스트

### 데이터 확보 후
- [ ] 클래스 분포 확인 (클래스당 300+ 목표)
- [ ] 파인튜닝 실행 (Mac Studio MPS, ~10 epochs)
- [ ] 평가 → 85%+ 정확도 확인
- [ ] 리포트에서 "unknown" → 실제 동작명 표시 확인

### 개선 사이클
- [ ] low-confidence 예측 → 수동 검수 큐 구축
- [ ] Active Learning: 불확실 예측 우선 라벨링
- [ ] 종목별 모델 분리 (foil/epee/sabre) 검토

---

## 관련 파일 인덱스

| 파일 | 역할 |
|------|------|
| `ml/training/config.py` | 8클래스 정의, 하이퍼파라미터, FLIP_LABEL_MAP |
| `ml/training/dataset.py` | FencingActionDataset, FACTSDatasetAdapter |
| `ml/training/train_videomae.py` | 메인 학습 루프 (311줄) |
| `ml/training/evaluate.py` | 평가 + confusion matrix (218줄) |
| `ml/action_classifier.py` | 추론 시 파인튜닝 모델 자동 로드 (302줄) |
| `analyzer/config.py` | ACTION_FINETUNED_PATH 설정 |
| `analyzer/models.py` | FencingAction enum (9+UNKNOWN) |
| `pipeline/tv_data_collector.py` | 자체 데이터 수집 파이프라인 |
| `scripts/labeling_server.py` | 웹 라벨링 검수 도구 |
| `tests/test_training_pipeline.py` | 파이프라인 테스트 (32개) |
| `tests/test_action_classifier.py` | 분류기 + FACTS 매핑 테스트 (20개) |

---

## 참고 자료

- **FACTS 논문**: Martinent et al., "Fencing Action Classification with Temporal Segments" — 90% 정확도
- **VideoMAE**: MCG-NJU/videomae-base-finetuned-kinetics (Kinetics-400 pretrained, 86M params)
- **CLAUDE.md**: Phase 8+ 로드맵 8-1 항목, 딥러닝 파인튜닝 파이프라인 섹션
