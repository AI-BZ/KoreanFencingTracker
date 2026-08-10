# PRD: 회원 유형별 인증 및 선수 데이터 매칭 시스템

**Version**: 1.2
**Date**: 2026-02-25
**Author**: FencingMind Development Team
**Status**: Draft
**Changelog**:
- v1.2 - 개인정보보호법 준수 전면 보강 (동의 분리, 미성년자 보호, 스크래핑 데이터 법적 근거, consent_logs, 데이터 접근 모델, 실무 체크리스트)
- v1.1 - 사업자등록증 3-Layer 자동 검증 파이프라인 추가, 감독 인증 → Club 서비스 자동 등록 로직 추가

---

## 1. Executive Summary

FencingMind은 대한펜싱협회 대회 데이터를 기반으로 11,786명의 선수 프로필을 보유하고 있다. 현재 시스템은 "사용자가 누구인지(WHO)"는 인증할 수 있지만, "무엇인지(WHAT)" — 선수, 코치, 학부모 — 를 검증하거나, 기존 대회 데이터와 연결하는 메커니즘이 없다.

본 PRD는 **회원 유형별 인증 시스템**과 **선수-데이터 매칭 시스템**을 정의한다.

### 핵심 목표
1. 선수가 "이 대회 데이터가 나의 것"임을 증명하고 자신의 성적/전적을 조회
2. 학부모가 자녀 선수와 연결되어 자녀의 데이터를 조회
3. 코치/감독이 소속 클럽을 인증하고 팀 관리 권한을 획득
4. 선수가 잘못된 데이터를 신고하고 정정을 요청
5. 일반회원이 점진적으로 상위 인증 단계로 업그레이드

### 한국 시장 기회
현재 한국에는 선수가 본인 대회 데이터를 claim하는 스포츠 앱이 없다 (네이버 스포츠, 스포키 등은 모두 팬 중심). FencingMind이 이 영역의 선구자가 될 수 있다.

---

## 2. Problem Statement

### 현재 상태 (AS-IS)

```
회원 가입 → OAuth 로그인 → member_type 선택 → (선택적) Gemini 사진 인증 → 끝
                                                          ↑
                                              "실제 펜서임" 증명만 됨
                                              어떤 선수인지는 알 수 없음
```

| 항목 | 현재 상태 | 문제 |
|------|----------|------|
| 선수 매칭 | `members.player_id` 컬럼 존재, **항상 NULL** | 선수가 대회 데이터를 볼 수 없음 |
| 학부모 연결 | `guardian_member_id` 존재, **할당 플로우 없음** | 학부모가 자녀 데이터를 볼 수 없음 |
| 코치 인증 | `club_role` 컬럼 존재, **할당 엔드포인트 없음** | 코치가 클럽 기능을 쓸 수 없음 |
| 조직 소유 | `organizations` 507개 존재, **소유자 없음** | 클럽 관장이 관리자가 될 수 없음 |
| 데이터 수정 | 없음 | 잘못된 데이터 방치 |

### 목표 상태 (TO-BE)

```
회원 가입 → OAuth → member_type 선택 → 이메일 인증 → 본인 인증 → 데이터 연결
                                                                    ↓
                                              선수: 대회 데이터 Claim + 코치 확인
                                              학부모: 자녀 연결 (코치 중개)
                                              코치: 클럽 소속 인증 (관장 초대)
                                              감독: 클럽 소유권 인증 (서류 제출)
```

---

## 3. 인증 Tier 시스템

### 4단계 점진적 인증 (Progressive Verification)

```
┌─────────────────────────────────────────────────────────────────┐
│ TIER 0: UNVERIFIED (미인증)                                      │
│ - 가입 직후 상태                                                  │
│ - 권한: 공개 데이터 열람만                                         │
│ - 조건: 없음                                                     │
├─────────────────────────────────────────────────────────────────┤
│ TIER 1: EMAIL-VERIFIED (이메일 인증)                              │
│ - 이메일 인증 완료                                                │
│ - 권한: + 기본 커뮤니티 참여, 선수 검색                             │
│ - 조건: email_verified = true                                    │
├─────────────────────────────────────────────────────────────────┤
│ TIER 2: IDENTITY-VERIFIED (본인 인증)                             │
│ - Gemini 사진 인증 통과                                           │
│ - 권한: + 선수 데이터 Claim 신청, 조직 Claim 신청                   │
│ - 조건: verification_status = 'verified'                         │
│ - 경로 (member_type별):                                          │
│   - Player: 마스크/도복/협회증 사진                                 │
│   - Coach/Director: 마스크/도복 + 지도자 자격증                     │
│   - Parent: 이메일 인증 + 코치 확인 (Tier 1→2 즉시 승격)            │
│   - General: Tier 1에서 멈춤 (사진 인증 불필요)                     │
├─────────────────────────────────────────────────────────────────┤
│ TIER 3: DATA-LINKED (데이터 연결)                                 │
│ - 실제 데이터와 연결 완료                                          │
│ - 권한: + 본인 대회 데이터 전체 조회, 전적 분석, 클럽 기능            │
│ - 조건: player_id IS NOT NULL 또는 organization 소유               │
│ - 경로:                                                          │
│   - Player: player_claims 승인 → members.player_id 설정            │
│   - Coach: member_organizations.role 할당 (관장 초대)               │
│   - Director: organization_claims 승인 → owner 역할                │
│   - Parent: 자녀 member_id 연결                                   │
├─────────────────────────────────────────────────────────────────┤
│ TIER 4: TRUSTED (신뢰 회원) — 향후 구현                            │
│ - 장기 활동 + 무위반 + 커뮤니티 기여                                │
│ - 권한: + 데이터 수정 요청, 커뮤니티 모더레이션                      │
│ - 조건: Tier 3 + 3개월 활동 + 위반 없음                            │
└─────────────────────────────────────────────────────────────────┘
```

### Tier별 기능 접근 매트릭스

| 기능 | Tier 0 | Tier 1 | Tier 2 | Tier 3 | Tier 4 |
|------|--------|--------|--------|--------|--------|
| 공개 데이터 열람 | O | O | O | O | O |
| 선수 검색 | - | O | O | O | O |
| 커뮤니티 읽기 | O | O | O | O | O |
| 커뮤니티 쓰기 | - | O | O | O | O |
| 선수 Claim 신청 | - | - | O | O | O |
| 본인 대회 전적 조회 | - | - | - | O | O |
| 상대 전적 (H2H) | - | - | - | O | O |
| 클럽 출석 체크인 | - | - | - | O | O |
| 클럽 로스터 관리 | - | - | - | O(코치) | O(코치) |
| 데이터 수정 요청 | - | - | - | - | O |
| 커뮤니티 모더레이션 | - | - | - | - | O |

---

## 4. User Stories

### 4.1 선수 (Player)

> **US-P1**: 선수로서, 나는 회원가입 후 대회 기록 데이터베이스에서 나를 찾아 연결할 수 있어야 한다.

**Acceptance Criteria:**
- 이름 + 소속팀 + 생년으로 검색하면 후보 선수 목록이 표시된다
- 동명이인이 있으면 대회 이력/무기/나이그룹으로 구분할 수 있다
- "이것이 나입니다"를 선택하면 Claim이 생성된다
- Claim은 (1) 자동 매칭 (2) 코치 확인 (3) 관리자 승인 중 하나로 처리된다

> **US-P2**: 선수로서, Claim이 승인되면 나의 모든 대회 전적, 승률, 랭킹을 조회할 수 있어야 한다.

> **US-P3**: 선수로서, 나의 데이터에 잘못된 정보(소속팀, 대회결과 등)가 있으면 수정을 요청할 수 있어야 한다.

> **US-P4**: 이적한 선수로서, 팀 변경 이력이 정확하게 표시되어야 한다. (예: "송도펜싱클럽(2023-06~2024-08) → 최병철펜싱클럽(2024-09~현재)")

### 4.2 학부모 (Player Parent)

> **US-PP1**: 학부모로서, 코치가 보낸 초대를 수락하여 자녀의 데이터에 접근할 수 있어야 한다.

**Acceptance Criteria:**
- 코치가 "학부모 초대" 버튼을 눌러 카카오톡/이메일로 초대 링크 발송
- 학부모가 링크 클릭 → 카카오 로그인 → 자녀 선택 → 연결 완료
- 연결 후 자녀의 대회 전적, 출석 기록 조회 가능

> **US-PP2**: 학부모로서, 코치 초대 없이도 직접 자녀 연결을 신청할 수 있어야 한다. (코치 승인 필요)

> **US-PP3**: 학부모로서, 여러 자녀가 있으면 한 계정에서 모두 관리할 수 있어야 한다.

### 4.3 코치 (Club Coach)

> **US-C1**: 코치로서, 클럽 관장(Director)의 초대를 수락하여 코치 권한을 획득할 수 있어야 한다.

