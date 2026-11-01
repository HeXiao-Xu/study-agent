<script setup lang="ts">
import { MdPreview } from 'md-editor-v3'

import CitationCard from '@/components/qa/CitationCard.vue'
import type { QaCitation, QaUiMessage } from '@/types/qa'

import 'md-editor-v3/lib/preview.css'
import 'katex/dist/katex.min.css'

defineProps<{ message: QaUiMessage }>()
const emit = defineEmits<{
  citation: [citation: QaCitation]
  suggestion: [text: string]
}>()

function onSuggestion(text: string): void {
  emit('suggestion', text)
}
</script>

<template>
  <article
    class="chat-message"
    :class="[message.role, { refused: message.refused, failed: Boolean(message.error) }]"
    :data-testid="`message-${message.id}`"
  >
    <div class="message-meta">
      <span>{{ message.role === 'user' ? '我' : '知序' }}</span>
      <span v-if="message.done?.cached" class="badge">缓存命中</span>
      <span v-if="message.streaming" class="badge">生成中…</span>
    </div>
    <div v-if="message.role === 'user'" class="user-text">{{ message.content_md }}</div>
    <template v-else>
      <MdPreview
        v-if="message.content_md"
        :model-value="message.content_md"
        :no-mermaid="true"
        preview-theme="github"
        code-theme="atom"
      />
      <p v-if="message.error" class="message-error" role="alert">{{ message.error }}</p>
      <p v-if="message.refused" class="refusal-tip">
        未在资料中找到可靠依据，建议换问法或补充笔记。
      </p>
      <div v-if="message.citations.length" class="citation-list">
        <CitationCard
          v-for="citation in message.citations"
          :key="citation.index"
          :citation="citation"
          @open="emit('citation', $event)"
        />
      </div>
      <div v-if="message.done?.suggestions.length" class="suggestions">
        <button
          v-for="item in message.done.suggestions"
          :key="item.text"
          type="button"
          class="suggestion"
          @click="onSuggestion(item.text)"
        >
          {{ item.text }}
        </button>
      </div>
      <p v-if="message.done" class="usage">
        {{ message.done.tokens }} tokens ·
        {{ (message.done.latency_ms / 1000).toFixed(1) }}s
      </p>
    </template>
  </article>
</template>

<style scoped>
.chat-message {
  display: grid;
  gap: 8px;
  padding: 14px 16px;
  background: var(--app-surface);
  border: 1px solid var(--app-border);
  border-radius: var(--app-radius-md);
}

.chat-message.user {
  margin-left: 15%;
  background: var(--app-primary-soft);
  border-color: transparent;
}

.chat-message.refused {
  border-color: var(--app-warning);
}

.chat-message.failed {
  border-color: var(--app-danger);
}

.message-meta {
  display: flex;
  gap: 8px;
  align-items: center;
  color: var(--app-text-secondary);
  font-size: 12px;
}

.badge {
  padding: 1px 6px;
  color: var(--app-primary-strong);
  background: var(--app-primary-soft);
  border-radius: 999px;
}

.user-text {
  white-space: pre-wrap;
}

.message-error {
  margin: 0;
  color: var(--app-danger);
}

.refusal-tip {
  margin: 0;
  padding: 8px 10px;
  color: var(--app-warning);
  background: #fff4e6;
  border-radius: var(--app-radius-sm);
}

.citation-list,
.suggestions {
  display: grid;
  gap: 6px;
}

.suggestion {
  justify-self: start;
  padding: 4px 8px;
  color: var(--app-primary-strong);
  background: var(--app-primary-soft);
  border: none;
  border-radius: 999px;
  cursor: pointer;
}

.usage {
  margin: 0;
  color: var(--app-text-tertiary);
  font-size: 11px;
}
</style>