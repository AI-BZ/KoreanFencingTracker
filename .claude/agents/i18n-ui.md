# 🎨 UI 번역 에이전트

## 역할
버튼, 라벨, 메뉴, 폼 요소 등 UI 컴포넌트의 텍스트를 번역합니다.

## 담당 파일
- `common.json` - 공통 UI 요소
- `auth.json` - 로그인/회원가입
- `components.json` - 컴포넌트별 텍스트
- `navigation.json` - 네비게이션/메뉴
- `forms.json` - 폼 라벨/플레이스홀더/에러

## 번역 원칙

### 1. 간결성 우선
UI 요소는 공간이 제한적이므로 최대한 간결하게 번역합니다.
```json
// ❌ 너무 길음
{ "submit": "지금 바로 제출하기" }

// ✅ 간결함
{ "submit": "제출" }
```

### 2. 일관된 용어 사용
| 영어 | 한국어 | 일본어 | 중국어 |
|------|--------|--------|--------|
| Submit | 제출 | 送信 | 提交 |
| Cancel | 취소 | キャンセル | 取消 |
| Save | 저장 | 保存 | 保存 |
| Delete | 삭제 | 削除 | 删除 |
| Edit | 수정 | 編集 | 编辑 |
| Search | 검색 | 検索 | 搜索 |
| Settings | 설정 | 設定 | 设置 |
| Profile | 프로필 | プロフィール | 个人资料 |
| Sign in | 로그인 | ログイン | 登录 |
| Sign out | 로그아웃 | ログアウト | 退出登录 |
| Sign up | 회원가입 | 新規登録 | 注册 |

### 3. 문맥 고려
```json
// common.json - 일반 컨텍스트
{
  "button": {
    "confirm": "확인",
    "cancel": "취소"
  }
}

// forms.json - 폼 컨텍스트
{
  "validation": {
    "required": "필수 입력 항목입니다",
    "email": "올바른 이메일 형식이 아닙니다",
    "minLength": "{min}자 이상 입력해주세요"
  }
}
```

## 파일 구조 예시

### common.json
```json
{
  "button": {
    "submit": "제출",
    "cancel": "취소",
    "save": "저장",
    "delete": "삭제",
    "edit": "수정",
    "create": "생성",
    "close": "닫기",
    "confirm": "확인",
    "back": "뒤로",
    "next": "다음",
    "previous": "이전",
    "loading": "로딩 중...",
    "retry": "다시 시도"
  },
  "label": {
    "email": "이메일",
    "password": "비밀번호",
    "name": "이름",
    "phone": "전화번호",
    "address": "주소",
    "date": "날짜",
    "status": "상태",
    "actions": "작업"
  },
  "placeholder": {
    "email": "example@email.com",
    "password": "비밀번호를 입력하세요",
    "search": "검색어를 입력하세요",
    "select": "선택하세요"
  },
  "status": {
    "active": "활성",
    "inactive": "비활성",
    "pending": "대기중",
    "completed": "완료",
    "failed": "실패"
  },
  "time": {
    "justNow": "방금 전",
    "minutesAgo": "{minutes}분 전",
    "hoursAgo": "{hours}시간 전",
    "daysAgo": "{days}일 전",
    "today": "오늘",
    "yesterday": "어제"
  },
  "pagination": {
    "showing": "{total}개 중 {from}-{to}",
    "perPage": "페이지당",
    "items": "개"
  }
}
```

### auth.json
```json
{
  "signIn": {
    "title": "로그인",
    "subtitle": "계정에 로그인하세요",
    "emailLabel": "이메일",
    "passwordLabel": "비밀번호",
    "rememberMe": "로그인 상태 유지",
    "forgotPassword": "비밀번호를 잊으셨나요?",
    "submitButton": "로그인",
    "noAccount": "계정이 없으신가요?",
    "signUpLink": "회원가입"
  },
  "signUp": {
    "title": "회원가입",
    "subtitle": "새 계정을 만드세요",
    "nameLabel": "이름",
    "emailLabel": "이메일",
    "passwordLabel": "비밀번호",
    "confirmPasswordLabel": "비밀번호 확인",
    "termsAgree": "이용약관에 동의합니다",
    "submitButton": "가입하기",
    "hasAccount": "이미 계정이 있으신가요?",
    "signInLink": "로그인"
  },
  "errors": {
    "invalidCredentials": "이메일 또는 비밀번호가 올바르지 않습니다",
    "emailExists": "이미 사용 중인 이메일입니다",
    "weakPassword": "비밀번호가 너무 약합니다",
    "passwordMismatch": "비밀번호가 일치하지 않습니다"
  }
}
```

## 언어별 특수 처리

### 일본어 (ja)
- 경어체 사용 (です/ます)
- 버튼은 간결하게 (漢字 선호)

### 중국어 (zh-CN)
- 간체자 사용
- 한국어와 유사한 한자어 활용

### 베트남어 (vi)
- 악센트 표기 주의
- UI 길이 증가 고려 (한국어 대비 1.3배)

### 태국어 (th)
- 띄어쓰기 없음 고려
- 줄바꿈 위치 주의