# Phase 2: 클럽 공개 페이지 기능

## 개요
클럽 감독/코치가 자신들의 클럽을 홍보할 수 있는 공개 페이지 제공

## URL 구조
- `/clubs/{club_slug}` - 클럽 공개 페이지
- 예: `/clubs/choibyungchul-fencing` (최병철펜싱클럽)

## 필수 기능

### 1. 클럽 정보
- 클럽명, 로고
- 감독 사진 및 소개
- 코치진 사진 및 소개
- 클럽 설립년도, 역사

### 2. 최근 대회 성적
- 우수 선수 성적 자동 정리
- 대회별/선수별 성과 하이라이트
- 메달/입상 카운트

### 3. 소셜 미디어 연동
- Instagram 링크/피드 임베드
- Facebook 페이지 연결
- 공식 홈페이지 링크
- YouTube 채널 (선택)

### 4. 위치 및 연락처
- Google Maps 지도 임베드
- 주소 표시
- 전화번호
- 이메일
- 카카오톡 채널 (선택)

### 5. 클럽 홍보
- 홍보 배너/슬라이드
- 수강 안내 (월회비, 레슨비 등)
- 시설 사진 갤러리
- 모집 공고

### 6. 관리 기능 (감독/코치용)
- 정보 편집 인터페이스
- 이미지 업로드
- 공지사항 작성
- SEO 설정 (메타 태그)

### 7. 레슨 예약 시스템 (핵심 기능)

#### 7.1 코치별 스케줄 공개
- 각 코치의 주간 레슨 스케줄 표시
- **예약된 시간**: "예약됨" 표시 (수강생 이름 비공개)
- **빈 시간**: "예약 가능" 표시 (클릭하여 예약 가능)
- 30분/1시간 단위 시간대 슬롯

#### 7.2 예약 프로세스
1. **학생/부모**: 코치 선택 → 빈 시간대 클릭 → 예약 신청
2. **시스템**: 카카오톡 알림 발송 (코치에게)
3. **코치**: 카카오톡/웹에서 승인/거절
4. **시스템**: 승인 결과 알림 (학생/부모에게)

#### 7.3 예약 관리
- 예약 취소 (24시간 전까지)
- 정기 레슨 설정 (매주 같은 시간)
- 예약 변경 요청
- 노쇼(No-show) 관리

#### 7.4 알림 연동
- **카카오톡 채널**: 예약 알림, 리마인더, 취소 알림
- **웹 알림**: 대시보드 내 알림
- **SMS (선택)**: 카카오톡 미사용자

#### 7.5 결제 연동 (Phase 2B)
- 레슨 예약 시 선결제 옵션
- Toss Payments 연동
- 취소 시 환불 처리

## 데이터베이스 추가 필요
```sql
-- organizations 테이블 확장
ALTER TABLE organizations ADD COLUMN slug VARCHAR(100) UNIQUE;
ALTER TABLE organizations ADD COLUMN logo_url TEXT;
ALTER TABLE organizations ADD COLUMN description TEXT;
ALTER TABLE organizations ADD COLUMN founded_year INTEGER;
ALTER TABLE organizations ADD COLUMN phone VARCHAR(20);
ALTER TABLE organizations ADD COLUMN email VARCHAR(100);
ALTER TABLE organizations ADD COLUMN website_url TEXT;
ALTER TABLE organizations ADD COLUMN instagram_url TEXT;
ALTER TABLE organizations ADD COLUMN facebook_url TEXT;
ALTER TABLE organizations ADD COLUMN youtube_url TEXT;
ALTER TABLE organizations ADD COLUMN kakao_channel TEXT;
ALTER TABLE organizations ADD COLUMN latitude DECIMAL(10, 8);
ALTER TABLE organizations ADD COLUMN longitude DECIMAL(11, 8);
ALTER TABLE organizations ADD COLUMN photos JSONB;  -- 시설 사진들
ALTER TABLE organizations ADD COLUMN banner_images JSONB;
ALTER TABLE organizations ADD COLUMN fee_info JSONB;  -- 수강료 정보
ALTER TABLE organizations ADD COLUMN is_public BOOLEAN DEFAULT false;

-- 코치 프로필 테이블
CREATE TABLE coach_profiles (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    member_id UUID REFERENCES members(id),
    organization_id BIGINT REFERENCES organizations(id),
    photo_url TEXT,
    bio TEXT,
    certifications JSONB,
    specialties TEXT[],
    display_order INTEGER DEFAULT 0,
    is_visible BOOLEAN DEFAULT true,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- 코치 주간 스케줄 (기본 근무 시간)
CREATE TABLE coach_schedules (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    coach_member_id UUID REFERENCES members(id),
    organization_id BIGINT REFERENCES organizations(id),
    day_of_week INTEGER NOT NULL,  -- 0=일, 1=월, ..., 6=토
    start_time TIME NOT NULL,
    end_time TIME NOT NULL,
    slot_duration INTEGER DEFAULT 60,  -- 슬롯 길이 (분)
    is_available BOOLEAN DEFAULT true,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- 레슨 예약 테이블
CREATE TABLE lesson_bookings (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id BIGINT REFERENCES organizations(id),
    coach_member_id UUID REFERENCES members(id),
    student_member_id UUID REFERENCES members(id),
    booking_date DATE NOT NULL,
    start_time TIME NOT NULL,
    end_time TIME NOT NULL,
    status VARCHAR(20) DEFAULT 'pending',  -- pending, approved, rejected, cancelled, completed
    lesson_type VARCHAR(30),  -- individual, group, trial
    notes TEXT,
    requested_by UUID REFERENCES members(id),  -- 예약 신청자 (학부모 가능)
    approved_by UUID REFERENCES members(id),
    approved_at TIMESTAMPTZ,
    cancelled_at TIMESTAMPTZ,
    cancel_reason TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- 정기 레슨 설정 (반복 예약)
CREATE TABLE recurring_lessons (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id BIGINT REFERENCES organizations(id),
    coach_member_id UUID REFERENCES members(id),
    student_member_id UUID REFERENCES members(id),
    day_of_week INTEGER NOT NULL,
    start_time TIME NOT NULL,
    end_time TIME NOT NULL,
    start_date DATE NOT NULL,
    end_date DATE,  -- NULL이면 무기한
    is_active BOOLEAN DEFAULT true,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- 예약 알림 로그
CREATE TABLE booking_notifications (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    booking_id UUID REFERENCES lesson_bookings(id),
    notification_type VARCHAR(30) NOT NULL,  -- request, approval, rejection, reminder, cancellation
    channel VARCHAR(20) NOT NULL,  -- kakao, sms, web
    recipient_id UUID REFERENCES members(id),
    sent_at TIMESTAMPTZ,
    status VARCHAR(20) DEFAULT 'pending',  -- pending, sent, failed
    error_message TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW()
);
```

## 우선순위

### Phase 2A (클럽 공개 페이지)
- **높음**: 기본 정보, 연락처, 지도
- **중간**: 소셜 미디어, 성적 자동 정리
- **낮음**: 갤러리, 배너 슬라이드, SEO

### Phase 2B (레슨 예약 시스템)
- **높음**: 코치 스케줄 공개, 예약 신청/승인, 카카오톡 알림
- **중간**: 정기 레슨 설정, 예약 취소/변경
- **낮음**: 결제 연동, 노쇼 관리

## 예상 일정
- Phase 2A (공개 페이지): 1-2주
- Phase 2B (예약 시스템): 2-3주 (카카오톡 연동 포함)
