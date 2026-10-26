import 'vue-router'

import type { UserRole } from '@/types/auth'

export {}

declare module 'vue-router' {
  interface RouteMeta {
    public?: boolean
    title?: string
    task?: string
    description?: string
    roles?: UserRole[]
  }
}