<script setup lang="ts">
/**
 * S4-2 错题详情页：题干/选项/作答/复习操作 + S4-3 诊断占位。
 *
 * 缩略图不能直接 `<img :src="detail.image_url">`：后端 `/api/v1/files/{id}/image`
 * 要求 `Authorization: Bearer`，而 `<img>` 发起的请求无法携带自定义头，必然 401。
 * 因此改为经 http.ts 拦截器带 token 的 `getImageBlob` 取图，再转 objectURL 渲染，
 * 离开页面时 revoke，避免 blob 泄漏。
 */
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { MdPreview } from 'md-editor-v3'

import PageHeader from '@/components/common/PageHeader.vue'
import { getImageBlob } from '@/api/files'
import { listSubjects } from '@/api/kp'
import {
  analyzeMistake,
  deleteMistake,
  getMistake,
  reviewMistake,
  updateMistake,
} from '@/api/mistakes'
import { getTask } from '@/api/tasks'
import type { SubjectOut } from '@/types/kp'
import {
  MISTAKE_CAUSE_LABELS,
  type MistakeAnalysis,
  type MistakeAnalyzeResult as MistakeAnalysisResultView,
  type MistakeDetail,
  type MistakeStatus,
} from '@/types/mistakes'

import 'md-editor-v3/lib/preview.css'
import 'katex/dist/katex.min.css'

/** S4-3 才会下发的相似题字段；共享类型尚未包含，这里按可选字段兼容。 */
interface MistakeAnalysisView extends MistakeAnalysis {
  similar_questions_json?: unknown
}

/** image_url 形如 `/api/v1/files/{file_id}/image`，鉴权取图需要其中的 file_id。 */
const IMAGE_PATH_RE = /\/files\/(\d+)\/image/

const route = useRoute()
const router = useRouter()

const detail = ref<MistakeDetail | null>(null)
const loading = ref(true)
const loadError = ref(false)
const subjects = ref<SubjectOut[]>([])
const answerDraft = ref('')
const saving = ref(false)
const reviewing = ref(false)
const deleting = ref(false)
const imageObjectUrl = ref('')
const imageLoading = ref(false)
/** 卸载标记与取图序号：迟到的图片响应既不能渲染，也不能留下未回收的 blob URL。 */
let disposed = false
let imageSeq = 0

const analysis = computed<MistakeAnalysisView | null>(() =>
  detail.value?.analysis ? (detail.value.analysis as MistakeAnalysisView) : null,
)

/** 相似题在 S4-3 回来前兜底为空；对象项按 JSON 文本展示。 */
const similarQuestions = computed<string[]>(() => {
  const raw = analysis.value?.similar_questions_json
  if (!Array.isArray(raw)) return []
  return raw.map((item) => (typeof item === 'string' ? item : JSON.stringify(item)))
})

const subjectName = computed(() => {
  const id = detail.value?.subject_id
  if (id === undefined) return '—'
  return subjects.value.find((item) => item.id === id)?.name ?? `学科 #${id}`
})

function statusTagType(status: MistakeStatus): 'warning' | 'primary' | 'success' {
  if (status === '已掌握') return 'success'
  if (status === '已订正') return 'primary'
  return 'warning'
}

