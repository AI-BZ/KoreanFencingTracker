# 📧 이메일/알림 번역 에이전트

## 역할
이메일 템플릿, 푸시 알림, 시스템 메시지를 번역합니다.

## 담당 파일
- `emails.json` - 이메일 템플릿
- `notifications.json` - 알림 메시지
- `sms.json` - SMS 템플릿
- `errors.json` - 에러 메시지

## 번역 원칙

### 1. 개인화된 톤
이메일은 1:1 소통이므로 개인화된 느낌을 줍니다.
```json
// ❌ 비개인적
{
  "ko": "비밀번호가 변경되었습니다."
}

// ✅ 개인화
{
  "ko": "{name}님, 비밀번호가 성공적으로 변경되었습니다."
}
```

### 2. 명확한 행동 유도
이메일의 목적과 다음 행동이 명확해야 합니다.

### 3. 변수 처리
모든 동적 값은 변수로 처리합니다.
```
{name} - 사용자 이름
{email} - 이메일
{date} - 날짜
{link} - 링크
{code} - 인증 코드
{amount} - 금액
```

## 파일 구조 예시

### emails.json
```json
{
  "welcome": {
    "subject": "{name}님, 가입을 환영합니다! 🎉",
    "preview": "서비스 시작을 위한 안내를 확인하세요",
    "greeting": "안녕하세요, {name}님!",
    "body": [
      "{serviceName}에 가입해 주셔서 감사합니다.",
      "지금 바로 서비스를 시작해 보세요."
    ],
    "cta": "시작하기",
    "tips": {
      "title": "시작하기 팁",
      "items": [
        "프로필을 완성하세요",
        "팀원을 초대하세요",
        "첫 프로젝트를 만들어 보세요"
      ]
    },
    "footer": "도움이 필요하시면 언제든 문의해 주세요."
  },
  "verification": {
    "subject": "이메일 인증을 완료해 주세요",
    "preview": "인증 코드: {code}",
    "greeting": "안녕하세요, {name}님!",
    "body": "아래 인증 코드를 입력하여 이메일 인증을 완료해 주세요.",
    "code": "{code}",
    "codeLabel": "인증 코드",
    "expiry": "이 코드는 {minutes}분 동안 유효합니다.",
    "warning": "본인이 요청하지 않으셨다면 이 이메일을 무시해 주세요.",
    "alternativeLink": "또는 아래 링크를 클릭하세요:",
    "cta": "이메일 인증하기"
  },
  "passwordReset": {
    "subject": "비밀번호 재설정 안내",
    "preview": "비밀번호를 재설정하세요",
    "greeting": "안녕하세요, {name}님!",
    "body": "비밀번호 재설정이 요청되었습니다. 아래 버튼을 클릭하여 새 비밀번호를 설정하세요.",
    "cta": "비밀번호 재설정",
    "expiry": "이 링크는 {hours}시간 동안 유효합니다.",
    "warning": "본인이 요청하지 않으셨다면 이 이메일을 무시해 주세요. 비밀번호는 변경되지 않습니다."
  },
  "passwordChanged": {
    "subject": "비밀번호가 변경되었습니다",
    "preview": "계정 보안 알림",
    "greeting": "안녕하세요, {name}님!",
    "body": "계정의 비밀번호가 성공적으로 변경되었습니다.",
    "details": {
      "time": "변경 시간: {datetime}",
      "device": "기기: {device}",
      "location": "위치: {location}"
    },
    "warning": "본인이 변경하지 않으셨다면 즉시 고객센터로 연락해 주세요.",
    "cta": "계정 보안 확인"
  },
  "invoice": {
    "subject": "결제 완료 안내 - {invoiceNumber}",
    "preview": "{amount} 결제가 완료되었습니다",
    "greeting": "안녕하세요, {name}님!",
    "body": "결제가 성공적으로 처리되었습니다.",
    "details": {
      "invoiceNumber": "청구서 번호",
      "date": "결제일",
      "amount": "결제 금액",
      "method": "결제 수단",
      "plan": "구독 플랜"
    },
    "cta": "청구서 보기",
    "support": "결제 관련 문의: billing@company.com"
  },
  "trialEnding": {
    "subject": "{name}님, 무료 체험이 곧 종료됩니다",
    "preview": "{daysLeft}일 후 무료 체험이 종료됩니다",
    "greeting": "안녕하세요, {name}님!",
    "body": [
      "무료 체험 기간이 {daysLeft}일 남았습니다.",
      "서비스를 계속 이용하시려면 구독을 시작해 주세요."
    ],
    "benefits": {
      "title": "구독 시 혜택",
      "items": [
        "모든 기능 무제한 이용",
        "우선 고객 지원",
        "데이터 영구 보존"
      ]
    },
    "cta": "지금 구독하기",
    "discount": "지금 구독하시면 첫 달 20% 할인!"
  }
}
```

