# PRD: FencingMind 통합 관리자 대시보드

**Version**: 1.0
**Date**: 2026-02-25
**Author**: FencingMind Development Team
**Status**: Draft

---

## 1. Executive Summary

FencingMind은 7개 서브도메인을 운영하는 펜싱 플랫폼이다. 현재 관리자 기능은 account 서비스에 API 수준으로만 구현되어 있고(6개 엔드포인트), UI는 기본 통계 카드만 존재한다. 회원 관리, 인증 승인, Claim 심사, 데이터 관리 등 핵심 운영 기능의 관리 화면이 전혀 없어 운영이 불가능한 상태다.

본 PRD는 `account.fencingmind.ai/admin/` 경로에 **중앙 집중형 통합 관리 대시보드**를 구축하여, 모든 서비스의 운영 관리를 하나의 인터페이스에서 수행할 수 있도록 한다.

### 핵심 목표
1. 회원 관리 (검색, 상세, 수정, 제재) UI 구현
2. 승인 큐 통합 (인증, Player Claim, 조직 인증, 데이터 수정 요청)
3. 서비스별 관리 탭 (Account, Data, Club)
4. RBAC 기반 관리자 권한 체계로 전환
5. 감사 로그 및 운영 모니터링

### 왜 중앙 집중형인가
- 1인 개발 → 분산형의 이점(팀 자율성)이 불필요
- 7개 서비스 중 3개만 개발 중 → 초기 복잡도 낮음
- account 서비스가 회원/인증 소유 → admin의 자연스러운 위치
- 모든 서비스가 같은 Supabase DB 공유 → 중앙에서 조회 용이

---

## 2. 현재 상태 (AS-IS)

### 구현된 것

| 영역 | 상태 | 내용 |
|------|:---:|------|
| Admin API | ✅ | 6개 엔드포인트 (인증 승인/거부, 회원 목록, 구독 통계) |
| Admin 대시보드 UI | ⚠️ 20% | 통계 카드 3개 + 링크 3개만 |
| 권한 체계 | ⚠️ | 이메일 하드코딩 (`admin@fencingmind.ai`만) + member_type 혼용 |

### 구현 안 된 것

| 영역 | 필요도 |
|------|:---:|
| 회원 관리 UI (검색/상세/수정) | 필수 |
| 인증 승인 상세 UI | 필수 |
| Player Claim 심사 UI | 필수 |
| 조직(클럽) 인증 심사 UI | 필수 |
| 데이터 수정 요청 처리 UI | 필수 |
| Data 서비스 관리 (대회/선수/스크래핑) | 필요 |
| Club 서비스 관리 (클럽/코치) | 필요 |
| 구독/결제 관리 상세 UI | 필요 |
| 감사 로그 | 필요 |
| RBAC 권한 체계 | 필요 |

### 현재 코드 위치

```
services/account/app/admin/router.py          # API 6개 (195줄)
services/account/templates/account/admin/
  └── dashboard.html                           # 기본 통계 카드 (112줄)
packages/shared_core/auth/dependencies.py      # 권한 함수 (333줄)
```

---

## 3. 관리자 역할 체계 (RBAC)

### 역할 정의

| 역할 | 범위 | 설명 |
|------|------|------|
| **super_admin** | 전체 시스템 | 모든 기능 + 시스템 설정 + 관리자 관리 |
| **service_admin** | 담당 서비스 | 해당 서비스 관리 + 회원 조회(읽기) |
| **moderator** | 콘텐츠 | 게시물 관리, 신고 처리 (community/blog용, 향후) |
| **support** | 고객 지원 | 회원 조회(읽기), 기본 문의 처리 |

### 권한 매트릭스

| 기능 | super_admin | service_admin | moderator | support |
|------|:-----------:|:-------------:|:---------:|:-------:|
| 시스템 설정 | RW | - | - | - |
| 관리자 역할 관리 | RW | - | - | - |
| 회원 수정/제재 | RW | RW* | - | - |
| 회원 조회 | RW | RW* | R | R |
| 승인 큐 처리 | RW | RW* | - | - |
| 구독/결제 관리 | RW | RW* | - | R |
| 콘텐츠 관리 | RW | RW* | RW | R |
| 통계 조회 | RW | RW* | R | R |
| 감사 로그 조회 | RW | R | - | - |

*service_admin은 자신이 담당하는 서비스 범위 내에서만*

### 현재 → 개선

