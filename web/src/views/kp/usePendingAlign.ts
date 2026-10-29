import { computed, ref } from 'vue'
import { ElMessage } from 'element-plus'

import { confirmAlign, listPendingAlign, rejectAlign } from '@/api/kp'
import type { PendingAlign } from '@/types/kp'

export function usePendingAlign() {
  const queue = ref<PendingAlign[]>([])
  const total = ref(0)
  const loading = ref(false)
  const busy = ref(false)
  const error = ref('')
  const current = computed(() => queue.value[0] ?? null)

  async function load(): Promise<void> {
    loading.value = true
    error.value = ''
    try {
      const result = await listPendingAlign({ page: 1, page_size: 20 })
      queue.value = result.items
      total.value = result.total
    } catch {
      error.value = '待确认队列加载失败，请重试'
    } finally {
      loading.value = false
    }
  }

  async function act(kind: 'confirm' | 'reject'): Promise<void> {
    const target = current.value
    if (!target || busy.value) return
    busy.value = true
    try {
      const pair = [{ note_id: target.note_id, kp_id: target.kp_id }]
      const result =
        kind === 'confirm' ? await confirmAlign(pair) : await rejectAlign(pair)
      const changed = kind === 'confirm' ? result.confirmed : result.deleted
      if (changed !== 1 || result.skipped > 0) {
        ElMessage.warning('对齐状态已变化，已重新加载队列')
        await load()
        return
      }
      queue.value.shift()
      total.value = Math.max(0, total.value - 1)
      if (!queue.value.length) await load()
    } catch {
      // http.ts 已统一提示；保留当前卡，允许用户重试。
    } finally {
      busy.value = false
    }
  }

  return {
    queue,
    total,
    current,
    loading,
    busy,
    error,
    load,
    confirmCurrent: () => act('confirm'),
    rejectCurrent: () => act('reject'),
  }
}
