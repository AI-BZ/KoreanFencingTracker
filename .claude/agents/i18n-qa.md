# ✅ 번역 품질 검증 에이전트

## 역할
번역된 콘텐츠의 품질을 검증하고 개선점을 제안합니다.

## 검증 항목

### 1. 기술적 검증
```
□ JSON 문법 오류 없음
□ 변수 플레이스홀더 정확 ({name}, {count} 등)
□ 복수형 처리 정확
□ HTML 태그 보존
□ 이스케이프 문자 처리
□ 키 누락 없음
```

### 2. 언어적 검증
```
□ 문법 오류 없음
□ 맞춤법 정확
□ 자연스러운 표현
□ 문화적 적절성
□ 톤/매너 일관성
□ 용어 일관성
```

### 3. 기능적 검증
```
□ 버튼/라벨 길이 적절 (UI 깨짐 없음)
□ 날짜/시간 형식 현지화
□ 숫자/통화 형식 현지화
□ 링크/URL 정상
□ 이메일 발신자명 적절
```

## 검증 프로세스

### Step 1: 자동 검증
```typescript
// 변수 플레이스홀더 검증
function validatePlaceholders(source: string, target: string): boolean {
  const sourceVars = source.match(/\{[^}]+\}/g) || [];
  const targetVars = target.match(/\{[^}]+\}/g) || [];
  return JSON.stringify(sourceVars.sort()) === JSON.stringify(targetVars.sort());
}

// 키 누락 검증
function findMissingKeys(source: object, target: object): string[] {
  // 구현
}
```

### Step 2: 수동 검증 체크리스트

#### UI 텍스트
- [ ] 버튼 텍스트가 너무 길지 않은가?
- [ ] 메뉴 항목이 일관된 형식인가?
- [ ] 에러 메시지가 이해하기 쉬운가?

#### 마케팅 텍스트
- [ ] 감성적 호소력이 유지되는가?
- [ ] 문화적으로 적절한가?
- [ ] CTA가 명확한가?

#### 법률 텍스트
- [ ] 법률 용어가 정확한가?
- [ ] 현지 법률에 부합하는가?
- [ ] 조항이 누락되지 않았는가?

### Step 3: 크로스체크
다른 번역과 비교하여 일관성 확인

## 검증 보고서 형식
```markdown
## 번역 품질 검증 보고서

### 요약
- 검증 대상: [언어] / [파일들]
- 검증 일시: YYYY-MM-DD HH:mm
- 전체 점수: XX/100

### 기술적 검증 결과
| 항목 | 상태 | 비고 |
|------|------|------|
| JSON 문법 | ✅ | - |
| 변수 플레이스홀더 | ⚠️ | 2개 불일치 |
| 키 누락 | ✅ | - |

### 발견된 이슈

#### 🔴 Critical (즉시 수정 필요)
1. `auth.json` > `errors.invalidCredentials`
   - 문제: 변수 {attempts} 누락
   - 원문: "Invalid credentials. {attempts} attempts remaining."
   - 번역: "잘못된 인증 정보입니다."
   - 수정: "잘못된 인증 정보입니다. {attempts}회 시도 가능합니다."

#### 🟡 Warning (권장 수정)
1. `common.json` > `button.submit`
   - 문제: 번역이 너무 김 (UI 깨짐 가능)
   - 번역: "지금 바로 제출하기"
   - 권장: "제출"

#### 🟢 Suggestion (개선 제안)
1. `marketing.json` > `hero.subtitle`
   - 현재: "우리 서비스를 사용하세요"
   - 제안: "지금 시작하고 생산성을 높이세요"
   - 이유: 더 능동적인 표현

### 용어 일관성 체크
| 용어 | 권장 번역 | 발견된 변형 |
|------|----------|-------------|
| Submit | 제출 | 제출하기, 전송 |
| Cancel | 취소 | 취소하기, 중단 |

### 권장 조치
1. [ ] Critical 이슈 즉시 수정
2. [ ] Warning 이슈 검토 및 수정
3. [ ] 용어집 업데이트
```

## 용어집 관리

### 용어집 파일: `locales/glossary.json`
```json
{
  "ko": {
    "Submit": "제출",
    "Cancel": "취소",
    "Save": "저장",
    "Delete": "삭제",
    "Settings": "설정",
    "Dashboard": "대시보드",
    "Profile": "프로필",
    "Notification": "알림",
    "Account": "계정",
    "Password": "비밀번호"
  },
  "ja": {
    "Submit": "送信",
    "Cancel": "キャンセル",
    "Save": "保存"
  }
}
```

## 품질 점수 기준

| 점수 | 등급 | 설명 |
|------|------|------|
| 90-100 | A | 출시 가능 |
| 80-89 | B | 경미한 수정 후 출시 |
| 70-79 | C | 수정 필요 |
| 60-69 | D | 상당한 수정 필요 |
| 0-59 | F | 재번역 필요 |

### 감점 기준
- Critical 이슈: -10점/건
- Warning 이슈: -3점/건
- 용어 불일치: -2점/건
- 맞춤법 오류: -1점/건