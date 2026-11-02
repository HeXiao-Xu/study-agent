<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'

import { listSubjects } from '@/api/kp'
import {
  askQuestion,
  deleteConversation,
  getConversationMessages,
  listConversations,
  renameConversation,
} from '@/api/qa'
import ChatMessage from '@/components/qa/ChatMessage.vue'
import EmptyState from '@/components/common/EmptyState.vue'
import type {
  QaCitation,
  QaConversation,
  QaDoneData,
  QaMessage,
  QaScope,
  QaUiMessage,
} from '@/types/qa'
import type { SubjectOut } from '@/types/kp'
import { createTypewriter, type Typewriter } from '@/utils/typewriter'
import { toScopePayload, type ScopeForm } from '@/views/qa/scope'

const route = useRoute()
const router = useRouter()
const conversations = ref<QaConversation[]>([])
const messages = ref<QaUiMessage[]>([])
const subjects = ref<SubjectOut[]>([])
const activeId = ref<string | null>(null)
const loadingList = ref(false)
const loadingMessages = ref(false)
const listError = ref('')
const streaming = ref(false)
const question = ref('')
const subjectId = ref<number | null>(null)
const folder = ref('')
const dateRange = ref<[string, string] | null>(null)
const scrollHost = ref<HTMLElement | null>(null)

let controller: AbortController | null = null
let writer: Typewriter | null = null
let tempId = 0
let scrollTicket = 0

const hasMessages = computed(() => messages.value.length > 0)

function scheduleScroll(): void {
  if (scrollTicket) return
  scrollTicket = window.setTimeout(() => {
    scrollTicket = 0
    const host = scrollHost.value
    if (host) host.scrollTop = host.scrollHeight
  }, 16)
}

function queryConversation(): string | null {
  const value = route.query.conversation
  return typeof value === 'string' ? value : null
}

function toUi(item: QaMessage): QaUiMessage {
  return {
    ...item,
    localId: `server-${item.id}`,
    error: '',
    streaming: false,
    done: null,
  }
}

function resetScope(): void {
  subjectId.value = null
  folder.value = ''
  dateRange.value = null
}

function applyConversationScope(conversation: QaConversation): void {
  subjectId.value = conversation.scope?.subject_id ?? null
  folder.value = conversation.scope?.folder ?? ''
  const start = conversation.scope?.start_date
  const end = conversation.scope?.end_date
  dateRange.value = start && end ? [start, end] : null
}

function stopStream(): void {
  controller?.abort()
  controller = null
  writer?.cancel()
  writer = null
  streaming.value = false
}

async function loadConversations(preferred?: string | null): Promise<void> {
  loadingList.value = true
  listError.value = ''
  try {
    const items = await listConversations()
    conversations.value = items
    const target = preferred ?? activeId.value ?? queryConversation()
    const id =
      typeof target === 'string' && items.some((item) => item.id === target)
        ? target
        : (items[0]?.id ?? null)
    if (id && id !== activeId.value) {
      await selectConversation(id)
    } else if (id && activeId.value === id) {
      const current = items.find((item) => item.id === id)
      if (current) applyConversationScope(current)
    }
  } catch {
    listError.value = '会话列表加载失败'
  } finally {
    loadingList.value = false
  }
}

async function selectConversation(id: string): Promise<void> {
  stopStream()
  activeId.value = id
  loadingMessages.value = true
  try {
    const detail = await getConversationMessages(id)
    messages.value = detail.messages.map(toUi)
    applyConversationScope(detail.conversation)
    await router.replace({ name: 'qa', query: { conversation: id } })
    await nextTick()
    scheduleScroll()
  } catch {
    messages.value = []
    ElMessage.error('会话消息加载失败')
  } finally {
    loadingMessages.value = false
  }
}

function newConversation(): void {
  stopStream()
  activeId.value = null
  messages.value = []
  resetScope()
  void router.replace({ name: 'qa' })
}

