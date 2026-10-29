<script setup lang="ts">
import { onMounted, onUnmounted } from 'vue'

import EmptyState from '@/components/common/EmptyState.vue'
import { usePendingAlign } from './usePendingAlign'

const {
  total,
  current,
  loading,
  busy,
  error,
  load,
  confirmCurrent,
  rejectCurrent,
} = usePendingAlign()

function isEditableTarget(target: EventTarget | null): boolean {
  if (!(target instanceof HTMLElement)) return false
  return Boolean(
    target.closest('input, textarea, select, [contenteditable="true"], .el-dialog'),
  )
}

function onKeydown(event: KeyboardEvent): void {
  if (!current.value || busy.value || isEditableTarget(event.target)) return
  if (event.key === 'Enter') {
    event.preventDefault()
    void confirmCurrent()
  } else if (event.key === 'Backspace') {
    event.preventDefault()
    void rejectCurrent()
  }
}

onMounted(() => {
  void load()
  window.addEventListener('keydown', onKeydown)
})

onUnmounted(() => {
  window.removeEventListener('keydown', onKeydown)
})
</script>

<template>
  <div class="pending-panel">
    <div v-if="loading" class="pending-loading" v-loading="true" />

    <div v-else-if="error" class="pending-error" role="alert">
      {{ error }}
      <el-button link type="primary" @click="load">重试</el-button>
    </div>

    <EmptyState
      v-else-if="!current"
      title="暂无待确认对齐"
      description="新笔记自动对齐后，低置信度候选会出现在这里。"
    />

    <template v-else>
      <div class="pending-meta">
        <span>待确认 {{ total }} 条</span>
        <span class="pending-hint">Enter 确认 · Backspace 忽略</span>
      </div>

      <article class="pending-card" tabindex="0" :aria-busy="busy">
        <section class="note-pane">
          <p class="pane-label">笔记内容</p>
          <h3 class="note-title">{{ current.note_title }}</h3>
          <p class="note-excerpt">
            {{ current.note_excerpt || '（这条笔记暂无摘要）' }}
          </p>
        </section>

        <section class="candidate-pane">
          <p class="pane-label">候选知识点</p>
          <h3 class="kp-title">{{ current.kp_name }}</h3>
          <p class="kp-code">{{ current.kp_code }}</p>
          <div class="confidence">
            <span>置信度</span>
            <strong>{{ Math.round(current.confidence * 100) }}%</strong>
          </div>
        </section>
      </article>

      <div class="pending-actions">
        <el-button
          type="primary"
          data-testid="confirm-align"
          :loading="busy"
          @click="confirmCurrent"
        >
          确认对齐
        </el-button>
        <el-button data-testid="reject-align" :disabled="busy" @click="rejectCurrent">
          忽略
        </el-button>
      </div>
    </template>
  </div>
</template>

<style scoped>
.pending-panel {
  min-height: 320px;
}

.pending-loading {
  min-height: 240px;
}

.pending-error {
  display: flex;
  gap: 8px;
  align-items: center;
  padding: 10px 14px;
  color: var(--app-danger);
  font-size: 13px;
  background: #fff5f5;
  border: 1px solid #ffc9c9;
  border-radius: var(--app-radius-sm);
}

.pending-meta {
  display: flex;
  justify-content: space-between;
  margin-bottom: 12px;
  color: var(--app-text-secondary);
  font-size: 13px;
}

.pending-hint {
  color: var(--app-text-tertiary);
}

.pending-card {
  display: grid;
  grid-template-columns: minmax(0, 1.5fr) minmax(260px, 1fr);
  gap: 0;
  overflow: hidden;
  background: #fff;
  border: 1px solid var(--app-border);
  border-radius: var(--app-radius-lg);
  box-shadow: var(--app-shadow-sm);
}

.note-pane,
.candidate-pane {
  padding: 26px;
}

.note-pane {
  border-right: 1px solid var(--app-border);
}

.candidate-pane {
  background: #fafbfc;
}

.pane-label {
  margin: 0 0 10px;
  color: var(--app-text-tertiary);
  font-size: 12px;
}

.note-title,
.kp-title {
  margin: 0 0 12px;
  font-size: 18px;
}

.note-excerpt {
  max-height: 260px;
  margin: 0;
  overflow: auto;
  color: var(--app-text-secondary);
  font-size: 14px;
  line-height: 1.8;
  white-space: pre-wrap;
}

.kp-code {
  margin: 0 0 18px;
  color: var(--app-text-tertiary);
  font-family: var(--app-font-mono);
  font-size: 12px;
}

.confidence {
  display: flex;
  justify-content: space-between;
  padding-top: 14px;
  color: var(--app-text-secondary);
  border-top: 1px solid var(--app-border);
}

.pending-actions {
  display: flex;
  gap: 10px;
  justify-content: center;
  margin-top: 18px;
}
</style>
