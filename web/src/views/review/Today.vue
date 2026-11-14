<script setup lang="ts">
/**
 * S5-7 今日复习清单。
 *
 * done/skip/later 都不改掌握度；页面只做移除、进度与“已记录”提示，
 * 不把“完成”包装成掌握度提升。
 */
import { ElMessage } from 'element-plus'
import { computed, onMounted, ref } from 'vue'

import {
  markReviewDone,
  markReviewLater,
  markReviewSkip,
  refreshReview,
} from '@/api/review'
import EmptyState from '@/components/common/EmptyState.vue'
import PageHeader from '@/components/common/PageHeader.vue'
import type { ReviewItem, ReviewToday } from '@/types/review'

import {
  minutesLabel,
  progressOf,
  reviewRefPath,
  truncatedLabel,
} from './useReviewProgress'

type ReviewAction = 'done' | 'skip' | 'later'

const data = ref<ReviewToday | null>(null)
const loading = ref(true)
const refreshing = ref(false)
const error = ref('')
const total = ref(0)
const processed = ref(0)
const pendingId = ref<number | null>(null)
const pendingAction = ref<ReviewAction | null>(null)
const actionError = ref('')

const items = computed(() => data.value?.items ?? [])
const progress = computed(() => progressOf(total.value, processed.value))
const truncated = computed(() => truncatedLabel(data.value?.truncated_count ?? null))
const allDone = computed(
  () => data.value !== null && items.value.length === 0 && processed.value > 0,
)

const actions: Record<ReviewAction, (id: number) => Promise<ReviewItem>> = {
  done: markReviewDone,
  skip: markReviewSkip,
  later: markReviewLater,
}

function itemPath(item: ReviewItem): string {
  return reviewRefPath(item) ?? ''
}

function overdueText(days: number): string {
  return days > 0 ? `逾期 ${days.toFixed(1)} 天` : '今日到期'
}

async function load(): Promise<void> {
  loading.value = true
  error.value = ''
  try {
    const out = await refreshReview()
    data.value = out
    total.value = out.item_count
    processed.value = 0
  } catch {
    data.value = null
    error.value = '复习清单加载失败，请重试'
  } finally {
    loading.value = false
  }
}

async function refresh(): Promise<void> {
  refreshing.value = true
  error.value = ''
  try {
    const out = await refreshReview()
    data.value = out
    total.value = out.item_count
    processed.value = 0
  } catch {
    error.value = '复习清单刷新失败，请重试'
  } finally {
    refreshing.value = false
  }
}

async function act(item: ReviewItem, action: ReviewAction): Promise<void> {
  if (pendingId.value !== null) return
  pendingId.value = item.id
  pendingAction.value = action
  actionError.value = ''
  try {
    await actions[action](item.id)
    if (data.value !== null) {
      const next = data.value.items.filter((row) => row.id !== item.id)
      data.value = { ...data.value, items: next, item_count: next.length }
    }
    processed.value += 1
    ElMessage.success(action === 'later' ? '已顺延到明天' : '已记录')
  } catch {
    actionError.value = '操作失败，请重试'
  } finally {
    pendingId.value = null
    pendingAction.value = null
  }
}

onMounted(() => {
  void load()
})
</script>

