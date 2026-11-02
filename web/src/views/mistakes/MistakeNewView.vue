<script setup lang="ts">
/**
 * S4-2 拍照录入页：选图 + 学科 + 可选手填作答 → 提交异步任务 → 轮询 → 跳详情。
 *
 * 不用 el-upload 的自动上传：题目图片需要和「我的作答」作为一次表单提交，
 * 且失败重试必须复用同一个 File 对象；原生 file input 更直接。
 */
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'

import PageHeader from '@/components/common/PageHeader.vue'
import { listSubjects } from '@/api/kp'
import { createMistakeFromPhoto } from '@/api/mistakes'
import { getTask } from '@/api/tasks'
import type { SubjectOut } from '@/types/kp'
import type { MistakeRecognizeResult } from '@/types/mistakes'
import type { TaskDetail } from '@/types/tasks'

/** 识别通常 10–30s：4s 轮询一次，60s 还没终态就提示可重试。 */
const POLL_INTERVAL_MS = 4000
const POLL_TIMEOUT_S = 60

type Phase = 'idle' | 'submitting' | 'polling' | 'failed'

const router = useRouter()
const subjects = ref<SubjectOut[]>([])
const subjectId = ref<number | null>(null)
const file = ref<File | null>(null)
const previewUrl = ref('')
const myAnswerMd = ref('')
const phase = ref<Phase>('idle')
/** 当前轮询的任务 id；重试会换任务，旧任务的迟到响应必须丢弃。 */
const taskId = ref<number | null>(null)
const elapsed = ref(0)
const errorText = ref('')

let pollTimer: number | undefined
let elapsedTimer: number | undefined
/** 卸载后迟到的请求不许再导航/弹提示（用户可能已点「改用题库选题」离开）。 */
let disposed = false

const busy = computed(() => phase.value === 'submitting' || phase.value === 'polling')
const canSubmit = computed(() => file.value !== null && subjectId.value !== null && !busy.value)
const pollingHint = computed(
  () => `识别中… 已用时 ${elapsed.value}s（每 4 秒查询一次，约 60 秒仍无结果会提示重试）`,
)

/** TaskDetail.result 是联合类型，按 `mistake_id` 收窄到错题识别结果。 */
function isRecognizeResult(value: TaskDetail['result']): value is MistakeRecognizeResult {
  return value !== null && 'mistake_id' in value
}

function stopTimers(): void {
  if (pollTimer !== undefined) {
    window.clearInterval(pollTimer)
    pollTimer = undefined
  }
  if (elapsedTimer !== undefined) {
    window.clearInterval(elapsedTimer)
    elapsedTimer = undefined
  }
}

function releasePreview(): void {
  if (previewUrl.value) {
    URL.revokeObjectURL(previewUrl.value)
    previewUrl.value = ''
  }
}

function onFileChange(event: Event): void {
  const picked = (event.target as HTMLInputElement).files?.[0] ?? null
  if (!picked) return
  releasePreview()
  file.value = picked
  previewUrl.value = URL.createObjectURL(picked)
  // 重新选图后旧的失败提示已过期，回到可提交态。
  if (phase.value === 'failed') {
    phase.value = 'idle'
    errorText.value = ''
  }
}

function onSucceeded(detail: TaskDetail): void {
  const result = detail.result
  if (!isRecognizeResult(result)) {
    phase.value = 'failed'
    errorText.value = '识别任务已完成，但没有返回错题信息，请重试。'
    return
  }
  // 低置信与重复录入都只是提醒，仍进详情页让学生核对。
  if (result.low_confidence) {
    ElMessage.warning('识别置信度偏低，请在详情页核对题干')
  }
  if (!result.created) {
    ElMessage.warning('该题已在错题本，已重置为待订正')
  }
  phase.value = 'idle'
  void router.push('/mistakes/' + result.mistake_id)
}

/** 从 axios 错误上取 HTTP 状态；业务错误（HTTP 200 + code）没有 response，返回 null。 */
function httpStatus(error: unknown): number | null {
  if (typeof error !== 'object' || error === null || !('response' in error)) return null
  const response = (error as { response?: { status?: number } }).response
  return typeof response?.status === 'number' ? response.status : null
}

async function poll(id: number): Promise<void> {
  let detail: TaskDetail
  try {
    detail = await getTask(id)
  } catch (error) {
    if (disposed) return
    if (httpStatus(error) === 404) {
      // 任务被清理/过期后继续轮询只会空转到超时，直接给可重试的失败态。
      stopTimers()
      phase.value = 'failed'
      errorText.value = '任务不存在或已过期，请重试'
    }
    // 其他错误按网络抖动处理，下一轮再试；http.ts 已统一提示。
    return
  }
  if (disposed) return
  // 重试会换新任务：旧任务迟到的响应不能改写新任务的状态。
  if (taskId.value !== id || phase.value !== 'polling') return
  if (detail.status === 'succeeded') {
    stopTimers()
    onSucceeded(detail)
  } else if (detail.status === 'failed') {
    stopTimers()
    phase.value = 'failed'
    errorText.value = detail.error ?? '识别失败，请重试或改用题库选题。'
  }
}