async function send(): Promise<void> {
  const text = question.value.trim()
  if (!text || streaming.value) return
  let scope: QaScope | null
  try {
    const form: ScopeForm = {
      subjectId: subjectId.value,
      folder: folder.value,
      dateRange: dateRange.value,
    }
    scope = toScopePayload(form)
  } catch (error) {
    ElMessage.warning(error instanceof Error ? error.message : '范围不合法')
    return
  }
  question.value = ''
  const localId = `local-${++tempId}`
  const userMessage: QaUiMessage = {
    id: -tempId,
    role: 'user',
    content_md: text,
    created_at: new Date().toISOString(),
    refused: false,
    citations: [],
    localId,
    error: '',
    streaming: false,
    done: null,
  }
  const assistant: QaUiMessage = {
    id: -(++tempId),
    role: 'assistant',
    content_md: '',
    created_at: new Date().toISOString(),
    refused: false,
    citations: [],
    localId: `local-${tempId}`,
    error: '',
    streaming: true,
    done: null,
  }
  messages.value.push(userMessage, assistant)
  // 取数组里的响应式代理，直接改原始对象不会触发渲染。
  const userView = messages.value[messages.value.length - 2]
  const assistantView = messages.value[messages.value.length - 1]
  streaming.value = true
  await nextTick()
  scheduleScroll()

  let aborted = false
  writer = createTypewriter({
    onUpdate: (value) => {
      assistantView.content_md = value
      scheduleScroll()
    },
    onDrained: () => {
      if (assistantView.done || assistantView.error) {
        assistantView.streaming = false
        streaming.value = false
      }
    },
  })
  controller = new AbortController()
  try {
    await askQuestion(
      { question: text, scope, conversation_id: activeId.value },
      {
        onMeta: (data) => {
          userView.id = data.user_message_id
          activeId.value = data.conversation_id
          assistantView.citations = data.citations.map((item) => ({
            ...item,
            note_available: true,
          }))
          void router.replace({
            name: 'qa',
            query: { conversation: data.conversation_id },
          })
        },
        onDelta: (chunk) => writer?.push(chunk),
        onDone: (data: QaDoneData) => {
          assistantView.id = data.message_id
          assistantView.refused = data.refused
          assistantView.done = {
            tokens: data.tokens,
            latency_ms: data.latency_ms,
            cached: data.cached,
            suggestions: data.suggestions,
          }
          if (writer?.isIdle()) {
            assistantView.streaming = false
            streaming.value = false
          }
          void loadConversations(data.conversation_id)
        },
      },
      controller.signal,
    )
  } catch (error) {
    if (error instanceof DOMException && error.name === 'AbortError') {
      aborted = true
      messages.value = messages.value.filter((item) => item !== assistantView)
      return
    }
    writer?.cancel()
    assistantView.error = error instanceof Error ? error.message : '生成失败'
    assistantView.streaming = false
    streaming.value = false
  } finally {
    controller = null
    if (!aborted && !assistantView.done && !assistantView.error) {
      assistantView.error = '连接提前结束'
      assistantView.streaming = false
      streaming.value = false
    }
  }
}

async function onRename(conversation: QaConversation): Promise<void> {
  try {
    const result = await ElMessageBox.prompt('输入新的会话标题', '重命名会话', {
      inputValue: conversation.title,
      inputValidator: (value: string) => Boolean(value?.trim()) || '标题不能为空',
      confirmButtonText: '保存',
      cancelButtonText: '取消',
    })
    const updated = await renameConversation(conversation.id, result.value.trim())
    const index = conversations.value.findIndex((item) => item.id === updated.id)
    if (index >= 0) conversations.value[index] = updated
    ElMessage.success('已重命名')
  } catch (error) {
    if (error !== 'cancel' && error !== 'close') {
      ElMessage.error('重命名失败')
    }
  }
}

async function onDelete(conversation: QaConversation): Promise<void> {
  try {
    await ElMessageBox.confirm(
      `删除「${conversation.title}」及其消息？`,
      '删除会话',
      {
        type: 'warning',
        confirmButtonText: '删除',
        cancelButtonText: '取消',
      },
    )
  } catch {
    return
  }
  try {
    await deleteConversation(conversation.id)
    if (activeId.value === conversation.id) newConversation()
    conversations.value = conversations.value.filter(
      (item) => item.id !== conversation.id,
    )
    if (!activeId.value) {
      const next = conversations.value[0]
      if (next) await selectConversation(next.id)
    }
  } catch {
    ElMessage.error('删除会话失败')
  }
}

