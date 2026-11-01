import http, { API_PREFIX, type ApiEnvelope } from '@/api/http'
import { useAuthStore } from '@/stores/auth'
import type {
  QaAskPayload,
  QaConversation,
  QaConversationDetail,
  QaDoneData,
  QaMetaData,
} from '@/types/qa'
import { readSseStream } from '@/utils/sse'

export class QaRequestError extends Error {
  constructor(
    message: string,
    readonly status = 0,
    readonly code = 0,
  ) {
    super(message)
    this.name = 'QaRequestError'
  }
}

export interface QaAskHandlers {
  onMeta: (data: QaMetaData) => void
  onDelta: (text: string) => void
  onDone: (data: QaDoneData) => void
}

export async function listConversations(limit = 50): Promise<QaConversation[]> {
  const resp = await http.get<ApiEnvelope<QaConversation[]>>(
    `${API_PREFIX}/qa/conversations`,
    { params: { limit } },
  )
  return resp.data.data
}

export async function getConversationMessages(
  conversationId: string,
): Promise<QaConversationDetail> {
  const resp = await http.get<ApiEnvelope<QaConversationDetail>>(
    `${API_PREFIX}/qa/conversations/${conversationId}/messages`,
  )
  return resp.data.data
}

export async function renameConversation(
  conversationId: string,
  title: string,
): Promise<QaConversation> {
  const resp = await http.patch<ApiEnvelope<QaConversation>>(
    `${API_PREFIX}/qa/conversations/${conversationId}`,
    { title },
  )
  return resp.data.data
}

export async function deleteConversation(conversationId: string): Promise<void> {
  await http.delete(`${API_PREFIX}/qa/conversations/${conversationId}`)
}

export async function askQuestion(
  payload: QaAskPayload,
  handlers: QaAskHandlers,
  signal?: AbortSignal,
): Promise<void> {
  const base = import.meta.env.VITE_API_BASE ?? ''
  const token = useAuthStore().token
  const response = await fetch(`${base}${API_PREFIX}/qa/ask`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
    },
    body: JSON.stringify(payload),
    signal,
  })

  if (!response.ok) {
    let message = '请求失败'
    let code = 0
    try {
      const body = (await response.json()) as { message?: string; code?: number }
      message = body.message ?? message
      code = body.code ?? 0
    } catch {
      // 非 JSON 错误体不暴露原始内容。
    }
    throw new QaRequestError(message, response.status, code)
  }
  if (!response.body) {
    throw new QaRequestError('服务器没有返回数据流', response.status)
  }

  let sawDone = false
  for await (const event of readSseStream(response.body)) {
    let data: unknown
    try {
      data = JSON.parse(event.data)
    } catch {
      throw new QaRequestError('SSE 数据格式错误')
    }
    if (event.event === 'meta') {
      handlers.onMeta(data as QaMetaData)
    } else if (event.event === 'delta') {
      handlers.onDelta(String((data as { text?: string }).text ?? ''))
    } else if (event.event === 'done') {
      sawDone = true
      handlers.onDone(data as QaDoneData)
    } else if (event.event === 'error') {
      throw new QaRequestError(
        String((data as { message?: string }).message ?? '生成失败'),
      )
    }
  }
  if (!sawDone) throw new QaRequestError('连接提前结束，未收到完成事件')
}