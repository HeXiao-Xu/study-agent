<script setup lang="ts">
/** S4-1 导入试卷：上传 → 轮询任务 → 展示统计（无题级进度，只显示已用时）。 */
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import type { UploadFile } from 'element-plus'

import PageHeader from '@/components/common/PageHeader.vue'
import { importQuestions } from '@/api/questions'
import { getTask } from '@/api/tasks'
import { listSubjects } from '@/api/kp'
import { useAuthStore } from '@/stores/auth'
import type { QuestionOrigin } from '@/types/questions'
import type { SubjectOut } from '@/types/kp'
import type { ExtractTaskResult, TaskDetail } from '@/types/tasks'

const router = useRouter()
const auth = useAuthStore()
const subjects = ref<SubjectOut[]>([])
const subjectId = ref<number | null>(null)
const origin = ref<QuestionOrigin>('upload')
const file = ref<File | null>(null)
const taskId = ref<number | null>(null)
const task = ref<TaskDetail | null>(null)
const elapsed = ref(0)
const submitting = ref(false)
let timer: number | undefined

// 后端只允许学生按 upload 记来源，教师/管理员才能选考试卷、模拟卷、教材。
const canChooseOrigin = computed(() => auth.user?.role === 'teacher' || auth.user?.role === 'admin')
// TaskDetail.result 现在是联合类型（含 S4-2 错题识别结果），按任务结果字段收窄。
const result = computed<ExtractTaskResult | null>(() => {
  const value = task.value?.result
  return value !== null && value !== undefined && 'detected_count' in value ? value : null
})
const failedItems = computed(() => result.value?.failed_items ?? [])
const finished = computed(
  () => task.value?.status === 'succeeded' || task.value?.status === 'failed',
)
const running = computed(() => taskId.value !== null && !finished.value)

function stopPolling(): void {
  if (timer !== undefined) {
    window.clearInterval(timer)
    timer = undefined
  }
}

function onExceed(): void {
  ElMessage.warning('一次只能导入一份试卷')
}

function onFileChange(uploadFile: UploadFile): void {
  file.value = (uploadFile.raw as File | undefined) ?? null
}

function onFileRemove(): void {
  file.value = null
}

async function poll(id: number): Promise<void> {
  try {
    const detail = await getTask(id)
    task.value = detail
    if (detail.status === 'succeeded' || detail.status === 'failed') stopPolling()
  } catch {
    stopPolling()
  }
}

async function submit(): Promise<void> {
  if (!file.value || !subjectId.value) {
    ElMessage.warning('请选择学科并上传试卷')
    return
  }
  submitting.value = true
  elapsed.value = 0
  task.value = null
  try {
    const created = await importQuestions(file.value, subjectId.value, origin.value)
    taskId.value = created.id
    const startedAt = Date.now()
    stopPolling()
    timer = window.setInterval(() => {
      elapsed.value = Math.round((Date.now() - startedAt) / 1000)
      if (taskId.value !== null) void poll(taskId.value)
    }, 1500)
  } catch {
    // http.ts 已统一提示，这里只保证 submitting 复位、页面可重试
  } finally {
    submitting.value = false
  }
}

function goReview(): void {
  const fileId = result.value?.file_id
  router.push({ path: '/questions', query: fileId ? { source_file_id: String(fileId) } : {} })
}

onMounted(async () => {
  try {
    subjects.value = await listSubjects()
  } catch {
    subjects.value = []
  }
})
onBeforeUnmount(stopPolling)
</script>

<template>
  <div class="import-view">
    <PageHeader title="导入试卷" description="上传 PDF 或 DOCX 试卷，系统自动切题并入库。" />

    <el-card shadow="never" class="import-view__card">
      <el-form label-width="88px">
        <el-form-item label="学科">
          <el-select v-model="subjectId" placeholder="选择学科" style="width: 220px">
            <el-option
              v-for="subject in subjects"
              :key="subject.id"
              :label="subject.name"
              :value="subject.id"
            />
          </el-select>
        </el-form-item>
        <el-form-item label="题目来源">
          <el-radio-group v-if="canChooseOrigin" v-model="origin">
            <el-radio value="upload">学生上传</el-radio>
            <el-radio value="exam">考试卷</el-radio>
            <el-radio value="mock">模拟卷</el-radio>
            <el-radio value="textbook">教材</el-radio>
          </el-radio-group>
          <span v-else class="import-view__fixed-origin">学生上传</span>
        </el-form-item>
        <el-form-item label="试卷文件">
          <el-upload
            :auto-upload="false"
            :limit="1"
            accept=".pdf,.docx"
            :on-change="onFileChange"
            :on-remove="onFileRemove"
            :on-exceed="onExceed"
          >
            <el-button>选择文件</el-button>
            <template #tip>
              <div class="import-view__tip">仅支持 PDF / DOCX；扫描件与拍照识别将在 S4-2 支持。</div>
            </template>
          </el-upload>
        </el-form-item>
        <el-form-item>
          <el-button type="primary" :loading="submitting" @click="submit">开始切题</el-button>
        </el-form-item>
      </el-form>
    </el-card>

    <el-card v-if="taskId !== null" shadow="never" class="import-view__card">
      <template #header>
        <span>切题任务 #{{ taskId }}</span>
      </template>
      <el-alert
        v-if="running"
        type="info"
        :closable="false"
        show-icon
        :title="`切题中… 已用时 ${elapsed}s（20 题通常 60–90s）`"
      />
      <el-alert
        v-else-if="task?.status === 'failed'"
        type="error"
        :closable="false"
        show-icon
        :title="`切题失败：${task.error ?? '未知原因'}`"
      />
      <template v-else>
        <el-descriptions :column="3" border>
          <el-descriptions-item label="识别题数">{{ result?.detected_count }}</el-descriptions-item>
          <el-descriptions-item label="新增">{{ result?.created }}</el-descriptions-item>
          <el-descriptions-item label="重复跳过">{{ result?.duplicated }}</el-descriptions-item>
          <el-descriptions-item label="卷面声明">{{ result?.expected_count ?? '—' }}</el-descriptions-item>
          <el-descriptions-item label="降级切题">{{ result?.degraded ? '是' : '否' }}</el-descriptions-item>
          <el-descriptions-item label="耗时">
            {{ Math.round((result?.elapsed_ms ?? 0) / 1000) }}s
          </el-descriptions-item>
        </el-descriptions>

        <el-alert
          v-if="failedItems.length"
          class="import-view__alert"
          type="warning"
          :closable="false"
          show-icon
          title="部分题目未能自动切出，请人工补录"
        >
          <div v-for="item in failedItems" :key="item.index">
            第 {{ item.index }} 题：{{ item.reason }}
          </div>
        </el-alert>
        <el-alert
          v-for="warning in result?.warnings ?? []"
          :key="warning"
          class="import-view__alert"
          type="warning"
          :closable="false"
          :title="warning"
        />

        <el-button type="primary" @click="goReview">去审题</el-button>
      </template>
    </el-card>
  </div>
</template>

<style scoped>
.import-view__card {
  margin-bottom: 16px;
}
.import-view__tip {
  color: var(--el-text-color-secondary);
  font-size: 12px;
}
.import-view__fixed-origin {
  color: var(--app-text);
  font-size: 14px;
}
.import-view__alert {
  margin: 12px 0;
}
</style>