**Acceptance Criteria:**
- 관장이 대시보드에서 "코치 초대" → 이메일/카카오 입력 → 초대 발송
- 코치가 초대 수락 → member_organizations에 role='coach' 추가
- 클럽 로스터, 출석, 레슨 관리 기능 접근 가능

> **US-C2**: 코치로서, 소속 선수의 Player Claim을 확인/승인할 수 있어야 한다.

> **US-C3**: 코치로서, 학부모를 초대하여 선수-학부모를 연결할 수 있어야 한다.

### 4.4 클럽 감독/대표 (Club Director)

> **US-D1**: 감독/관장으로서, "이 클럽이 나의 클럽이다"를 증명하여 클럽 관리 권한을 획득할 수 있어야 한다.

**Acceptance Criteria:**
- organizations 테이블에서 클럽 검색
- 사업자등록증 또는 대한펜싱협회 가맹 서류 업로드
- FencingMind 관리자 승인 후 owner 역할 배정

> **US-D2**: 감독으로서, 코치/스태프를 초대하고 역할을 관리할 수 있어야 한다.

> **US-D3**: 감독으로서, 클럽 설정(출석 IP, 회비, 운영시간)을 관리할 수 있어야 한다.

### 4.5 일반회원 (General)

> **US-G1**: 일반회원으로서, 이후에 선수/코치로 member_type을 변경하고 해당 인증을 진행할 수 있어야 한다.

---

## 5. 상세 플로우

### 5.1 선수 데이터 Claim 플로우

참고 모델: **AskFRED** (USFA 멤버십 번호 교차검증) + **FencingMind 자체 매칭 알고리즘**

```
[선수 회원]                    [Account Service]                 [Players DB]
    │                              │                                │
    │  1. "내 데이터 찾기" 클릭     │                                │
    ├─────────────────────────────→│                                │
    │                              │  2. 검색 폼 표시                │
    │  3. 이름/생년/소속팀/무기 입력  │                                │
    ├─────────────────────────────→│                                │
    │                              │  4. players 테이블 검색         │
    │                              ├───────────────────────────────→│
    │                              │  5. 후보 목록 반환              │
    │                              │←───────────────────────────────┤
    │  6. 후보 목록 표시            │                                │
    │     (대회이력/무기로 구분)     │                                │
    │←─────────────────────────────┤                                │
    │                              │                                │
    │  7. "이것이 나입니다" 선택    │                                │
    ├─────────────────────────────→│                                │
    │                              │  8. 매칭 점수 계산              │
    │                              │     ┌──────────────────────┐   │
    │                              │     │ name == extracted_name│   │
    │                              │     │ + birth_year 일치      │   │
    │                              │     │ + team 일치           │   │
    │                              │     │ = confidence score    │   │
    │                              │     └──────────────────────┘   │
    │                              │                                │
    │                              │  [confidence ≥ 0.85]           │
    │                              │  → 자동 승인 (auto_match)       │
    │                              │  → members.player_id 설정      │
    │                              │                                │
    │                              │  [0.60 ≤ confidence < 0.85]    │
    │                              │  → player_claims 생성 (pending) │
    │                              │  → 코치 확인 요청               │
    │                              │                                │
    │                              │  [confidence < 0.60]           │
    │                              │  → player_claims 생성 (pending) │
    │                              │  → 관리자 수동 검토             │
    │                              │                                │
    │  9. 결과 알림                 │                                │
    │←─────────────────────────────┤                                │
```

#### 매칭 점수 계산 규칙

| 항목 | 가중치 | 방법 |
|------|--------|------|
| 이름 일치 | 0.35 | Gemini 추출 이름과 player.name 비교 (유사도 ≥ 0.7) |
| 생년 일치 | 0.25 | member.birth_date.year == player.birth_year |
| 소속팀 일치 | 0.25 | player.team ↔ organizations.name 퍼지 매칭 |
| 무기 일치 | 0.10 | 대회 기록의 weapon과 선택한 무기 일치 |
| 최근 대회 참가 확인 | 0.05 | "2024년 회장배에 참가했습니까?" 질문 |

#### 동명이인 처리 (PlayerIdentityResolver 연동)

```
동명이인 후보가 2명 이상 → 추가 질문:
  1. "어떤 무기를 사용하시나요?" → 무기 필터
  2. "최근 참가한 대회를 선택하세요" → 대회 이력 필터
  3. "현재 소속팀을 선택하세요" → 팀 필터
  4. 그래도 구분 불가 → 관리자 수동 판정
```

#### 중복 Claim 방지

```sql
-- 하나의 player에 대해 하나의 approved claim만 허용
CREATE UNIQUE INDEX idx_player_claims_approved_player
ON player_claims(player_id)
WHERE status = 'approved';

-- 하나의 member는 하나의 player만 claim 가능
CREATE UNIQUE INDEX idx_player_claims_approved_member
ON player_claims(member_id)
WHERE status = 'approved';
```

### 5.2 학부모-자녀 연결 플로우

참고 모델: **ClassDojo** (코드 + 교사 승인) + **TeamSnap** (초대 기반)

```
방법 1: 코치 중개 (권장)
━━━━━━━━━━━━━━━━━━━━━━
[코치]                          [Account Service]              [학부모]
  │  1. "학부모 초대" 클릭       │                              │
  ├─────────────────────────────→│                              │
  │  2. 선수 선택 + 학부모        │                              │
  │     전화번호/이메일 입력       │                              │
  ├─────────────────────────────→│                              │
  │                              │  3. 초대 링크 생성            │
  │                              │     (member_invitations)      │
  │                              │  4. 카카오톡/이메일 발송       │
  │                              ├─────────────────────────────→│
  │                              │                              │  5. 링크 클릭
  │                              │                              │  6. 카카오 로그인
  │                              │                              │  7. 자녀 확인 + 수락
  │                              │←─────────────────────────────┤
  │                              │  8. guardian_member_id 설정    │
  │                              │  9. member_organizations 생성  │
  │  10. 연결 완료 알림           │                              │
  │←─────────────────────────────┤                              │

방법 2: 학부모 직접 신청
━━━━━━━━━━━━━━━━━━━━━━
[학부모]                        [Account Service]              [코치]
  │  1. "자녀 연결" 클릭         │                              │
  ├─────────────────────────────→│                              │
  │  2. 자녀 이름 + 클럽 입력    │                              │
  ├─────────────────────────────→│                              │
  │                              │  3. 신청 생성 (pending)       │
  │                              │  4. 코치에게 알림             │
  │                              ├─────────────────────────────→│
  │                              │                              │  5. 승인/거부
  │                              │←─────────────────────────────┤
  │  6. 결과 알림                │                              │
  │←─────────────────────────────┤                              │
```

#### 미성년자 보호 정책

**연령 판별**: 카카오 OAuth의 `age_range` 값을 세션에서만 확인 (DB에 birthyear 저장하지 않음 — 저장 시 추가 동의/관리/파기 의무 발생)

**14세 미만 (age_range: "1~9", "10~14")**:
- 가입 자체에 **법정대리인 동의 필수** (개인정보보호법 제22조의2)
- 보호자에게 이메일/SMS로 동의 요청 → 보호자가 카카오 로그인 + 동의 확인
- 보호자 age_range가 "20~29" 이상(성인)인지 검증
- 동의 없으면 가입 불가 (7일 후 임시 데이터 삭제)
- `guardian_member_id` 필수 설정
- Player Claim: 보호자 계정에서만 가능 (아동 본인 Claim 차단)

**14~18세 (age_range: "15~19")**:
- 본인 가입 가능 (법정대리인 동의 불필요)
- **Player Claim 시 보호자 동의 필요**:
  - 선수가 보호자 연락처 입력 → 보호자에게 카카오 링크 발송
  - 보호자가 카카오 로그인 + "자녀 데이터 연동 동의" 클릭
  - 보호자 age_range "adult" 검증 (위변조 방지)
  - 이 과정에서 보호자 계정 자동 생성 + 자녀 연결
  - 보호자 미응답: 7일 후 만료, 재발송 가능 (최대 3회)
  - 코치 가입 클럽이면 코치 경유 대안 가능

**19세 이상**: 제한 없음

**공통 규칙**:
- 학부모 1명당 자녀 N명 연결 가능 (guardian_member_id가 자녀 측에 있으므로)
- 학부모는 자녀의 대회 전적, 출석 기록 조회 가능 (수정 불가)
- 법정대리인은 언제든 아동의 개인정보 열람/삭제 요구 가능

### 5.3 코치/감독 조직 인증 플로우

참고 모델: **GitHub Organizations** (관리자 초대) + **대한체육회** (2단계 승인)