function startPolling(id: number): void {
  taskId.value = id
  phase.value = 'polling'
  elapsed.value = 0
  const startedAt = Date.now()
  stopTimers()
  // 立即查一次，省掉最短 4s 的空等。
  void poll(id)
  pollTimer = window.setInterval(() => {
    void poll(id)
  }, POLL_INTERVAL_MS)
  elapsedTimer = window.setInterval(() => {
    elapsed.value = Math.round((Date.now() - startedAt) / 1000)
    if (elapsed.value >= POLL_TIMEOUT_S) {
      stopTimers()
      phase.value = 'failed'
      errorText.value = '识别超时（已等待约 60 秒），可重试或改用题库选题。'
    }
  }, 1000)
}

async function submit(): Promise<void> {
  const picked = file.value
  const subject = subjectId.value
  if (!picked || subject === null || busy.value) return
  stopTimers()
  taskId.value = null
  errorText.value = ''
  phase.value = 'submitting'
  try {
    // 空作答不 append（api/mistakes.ts 已按空串跳过），避免把空串当学生作答落库。
    const task = await createMistakeFromPhoto(picked, subject, myAnswerMd.value.trim() || undefined)
    // 请求期间页面已卸载：不要再起轮询（否则定时器与导航都泄漏到已离开的页面）。
    if (disposed) return
    startPolling(task.id)
  } catch {
    if (disposed) return
    // http.ts 已统一弹错；停在可重试态并保留文件与参数。
    phase.value = 'failed'
    errorText.value = '提交失败，请重试或改用题库选题。'
  }
}

function retry(): void {
  if (busy.value) return
  void submit()
}

function goPick(): void {
  void router.push('/mistakes')
}

onMounted(async () => {
  try {
    subjects.value = await listSubjects()
  } catch {
    subjects.value = []
  }
})

onBeforeUnmount(() => {
  disposed = true
  stopTimers()
  releasePreview()
})
</script>

<template>
  <div class="mistake-new" data-testid="mistake-new">
    <PageHeader
      title="拍照录入错题"
      description="拍下题目照片，系统识别题干与答案，再进详情页核对与订正。"
    />

    <el-card shadow="never" class="card">
      <el-form label-width="96px">
        <el-form-item label="学科" required>
          <el-select
            v-model="subjectId"
            data-testid="subject-select"
            class="subject-select"
            placeholder="选择学科"
          >
            <el-option
              v-for="subject in subjects"
              :key="subject.id"
              :label="subject.name"
              :value="subject.id"
            />
          </el-select>
        </el-form-item>

        <el-form-item label="题目照片" required>
          <div class="file-row">
            <input
              data-testid="image-input"
              class="file-input"
              type="file"
              accept="image/png,image/jpeg"
              capture="environment"
              :disabled="busy"
              @change="onFileChange"
            />
            <span class="tip">支持 JPG / PNG；手机端会直接调起相机。</span>
          </div>
          <img
            v-if="previewUrl"
            :src="previewUrl"
            class="preview"
            data-testid="preview-image"
            alt="待识别题目预览"
          >
        </el-form-item>

        <el-form-item label="我的作答">
          <el-input
            v-model="myAnswerMd"
            data-testid="my-answer"
            type="textarea"
            :rows="3"
            placeholder="可选：手填你的作答；手填内容优先于图片识别结果。"
          />
        </el-form-item>

        <el-form-item>
          <el-button
            type="primary"
            data-testid="submit"
            :disabled="!canSubmit"
            :loading="busy"
            @click="submit"
          >
            开始识别
          </el-button>
          <el-button data-testid="switch-pick" @click="goPick">改用题库选题</el-button>
        </el-form-item>
      </el-form>
    </el-card>

    <el-card v-if="busy" shadow="never" data-testid="polling-hint">
      <el-alert type="info" :closable="false" show-icon :title="pollingHint" />
    </el-card>

    <el-card v-if="phase === 'failed'" shadow="never" data-testid="submit-error">
      <el-alert
        type="error"
        :closable="false"
        show-icon
        title="识别失败"
        :description="errorText"
      />
      <div class="error-actions">
        <el-button type="primary" data-testid="retry" @click="retry">重试</el-button>
        <el-button data-testid="fallback-pick" @click="goPick">改用题库选题</el-button>
      </div>
    </el-card>
  </div>
</template>

<style scoped>
.mistake-new {
  display: grid;
  gap: 16px;
}

.card {
  background: var(--app-surface);
  border-radius: var(--app-radius-md);
}

.subject-select {
  width: 220px;
}

.file-row {
  display: flex;
  flex-wrap: wrap;
  gap: 12px;
  align-items: center;
}

.file-input {
  max-width: 320px;
}

.tip {
  color: var(--app-text-tertiary);
  font-size: 12px;
}

.preview {
  display: block;
  max-width: 100%;
  max-height: 320px;
  margin-top: 12px;
  border: 1px solid var(--app-border);
  border-radius: var(--app-radius-md);
}

.error-actions {
  display: flex;
  gap: 8px;
  margin-top: 12px;
}
</style>