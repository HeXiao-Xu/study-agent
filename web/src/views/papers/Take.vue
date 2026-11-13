<script setup lang="ts">
/** S5-4 在线作答：单页 + 题号面板 + 自动保存 + 交卷成绩/掌握度回显。 */
import { computed, onBeforeUnmount, onMounted, reactive, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'

import MathText from '@/components/common/MathText.vue'
import PageHeader from '@/components/common/PageHeader.vue'
import { getPaper, getPaperAnswers, savePaperAnswer, submitPaper } from '@/api/papers'
import type { PaperAnswerRow, PaperDetail, PaperSubmitResult } from '@/types/papers'

const SELF_RATED_QTYPES = ['填空', '解答']
const AUTOSAVE_MS = 800

interface LocalAnswer {
  user_answer_md: string
  self_rated: number | null
}

const route = useRoute()
const router = useRouter()
const paperId = computed(() => Number(route.params.id))

const detail = ref<PaperDetail | null>(null)
const loading = ref(true)
const submitting = ref(false)
const submitted = ref(false)
const currentIndex = ref(0)
const savedAt = ref('')
const saveState = ref<'idle' | 'saving' | 'error'>('idle')
const earnedScore = ref(0)
const summary = ref<PaperSubmitResult | null>(null)
const answers = reactive<Record<number, LocalAnswer>>({})
const elapsedByQuestion = reactive<Record<number, number>>({})
const graded = reactive<Record<number, PaperAnswerRow>>({})
const timers = new Map<number, ReturnType<typeof setTimeout>>()
let ticker: ReturnType<typeof setInterval> | null = null

const items = computed(() => detail.value?.items ?? [])
const current = computed(() => items.value[currentIndex.value] ?? null)
const canEdit = computed(() => !submitted.value)
const answeredCount = computed(
  () =>
    items.value.filter((item) => (answers[item.question_id]?.user_answer_md ?? '').trim().length > 0)
      .length,
)
const unratedCount = computed(
  () =>
    items.value.filter(
      (item) => isSelfRated(item.qtype) && answers[item.question_id]?.self_rated == null,
    ).length,
)
const totalSeconds = computed(() =>
  Object.values(elapsedByQuestion).reduce((sum, value) => sum + value, 0),
)
const timerText = computed(() => {
  const total = totalSeconds.value
  const hours = Math.floor(total / 3600)
  const minutes = Math.floor((total % 3600) / 60)
  const seconds = total % 60
  const mm = String(minutes).padStart(2, '0')
  const ss = String(seconds).padStart(2, '0')
  return hours > 0 ? `${hours}:${mm}:${ss}` : `${mm}:${ss}`
})
const scoreText = computed(() => {
  const total = detail.value?.total_score ?? 0
  if (summary.value) return `${summary.value.score} / ${summary.value.total_score}`
  return `${earnedScore.value} / ${total}`
})

const currentAnswerText = computed({
  get: () => {
    const questionId = current.value?.question_id
    return questionId ? (answers[questionId]?.user_answer_md ?? '') : ''
  },
  set: (value: string) => {
    const item = current.value
    if (!item || !canEdit.value) return
    answers[item.question_id] = {
      user_answer_md: value,
      self_rated: answers[item.question_id]?.self_rated ?? null,
    }
    onAnswerChange()
  },
})

const currentSelfRated = computed(() => {
  const questionId = current.value?.question_id
  return questionId ? (answers[questionId]?.self_rated ?? null) : null
})

const currentGraded = computed(() => {
  const questionId = current.value?.question_id
  return questionId ? (graded[questionId] ?? null) : null
})

function isSelfRated(qtype: string): boolean {
  return SELF_RATED_QTYPES.includes(qtype)
}

async function load(): Promise<void> {
  loading.value = true
  try {
    const [paper, answerData] = await Promise.all([
      getPaper(paperId.value),
      getPaperAnswers(paperId.value),
    ])
    detail.value = paper
    submitted.value = answerData.submitted
    earnedScore.value = answerData.earned_score ?? 0
    for (const item of paper.items) {
      answers[item.question_id] = { user_answer_md: '', self_rated: null }
      elapsedByQuestion[item.question_id] = 0
    }
    for (const row of answerData.items) {
      answers[row.question_id] = {
        user_answer_md: row.user_answer_md ?? '',
        self_rated: row.self_rated,
      }
      elapsedByQuestion[row.question_id] = row.time_spent_sec ?? 0
      graded[row.question_id] = row
    }
  } finally {
    loading.value = false
  }
}

function onAnswerChange(): void {
  const item = current.value
  if (item) scheduleSave(item.question_id)
}

function singleValue(questionId: number): string {
  return answers[questionId]?.user_answer_md ?? ''
}

function onSingleChange(value: unknown): void {
  const item = current.value
  if (!item) return
  answers[item.question_id] = {
    user_answer_md: String(value ?? ''),
    self_rated: answers[item.question_id]?.self_rated ?? null,
  }
  scheduleSave(item.question_id)
}

function multiValue(questionId: number): string[] {
  return (answers[questionId]?.user_answer_md ?? '').split('').filter(Boolean)
}

function onMultiChange(value: unknown): void {
  const item = current.value
  if (!item) return
  const list = Array.isArray(value) ? value.map(String) : []
  answers[item.question_id] = {
    user_answer_md: [...list].sort().join(''),
    self_rated: answers[item.question_id]?.self_rated ?? null,
  }
  scheduleSave(item.question_id)
}

function onSelfRate(value: unknown): void {
  const item = current.value
  if (!item) return
  answers[item.question_id] = {
    user_answer_md: answers[item.question_id]?.user_answer_md ?? '',
    self_rated: Number(value),
  }
  scheduleSave(item.question_id)
}

function scheduleSave(questionId: number): void {
  if (!canEdit.value) return
  const existing = timers.get(questionId)
  if (existing) clearTimeout(existing)
  timers.set(
    questionId,
    setTimeout(() => {
      timers.delete(questionId)
      void save(questionId)
    }, AUTOSAVE_MS),
  )
}

async function save(questionId: number): Promise<void> {
  if (!canEdit.value) return
  saveState.value = 'saving'
  try {
    const row = await savePaperAnswer(paperId.value, questionId, {
      user_answer_md: answers[questionId]?.user_answer_md || null,
      time_spent_sec: elapsedByQuestion[questionId] ?? 0,
    })
    graded[questionId] = row
    savedAt.value = new Date().toLocaleTimeString('zh-CN', { hour12: false })
    saveState.value = 'idle'
  } catch {
    saveState.value = 'error'
  }
}

async function flushSaves(): Promise<void> {
  const pending = [...timers.keys()]
  for (const questionId of pending) {
    const timer = timers.get(questionId)
    if (timer) clearTimeout(timer)
    timers.delete(questionId)
    await save(questionId)
  }
}

async function switchTo(index: number): Promise<void> {
  if (index < 0 || index >= items.value.length) return
  await flushSaves()
  currentIndex.value = index
}

async function onSubmit(): Promise<void> {
  if (!detail.value || submitting.value || submitted.value) return
  if (unratedCount.value > 0) {
    ElMessage.warning(`还有 ${unratedCount.value} 道题未自评`)
    return
  }
  const unanswered = items.value.length - answeredCount.value
  try {
    await ElMessageBox.confirm(
      unanswered > 0 ? `还有 ${unanswered} 道题未作答，确定交卷？` : '确认交卷？交卷后不可修改。',
      '确认交卷',
      { confirmButtonText: '交卷', cancelButtonText: '再检查一下', type: 'warning' },
    )
  } catch {
    return
  }
  submitting.value = true
  try {
    await flushSaves()
    const result = await submitPaper(paperId.value, {
      items: items.value.map((item) => ({
        question_id: item.question_id,
        user_answer_md: answers[item.question_id]?.user_answer_md || null,
        self_rated: isSelfRated(item.qtype)
          ? (answers[item.question_id]?.self_rated ?? null)
          : null,
        time_spent_sec: elapsedByQuestion[item.question_id] ?? 0,
      })),
    })
    summary.value = result
    submitted.value = true
    earnedScore.value = result.score
    for (const row of result.items) {
      graded[row.question_id] = {
        question_id: row.question_id,
        user_answer_md: row.user_answer_md,
        self_rated: row.self_rated,
        is_correct: row.is_correct,
        score: row.score,
        time_spent_sec: elapsedByQuestion[row.question_id] ?? null,
        saved: true,
      }
    }
    ElMessage.success(`交卷成功，得分 ${result.score} / ${result.total_score}`)
  } finally {
    submitting.value = false
  }
}

onMounted(async () => {
  await load()
  ticker = setInterval(() => {
    const questionId = current.value?.question_id
    if (!questionId || submitted.value) return
    elapsedByQuestion[questionId] = (elapsedByQuestion[questionId] ?? 0) + 1
  }, 1000)
})

onBeforeUnmount(() => {
  if (ticker) clearInterval(ticker)
  for (const timer of timers.values()) clearTimeout(timer)
  timers.clear()
})
</script>

<template>
  <section v-loading="loading" class="paper-take">
    <PageHeader
      :title="detail?.title ?? '在线作答'"
      description="作答会自动保存；填空/解答请自评，交卷后掌握度与错题本同步更新。"
    />

    <el-alert
      v-if="submitted"
      type="success"
      :closable="false"
      data-testid="submitted-banner"
      class="submitted-banner"
    >
      已提交，得分 {{ scoreText }}
    </el-alert>

    <div class="take-meta">
      <span data-testid="take-progress">已答 {{ answeredCount }} / {{ items.length }}</span>
      <span data-testid="take-timer">用时 {{ timerText }}</span>
      <span v-if="!submitted && saveState === 'saving'" class="save-state">保存中…</span>
      <span v-else-if="!submitted && savedAt" class="save-state" data-testid="save-status">
        已保存 {{ savedAt }}
      </span>
      <span v-else-if="!submitted && saveState === 'error'" class="save-state error">
        保存失败，请检查网络
      </span>
    </div>

    <div class="take-body">
      <el-card v-if="current" class="question-card">
        <template #header>
          <div class="question-head">
            <span data-testid="current-index">第 {{ currentIndex + 1 }} 题</span>
            <el-tag size="small">{{ current.qtype }}</el-tag>
            <span>{{ current.score }} 分</span>
            <span class="difficulty">难度 {{ current.difficulty }}</span>
          </div>
        </template>

        <div class="stem" data-testid="current-stem">
          <MathText :text="current.stem_md" />
        </div>

        <el-radio-group
          v-if="current.qtype === '单选'"
          class="choice-group"
          :model-value="singleValue(current.question_id)"
          :disabled="!canEdit"
          @update:model-value="onSingleChange"
        >
          <el-radio
            v-for="option in current.options"
            :key="option.key"
            :value="option.key"
            :data-testid="`option-${option.key}`"
          >
            {{ option.key }}. <MathText :text="option.text" />
          </el-radio>
        </el-radio-group>

        <el-checkbox-group
          v-else-if="current.qtype === '多选'"
          class="choice-group"
          :model-value="multiValue(current.question_id)"
          :disabled="!canEdit"
          @update:model-value="onMultiChange"
        >
          <el-checkbox
            v-for="option in current.options"
            :key="option.key"
            :value="option.key"
            :data-testid="`option-${option.key}`"
          >
            {{ option.key }}. <MathText :text="option.text" />
          </el-checkbox>
        </el-checkbox-group>

        <el-input
          v-else-if="current.qtype === '填空'"
          v-model="currentAnswerText"
          :disabled="!canEdit"
          data-testid="answer-input"
          placeholder="填写答案"
        />

        <el-input
          v-else
          v-model="currentAnswerText"
          type="textarea"
          :rows="5"
          :disabled="!canEdit"
          data-testid="answer-input"
          placeholder="写出解答过程"
        />

        <div v-if="isSelfRated(current.qtype)" class="self-rated">
          <span class="self-rated-label">自评：</span>
          <el-radio-group
            :model-value="currentSelfRated ?? undefined"
            :disabled="!canEdit"
            @update:model-value="onSelfRate"
          >
            <el-radio :value="1" data-testid="self-rated-1">对</el-radio>
            <el-radio :value="0.5" data-testid="self-rated-0.5">半对</el-radio>
            <el-radio :value="0" data-testid="self-rated-0">错</el-radio>
          </el-radio-group>
        </div>

        <div v-if="submitted && currentGraded" class="graded" data-testid="graded-result">
          <p>
            得分 {{ currentGraded?.score }} / {{ current.score }}
            <el-tag v-if="currentGraded?.is_correct" type="success" size="small">正确</el-tag>
          </p>
          <p v-if="current.answer_md">
            正确答案：<MathText :text="current.answer_md" />
          </p>
          <p v-if="current.analysis_md">解析：<MathText :text="current.analysis_md" /></p>
        </div>
      </el-card>

      <aside class="palette">
        <button
          v-for="(item, index) in items"
          :key="item.question_id"
          type="button"
          class="palette-item"
          :class="{
            active: index === currentIndex,
            answered: (answers[item.question_id]?.user_answer_md ?? '').trim().length > 0,
          }"
          :data-testid="`question-nav-${item.question_id}`"
          @click="switchTo(index)"
        >
          {{ index + 1 }}
        </button>
      </aside>
    </div>

    <div class="take-actions">
      <el-button
        :disabled="currentIndex === 0"
        data-testid="prev-button"
        @click="switchTo(currentIndex - 1)"
      >
        上一题
      </el-button>
      <el-button
        :disabled="currentIndex >= items.length - 1"
        data-testid="next-button"
        @click="switchTo(currentIndex + 1)"
      >
        下一题
      </el-button>
      <el-button
        v-if="!submitted"
        type="primary"
        :loading="submitting"
        :disabled="unratedCount > 0"
        data-testid="submit-button"
        @click="onSubmit"
      >
        交卷
      </el-button>
      <span v-if="!submitted && unratedCount > 0" class="hint">
        还有 {{ unratedCount }} 道题未自评
      </span>
    </div>

    <el-card v-if="summary" class="summary" data-testid="submit-summary">
      <template #header>交卷结果</template>
      <p data-testid="summary-score">
        {{ summary.score }} / {{ summary.total_score }}（正确 {{ summary.correct_count }} /
        {{ summary.question_count }}）
      </p>
      <ul class="mastery-list">
        <li v-for="delta in summary.mastery" :key="delta.kp_id" data-testid="mastery-delta">
          {{ delta.kp_name || `知识点 #${delta.kp_id}` }}：
          {{ delta.mastery_before === null ? '未评估' : delta.mastery_before }} →
          {{ delta.mastery_after }}（本次 {{ delta.attempts_delta }} 次）
        </li>
      </ul>
      <p v-if="summary.mistake_question_ids.length">
        错题已入库 {{ summary.mistake_question_ids.length }} 道
      </p>
      <el-button data-testid="goto-mistakes" @click="router.push('/mistakes')">去错题本</el-button>
      <el-button @click="router.push('/papers/generate')">返回组卷</el-button>
    </el-card>
  </section>