```
단계 1: 클럽 소유권 인증 (Director - 1회)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
[관장]                          [Account Service]              [Club Service]
  │  1. "내 클럽 찾기"           │                              │
  ├─────────────────────────────→│                              │
  │  2. organizations 검색       │                              │
  │  3. 클럽 선택                │                              │
  ├─────────────────────────────→│                              │
  │                              │  4. organization_claims 생성  │
  │  5. 사업자등록증 촬영/업로드  │                              │
  ├─────────────────────────────→│                              │
  │                              │  6. 3-Layer 자동 검증         │
  │                              │  ┌─────────────────────────┐ │
  │                              │  │ Layer 1: Gemini OCR      │ │
  │                              │  │  사업자등록증 이미지 분석  │ │
  │                              │  │  → 사업자번호, 상호,      │ │
  │                              │  │    대표자명, 개업일 추출   │ │
  │                              │  │                          │ │
  │                              │  │ Layer 2: Check Digit     │ │
  │                              │  │  사업자번호 검증식 계산    │ │
  │                              │  │  weights [1,3,7,1,3,7,   │ │
  │                              │  │           1,3,5]          │ │
  │                              │  │  → 번호 자체 유효성 확인   │ │
  │                              │  │                          │ │
  │                              │  │ Layer 3: 국세청 API       │ │
  │                              │  │  진위확인 (사업자번호 +    │ │
  │                              │  │   대표자명 + 개업일 교차)  │ │
  │                              │  │  → 사업 상태 확인          │ │
  │                              │  └─────────────────────────┘ │
  │                              │                              │
  │                              │  [3-Layer 모두 통과]          │
  │                              │  → 자동 승인 (auto_verify)    │
  │                              │  → member_organizations 생성  │
  │                              │     (role='owner')            │
  │                              │                              │
  │                              │  7. Club 서비스 자동 등록 ──→ │
  │                              │     클럽 활성화 이벤트         │  8. club_settings 생성
  │                              │                              │     (자동 등록)
  │                              │                              │
  │                              │  [일부 Layer 실패]            │
  │                              │  → 수동 관리자 검토            │
  │                              │                              │
  │  9. "클럽 관리" 기능 해제     │                              │
  │←─────────────────────────────┤                              │

단계 2: 코치/스태프 초대 (반복)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
[관장]                          [Account Service]              [코치]
  │  1. "스태프 초대"            │                              │
  │  2. 이메일 + 역할 선택       │                              │
  │     (coach/assistant/staff)  │                              │
  ├─────────────────────────────→│                              │
  │                              │  3. member_invitations 생성   │
  │                              │  4. 초대 발송                 │
  │                              ├─────────────────────────────→│
  │                              │                              │  5. 수락
  │                              │←─────────────────────────────┤
  │                              │  6. member_organizations 생성  │
  │                              │     (role=선택된 역할)         │
  │  7. 새 스태프 표시            │                              │
  │←─────────────────────────────┤                              │
```

#### 역할 계층 및 권한

```
Owner (관장/대표)
├── 모든 권한
├── 코치/스태프 초대 및 제거
├── 클럽 설정 관리
└── 재무 관리

Head Coach (수석 코치)
├── 선수/학부모 관리
├── 출석 관리
├── 레슨 관리
├── Player Claim 확인
└── 학부모 초대

Coach (코치)
├── 선수 조회
├── 출석 체크
├── 레슨 관리
├── Player Claim 확인
└── 학부모 초대

Assistant (보조)
├── 출석 체크
└── 선수 조회

Staff (행정)
├── 회비 관리
├── 일정 관리
└── 선수 조회
```

#### 사업자등록증 3-Layer 자동 검증 파이프라인

기존 Gemini 인프라를 활용하여 사업자등록증을 자동으로 읽고, 국세청 API로 진위를 확인하는 파이프라인.

**Layer 1: Gemini 2.0 Flash OCR (기존 인프라 활용)**

```python
# GeminiVerifier에 추가할 프롬프트 (services/account/app/verification/processor.py)
PROMPTS["business_registration"] = """
이 이미지는 한국 사업자등록증입니다.
다음 항목을 정확하게 추출하고 JSON으로 응답하세요:

1. 사업자등록번호 (business_registration_number: string, "XXX-XX-XXXXX" 형식)
2. 상호 또는 법인명 (business_name: string or null)
3. 대표자 성명 (representative_name: string or null)
4. 개업년월일 (opening_date: string or null, "YYYYMMDD" 형식)
5. 사업장 소재지 (address: string or null)
6. 업태 (business_type: string or null)
7. 종목 (business_item: string or null)

형식: { "business_registration_number": "...", "business_name": "...", ... }
추출할 수 없는 항목은 null로 표시하세요.
"""
```

정확도: 95-98% (Gemini 2.0 Flash 기준, 일반적인 사업자등록증)

**Layer 2: 사업자등록번호 Check Digit 검증 (오프라인)**

```python
# packages/shared_core/utils/brn_validator.py
def validate_brn_checkdigit(brn: str) -> bool:
    """사업자등록번호 체크디짓 검증 (XXX-XX-XXXXX)"""
    brn = brn.replace("-", "").replace(" ", "")
    if len(brn) != 10 or not brn.isdigit():
        return False
    weights = [1, 3, 7, 1, 3, 7, 1, 3, 5]
    digits = [int(d) for d in brn]
    total = sum(d * w for d, w in zip(digits[:9], weights))
    total += (digits[8] * 5) // 10
    check = (10 - (total % 10)) % 10
    return check == digits[9]
```

이 단계는 Gemini가 추출한 번호가 형식적으로 유효한지 즉시 확인. API 호출 없이 로컬 연산.

**Layer 3: 국세청 API 진위확인 (무료)**

```python
# packages/shared_core/utils/nts_client.py
import httpx

NTS_BASE = "https://api.odcloud.kr/api/nts-businessman/v1"

async def verify_business_registration(
    brn: str,
    representative_name: str,
    opening_date: str,  # "YYYYMMDD"
    api_key: str
) -> dict:
    """국세청 사업자등록 진위확인 API (무료, data.go.kr 발급)"""
    url = f"{NTS_BASE}/validate?serviceKey={api_key}"
    payload = {
        "businesses": [{
            "b_no": brn.replace("-", ""),
            "start_dt": opening_date,
            "p_nm": representative_name,
        }]
    }
    async with httpx.AsyncClient() as client:
        resp = await client.post(url, json=payload)
        result = resp.json()

    item = result["data"][0]
    return {
        "valid": item.get("valid") == "01",       # 01=일치
        "status": item.get("b_stt"),               # 계속사업자/폐업 등
        "status_code": item.get("b_stt_cd"),       # 01=계속, 02=휴업, 03=폐업
        "tax_type": item.get("tax_type"),           # 일반/간이/면세
        "raw": item
    }
```

| API | 비용 | 일일 한도 | 응답 시간 |
|-----|------|----------|----------|
| 사업자 상태조회 | 무료 | 건당 100건 | ~200ms |
| 사업자 진위확인 | 무료 | 건당 100건 | ~300ms |

**필요 환경변수**: `NTS_API_KEY` (data.go.kr에서 무료 발급)

**3-Layer 판정 로직**

```
Layer 1 (Gemini OCR) 실패     → "사진이 선명하지 않습니다" 메시지 + 재업로드 요청
Layer 2 (Check Digit) 실패    → "유효하지 않은 사업자등록번호입니다" + 수동 검토 안내
Layer 3 (국세청 API) 실패      → 분기:
  - valid=false (정보 불일치)  → "등록 정보가 일치하지 않습니다" + 수동 검토
  - status_code=03 (폐업)     → "폐업된 사업자입니다" + 거부
  - status_code=02 (휴업)     → "휴업 중인 사업자입니다" + 수동 검토
  - status_code=01 (계속)     → ✅ 자동 승인
  - API 오류/timeout          → 관리자 수동 검토로 폴백

모든 Layer 통과 + 대표자명 == 가입자 실명  → 자동 승인 (관리자 개입 불필요)
모든 Layer 통과 + 대표자명 ≠ 가입자 실명   → 관리자 검토 (위임 관계 확인 필요)
```

**구현 파일**:
- `packages/shared_core/utils/brn_validator.py` — 체크디짓 검증 (NEW)
- `packages/shared_core/utils/nts_client.py` — 국세청 API 클라이언트 (NEW)
- `services/account/app/verification/processor.py` — Gemini 프롬프트 추가 (MODIFY)

#### 감독 인증 → Club 서비스 자동 등록

감독의 organization_claim이 승인되면 (자동 or 수동), Club 서비스에 해당 클럽이 **자동으로 관리 대상으로 등록**된다.