```
현재 (하드코딩):
  if member.email in ADMIN_EMAILS or member.member_type in ("club_director",):
      → 관리자

개선 (RBAC):
  members.admin_role = "super_admin" | "service_admin" | "moderator" | "support" | NULL
  + admin_service_assignments 테이블로 service_admin의 담당 서비스 지정
```

---

## 4. 전체 구조 및 네비게이션

### URL 구조

```
/admin/                                    ← 통합 대시보드 홈
│
├── /admin/members                         ← 회원 관리
│   ├── /admin/members?q=김&status=active  ← 검색/필터
│   └── /admin/members/{id}               ← 회원 상세
│
├── /admin/approvals                       ← 승인 큐 (통합)
│   ├── /admin/approvals?type=verification ← 인증 승인
│   ├── /admin/approvals?type=player_claim ← 선수 Claim
│   ├── /admin/approvals?type=org_claim    ← 조직 인증
│   └── /admin/approvals?type=correction   ← 데이터 수정
│
├── /admin/services/account                ← Account 관리
│   ├── 구독 현황
│   └── 결제 관리
│
├── /admin/services/data                   ← Data 관리
│   ├── 대회 관리
│   ├── 선수 관리 (병합/분리)
│   └── 스크래핑 로그
│
├── /admin/services/club                   ← Club 관리
│   ├── 클럽 목록/관리
│   └── 코치 관리
│
├── /admin/logs                            ← 감사 로그
│
└── /admin/settings                        ← 시스템 설정
    ├── 관리자 역할 관리
    └── 서비스 설정
```

### 탭 네비게이션 UI

```
┌──────────────────────────────────────────────────────────────────┐
│  FencingMind Admin                           관리자: 박제인 ▼    │
├──────┬──────┬──────────┬──────┬──────┬──────┬─────────┬─────────┤
│ 홈   │ 회원 │ 승인(12) │ ACC  │ DATA │ CLUB │ 로그    │ 설정    │
├──────┴──────┴──────────┴──────┴──────┴──────┴─────────┴─────────┤
│                                                                  │
│  [페이지 콘텐츠]                                                  │
│                                                                  │
└──────────────────────────────────────────────────────────────────┘
```

승인 탭의 `(12)`는 pending 건수를 실시간 표시.

---

## 5. 기능 상세

### 5.1 통합 대시보드 홈 (`/admin/`)

```
┌─────────────────────────────────────────────────────────────┐
│  📊 FencingMind 관리 대시보드                                │
├─────────────┬─────────────┬─────────────┬───────────────────┤
│ 전체 회원    │ 오늘 가입    │ 유료 구독    │ 승인 대기          │
│ 1,234       │ +7          │ 45          │ 12건              │
│ (+23 이번주) │             │ ($4,500/월)  │ ⚠️ 3건 긴급       │
├─────────────┴─────────────┴─────────────┴───────────────────┤
│                                                              │
│  승인 대기 요약                                    [전체 보기] │
│  ┌────────────────────────────────────────────────────────┐  │
│  │ 🔴 인증 심사 3건  │ 🟡 Claim 5건  │ 🔵 조직 인증 2건  │  │
│  │ 🟢 데이터 수정 2건                                     │  │
│  └────────────────────────────────────────────────────────┘  │
│                                                              │
│  서비스별 현황                                                │
│  ┌──────────┬──────────┬──────────┐                          │
│  │ Account  │ Data     │ Club     │                          │
│  │ 회원 1234│ 대회 132 │ 클럽 3   │                          │
│  │ 구독 45  │ 선수 11K │ 코치 5   │                          │
│  │ [관리]   │ [관리]   │ [관리]   │                          │
│  └──────────┴──────────┴──────────┘                          │
│                                                              │
│  최근 활동                                                    │
│  • 김철수 - 인증 신청 (2분 전)                                │
│  • 박영희 - 선수 Claim KOP03421 (15분 전)                    │
│  • 서울펜싱클럽 - 사업자등록증 제출 (1시간 전)                 │
│                                                              │
└─────────────────────────────────────────────────────────────┘
```

**데이터 소스:**
- 전체 회원: `SELECT COUNT(*) FROM members`
- 오늘 가입: `WHERE created_at >= today()`
- 유료 구독: `SELECT COUNT(*) FROM member_services WHERE tier != 'free' AND status = 'active'`
- 승인 대기: verifications(pending) + player_claims(pending) + organization_claims(pending) + data_correction_requests(pending)

### 5.2 회원 관리 (`/admin/members`)

#### 목록 화면

