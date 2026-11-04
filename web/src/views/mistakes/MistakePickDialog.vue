<script setup lang="ts">
/** 从题库选题弹窗：题型筛选 + 分页列表 + 录入错题。 */
import { ref, watch } from 'vue'
import { ElMessage } from 'element-plus'

import { createMistake } from '@/api/mistakes'
import MathText from '@/components/common/MathText.vue'
import { listQuestions } from '@/api/questions'
import type { QuestionSummary, QuestionType } from '@/types/questions'

const props = defineProps<{ modelValue: boolean }>()
const emit = defineEmits<{
  'update:modelValue': [value: boolean]
  created: []
}>()

const PICK_PAGE_SIZE = 10
const QUESTION_TYPES: QuestionType[] = ['单选', '多选', '填空', '解答']

const loading = ref(false)
const submitting = ref(false)
const rows = ref<QuestionSummary[]>([])
const total = ref(0)
const page = ref(1)
const qtype = ref<QuestionType | ''>('')
const selectedId = ref<number | null>(null)

async function loadRows(): Promise<void> {
  loading.value = true
  try {
    const data = await listQuestions({
      page: page.value,
      page_size: PICK_PAGE_SIZE,
      qtype: qtype.value || undefined,
    })
    rows.value = data.items
    total.value = data.total
  } catch {
    rows.value = []
    total.value = 0
  } finally {
    loading.value = false
  }
}

function resetState(): void {
  page.value = 1
  qtype.value = ''
  selectedId.value = null
}

watch(
  () => props.modelValue,
  (open) => {
    if (!open) return
    resetState()
    void loadRows()
  },
)

async function onQtypeChange(): Promise<void> {
  page.value = 1
  await loadRows()
}

async function onPageChange(value: number): Promise<void> {
  page.value = value
  await loadRows()
}

function selectQuestion(id: number): void {
  selectedId.value = id
}

async function confirmPick(): Promise<void> {
  const questionId = selectedId.value
  if (questionId === null) return
  submitting.value = true
  try {
    const result = await createMistake({ questionId })
    if (result.created) {
      ElMessage.success('已加入错题本')
    } else {
      ElMessage.warning('已存在，已重置为待订正')
    }
    emit('update:modelValue', false)
    emit('created')
  } catch {
    // http.ts 已统一提示
  } finally {
    submitting.value = false
  }
}
</script>

<template>
  <el-dialog
    :model-value="modelValue"
    title="从题库选题"
    width="720px"
    class="pick-dialog"
    @update:model-value="emit('update:modelValue', $event)"
  >
    <div class="pick-toolbar">
      <el-radio-group v-model="qtype" data-testid="pick-qtype" @change="onQtypeChange">
        <el-radio-button value="">全部</el-radio-button>
        <el-radio-button v-for="item in QUESTION_TYPES" :key="item" :value="item">
          {{ item }}
        </el-radio-button>
      </el-radio-group>
      <span class="pick-hint">选中题目后点「录入错题」；重复录入会重置为待订正。</span>
    </div>

    <el-table
      v-loading="loading"
      :data="rows"
      row-key="id"
      max-height="320"
      class="pick-table"
      @row-click="selectQuestion($event.id)"
    >
      <el-table-column prop="id" label="ID" width="70" />
      <el-table-column label="题干" min-width="320">
        <template #default="{ row }">
          <span class="pick-stem" :title="row.stem_md">
            <MathText :text="row.stem_md" />
          </span>
        </template>
      </el-table-column>
      <el-table-column prop="qtype" label="题型" width="72" />
      <el-table-column label="选择" width="88">
        <template #default="{ row }">
          <el-button
            link
            type="primary"
            :data-testid="`pick-row-${row.id}`"
            @click.stop="selectQuestion(row.id)"
          >
            {{ selectedId === row.id ? '已选' : '选择' }}
          </el-button>
        </template>
      </el-table-column>
    </el-table>

    <div class="pick-pager">
      <el-pagination
        :current-page="page"
        :page-size="PICK_PAGE_SIZE"
        :total="total"
        layout="total, prev, pager, next"
        @current-change="onPageChange"
      />
    </div>

    <template #footer>
      <el-button @click="emit('update:modelValue', false)">取消</el-button>
      <el-button
        type="primary"
        data-testid="pick-confirm"
        :disabled="selectedId === null"
        :loading="submitting"
        @click="confirmPick"
      >
        录入错题
      </el-button>
    </template>
  </el-dialog>
</template>

<style scoped>
.pick-toolbar {
  display: flex;
  gap: 12px;
  align-items: center;
  margin-bottom: 12px;
}

.pick-hint {
  color: var(--app-text-tertiary);
  font-size: 12px;
}

.pick-stem {
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}

.pick-pager {
  display: flex;
  justify-content: flex-end;
  margin-top: 12px;
}
</style>