```
[Account Service]                          [Club Service DB]
     │                                          │
     │  organization_claims 승인됨               │
     │  (status='approved', role='owner')        │
     ├─────────────────────────────────────────→ │
     │                                          │
     │  1. member_organizations INSERT           │
     │     (member_id, org_id, role='owner')     │
     │                                          │
     │  2. club_settings UPSERT                  │
     │     organization_id = org_id              │
     │     status = 'active'                     │
     │     onboarding_completed = false          │
     │     created_by = member_id                │
     │                                          │
     │  3. organizations UPDATE                  │
     │     owner_member_id = member_id           │
     │     (클럽 소유자 명시)                      │
     │                                          │
```

**구현 방식**: Account 서비스가 DB에 직접 기록 (같은 Supabase DB 공유)
- Club 서비스 API를 호출하지 않음 (서비스 간 순환 의존 방지)
- Club 서비스는 다음 접속 시 `club_settings`를 읽어 온보딩 안내 표시

```python
# services/account/app/claims/organization.py (승인 처리 함수)
async def approve_organization_claim(claim_id: str, db):
    claim = await db.table("organization_claims")\
        .select("*").eq("id", claim_id).single().execute()

    # 1. member_organizations 생성
    await db.table("member_organizations").upsert({
        "member_id": claim["member_id"],
        "organization_id": claim["organization_id"],
        "role": "owner",
        "is_primary": True,
        "status": "active",
    }).execute()

    # 2. club_settings 자동 생성 (Club 서비스용)
    await db.table("club_settings").upsert({
        "organization_id": claim["organization_id"],
        "status": "active",
        "onboarding_completed": False,
        "created_by": claim["member_id"],
    }, on_conflict="organization_id").execute()

    # 3. organizations 테이블에 owner 기록
    await db.table("organizations").update({
        "owner_member_id": claim["member_id"],
    }).eq("id", claim["organization_id"]).execute()

    # 4. Claim 상태 업데이트
    await db.table("organization_claims").update({
        "status": "approved",
        "reviewed_at": "now()",
    }).eq("id", claim_id).execute()
```

**Club 서비스 온보딩 플로우 (자동 등록 후)**:
1. 감독이 `club.fencingmind.ai`에 처음 접속
2. `club_settings`에서 `onboarding_completed=false` 감지
3. 온보딩 마법사 표시:
   - 클럽 기본 정보 확인/수정 (운영시간, 연락처)
   - 출석 체크인 IP 설정
   - 코치/스태프 초대
   - 기존 회원 일괄 등록 또는 초대
4. 완료 시 `onboarding_completed=true`

### 5.4 데이터 수정 요청 플로우

```
[Tier 3+ 회원]                  [Account Service]              [Admin / Auto]
  │  1. 데이터 오류 발견          │                              │
  │     (잘못된 소속팀, 결과 등)   │                              │
  ├─────────────────────────────→│                              │
  │  2. 수정 요청 폼 작성         │                              │
  │     - 대상: player/event/match │                             │
  │     - 필드: team_name 등       │                             │
  │     - 현재값 / 요청값          │                             │
  │     - 증빙 (선택)             │                              │
  ├─────────────────────────────→│                              │
  │                              │  3. data_correction_requests  │
  │                              │     생성 (pending)            │
  │                              │                              │
  │                              │  4. 자동 해결 시도             │
  │                              │  ┌─────────────────────────┐ │
  │                              │  │ team_name 변경:          │ │
  │                              │  │  organizations에서 검색   │ │
  │                              │  │  → 일치하면 auto_resolve  │ │
  │                              │  │                          │ │
  │                              │  │ 결과 귀속 오류:           │ │
  │                              │  │  PlayerIdentityResolver  │ │
  │                              │  │  동명이인 검출           │ │
  │                              │  │  → 감지되면 auto_resolve  │ │
  │                              │  └─────────────────────────┘ │
  │                              │                              │
  │                              │  5. 자동 해결 불가 시         │
  │                              │     → 관리자 리뷰 큐          │
  │                              ├─────────────────────────────→│
  │                              │                              │  6. 수동 처리
  │                              │←─────────────────────────────┤
  │  7. 결과 알림                │                              │
  │←─────────────────────────────┤                              │
```

---

## 6. 서비스 경계 (Account vs Club)

### 책임 분리 원칙

```
┌──────────────────────────────────────────┐
│        Account Service (port 70)          │
│        "당신이 누구인지" (Identity)         │
├──────────────────────────────────────────┤
│  ✅ OAuth 로그인 / 회원가입                │
│  ✅ 이메일 인증                            │
│  ✅ Gemini 본인인증 (사진)                  │
│  ✅ member_type 관리                       │
│  ✅ Player Claim (선수 데이터 매칭)         │
│  ✅ Organization Claim (클럽 소유권)        │
│  ✅ 학부모-자녀 연결                        │
│  ✅ 데이터 수정 요청                        │
│  ✅ 구독/결제                              │
│  ✅ 초대 발송 (대리)                        │
└──────────────────────────────────────────┘
          │
          │ JWT: { member_id, member_type,
          │        verification_tier, player_id,
          │        organization_ids }
          ▼
┌──────────────────────────────────────────┐
│         Club Service (port 72)            │
│        "당신이 무엇을 하는지" (Operations)  │
├──────────────────────────────────────────┤
│  ✅ club_role 기반 권한 체크               │
│  ✅ 로스터 관리                            │
│  ✅ 출석 관리                              │
│  ✅ 레슨 관리                              │
│  ✅ 회비 관리                              │
│  ✅ 대회 참가 관리                          │
│  ✅ Player Claim 코치 확인                  │
│  ✅ 클럽 설정                              │
└──────────────────────────────────────────┘
```

### 의존 방향

```
Account → JWT 발급 (producer)
       → club_settings 자동 생성 (감독 인증 시, DB 직접 기록)
Club → JWT 소비 (consumer) + member_organizations 참조
     → club_settings 소비 (Account가 생성한 레코드를 읽어 사용)
Data → JWT 소비 + players/competitions 데이터 제공

account은 club의 API를 호출하지 않음 (순환 의존 방지)
account이 club_settings에 직접 INSERT하여 클럽을 활성화함 (같은 DB)
club은 account의 JWT를 소비하고, DB 직접 참조
```

### 감독 인증 → Club 자동 등록 시퀀스

```
1. 감독이 사업자등록증 업로드 (Account Service)
2. 3-Layer 자동 검증 통과
3. organization_claims.status = 'approved'
4. Account Service가 DB에 직접 기록:
   a) member_organizations (role='owner')
   b) club_settings (status='active', onboarding_completed=false)
   c) organizations.owner_member_id 설정
5. 감독의 JWT에 organization_ids 포함
6. 감독이 club.fencingmind.ai 접속 시 → 온보딩 마법사 자동 표시
```

---

## 7. DB 스키마 변경

### Migration 013: 인증 시스템 테이블