```
┌─────────────────────────────────────────────────────────────┐
│  회원 관리                                    [CSV 내보내기]  │
├─────────────────────────────────────────────────────────────┤
│  검색: [이름/이메일___________] 유형: [전체 ▼]               │
│  상태: [전체 ▼]  인증: [전체 ▼]  정렬: [최근가입 ▼]          │
├────┬──────────┬─────────────────┬──────┬──────┬──────┬──────┤
│ ☐  │ 이름     │ 이메일           │ 유형 │ 인증 │ 가입일│ 관리 │
├────┼──────────┼─────────────────┼──────┼──────┼──────┼──────┤
│ ☐  │ 김철수   │ kim@...         │ 선수 │ T2   │ 2/24 │ [상세]│
│ ☐  │ 박영희   │ park@...        │ 코치 │ T3   │ 2/20 │ [상세]│
│ ☐  │ 이관장   │ lee@...         │ 감독 │ T3   │ 2/15 │ [상세]│
├────┴──────────┴─────────────────┴──────┴──────┴──────┴──────┤
│  [이전] 1 2 3 ... 25 [다음]      총 1,234명  │ 50개씩 표시   │
├─────────────────────────────────────────────────────────────┤
│  선택된 항목: [일괄 이메일] [일괄 상태 변경]                   │
└─────────────────────────────────────────────────────────────┘
```

#### 회원 상세 화면 (`/admin/members/{id}`)

```
┌─────────────────────────────────────────────────────────────┐
│  ← 목록으로   회원 상세: 김철수                               │
├──────────────────────────┬──────────────────────────────────┤
│  프로필                   │  빠른 액션                        │
│  ─────────               │  [인증 Tier 변경]                 │
│  이름: 김철수             │  [회원 유형 변경]                  │
│  이메일: kim@gmail.com    │  [비밀번호 초기화]                 │
│  전화: 010-****-5678     │  [계정 정지]                      │
│  가입일: 2026-02-24      │  [계정 삭제]                      │
│  유형: player (선수)      │                                  │
│  인증: Tier 2 (본인확인)  │                                  │
│  닉네임: @chulsoo        │                                  │
├──────────────────────────┴──────────────────────────────────┤
│  [프로필] [인증이력] [구독] [Claim] [활동로그] [메모]          │
├─────────────────────────────────────────────────────────────┤
│                                                              │
│  인증 이력 탭:                                                │
│  ┌──────────┬──────────┬──────────┬──────────┐               │
│  │ Tier 0   │ Tier 1   │ Tier 2   │ Tier 3   │               │
│  │ 2/24     │ 2/24     │ 2/25     │ -        │               │
│  │ 가입     │ 이메일   │ Gemini   │ 미연결   │               │
│  │ ✅       │ ✅       │ ✅ (0.91) │ ⏳       │               │
│  └──────────┴──────────┴──────────┴──────────┘               │
│                                                              │
│  구독 탭:                                                     │
│  Data: Free │ Club: - │ Community: - │ Shop: -               │
│                                                              │
│  관리자 메모:                                                  │
│  [메모 입력란________________________________] [저장]          │
│                                                              │
└─────────────────────────────────────────────────────────────┘
```

### 5.3 승인 큐 (`/admin/approvals`)

모든 승인 유형을 하나의 통합 큐에서 관리한다.

#### 필터 탭

```
[전체 (12)] [인증 (3)] [선수Claim (5)] [조직인증 (2)] [데이터수정 (2)]
```

#### 인증 승인 카드

```
┌─────────────────────────────────────────────────────────────┐
│  🔴 인증 심사  │  김철수 (kim@gmail.com)  │  2시간 전         │
├─────────────────────────────────────────────────────────────┤
│                                                              │
│  유형: player (선수)                                          │
│  Gemini 판정: 0.72 (불확실 → 수동 심사)                       │
│  제출 사진: [마스크 착용] [도복 착용] [협회 등록증]             │
│                                                              │
│  Gemini 분석 결과:                                            │
│  ┌────────────────────────────────────────────────────────┐  │
│  │ 마스크: ✅ 펜싱 마스크 감지 (0.95)                      │  │
│  │ 도복: ✅ 펜싱 도복 감지 (0.88)                          │  │
│  │ 등록증: ⚠️ 텍스트 일부 불선명 (0.72)                   │  │
│  │ 추출 이름: "김철*" (부분 판독)                          │  │
│  └────────────────────────────────────────────────────────┘  │
│                                                              │
│  사유: [________________________________]                     │
│                                                              │
│  [승인] [거부] [추가 서류 요청] [보류]                         │
└─────────────────────────────────────────────────────────────┘
```

#### 선수 Claim 심사 카드

