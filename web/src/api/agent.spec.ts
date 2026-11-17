import { describe, expect, it, vi } from 'vitest'

import type { ApiEnvelope } from '@/api/http'
import type { AgentTaskDetail, AgentTaskPage, AgentTaskSummary } from '@/types/agent'

const http = vi.hoisted(() => ({ get: vi.fn(), post: vi.fn() }))
vi.mock('@/api/http', () => ({ default: http, API_PREFIX: '/api/v1' }))

import {
  confirmAgentTask,
  createAgentTask,
  getAgentTask,
  listAgentTasks,
  retryAgentTask,
} from './agent'

function envelope<T>(data: T) {
  const body: ApiEnvelope<T> = { code: 0, message: 'ok', trace_id: 't', data }
  return { data: body }
}

describe('agent api', () => {
  it('creates an agent task', async () => {
    http.post.mockResolvedValue(
      envelope<AgentTaskSummary>({ id: 7, status: 'pending' } as AgentTaskSummary),
    )
    const data = await createAgentTask({
      task_type: 'weekly_mindmap',
      input: { days: 7 },
    })
    expect(http.post).toHaveBeenCalledWith('/api/v1/agent/tasks', {
      task_type: 'weekly_mindmap',
      input: { days: 7 },
    })
    expect(data.id).toBe(7)
  })


  it('lists tasks with filters', async () => {
    http.get.mockResolvedValue(
      envelope<AgentTaskPage>({ items: [], total: 0, page: 2, page_size: 10 }),
    )
    await listAgentTasks({
      page: 2,
      page_size: 10,
      status: 'failed',
      task_type: 'weekly_mindmap',
    })
    expect(http.get).toHaveBeenCalledWith('/api/v1/agent/tasks', {
      params: {
        page: 2,
        page_size: 10,
        status: 'failed',
        task_type: 'weekly_mindmap',
      },
    })
  })

  it('confirms a task', async () => {
    http.post.mockResolvedValue(
      envelope<AgentTaskSummary>({ id: 5, status: 'pending' } as AgentTaskSummary),
    )
    await confirmAgentTask(5, { approved: true, comment: '可以' })
    expect(http.post).toHaveBeenCalledWith('/api/v1/agent/tasks/5/confirm', {
      approved: true,
      comment: '可以',
    })
  })


  it('retries a failed task', async () => {
    http.post.mockResolvedValue(
      envelope<AgentTaskSummary>({ id: 11, status: 'pending' } as AgentTaskSummary),
    )
    await retryAgentTask(11)
    expect(http.post).toHaveBeenCalledWith('/api/v1/agent/tasks/11/retry')
  })

  it('gets task detail by id', async () => {
    http.get.mockResolvedValue(
      envelope<AgentTaskDetail>({ id: 7, status: 'succeeded' } as AgentTaskDetail),
    )
    const data = await getAgentTask(7)
    expect(http.get).toHaveBeenCalledWith('/api/v1/agent/tasks/7')
    expect(data.status).toBe('succeeded')
  })
})