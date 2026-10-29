<script setup lang="ts">
import { computed, nextTick, reactive, ref, watch } from 'vue'
import type { FormInstance, FormRules } from 'element-plus'

import type { KpDialogPayload, KpNode } from '@/types/kp'

const props = defineProps<{
  modelValue: boolean
  mode: 'create' | 'edit'
  node?: KpNode | null
  parentId?: number | null
  parentName?: string
  saving?: boolean
}>()

const emit = defineEmits<{
  'update:modelValue': [value: boolean]
  submit: [payload: KpDialogPayload]
}>()

const formRef = ref<FormInstance>()
const form = reactive({
  name: '',
  code: '',
  description: '',
  exam_weight: undefined as number | undefined,
})

const title = computed(() => (props.mode === 'create' ? '新增知识点' : '编辑知识点'))
const parentLabel = computed(() => props.parentName ?? '根级')
const rules = computed<FormRules>(() => ({
  name: [
    { required: true, message: '请输入知识点名称', trigger: 'blur' },
    { max: 100, message: '名称不能超过 100 字', trigger: 'blur' },
  ],
  ...(props.mode === 'create'
    ? {
        code: [
          { required: true, message: '请输入知识点编码', trigger: 'blur' },
          { max: 50, message: '编码不能超过 50 字', trigger: 'blur' },
        ],
      }
    : {}),
  description: [{ max: 500, message: '描述不能超过 500 字', trigger: 'blur' }],
}))

function fillForm(): void {
  form.name = props.node?.name ?? ''
  form.code = props.node?.code ?? ''
  form.description = props.node?.description ?? ''
  form.exam_weight = props.node?.exam_weight ?? undefined
  void nextTick(() => formRef.value?.clearValidate())
}

watch(
  () => props.modelValue,
  (open) => {
    if (open) fillForm()
  },
  { immediate: true },
)

function close(): void {
  emit('update:modelValue', false)
}

async function submit(): Promise<void> {
  const valid = await formRef.value?.validate().catch(() => false)
  if (!valid) return
  emit('submit', {
    name: form.name.trim(),
    code: props.mode === 'create' ? form.code.trim() : undefined,
    description: form.description.trim() || null,
    exam_weight: form.exam_weight ?? null,
    parent_id: props.node?.parent_id ?? props.parentId ?? null,
  })
}
</script>

<template>
  <el-dialog
    :model-value="modelValue"
    :title="title"
    width="480px"
    :close-on-click-modal="false"
    @update:model-value="emit('update:modelValue', $event)"
  >
    <el-form ref="formRef" :model="form" :rules="rules" label-width="88px">
      <el-form-item label="父节点">
        <el-input :model-value="parentLabel" disabled />
      </el-form-item>
      <el-form-item label="名称" prop="name">
        <el-input
          v-model="form.name"
          name="kp-name"
          maxlength="100"
          placeholder="例如：函数的单调性"
        />
      </el-form-item>
      <el-form-item label="编码" prop="code">
        <el-input
          v-model="form.code"
          name="kp-code"
          maxlength="50"
          :disabled="mode === 'edit'"
          placeholder="例如：MATH-FUNC-01"
        />
      </el-form-item>
      <el-form-item label="描述" prop="description">
        <el-input
          v-model="form.description"
          name="kp-description"
          type="textarea"
          :rows="3"
          maxlength="500"
          show-word-limit
          placeholder="可选：这个知识点包含什么"
        />
      </el-form-item>
      <el-form-item label="权重" prop="exam_weight">
        <el-input-number
          v-model="form.exam_weight"
          :min="0"
          :max="1"
          :step="0.05"
          :precision="2"
          controls-position="right"
        />
      </el-form-item>
    </el-form>
    <template #footer>
      <el-button :disabled="saving" @click="close">取消</el-button>
      <el-button
        type="primary"
        data-testid="kp-save"
        :loading="saving"
        @click="submit"
      >
        保存
      </el-button>
    </template>
  </el-dialog>
</template>