```
┌─────────────────────────────────────────────────────────────┐
│  🟡 선수 Claim  │  박영희 → KOP03421  │  15분 전            │
├─────────────────────────────────────────────────────────────┤
│                                                              │
│  신청자: 박영희 (park@gmail.com, Tier 2)                     │
│  Claim 대상: 박영희 (KOP03421)                               │
│  매칭 점수: 0.73                                              │
│                                                              │
│  매칭 상세:                                                   │
│  ┌──────────────────────┬──────────┬──────────┐              │
│  │ 항목                 │ 신청자    │ 선수DB   │              │
│  ├──────────────────────┼──────────┼──────────┤              │
│  │ 이름                 │ 박영희   │ 박영희    │ ✅           │
│  │ 소속팀               │ 서울FC   │ 서울펜싱  │ ⚠️ (유사)    │
│  │ 무기                 │ 플뢰레   │ 플뢰레    │ ✅           │
│  │ 생년                 │ 2005     │ 2005     │ ✅           │
│  └──────────────────────┴──────────┴──────────┘              │
│                                                              │
│  최근 대회 (선수DB):                                          │
│  • 2025 회장배 여자 플뢰레 - 16강                             │
│  • 2025 전국체전 여자 플뢰레 - 8강                            │
│                                                              │
│  [승인] [거부] [코치 확인 요청]                                │
└─────────────────────────────────────────────────────────────┘
```

#### 조직 인증 심사 카드

```
┌─────────────────────────────────────────────────────────────┐
│  🔵 조직 인증  │  서울펜싱클럽 (이관장)  │  1시간 전          │
├─────────────────────────────────────────────────────────────┤
│                                                              │
│  신청자: 이관장 (lee@gmail.com, Tier 2)                      │
│  클럽: 서울펜싱클럽 (org_id: 125)                            │
│  인증 유형: director (클럽 대표)                               │
│                                                              │
│  사업자등록증 자동 검증:                                       │
│  ┌────────────────────────────────────────────────────────┐  │
│  │ Layer 1 (Gemini OCR): ✅ 사업자번호 123-45-67890       │  │
│  │ Layer 2 (체크디짓):   ✅ 유효                           │  │
│  │ Layer 3 (국세청 API): ✅ 계속사업자, 정보 일치           │  │
│  │ 대표자명 일치:        ✅ "이관장" == 가입자 실명          │  │
│  │                                                        │  │
│  │ → 자동 승인 가능                                        │  │
│  └────────────────────────────────────────────────────────┘  │
│                                                              │
│  ※ 3-Layer 모두 통과 + 대표자명 일치 → 자동 승인 대상         │
│  ※ 관리자 개입 필요 없음 (이 카드는 참고용 로그)              │
│                                                              │
│  [수동 승인] [거부] [추가 서류 요청]                           │
└─────────────────────────────────────────────────────────────┘
```

### 5.4 Account 서비스 탭 (`/admin/services/account`)

```
┌─────────────────────────────────────────────────────────────┐
│  Account 서비스 관리                                         │
├─────────────────────────────────────────────────────────────┤
│                                                              │
│  구독 현황                                                    │
│  ┌───────────┬──────┬──────┬──────┬──────┐                   │
│  │ 서비스     │ Free │ Basic│ Prem │ 합계 │                   │
│  ├───────────┼──────┼──────┼──────┼──────┤                   │
│  │ Data      │ 1180 │ 30   │ 10   │ 1220 │                   │
│  │ Club      │ 3    │ 2    │ 0    │ 5    │                   │
│  │ Community │ -    │ -    │ -    │ -    │                   │
│  │ Shop      │ -    │ -    │ -    │ -    │                   │
│  └───────────┴──────┴──────┴──────┴──────┘                   │
│                                                              │
│  월 매출: $4,500  │  MRR 추이: [차트]                         │
│                                                              │
│  최근 결제 이벤트                                              │
│  • 김철수 - Data Basic 구독 ($9.99) - 2시간 전               │
│  • 박코치 - Club Basic 구독 ($29.99) - 1일 전                │
│                                                              │
└─────────────────────────────────────────────────────────────┘
```

### 5.5 Data 서비스 탭 (`/admin/services/data`)

