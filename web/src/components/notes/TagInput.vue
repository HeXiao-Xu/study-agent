<script setup lang="ts">
import { ElMessage } from 'element-plus'

const props = defineProps<{ modelValue: string[] }>()
const emit = defineEmits<{ 'update:modelValue': [value: string[]] }>()

function onChange(values: string[]): void {
  const result: string[] = []
  for (const raw of values) {
    const tag = raw.trim()
    if (!tag) continue
    if (tag.length > 30) {
      ElMessage.warning('单个标签不超过 30 字')
      continue
    }
    if (!result.includes(tag)) result.push(tag)
  }
  if (result.length > 20) ElMessage.warning('最多 20 个标签')
  emit('update:modelValue', result.slice(0, 20))
}
</script>

<template>
  <el-select
    :model-value="props.modelValue"
    data-testid="tag-input"
    multiple
    filterable
    allow-create
    default-first-option
    placeholder="添加标签"
    class="tag-input"
    @change="onChange"
  />
</template>

<style scoped>
.tag-input {
  width: 260px;
}
</style>