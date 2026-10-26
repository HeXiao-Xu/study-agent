import { reactive, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'

import { listNotes } from '@/api/notes'
import type { NoteSummary } from '@/types/notes'
import {
  normalizeListQuery,
  toListQuery,
  toNoteListParams,
  type ListQueryState,
} from '@/views/notes/listQuery'

export function useNoteList() {
  const route = useRoute()
  const router = useRouter()
  const items = ref<NoteSummary[]>([])
  const total = ref(0)
  const loading = ref(false)
  const error = ref('')
  const query = reactive<ListQueryState>(normalizeListQuery(route.query))
  let requestId = 0

  async function fetchList(): Promise<void> {
    const current = ++requestId
    loading.value = true
    error.value = ''
    try {
      const page = await listNotes(toNoteListParams(query))
      if (current !== requestId) return
      items.value = page.items
      total.value = page.total
    } catch {
      if (current !== requestId) return
      error.value = '笔记加载失败，请重试'
    } finally {
      if (current === requestId) loading.value = false
    }
  }

  async function updateQuery(patch: Partial<ListQueryState>, resetPage = false): Promise<void> {
    Object.assign(query, patch)
    if (resetPage) query.page = 1
    await router.replace({ query: toListQuery(query) })
  }

  function syncFromRoute(): void {
    Object.assign(query, normalizeListQuery(route.query))
  }

  return { items, total, loading, error, query, fetchList, updateQuery, syncFromRoute }
}