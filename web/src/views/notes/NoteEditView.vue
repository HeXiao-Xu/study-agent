<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import { onBeforeRouteLeave, useRoute, useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'

import { listSubjects } from '@/api/kp'
import MarkdownEditor from '@/components/notes/MarkdownEditor.vue'
import TagInput from '@/components/notes/TagInput.vue'
import type { SubjectOut } from '@/types/kp'
import { useNoteEditor } from '@/views/notes/useNoteEditor'

const route = useRoute()
const router = useRouter()
const initialId = route.name === 'note-edit' ? Number(route.params.id) : null
const currentId = ref<number | null>(initialId)
const subjects = ref<SubjectOut[]>([])
const ready = ref(false)
const draftAt = ref<Date | null>(null)
let draftTimer: ReturnType<typeof setTimeout> | undefined

const editor = useNoteEditor(currentId, {
  onCreated: (id) => {
    void router.replace({ name: 'note-edit', params: { id } })
  },
})
const { form, loading, saving, error, dirty, pendingDraft, imageFailures } = editor

const statusText = computed(() => {
  if (saving.value) return '保存中…'
  if (draftAt.value) {
    return `草稿已保存 ${draftAt.value.toLocaleTimeString('zh-CN', {
      hour: '2-digit',
      minute: '2-digit',
      hour12: false,
    })}`
  }
  return dirty.value ? '未保存' : '已保存'
})

function scheduleDraft(): void {
  if (!ready.value || saving.value || !dirty.value) return
  if (draftTimer) clearTimeout(draftTimer)
  draftTimer = setTimeout(() => {
    editor.writeCurrentDraft()
    draftAt.value = new Date()
  }, 800)
}

async function maybeRestoreDraft(): Promise<void> {
  if (!pendingDraft.value) return
  try {
    await ElMessageBox.confirm('发现一份本地草稿，是否恢复？', '恢复草稿', {
      confirmButtonText: '恢复',
      cancelButtonText: '丢弃',
      showClose: false,
      closeOnClickModal: false,
      closeOnPressEscape: false,
    })
    await editor.applyDraft()
    ElMessage.success('已恢复本地草稿')
  } catch {
    editor.discardDraft()
  }
}

async function onSave(): Promise<void> {
  if (!dirty.value) {
    ElMessage.info('没有需要保存的修改')
    return
  }
  const ok = await editor.save()
  if (ok) {
    if (draftTimer) clearTimeout(draftTimer)
    draftAt.value = null
    ElMessage.success('已保存')
  }
}

function onImageUploaded(payload: { id: number; url: string }): void {
  editor.registerImage(payload.id, payload.url)
}

function onUploadError(): void {
  ElMessage.error('图片上传失败')
}

function onBeforeUnload(event: BeforeUnloadEvent): void {
  event.preventDefault()
  event.returnValue = ''
}

watch(
  () => [form.title, form.content_md, form.subject_id, form.tags],
  scheduleDraft,
  { deep: true },
)

watch(dirty, (value) => {
  if (value) window.addEventListener('beforeunload', onBeforeUnload)
  else window.removeEventListener('beforeunload', onBeforeUnload)
})

onMounted(async () => {
  try {
    subjects.value = await listSubjects()
  } catch {
    subjects.value = []
  }
  await editor.load()
  await maybeRestoreDraft()
  ready.value = true
})

onUnmounted(() => {
  if (draftTimer) clearTimeout(draftTimer)
  window.removeEventListener('beforeunload', onBeforeUnload)
  editor.revokeImages()
})

onBeforeRouteLeave(async () => {
  if (saving.value) {
    ElMessage.warning('正在保存，请稍候')
    return false
  }
  if (!dirty.value) return true
  editor.writeCurrentDraft()
  draftAt.value = new Date()
  try {
    await ElMessageBox.confirm('有未保存的修改，已自动保存为本地草稿。仍要离开吗？', '离开笔记', {
      confirmButtonText: '离开',
      cancelButtonText: '继续编辑',
      type: 'warning',
    })
    return true
  } catch {
    return false
  }
})
</script>

<template>
  <div class="edit-page">
    <header class="edit-header">
      <button class="back" type="button" @click="router.push({ name: 'notes' })">← 笔记</button>
      <span class="status" data-testid="save-status">{{ statusText }}</span>
      <el-button type="primary" data-testid="save-note" :loading="saving" @click="onSave">
        保存
      </el-button>
    </header>

    <div v-if="loading" class="loading">加载中…</div>
    <div v-else-if="error && !form.title" class="load-error">
      <p>{{ error }}</p>
      <el-button @click="router.push({ name: 'notes' })">返回笔记列表</el-button>
    </div>
    <template v-else>
      <input
        v-model="form.title"
        class="title-input"
        data-testid="note-title"
        maxlength="200"
        aria-label="笔记标题"
        placeholder="无标题笔记"
      />
      <div class="meta-row">
        <el-select v-model="form.subject_id" class="subject-select" placeholder="未分类" clearable>
          <el-option v-for="item in subjects" :key="item.id" :label="item.name" :value="item.id" />
        </el-select>
        <TagInput v-model="form.tags" />
      </div>
      <p v-if="error" class="form-error" role="alert">{{ error }}</p>
      <p v-if="imageFailures" class="form-warning">
        {{ imageFailures }} 张图片加载失败；保存时不会丢失引用。
      </p>
      <MarkdownEditor
        v-model="form.content_md"
        @save="onSave"
        @upload-error="onUploadError"
        @image-uploaded="onImageUploaded"
      />
    </template>
  </div>
</template>

<style scoped>
.edit-page {
  display: grid;
  gap: 12px;
}

.edit-header {
  display: flex;
  gap: 16px;
  align-items: center;
  min-height: 40px;
}

.back {
  padding: 4px 0;
  color: var(--app-text-secondary);
  font-size: 13px;
  background: none;
  border: none;
  cursor: pointer;
}

.back:hover {
  color: var(--app-primary);
}

.status {
  margin-left: auto;
  color: var(--app-text-tertiary);
  font-size: 12px;
}

.title-input {
  width: 100%;
  padding: 4px 0;
  color: var(--app-text);
  font-size: 26px;
  font-weight: 600;
  background: none;
  border: none;
  border-bottom: 1px solid transparent;
  outline: none;
}

.title-input:focus {
  border-bottom-color: var(--app-primary);
}

.meta-row {
  display: flex;
  gap: 12px;
  align-items: center;
}

.subject-select {
  width: 180px;
}

.form-error {
  margin: 0;
  color: var(--app-danger);
  font-size: 13px;
}

.form-warning {
  margin: 0;
  color: var(--app-warning);
  font-size: 13px;
}

.loading,
.load-error {
  padding: 64px;
  color: var(--app-text-secondary);
  text-align: center;
}
</style>