```
┌─────────────────────────────────────────────────────────────┐
│  Data 서비스 관리                                            │
├──────────┬───────────────┬──────────────────────────────────┤
│ [대회]   │ [선수 관리]    │ [스크래핑]                        │
├──────────┴───────────────┴──────────────────────────────────┤
│                                                              │
│  선수 관리 탭:                                                │
│  ┌────────────────────────────────────────────────────────┐  │
│  │ 선수 검색: [이름____________] [팀________] [검색]       │  │
│  │                                                        │  │
│  │ 동명이인 감지 목록 (자동):                               │  │
│  │ ⚠️ 김민수 - 3명 감지 (플뢰레/에페/사브르)               │  │
│  │    [상세 보기] [병합] [분리 확인]                        │  │
│  │ ⚠️ 박지현 - 2명 감지 (같은 무기, 다른 팀)               │  │
│  │    [상세 보기] [병합] [분리 확인]                        │  │
│  │                                                        │  │
│  │ 데이터 수정 요청 (pending):                              │  │
│  │ • KOP03421 박영희 - 소속팀 변경 요청 (1건)              │  │
│  │ • KOP05612 최강 - 대회결과 귀속 오류 신고 (1건)          │  │
│  └────────────────────────────────────────────────────────┘  │
│                                                              │
│  스크래핑 탭:                                                  │
│  ┌────────────────────────────────────────────────────────┐  │
│  │ 마지막 실행: 2026-02-24 03:00                           │  │
│  │ 상태: ✅ 성공 (132 대회, 2,500 종목)                    │  │
│  │ 다음 예약: 2026-02-25 03:00                             │  │
│  │                                                        │  │
│  │ [지금 실행] [로그 보기] [설정]                           │  │
│  │                                                        │  │
│  │ 최근 에러:                                              │  │
│  │ (없음)                                                  │  │
│  └────────────────────────────────────────────────────────┘  │
│                                                              │
└─────────────────────────────────────────────────────────────┘
```

### 5.6 Club 서비스 탭 (`/admin/services/club`)

```
┌─────────────────────────────────────────────────────────────┐
│  Club 서비스 관리                                            │
├──────────┬──────────────────────────────────────────────────┤
│ [클럽]   │ [코치]                                           │
├──────────┴──────────────────────────────────────────────────┤
│                                                              │
│  등록된 클럽                                                  │
│  ┌──────┬──────────────┬────────┬──────┬──────┬──────────┐  │
│  │ ID   │ 클럽명        │ 관장    │ 코치 │ 회원 │ 구독     │  │
│  ├──────┼──────────────┼────────┼──────┼──────┼──────────┤  │
│  │ 401  │ 최병철펜싱클럽│ 최병철  │ 2    │ 35   │ Basic    │  │
│  │ 125  │ 서울펜싱클럽  │ 이관장  │ 1    │ 20   │ Free     │  │
│  │ 203  │ 부산검도FC    │ -       │ -    │ -    │ 미등록   │  │
│  └──────┴──────────────┴────────┴──────┴──────┴──────────┘  │
│                                                              │
│  미등록 클럽: 504개 (organizations에 존재, club_settings 없음) │
│                                                              │
│  온보딩 현황:                                                  │
│  ✅ 완료: 1  │  🔄 진행 중: 1  │  ⏳ 대기: 504               │
│                                                              │
└─────────────────────────────────────────────────────────────┘
```

### 5.7 감사 로그 (`/admin/logs`)

모든 관리자 행위를 기록한다.

```
┌─────────────────────────────────────────────────────────────┐
│  감사 로그                                                    │
├─────────────────────────────────────────────────────────────┤
│  기간: [2026-02-01] ~ [2026-02-25]  관리자: [전체 ▼]         │
│  유형: [전체 ▼]                                               │
├──────────┬────────┬──────────────────────────┬──────────────┤
│ 시간     │ 관리자  │ 행위                      │ 대상         │
├──────────┼────────┼──────────────────────────┼──────────────┤
│ 14:32    │ 박제인 │ 인증 승인                 │ 김철수       │
│ 14:15    │ 박제인 │ Player Claim 승인         │ 박영희→KOP03│
│ 13:50    │ 시스템 │ 조직 인증 자동 승인        │ 서울펜싱클럽 │
│ 13:20    │ 박제인 │ 회원 상태 변경 (정지)      │ 스패머001   │
└──────────┴────────┴──────────────────────────┴──────────────┘
```

---

## 6. DB 스키마 변경

### Migration 014: Admin Dashboard 지원

