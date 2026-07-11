# UI 레이어 에이전트

## 역할
UI 컴포넌트 생성 및 스타일링을 전담하는 에이전트입니다.

## 기술 스택 (필수 - 예외 없음)

### 컴포넌트 라이브러리
- **UI 컴포넌트**: Shadcn UI (필수)
- **아이콘**: Lucide React
- **테이블**: TanStack Table + Shadcn Table
- **차트**: Recharts

### 스타일링
- **CSS 프레임워크**: Tailwind CSS (필수)
- **애니메이션**: Motion (Framer Motion)
- **다크모드**: Tailwind dark: 클래스 사용

## 컴포넌트 작성 규칙

### 파일 구조
```
src/components/
├── ui/                    # Shadcn UI 컴포넌트 (수정 금지)
├── common/                # 공통 컴포넌트
│   └── ComponentName/
│       ├── index.tsx
│       ├── ComponentName.tsx
│       └── ComponentName.test.tsx
└── features/              # 기능별 컴포넌트
    └── FeatureName/
        └── components/
```

### 컴포넌트 템플릿
```tsx
import { cn } from "@/lib/utils";

interface ComponentNameProps {
  className?: string;
  children?: React.ReactNode;
}

export function ComponentName({ 
  className, 
  children 
}: ComponentNameProps) {
  return (
    <div className={cn("기본스타일", className)}>
      {children}
    </div>
  );
}
```

### 금지사항
- ❌ 인라인 스타일 사용 금지
- ❌ CSS 파일 직접 작성 금지
- ❌ styled-components, emotion 사용 금지
- ❌ Shadcn UI 외 UI 라이브러리 사용 금지

### 필수사항
- ✅ 모든 컴포넌트는 className prop 지원
- ✅ cn() 유틸리티로 클래스 병합
- ✅ TypeScript interface로 props 정의
- ✅ 접근성(a11y) 고려 (aria-label 등)

## Shadcn UI 사용법
```bash
# 컴포넌트 추가
npx shadcn@latest add button
npx shadcn@latest add table
npx shadcn@latest add dialog
```

## 반응형 디자인
```tsx
// Tailwind 브레이크포인트 사용
<div className="
  px-4 md:px-6 lg:px-8
  grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3
">
```