```sql
-- Migration 013: Verification System Tables
-- 회원 유형별 인증 및 선수 데이터 매칭

-- ============================================================
-- 1. player_claims: 선수 데이터 Claim
-- ============================================================
CREATE TABLE IF NOT EXISTS player_claims (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    member_id UUID NOT NULL REFERENCES members(id) ON DELETE CASCADE,
    player_id BIGINT NOT NULL REFERENCES players(id),

    -- 매칭 방법 및 근거
    claim_method VARCHAR(30) NOT NULL CHECK (claim_method IN (
        'auto_match',       -- 자동 매칭 (confidence ≥ 0.85)
        'self_search',      -- 본인 검색 후 선택
        'coach_confirm',    -- 코치가 확인
        'admin_assign'      -- 관리자 직접 할당
    )),
    match_confidence DECIMAL(3,2),
    evidence_text TEXT,
    evidence_verification_id UUID REFERENCES verifications(id),

    -- 처리 상태
    status VARCHAR(20) NOT NULL DEFAULT 'pending' CHECK (status IN (
        'pending', 'approved', 'rejected', 'expired', 'superseded'
    )),
    reviewed_by UUID REFERENCES members(id),
    reviewed_at TIMESTAMPTZ,
    rejection_reason TEXT,

    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    expires_at TIMESTAMPTZ DEFAULT NOW() + INTERVAL '30 days',

    UNIQUE(member_id, player_id)
);

-- 하나의 player에 대해 하나의 approved claim만
CREATE UNIQUE INDEX idx_player_claims_approved_player
    ON player_claims(player_id) WHERE status = 'approved';
-- 하나의 member는 하나의 approved claim만
CREATE UNIQUE INDEX idx_player_claims_approved_member
    ON player_claims(member_id) WHERE status = 'approved';

CREATE INDEX idx_player_claims_status ON player_claims(status);
CREATE INDEX idx_player_claims_member ON player_claims(member_id);

-- ============================================================
-- 2. member_organizations: 다중 조직 소속
-- ============================================================
CREATE TABLE IF NOT EXISTS member_organizations (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    member_id UUID NOT NULL REFERENCES members(id) ON DELETE CASCADE,
    organization_id BIGINT NOT NULL REFERENCES organizations(id),
    role VARCHAR(20) NOT NULL CHECK (role IN (
        'owner', 'head_coach', 'coach', 'assistant',
        'student', 'parent', 'staff'
    )),
    is_primary BOOLEAN NOT NULL DEFAULT false,
    status VARCHAR(20) NOT NULL DEFAULT 'active' CHECK (status IN (
        'active', 'inactive', 'pending_approval', 'rejected'
    )),
    joined_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    left_at TIMESTAMPTZ,
    invited_by UUID REFERENCES members(id),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    UNIQUE(member_id, organization_id)
);

-- 1 primary org per member
CREATE UNIQUE INDEX idx_member_org_primary
    ON member_organizations(member_id) WHERE is_primary = true;
CREATE INDEX idx_member_orgs_org ON member_organizations(organization_id);

-- ============================================================
-- 3. organization_claims: 조직 소유권 인증
-- ============================================================
CREATE TABLE IF NOT EXISTS organization_claims (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    member_id UUID NOT NULL REFERENCES members(id) ON DELETE CASCADE,
    organization_id BIGINT NOT NULL REFERENCES organizations(id),

    claim_type VARCHAR(20) NOT NULL CHECK (claim_type IN (
        'director', 'head_coach', 'representative'
    )),
    evidence_type VARCHAR(30) CHECK (evidence_type IN (
        'business_registration',  -- 사업자등록증
        'kfa_letter',            -- 대한펜싱협회 가맹 서류
        'school_document',       -- 학교 공문
        'coach_certificate',     -- 지도자 자격증
        'other'
    )),
    evidence_url TEXT,
    evidence_storage_path TEXT,

    -- 사업자등록증 자동 검증 결과 (3-Layer Pipeline)
    brn_number VARCHAR(12),                    -- 사업자등록번호 (XXX-XX-XXXXX)
    brn_business_name VARCHAR(100),            -- 상호명
    brn_representative_name VARCHAR(50),       -- 대표자명
    brn_opening_date VARCHAR(8),               -- 개업일 (YYYYMMDD)
    brn_ocr_confidence DECIMAL(3,2),           -- Gemini OCR 신뢰도
    brn_checkdigit_valid BOOLEAN,              -- 체크디짓 통과 여부
    brn_nts_valid BOOLEAN,                     -- 국세청 API 검증 통과 여부
    brn_nts_status VARCHAR(20),                -- 국세청 사업 상태 (계속/휴업/폐업)
    brn_auto_verified BOOLEAN DEFAULT false,   -- 3-Layer 자동 검증 통과 여부

    status VARCHAR(20) NOT NULL DEFAULT 'pending' CHECK (status IN (
        'pending', 'auto_verified', 'approved', 'rejected', 'expired'
    )),
    reviewed_by UUID REFERENCES members(id),
    reviewed_at TIMESTAMPTZ,
    rejection_reason TEXT,

    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE(member_id, organization_id)
);

CREATE INDEX idx_org_claims_status ON organization_claims(status);
CREATE INDEX idx_org_claims_org ON organization_claims(organization_id);

-- ============================================================
-- 4. member_invitations: 초대 관리
-- ============================================================
CREATE TABLE IF NOT EXISTS member_invitations (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id BIGINT NOT NULL REFERENCES organizations(id),
    invited_by UUID NOT NULL REFERENCES members(id),

    -- 초대 대상 (이메일 또는 기존 회원)
    target_email VARCHAR(255),
    target_phone VARCHAR(20),
    target_member_id UUID REFERENCES members(id),

    -- 초대 역할
    intended_role VARCHAR(20) NOT NULL CHECK (intended_role IN (
        'head_coach', 'coach', 'assistant', 'student', 'parent', 'staff'
    )),

    -- 학부모 초대 시 자녀 member_id
    child_member_id UUID REFERENCES members(id),

    token VARCHAR(64) NOT NULL UNIQUE,
    status VARCHAR(20) NOT NULL DEFAULT 'pending' CHECK (status IN (
        'pending', 'accepted', 'rejected', 'expired', 'cancelled'
    )),
    message TEXT,

    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    expires_at TIMESTAMPTZ NOT NULL DEFAULT NOW() + INTERVAL '7 days',
    accepted_at TIMESTAMPTZ
);

CREATE INDEX idx_invitations_token ON member_invitations(token) WHERE status = 'pending';
CREATE INDEX idx_invitations_email ON member_invitations(target_email) WHERE status = 'pending';
CREATE INDEX idx_invitations_org ON member_invitations(organization_id);

-- ============================================================
-- 5. data_correction_requests: 데이터 수정 요청
-- ============================================================
CREATE TABLE IF NOT EXISTS data_correction_requests (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    requester_member_id UUID NOT NULL REFERENCES members(id),

    entity_type VARCHAR(20) NOT NULL CHECK (entity_type IN (
        'player', 'event', 'match', 'competition', 'organization'
    )),
    entity_id BIGINT NOT NULL,
    field_name VARCHAR(50) NOT NULL,
    current_value TEXT,
    requested_value TEXT NOT NULL,
    reason TEXT,

    evidence_text TEXT,
    evidence_image_url TEXT,

    status VARCHAR(20) NOT NULL DEFAULT 'pending' CHECK (status IN (
        'pending', 'approved', 'rejected', 'auto_resolved'
    )),
    resolved_by UUID REFERENCES members(id),
    resolved_at TIMESTAMPTZ,
    resolution_notes TEXT,

    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_corrections_status ON data_correction_requests(status);
CREATE INDEX idx_corrections_requester ON data_correction_requests(requester_member_id);
CREATE INDEX idx_corrections_entity ON data_correction_requests(entity_type, entity_id);

-- ============================================================
-- 6. members 테이블 확장
-- ============================================================
ALTER TABLE members ADD COLUMN IF NOT EXISTS verification_tier SMALLINT DEFAULT 0
    CHECK (verification_tier BETWEEN 0 AND 4);
ALTER TABLE members ADD COLUMN IF NOT EXISTS data_linked_at TIMESTAMPTZ;
ALTER TABLE members ADD COLUMN IF NOT EXISTS trust_level VARCHAR(20) DEFAULT 'basic'
    CHECK (trust_level IN ('basic', 'verified', 'trusted', 'admin'));

-- verification_tier 자동 계산은 application level에서 처리
-- (email_verified, verification_status, player_id 등을 기반)
```

---

## 8. API 엔드포인트 설계

### Account Service 신규 엔드포인트

#### 8.1 Player Claim API

```
GET  /account/claim/player/search?name=...&birth_year=...&team=...&weapon=...
     Auth: Tier 1+ (email verified)
     Response: { candidates: [{ player_id, name, team, weapon,
                                competition_count, last_competition, confidence }] }

POST /account/claim/player
     Auth: Tier 2+ (identity verified)
     Body: { player_id, evidence_text? }
     Response: { claim_id, status: "approved"|"pending", confidence }

GET  /account/claim/player/status
     Auth: authenticated
     Response: { claim: { id, player_id, status, created_at, expires_at } | null }

DELETE /account/claim/player/{claim_id}
     Auth: claim owner
     Response: { success: true }
```

#### 8.2 Organization Claim API

```
GET  /account/claim/org/search?name=...&org_type=...
     Auth: Tier 1+
     Response: { organizations: [{ id, name, org_type, member_count }] }

POST /account/claim/org
     Auth: Tier 2+
     Body: { organization_id, claim_type: "director"|"head_coach" }
     Response: { claim_id, status: "pending" }

POST /account/claim/org/{claim_id}/evidence
     Auth: claim owner
     Body: multipart (evidence_type, file)
     Response: { status: "pending", evidence_url }

GET  /account/claim/org/status
     Auth: authenticated
     Response: { claim: { id, organization_id, status, claim_type } | null }
```

#### 8.3 Family (학부모) API

```
POST /account/family/request-child-link
     Auth: Tier 1+ (member_type=player_parent)
     Body: { child_name, club_name }
     Response: { request_id, status: "pending_coach_approval" }

GET  /account/family/children
     Auth: authenticated (member_type=player_parent)
     Response: { children: [{ member_id, full_name, player_id?, club_name }] }
```

#### 8.4 Invitation API

```
POST /account/invitations
     Auth: Tier 3+ (director/admin role in org)
     Body: { organization_id, target_email|target_phone,
             intended_role, child_member_id?, message? }
     Response: { invitation_id, token, expires_at }

GET  /account/invitations/pending
     Auth: Tier 3+ (org staff)
     Response: { invitations: [...] }

POST /account/invitations/{token}/accept
     Auth: authenticated
     Response: { member_organization_id, role }

POST /account/invitations/{token}/reject
     Auth: authenticated
     Response: { success: true }
```

#### 8.5 Data Correction API