```sql
-- Migration 014: Admin Dashboard Infrastructure
-- 관리자 역할 체계 + 감사 로그

-- ============================================================
-- 1. members 테이블에 admin_role 추가
-- ============================================================
ALTER TABLE members ADD COLUMN IF NOT EXISTS admin_role VARCHAR(20)
    CHECK (admin_role IN ('super_admin', 'service_admin', 'moderator', 'support'));

-- 초기 super_admin 설정 (대표)
-- UPDATE members SET admin_role = 'super_admin' WHERE email = '대표이메일';

-- ============================================================
-- 2. admin_service_assignments: service_admin 담당 서비스
-- ============================================================
CREATE TABLE IF NOT EXISTS admin_service_assignments (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    member_id UUID NOT NULL REFERENCES members(id) ON DELETE CASCADE,
    service_id VARCHAR(20) NOT NULL,  -- 'data', 'club', 'community', 'shop', 'blog', 'analytics'
    assigned_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    assigned_by UUID REFERENCES members(id),

    UNIQUE(member_id, service_id)
);

CREATE INDEX idx_admin_assignments_member ON admin_service_assignments(member_id);

-- ============================================================
-- 3. admin_audit_logs: 감사 로그
-- ============================================================
CREATE TABLE IF NOT EXISTS admin_audit_logs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    admin_member_id UUID REFERENCES members(id),  -- NULL이면 시스템 자동
    action VARCHAR(50) NOT NULL,  -- 'approve_verification', 'reject_claim', 'suspend_member', ...
    target_type VARCHAR(30) NOT NULL,  -- 'member', 'verification', 'player_claim', 'org_claim', 'player', ...
    target_id TEXT NOT NULL,  -- 대상 ID (UUID 또는 BIGINT의 TEXT 표현)
    details JSONB,  -- 변경 전/후 값, 사유 등
    ip_address INET,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_audit_logs_admin ON admin_audit_logs(admin_member_id);
CREATE INDEX idx_audit_logs_target ON admin_audit_logs(target_type, target_id);
CREATE INDEX idx_audit_logs_created ON admin_audit_logs(created_at DESC);

-- ============================================================
-- 4. admin_notes: 관리자 메모 (회원별)
-- ============================================================
CREATE TABLE IF NOT EXISTS admin_notes (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    member_id UUID NOT NULL REFERENCES members(id) ON DELETE CASCADE,
    author_id UUID NOT NULL REFERENCES members(id),
    content TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_admin_notes_member ON admin_notes(member_id);
```

---

## 7. API 엔드포인트 설계

### 7.1 기존 API 유지 + 확장

```
기존 (유지):
GET  /admin/dashboard              → 대시보드 페이지 (HTML 확장)
GET  /admin/verifications          → 인증 대기 목록
POST /admin/verifications/{id}/approve
POST /admin/verifications/{id}/reject
GET  /admin/members                → 회원 목록
GET  /admin/subscriptions/stats    → 구독 통계
```

### 7.2 신규 API

#### 회원 관리

```
GET  /admin/members/{id}
     Response: { member, oauth_connections, subscriptions, claims,
                 verification_history, consent_logs, admin_notes }

PATCH /admin/members/{id}
     Auth: super_admin | service_admin(account)
     Body: { admin_role?, member_type?, member_status?, verification_tier? }

POST /admin/members/{id}/suspend
     Auth: super_admin | service_admin(account)
     Body: { reason, duration_days? }

POST /admin/members/{id}/unsuspend
     Auth: super_admin | service_admin(account)

DELETE /admin/members/{id}
     Auth: super_admin
     Body: { reason }
     → 30일 유예 삭제 (soft delete)
```

#### 통합 승인 큐

```
GET  /admin/approvals?type=all|verification|player_claim|org_claim|correction
     &status=pending|approved|rejected
     &page=1&limit=20
     Auth: super_admin | service_admin
     Response: { items: [...], total, page, pages }

POST /admin/approvals/{type}/{id}/approve
     Auth: super_admin | service_admin
     Body: { reason? }

POST /admin/approvals/{type}/{id}/reject
     Auth: super_admin | service_admin
     Body: { reason }

POST /admin/approvals/{type}/{id}/request-more-info
     Auth: super_admin | service_admin
     Body: { message }
```

#### Data 서비스 관리

```
GET  /admin/services/data/competitions
     Response: { competitions: [...], total }

GET  /admin/services/data/players?q=...
     Response: { players: [...], total }

POST /admin/services/data/players/{id}/merge
     Auth: super_admin | service_admin(data)
     Body: { merge_into_player_id }

POST /admin/services/data/players/{id}/split
     Auth: super_admin | service_admin(data)
     Body: { events_to_split: [event_id, ...] }

GET  /admin/services/data/scrape-logs
     Response: { logs: [...] }

POST /admin/services/data/scrape/trigger
     Auth: super_admin | service_admin(data)
```

#### Club 서비스 관리

