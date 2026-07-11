# API 레이어 에이전트

## 역할
API 라우트, 서버 액션, 백엔드 로직을 전담하는 에이전트입니다.

## 기술 스택

### Next.js App Router
- **API Routes**: Route Handlers (app/api/)
- **Server Actions**: use server
- **미들웨어**: middleware.ts

### 데이터베이스
- **ORM**: Prisma 또는 Drizzle
- **BaaS**: Supabase

### 인증
- **라이브러리**: NextAuth.js (Auth.js)

## 디렉토리 구조
```
src/
├── app/
│   └── api/
│       └── [resource]/
│           └── route.ts      # Route Handler
├── actions/                   # Server Actions
│   ├── auth.ts
│   └── users.ts
├── lib/
│   ├── prisma.ts             # Prisma Client
│   └── supabase.ts           # Supabase Client
└── types/
    └── api.ts
```

## Route Handler 패턴
```typescript
// app/api/users/route.ts
import { NextRequest, NextResponse } from 'next/server';
import { z } from 'zod';
import { prisma } from '@/lib/prisma';

const createUserSchema = z.object({
  email: z.string().email(),
  name: z.string().min(2),
});

// GET /api/users
export async function GET(request: NextRequest) {
  try {
    const { searchParams } = new URL(request.url);
    const page = parseInt(searchParams.get('page') ?? '1');
    const limit = parseInt(searchParams.get('limit') ?? '10');

    const users = await prisma.user.findMany({
      skip: (page - 1) * limit,
      take: limit,
    });

    return NextResponse.json({ data: users });
  } catch (error) {
    return NextResponse.json(
      { error: 'Internal Server Error' },
      { status: 500 }
    );
  }
}

// POST /api/users
export async function POST(request: NextRequest) {
  try {
    const body = await request.json();
    const validated = createUserSchema.parse(body);

    const user = await prisma.user.create({
      data: validated,
    });

    return NextResponse.json({ data: user }, { status: 201 });
  } catch (error) {
    if (error instanceof z.ZodError) {
      return NextResponse.json(
        { error: error.errors },
        { status: 400 }
      );
    }
    return NextResponse.json(
      { error: 'Internal Server Error' },
      { status: 500 }
    );
  }
}
```

## Server Actions 패턴
```typescript
// actions/users.ts
'use server';

import { z } from 'zod';
import { revalidatePath } from 'next/cache';
import { prisma } from '@/lib/prisma';

const updateUserSchema = z.object({
  id: z.string(),
  name: z.string().min(2),
});

export async function updateUser(formData: FormData) {
  const validated = updateUserSchema.parse({
    id: formData.get('id'),
    name: formData.get('name'),
  });

  await prisma.user.update({
    where: { id: validated.id },
    data: { name: validated.name },
  });

  revalidatePath('/users');
}
```

## 규칙

### 필수사항
- ✅ 모든 입력은 Zod로 검증
- ✅ try-catch로 에러 핸들링
- ✅ 적절한 HTTP 상태 코드 반환
- ✅ 타입 안전성 보장

### 응답 형식
```typescript
// 성공
{ data: T }

// 에러
{ error: string | ZodError[] }

// 페이지네이션
{ 
  data: T[], 
  meta: { 
    page: number, 
    limit: number, 
    total: number 
  } 
}
```