<template>
  <div class="review-page">
    <PageHeader
      title="今日复习"
      description="按掌握度与到期时间排序；完成/跳过只记今天，掌握度由后续作答更新。"
    >
      <template #actions>
        <el-button
          :loading="refreshing"
          data-testid="review-refresh"
          @click="refresh"
        >
          重新生成
        </el-button>
      </template>
    </PageHeader>

    <el-skeleton v-if="loading" :rows="5" animated data-testid="review-loading" />

    <el-alert
      v-else-if="error"
      type="error"
      :closable="false"
      :title="error"
      data-testid="review-error"
    >
      <el-button size="small" @click="load">重试</el-button>
    </el-alert>

    <template v-else-if="data">
      <section class="review-summary">
        <div>
          <strong>{{ data.date }}</strong>
          <span>{{ data.timezone }} · {{ minutesLabel(data.total_minutes) }} / 上限 {{ data.cap_minutes }} 分钟</span>
        </div>
        <div class="review-progress" data-testid="review-progress">
          <span>{{ progress.label }}</span>
          <el-progress :percentage="progress.percent" :show-text="false" :stroke-width="8" />
        </div>
      </section>

      <el-alert
        v-if="truncated"
        type="warning"
        :closable="false"
        :title="truncated"
        data-testid="review-truncated"
      />
      <el-alert
        v-if="actionError"
        type="error"
        :closable="false"
        :title="actionError"
        data-testid="review-action-error"
      />

      <TransitionGroup
        v-if="items.length"
        name="review-list"
        tag="div"
        class="review-list"
        data-testid="review-list"
      >
        <article
          v-for="item in items"
          :key="item.id"
          class="review-card"
          :data-testid="`review-item-${item.id}`"
        >
          <header class="review-card__head">
            <div>
              <h3>{{ item.kp_name }}</h3>
              <p>
                <span v-if="item.low_mastery" class="review-badge">薄弱</span>
                <span>掌握度 {{ item.mastery_t.toFixed(2) }}</span>
                <span>{{ overdueText(item.overdue_days) }}</span>
                <span>优先级 {{ item.priority.toFixed(2) }}</span>
              </p>
            </div>
            <el-tag effect="plain">{{ minutesLabel(item.estimated_minutes) }}</el-tag>
          </header>

          <router-link
            v-if="itemPath(item)"
            :to="itemPath(item)"
            class="review-ref"
            data-testid="review-ref-link"
          >
            {{ item.ref_title || '查看参考内容' }} →
          </router-link>
          <p v-else class="review-ref review-ref--disabled">参考资源已删除</p>

          <footer class="review-actions">
            <el-button
              type="primary"
              :loading="pendingId === item.id && pendingAction === 'done'"
              :disabled="pendingId !== null"
              :data-testid="`done-${item.id}`"
              @click="act(item, 'done')"
            >
              完成
            </el-button>
            <el-button
              :loading="pendingId === item.id && pendingAction === 'skip'"
              :disabled="pendingId !== null"
              :data-testid="`skip-${item.id}`"
              @click="act(item, 'skip')"
            >
              跳过
            </el-button>
            <el-button
              :loading="pendingId === item.id && pendingAction === 'later'"
              :disabled="pendingId !== null"
              :data-testid="`later-${item.id}`"
              @click="act(item, 'later')"
            >
              稍后
            </el-button>
          </footer>
        </article>
      </TransitionGroup>

      <EmptyState
        v-else
        :title="allDone ? '今天的复习已完成' : '今天没有待复习项'"
        :description="
          allDone
            ? '完成的项不会改变掌握度；去组卷或作答后，掌握度与到期时间才会更新。'
            : '可以先组一份卷子，或稍后回来重新生成清单。'
        "
        data-testid="review-empty"
      >
        <template #actions>
          <router-link to="/papers/generate">
            <el-button type="primary">去组卷</el-button>
          </router-link>
          <el-button @click="refresh">重新生成</el-button>
        </template>
      </EmptyState>
    </template>
  </div>
</template>

<style scoped>
.review-page {
  display: flex;
  flex-direction: column;
  gap: 16px;
}
.review-summary {
  display: flex;
  justify-content: space-between;
  gap: 24px;
  padding: 14px 16px;
  background: #fff;
  border: 1px solid #eaecf0;
  border-radius: 10px;
}
.review-summary strong {
  display: block;
  color: #101828;
  font-size: 16px;
}
.review-summary span {
  color: #667085;
  font-size: 12px;
}
.review-progress {
  display: grid;
  min-width: 240px;
  gap: 4px;
  font-size: 12px;
  color: #667085;
}
.review-list {
  display: grid;
  gap: 12px;
}
.review-card {
  display: grid;
  gap: 12px;
  padding: 16px;
  background: #fff;
  border: 1px solid #eaecf0;
  border-radius: 10px;
}
.review-card__head {
  display: flex;
  justify-content: space-between;
  gap: 16px;
}
.review-card h3 {
  margin: 0;
  color: #101828;
  font-size: 16px;
}
.review-card__head p {
  display: flex;
  flex-wrap: wrap;
  gap: 12px;
  margin: 6px 0 0;
  color: #667085;
  font-size: 12px;
}
.review-badge {
  padding: 0 6px;
  color: #b42318;
  background: #fef3f2;
  border-radius: 999px;
}
.review-ref {
  color: #3538cd;
  font-size: 13px;
}
.review-ref--disabled {
  color: #98a2b3;
  margin: 0;
}
.review-actions {
  display: flex;
  gap: 8px;
}
.review-list-leave-active {
  transition: opacity 160ms ease, transform 160ms ease;
}
.review-list-leave-to {
  opacity: 0;
  transform: translateX(16px);
}
</style>