```
GET  /admin/services/club/clubs
     Response: { clubs: [{ org, settings, owner, coach_count, member_count }] }

GET  /admin/services/club/clubs/{org_id}
     Response: { org, settings, members, coaches, stats }

PATCH /admin/services/club/clubs/{org_id}/settings
     Auth: super_admin | service_admin(club)
     Body: { status?, ... }
```

#### 감사 로그

```
GET  /admin/logs?admin_id=...&target_type=...&from=...&to=...&page=1
     Auth: super_admin | service_admin(읽기)
     Response: { logs: [...], total }
```

#### 관리자 메모

```
GET  /admin/members/{id}/notes
     Auth: support+
     Response: { notes: [...] }

POST /admin/members/{id}/notes
     Auth: support+
     Body: { content }
```

#### 시스템 설정

```
GET  /admin/settings/admins
     Auth: super_admin
     Response: { admins: [{ member, admin_role, services }] }

POST /admin/settings/admins/{member_id}/assign
     Auth: super_admin
     Body: { admin_role, service_ids? }

DELETE /admin/settings/admins/{member_id}/revoke
     Auth: super_admin
```

---

## 8. 파일 구조

### 신규/수정 파일

```
services/account/app/admin/
├── router.py               # MODIFY - 기존 6개 + 신규 엔드포인트
├── members.py              # NEW - 회원 관리 라우터
├── approvals.py            # NEW - 통합 승인 큐 라우터
├── services_data.py        # NEW - Data 서비스 관리
├── services_club.py        # NEW - Club 서비스 관리
├── services_account.py     # NEW - Account 서비스 관리 (구독/결제)
├── logs.py                 # NEW - 감사 로그 라우터
├── settings.py             # NEW - 시스템 설정 라우터
└── dependencies.py         # NEW - Admin 전용 권한 체크

services/account/templates/admin/
├── layout.html             # NEW - Admin 레이아웃 (탭 네비게이션)
├── dashboard.html          # MODIFY - 통합 대시보드 홈
├── members/
│   ├── list.html           # NEW - 회원 목록
│   └── detail.html         # NEW - 회원 상세
├── approvals/
│   ├── list.html           # NEW - 승인 큐 목록
│   ├── verification.html   # NEW - 인증 심사 카드
│   ├── player_claim.html   # NEW - Claim 심사 카드
│   └── org_claim.html      # NEW - 조직 인증 카드
├── services/
│   ├── account.html        # NEW - Account 관리
│   ├── data.html           # NEW - Data 관리
│   └── club.html           # NEW - Club 관리
├── logs.html               # NEW - 감사 로그
└── settings.html           # NEW - 시스템 설정

packages/shared_core/types/member.py
  └── AdminRole enum 추가   # MODIFY

packages/shared_core/auth/dependencies.py
  └── require_admin_role() 추가  # MODIFY

database/migrations/
  └── 014_admin_dashboard.sql    # NEW
```

---

## 9. 구현 우선순위 및 Phase 분할

### Phase 1: Admin 기본 골격 + 회원 관리 (2주)

| 주차 | 작업 |
|------|------|
| 1 | Migration 014 작성 + 실행 (admin_role, audit_logs, admin_notes) |
| 1 | AdminRole enum + `require_admin_role()` dependency 구현 |
| 1 | Admin 레이아웃 템플릿 (탭 네비게이션) |
| 1 | 대시보드 홈 UI (KPI 카드 + 승인 대기 요약 + 최근 활동) |
| 2 | 회원 목록 UI (검색/필터/페이지네이션) |
| 2 | 회원 상세 UI (프로필/인증이력/구독/메모 탭) |
| 2 | 회원 수정/정지/삭제 API + 감사 로그 기록 |

**Phase 1 완료 기준**: 관리자가 로그인 → 대시보드에서 현황 파악 → 회원 검색 → 상세 조회 → 상태 변경 가능

### Phase 2: 승인 큐 통합 (2주)

| 주차 | 작업 |
|------|------|
| 3 | 통합 승인 큐 API (4가지 유형 조회) |
| 3 | 인증 심사 UI (Gemini 결과 표시 + 사진 미리보기 + 승인/거부) |
| 3 | 기존 `admin/verifications` API를 통합 큐로 마이그레이션 |
| 4 | Player Claim 심사 UI (매칭 상세 비교 + 대회 이력) |
| 4 | 조직 인증 심사 UI (사업자등록증 3-Layer 결과 표시) |
| 4 | 데이터 수정 요청 처리 UI |

**Phase 2 완료 기준**: 모든 승인 유형을 하나의 큐에서 처리 가능, 감사 로그 자동 기록

