import axios from 'axios'
import { ref } from 'vue'

import { getFileStatus, uploadDocument } from '@/api/files'
import type { FileStatus, ParseStatus } from '@/types/files'
import {
  POLL_INTERVAL_MS,
  POLL_TIMEOUT_MS,
  isAcceptedFile,
} from '@/views/files/constants'

export type UploadPhase =
  | 'waiting'
  | 'uploading'
  | 'pending'
  | 'parsing'
  | 'done'
  | 'failed'
  | 'timeout'

export interface UploadTask {
  uid: string
  file: File
  name: string
  size: number
  progress: number
  phase: UploadPhase
  statusText: string
  error: string
  recordId: number | null
  chunkCount: number
  startedAt: number
  notified: boolean
}

interface UseFileUploadsOptions {
  onFinished?: (task: UploadTask) => void
}

let sequence = 0

function isActive(status: ParseStatus): boolean {
  return status === 'pending' || status === 'parsing'
}

function errorMessage(error: unknown): string {
  if (axios.isAxiosError(error)) {
    const payload = error.response?.data as { message?: string } | undefined
    return payload?.message ?? '上传失败，请重试'
  }
  if (error instanceof Error && error.message) return error.message
  return '上传失败，请重试'
}

export function useFileUploads(options: UseFileUploadsOptions = {}) {
  const tasks = ref<UploadTask[]>([])
  const timers = new Map<string, ReturnType<typeof setTimeout>>()
  let running = false

  function makeTask(file: File): UploadTask {
    sequence += 1
    return {
      uid: `${Date.now()}-${sequence}`,
      file,
      name: file.name,
      size: file.size,
      progress: 0,
      phase: 'waiting',
      statusText: '等待上传',
      error: '',
      recordId: null,
      chunkCount: 0,
      startedAt: 0,
      notified: false,
    }
  }

  function stopPolling(uid: string): void {
    const timer = timers.get(uid)
    if (timer) clearTimeout(timer)
    timers.delete(uid)
  }

  function notify(task: UploadTask): void {
    if (task.notified) return
    task.notified = true
    options.onFinished?.(task)
  }

  function applyStatus(task: UploadTask, status: FileStatus): void {
    task.progress = status.parse_progress
    task.chunkCount = status.chunk_count
    task.error = status.error_msg ?? ''
    if (status.parse_status === 'done') {
      task.phase = 'done'
      task.progress = 100
      task.statusText = `完成 · ${status.chunk_count} 块`
      stopPolling(task.uid)
      notify(task)
      return
    }
    if (status.parse_status === 'failed') {
      task.phase = 'failed'
      task.statusText = '解析失败'
      stopPolling(task.uid)
      notify(task)
      return
    }
    task.phase = status.parse_status
    task.statusText =
      status.parse_status === 'pending'
        ? '排队中'
        : `解析中 ${status.parse_progress}%`
  }

  function timeoutTask(task: UploadTask): void {
    if (task.phase === 'done' || task.phase === 'failed') return
    task.phase = 'timeout'
    task.statusText = '解析超时，请刷新查看'
    stopPolling(task.uid)
    notify(task)
  }

  function startPolling(task: UploadTask): void {
    if (timers.has(task.uid) || task.recordId === null) return
    const tick = async (): Promise<void> => {
      if (!isActive(task.phase as ParseStatus)) return
      if (Date.now() - task.startedAt >= POLL_TIMEOUT_MS) {
        timeoutTask(task)
        return
      }
      try {
        applyStatus(task, await getFileStatus(task.recordId as number))
      } catch {
        // 单次轮询失败不终止；下一轮继续，直到终态或超时
      }
      if (isActive(task.phase as ParseStatus)) {
        timers.set(task.uid, setTimeout(tick, POLL_INTERVAL_MS))
      }
    }
    timers.set(task.uid, setTimeout(tick, POLL_INTERVAL_MS))
  }

  async function startTask(task: UploadTask): Promise<void> {
    task.phase = 'uploading'
    task.statusText = '上传中'
    task.progress = 0
    task.error = ''
    task.notified = false
    try {
      const record = await uploadDocument(task.file, (percent) => {
        task.progress = percent
        task.statusText = `上传中 ${percent}%`
      })
      task.recordId = record.id
      task.startedAt = Date.now()
      try {
        const status = await getFileStatus(record.id)
        applyStatus(task, status)
        if (isActive(status.parse_status)) startPolling(task)
      } catch {
        task.phase = 'pending'
        task.statusText = '待解析'
        startPolling(task)
      }
    } catch (error) {
      task.phase = 'failed'
      task.statusText = '上传失败'
      task.error = errorMessage(error)
      notify(task)
    }
  }

  async function drain(): Promise<void> {
    if (running) return
    running = true
    try {
      let next = tasks.value.find((task) => task.phase === 'waiting')
      while (next) {
        await startTask(next)
        next = tasks.value.find((task) => task.phase === 'waiting')
      }
    } finally {
      running = false
    }
  }

  function enqueue(files: File[]): string[] {
    const rejected: string[] = []
    for (const file of files) {
      if (!isAcceptedFile(file.name)) {
        rejected.push(`${file.name}：仅支持 PDF / Word / Markdown / TXT`)
        continue
      }
      tasks.value.push(makeTask(file))
    }
    if (tasks.value.some((task) => task.phase === 'waiting')) void drain()
    return rejected
  }

  function retry(uid: string): void {
    const task = tasks.value.find((item) => item.uid === uid)
    if (!task) return
    stopPolling(uid)
    task.phase = 'waiting'
    task.progress = 0
    task.statusText = '等待上传'
    task.error = ''
    task.recordId = null
    task.chunkCount = 0
    task.startedAt = 0
    task.notified = false
    void drain()
  }

  function clearFinished(): void {
    tasks.value = tasks.value.filter(
      (task) => !['done', 'failed', 'timeout'].includes(task.phase),
    )
  }

  function dispose(): void {
    for (const timer of timers.values()) clearTimeout(timer)
    timers.clear()
  }

  return { tasks, enqueue, retry, clearFinished, dispose }
}