</template>

<style scoped>
.paper-take {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.submitted-banner {
  margin-bottom: 8px;
}

.take-meta {
  display: flex;
  flex-wrap: wrap;
  gap: 18px;
  align-items: center;
  color: #606266;
  font-size: 14px;
}

.save-state.error {
  color: #f56c6c;
}

.take-body {
  display: grid;
  grid-template-columns: minmax(0, 1fr) 160px;
  gap: 16px;
  align-items: start;
}

.question-head {
  display: flex;
  gap: 12px;
  align-items: center;
}

.difficulty {
  color: #909399;
  font-size: 12px;
}

.stem {
  margin-bottom: 16px;
  line-height: 1.8;
}

.choice-group {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.self-rated {
  margin-top: 16px;
  display: flex;
  gap: 12px;
  align-items: center;
}

.self-rated-label {
  color: #606266;
}

.graded {
  margin-top: 20px;
  padding-top: 12px;
  border-top: 1px dashed #dcdfe6;
  line-height: 1.8;
}

.palette {
  display: grid;
  grid-template-columns: repeat(5, 1fr);
  gap: 8px;
}

.palette-item {
  height: 32px;
  border: 1px solid #dcdfe6;
  border-radius: 4px;
  background: #fff;
  cursor: pointer;
}

.palette-item.answered {
  background: #ecf5ff;
  border-color: #409eff;
}

.palette-item.active {
  background: #409eff;
  border-color: #409eff;
  color: #fff;
}

.take-actions {
  display: flex;
  gap: 12px;
  align-items: center;
}

.hint {
  color: #e6a23c;
  font-size: 13px;
}

.summary {
  margin-top: 8px;
}

.mastery-list {
  margin: 8px 0;
  padding-left: 20px;
  line-height: 1.8;
}

@media (max-width: 900px) {
  .take-body {
    grid-template-columns: 1fr;
  }

  .palette {
    grid-template-columns: repeat(8, 1fr);
  }
}
</style>