### notifications.json
```json
{
  "push": {
    "newMessage": {
      "title": "새 메시지",
      "body": "{sender}님이 메시지를 보냈습니다"
    },
    "mention": {
      "title": "멘션됨",
      "body": "{user}님이 '{project}'에서 회원님을 멘션했습니다"
    },
    "taskAssigned": {
      "title": "새 작업 할당",
      "body": "'{taskName}' 작업이 할당되었습니다"
    },
    "taskDue": {
      "title": "작업 마감 임박",
      "body": "'{taskName}' 마감이 {timeLeft} 남았습니다"
    },
    "commentReply": {
      "title": "댓글 답글",
      "body": "{user}님이 회원님의 댓글에 답글을 남겼습니다"
    }
  },
  "inApp": {
    "welcome": "환영합니다, {name}님! 🎉",
    "profileComplete": "프로필이 완성되었습니다!",
    "teamJoined": "'{teamName}' 팀에 참여했습니다",
    "upgradeSuccess": "프로 플랜으로 업그레이드되었습니다",
    "exportReady": "내보내기가 완료되었습니다. 다운로드하세요.",
    "maintenanceScheduled": "예정된 점검: {date} {time}"
  },
  "toast": {
    "saved": "저장되었습니다",
    "deleted": "삭제되었습니다",
    "copied": "클립보드에 복사되었습니다",
    "sent": "전송되었습니다",
    "updated": "업데이트되었습니다",
    "error": "오류가 발생했습니다. 다시 시도해 주세요."
  }
}
```

### errors.json
```json
{
  "network": {
    "offline": "인터넷 연결이 끊어졌습니다",
    "timeout": "요청 시간이 초과되었습니다",
    "serverError": "서버 오류가 발생했습니다. 잠시 후 다시 시도해 주세요."
  },
  "auth": {
    "sessionExpired": "세션이 만료되었습니다. 다시 로그인해 주세요.",
    "unauthorized": "접근 권한이 없습니다",
    "invalidToken": "인증 정보가 유효하지 않습니다"
  },
  "validation": {
    "required": "필수 입력 항목입니다",
    "invalidEmail": "올바른 이메일 형식이 아닙니다",
    "invalidPhone": "올바른 전화번호 형식이 아닙니다",
    "passwordTooShort": "비밀번호는 최소 {min}자 이상이어야 합니다",
    "passwordMismatch": "비밀번호가 일치하지 않습니다",
    "fileTooLarge": "파일 크기는 {max}MB를 초과할 수 없습니다",
    "invalidFileType": "지원하지 않는 파일 형식입니다"
  },
  "generic": {
    "somethingWentWrong": "문제가 발생했습니다",
    "tryAgain": "다시 시도해 주세요",
    "contactSupport": "문제가 계속되면 고객센터로 문의해 주세요"
  }
}
```

## 언어별 이메일 톤

### 한국어
- "~님" 존칭 사용
- 정중하고 친근한 톤
- 이모지 적절히 사용 가능

### 일본어
- "様" 존칭 사용
- 매우 정중한 톤
- 이모지 자제

### 영어
- First name 직접 사용
- 친근하고 직접적인 톤
- 이모지 자유롭게 사용

### 중국어
- "您" 존칭 사용
- 간결하고 명확한 톤
- 이모지 자제