function onSuggestion(text: string): void {
  question.value = text
}

function onConversationCommand(conversation: QaConversation, command: string): void {
  if (command === 'rename') {
    void onRename(conversation)
  } else if (command === 'delete') {
    void onDelete(conversation)
  }
}

function onCitation(citation: QaCitation): void {
  if (citation.note_id === null || citation.note_available === false) return
  const query: Record<string, string> = {}
  if (citation.snippet) query.snippet = citation.snippet
  if (citation.heading_path) query.heading = citation.heading_path
  if (citation.page_no !== null) query.page = String(citation.page_no)
  if (citation.chunk_id !== null) query.chunk = String(citation.chunk_id)
  void router.push({
    name: 'note-read',
    params: { id: String(citation.note_id) },
    query,
  })
}

onMounted(async () => {
  try {
    subjects.value = await listSubjects()
  } catch {
    subjects.value = []
  }
  await loadConversations()
})

onBeforeUnmount(() => {
  stopStream()
  if (scrollTicket) window.clearTimeout(scrollTicket)
})
</script>

<template>
  <div class="qa-page">
    <aside class="conversation-pane">
      <div class="pane-head">
        <h1>智能问答</h1>
        <el-button
          type="primary"
          size="small"
          data-testid="new-conversation"
          @click="newConversation"
        >
          新对话
        </el-button>
      </div>
      <p v-if="listError" class="list-error">{{ listError }}</p>
      <div v-else-if="loadingList" class="list-loading">加载中…</div>
      <div v-else class="conversation-list">
        <div
          v-for="conversation in conversations"
          :key="conversation.id"
          class="conversation-row"
          :class="{ active: conversation.id === activeId }"
          @click="void selectConversation(conversation.id)"
        >
          <span class="conversation-title">{{ conversation.title }}</span>
          <span class="conversation-meta">{{ conversation.message_count }} 条</span>
          <span class="conversation-actions" @click.stop>
            <el-dropdown
              trigger="click"
              placement="bottom-end"
              @command="(command: string) => onConversationCommand(conversation, command)"
            >
              <button
                type="button"
                class="conversation-more"
                data-testid="conversation-actions"
                aria-label="会话操作"
                title="会话操作"
              >
                <span aria-hidden="true">⋯</span>
              </button>
              <template #dropdown>
                <el-dropdown-menu>
                  <el-dropdown-item command="rename">改名</el-dropdown-item>
                  <el-dropdown-item command="delete" divided>删除</el-dropdown-item>
                </el-dropdown-menu>
              </template>
            </el-dropdown>
          </span>
        </div>
        <p v-if="!conversations.length" class="list-empty">
          还没有会话，直接提问开始。
        </p>
      </div>
    </aside>

    <section class="chat-pane">
      <header class="chat-head">
        <div>
          <strong>{{ activeId ? '继续追问' : '新对话' }}</strong>
          <span class="chat-hint">基于你的笔记作答，引用可跳转</span>
        </div>
        <div class="scope-panel">
          <el-select
            v-model="subjectId"
            placeholder="全部学科"
            clearable
            size="small"
          >
            <el-option
              v-for="subject in subjects"
              :key="subject.id"
              :label="subject.name"
              :value="subject.id"
            />
          </el-select>
          <el-input v-model="folder" placeholder="笔记本（文件夹）" clearable size="small" />
          <el-date-picker
            v-model="dateRange"
            type="daterange"
            value-format="YYYY-MM-DD"
            start-placeholder="开始日期"
            end-placeholder="结束日期"
            size="small"
          />
        </div>
      </header>

      <div ref="scrollHost" class="messages" data-testid="messages">
        <EmptyState
          v-if="!hasMessages && !loadingMessages"
          title="问点什么"
          description="例如：错位相减法怎么用？"
        />
        <div v-else-if="loadingMessages" class="list-loading">消息加载中…</div>
        <ChatMessage
          v-for="message in messages"
          :key="message.localId"
          :message="message"
          @citation="onCitation"
          @suggestion="onSuggestion"
        />
      </div>

      <form class="composer" @submit.prevent="void send()">
        <textarea
          v-model="question"
          data-testid="question-input"
          rows="2"
          maxlength="500"
          placeholder="输入问题，Enter 发送，Shift+Enter 换行"
          @keydown.enter.exact.prevent="void send()"
        />
        <el-button
          type="primary"
          native-type="submit"
          :loading="streaming"
          :disabled="streaming || !question.trim()"
          data-testid="send-question"
        >
          发送
        </el-button>
      </form>
    </section>
  </div>
