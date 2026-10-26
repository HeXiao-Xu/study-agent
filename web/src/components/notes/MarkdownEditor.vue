<script setup lang="ts">
import { MdEditor, type ToolbarNames } from 'md-editor-v3'
import { ElMessage } from 'element-plus'

import { getImageBlob, uploadImage } from '@/api/files'

import 'md-editor-v3/lib/style.css'
import 'katex/dist/katex.min.css'

const props = defineProps<{ modelValue: string }>()
const emit = defineEmits<{
  'update:modelValue': [value: string]
  save: []
  'upload-error': []
  'image-uploaded': [payload: { id: number; url: string }]
}>()

const toolbars: ToolbarNames[] = [
  'bold',
  'italic',
  'strikeThrough',
  'title',
  'quote',
  'unorderedList',
  'orderedList',
  'code',
  'link',
  'image',
  'table',
  'katex',
  '-',
  'preview',
  'fullscreen',
  'save',
]

async function onUploadImg(files: File[], callback: (urls: string[]) => void): Promise<void> {
  const urls: string[] = []
  for (const file of files) {
    if (!file.type.startsWith('image/')) {
      ElMessage.warning('只能插入图片文件')
      continue
    }
    try {
      const record = await uploadImage(file)
      const blob = await getImageBlob(record.id)
      const url = URL.createObjectURL(blob)
      urls.push(url)
      emit('image-uploaded', { id: record.id, url })
    } catch {
      emit('upload-error')
    }
  }
  callback(urls)
}
</script>

<template>
  <div class="editor-shell" data-testid="markdown-editor">
    <MdEditor
      :model-value="props.modelValue"
      :toolbars="toolbars"
      :no-mermaid="true"
      preview-theme="github"
      code-theme="atom"
      :style="{ height: '100%' }"
      :on-upload-img="onUploadImg"
      @update:model-value="emit('update:modelValue', $event)"
      @on-save="emit('save')"
    />
  </div>
</template>

<style scoped>
.editor-shell {
  height: calc(100vh - 280px);
  min-height: 420px;
  overflow: hidden;
  background: var(--app-surface);
  border: 1px solid var(--app-border);
  border-radius: var(--app-radius-md);
}
</style>