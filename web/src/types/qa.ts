export interface QaScope {
  subject_id?: number | null
  folder?: string | null
  start_date?: string | null
  end_date?: string | null
}

export interface QaCitation {
  index: number
  note_id: number | null
  chunk_id: number | null
  title: string | null
  heading_path: string | null
  page_no: number | null
  snippet: string | null
  score?: number | null
  note_available?: boolean
}

export interface QaConversation {
  id: string
  title: string
  scope: QaScope | null
  created_at: string
  last_message_at: string | null
  message_count: number
}

export interface QaMessage {
  id: number
  role: 'user' | 'assistant'
  content_md: string
  created_at: string
  refused: boolean
  citations: QaCitation[]
}

export interface QaSuggestion {
  type: 'rephrase' | 'note'
  text: string
  note_id: number | null
}

export interface QaDoneData {
  message_id: number
  conversation_id: string
  tokens: number
  latency_ms: number
  refused: boolean
  refusal_reason: string | null
  suggestions: QaSuggestion[]
  cached: boolean
}

export interface QaMetaData {
  conversation_id: string
  user_message_id: number
  citations: QaCitation[]
}

export interface QaConversationDetail {
  conversation: QaConversation
  messages: QaMessage[]
}

export interface QaAskPayload {
  question: string
  scope?: QaScope | null
  conversation_id?: string | null
}

export interface QaUiMessage extends QaMessage {
  localId: string
  error: string
  streaming: boolean
  done: {
    tokens: number
    latency_ms: number
    cached: boolean
    suggestions: QaSuggestion[]
  } | null
}