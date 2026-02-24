# FencingMind Club Service - PRD & 개발계획서 v2.0

**작성일:** 2026-02-24
**서비스:** app.fencingmind.ai (포트 72)
**파일럿:** 최병철펜싱클럽 (org_id: 401)
**목표:** 펜싱 클럽/학원 운영에 필요한 모든 기능을 제공하는 SaaS 플랫폼

---

## 목차

1. [현재 상태 요약](#1-현재-상태-요약)
2. [역할별 기능 매트릭스](#2-역할별-기능-매트릭스)
3. [페이지 구성 (역할별)](#3-페이지-구성-역할별)
4. [Phase 3: 계정 연동 & 역할별 최적화](#4-phase-3-계정-연동--역할별-최적화)
5. [Phase 4: 핵심 비즈니스 기능](#5-phase-4-핵심-비즈니스-기능)
6. [Phase 5: 고급 기능](#6-phase-5-고급-기능)
7. [Phase 6: UI/UX 전면 개선](#7-phase-6-uiux-전면-개선)
8. [데이터 동기화 아키텍처](#8-데이터-동기화-아키텍처)
9. [기술 부채 해소](#9-기술-부채-해소)
10. [구현 우선순위 로드맵](#10-구현-우선순위-로드맵)

---

## 1. 현재 상태 요약

### 1.1 완료된 기능

| 기능 | 모듈 | 상태 | 비고 |
|------|------|------|------|
| 코치 대시보드 | `club/router.py` | ✅ 코드 완성 | TEST_MODE=true 고정 |
| 학생 대시보드 | `dashboard_student.html` | ✅ 템플릿 있음 | 라우트 미연결 |
| IP 기반 체크인 | `club/router.py` | ✅ 코드 완성 | 실 운영 0건 |
| 회원 관리 | `club/router.py` | ✅ 동작 | 64명 등록 |
| 선수 데이터 연동 | `club/players/` | ✅ 동작 | N+1 HTTP 문제 |
| 비용 관리 (Legacy) | `club/router.py` | ✅ 코드 완성 | owner 전용, 5건 |
| 레슨 관리 | `club/router.py` | ✅ 코드 완성 | 실 운영 0건 |
| 결제/청구 | `billing/` | ✅ 코드 완성 | UI 없음, 미테스트 |
| 알림 | `notifications/` | ✅ 코드 완성 | 알림톡 미연동 |
| 스케줄러 | `schedule/` | ✅ 동작 확인 | 테스트 8건 |
| PWA | `sw.js` | ✅ 설정 완료 | - |
| shared_core 인증 | `dependencies.py` | ✅ 연동 완료 | JWT + Supabase Auth |

### 1.2 핵심 문제점

| 문제 | 심각도 | 상세 |
|------|--------|------|
| **TEST_MODE=true 고정** | 🔴 | 모든 템플릿에서 `const TEST_MODE = true` 하드코딩. 인증 우회됨 |
| **랜딩 페이지 없음** | 🔴 | `/` 접속 시 빈 페이지. 로그인/비로그인 구분 없음 |
| **역할별 페이지 분기 없음** | 🔴 | 감독/코치/선수/학부모 모두 같은 화면 |
| **CSS 불일치** | 🟡 | `dark-theme.css` 정의 ≠ 템플릿 인라인 스타일 (라이트 테마) |
| **데이터 동기화 없음** | 🟡 | players 테이블 정적, 자동 갱신 없음 |
| **billing UI 없음** | 🟡 | API만 존재, 프론트엔드 없음 |
| **알림톡 미구현** | 🟡 | 코드 존재하나 실제 발송 안 됨 |
| **자동 스케줄러 없음** | 🟡 | 반복 청구, 연체 확인 등 수동 호출 필요 |

---

## 2. 역할별 기능 매트릭스

### 2.1 역할 정의

```
ClubRole 계층:
  owner (감독/대표) ─── 최고 권한, 재정/인사 관리
  head_coach (수석코치) ─── 코치 관리, 훈련 총괄
  coach (코치) ─── 레슨/출석/스케줄 관리
  assistant (보조코치) ─── 제한적 코치 기능
  staff (행정) ─── 재정/행정 지원
  student (선수/수강생) ─── 체크인, 레슨, 본인 정보
  parent (학부모) ─── 자녀 정보 열람, 결제

MemberType (계정 유형):
  player ─────── 성인 선수 (18세 이상, 직접 가입, 본인 결제)
  minor_player ── 미성년 선수 (18세 미만, 본인 계정, guardian 필수)
  player_parent ─ 학부모 (미성년 자녀 결제/관리 담당)
  club_coach ──── 코치
  general ─────── 일반 회원
```

### 2.1.1 미성년 선수 (minor_player) 계정 구조

```
모든 미성년 선수는 본인 스마트폰으로 서비스를 사용한다.

┌─────────────────────────────────────────────────────────────┐
│ 미성년 선수 (minor_player)                                   │
│ 예: 박소윤 (13세, U14 여자 플뢰레)                           │
│                                                             │
│ ■ 본인 계정:                                                 │
│   - 카카오 로그인 (본인 폰)                                  │
│   - MemberType: minor_player                                │
│   - ClubRole: student                                       │
│   - guardian_member_id → 박소윤 어머니 (player_parent)       │
│                                                             │
│ ■ 할 수 있는 것:                                            │
│   ✅ 체크인 / 체크아웃 (IP, QR, GPS)                         │
│   ✅ 내 스케줄 확인 (정규 훈련, 레슨)                        │
│   ✅ 코치 빈 시간 확인 & 레슨 신청                           │
│   ✅ 내 대회 성적 / 상대 전적 확인                           │
│   ✅ 공지사항 열람                                           │
│   ✅ 내 출석 기록 확인                                       │
│   ✅ 내 레슨 잔여 회수 확인                                  │
│   ✅ 영상 등록 & 코치 코멘트 확인                            │
│   ✅ 대회 출전 의사 표시 ("출전할게요" / "안 할게요")         │
│   ✅ 알림 수신 (카카오톡, 앱 내)                             │
│                                                             │
│ ■ 할 수 없는 것 (→ 학부모가 처리):                          │
│   ❌ 결제 (카드/이체) — 학부모 계정으로 청구                  │
│   ❌ 청구서 열람 — 학부모만 확인                              │
│   ❌ 레슨 패키지 구매 — 학부모가 구매                        │
│   ❌ 회원 정보 수정 (전화번호, 주소 등) — 학부모/감독만       │
│                                                             │
│ ■ 연결된 학부모:                                             │
│   ┌──────────────────────────────────────────┐              │
│   │ 학부모 (player_parent)                    │              │
│   │ 박소윤 어머니                              │              │
│   │                                          │              │
│   │ - 자녀 정보 열람 (출석, 레슨, 성적)       │              │
│   │ - 결제 담당 (월회비, 레슨비, 대회비)       │              │
│   │ - 자녀 대리 레슨 신청 가능                │              │
│   │ - 자녀 대리 대회 출전 확인 가능            │              │
│   │ - 다자녀 지원 (자녀 선택 드롭다운)         │              │
│   └──────────────────────────────────────────┘              │
└─────────────────────────────────────────────────────────────┘

■ 가입 플로우:
  1. 감독이 회원 등록 시 계정 유형 직접 선택 (minor_player)
  2. 학부모 계정 동시 생성 (또는 기존 학부모 계정에 연결)
  3. guardian_member_id로 양방향 연결
  4. 미성년 선수: 본인 카카오로 로그인 → ClubRole: student
  5. 학부모: 본인 카카오로 로그인 → ClubRole: parent

■ 성인 전환:
  감독이 회원 관리에서 member_type을 player로 수동 변경
  → 본인 결제 가능, guardian 연결 유지 (선택)
```

### 2.2 기능별 권한 매트릭스

| 기능 | owner | head_coach | coach | assistant | staff | student (성인) | student (미성년) | parent |
|------|:-----:|:----------:|:-----:|:---------:|:-----:|:-------------:|:---------------:|:------:|
| **클럽 정보 관리** | ✏️ | 👁️ | 👁️ | 👁️ | 👁️ | 👁️ | 👁️ | 👁️ |
| **회원 등록/삭제** | ✅ | ✅ | ❌ | ❌ | ✅ | ❌ | ❌ | ❌ |
| **회원 역할 변경** | ✅ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ |
| **선수 인증 승인** | ✅ | ✅ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ |
| **전체 출석 조회** | ✅ | ✅ | ✅ | ✅ | ✅ | ❌ | ❌ | ❌ |
| **체크인/체크아웃** | ❌ | ❌ | ❌ | ❌ | ❌ | ✅ | ✅ | ❌ |
| **본인 출석 조회** | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | 자녀만 |
| **스케줄 생성** | ✅ | ✅ | 본인만 | ❌ | ❌ | ❌ | ❌ | ❌ |
| **스케줄 수정** | 전체 | 전체 | 본인만 | ❌ | ❌ | ❌ | ❌ | ❌ |
| **스케줄 조회** | 전체 | 전체 | 전체 | 전체 | 전체 | 코치빈칸만 | 코치빈칸만 | 자녀만 |
| **레슨 생성** | ✅ | ✅ | 본인만 | ❌ | ❌ | ❌ | ❌ | ❌ |
| **레슨 신청** | ❌ | ❌ | ❌ | ❌ | ❌ | ✅ | ✅ | 자녀대리 |
| **레슨 승인** | ✅ | ✅ | 본인만 | ❌ | ❌ | ❌ | ❌ | ❌ |
| **레슨 차감 조회** | ✅ | ✅ | 담당만 | ❌ | ✅ | 본인만 | 본인만 | 자녀만 |
| **청구서 생성** | ✅ | ❌ | ❌ | ❌ | ✅ | ❌ | ❌ | ❌ |
| **결제 (카드)** | ❌ | ❌ | ❌ | ❌ | ❌ | ✅ | ❌ →학부모 | ✅ |
| **청구서 열람** | ✅ | ❌ | ❌ | ❌ | ✅ | 본인만 | ❌ →학부모 | 자녀분 |
| **결제 (현금 확인)** | ✅ | ❌ | ❌ | ❌ | ✅ | ❌ | ❌ | ❌ |
| **재정 리포트** | ✅ | ❌ | ❌ | ❌ | ✅ | ❌ | ❌ | ❌ |
| **대회 이벤트 생성** | ✅ | ✅ | ✅ | ❌ | ❌ | ❌ | ❌ | ❌ |
| **대회 출전 확인** | ✅ | ✅ | ✅ | ❌ | ❌ | ✅ | ✅ | 자녀대리 |
| **선수 성적 조회** | ✅ | ✅ | ✅ | ✅ | ❌ | 본인만 | 본인만 | 자녀만 |
| **영상 등록/코멘트** | ✅ | ✅ | ✅ | ❌ | ❌ | 본인만 | 본인만 | 자녀만 |
| **공지사항 작성** | ✅ | ✅ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ |
| **공지사항 열람** | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| **알림 설정** | ✅ | 본인 | 본인 | 본인 | 본인 | 본인 | 본인 | 본인 |
| **빈 레슨 알림 수신** | ❌ | ❌ | ❌ | ❌ | ❌ | 설정시 | 설정시 | 설정시 |
| **클럽 설정 변경** | ✅ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ |

> **범례:** ✅ 가능 / ❌ 불가 / ✏️ 편집 / 👁️ 열람 / 본인만 = 자기 데이터만 / 자녀만 = guardian 연결된 자녀만 / ❌ →학부모 = 미성년 불가, 학부모 계정에서 처리

---

## 3. 페이지 구성 (역할별)

### 3.1 비로그인 상태 (랜딩 페이지)

```
┌────────────────────────────────────────────────────┐
│  ⚔️ FencingMind Club                    [로그인]   │
├────────────────────────────────────────────────────┤
│                                                    │
│  ┌──────────────────────────────────────────────┐  │
│  │         히어로 섹션                           │  │
│  │  "펜싱 클럽 운영의 모든 것, 한 곳에서"       │  │
│  │                                              │  │
│  │  [카카오로 시작하기]  [Google로 시작하기]     │  │
│  └──────────────────────────────────────────────┘  │
│                                                    │
│  ┌─────────┐ ┌─────────┐ ┌─────────┐ ┌─────────┐  │
│  │ 출석관리 │ │ 레슨관리│ │ 성적관리 │ │ 결제관리│  │
│  │ IP/QR   │ │ 스케줄링│ │ 대회연동 │ │ 카드/현금│  │
│  └─────────┘ └─────────┘ └─────────┘ └─────────┘  │
│                                                    │
│  "이미 클럽이 등록되어 있나요?"                    │
│  [클럽 검색] ─────────────────                     │
│                                                    │
│  ── 주요 기능 소개 ──                              │
│  • 실시간 출석 체크인 (IP/QR/GPS)                  │
│  • 대한펜싱협회 대회 데이터 자동 연동              │
│  • 레슨 스케줄 관리 & 코치 예약                    │
│  • 월회비/레슨비/시합출전비 통합 청구              │
│  • 선수별 대회 성적 & 상대 전적 분석               │
│  • 카카오톡 알림                                   │
│                                                    │
│  ── 요금제 ──                                      │
│  [Free]  [Basic ₩9,900]  [Premium ₩29,900]        │
│                                                    │
│  ── Footer ──                                      │
│  FencingMind LLC | 이용약관 | 개인정보처리방침     │
└────────────────────────────────────────────────────┘
```

### 3.2 감독/대표 (owner) 대시보드

```
┌────────────────────────────────────────────────────┐
│  ⚔️ FencingMind Club   [최병철펜싱클럽]  [최병철 ▾]│
├────────────────────────────────────────────────────┤
│  사이드 네비게이션:                                │
│  ┌──────────┐                                      │
│  │ 📊 대시보드 │ ← 현재                           │
│  │ 👥 회원관리  │                                  │
│  │ 📅 스케줄   │                                   │
│  │ 📋 레슨관리  │                                  │
│  │ ✅ 출석관리  │                                  │
│  │ 🏆 대회관리  │                                  │
│  │ 💰 재정관리  │                                  │
│  │ 📢 공지사항  │                                  │
│  │ 🔔 알림설정  │                                  │
│  │ ⚙️ 클럽설정  │                                  │
│  └──────────┘                                      │
│                                                    │
│  메인 영역 (대시보드):                             │
│  ┌────────┐ ┌────────┐ ┌────────┐ ┌────────┐      │
│  │ 오늘출석 │ │ 전체회원│ │ 이번달매출│ │ 미납건수│  │
│  │ 12/28명 │ │ 64명   │ │ ₩3.2M  │ │ 5건    │    │
│  └────────┘ └────────┘ └────────┘ └────────┘      │
│                                                    │
│  ┌─── 오늘 스케줄 ───┐ ┌─── 알림 ─────────────┐   │
│  │ 09:00 정규훈련     │ │ 박소윤 레슨 신청 대기  │  │
│  │ 14:00 김코치 레슨  │ │ 이선수 월회비 미납 7일 │  │
│  │ 16:00 정규훈련     │ │ 3/1 회장배 출전 마감   │  │
│  └───────────────────┘ └───────────────────────┘   │
│                                                    │
│  ┌─── 최근 대회 결과 (자동) ──────────────────┐    │
│  │ 2026 회장배 (2/15) - 우리 클럽 성적:        │   │
│  │   박소윤 U14 여자 플뢰레 🥇 1위             │   │
│  │   김선수 U14 남자 에페 8위                  │    │
│  └────────────────────────────────────────────┘    │
└────────────────────────────────────────────────────┘
```

### 3.3 코치 (coach) 대시보드

```
┌────────────────────────────────────────────────────┐
│  ⚔️ FencingMind Club   [최병철펜싱클럽]  [김코치 ▾]│
├────────────────────────────────────────────────────┤
│  사이드 네비게이션:                                │
│  ┌──────────┐                                      │
│  │ 📊 내 대시보드│                                 │
│  │ 📅 내 스케줄  │ ← 본인 스케줄만 편집           │
│  │ 📋 내 레슨   │ ← 본인 담당 레슨만              │
│  │ ✅ 출석현황   │ ← 조회만 (전체)                 │
│  │ 🏆 대회관리  │ ← 출전 확인/이벤트 생성         │
│  │ 📢 공지사항  │ ← 열람만                        │
│  │ 🔔 알림     │                                   │
│  └──────────┘                                      │
│  ❌ 회원관리 없음                                  │
│  ❌ 재정관리 없음                                  │
│  ❌ 클럽설정 없음                                  │
│                                                    │
│  메인 영역:                                        │
│  ┌────────┐ ┌────────┐ ┌────────┐                  │
│  │ 오늘레슨 │ │ 이번주  │ │ 레슨신청│              │
│  │ 3회     │ │ 12회   │ │ 2건대기 │               │
│  └────────┘ └────────┘ └────────┘                  │
│                                                    │
│  ┌─── 오늘 내 스케줄 ──────────────────────┐       │
│  │ 14:00-15:00 박소윤 레슨 (플뢰레)        │       │
│  │ 15:00-16:00 [빈 시간] ← 대기자 알림 가능│       │
│  │ 16:00-18:00 정규 훈련 지도              │       │
│  └─────────────────────────────────────────┘       │
│                                                    │
│  ┌─── 레슨 신청 대기 ─────────────────────┐        │
│  │ 박소윤: 2/26(수) 14:00 레슨 신청        │       │
│  │ [승인] [거절] [시간변경 제안]            │       │
│  └─────────────────────────────────────────┘       │
└────────────────────────────────────────────────────┘
```

### 3.4 선수/수강생 (student) 대시보드 — 미성년 선수 기준

> **핵심:** 대부분의 선수가 미성년(초등~고등학생)이며, 본인 스마트폰으로 사용.
> 모바일 PWA 최적화가 최우선. 결제 관련 UI는 표시하지 않음.

```
┌────────────────────────────────────────────────────┐
│  ⚔️ FencingMind Club   [최병철펜싱클럽]  [박소윤 ▾]│
│                               member_type: minor   │
├────────────────────────────────────────────────────┤
│                                                    │
│  ┌──────────────────────────────────────────┐      │
│  │           ✅ 체크인                       │      │
│  │        [큰 체크인 버튼]                   │      │
│  │     "오늘 아직 체크인하지 않았습니다"      │      │
│  │                                          │      │
│  │     체크인 시간: --:--                    │      │
│  │     [체크아웃] ← 퇴관 시 누름             │      │
│  └──────────────────────────────────────────┘      │
│                                                    │
│  ┌─── 내 레슨 현황 ───┐ ┌─── 다음 레슨 ────┐      │
│  │ 📋 김코치 레슨      │ │ 2/26(수) 14:00   │      │
│  │ 잔여: 6/20회        │ │ 김코치 플뢰레     │      │
│  │ ████████░░ 70%     │ │ [장소: 피스트 3]  │      │
│  └────────────────────┘ └────────────────────┘     │
│  ※ 결제/구매는 학부모 계정에서 처리됩니다          │
│                                                    │
│  ┌─── 코치 빈 시간 & 레슨 신청 ───────────┐       │
│  │ 김코치: 2/27(목) 15:00 [신청]            │       │
│  │         2/28(금) 14:00 [신청]            │       │
│  │ 이코치: 2/27(목) 14:00 [신청]            │       │
│  │                                         │       │
│  │ ※ 다른 선수 레슨 시간은 "예약됨"으로 표시 │       │
│  │   (누구인지는 비공개)                     │       │
│  └─────────────────────────────────────────┘       │
│                                                    │
│  ┌─── 내 스케줄 (이번 주) ────────────────┐        │
│  │ 월 16:00-18:00 정규 훈련               │        │
│  │ 수 14:00-15:00 김코치 레슨 ← 내 레슨   │        │
│  │ 수 16:00-18:00 정규 훈련               │        │
│  │ 금 16:00-18:00 정규 훈련               │        │
│  └─────────────────────────────────────────┘       │
│                                                    │
│  ┌─── 대회 ──────────────────────────────┐         │
│  │ 📌 3/1 회장배 — 출전 여부 응답 필요     │        │
│  │   [출전합니다] [미출전]                  │        │
│  │                                        │        │
│  │ 🏆 내 최근 성적:                        │        │
│  │   2026 회장배 U14 여자 플뢰레 🥇 1위    │        │
│  └─────────────────────────────────────────┘       │
│                                                    │
│  ┌─── 공지사항 ───────────────────────────┐        │
│  │ [NEW] 3/1 회장배 출전 신청 마감 (2/28)  │       │
│  │ 내일 클럽 휴무 (공휴일)                  │       │
│  └─────────────────────────────────────────┘       │
│                                                    │
│  ┌────┐ ┌────┐ ┌────┐ ┌────┐ ┌────┐               │
│  │ 홈 │ │체크인│ │레슨│ │대회│ │더보기│             │
│  └────┘ └────┘ └────┘ └────┘ └────┘               │
└────────────────────────────────────────────────────┘

※ 성인 선수(player)는 동일 화면 + "내 청구서" 탭 추가
```

### 3.5 학부모 (parent) 대시보드

```
┌────────────────────────────────────────────────────┐
│  ⚔️ FencingMind Club   [최병철펜싱클럽] [박소윤 보호자 ▾]│
├────────────────────────────────────────────────────┤
│                                                    │
│  ┌─── 자녀 정보 ──────────────────────────┐        │
│  │ 👤 박소윤 (U14 여자 플뢰레)             │       │
│  │ 출석: 이번 달 18/22일                   │       │
│  │ 레슨 잔여: 6회 / 20회                   │       │
│  └─────────────────────────────────────────┘       │
│                                                    │
│  ┌─── 결제 현황 ──────────────────────────┐        │
│  │ ⚠️ 미납 청구서                         │        │
│  │ • 3월 월회비 ₩150,000 (3/1 마감)       │        │
│  │   [카드 결제]                           │        │
│  │                                         │       │
│  │ 최근 결제 내역:                         │       │
│  │ • 2월 월회비 ₩150,000 ✅ 2/1 결제      │       │
│  │ • 레슨 10회 (김코치) ₩300,000 ✅ 1/15  │       │
│  └─────────────────────────────────────────┘       │
│                                                    │
│  ┌─── 자녀 레슨 스케줄 ──────────────────┐         │
│  │ 2/26(수) 14:00 김코치 레슨 (14/20회)   │        │
│  │ 2/28(금) 14:00 김코치 레슨 (15/20회)   │        │
│  └─────────────────────────────────────────┘       │
│                                                    │
│  ┌─── 자녀 대회 성적 ────────────────────┐         │
│  │ 최근: 2026 회장배 🥇 1위               │        │
│  └─────────────────────────────────────────┘       │
│                                                    │
│  ┌─── 대회 출전 확인 ────────────────────┐         │
│  │ 3/1 회장배 - 출전 여부: [출전] [미출전] │        │
│  │ 예상 비용: 참가비 ₩30,000 +            │        │
│  │           코치출장비 ₩50,000            │        │
│  └─────────────────────────────────────────┘       │
│                                                    │
│  ┌────┐ ┌────┐ ┌────┐ ┌────┐                      │
│  │ 홈 │ │결제 │ │레슨│ │알림│                      │
│  └────┘ └────┘ └────┘ └────┘                      │
└────────────────────────────────────────────────────┘
```

---

## 4. Phase 3: 계정 연동 & 역할별 최적화

> **목표:** TEST_MODE 제거, 실제 로그인 연동, 역할별 페이지 분기

### 4.1 카카오/Google 로그인 연동

**현재 상태:**
- `shared_core/auth/oauth/` 에 OAuthHandler 구현 완료
- `services/data/app/auth/router.py`에 로그인/콜백/회원가입 라우트 존재 (포트 71)
- club 서비스(포트 72)에는 auth 라우트 없음

**구현 방향:**
```
선택지 A: club 서비스에 자체 auth 라우트 추가 (독립적)
선택지 B: account 서비스(포트 70)로 중앙화하고 리다이렉트
→ 선택지 B 권장 (SSO 원칙)
```

**플로우:**
```
1. 유저 → app.fencingmind.ai/ (club 랜딩)
2. [카카오 로그인] 클릭
3. → account.fencingmind.ai/auth/login/kakao?redirect=app.fencingmind.ai/
4. 카카오 인증 완료
5. → account 서비스: JWT 발급, access_token 쿠키 설정
6. → app.fencingmind.ai/ 리다이렉트 (쿠키에 JWT 포함)
7. club 서비스: JWT 검증 → 역할별 대시보드 렌더링
```

**구현 항목:**
- [ ] `services/club/app/auth/router.py` 생성 — 로그인 페이지, 로그아웃, 회원가입 리다이렉트
- [ ] `base.html` 네비바 — 로그인/프로필 버튼 추가
- [ ] JWT에서 `club_role` 추출 → 프론트엔드 전달
- [ ] TEST_MODE 기본값 `false`로 변경 (개발 시만 `?test=1`)
- [ ] 쿠키 기반 인증 → `access_token` httponly 쿠키 읽기

### 4.2 역할별 페이지 라우팅

```python
# services/club/app/club/router.py 수정안

@router.get("/", response_class=HTMLResponse)
async def club_home(request: Request):
    """역할별 대시보드 분기"""
    member = await try_get_member(request)  # 인증 실패 시 None

    if not member:
        # 비로그인 → 랜딩 페이지
        return templates.TemplateResponse("club/landing.html", {"request": request})

    # 역할별 대시보드
    role = member.club_role.value if member.club_role else "student"

    if role in ("owner", "head_coach"):
        template = "club/dashboard_owner.html"
    elif role in ("coach", "assistant"):
        template = "club/dashboard_coach.html"
    elif role == "parent":
        template = "club/dashboard_parent.html"
    else:  # student, staff
        template = "club/dashboard_student.html"

    return templates.TemplateResponse(template, {
        "request": request,
        "user": member,
        "user_role": role,
    })
```

**구현 항목:**
- [ ] `try_get_member()` 헬퍼 — 인증 실패 시 None 반환 (403 대신)
- [ ] `templates/club/landing.html` — 비로그인 랜딩 페이지
- [ ] `templates/club/dashboard_owner.html` — 감독 전용 대시보드
- [ ] `templates/club/dashboard_parent.html` — 학부모 전용 대시보드
- [ ] 기존 `dashboard_coach.html`, `dashboard_student.html` 리팩토링
- [ ] 모든 템플릿에서 `TEST_MODE = true` 제거 → 서버에서 주입

### 4.3 미성년 선수 계정 & 학부모 연동

**설계 원칙:**
- 미성년 선수는 **반드시 본인 계정**이 있어야 함 (체크인/스케줄/레슨 신청)
- 결제/청구는 **학부모 계정**으로 전달
- `member_type = "minor_player"` + `guardian_member_id` 필수

**현재 상태:**
- `members.guardian_member_id` 컬럼 존재
- `members.member_type` 컬럼 존재
- `MemberType.MINOR_PLAYER` 추가 완료 (shared_core)
- `ServiceMemberContext.is_minor()`, `.can_make_payment()` 메서드 추가 완료

**회원 등록 플로우 (감독이 등록):**
```
감독이 신규 회원 등록 시:

1. 회원 정보 입력
   ┌────────────────────────────────────────────┐
   │ 이름: [박소윤        ]                      │
   │ 연락처: [010-xxxx-xxxx ]                    │
   │ 무기: [플뢰레 ▾]                            │
   │                                            │
   │ 계정 유형:  ← 감독이 직접 선택              │
   │ ○ 성인 선수 (player)                       │
   │ ● 미성년 선수 (minor_player)               │
   │ ○ 학부모 (player_parent)                   │
   │ ○ 코치 (club_coach)                        │
   │ ○ 일반 (general)                           │
   └────────────────────────────────────────────┘

2. "미성년 선수" 선택 시 → 학부모 연결 UI 표시
   ┌────────────────────────────────────────────┐
   │ ⚠️ 미성년 선수는 학부모 연결이 필수입니다    │
   │                                            │
   │ 학부모 연결:                                │
   │ ○ 기존 학부모 선택: [박소윤 어머니 ▾]      │
   │ ○ 새 학부모 등록:                          │
   │   이름: _________ 연락처: _________        │
   │                                            │
   │ [등록]                                     │
   └────────────────────────────────────────────┘

   ※ 감독이 본인 클럽 선수를 직접 등록하므로
     미성년 여부를 시스템이 자동 판별할 필요 없음.
     감독이 아는 정보 기반으로 직접 선택.

3. 미성년 선수 → members INSERT (member_type: "minor_player", club_role: "student")
4. 학부모 → members INSERT (member_type: "player_parent", club_role: "parent")
5. guardian_member_id 양방향 연결
```

> **참고 (클럽 서비스 범위 밖):**
> 클럽에 소속되지 않은 일반 선수가 FencingMind에 직접 가입할 때의
> 미성년 판별은 account 서비스(포트 70) 범위에서 별도 설계 필요.
> (예: 선수인증 시 생년월일 수집, 대회 데이터의 age_group 참조 등)

**미성년 선수 로그인 → 서비스 사용:**
```
1. 박소윤 (13세) → 본인 스마트폰으로 카카오 로그인
2. JWT 발급 (member_type: "minor_player", club_role: "student")
3. 대시보드 진입 → student 화면 (결제 메뉴 숨김)
4. 체크인 → ✅ 가능 (본인 IP/QR/GPS로)
5. 레슨 신청 → ✅ 가능 (코치에게 직접 신청)
6. 결제 필요 → "학부모님에게 결제 알림이 발송됩니다" 메시지
   → 학부모(박소윤 어머니)에게 카카오톡 결제 안내 발송
```

**API 분기 로직:**
```python
# 결제 관련 API에서
@router.post("/api/billing/pay")
async def pay_invoice(member = Depends(get_current_club_member)):
    if member.is_minor():
        raise HTTPException(403, "미성년 선수는 결제할 수 없습니다. 학부모 계정에서 결제해주세요.")

# 레슨 신청 API에서
@router.post("/api/lessons/request")
async def request_lesson(data, member = Depends(get_current_club_member)):
    # 미성년도 직접 레슨 신청 가능
    if member.can_request_lesson():
        requested_by = member.member_id
        # 미성년이면 학부모에게도 알림
        if member.is_minor() and member.guardian_member_id:
            notify_parent(member.guardian_member_id, "자녀가 레슨을 신청했습니다")
```

**구현 항목:**
- [ ] 회원 등록 UI — 나이 기반 `minor_player` 자동 판별
- [ ] 회원 등록 시 학부모 동시 생성/연결 UI
- [ ] 학부모 로그인 → 자녀 자동 표시 (guardian_member_id 역참조)
- [ ] 학부모 대시보드에 자녀 선택 드롭다운 (다자녀 지원)
- [ ] 미성년 대시보드에서 결제/청구 UI 숨김
- [ ] 결제 필요 시 학부모에게 카카오톡 알림 자동 발송
- [ ] 학부모 → 자녀 레슨 신청 대리
- [ ] 학부모 → 자녀 대회 출전 확인 대리
- [ ] 미성년 레슨 신청 시 학부모 알림 동시 발송
- [ ] 감독이 회원 관리에서 member_type 변경 (minor_player → player) 기능

### 4.4 코치별 스케줄 권한 분리

**핵심 규칙:** 코치는 자기 스케줄만 생성/수정/삭제 가능

```python
# schedule/router.py 수정안

@router.post("/events")
async def create_event(data: ScheduleCreate, member = Depends(require_coach)):
    # 코치는 자기 자신만 assigned_coach_id로 설정 가능
    if member.club_role.value == "coach":
        data.assigned_coach_id = member.member_id  # 강제
    # owner/head_coach는 모든 코치에 할당 가능

@router.put("/events/{event_id}")
async def update_event(event_id: str, data: ScheduleUpdate, member = Depends(require_coach)):
    existing = schedule_service.get_event(event_id, member.organization_id)
    # 코치는 본인 이벤트만 수정 가능
    if member.club_role.value == "coach":
        if existing.get("assigned_coach_id") != member.member_id:
            raise HTTPException(403, "본인 스케줄만 수정할 수 있습니다")
```

**선수의 코치 스케줄 조회 규칙:**
- 선수는 코치별 빈 시간/레슨 시간만 볼 수 있음
- 다른 선수의 레슨 내용(누가 레슨인지)은 보이지 않음
- 자기 레슨만 상세 내용 확인 가능

---

## 5. Phase 4: 핵심 비즈니스 기능

### 5.1 클럽 프로필 관리

**현재:** `club_settings` 테이블에 최소한의 설정만 존재

**추가 필요:**

```sql
-- 클럽 프로필 확장 (organizations 테이블 또는 별도 테이블)
ALTER TABLE organizations ADD COLUMN IF NOT EXISTS
    club_profile JSONB DEFAULT '{}';

-- club_profile 구조:
{
    "established_date": "2010-03-15",        -- 설립일
    "weapons": ["foil", "epee", "sabre"],    -- 운영 무기 종류
    "piste_count": 6,                         -- 피스트 수
    "address": "서울시 강남구 ...",            -- 상세 주소
    "phone": "02-1234-5678",                  -- 대표 전화
    "training_hours": {                       -- 정규 훈련 시간
        "weekday": "16:00-20:00",
        "saturday": "10:00-14:00",
        "sunday": "off"
    },
    "description": "...",                     -- 클럽 소개
    "logo_url": null,                         -- 로고
    "photos": [],                             -- 시설 사진
    "social_links": {                         -- SNS 링크
        "instagram": "...",
        "youtube": "..."
    },
    "coaches": [                              -- 코치 소개
        {"name": "최병철", "title": "대표/감독", "weapons": ["foil"]},
        {"name": "김코치", "title": "코치", "weapons": ["epee"]}
    ],
    "fee_structure": {                        -- 비용 체계 (공개용)
        "monthly_dues": 150000,
        "lesson_10_pack": 300000,
        "lesson_20_pack": 550000
    }
}
```

**페이지:**
- [ ] `templates/club/settings.html` — 클럽 설정 (owner 전용)
- [ ] `templates/club/profile_public.html` — 클럽 공개 프로필 (비로그인도 조회 가능)

### 5.2 레슨 패키지 & 차감 시스템

**최병철펜싱클럽 비즈니스 모델:**
```
레슨 구매 방식:
  - 10회 패키지: ₩300,000 (코치)
  - 20회 패키지: ₩550,000 (코치)
  - 감독 레슨: 별도 1회 금액 (더 비쌈)

레슨 차감:
  - 레슨 완료 시 잔여 회수에서 1회 차감
  - 코치별/감독별 회수 별도 관리
  - 잔여 회수 0이면 추가 구매 필요 알림
```

**DB 설계:**

```sql
-- 레슨 패키지 테이블
CREATE TABLE app_lesson_packages (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id INTEGER NOT NULL REFERENCES organizations(id),
    member_id UUID NOT NULL REFERENCES members(id),        -- 구매한 선수
    coach_id UUID NOT NULL REFERENCES members(id),         -- 담당 코치
    package_type VARCHAR(20) NOT NULL,                      -- '10_pack', '20_pack', 'single'
    total_sessions INTEGER NOT NULL,                        -- 총 회수
    used_sessions INTEGER NOT NULL DEFAULT 0,               -- 사용 회수
    remaining_sessions INTEGER GENERATED ALWAYS AS (total_sessions - used_sessions) STORED,
    price_per_session INTEGER,                              -- 회당 금액
    total_price INTEGER NOT NULL,                           -- 총 결제 금액
    purchased_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    expires_at TIMESTAMPTZ,                                 -- 만료일 (선택)
    status VARCHAR(20) DEFAULT 'active',                    -- active, exhausted, expired, cancelled
    invoice_id UUID REFERENCES app_invoices(id),            -- 연결된 청구서
    created_at TIMESTAMPTZ DEFAULT now()
);

-- 레슨 차감 기록
CREATE TABLE app_lesson_deductions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    package_id UUID NOT NULL REFERENCES app_lesson_packages(id),
    lesson_id UUID REFERENCES lessons(id),                  -- 연결된 레슨
    deducted_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    deducted_by UUID NOT NULL REFERENCES members(id),       -- 차감 처리한 코치
    notes TEXT
);
```

**비즈니스 로직:**
- 레슨 완료(`POST /club/lessons/{id}/complete`) 시 자동 차감
- 잔여 회수 2회 이하 → 선수/학부모에게 카카오톡 알림
- 잔여 회수 0 → 레슨 예약 불가 + 구매 안내

### 5.3 레슨 예약 시스템 (선수 → 코치)

**플로우:**
```
1. 선수: 코치 스케줄에서 빈 시간 확인
   → GET /api/schedule/events?visibility=club&coach_id=xxx
   → 이미 레슨/훈련인 시간 제외, 빈 슬롯만 표시
   → 다른 선수 레슨은 "레슨 예약됨"으로만 표시 (이름 비공개)

2. 선수: 빈 시간에 레슨 신청
   → POST /api/lessons/request
   → { coach_id, requested_date, requested_time, duration }

3. 코치: 레슨 신청 알림 수신 (카카오톡 + 앱 내 알림)
   → GET /api/lessons/requests (대기 중인 신청 목록)

4. 코치: 승인/거절/시간변경 제안
   → PATCH /api/lessons/requests/{id}/approve
   → PATCH /api/lessons/requests/{id}/reject
   → PATCH /api/lessons/requests/{id}/reschedule { new_date, new_time }

5. 승인 시: 스케줄에 자동 등록 + 선수에게 알림
6. 거절/변경 시: 선수에게 알림 + 재신청 가능
```

**공강 알림 시스템:**
```
1. 코치: 레슨 중 선수 미출석 → "공강" 상태로 변경
   → PUT /api/lessons/{id}/status { status: "vacant" }

2. 시스템: 사전 등록된 "공강 알림 수신" 선수 목록에 알림
   → 카카오톡: "오늘 14:00 김코치 레슨 빈자리 발생! 신청하세요"

3. 선수: 알림 → 빠른 신청 → 코치 자동 승인 (설정 시)
```

**DB 추가:**
```sql
-- 레슨 신청 테이블
CREATE TABLE app_lesson_requests (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id INTEGER NOT NULL,
    student_id UUID NOT NULL REFERENCES members(id),
    coach_id UUID NOT NULL REFERENCES members(id),
    requested_by UUID NOT NULL REFERENCES members(id),     -- 본인 or 학부모
    requested_date DATE NOT NULL,
    requested_start_time TIME NOT NULL,
    duration_minutes INTEGER DEFAULT 60,
    status VARCHAR(20) DEFAULT 'pending',                   -- pending, approved, rejected, rescheduled, cancelled
    coach_note TEXT,
    rescheduled_date DATE,
    rescheduled_time TIME,
    created_at TIMESTAMPTZ DEFAULT now(),
    responded_at TIMESTAMPTZ
);

-- 공강 알림 수신 설정
CREATE TABLE app_vacancy_subscribers (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id INTEGER NOT NULL,
    member_id UUID NOT NULL REFERENCES members(id),        -- 수신 선수
    coach_id UUID REFERENCES members(id),                  -- 특정 코치만 (NULL=전체)
    weekdays INTEGER[],                                     -- 수신 요일 [1,3,5] = 월수금
    time_range_start TIME,                                  -- 선호 시간대 시작
    time_range_end TIME,                                    -- 선호 시간대 끝
    is_active BOOLEAN DEFAULT true,
    created_at TIMESTAMPTZ DEFAULT now()
);
```

### 5.4 대회 이벤트 관리

**자동 연동 (대한펜싱협회 대회):**
```
1. data 서비스(포트 71)에서 새 대회 스크래핑
2. → webhook 또는 polling으로 club 서비스에 알림
3. → app_schedule_events에 자동 등록 (event_type: "competition")
4. → 소속 선수들에게 출전 여부 확인 알림 발송
```

**수동 입력 (비협회 대회):**
```
1. 감독/코치: 대회 이벤트 수동 생성
   → POST /api/competitions/events
   → { name, date, location, weapon, age_group, entry_fee, deadline }

2. 공지사항 자동 생성 → 선수/학부모에게 알림

3. 선수/학부모: 출전 여부 응답
   → POST /api/competitions/events/{id}/rsvp
   → { status: "attending" | "not_attending", reason? }

4. 감독: 출전자 확정 → 비용 자동 산출
   → 참가비 + 코치출장비(참가자 수로 나눔) + 교통비
   → 청구서 자동 생성
```

**DB 추가:**
```sql
-- 대회 출전 관리 (기존 competition_entries 확장)
CREATE TABLE app_competition_events (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id INTEGER NOT NULL,
    competition_id INTEGER REFERENCES competitions(id),    -- 협회 대회면 연결
    name VARCHAR(200) NOT NULL,
    start_date DATE NOT NULL,
    end_date DATE,
    location VARCHAR(200),
    weapon VARCHAR(20),
    age_group VARCHAR(50),
    entry_fee INTEGER DEFAULT 0,
    coach_travel_fee INTEGER DEFAULT 0,
    transportation_fee INTEGER DEFAULT 0,
    rsvp_deadline DATE,
    is_auto_synced BOOLEAN DEFAULT false,                  -- 협회 대회 자동 동기화 여부
    source VARCHAR(20) DEFAULT 'manual',                   -- 'auto' | 'manual'
    status VARCHAR(20) DEFAULT 'upcoming',                 -- upcoming, closed, completed
    created_by UUID REFERENCES members(id),
    created_at TIMESTAMPTZ DEFAULT now()
);

-- 출전 RSVP
CREATE TABLE app_competition_rsvps (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    event_id UUID NOT NULL REFERENCES app_competition_events(id),
    member_id UUID NOT NULL REFERENCES members(id),
    responded_by UUID NOT NULL REFERENCES members(id),     -- 본인 or 학부모
    status VARCHAR(20) NOT NULL,                           -- attending, not_attending, maybe
    reason TEXT,
    responded_at TIMESTAMPTZ DEFAULT now(),
    UNIQUE(event_id, member_id)
);
```

### 5.5 비용 청구 통합

**청구 유형별 처리:**

| 유형 | 결제 방식 | 자동화 |
|------|----------|--------|
| 월회비 | 카드 (자동/수동) | 매월 자동 청구서 생성 |
| 레슨비 (패키지) | 카드 | 구매 시 1회 청구 |
| 감독 레슨비 | 카드 | 별도 단가, 구매 시 1회 |
| 대회 참가비 | 현금/이체 | 대회 확정 시 수동 |
| 코치 출장비 | 현금/이체 | 참가자 수 균등 분할 |
| 교통비 | 현금/이체 | 수동 |
| 장비 수리비 | 현금/이체 | 수동 |
| 장비 구매비 | 카드/현금 | 수동 |

**대회 비용 분할 로직:**
```python
# 예: 회장배 출전 5명
entry_fee = 30000  # 참가비 (개인)
coach_travel = 200000  # 코치 출장비 (총)
transport = 150000  # 교통비 (총)

per_person = {
    "entry_fee": 30000,                    # 개인
    "coach_travel": 200000 / 5,            # ₩40,000
    "transport": 150000 / 5,               # ₩30,000
    "total": 30000 + 40000 + 30000,        # ₩100,000
}
```

### 5.6 회원 인증 시스템

**data 서비스 연동 인증 플로우:**
```
1. 신규 회원 가입 (카카오 로그인)
2. 클럽 검색 → "최병철펜싱클럽" 선택
3. 감독에게 가입 승인 요청 알림
4. 감독/수석코치: 회원 목록에서 승인
   → data 서비스의 선수 데이터와 매칭 (이름 기반)
   → 매칭 성공: player_id 자동 연결
   → 매칭 실패: 수동 연결 또는 신규 등록
5. 역할 배정 (student/coach/parent 등)
6. 승인 완료 알림 → 서비스 이용 가능
```

---

## 6. Phase 5: 고급 기능

### 6.1 영상 코멘트 시스템

**개요:** 선수가 유튜브에 훈련/시합 영상을 올리고, 계정에 연결하면 감독/코치가 코멘트 작성

**플로우:**
```
1. 선수: 유튜브 영상 URL 등록
   → POST /api/club/videos
   → { youtube_url, title, description, category: "training"|"competition"|"drill" }

2. 시스템: 유튜브 oEmbed API로 썸네일/메타데이터 자동 추출

3. 감독/코치: 영상 목록에서 코멘트 작성
   → POST /api/club/videos/{id}/comments
   → { content, timestamp_seconds? }  ← 특정 시간대에 코멘트 가능

4. 선수/학부모: 코멘트 확인 + 답글

5. 알림: 새 코멘트 시 카카오톡 알림
```

**DB:**
```sql
CREATE TABLE app_videos (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id INTEGER NOT NULL,
    member_id UUID NOT NULL REFERENCES members(id),
    youtube_url TEXT NOT NULL,
    youtube_id VARCHAR(20),
    title VARCHAR(200),
    description TEXT,
    category VARCHAR(20),                                  -- training, competition, drill
    thumbnail_url TEXT,
    duration_seconds INTEGER,
    is_public BOOLEAN DEFAULT false,                       -- 클럽 내 공개 여부
    created_at TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE app_video_comments (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    video_id UUID NOT NULL REFERENCES app_videos(id),
    author_id UUID NOT NULL REFERENCES members(id),
    content TEXT NOT NULL,
    timestamp_seconds INTEGER,                             -- 영상 내 시간 위치
    parent_comment_id UUID REFERENCES app_video_comments(id),  -- 답글
    created_at TIMESTAMPTZ DEFAULT now()
);
```

### 6.2 공지사항 시스템

**현재:** stub 데이터 (하드코딩된 mock)

**구현:**
```sql
CREATE TABLE app_announcements (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id INTEGER NOT NULL,
    author_id UUID NOT NULL REFERENCES members(id),
    title VARCHAR(200) NOT NULL,
    content TEXT NOT NULL,
    category VARCHAR(20) DEFAULT 'general',                -- general, competition, schedule, urgent
    is_pinned BOOLEAN DEFAULT false,
    target_roles TEXT[],                                    -- NULL=전체, ['student','parent']=선수+학부모
    published_at TIMESTAMPTZ DEFAULT now(),
    expires_at TIMESTAMPTZ,
    read_by UUID[] DEFAULT '{}',                           -- 읽은 회원 ID 배열
    created_at TIMESTAMPTZ DEFAULT now()
);
```

**규칙:**
- 작성: owner, head_coach만
- 열람: 전체 회원 (target_roles 필터링)
- 긴급 공지: 카카오톡 알림 동시 발송
- 대회 관련 공지: competition_event와 자동 연결

### 6.3 체크인/체크아웃 고도화

**현재:** IP 기반 자동 체크인만 존재 (체크아웃 없음)

**추가:**
- [ ] **체크아웃 기능** — 퇴관 시간 기록
- [ ] **QR 코드 체크인** — 동적 QR (5분 갱신), 클럽 현장 TV에 표시
- [ ] **GPS Geofence** — 반경 100m 이내 확인 (IP 실패 시 fallback)
- [ ] **코치 대리 체크인** — 코치가 선수 직접 체크인 처리
- [ ] **출석 통계** — 월별/주별 출석률, 연속 출석일

```sql
-- 체크아웃 컬럼 추가
ALTER TABLE attendance ADD COLUMN IF NOT EXISTS
    checked_out_at TIMESTAMPTZ;
ALTER TABLE attendance ADD COLUMN IF NOT EXISTS
    checkout_method VARCHAR(20);  -- 'auto_ip', 'manual', 'qr', 'gps', 'timeout'

-- 동적 QR 코드
CREATE TABLE app_qr_sessions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id INTEGER NOT NULL,
    qr_code VARCHAR(64) NOT NULL UNIQUE,
    valid_from TIMESTAMPTZ NOT NULL,
    valid_until TIMESTAMPTZ NOT NULL,                      -- 5분 유효
    created_at TIMESTAMPTZ DEFAULT now()
);
```

---

## 7. Phase 6: UI/UX 전면 개선

### 7.1 디자인 시스템 통일

**문제:** `dark-theme.css` vs 템플릿 인라인 스타일 충돌

**해결:**
```
1. 디자인 토큰 통일 (CSS Variables만 사용)
2. 모든 인라인 <style> 제거 → 외부 CSS 파일로 분리
3. 다크/라이트 테마 전환 지원
4. 컴포넌트 라이브러리 정리 (components.css에서 club 전용만 분리)
```

**새 CSS 구조:**
```
static/css/
├── tokens.css           # 디자인 토큰 (색상, 타이포, 간격)
├── layout.css           # 레이아웃 (사이드바, 그리드)
├── components.css       # 공통 컴포넌트 (버튼, 카드, 모달, 폼)
├── pages/
│   ├── landing.css      # 랜딩 페이지
│   ├── dashboard.css    # 대시보드 공통
│   ├── schedule.css     # 스케줄러 (기존)
│   ├── lessons.css      # 레슨 관리
│   ├── billing.css      # 결제/청구
│   └── checkin.css      # 체크인
└── themes/
    ├── dark.css          # 다크 테마 오버라이드
    └── light.css         # 라이트 테마 오버라이드
```

### 7.2 반응형 디자인

**원칙:**
- **선수/학부모:** 모바일 우선 (PWA 사용)
- **감독/코치:** 데스크톱 + 태블릿 (클럽 사무실에서 사용)

**브레이크포인트:**
```css
/* 모바일 (선수/학부모 기본) */
@media (max-width: 768px) { /* 하단 네비게이션, 풀폭 카드 */ }

/* 태블릿 */
@media (min-width: 769px) and (max-width: 1024px) { /* 접는 사이드바 */ }

/* 데스크톱 (감독/코치 기본) */
@media (min-width: 1025px) { /* 고정 사이드바 + 넓은 메인 영역 */ }
```

### 7.3 네비게이션 개편

**데스크톱 (감독/코치):**
```
┌──────────────────────────────────────────┐
│  ⚔️ FencingMind          [알림🔔] [프로필▾]│
├────────┬─────────────────────────────────┤
│ 사이드  │                                │
│ 네비    │     메인 콘텐츠 영역            │
│        │                                │
│ 📊 대시 │                                │
│ 👥 회원 │                                │
│ 📅 스케 │                                │
│ 📋 레슨 │                                │
│ ...    │                                │
└────────┴─────────────────────────────────┘
```

**모바일 (선수/학부모):**
```
┌────────────────────────────────────────┐
│  ⚔️ FencingMind    [알림🔔]            │
├────────────────────────────────────────┤
│                                        │
│            메인 콘텐츠 영역             │
│                                        │
├────────────────────────────────────────┤
│  🏠    ✅    📋    🏆    ⋯             │
│  홈  체크인 레슨  대회  더보기          │
└────────────────────────────────────────┘
```

### 7.4 주요 UI 개선 항목

| 항목 | 현재 | 개선 |
|------|------|------|
| 네비바 | 로그인/로그아웃 없음 | 프로필 드롭다운 + 알림 벨 |
| 대시보드 카드 | 숫자만 표시 | 트렌드 그래프 + 비교 지표 |
| 스케줄러 | FullCalendar 기본 | 역할별 뷰 최적화 |
| 체크인 | 버튼 1개 | 상태 카드 + 체크아웃 + 기록 |
| 레슨 | 리스트 뷰만 | 캘린더 뷰 + 차감 현황 바 |
| 결제 | UI 없음 | 학부모 전용 결제 화면 |
| 알림 | UI 없음 | 알림 센터 + 설정 화면 |
| 로딩 | 없음 | 스켈레톤 UI + 스피너 |
| 에러 | alert() | 토스트 메시지 |
| 빈 상태 | 없음 | 일러스트 + 행동 유도 |

---

## 8. 데이터 동기화 아키텍처

### 8.1 현재 문제

```
문제 1: players.team_name이 스크래핑 시점 고정
  → 이적한 선수의 소속이 업데이트되지 않음

문제 2: 로스터 조회 시 N+1 HTTP 호출
  → 64명 회원 → 최대 128번 httpx 호출 → 타임아웃

문제 3: 자동 동기화 없음
  → data 서비스 재스크래핑 후에도 club에 반영 안 됨
```

### 8.2 해결 아키텍처

```
┌─────────────────┐     webhook/polling     ┌─────────────────┐
│  Data Service   │ ──────────────────────→ │  Club Service   │
│  (포트 71)      │                         │  (포트 72)      │
│                 │                         │                 │
│  competitions   │     동기화 이벤트        │  app_player_    │
│  events         │ ──────────────────────→ │  cache          │
│  players        │                         │  (로컬 캐시)    │
│  matches        │                         │                 │
│  rankings       │                         │                 │
└─────────────────┘                         └─────────────────┘
```

**동기화 전략:**

```
방안 A: 이벤트 기반 (webhook)
  - data 서비스에서 스크래핑 완료 시 → POST /api/club/sync/webhook
  - club 서비스: 해당 클럽 소속 선수 데이터만 갱신
  - 장점: 실시간, 필요할 때만 호출
  - 단점: data 서비스 수정 필요

방안 B: 주기적 폴링 (cron)
  - 매일 새벽 3시 club 서비스 → data 서비스 API 호출
  - 클럽 소속 선수 데이터 배치 갱신
  - 장점: 단순, data 서비스 수정 불필요
  - 단점: 실시간 아님

→ 1단계: 방안 B (배치 동기화)
→ 2단계: 방안 A (이벤트 기반) 추가
```

**로컬 캐시 테이블:**

```sql
-- 선수 데이터 로컬 캐시 (N+1 HTTP 제거)
CREATE TABLE app_player_cache (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id INTEGER NOT NULL,
    member_id UUID NOT NULL REFERENCES members(id),
    player_id VARCHAR(20),                                 -- KOP00000 형식
    player_name VARCHAR(100) NOT NULL,
    current_team VARCHAR(100),
    weapons TEXT[],
    age_group VARCHAR(20),
    competition_count INTEGER DEFAULT 0,
    last_competition_date DATE,
    recent_result TEXT,                                     -- "2026 🥇1"
    medals JSONB DEFAULT '{}',                             -- {"gold":2,"silver":1,"bronze":3}
    last_synced_at TIMESTAMPTZ DEFAULT now(),
    UNIQUE(organization_id, member_id)
);
```

**배치 동기화 서비스:**
```python
# services/club/app/sync/service.py

class SyncService:
    async def sync_club_players(self, org_id: int):
        """클럽 소속 선수 데이터 배치 동기화"""
        members = get_club_members(org_id, role="student")

        # 1회 HTTP 호출로 전체 선수 데이터 조회
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{DATA_SERVICE_URL}/api/players/search",
                params={"q": org_name, "limit": 200},
                timeout=30.0
            )
            all_players = response.json().get("results", [])

        # 로컬 캐시 업데이트 (upsert)
        for member in members:
            matched = find_matching_player(member, all_players)
            if matched:
                upsert_player_cache(org_id, member.id, matched)
```

---

## 9. 기술 부채 해소

### 9.1 보안 (Critical)

| 항목 | 현재 | 해결 |
|------|------|------|
| TEST_MODE 기본값 | `"1"` (true) | `"0"` (false)으로 변경 |
| 템플릿 TEST_MODE | `const TEST_MODE = true` 하드코딩 | 서버에서 주입, 기본 false |
| CORS | 미설정 | origin 화이트리스트 |
| Rate Limiting | 없음 | API별 속도 제한 |
| Input Validation | 부분적 | 전체 엔드포인트 Pydantic 검증 |

### 9.2 성능

| 항목 | 현재 | 해결 |
|------|------|------|
| N+1 HTTP 호출 | 선수 1명당 2번 | 배치 조회 + 로컬 캐시 |
| DB 커넥션 | 요청마다 새 클라이언트 | 커넥션 풀 |
| 정적 파일 | 버전 쿼리스트링 | CDN + 해시 기반 캐시버스팅 |
| 큰 CSS 로드 | components.css (2905줄) 전체 로드 | club 전용 CSS 분리 |

### 9.3 코드 품질

| 항목 | 현재 | 해결 |
|------|------|------|
| router.py | 1,320줄 단일 파일 | 도메인별 분리 (members, attendance, lessons) |
| CSS 불일치 | dark-theme vs 인라인 | 통일된 디자인 토큰 |
| .env.example | 불완전 | 모든 env 변수 문서화 |
| 에러 처리 | `except: pass` 다수 | 구조화된 에러 핸들링 |
| 알림톡 | 코드만, 미구현 | Solapi/NHN 실제 연동 |
| 자동 스케줄러 | 없음 | APScheduler 또는 cron |

---

## 10. 구현 우선순위 로드맵

### Sprint 1 (2주): 🔴 인증 & 랜딩

```
목표: TEST_MODE 제거, 실제 로그인, 랜딩 페이지

1. 랜딩 페이지 (landing.html) 구현
2. 카카오/Google 로그인 연동 (account 서비스 리다이렉트)
3. base.html 네비바: 로그인/프로필 버튼
4. TEST_MODE 기본값 false 변경
5. 역할별 대시보드 분기 라우팅
6. try_get_member() 헬퍼 구현
```

### Sprint 2 (2주): 🔴 역할별 대시보드

```
목표: 감독/코치/선수/학부모 전용 대시보드

1. dashboard_owner.html 구현
2. dashboard_coach.html 리팩토링 (본인 스케줄 중심)
3. dashboard_student.html 리팩토링 (모바일 최적화)
4. dashboard_parent.html 신규 구현
5. 학부모-자녀 연동 (guardian_member_id 활용)
6. 코치별 스케줄 권한 분리
```

### Sprint 3 (2주): 🟡 레슨 패키지 & 예약

```
목표: 레슨 구매/차감/예약 시스템

1. app_lesson_packages 테이블 생성
2. 레슨 패키지 구매 API
3. 레슨 완료 시 자동 차감
4. 선수의 코치 빈 시간 조회 API
5. 레슨 신청/승인/거절 플로우
6. 스케줄 조회 시 개인정보 마스킹 (다른 선수 이름 비공개)
```

### Sprint 4 (2주): 🟡 결제 & 대회

```
목표: 실제 결제 연동, 대회 이벤트 관리

1. PortOne 결제 테스트 환경 구축
2. 학부모 결제 UI (billing.html)
3. 대회 이벤트 자동 동기화 (data 서비스 → club)
4. 수동 대회 이벤트 생성 UI
5. 출전 RSVP 시스템
6. 대회 비용 분할 청구
```

### Sprint 5 (2주): 🟡 알림 & 동기화

```
목표: 카카오톡 알림 실연동, 데이터 동기화

1. 카카오 알림톡 실제 연동 (Solapi/NHN)
2. 알림 설정 UI
3. 데이터 동기화 배치 서비스 (매일 새벽)
4. app_player_cache 로컬 캐시 구축
5. 로스터 조회 N+1 문제 해결
6. 공강 알림 시스템
```

### Sprint 6 (2주): 🟢 고급 기능 & UI 개선

```
목표: 영상 코멘트, 공지사항, UI 전면 개선

1. 영상 코멘트 시스템
2. 공지사항 CRUD
3. CSS 디자인 시스템 통일
4. 모바일 하단 네비게이션
5. 스켈레톤 UI / 토스트 메시지
6. 체크아웃 기능 + QR 체크인
```

### Sprint 7 (2주): 🟢 클럽 프로필 & 안정화

```
목표: 클럽 설정 고도화, 전체 QA

1. 클럽 프로필 관리 페이지
2. 회원 가입 승인 플로우
3. 반복 청구 자동 스케줄러
4. 연체 자동 감지/알림
5. 전체 엔드포인트 보안 점검
6. 파일럿 클럽 실 운영 테스트
```

---

## 부록 A: 새 DB 테이블 요약

| 테이블 | Phase | 용도 |
|--------|-------|------|
| `app_lesson_packages` | 4 | 레슨 패키지 구매/차감 |
| `app_lesson_deductions` | 4 | 레슨 차감 기록 |
| `app_lesson_requests` | 4 | 레슨 신청/승인 |
| `app_vacancy_subscribers` | 4 | 공강 알림 수신 설정 |
| `app_competition_events` | 4 | 대회 이벤트 (수동+자동) |
| `app_competition_rsvps` | 4 | 출전 RSVP |
| `app_player_cache` | 5 | 선수 데이터 로컬 캐시 |
| `app_videos` | 5 | 선수 영상 |
| `app_video_comments` | 5 | 영상 코멘트 |
| `app_announcements` | 5 | 공지사항 |
| `app_qr_sessions` | 6 | QR 체크인 세션 |

## 부록 B: API 엔드포인트 추가 예정

```
Auth:
  GET  /auth/login              → 로그인 페이지
  GET  /auth/logout             → 로그아웃 + 리다이렉트

Lessons (확장):
  POST /api/lessons/request     → 레슨 신청 (선수)
  GET  /api/lessons/requests    → 신청 목록 (코치)
  PATCH /api/lessons/requests/{id}/approve
  PATCH /api/lessons/requests/{id}/reject
  PATCH /api/lessons/requests/{id}/reschedule

Lesson Packages:
  POST /api/lesson-packages     → 패키지 구매
  GET  /api/lesson-packages/my  → 내 패키지 현황
  GET  /api/lesson-packages/{id}/history → 차감 이력

Competition Events:
  POST /api/competitions/events     → 대회 이벤트 생성
  GET  /api/competitions/events     → 대회 목록
  POST /api/competitions/events/{id}/rsvp → 출전 응답
  GET  /api/competitions/events/{id}/rsvps → 응답 현황

Videos:
  POST /api/club/videos              → 영상 등록
  GET  /api/club/videos              → 영상 목록
  POST /api/club/videos/{id}/comments → 코멘트 작성
  GET  /api/club/videos/{id}/comments → 코멘트 목록

Announcements:
  POST /api/club/announcements       → 공지 작성
  GET  /api/club/announcements       → 공지 목록
  GET  /api/club/announcements/{id}  → 공지 상세

Sync:
  POST /api/sync/players             → 선수 데이터 수동 동기화
  POST /api/sync/webhook             → data 서비스 webhook 수신
  GET  /api/sync/status              → 마지막 동기화 상태

Club Profile:
  GET  /api/club/profile             → 클럽 프로필 조회
  PUT  /api/club/profile             → 클럽 프로필 수정 (owner)
  GET  /api/club/profile/public      → 공개 프로필
```

## 부록 C: 환경 변수 전체 목록

```env
# === 필수 ===
SUPABASE_URL=https://xxx.supabase.co
SUPABASE_KEY=eyJ...
JWT_SECRET_KEY=your-jwt-secret-key

# === 서비스 ===
CLUB_PORT=72
CLUB_HOST=0.0.0.0
CLUB_DEBUG=0
CLUB_TEST_MODE=0                          # 프로덕션: 반드시 0
DEFAULT_ORG_ID=401
DATA_SERVICE_URL=http://localhost:71

# === OAuth ===
KAKAO_CLIENT_ID=your-kakao-client-id
KAKAO_REDIRECT_URI=https://app.fencingmind.ai/auth/kakao/callback
GOOGLE_CLIENT_ID=your-google-client-id
GOOGLE_CLIENT_SECRET=your-google-secret

# === 결제 ===
PORTONE_API_SECRET=your-portone-api-secret
PORTONE_STORE_ID=your-portone-store-id

# === 알림 ===
FCM_CREDENTIALS_PATH=/path/to/firebase-credentials.json
ALIMTALK_API_KEY=your-solapi-key
ALIMTALK_API_SECRET=your-solapi-secret
ALIMTALK_SENDER_PHONE=02-1234-5678
KAKAO_CHANNEL_ID=your-kakao-channel-pfid

# === 동기화 ===
SYNC_CRON_SCHEDULE=0 3 * * *             # 매일 새벽 3시
SYNC_ENABLED=1
```