### Phase 3: 서비스별 관리 탭 (2주)

| 주차 | 작업 |
|------|------|
| 5 | Account 탭 (구독 현황, 결제 이벤트, MRR) |
| 5 | Data 탭 - 대회/선수 목록 조회 |
| 5 | Data 탭 - 선수 병합/분리 UI (PlayerIdentityResolver 연동) |
| 6 | Data 탭 - 스크래핑 로그 + 수동 트리거 |
| 6 | Club 탭 - 클럽 목록, 온보딩 현황 |
| 6 | Club 탭 - 코치 관리 |

**Phase 3 완료 기준**: 서비스별 핵심 관리 기능이 모두 Admin에서 접근 가능

### Phase 4: 운영 도구 (1주)

| 주차 | 작업 |
|------|------|
| 7 | 감사 로그 UI (필터/검색) |
| 7 | 시스템 설정 UI (관리자 역할 관리) |
| 7 | CSV 내보내기 (회원 목록, 구독 목록) |

---

## 10. 기술적 고려사항

### 10.1 Admin 레이아웃 (layout.html)

기존 `base.html`과 별도로 admin 전용 레이아웃을 만든다:
- 좌측 또는 상단 탭 네비게이션
- 승인 대기 건수 배지
- 관리자 정보 표시
- 반응형 (모바일에서도 사용 가능)

### 10.2 검색/필터 패턴

서버 사이드 렌더링 기반:

```
URL: /admin/members?q=김&status=active&type=player&page=2&limit=50

→ Supabase 쿼리:
  .select("*")
  .ilike("full_name", "%김%")
  .eq("member_status", "active")
  .eq("member_type", "player")
  .order("created_at", desc=True)
  .range(50, 99)
```

### 10.3 감사 로그 자동 기록

모든 admin API에 감사 로그를 자동 기록하는 헬퍼 함수:

```python
async def log_admin_action(
    db, admin_id: str, action: str,
    target_type: str, target_id: str,
    details: dict = None, ip: str = None
):
    await db.table("admin_audit_logs").insert({
        "admin_member_id": admin_id,
        "action": action,
        "target_type": target_type,
        "target_id": target_id,
        "details": details,
        "ip_address": ip,
    }).execute()
```

### 10.4 보안

- Admin 페이지는 `admin_role IS NOT NULL`인 회원만 접근
- 모든 쓰기 작업에 CSRF 토큰 적용
- 감사 로그는 삭제 불가 (append-only)
- 민감 정보(전화번호 등)는 관리자 화면에서도 부분 마스킹
- Admin 페이지 접근 시 IP 로깅

---

## 11. 의존성

| 의존 항목 | 현재 상태 | 필요 조치 |
|----------|----------|----------|
| Admin API 기존 6개 | ✅ 구현됨 | 통합 승인 큐로 확장 |
| Gemini 인증 결과 | ✅ verifications 테이블 | 심사 UI에서 표시 |
| Player Claim 테이블 | ❌ Migration 013 | 인증 시스템 PRD와 함께 구현 |
| Organization Claim | ❌ Migration 013 | 인증 시스템 PRD와 함께 구현 |
| PlayerIdentityResolver | ✅ data 서비스 | 선수 병합/분리 API 노출 |
| club_settings 테이블 | ✅ Migration 004 | Club 탭에서 조회 |

### PRD_member_verification.md와의 관계

이 PRD의 **Phase 2 (승인 큐)**는 인증 시스템 PRD의 테이블(player_claims, organization_claims, data_correction_requests)에 의존한다. 따라서:

```
구현 순서:
1. Migration 013 (인증 시스템 테이블) — PRD_member_verification Phase 1
2. Migration 014 (Admin 테이블) — 이 PRD Phase 1
3. Admin 기본 골격 + 회원 관리 — 이 PRD Phase 1
4. Player Claim API — PRD_member_verification Phase 1
5. 승인 큐 UI — 이 PRD Phase 2 (4번과 병행 가능)
```

---

## 12. 성공 지표

| 지표 | Phase 1 목표 | Phase 4 목표 |
|------|:----------:|:----------:|
| 승인 요청 처리 시간 | 24시간 내 | 4시간 내 |
| 회원 검색→상세 조회 | 3클릭 이내 | 2클릭 이내 |
| 자동 승인 비율 (조직 인증) | 60% | 80% |
| 감사 로그 커버리지 | 관리자 쓰기 100% | 읽기 포함 100% |
| 관리자 페이지 로드 시간 | 2초 이내 | 1초 이내 |