function formatTime(value: string): string {
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return value
  const pad = (part: number) => String(part).padStart(2, '0')
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())} ${pad(
    date.getHours(),
  )}:${pad(date.getMinutes())}`
}

function releaseImage(): void {
  if (imageObjectUrl.value) {
    URL.revokeObjectURL(imageObjectUrl.value)
    imageObjectUrl.value = ''
  }
}

async function loadImage(url: string | null): Promise<void> {
  const seq = ++imageSeq
  releaseImage()
  imageLoading.value = false
  if (!url) return
  const match = IMAGE_PATH_RE.exec(url)
  if (!match) return
  imageLoading.value = true
  try {
    const blob = await getImageBlob(Number(match[1]))
    const objectUrl = URL.createObjectURL(blob)
    // 卸载或已切到别的错题：这张图不会再有 DOM 使用，立即 revoke，避免 blob 泄漏。
    if (disposed || seq !== imageSeq) {
      URL.revokeObjectURL(objectUrl)
      return
    }
    imageObjectUrl.value = objectUrl
  } catch {
    // http.ts 已统一提示；图片失败不影响题干与复习操作。
  } finally {
    if (!disposed && seq === imageSeq) imageLoading.value = false
  }
}

function applyDetail(data: MistakeDetail): void {
  detail.value = data
  answerDraft.value = data.my_answer_md ?? ''
}

async function load(): Promise<void> {
  loading.value = true
  loadError.value = false
  try {
    const data = await getMistake(Number(route.params.id))
    if (disposed) return
    applyDetail(data)
    // 图片单独异步加载：慢图不能把题干/作答/复习按钮一起挡在「加载中」后面。
    loading.value = false
    void loadImage(data.image_url)
  } catch {
    if (disposed) return
    // http.ts 已统一提示；404 与越权在这里统一成同一条文案，不泄露存在性。
    loadError.value = true
    loading.value = false
  }
}

async function loadSubjects(): Promise<void> {
  try {
    subjects.value = await listSubjects()
  } catch {
    subjects.value = []
  }
}

async function saveAnswer(): Promise<void> {
  if (!detail.value || saving.value) return
  const text = answerDraft.value.trim()
  saving.value = true
  try {
    // 显式 null 才会清库：PATCH 里空串与缺省都做不到清空。
    const updated = await updateMistake(detail.value.id, { myAnswerMd: text ? text : null })
    applyDetail(updated)
    ElMessage.success('已保存作答')
  } catch {
    // http.ts 已统一提示，保留编辑内容供修改
  } finally {
    saving.value = false
  }
}

async function review(correct: boolean): Promise<void> {
  if (!detail.value || reviewing.value) return
  reviewing.value = true
  try {
    // 用返回值直接刷新本地状态，不再多发一次 getMistake。
    const updated = await reviewMistake(detail.value.id, correct)
    applyDetail(updated)
    ElMessage.success(`已记录为「${updated.status}」，连续答对 ${updated.correct_streak} 次`)
  } catch {
    // http.ts 已统一提示
  } finally {
    reviewing.value = false
  }
}

async function remove(): Promise<void> {
  if (!detail.value || deleting.value) return
  try {
    await ElMessageBox.confirm('删除后不可恢复，确认删除这道错题？', '删除错题', {
      type: 'warning',
      confirmButtonText: '删除',
      cancelButtonText: '取消',
    })
  } catch {
    return
  }
  deleting.value = true
  try {
    await deleteMistake(detail.value.id)
    ElMessage.success('已删除')
    await router.push('/mistakes')
  } catch {
    // http.ts 已统一提示
  } finally {
    deleting.value = false
  }
}

/** 诊断轮询：任务在 4 秒间隔下轮询，成功/失败/卸载都要停表，避免孤儿定时器。 */
const analyzing = ref(false)
const analyzeError = ref('')
const analyzeTaskId = ref<number | null>(null)
const analyzeSeconds = ref(0)
let analyzeTimer: ReturnType<typeof setInterval> | null = null

const lowConfidence = computed(() => {
  const value = analysis.value?.confidence
  return value !== null && value !== undefined && value < 0.5
})

function stopAnalyzePolling(): void {
  if (analyzeTimer !== null) {
    clearInterval(analyzeTimer)
    analyzeTimer = null
  }
}

function resetAnalyzeState(): void {
  stopAnalyzePolling()
  analyzeSeconds.value = 0
  analyzeTaskId.value = null
}

async function pollAnalyze(): Promise<void> {
  const taskId = analyzeTaskId.value
  if (taskId === null || !analyzing.value) return
  try {
    const task = await getTask(taskId)
    // 卸载或重跑后迟到的响应：既不能刷新详情，也不能把 analyzing 改回 false
    if (!analyzing.value) return
    if (task.status === 'succeeded') {
      const result = task.result as MistakeAnalysisResultView | null
      resetAnalyzeState()
      analyzing.value = false
      await load()
      if (result?.skipped) ElMessage.info('已有诊断，未重复调用')
      return
    }
    if (task.status === 'failed') {
      analyzeError.value = task.error || '诊断失败，可重试'
      resetAnalyzeState()
      analyzing.value = false
    }
  } catch {
    // http.ts 已弹错；这里只停轮询，避免无限重试把后端打满
    resetAnalyzeState()
    analyzing.value = false
  }
}

async function startAnalyze(): Promise<void> {
  if (analyzing.value || detail.value === null) return
  analyzeError.value = ''
  analyzing.value = true
  try {
    const task = await analyzeMistake(detail.value.id, true)
    analyzeTaskId.value = task.id
    analyzeSeconds.value = 0
    analyzeTimer = setInterval(() => {
      analyzeSeconds.value += 4
      void pollAnalyze()
    }, 4000)
  } catch {
    analyzing.value = false
    analyzeError.value = '发起诊断失败，请稍后重试'
  }
}

onMounted(() => {
  void load()
  void loadSubjects()
})

// 列表 → 详情 → 详情（同组件复用）时 params 变化，需要按新 id 重取。
watch(
  () => route.params.id,
  () => {
    if (disposed) return
    void load()
  },
)

onBeforeUnmount(() => {
  disposed = true
  imageSeq += 1
  releaseImage()
  // analyzing 先落 false：迟到的轮询响应会据此丢弃，不再回写已卸载的组件
  analyzing.value = false
  resetAnalyzeState()
})
</script>

<template>
  <div class="mistake-detail" data-testid="mistake-detail">
    <PageHeader title="错题详情" description="核对题干与作答，记录本次复习结果。">
      <template #actions>
        <el-button data-testid="back-list" @click="router.push('/mistakes')">返回列表</el-button>
      </template>
    </PageHeader>

    <div v-if="loading" class="loading" data-testid="detail-loading">加载中…</div>

    <div v-else-if="loadError" class="load-error" data-testid="detail-error">
      <p>错题不存在或无权访问</p>
      <el-button data-testid="detail-back" @click="router.push('/mistakes')">返回列表</el-button>
    </div>

    <template v-else-if="detail">
      <el-card shadow="never" class="card">
        <div class="summary-row">
          <el-tag :type="statusTagType(detail.status)" data-testid="status-tag">
            {{ detail.status }}
          </el-tag>
          <span class="summary-item" data-testid="correct-streak">
            连续答对 {{ detail.correct_streak }} 次
          </span>
          <span class="summary-item">录入时间 {{ formatTime(detail.created_at) }}</span>
          <span class="summary-item" data-testid="subject-name">学科 {{ subjectName }}</span>
          <span class="summary-item">题型 {{ detail.qtype }}</span>
          <span class="summary-item">难度 {{ detail.difficulty }}/5</span>
        </div>
      </el-card>

      <el-card shadow="never" class="card">
        <template #header>
          <span>题干</span>
        </template>
        <div class="stem" data-testid="stem">
          <MdPreview :model-value="detail.stem_md" :no-mermaid="true" preview-theme="github" />
        </div>
        <ul v-if="detail.options && detail.options.length" class="options" data-testid="options">
          <li
            v-for="option in detail.options"
            :key="option.key"
            :data-testid="`option-${option.key}`"
          >
            <strong>{{ option.key }}.</strong> <span>{{ option.text }}</span>
          </li>
        </ul>
        <div v-if="imageLoading || imageObjectUrl" class="image-wrap">
          <div v-if="imageLoading" class="image-loading" data-testid="image-loading">
            图片加载中…
          </div>
          <img
            v-else
            :src="imageObjectUrl"
            class="image"
            data-testid="image-preview"
            alt="错题原图"
          >
        </div>
      </el-card>

      <el-card shadow="never" class="card">
        <template #header>
          <span>作答</span>
        </template>
        <label class="field-label" for="my-answer">我的作答</label>
        <el-input
          id="my-answer"
          v-model="answerDraft"
          data-testid="my-answer"
          type="textarea"
          :rows="4"
          placeholder="写下你的作答，保存后用于订正对比。"
        />
        <div class="answer-actions">
          <el-button
            type="primary"
            data-testid="save-answer"
            :loading="saving"
            @click="saveAnswer"
          >
            保存作答
          </el-button>
        </div>

        <template v-if="detail.correct_answer_md">
          <span class="field-label">正确答案</span>
          <div class="correct-answer" data-testid="correct-answer">
            <MdPreview
              :model-value="detail.correct_answer_md"
              :no-mermaid="true"
              preview-theme="github"
            />
          </div>
        </template>
        <p v-else class="muted">暂无正确答案</p>
      </el-card>

      <div class="review-actions">
        <el-button
          type="success"
          data-testid="review-correct"
          :loading="reviewing"
          @click="review(true)"
        >
          答对了
        </el-button>
        <el-button
          type="warning"
          data-testid="review-wrong"
          :loading="reviewing"
          @click="review(false)"
        >
          答错了
        </el-button>
        <el-button
          type="danger"
          plain
          data-testid="delete-mistake"
          :loading="deleting"
          @click="remove"
        >
          删除
        </el-button>
      </div>

      <el-card shadow="never" class="card" data-testid="analysis">
        <template #header>
          <div class="section-head">
            <span>AI 错因诊断</span>
            <el-button
              v-if="analysis"
              size="small"
              data-testid="rerun-analysis"
              :loading="analyzing"
              :disabled="analyzing"
              @click="startAnalyze"
            >
              重新诊断
            </el-button>
          </div>
        </template>

        <el-alert
          v-if="analyzeError"
          type="error"
          :title="analyzeError"
          :closable="false"
          show-icon
        />

        <div v-if="analyzing" class="analyzing" data-testid="analyzing">
          <span class="spinner" aria-hidden="true" />
          诊断中…已等待 {{ analyzeSeconds }} 秒
        </div>

        <template v-else-if="analysis">
          <div class="cause-row">
            <el-tag :type="analysis.cause_type === 'unknown' ? 'info' : 'warning'" size="small">
              {{ MISTAKE_CAUSE_LABELS[analysis.cause_type] }}
            </el-tag>
            <el-tag
              v-for="cause in analysis.secondary_causes"
              :key="cause"
              size="small"
              type="info"
              effect="plain"
            >
              {{ cause }}
            </el-tag>
            <span v-if="analysis.confidence !== null" class="confidence">
              置信度 {{ Math.round(analysis.confidence * 100) }}%
            </span>
          </div>
          <el-alert
            v-if="lowConfidence"
            type="warning"
            title="诊断把握较低，建议人工确认"
            :closable="false"
            show-icon
          />
          <p v-if="analysis.cause_type === 'unknown'" class="hint">
            未提供作答，仅讲解题目，不推断错因。
          </p>
          <template v-else>
            <p class="field-label">第一处错误</p>
            <p class="error-step">{{ analysis.error_step || '未定位到明确的错误步骤' }}</p>
          </template>
          <p class="field-label">正确解法</p>
          <MdPreview
            :model-value="analysis.explanation_md || '（无）'"
            :no-mermaid="true"
            preview-theme="github"
          />
          <p class="field-label">复习建议</p>
          <MdPreview
            :model-value="analysis.review_advice_md || '（无）'"
            :no-mermaid="true"
            preview-theme="github"
          />
          <template v-if="similarQuestions.length">
            <p class="field-label">相似题</p>
            <ul class="similar-list">
              <li v-for="(item, index) in similarQuestions" :key="index">{{ item }}</li>
            </ul>
          </template>
          <p class="hint">
            诊断模型：{{ analysis.model }} · Prompt {{ analysis.prompt_version }}
          </p>
        </template>

        <el-empty v-else description="尚未诊断">
          <el-button type="primary" data-testid="start-analysis" @click="startAnalyze">
            立即诊断
          </el-button>
        </el-empty>
      </el-card>
    </template>
  </div>
</template>

<style scoped>
.mistake-detail {
  display: grid;
  gap: 16px;
}

.card {
  background: var(--app-surface);
  border-radius: var(--app-radius-md);
}

.loading,
.load-error {
  padding: 48px 0;
  color: var(--app-text-secondary);
  text-align: center;
}

.summary-row {
  display: flex;
  flex-wrap: wrap;
  gap: 12px 20px;
  align-items: center;
}

.summary-item {
  color: var(--app-text-secondary);
  font-size: 13px;
}

.stem {
  font-size: 15px;
  line-height: 1.7;
}

.options {
  padding-left: 4px;
  margin: 16px 0 0;
  list-style: none;
}

.options li {
  padding: 4px 0;
}

.image-wrap {
  margin-top: 16px;
}

.image-loading {
  padding: 24px;
  color: var(--app-text-tertiary);
  font-size: 13px;
  text-align: center;
  border: 1px dashed var(--app-border);
  border-radius: var(--app-radius-md);
}

.image {
  display: block;
  max-width: 100%;
  max-height: 360px;
  border: 1px solid var(--app-border);
  border-radius: var(--app-radius-md);
}

.field-label {
  display: block;
  margin: 12px 0 8px;
  color: var(--app-text-secondary);
  font-size: 13px;
}

.answer-actions {
  margin-top: 12px;
}

.correct-answer {
  padding: 12px;
  background: var(--app-surface-muted, var(--app-surface));
  border: 1px solid var(--app-border);
  border-radius: var(--app-radius-md);
}

.muted {
  color: var(--app-text-tertiary);
  font-size: 13px;
}

.review-actions {
  display: flex;
  gap: 8px;
}

.analysis-row {
  display: flex;
  gap: 12px;
  margin: 8px 0;
}

.similar-list {
  padding-left: 20px;
  margin: 8px 0 0;
}

.section-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.cause-row {
  display: flex;
  gap: 8px;
  align-items: center;
  flex-wrap: wrap;
  margin-bottom: 8px;
}

.confidence {
  color: var(--app-text-tertiary);
  font-size: 12px;
}

.error-step {
  padding: 8px 12px;
  margin: 4px 0 12px;
  white-space: pre-wrap;
  background: var(--app-surface-muted, var(--app-surface));
  border-left: 3px solid var(--el-color-warning);
}

.hint {
  color: var(--app-text-tertiary);
  font-size: 12px;
}

.analyzing {
  display: flex;
  gap: 6px;
  align-items: center;
  color: var(--app-text-secondary);
}

/* 不引 @element-plus/icons-vue：一个转圈不值得多一个依赖（AGENTS §2.1） */
.spinner {
  width: 12px;
  height: 12px;
  border: 2px solid var(--app-border);
  border-top-color: var(--el-color-primary);
  border-radius: 50%;
  animation: spin 0.8s linear infinite;
}

@keyframes spin {
  to {
    transform: rotate(360deg);
  }
}
</style>