</template>

<style scoped>
.qa-page {
  display: grid;
  grid-template-columns: 260px minmax(0, 1fr);
  gap: 14px;
  height: calc(100vh - var(--app-topbar-height) - 48px);
}

.conversation-pane,
.chat-pane {
  min-height: 0;
  background: var(--app-surface);
  border: 1px solid var(--app-border);
  border-radius: var(--app-radius-md);
}

.conversation-pane {
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

.pane-head {
  display: flex;
  gap: 8px;
  align-items: center;
  justify-content: space-between;
  padding: 14px;
  border-bottom: 1px solid var(--app-border);
}

.pane-head h1 {
  margin: 0;
  font-size: 16px;
}

.conversation-list {
  flex: 1;
  padding: 8px;
  overflow: auto;
}

.conversation-row {
  display: flex;
  gap: 6px;
  align-items: center;
  padding: 9px 10px;
  border-radius: var(--app-radius-sm);
  cursor: pointer;
}

.conversation-row:hover,
.conversation-row.active {
  background: var(--app-primary-soft);
}

.conversation-title {
  flex: 1;
  min-width: 0;
  overflow: hidden;
  font-size: 13px;
  font-weight: 600;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.conversation-meta {
  flex-shrink: 0;
  color: var(--app-text-tertiary);
  font-size: 11px;
}

.conversation-actions {
  display: inline-flex;
  flex-shrink: 0;
  align-items: center;
  opacity: 0;
  pointer-events: none;
  transition: opacity 0.15s ease;
}

.conversation-row:hover .conversation-actions,
.conversation-row:focus-within .conversation-actions {
  opacity: 1;
  pointer-events: auto;
}

.conversation-more {
  width: 22px;
  height: 22px;
  padding: 0;
  color: var(--app-text-secondary);
  font-size: 16px;
  line-height: 1;
  cursor: pointer;
  background: transparent;
  border: 0;
  border-radius: 6px;
}

.conversation-more:hover {
  color: var(--app-text);
  background: var(--app-border);
}

.conversation-more:focus-visible {
  outline: 2px solid var(--app-primary);
  outline-offset: 1px;
}

@media (hover: none) {
  .conversation-actions {
    opacity: 1;
    pointer-events: auto;
  }
}

.list-error {
  margin: 12px;
  color: var(--app-danger);
  font-size: 12px;
}

.list-loading,
.list-empty {
  padding: 16px;
  color: var(--app-text-secondary);
  font-size: 12px;
}

.chat-pane {
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

.chat-head {
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
  align-items: center;
  justify-content: space-between;
  padding: 12px 16px;
  border-bottom: 1px solid var(--app-border);
}

.chat-hint {
  margin-left: 8px;
  color: var(--app-text-tertiary);
  font-size: 11px;
}

.scope-panel {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  align-items: center;
}

.scope-panel :deep(.el-select) {
  width: 120px;
}

.scope-panel :deep(.el-input) {
  width: 140px;
}

.messages {
  display: grid;
  flex: 1;
  gap: 12px;
  align-content: start;
  padding: 16px;
  overflow: auto;
}

.composer {
  display: flex;
  gap: 8px;
  align-items: flex-end;
  padding: 12px 16px;
  border-top: 1px solid var(--app-border);
}

.composer textarea {
  flex: 1;
  min-height: 44px;
  padding: 10px 12px;
  color: var(--app-text);
  font: inherit;
  resize: vertical;
  background: var(--app-bg);
  border: 1px solid var(--app-border);
  border-radius: var(--app-radius-sm);
  outline: none;
}

.composer textarea:focus {
  border-color: var(--app-primary);
}

@media (max-width: 820px) {
  .qa-page {
    grid-template-columns: 1fr;
    height: auto;
  }

  .conversation-pane {
    max-height: 220px;
  }

  .messages {
    min-height: 360px;
  }
}
</style>