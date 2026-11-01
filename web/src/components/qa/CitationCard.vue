<script setup lang="ts">
import type { QaCitation } from '@/types/qa'

const props = defineProps<{ citation: QaCitation }>()
const emit = defineEmits<{ open: [citation: QaCitation] }>()

function onClick(): void {
  if (props.citation.note_available === false || props.citation.note_id === null) return
  emit('open', props.citation)
}
</script>

<template>
  <button
    class="citation-card"
    type="button"
    :disabled="citation.note_available === false || citation.note_id === null"
    @click="onClick"
  >
    <span class="citation-index">[{{ citation.index }}]</span>
    <span class="citation-title">{{ citation.title || '未命名笔记' }}</span>
    <span v-if="citation.heading_path" class="citation-path">{{ citation.heading_path }}</span>
    <span v-if="citation.page_no" class="citation-page">第 {{ citation.page_no }} 页</span>
    <span v-if="citation.snippet" class="citation-snippet">{{ citation.snippet }}</span>
    <span v-if="citation.note_available === false" class="citation-missing">原笔记已删除</span>
  </button>
</template>

<style scoped>
.citation-card {
  display: grid;
  grid-template-columns: auto 1fr;
  gap: 4px 8px;
  width: 100%;
  padding: 10px 12px;
  color: var(--app-text);
  text-align: left;
  background: var(--app-surface);
  border: 1px solid var(--app-border);
  border-radius: var(--app-radius-sm);
  cursor: pointer;
}

.citation-card:hover:not(:disabled) {
  border-color: var(--app-primary);
  background: var(--app-primary-soft);
}

.citation-card:disabled {
  cursor: not-allowed;
  opacity: 0.7;
}

.citation-index {
  color: var(--app-primary);
  font-weight: 600;
}

.citation-title {
  font-weight: 600;
}

.citation-path,
.citation-page,
.citation-snippet,
.citation-missing {
  grid-column: 2;
  color: var(--app-text-secondary);
  font-size: 12px;
}

.citation-snippet {
  display: -webkit-box;
  overflow: hidden;
  -webkit-box-orient: vertical;
  -webkit-line-clamp: 2;
}

.citation-missing {
  color: var(--app-danger);
}
</style>