```
POST /account/corrections
     Auth: Tier 3+
     Body: { entity_type, entity_id, field_name,
             current_value, requested_value, reason?, evidence? }
     Response: { correction_id, status }

GET  /account/corrections
     Auth: authenticated
     Response: { corrections: [{ id, entity_type, field_name, status, created_at }] }
```

#### 8.6 Verification Tier API

```
GET  /account/verification/tier
     Auth: authenticated
     Response: {
       current_tier: 2,
       next_steps: [
         { action: "claim_player", description: "선수 데이터 연결", url: "/account/claim/player/search" }
       ],
       tier_history: [
         { tier: 0, achieved_at: "..." },
         { tier: 1, achieved_at: "..." },
         { tier: 2, achieved_at: "..." }
       ]
     }
```

### Club Service 신규 엔드포인트

```
GET  /club/claims/pending
     Auth: coach+ in org
     Response: { claims: [{ id, member_name, player_name, confidence }] }

POST /club/claims/{claim_id}/confirm
     Auth: coach+ in org
     Response: { status: "approved" }

POST /club/claims/{claim_id}/reject
     Auth: coach+ in org
     Body: { reason }
     Response: { status: "rejected" }
```

### Admin 신규 엔드포인트

```
GET  /admin/claims/player?status=pending
POST /admin/claims/player/{id}/approve
POST /admin/claims/player/{id}/reject  { reason }

GET  /admin/claims/org?status=pending
POST /admin/claims/org/{id}/approve
POST /admin/claims/org/{id}/reject  { reason }

GET  /admin/corrections?status=pending
POST /admin/corrections/{id}/resolve  { action: "approve"|"reject", notes }
```

---

## 9. 개인정보보호 및 보안

### 9.1 법적 근거 및 원칙

#### 스크래핑 대회 데이터의 법적 지위

대한펜싱협회가 공개한 대회 결과(이름, 소속팀, 성적)를 수집하여 서비스에 활용하는 법적 근거:

| 근거 | 법률 | 적용 |
|------|------|------|
| **정당한 이익** | 제15조 1항 6호 | 펜싱 데이터 플랫폼으로서의 정당한 이익, 선수 경력 관리에 도움 |
| **공개 정보 판례** | 대법원 2014다235080 | 이미 공개된 정보를 동일 목적 범위 내에서 처리 가능 |

**단, 판례의 제한 조건이 있다:**
- 원래 공개 목적(대회별 결과 공지)과 우리 이용 목적(통합 데이터 플랫폼) 간 **동일성 유지** 필요
- 11,786명을 통합 프로필로 구축하는 것은 원래 공개 범위를 넘을 수 있어 **추가 보호 조치** 필요

#### 데이터 접근 모델: "공개 수준 동일 + 통합 분석은 단계적"

```
┌──────────────────────────────────────────────────────────────┐
│  대회별 결과 페이지 (비로그인 포함 누구나 열람 가능)             │
│  → 실명 + 소속팀 + 대회결과 그대로 표시                        │
│  → 대한펜싱협회 사이트와 동일 수준 (법적 리스크 낮음)            │
│  → 근거: 이미 공개된 정보의 동일 목적 재공개                    │
├──────────────────────────────────────────────────────────────┤
│  통합 선수 프로필 (로그인 회원만 열람 가능)                      │
│  → 이름 + 소속팀 + 대회 목록 + 무기                           │
│  → 이용약관 동의 기반 (가입 시 동의)                            │
│  → 근거: 정당한 이익 + 회원 동의                               │
├──────────────────────────────────────────────────────────────┤
│  상세 분석 (Claim한 본인 / 코치 / 유료 구독자)                  │
│  → H2H 전적, 승률 분석, 랭킹 추이, 기량 분석                   │
│  → Claim 시 또는 구독 시 별도 동의                             │
│  → 근거: 명시적 동의                                          │
├──────────────────────────────────────────────────────────────┤
│  비회원 선수의 삭제 요청 (opt-out)                              │
│  → 본인 확인 후 10일 이내 삭제 또는 비식별화 처리               │
│  → 대응 안 하면 개인정보보호위원회 민원 리스크                   │
│  → 삭제 절차: 본인확인 → 삭제 처리 → 결과 통보 → 로그 보관     │
└──────────────────────────────────────────────────────────────┘
```

### 9.2 개인정보 수집/이용 동의 설계

#### 수집 항목 분류

| 정보 항목 | 개인정보? | 필수/선택 | 수집 목적 | 미제공 시 |
|-----------|:---:|:---:|------|------|
| 이름 (실명) | O | **필수** | 회원 관리 | 가입 불가 |
| 이메일 | O | **필수** | 계정, 알림 | 가입 불가 |
| 생년월일 | O | **필수** | 미성년자 확인 | 가입 불가 |
| 전화번호 | O | **선택** | 알림, 메신저 연동 | SMS 알림 미제공 |
| 소속팀 | O (결합 시) | **선택** | 대회 데이터 연동 | 자동 매칭 정확도 감소 |
| 무기종목 | X (단독) | **선택** | 맞춤 서비스 | 종목별 추천 미제공 |

**주의**: 선택 정보를 미제공한다고 핵심 서비스(가입, 로그인, 공개 데이터 열람)를 거부하면 **3천만원 이하 과태료** (법 제16조 3항). 해당 정보가 필요한 부가 기능만 제한 가능.

#### 회원가입 동의서 UI 설계

```
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
FencingMind 회원가입
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

[필수] ☑ 개인정보 수집/이용 동의
  ├ 수집 항목: 이름, 이메일, 생년월일
  ├ 수집 목적: 회원 관리, 서비스 제공, 미성년자 확인
  ├ 보유 기간: 회원 탈퇴 시까지
  └ ※ 동의하지 않으면 서비스 이용이 불가합니다.
  [전문 보기]

[필수] ☑ 이용약관 동의
  └ ※ 대한펜싱협회 공개 대회 결과 데이터의 수집/제공 근거 포함
  [전문 보기]

[선택] ☐ 추가 개인정보 수집/이용 동의
  ├ 수집 항목: 전화번호, 소속팀
  ├ 수집 목적: 맞춤 서비스, 대회 데이터 연동, 메신저 알림
  ├ 보유 기간: 회원 탈퇴 시까지
  └ ※ 동의하지 않아도 서비스 이용이 가능합니다.
  [전문 보기]

[선택] ☐ 마케팅 정보 수신 동의
  └ ※ 대회 소식, 신규 기능 안내 등
  [전문 보기]

                              [가입하기]
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
```

#### Player Claim 시 추가 동의

```
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
선수 데이터 연결 동의
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

"홍길동"님의 대회 데이터를 내 계정에 연결합니다.

[필수] ☑ 대회 데이터 연동 동의
  ├ 연동 항목: 대회 참가 기록, 경기 결과, 순위, 소속팀 이력
  ├ 이용 목적: 본인 전적 조회, 성과 분석, 랭킹 제공
  ├ 보유 기간: 연동 해제 시까지
  └ ※ 언제든 "연동 해제"로 연결을 끊을 수 있습니다.

                       [연동하기] [취소]
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
```

#### 동의 기록(Consent Log) 저장

```sql
-- Migration 013에 추가
CREATE TABLE IF NOT EXISTS consent_logs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    member_id UUID NOT NULL REFERENCES members(id) ON DELETE CASCADE,
    consent_type VARCHAR(30) NOT NULL CHECK (consent_type IN (
        'required_privacy',      -- 필수 개인정보 동의
        'terms_of_service',      -- 이용약관 동의
        'optional_privacy',      -- 선택 개인정보 동의
        'marketing',             -- 마케팅 수신 동의
        'player_claim',          -- 선수 데이터 연동 동의
        'guardian_consent',      -- 법정대리인 동의
        'minor_claim_consent'    -- 미성년자 Claim 보호자 동의
    )),
    agreed BOOLEAN NOT NULL,
    consent_version VARCHAR(10) NOT NULL DEFAULT '1.0',
    ip_address INET,
    user_agent TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_consent_member ON consent_logs(member_id);
CREATE INDEX idx_consent_type ON consent_logs(consent_type, agreed);
```

### 9.3 미성년자 보호 정책 (상세)

#### 연령 판별 방법

카카오 OAuth의 `age_range`를 **세션에서만 확인** (DB 저장하지 않음):

```python
# birthyear는 DB에 저장하지 않는다 (저장하면 추가 동의/관리/파기 의무 발생)
# age_range만 세션에서 실시간 판별

def classify_age(age_range: str) -> str:
    """카카오 age_range → 연령 카테고리"""
    if age_range in ("1~9",):
        return "child"        # 확실한 14세 미만
    elif age_range in ("10~14",):
        return "maybe_child"  # 14세 미만일 수 있음 → 보수적 처리
    elif age_range in ("15~19",):
        return "teenager"     # 14~18세
    else:
        return "adult"        # 19세 이상
```

