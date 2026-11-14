<script setup lang="ts">
/** S5-2 组卷页：约束表单 → 生成预览 → 换题/删题/调序 → 保存为草稿（单页，不跳转）。 */
import { computed, onMounted, reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'

import MathText from '@/components/common/MathText.vue'
import PageHeader from '@/components/common/PageHeader.vue'
import { getKpTree, listSubjects } from '@/api/kp'
import { exportPaperPdf, generatePaper, replacePaperItem, savePaper } from '@/api/papers'
import type { KpNode, SubjectOut } from '@/types/kp'
import type { PaperConstraintPayload, PaperItem, PaperPreview, PaperQuestionType } from '@/types/papers'

import { DIFFICULTY_LABELS, difficultyCounts, qtypeCounts } from './paperForm'

const QTYPES: PaperQuestionType[] = ['单选', '多选', '填空', '解答']
const router = useRouter()

const subjects = ref<SubjectOut[]>([])
const subjectCode = ref('')
const kpTree = ref<KpNode[]>([])
const checkedKpIds = ref<number[]>([])
const loadingSubjects = ref(false)

const form = reactive({
  total_questions: 10,
  total_score: 60,
  duration_min: 60 as number | null,
  exclude_recent_days: 14,
  qtype_ratio: { 单选: 0.4, 多选: 0, 填空: 0.2, 解答: 0.4 } as Record<PaperQuestionType, number>,
  difficulty_dist: [0, 50, 50, 0, 0],
})

const preview = ref<PaperPreview | null>(null)
const savedPaperId = ref<number | null>(null)
const exporting = ref<'questions' | 'answers' | null>(null)
const generating = ref(false)
const saving = ref(false)
const replacingId = ref<number | null>(null)
const showAnswer = ref(false)

const items = computed<PaperItem[]>(() => preview.value?.items ?? [])
const displayTotal = computed(() => items.value.reduce((sum, item) => sum + item.score, 0))
const canSave = computed(() => items.value.length > 0 && !saving.value)
const qtypePreview = computed(() => qtypeCounts(form.qtype_ratio, form.total_questions))
const difficultyPreview = computed(() =>
  difficultyCounts(form.difficulty_dist, form.total_questions),
)
const qtypeWeightSum = computed(() =>
  QTYPES.reduce((sum, qtype) => sum + Math.max(0, Number(form.qtype_ratio[qtype]) || 0), 0),
)

function qtypePercent(qtype: PaperQuestionType): number | null {
  const weight = Math.max(0, Number(form.qtype_ratio[qtype]) || 0)
  if (weight <= 0 || qtypeWeightSum.value <= 0) return null
  return Math.round((weight / qtypeWeightSum.value) * 100)
}

function onTreeCheck(_node: KpNode, info: { checkedKeys: number[] }): void {
  checkedKpIds.value = [...info.checkedKeys]
}

function setDifficulty(index: number, value: number): void {
  form.difficulty_dist[index] = value
}

async function loadSubjects(): Promise<void> {
  loadingSubjects.value = true
  try {
    subjects.value = await listSubjects()
    if (subjects.value.length && !subjectCode.value) {
      subjectCode.value = subjects.value[0]!.code
      await loadTree()
    }
  } finally {
    loadingSubjects.value = false
  }
}

async function loadTree(): Promise<void> {
  if (!subjectCode.value) return
  const tree = await getKpTree(subjectCode.value)
  kpTree.value = tree.nodes
  checkedKpIds.value = []
}

function onSubjectChange(): void {
  preview.value = null
  void loadTree()
}

/** 生成用载荷：从表单现算；换题/保存用 preview.constraint，保证与卷面同源。 */
function buildConstraint(): PaperConstraintPayload {
  if (checkedKpIds.value.length === 0) throw new Error('请至少选择 1 个知识点')
  const qtype_ratio: Record<string, number> = {}
  for (const qtype of QTYPES) {
    const weight = Number(form.qtype_ratio[qtype])
    if (weight > 0) qtype_ratio[qtype] = weight
  }
  if (Object.keys(qtype_ratio).length === 0) throw new Error('至少给一个题型配置配比')
  const difficulty_dist: Record<string, number> = {}
  form.difficulty_dist.forEach((value, index) => {
    if ((value ?? 0) > 0) difficulty_dist[String(index + 1)] = value / 100
  })
  if (Object.keys(difficulty_dist).length === 0) throw new Error('至少给一个难度配置权重')
  return {
    kp_ids: [...checkedKpIds.value],
    total_questions: form.total_questions,
    qtype_ratio,
    difficulty_dist,
    total_score: form.total_score,
    duration_min: form.duration_min ?? null,
    exclude_recent_days: form.exclude_recent_days,
  }
}

function constraintFromPreview(): PaperConstraintPayload {
  const constraint = preview.value!.constraint
  return {
    kp_ids: [...constraint.kp_ids],
    total_questions: constraint.total_questions,
    qtype_ratio: { ...constraint.qtype_ratio },
    difficulty_dist: { ...constraint.difficulty_dist },
    total_score: constraint.total_score,
    duration_min: constraint.duration_min,
    exclude_recent_days: constraint.exclude_recent_days,
    seed: constraint.seed,
  }
}

async function onGenerate(): Promise<void> {
  let payload: PaperConstraintPayload
  try {
    payload = buildConstraint()
  } catch (error) {
    ElMessage.warning((error as Error).message)
    return
  }
  generating.value = true
  try {
    preview.value = await generatePaper(payload)
    if (!preview.value.ok) {
      ElMessage.warning(`题库不足，已出 ${preview.value.items.length} 题`)
    }
  } finally {
    generating.value = false
  }
}

async function onReplace(item: PaperItem): Promise<void> {
  if (!preview.value) return
  replacingId.value = item.question_id
  try {
    const result = await replacePaperItem({
      ...constraintFromPreview(),
      selected_question_ids: items.value.map((row) => row.question_id),
      replace_question_id: item.question_id,
    })
    if (!result.replaced || !result.item) {
      ElMessage.warning(result.reason ?? '没有可替换的候选题')
      return
    }
    const index = preview.value.items.findIndex((row) => row.question_id === item.question_id)
    if (index >= 0) preview.value.items.splice(index, 1, result.item)
  } finally {
    replacingId.value = null
  }
}

function onRemove(item: PaperItem): void {
  if (!preview.value) return
  preview.value.items = preview.value.items.filter((row) => row.question_id !== item.question_id)
}

function move(index: number, delta: number): void {
  if (!preview.value) return
  const list = preview.value.items
  const target = index + delta
  if (target < 0 || target >= list.length) return
  const [row] = list.splice(index, 1)
  if (row) list.splice(target, 0, row)
}

async function onSave(): Promise<void> {
  if (!preview.value || items.value.length === 0) return
  const suggested = `${new Date().toISOString().slice(0, 10)} 组卷（${items.value.length} 题）`
  let title: string
  try {
    const result = await ElMessageBox.prompt('给这份卷子起个名字', '保存为草稿', {
      inputValue: suggested,
      confirmButtonText: '保存',
      cancelButtonText: '取消',
      inputValidator: (value: string) => (value.trim().length > 0 ? true : '标题不能为空'),
    })
    title = result.value.trim()
  } catch {
    return
  }
  saving.value = true
  try {
    const paper = await savePaper({
      title,
      constraint: constraintFromPreview(),
      question_ids: items.value.map((row) => row.question_id),
      duration_min: preview.value.constraint.duration_min,
    })
    savedPaperId.value = paper.id
    ElMessage.success(`已保存试卷 #${paper.id}`)
  } finally {
    saving.value = false
  }
}

async function onExport(variant: 'questions' | 'answers'): Promise<void> {
  if (!savedPaperId.value) return
  exporting.value = variant
  try {
    const blob = await exportPaperPdf(savedPaperId.value, variant)
    const url = URL.createObjectURL(blob)
    const link = document.createElement('a')
    link.href = url
    link.download = `试卷-${savedPaperId.value}-${variant === 'answers' ? '答案卷' : '题干卷'}.pdf`
    document.body.appendChild(link)
    link.click()
    link.remove()
    URL.revokeObjectURL(url)
  } finally {
    exporting.value = null
  }
}

onMounted(() => {
  void loadSubjects()
})
</script>

<template>
  <section class="papers-generate">
    <PageHeader
      title="组卷"
      description="按知识点、题型与难度自动配卷；预览可换题、删题、调序，满意后保存为草稿。"
    />

    <el-form class="constraint-form" label-width="96px" @submit.prevent>
      <el-form-item label="学科">
        <el-select
          v-model="subjectCode"
          :loading="loadingSubjects"
          data-testid="subject-select"
          @change="onSubjectChange"
        >
          <el-option
            v-for="subject in subjects"
            :key="subject.code"
            :label="subject.name"
            :value="subject.code"
          />
        </el-select>
      </el-form-item>

      <el-form-item label="知识点">
        <el-tree
          class="kp-tree"
          :data="kpTree"
          show-checkbox
          node-key="id"
          :props="{ label: 'name', children: 'children' }"
          data-testid="kp-tree"
          @check="onTreeCheck"
        />
      </el-form-item>

      <el-form-item label="题量">
        <el-input-number
          v-model="form.total_questions"
          :min="1"
          :max="100"
          data-testid="total-questions"
        />
        <span class="hint">道</span>
      </el-form-item>

      <el-form-item label="总分">
        <el-input-number v-model="form.total_score" :min="1" :max="300" data-testid="total-score" />
        <span class="hint">分（单选 3 / 多选 4 / 填空 4 / 解答 8，按题型固定）</span>
      </el-form-item>

      <el-form-item label="时长">
        <el-input-number v-model="form.duration_min" :min="1" :max="1440" />
        <span class="hint">分钟（可清空）</span>
      </el-form-item>

      <el-form-item label="题型占比">
        <div class="ratio-row">
          <label v-for="qtype in QTYPES" :key="qtype" class="ratio-item">
            <span>{{ qtype }}</span>
            <el-input-number
              v-model="form.qtype_ratio[qtype]"
              :min="0"
              :max="1"
              :step="0.1"
              :precision="1"
              size="small"
            />
            <span class="ratio-explain" :data-testid="`qtype-count-${qtype}`">
              {{
                qtypePercent(qtype) === null
                  ? '不出'
                  : `约 ${qtypePercent(qtype)}% · ${qtypePreview[qtype] ?? 0} 题`
              }}
            </span>
          </label>
        </div>
        <span class="hint">
          数字是相对权重，合计不需要等于 1；0 表示不出；最终题量可能因总分容差微调。
        </span>
      </el-form-item>

      <el-form-item label="难度分布">
        <div class="difficulty-grid">
          <div v-for="(value, index) in form.difficulty_dist" :key="index" class="difficulty-item">
            <span class="difficulty-index">d{{ index + 1 }}</span>
            <span class="difficulty-label" :data-testid="`difficulty-label-${index + 1}`">
              {{ DIFFICULTY_LABELS[index] }}
            </span>
            <el-slider
              :model-value="value"
              :max="100"
              :step="10"
              size="small"
              @update:model-value="
                (next: number | number[]) =>
                  setDifficulty(index, Array.isArray(next) ? (next[0] ?? 0) : next)
              "
            />
            <span class="difficulty-count" :data-testid="`difficulty-count-${index + 1}`">
              约 {{ difficultyPreview[index + 1] ?? 0 }} 题
            </span>
          </div>
        </div>
        <span class="hint">
          权重越高该难度题越多，不需要加到 100；1 最简单，5 最难；题库不足时向相邻难度借题。
        </span>
      </el-form-item>

      <el-form-item label="排除近期">
        <el-input-number v-model="form.exclude_recent_days" :min="0" :max="365" />
        <span class="hint">天内做过的题不选（默认 14 天）</span>
      </el-form-item>

      <el-form-item>
        <el-button
          type="primary"
          :loading="generating"
          data-testid="generate-button"
          @click="onGenerate"
        >
          生成试卷
        </el-button>
        <el-button v-if="preview" data-testid="regenerate-button" @click="onGenerate">
          重新生成
        </el-button>
      </el-form-item>
    </el-form>

    <section v-if="preview" class="preview" data-testid="preview">
      <header class="preview-head">
        <div class="preview-meta">
          <span
            class="badge"
            :class="preview.ok ? 'badge-ok' : 'badge-short'"
            data-testid="preview-status"
            >{{ preview.ok ? '约束已满足' : '题库不足' }}</span
          >
          <span class="score" data-testid="preview-total"
            >总分 {{ displayTotal }} / {{ preview.target_score }}</span
          >
          <span class="seed">seed {{ preview.seed }}（同种子可复现）</span>
        </div>
        <div class="preview-actions">
          <el-switch v-model="showAnswer" active-text="显示答案" data-testid="answer-toggle" />
          <el-button :disabled="!canSave" :loading="saving" data-testid="save-button" @click="onSave">
            保存为草稿
          </el-button>
          <el-button
            v-if="savedPaperId"
            data-testid="export-questions"
            :loading="exporting === 'questions'"
            @click="onExport('questions')"
          >
            导出题干卷
          </el-button>
          <el-button
            v-if="savedPaperId"
            data-testid="export-answers"
            :loading="exporting === 'answers'"
            @click="onExport('answers')"
          >
            导出答案卷
          </el-button>
          <el-button
            v-if="savedPaperId"
            type="primary"
            data-testid="take-button"
            @click="router.push(`/papers/${savedPaperId}/take`)"
          >
            开始作答
          </el-button>
          <span v-if="savedPaperId" class="export-hint">导出的为已保存版本</span>
        </div>
      </header>

      <el-alert
        v-if="preview.violations.length"
        class="violations"
        type="warning"
        :closable="false"
        title="题库不足明细"
      >
        <ul>
          <li
            v-for="violation in preview.violations"
            :key="violation.code + violation.message"
            data-testid="violation"
          >
            {{ violation.message }}
          </li>
        </ul>
        <p v-if="preview.warnings.length" class="hint">{{ preview.warnings.join('；') }}</p>
      </el-alert>

      <el-table :data="preview.items" border class="preview-table">
        <el-table-column label="#" width="52">
          <template #default="{ $index }">{{ $index + 1 }}</template>
        </el-table-column>
        <el-table-column label="题型" prop="qtype" width="72" />
        <el-table-column label="难度" width="64">
          <template #default="{ row }">d{{ row.difficulty }}</template>
        </el-table-column>
        <el-table-column label="知识点" width="120">
          <template #default="{ row }">{{ row.kp_ids.join(', ') }}</template>
        </el-table-column>
        <el-table-column label="分值" prop="score" width="64" />
        <el-table-column label="打分" width="88">
          <template #default="{ row }">{{ row.parts ? row.parts.total.toFixed(4) : '-' }}</template>
        </el-table-column>
        <el-table-column label="题干" min-width="320">
          <template #default="{ row }">
            <div class="stem"><MathText :text="row.stem_md" /></div>
            <ul v-if="row.options.length" class="options">
              <li v-for="option in row.options" :key="option.key">
                {{ option.key }}. {{ option.text }}
              </li>
            </ul>
            <div v-if="showAnswer" class="answers" data-testid="answer-text">
              <p>答案：<MathText :text="row.answer_md ?? '（无）'" /></p>
              <p v-if="row.analysis_md">解析：<MathText :text="row.analysis_md" /></p>
            </div>
          </template>
        </el-table-column>
        <el-table-column label="操作" width="248">
          <template #default="{ row, $index }">
            <el-button
              size="small"
              :loading="replacingId === row.question_id"
              data-testid="replace-button"
              @click="onReplace(row)"
            >
              换一题
            </el-button>
            <el-button
              size="small"
              data-testid="move-up"
              :disabled="$index === 0"
              @click="move($index, -1)"
            >
              上移
            </el-button>
            <el-button
              size="small"
              data-testid="move-down"
              :disabled="$index === preview.items.length - 1"
              @click="move($index, 1)"
            >
              下移
            </el-button>
            <el-button size="small" type="danger" data-testid="remove-button" @click="onRemove(row)">
              删除
            </el-button>
          </template>
        </el-table-column>
      </el-table>
    </section>

    <el-empty
      v-else
      data-testid="empty-preview"
      description="尚未生成试卷：选好知识点与配比后点「生成试卷」"
    />
  </section>
</template>

<style scoped>
.papers-generate {
  padding: 24px;
}

.constraint-form {
  max-width: 880px;
}

.kp-tree {
  width: 100%;
  max-height: 240px;
  overflow: auto;
  padding: 8px;
  border: 1px solid var(--el-border-color);
  border-radius: 6px;
}

.ratio-row,
.difficulty-grid {
  display: flex;
  flex-wrap: wrap;
  gap: 12px 24px;
  width: 100%;
}

.ratio-item {
  display: flex;
  flex-direction: column;
  gap: 4px;
  align-items: flex-start;
}

.ratio-explain {
  color: var(--el-text-color-secondary);
  font-size: 12px;
  white-space: nowrap;
}

.difficulty-item {
  display: flex;
  gap: 6px;
  align-items: center;
  width: 300px;
}

.difficulty-item :deep(.el-slider) {
  flex: 1;
  min-width: 80px;
}

.difficulty-index {
  width: 18px;
  color: var(--el-text-color-secondary);
  font-size: 12px;
}

.difficulty-label {
  width: 42px;
  font-size: 13px;
}

.difficulty-count {
  width: 56px;
  color: var(--el-text-color-secondary);
  font-size: 12px;
  text-align: right;
  white-space: nowrap;
}

.hint {
  margin-left: 8px;
  color: var(--el-text-color-secondary);
  font-size: 12px;
}

.preview {
  margin-top: 24px;
}

.preview-head {
  display: flex;
  flex-wrap: wrap;
  gap: 12px;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 12px;
}

.preview-meta,
.preview-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 12px;
  align-items: center;
}

.export-hint {
  font-size: 12px;
  color: #909399;
}

.badge {
  padding: 2px 10px;
  font-size: 12px;
  border-radius: 999px;
}

.badge-ok {
  color: var(--el-color-success);
  background: var(--el-color-success-light-9);
}

.badge-short {
  color: var(--el-color-warning);
  background: var(--el-color-warning-light-9);
}

.seed {
  color: var(--el-text-color-secondary);
  font-size: 12px;
}

.violations {
  margin-bottom: 12px;
}

.violations ul {
  margin: 0;
  padding-left: 18px;
}

.answers {
  margin-top: 6px;
  padding-top: 6px;
  color: var(--el-color-success);
  border-top: 1px dashed var(--el-border-color);
}

.options {
  margin: 4px 0 0;
  padding-left: 18px;
  color: var(--el-text-color-regular);
}
</style>