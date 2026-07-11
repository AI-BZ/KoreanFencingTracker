# 폼 레이어 에이전트

## 역할
폼 생성, 검증, 제출 처리를 전담하는 에이전트입니다.

## 기술 스택 (필수)
- **폼 관리**: React Hook Form (필수)
- **스키마 검증**: Zod (필수)
- **UI 컴포넌트**: Shadcn UI Form

## 폼 작성 패턴

### 기본 템플릿
```typescript
import { useForm } from 'react-hook-form';
import { zodResolver } from '@hookform/resolvers/zod';
import { z } from 'zod';
import {
  Form,
  FormControl,
  FormField,
  FormItem,
  FormLabel,
  FormMessage,
} from '@/components/ui/form';
import { Input } from '@/components/ui/input';
import { Button } from '@/components/ui/button';

// 1. Zod 스키마 정의
const formSchema = z.object({
  email: z.string().email('유효한 이메일을 입력하세요'),
  password: z.string().min(8, '최소 8자 이상 입력하세요'),
});

type FormValues = z.infer<typeof formSchema>;

// 2. 컴포넌트
export function LoginForm() {
  const form = useForm<FormValues>({
    resolver: zodResolver(formSchema),
    defaultValues: {
      email: '',
      password: '',
    },
  });

  const onSubmit = (values: FormValues) => {
    console.log(values);
  };

  return (
    <Form {...form}>
      <form onSubmit={form.handleSubmit(onSubmit)} className="space-y-4">
        <FormField
          control={form.control}
          name="email"
          render={({ field }) => (
            <FormItem>
              <FormLabel>이메일</FormLabel>
              <FormControl>
                <Input placeholder="email@example.com" {...field} />
              </FormControl>
              <FormMessage />
            </FormItem>
          )}
        />
        
        <FormField
          control={form.control}
          name="password"
          render={({ field }) => (
            <FormItem>
              <FormLabel>비밀번호</FormLabel>
              <FormControl>
                <Input type="password" {...field} />
              </FormControl>
              <FormMessage />
            </FormItem>
          )}
        />
        
        <Button type="submit" disabled={form.formState.isSubmitting}>
          {form.formState.isSubmitting ? '처리 중...' : '로그인'}
        </Button>
      </form>
    </Form>
  );
}
```

## Zod 스키마 패턴

### 공통 스키마 (재사용)
```typescript
// src/lib/validations/common.ts
import { z } from 'zod';

export const emailSchema = z
  .string()
  .email('유효한 이메일을 입력하세요');

export const passwordSchema = z
  .string()
  .min(8, '최소 8자 이상')
  .regex(/[A-Z]/, '대문자 포함 필수')
  .regex(/[0-9]/, '숫자 포함 필수');

export const phoneSchema = z
  .string()
  .regex(/^01[0-9]-\d{4}-\d{4}$/, '올바른 전화번호 형식이 아닙니다');
```

### 폼별 스키마
```typescript
// src/lib/validations/auth.ts
import { z } from 'zod';
import { emailSchema, passwordSchema } from './common';

export const loginSchema = z.object({
  email: emailSchema,
  password: z.string().min(1, '비밀번호를 입력하세요'),
});

export const registerSchema = z.object({
  email: emailSchema,
  password: passwordSchema,
  confirmPassword: z.string(),
}).refine((data) => data.password === data.confirmPassword, {
  message: '비밀번호가 일치하지 않습니다',
  path: ['confirmPassword'],
});
```

## 디렉토리 구조
```
src/
├── lib/
│   └── validations/       # Zod 스키마
│       ├── common.ts
│       ├── auth.ts
│       └── user.ts
└── components/
    └── forms/             # 폼 컴포넌트
        ├── LoginForm.tsx
        └── RegisterForm.tsx
```

## 규칙

### 필수사항
- ✅ 모든 폼은 Zod 스키마로 검증
- ✅ Shadcn UI Form 컴포넌트 사용
- ✅ 에러 메시지는 언어페이지별 언어에 맞는 것으로 작성
- ✅ 제출 중 버튼 비활성화
- ✅ 언어 페이지별 언어에 맞는 Form 사용

### 금지사항
- ❌ Formik 사용 금지
- ❌ 수동 유효성 검사 금지