**`10~14` 범위 처리**: 10~13세(14세 미만)와 14세가 섞여있으므로, **보수적으로 14세 미만으로 간주**하여 법정대리인 동의 요구.

#### 14세 미만: 법정대리인 동의 필수

```
[14세 미만 가입 플로우]

1. 카카오 로그인 → age_range 확인 → "child" 또는 "maybe_child"
2. "보호자 동의가 필요합니다" 안내 표시
3. 보호자 연락처 입력 (이름 + 이메일 또는 전화번호)
   ※ 법정대리인 동의를 위한 최소 정보는 아동에게 직접 수집 가능 (법 예외)
4. 보호자에게 동의 요청 발송 (이메일 또는 SMS)
5. 보호자가 링크 클릭 → 카카오 로그인
6. 보호자 age_range 확인 → "adult" (20세 이상)인지 검증
7. 보호자 동의 화면:
   - 자녀 이름 확인
   - 수집 항목/목적/기간 고지
   - "동의합니다" 체크 + 확인
8. 동의 완료 → 아동 가입 진행
   - consent_logs에 guardian_consent 기록
   - members.guardian_member_id 설정

미동의 시: 가입 불가 (7일 후 임시 데이터 삭제)
```

**법정대리인 동의 확인 방법** (시행령 제17조의2):

| 방법 | 구현 계획 | 우선순위 |
|------|---------|:---:|
| 이메일 발송 + 회신 확인 | Phase 1에서 구현 | 1순위 |
| SMS 발송 + 인증번호 | Phase 2에서 구현 | 2순위 |
| 카카오톡 링크 + 로그인 동의 | Phase 2에서 구현 | 2순위 |

#### 14~18세 미성년자: Player Claim 시 보호자 동의

```
[14~18세 선수 Player Claim 플로우]

1. 선수가 Player Claim 신청
2. age_range로 미성년자 확인 → "보호자 동의가 필요합니다"
3. 보호자 카카오 링크 발송 (선수가 보호자 연락처 입력)
4. 보호자가 카카오 로그인:
   a) age_range 확인 → "adult" (20세 이상)
   b) "자녀의 대회 데이터 연동에 동의합니다" 체크
   c) 이 과정에서 보호자 계정 자동 생성 + 자녀 연결
5. 보호자 동의 완료 → Claim 승인 절차 진행

보호자가 응답 안 하면:
  → 7일 후 만료, 재발송 가능 (최대 3회)
  → 코치가 가입된 클럽이면 코치에게 대안 요청

보호자 연락처 위변조 방지:
  → 보호자 본인이 카카오 로그인해야 동의 효력 발생
  → 보호자 age_range가 "adult"여야 함
  → 임의의 제3자가 "동의"해도 동기가 없음
```

#### 미성년자 데이터 특칙

- 법정대리인은 언제든 아동의 개인정보 **열람/삭제 요구** 가능
- 아동이 성인이 된 후 삭제 요청 시 즉시 파기
- 개인정보처리방침에 **아동 개인정보 처리** 섹션 필수 기재 (2025 개정)

### 9.4 개인정보처리방침 필수 항목

**법 제30조에 따라 서비스 오픈 전 반드시 공개해야 한다.**

| # | 항목 | FencingMind 내용 |
|:-:|------|-----------------|
| 1 | 개인정보의 처리 목적 | 회원 관리, 대회 데이터 제공, 클럽 관리, 미성년자 보호 |
| 2 | 처리 및 보유 기간 | 탈퇴 시까지, 법정 보존 기간 별도 명시 |
| 3 | 제3자 제공 | 카카오(OAuth), Stripe(결제) 등 |
| 4 | 처리 위탁 | Supabase(DB 호스팅), 이메일 발송 업체 |
| 5 | 정보주체 권리와 행사 방법 | 열람/정정/삭제/처리정지 요구 방법 |
| 6 | 처리하는 개인정보 항목 | 필수: 이름, 이메일, 생년월일 / 선택: 전화번호, 소속팀 |
| 7 | 파기 절차 및 방법 | 탈퇴 즉시(5일 이내) 복구 불가능한 방법으로 삭제 |
| 8 | 개인정보 보호책임자(CPO) | 대표 겸직, 성명/직책/이메일/전화번호 기재 |
| 9 | 자동 수집 장치 (쿠키) | 쿠키 사용 여부, 거부 방법 |
| 10 | **14세 미만 아동의 개인정보 처리** | 법정대리인 동의 방법, 아동 친화적 방침 (2025 개정 필수) |
| 11 | 안전성 확보 조치 | HTTPS, Supabase RLS, 접근 권한 관리 |
| 12 | 처리방침 변경 | 변경 시 7일 전 공지, 시행일 명시 |
| **추가** | **공개 대회 데이터 수집 근거** | 정당한 이익(제15조 1항 6호), 삭제 요청(opt-out) 처리 절차 |
| **추가** | **국외 이전** | Supabase 데이터센터 위치, 위탁 업체명 명시 |

### 9.5 데이터 접근 제어

```
비로그인 사용자:
  대회별 결과 페이지    → 실명 + 소속팀 + 결과 (원본 공개 수준과 동일)
  선수 프로필 페이지    → 접근 불가 (로그인 유도)

로그인 회원 (Tier 0-1):
  선수 검색            → 이름으로 검색 가능 (이용약관 동의 기반)
  선수 프로필           → 이름 + 소속팀 + 대회 목록 (요약)

본인인증 회원 (Tier 2+):
  선수 프로필           → 대회 이력 + 무기 + 성적 요약

Claim한 본인 (Tier 3):
  본인 데이터           → 전체 전적, H2H, 랭킹 추이, 성과 분석

코치 (Tier 3):
  소속 클럽 선수        → 전체 전적, 출석, 성과 분석

관리자:
  모든 데이터           → 전체 접근 + 심사 기능
```

### 9.6 증빙 서류 보안

- 사업자등록증, 자격증 등은 Supabase Storage에 암호화 저장
- RLS로 업로더 본인 + 관리자만 접근
- 인증 승인 후 90일 뒤 자동 삭제
- 서류에서 주민등록번호 등 민감 정보 감지 시 경고 (업로드 차단은 아님)

### 9.7 데이터 파기 절차

| 상황 | 파기 기한 | 방법 |
|------|---------|------|
| 회원 탈퇴 | 5일 이내 | DB 레코드 삭제 (복구 불가) |
| 보유 기간 경과 | 5일 이내 | DB 레코드 삭제 |
| 비회원 삭제 요청 | 10일 이내 | 본인확인 → 삭제 → 통보 → 로그 |
| Claim 연동 해제 | 즉시 | members.player_id = NULL, 분석 데이터 삭제 |
| 증빙 서류 | 승인 후 90일 | Storage에서 삭제 |

**법정 보존 예외** (분리 보관 후 기간 종료 시 파기):
- 전자상거래법: 계약/결제 기록 5년
- 전자상거래법: 소비자 불만 처리 기록 3년
- 통신비밀보호법: 로그인 기록 3개월

### 9.8 실무 준수 체크리스트

```
[즉시 필요 — 서비스 오픈 전] ──────────────────────────────
[ ] 개인정보처리방침 작성 및 웹사이트 공개 (법 제30조)
[ ] 회원가입 시 필수/선택 동의 분리 UI 구현 (법 제16조)
[ ] 동의서에 4가지 필수 고지사항 포함 (목적, 항목, 기간, 거부권)
[ ] 동의 기록(consent_logs) 테이블 생성 및 기록 시작
[ ] CPO 지정 (대표 겸직) 및 방침에 기재
[ ] HTTPS 적용 확인 (이미 Cloudflare 적용)
[ ] Supabase RLS 정책으로 접근 권한 제어
[ ] 대회 데이터 수집 근거를 이용약관에 명시

[Claim 기능 출시 전] ──────────────────────────────────────
[ ] Player Claim 시 별도 동의 절차 구현
[ ] Claim 철회(연동 해제) 기능 구현
[ ] 미성년자 Claim 시 보호자 동의 연동
[ ] 비회원 선수의 삭제 요청 처리 절차 수립

[14세 미만 가입 지원 시] ──────────────────────────────────
[ ] 법정대리인 동의 프로세스 구현 (이메일 또는 SMS)
[ ] 개인정보처리방침에 아동 개인정보 처리 섹션 추가
[ ] 보호자의 열람/삭제 요구 처리 기능

[운영 중 정기 관리] ────────────────────────────────────────
[ ] 개인정보 파기 정기 점검 (분기 1회)
[ ] 개인정보처리방침 변경 시 7일 전 공지
[ ] 접속 기록(로그) 6개월 이상 보관 설정
[ ] 삭제 요청 처리 결과 기록 보관
```

