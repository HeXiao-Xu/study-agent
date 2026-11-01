<script setup lang="ts">
import { nextTick, onMounted, onUnmounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { MdPreview } from 'md-editor-v3'

import { getNote } from '@/api/notes'
import type { NoteOut } from '@/types/notes'
import { highlightSnippet, scrollToHeading } from '@/utils/highlight'

import 'md-editor-v3/lib/preview.css'
import 'katex/dist/katex.min.css'

const route = useRoute()
const router = useRouter()
const note = ref<NoteOut | null>(null)
const loading = ref(true)
const error = ref('')
const manualNotice = ref(false)
const previewHost = ref<HTMLElement | null>(null)
let appliedQuery = ''
let applying = false
let highlightTimer: ReturnType<typeof setTimeout> | undefined

function queryString(key: string): string {
  const value = route.query[key]
  return typeof value === 'string' ? value : ''
}

async function applyHighlight(): Promise<void> {
  const signature = `${queryString('snippet')}|${queryString('heading')}`
  if (!signature || signature === appliedQuery || applying) return
  applying = true
  try {
    await nextTick()
    const host = previewHost.value
    if (!host?.textContent?.trim()) return
    appliedQuery = signature

    const snippet = queryString('snippet')
    const heading = queryString('heading')
    if (snippet) {
      const mark = highlightSnippet(host, snippet)
      if (mark) {
        manualNotice.value = false
        return
      }
    }
    scrollToHeading(host, heading)
    manualNotice.value = true
  } finally {
    applying = false
  }
}

async function load(): Promise<void> {
  loading.value = true
  error.value = ''
  try {
    note.value = await getNote(Number(route.params.id))
    loading.value = false
  } catch {
    error.value = '笔记不存在或无权访问'
    loading.value = false
  }
}

function scheduleHighlight(): void {
  if (highlightTimer !== undefined) clearTimeout(highlightTimer)
  highlightTimer = setTimeout(() => {
    highlightTimer = undefined
    void applyHighlight()
  }, 80)
}

function toEdit(): void {
  if (note.value) {
    void router.push({ name: 'note-edit', params: { id: note.value.id } })
  }
}

watch(
  () => route.query,
  () => {
    appliedQuery = ''
    scheduleHighlight()
  },
)

onMounted(load)
onUnmounted(() => {
  if (highlightTimer !== undefined) clearTimeout(highlightTimer)
})
</script>

<template>
  <div class="read-page">
    <header class="read-head">
      <button class="back" type="button" @click="router.push({ name: 'notes' })">
        ← 笔记
      </button>
      <span v-if="note" class="read-status">只读</span>
      <el-button
        v-if="note"
        type="primary"
        plain
        data-testid="edit-note"
        @click="toEdit"
      >
        编辑
      </el-button>
    </header>
    <div v-if="loading" class="loading">加载中…</div>
    <div v-else-if="error" class="load-error">
      <p>{{ error }}</p>
      <el-button @click="router.push({ name: 'notes' })">返回笔记列表</el-button>
    </div>
    <template v-else-if="note">
      <h1 class="note-title">{{ note.title }}</h1>
      <p v-if="manualNotice" class="fallback-notice" data-testid="citation-fallback">
        未能精确定位引用片段，已滚动到对应章节。引用原文：{{ queryString('snippet') }}
      </p>
      <div ref="previewHost" class="preview-host">
        <MdPreview
          :model-value="note.content_md"
          :no-mermaid="true"
          preview-theme="github"
          :on-html-changed="scheduleHighlight"
        />
      </div>
    </template>
  </div>
</template>

<style scoped>
.read-page {
  display: grid;
  gap: 14px;
}

.read-head {
  display: flex;
  gap: 12px;
  align-items: center;
  min-height: 40px;
}

.read-head .back {
  padding: 4px 0;
  color: var(--app-text-secondary);
  background: none;
  border: none;
  cursor: pointer;
}

.read-status {
  color: var(--app-text-tertiary);
  font-size: 12px;
}

.note-title {
  margin: 0;
  font-size: 24px;
}

.preview-host {
  padding: 20px 24px;
  background: var(--app-surface);
  border: 1px solid var(--app-border);
  border-radius: var(--app-radius-md);
}

.fallback-notice {
  margin: 0;
  padding: 10px 12px;
  color: var(--app-warning);
  background: #fff4e6;
  border-radius: var(--app-radius-sm);
}

.preview-host :deep(mark.citation-hit) {
  padding: 0 2px;
  background: #fff3bf;
  border-radius: 2px;
}
</style>