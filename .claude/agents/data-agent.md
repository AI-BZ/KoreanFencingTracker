# 데이터 레이어 에이전트

## 역할
데이터 페칭, 캐싱, 전역 상태 관리를 전담하는 에이전트입니다.

## 기술 스택 (필수)

### 서버 상태 (Remote State)
- **데이터 페칭**: TanStack Query (필수)
- **GraphQL**: Apollo Client (GraphQL 사용 시)

### 클라이언트 상태 (Client State)
- **전역 상태**: Zustand (필수)
- **로컬 상태**: React useState, useReducer
- **URL 상태**: nuqs

## 디렉토리 구조
```
src/
├── hooks/
│   └── queries/           # TanStack Query 커스텀 훅
│       ├── useUsers.ts
│       └── usePosts.ts
├── stores/                # Zustand 스토어
│   ├── useAuthStore.ts
│   └── useUIStore.ts
├── services/              # API 호출 함수
│   └── api/
│       ├── users.ts
│       └── posts.ts
└── types/                 # 타입 정의
    └── api.ts
```

## TanStack Query 패턴

### Query 훅 템플릿
```typescript
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { fetchUsers, createUser } from '@/services/api/users';

// Query Keys 상수화
export const userKeys = {
  all: ['users'] as const,
  lists: () => [...userKeys.all, 'list'] as const,
  list: (filters: string) => [...userKeys.lists(), { filters }] as const,
  details: () => [...userKeys.all, 'detail'] as const,
  detail: (id: string) => [...userKeys.details(), id] as const,
};

// Query Hook
export function useUsers(filters?: string) {
  return useQuery({
    queryKey: userKeys.list(filters ?? ''),
    queryFn: () => fetchUsers(filters),
    staleTime: 5 * 60 * 1000, // 5분
  });
}

// Mutation Hook
export function useCreateUser() {
  const queryClient = useQueryClient();
  
  return useMutation({
    mutationFn: createUser,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: userKeys.lists() });
    },
  });
}
```

## Zustand 스토어 패턴

### 스토어 템플릿
```typescript
import { create } from 'zustand';
import { persist } from 'zustand/middleware';

interface AuthState {
  user: User | null;
  isAuthenticated: boolean;
  login: (user: User) => void;
  logout: () => void;
}

export const useAuthStore = create<AuthState>()(
  persist(
    (set) => ({
      user: null,
      isAuthenticated: false,
      login: (user) => set({ user, isAuthenticated: true }),
      logout: () => set({ user: null, isAuthenticated: false }),
    }),
    { name: 'auth-storage' }
  )
);
```

## 규칙

### 상태 분류 기준
| 상태 유형 | 저장소 | 예시 |
|----------|--------|------|
| 서버 데이터 | TanStack Query | 사용자 목록, 게시물 |
| 인증/세션 | Zustand (persist) | 로그인 상태, 토큰 |
| UI 상태 | Zustand 또는 useState | 모달 열림, 사이드바 |
| URL 상태 | nuqs | 필터, 페이지네이션 |

### 금지사항
- ❌ Redux 사용 금지 (Zustand로 대체)
- ❌ Context API로 전역 상태 관리 금지
- ❌ useEffect로 직접 데이터 페칭 금지
- ❌ Query Key 하드코딩 금지