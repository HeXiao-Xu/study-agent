<script setup lang="ts">
/** S4-1 审题页：左侧题库列表，右侧单题编辑；支持合并、拆分、删除与公式预览。 */
import { computed, onMounted, reactive, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { MdPreview } from 'md-editor-v3'
import MathText from '@/components/common/MathText.vue'

import PageHeader from '@/components/common/PageHeader.vue'
import {
  deleteQuestion,
  getQuestion,
  listQuestions,
  mergeQuestions,
  splitQuestion,
  updateQuestion,
} from '@/api/questions'
import { getKpTree, listSubjects } from '@/api/kp'
import { useAuthStore } from '@/stores/auth'
import type {
  QuestionDetail,
  QuestionOption,
  QuestionSummary,
  QuestionType,
  QuestionUpdatePayload,
} from '@/types/questions'
import type { KpNode } from '@/types/kp'

import 'md-editor-v3/lib/preview.css'
import 'katex/dist/katex.min.css'

interface KpOption {
  id: number
  label: string
}

const PAGE_SIZE = 20

const route = useRoute()
const router = useRouter()
const auth = useAuthStore()

const rows = ref<QuestionSummary[]>([])
const total = ref(0)
const page = ref(1)
const keyword = ref('')
const loading = ref(false)
const listError = ref(false)
const detail = ref<QuestionDetail | null>(null)
const splitAt = ref('')
const selection = ref<number[]>([])
const kpOptions = ref<KpOption[]>([])
const kpOptionsSubject = ref<number | null>(null)
const subjectCodes = ref<Record<number, string>>({})

const form = reactive({
  stem_md: '',
  qtype: '解答' as QuestionType,
  difficulty: 3,
  answer_md: '',
  analysis_md: '',
  options: [] as QuestionOption[],
  kp_ids: [] as number[],
})

const canEdit = computed(() => {
  const user = auth.user
  if (!user || !detail.value) return false
  return user.role === 'teacher' || user.role === 'admin' || detail.value.created_by === user.id
})

/** KpNode 自带 children（api/kp.ts 一次查库组树），据此深度优先拍平成下拉项。 */
function flattenKps(nodes: KpNode[], prefix = ''): KpOption[] {
  const out: KpOption[] = []
  for (const node of nodes) {
    out.push({ id: node.id, label: `${prefix}${node.name}` })
    if (node.children.length) {
      out.push(...flattenKps(node.children, `${prefix}${node.name} / `))
    }
  }
  return out
}

async function loadList(): Promise<void> {
  loading.value = true
  listError.value = false
  try {
    const data = await listQuestions({
      page: page.value,
      page_size: PAGE_SIZE,
      keyword: keyword.value.trim() || undefined,
      source_file_id: route.query.source_file_id
        ? Number(route.query.source_file_id)
        : undefined,
    })
    rows.value = data.items
    total.value = data.total
  } catch {
    // http.ts 已统一提示，这里只保留可重试的局部状态
    listError.value = true
  } finally {
    loading.value = false
  }
}

function onSelectionChange(selected: QuestionSummary[]): void {
  selection.value = selected.map((row) => row.id)
}

function applyDetail(data: QuestionDetail): void {
  detail.value = data
  form.stem_md = data.stem_md
  form.qtype = data.qtype
  form.difficulty = data.difficulty
  form.answer_md = data.answer_md ?? ''
  form.analysis_md = data.analysis_md ?? ''
  form.options = data.options_json ? data.options_json.map((item) => ({ ...item })) : []
  form.kp_ids = data.kps.map((item) => item.kp_id)
  splitAt.value = ''
}

/** getKpTree 收的是学科 code；subject_id → code 由 /kp/subjects 映射。 */
async function loadKpOptions(subjectId: number): Promise<void> {
  if (kpOptionsSubject.value === subjectId) return
  if (!Object.keys(subjectCodes.value).length) {
    const subjects = await listSubjects()
    subjectCodes.value = Object.fromEntries(subjects.map((item) => [item.id, item.code]))
  }
  const code = subjectCodes.value[subjectId]
  if (!code) {
    kpOptions.value = []
    kpOptionsSubject.value = null
    return
  }
  const tree = await getKpTree(code)
  kpOptions.value = flattenKps(tree.nodes)
  kpOptionsSubject.value = subjectId
}

async function openQuestion(id: number): Promise<void> {
  const data = await getQuestion(id).catch(() => null)
  if (!data) return
  applyDetail(data)
  await loadKpOptions(data.subject_id).catch(() => {
    kpOptions.value = []
  })
}

/** 后端收到 kp_ids 会整体重建链接并把 weight 写成 MANUAL_WEIGHT=1.0，未改选时必须省略该字段。 */
function kpIdsChanged(current: number[], next: number[]): boolean {
  const left = [...current].sort((a, b) => a - b)
  const right = [...next].sort((a, b) => a - b)
  return left.length !== right.length || left.some((id, index) => id !== right[index])
}

async function save(): Promise<void> {
  if (!detail.value || !canEdit.value) return
  const payload: QuestionUpdatePayload = {
    stem_md: form.stem_md,
    qtype: form.qtype,
    difficulty: form.difficulty,
    answer_md: form.answer_md.trim() ? form.answer_md : null,
    analysis_md: form.analysis_md.trim() ? form.analysis_md : null,
    options: form.options.length ? form.options : null,
  }
  if (kpIdsChanged(detail.value.kps.map((item) => item.kp_id), form.kp_ids)) {
    payload.kp_ids = [...form.kp_ids]
  }
  try {
    const updated = await updateQuestion(detail.value.id, payload)
    applyDetail(updated)
    ElMessage.success('已保存')
    await loadList()
  } catch {
    // http.ts 已统一提示，保留表单内容供修改
  }
}

async function split(): Promise<void> {
  if (!detail.value || !canEdit.value) return
  const marker = splitAt.value.trim()
  if (!marker) {
    ElMessage.warning('请填写切分标记（第二道题开头的文字）')
    return
  }
  try {
    const created = await splitQuestion(detail.value.id, marker)
    ElMessage.success(`已拆成 ${created.length} 道题`)
    if (created[0]) applyDetail(created[0])
    else detail.value = null
    await loadList()
  } catch {
    // http.ts 已统一提示
  }
}

async function merge(): Promise<void> {
  if (selection.value.length < 2 || selection.value.length > 10) {
    ElMessage.warning('请勾选 2–10 道题再合并')
    return
  }
  try {
    const merged = await mergeQuestions(selection.value)
    ElMessage.success(`已合并为题目 #${merged.id}`)
    selection.value = []
    await loadList()
    await openQuestion(merged.id)
  } catch {
    // http.ts 已统一提示
  }
}

async function remove(): Promise<void> {
  if (!detail.value || !canEdit.value) return
  try {
    await ElMessageBox.confirm('删除后不可恢复，确认删除这道题？', '确认删除', { type: 'warning' })
  } catch {
    return
  }
  try {
    await deleteQuestion(detail.value.id)
    ElMessage.success('已删除')
    detail.value = null
    await loadList()
  } catch {
    // http.ts 已统一提示
  }
}

function addOption(): void {
  form.options.push({ key: String.fromCharCode(65 + form.options.length), text: '' })
}

function removeOption(index: number): void {
  form.options.splice(index, 1)
}

onMounted(() => {
  void loadList()
})
</script>

<template>
  <div class="review-view">
    <PageHeader title="题库" description="AI 切题后逐题核对：可直接用 / 需小改 / 需重录。">
      <template #actions>
        <el-button @click="router.push('/questions/import')">导入试卷</el-button>
      </template>
    </PageHeader>

    <div class="review-view__body">
      <el-card shadow="never" class="review-view__list">
        <div class="review-view__toolbar">
          <el-input
            v-model="keyword"
            placeholder="搜索题干"
            clearable
            data-test="keyword"
            @keyup.enter="loadList"
          />
          <el-button @click="loadList">搜索</el-button>
          <el-button
            data-test="merge"
            :disabled="selection.length < 2 || selection.length > 10"
            @click="merge"
          >
            合并所选（{{ selection.length }}）
          </el-button>
        </div>

        <el-alert
          v-if="listError"
          type="error"
          :closable="false"
          show-icon
          title="题库加载失败"
          class="review-view__alert"
        >
          <el-button size="small" @click="loadList">重试</el-button>
        </el-alert>

        <el-table
          v-loading="loading"
          :data="rows"
          row-key="id"
          @selection-change="onSelectionChange"
        >
          <el-table-column type="selection" width="42" />
          <el-table-column prop="id" label="ID" width="64" />
          <el-table-column prop="qtype" label="题型" width="72" />
          <el-table-column prop="difficulty" label="难度" width="64" />
          <el-table-column label="题干" min-width="220">
            <template #default="{ row }">
              <span
                :data-test="`row-${row.id}`"
                class="review-view__stem"
                :title="row.stem_md"
                @click="openQuestion(row.id)"
              >
                <MathText :text="row.stem_md" />
              </span>
            </template>
          </el-table-column>
          <el-table-column label="知识点" min-width="120">
            <template #default="{ row }">
              <el-tag
                v-for="name in row.kp_names"
                :key="name"
                size="small"
                class="review-view__tag"
              >
                {{ name }}
              </el-tag>
            </template>
          </el-table-column>
          <el-table-column label="来源" width="80">
            <template #default="{ row }">
              <el-tag :type="row.verified ? 'success' : 'warning'" size="small">
                {{ row.verified ? '卷面' : 'AI/无' }}
              </el-tag>
            </template>
          </el-table-column>
        </el-table>

        <el-pagination
          v-model:current-page="page"
          :total="total"
          :page-size="PAGE_SIZE"
          layout="prev, pager, next"
          class="review-view__pager"
          @current-change="loadList"
        />
      </el-card>

      <el-card v-if="detail" shadow="never" class="review-view__detail">
        <template #header>
          <span>题目 #{{ detail.id }}</span>
          <el-tag :type="detail.verified ? 'success' : 'warning'" size="small" class="review-view__tag">
            {{ detail.verified ? '卷面答案' : 'AI / 无答案' }}
          </el-tag>
        </template>

        <el-form label-width="72px">
          <el-form-item label="题干">
            <el-input v-model="form.stem_md" data-test="stem" type="textarea" :rows="6" />
          </el-form-item>
          <el-form-item label="预览">
            <MdPreview
              v-if="form.stem_md"
              :model-value="form.stem_md"
              :no-mermaid="true"
              preview-theme="github"
            />
          </el-form-item>
          <el-form-item label="题型">
            <el-select v-model="form.qtype" style="width: 140px">
              <el-option label="单选" value="单选" />
              <el-option label="多选" value="多选" />
              <el-option label="填空" value="填空" />
              <el-option label="解答" value="解答" />
            </el-select>
          </el-form-item>
          <el-form-item label="难度">
            <el-rate v-model="form.difficulty" :max="5" />
          </el-form-item>
          <el-form-item v-if="form.qtype === '单选' || form.qtype === '多选'" label="选项">
            <div
              v-for="(option, index) in form.options"
              :key="index"
              class="review-view__option"
            >
              <el-input v-model="option.key" style="width: 60px" />
              <el-input v-model="option.text" />
              <el-button link type="danger" @click="removeOption(index)">删除</el-button>
            </div>
            <el-button size="small" @click="addOption">增加选项</el-button>
          </el-form-item>
          <el-form-item label="答案">
            <el-input v-model="form.answer_md" type="textarea" :rows="2" />
          </el-form-item>
          <el-form-item label="解析">
            <el-input v-model="form.analysis_md" type="textarea" :rows="3" />
          </el-form-item>
          <el-form-item label="知识点">
            <el-select v-model="form.kp_ids" multiple filterable style="width: 100%">
              <el-option
                v-for="option in kpOptions"
                :key="option.id"
                :label="option.label"
                :value="option.id"
              />
            </el-select>
          </el-form-item>
          <el-form-item>
            <el-button type="primary" data-test="save" :disabled="!canEdit" @click="save">
              保存
            </el-button>
            <el-button danger data-test="delete" :disabled="!canEdit" @click="remove">
              删除
            </el-button>
          </el-form-item>
        </el-form>

        <el-divider content-position="left">拆分 / 合并</el-divider>
        <div class="review-view__split">
          <el-input
            v-model="splitAt"
            data-test="split-at"
            placeholder="切分标记：第二道题开头的文字，例如 2."
            :disabled="!canEdit"
          />
          <el-button data-test="split" :disabled="!canEdit" @click="split">拆分</el-button>
        </div>
        <p class="review-view__hint">
          合并请在左侧勾选 2–10 道题后点「合并所选」；合并与拆分都会硬删原题，操作不可撤销。
        </p>
      </el-card>

      <el-card v-else shadow="never" class="review-view__detail">
        <el-empty description="点击左侧题干预览开始审题" />
      </el-card>
    </div>
  </div>
</template>

<style scoped>
.review-view__body {
  display: grid;
  grid-template-columns: minmax(420px, 1fr) minmax(420px, 1fr);
  gap: 16px;
}

.review-view__toolbar {
  display: flex;
  gap: 8px;
  margin-bottom: 12px;
}

.review-view__alert {
  margin-bottom: 12px;
}

.review-view__stem {
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
  color: var(--el-color-primary);
  cursor: pointer;
}

.review-view__tag {
  margin-right: 6px;
}

.review-view__pager {
  margin-top: 12px;
}

.review-view__option {
  display: flex;
  gap: 8px;
  width: 100%;
  margin-bottom: 6px;
}

.review-view__split {
  display: flex;
  gap: 8px;
  max-width: 480px;
}

.review-view__hint {
  margin: 8px 0 0;
  color: var(--el-text-color-secondary);
  font-size: 12px;
}
</style>