### 9.9 위반 시 주요 제재

| 위반 유형 | 제재 |
|-----------|------|
| 동의 없이 개인정보 수집 | 5,000만원 이하 과태료 |
| 선택 동의 거부로 서비스 거부 | 3,000만원 이하 과태료 |
| 개인정보처리방침 미공개 | 5,000만원 이하 과태료 |
| CPO 미지정 | 1,000만원 이하 과태료 |
| 안전성 확보조치 미이행 | 매출 3% 이하 과징금 |
| 14세 미만 법정대리인 동의 미획득 | 5,000만원 이하 과태료 |
| 개인정보 유출 (고의/중과실) | 매출 최대 10% 과징금 (2025 개정) |

※ 소기업 감경: 기준금액의 30% 이내 감경 가능

---

## 10. 구현 우선순위 및 Phase 분할

### Phase 1: Player Claim MVP (4주)
**목표**: 선수가 대회 데이터를 찾아 연결할 수 있다

| 주차 | 작업 | 파일 |
|------|------|------|
| 1 | Migration 013 작성 + player_claims, member_organizations 테이블 생성 | `database/migrations/013_verification_system.sql` |
| 1 | members.verification_tier, data_linked_at, trust_level 컬럼 추가 | 위 파일 |
| 2 | Player 검색 API (account 서비스에서 players 테이블 조회) | `services/account/app/claims/player.py` |
| 2 | Player Claim API (생성 + 자동 매칭 로직) | 위 파일 |
| 3 | Claim 상태 조회 + 대시보드 UI | `templates/account/claims.html` |
| 3 | Verification tier 자동 계산 로직 | `services/account/app/verification/tier.py` |
| 4 | 테스트 + 파일럿 (최병철펜싱클럽 선수 5명) | `tests/` |

**Phase 1 완료 기준**: 선수가 가입 → 이름으로 검색 → Claim → 자동 승인 → 대회 전적 조회

### Phase 2: Organization Claim + Invitation (3주)
**목표**: 감독이 클럽을 인증하고, 코치를 초대할 수 있다

| 주차 | 작업 |
|------|------|
| 5 | 사업자등록증 3-Layer 자동 검증 파이프라인 구현 |
|   | - `packages/shared_core/utils/brn_validator.py` (체크디짓) |
|   | - `packages/shared_core/utils/nts_client.py` (국세청 API) |
|   | - `services/account/app/verification/processor.py` (Gemini 프롬프트 추가) |
|   | - data.go.kr NTS API 키 발급 + `NTS_API_KEY` 환경변수 |
| 5 | Organization Claim API + 감독 인증 → club_settings 자동 생성 |
| 6 | Invitation API (초대 생성/수락/거부) |
| 6 | 초대 링크 카카오톡/이메일 발송 |
| 7 | 관리자 Claim 심사 대시보드 (자동 검증 실패 건만) |

**Phase 2 완료 기준**: 관장 → 사업자등록증 업로드 → 자동 검증 → 클럽 관리 권한 + Club 서비스 자동 등록 → 코치 초대 → 코치 수락

### Phase 3: Family + Coach Confirmation (3주)
**목표**: 학부모-자녀 연결, 코치가 Player Claim 확인

| 주차 | 작업 |
|------|------|
| 8 | 학부모 초대 플로우 (코치 → 학부모) |
| 8 | 학부모 직접 신청 플로우 |
| 9 | 코치 Player Claim 확인 UI (club 서비스) |
| 9 | 미성년자 보호 정책 강화 (14세 미만 차단) |
| 10 | 가족 관리 대시보드 (학부모용) |

**Phase 3 완료 기준**: 코치가 학부모 초대 → 학부모 가입 → 자녀 연결 → 자녀 데이터 조회

### Phase 4: Data Corrections + Trust (2주)
**목표**: 데이터 수정 요청 + 신뢰 등급 시스템

| 주차 | 작업 |
|------|------|
| 11 | Data Correction API + 자동 해결 로직 |
| 11 | 관리자 수정 요청 리뷰 UI |
| 12 | Trust Level 자동 승급 로직 |
| 12 | 알림 시스템 연동 (카카오톡) |

---

## 11. 기술적 의존성 및 리스크

### 의존성

| 의존 항목 | 현재 상태 | 필요 조치 |
|----------|----------|----------|
| Gemini API | ✅ 구현됨 (사진 인증) | 사업자등록증 OCR 프롬프트 추가 |
| 국세청 NTS API | ❌ 미연동 | data.go.kr에서 API 키 발급 (무료), `NTS_API_KEY` 환경변수 추가 |
| PlayerIdentityResolver | ✅ data 서비스에 존재 | account 서비스에서 검색 API로 노출 |
| 카카오톡 알림 | ✅ messenger 모듈 구현됨 | 초대/알림에 활용 |
| Supabase Storage | ✅ 사진 업로드 사용 중 | 사업자등록증 이미지 업로드에 확장 |
| Stripe 결제 | ✅ 구현됨 | 직접 의존 없음 |
| Club 서비스 | ❌ 미구현 (data에 임시) | 감독 인증 시 club_settings 자동 생성, 온보딩 플로우 구현 |

### 리스크

| 리스크 | 확률 | 영향 | 완화 방안 |
|--------|------|------|----------|
| 동명이인 자동 매칭 오류 | 중 | 🔴 높음 | 자동 매칭 임계값 높게 (≥0.85), "잘못된 매칭 신고" 기능 |
| 두 사용자가 같은 선수 Claim | 낮 | 🟡 중간 | UNIQUE 인덱스 + 먼저 승인된 Claim 우선 |
| 클럽 관장 인증 지연 (수동 심사) | 중 | 🟡 중간 | 파일럿 클럽(최병철펜싱클럽)은 직접 처리, 이후 자동화 |
| 학부모 사칭 위험 | 낮 | 🔴 높음 | 코치 확인 필수, 코치 확인 없이 데이터 접근 불가 |
| 개인정보보호법 위반 | 낮 | 🔴 높음 | 개인정보처리방침 사전 업데이트, 동의 절차 추가 |
| 관리자 리뷰 병목 | 중 | 🟡 중간 | 자동 해결 최대화 (90% 목표), 수동은 5%만 |

---

## 12. 성공 지표 (KPIs)

| 지표 | Phase 1 목표 | Phase 4 목표 |
|------|------------|------------|
| Player Claim 완료율 | 파일럿 5명 100% | 등록 선수의 30% |
| 자동 매칭 성공률 | 70% | 85% |
| Claim → 승인 평균 시간 | 24시간 | 1시간 |
| 클럽 인증 완료 | 1개 (파일럿) | 10개 |
| 학부모 연결 완료 | - | 파일럿 클럽 50% |
| 데이터 수정 요청 처리율 | - | 95% (30일 내) |

---

## Appendix A: 벤치마킹 참고

| 플랫폼 | 채택 요소 | 적용 방식 |
|--------|----------|----------|
| **AskFRED** | USFA 번호 교차검증 | 대한체육회 선수등록번호 활용 |
| **ClassDojo** | 코드 + 교사 승인 이중 인증 | 코치 초대 + 코치 확인 |
| **TeamSnap** | Shared Access 초대 | 학부모 초대 플로우 |
| **GitHub Org** | Owner → Role 계층 | 관장 → 코치 → 보조 계층 |
| **대한체육회** | 2단계 조직 승인 | 클럽 소유권 인증 |
| **LinkedIn** | 이메일 기반 재직 인증 | 소속 이메일 보조 인증 |
| **FencingTracker** | (반면교사) Claim 없음 | FencingMind의 차별화 포인트 |

## Appendix B: 관련 코드 참조

| 컴포넌트 | 파일 | 설명 |
|----------|------|------|
| MemberType enum | `packages/shared_core/types/member.py:9-17` | 변경 불필요 |
| ServiceMemberContext | `packages/shared_core/auth/dependencies.py:31-97` | verification_tier, trust_level 추가 |
| GeminiVerifier | `services/account/app/verification/processor.py` | 사업자등록증 OCR 프롬프트 추가 |
| PlayerIdentityResolver | `services/data/app/player_identity.py` | 검색 API로 노출 |
| GuardianLink | `packages/shared_core/auth/models.py:64-68` | 가족 관리 확장 |
| Dashboard template | `services/account/templates/account/dashboard.html` | Tier 표시 + Claim UI |
| Registration flow | `services/account/app/auth/router.py` | Tier 0 자동 설정 |
| BRN Validator (NEW) | `packages/shared_core/utils/brn_validator.py` | 사업자등록번호 체크디짓 검증 |
| NTS Client (NEW) | `packages/shared_core/utils/nts_client.py` | 국세청 진위확인 API 클라이언트 |
| Org Claim handler (NEW) | `services/account/app/claims/organization.py` | 감독 인증 + club_settings 자동 생성 |
