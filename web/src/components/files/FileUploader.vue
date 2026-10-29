<script setup lang="ts">
import { computed, onUnmounted, ref } from 'vue'
import { ElMessage } from 'element-plus'

import type { UploadTask } from '@/views/files/useFileUploads'
import { useFileUploads } from '@/views/files/useFileUploads'
import { ACCEPT_ATTR, formatFileSize } from '@/views/files/constants'

const emit = defineEmits<{ finished: [task: UploadTask] }>()
const inputRef = ref<HTMLInputElement>()
const dragging = ref(false)
const { tasks, enqueue, retry, clearFinished, dispose } = useFileUploads({
  onFinished: (task) => {
    emit('finished', task)
    if (task.phase === 'done') ElMessage.success(`${task.name} 解析完成`)
  },
})

const hasFinished = computed(() =>
  tasks.value.some((task) => ['done', 'failed', 'timeout'].includes(task.phase)),
)

function addFiles(list: FileList | null): void {
  if (!list || !list.length) return
  const rejected = enqueue(Array.from(list))
  if (rejected.length) ElMessage.warning(rejected.join('；'))
}

function onInputChange(event: Event): void {
  const input = event.target as HTMLInputElement
  addFiles(input.files)
  input.value = ''
}

function onDrop(event: DragEvent): void {
  dragging.value = false
  addFiles(event.dataTransfer?.files ?? null)
}

function pickFile(): void {
  inputRef.value?.click()
}

function onKeydown(event: KeyboardEvent): void {
  if (event.key === 'Enter' || event.key === ' ') {
    event.preventDefault()
    pickFile()
  }
}

function progressStatus(task: UploadTask): '' | 'success' | 'exception' {
  if (task.phase === 'done') return 'success'
  if (task.phase === 'failed' || task.phase === 'timeout') return 'exception'
  return ''
}

onUnmounted(dispose)
</script>

<template>
  <section class="file-uploader" aria-label="上传文件">
    <div
      class="dropzone"
      :class="{ dragging }"
      role="button"
      tabindex="0"
      data-testid="file-dropzone"
      @click="pickFile"
      @keydown="onKeydown"
      @dragover.prevent="dragging = true"
      @dragleave="dragging = false"
      @drop.prevent="onDrop"
    >
      <input
        ref="inputRef"
        class="file-input"
        type="file"
        multiple
        :accept="ACCEPT_ATTR"
        data-testid="file-input"
        @click.stop
        @change="onInputChange"
      />
      <div class="drop-mark" aria-hidden="true">↑</div>
      <div class="drop-title">拖拽文件到这里，或点击选择</div>
      <p class="drop-hint">支持 PDF / Word / Markdown / TXT，单个文件不超过 60MB</p>
    </div>

    <div v-if="tasks.length" class="upload-queue" aria-live="polite">
      <div class="queue-head">
        <span>上传队列</span>
        <el-button v-if="hasFinished" link type="primary" @click="clearFinished">
          清空已完成
        </el-button>
      </div>
      <div
        v-for="task in tasks"
        :key="task.uid"
        class="queue-item"
        :data-testid="`upload-task-${task.uid}`"
      >
        <div class="queue-top">
          <span class="queue-name" :title="task.name">{{ task.name }}</span>
          <span class="queue-size">{{ formatFileSize(task.size) }}</span>
        </div>
        <el-progress
          :percentage="task.progress"
          :status="progressStatus(task)"
          :stroke-width="6"
          :show-text="false"
        />
        <div class="queue-bottom">
          <span class="queue-status">{{ task.statusText }}</span>
          <el-button
            v-if="task.phase === 'failed'"
            link
            type="primary"
            @click="retry(task.uid)"
          >
            重试
          </el-button>
        </div>
        <p v-if="task.error" class="queue-error">{{ task.error }}</p>
      </div>
    </div>
  </section>
</template>

<style scoped>
.file-uploader {
  display: flex;
  flex-direction: column;
  gap: 16px;
  margin-bottom: 24px;
}

.dropzone {
  position: relative;
  padding: 28px 24px;
  text-align: center;
  cursor: pointer;
  background: var(--app-surface);
  border: 1px dashed #c7d0e0;
  border-radius: var(--app-radius-md);
  transition: border-color 0.15s ease, background 0.15s ease;
}

.dropzone:hover,
.dropzone.dragging {
  background: var(--app-primary-soft);
  border-color: var(--app-primary);
}

.file-input {
  position: absolute;
  width: 1px;
  height: 1px;
  overflow: hidden;
  clip: rect(0 0 0 0);
}

.drop-mark {
  display: grid;
  width: 36px;
  height: 36px;
  margin: 0 auto 10px;
  place-items: center;
  color: var(--app-primary);
  font-size: 20px;
  background: var(--app-primary-soft);
  border-radius: 50%;
}

.drop-title {
  color: var(--app-text);
  font-size: 14px;
  font-weight: 500;
}

.drop-hint {
  margin: 6px 0 0;
  color: var(--app-text-tertiary);
  font-size: 12px;
}

.upload-queue {
  padding: 16px;
  background: var(--app-surface);
  border: 1px solid var(--app-border);
  border-radius: var(--app-radius-md);
}

.queue-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 12px;
  color: var(--app-text-secondary);
  font-size: 13px;
}

.queue-item {
  padding: 12px 0;
  border-top: 1px solid var(--el-border-color-lighter);
}

.queue-item:first-of-type {
  border-top: none;
}

.queue-top,
.queue-bottom {
  display: flex;
  gap: 12px;
  align-items: center;
  justify-content: space-between;
}

.queue-top {
  margin-bottom: 8px;
}

.queue-name {
  overflow: hidden;
  color: var(--app-text);
  font-size: 13px;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.queue-size {
  flex-shrink: 0;
  color: var(--app-text-tertiary);
  font-size: 12px;
}

.queue-bottom {
  margin-top: 6px;
}

.queue-status {
  color: var(--app-text-secondary);
  font-size: 12px;
}

.queue-error {
  margin: 6px 0 0;
  color: var(--app-danger);
  font-size: 12px;
  word-break: break-word;
}
</style>