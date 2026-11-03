<script setup lang="ts">
/**
 * S4-5 图谱关系审核：AI 推断的边默认待校验，通过才生效；驳回记墓碑。
 * 可视化留给 S4-6，这里只做审核。
 */
import { onMounted, watch } from 'vue'

import type { GraphEdge } from '@/types/kp'
import { useGraphReview } from './useGraphReview'

const props = defineProps<{ subjectId: number }>()
const {
  edges,
  stats,
  total,
  page,
  pageSize,
  status,
  relation,
  keyword,
  loading,
  building,
  selection,
  pendingCount,
  RELATION_LABELS,
  load,
  review,
  reviewSelected,
  rebuild,
} = useGraphReview(() => props.subjectId)

onMounted(load)
watch(
  () => props.subjectId,
  () => {
    page.value = 1
    load()
  },
)

function onSelectionChange(rows: GraphEdge[]): void {
  selection.value = rows
}
</script>

<template>
  <div class="graph-review">
    <div class="graph-summary" data-testid="graph-stats">
      <span>节点 {{ stats?.nodes ?? 0 }}</span>
      <span>关系 {{ stats?.edges ?? 0 }}</span>
      <span class="pending">待校验 {{ pendingCount() }}</span>
      <el-button
        type="primary"
        size="small"
        data-testid="graph-rebuild"
        :loading="building"
        @click="rebuild"
      >
        重新构建
      </el-button>
    </div>

    <div class="graph-filters">
      <el-select v-model="status" data-testid="graph-status" style="width: 130px">
        <el-option label="待校验" value="pending" />
        <el-option label="已通过" value="approved" />
        <el-option label="已驳回" value="rejected" />
        <el-option label="全部" value="all" />
      </el-select>
      <el-select
        v-model="relation"
        clearable
        placeholder="全部关系"
        style="width: 130px"
      >
        <el-option label="包含" value="contains" />
        <el-option label="前置" value="prerequisite" />
        <el-option label="相关" value="related" />
        <el-option label="易混" value="confusable" />
      </el-select>
      <el-input
        v-model="keyword"
        placeholder="知识点名称"
        clearable
        style="width: 180px"
        @keyup.enter="load"
      />
      <el-button data-testid="graph-search" @click="load">查询</el-button>
      <el-button
        data-testid="graph-batch-approve"
        :disabled="selection.length === 0"
        @click="reviewSelected(true)"
      >
        批量通过
      </el-button>
      <el-button
        data-testid="graph-batch-reject"
        :disabled="selection.length === 0"
        @click="reviewSelected(false)"
      >
        批量驳回
      </el-button>
    </div>

    <el-table
      v-loading="loading"
      :data="edges"
      row-key="id"
      data-testid="graph-table"
      @selection-change="onSelectionChange"
    >
      <el-table-column type="selection" width="44" />
      <el-table-column prop="src_name" label="起点" min-width="160" />
      <el-table-column label="关系" width="90">
        <template #default="{ row }">
          <el-tag size="small">{{ RELATION_LABELS[row.relation] ?? row.relation }}</el-tag>
        </template>
      </el-table-column>
      <el-table-column prop="dst_name" label="终点" min-width="160" />
      <el-table-column label="置信度/相似度" width="130">
        <template #default="{ row }">
          {{ row.weight === null ? '—' : Number(row.weight).toFixed(2) }}
        </template>
      </el-table-column>
      <el-table-column prop="source" label="来源" width="80" />
      <el-table-column prop="review_status" label="状态" width="90" />
      <el-table-column label="操作" width="140" fixed="right">
        <template #default="{ row }">
          <el-button link type="primary" @click="review(row, true)">通过</el-button>
          <el-button link type="danger" @click="review(row, false)">驳回</el-button>
        </template>
      </el-table-column>
      <template #empty>
        <div class="graph-empty" data-testid="graph-empty">
          还没有 AI 推断的关系，点「重新构建」生成
        </div>
      </template>
    </el-table>

    <el-pagination
      v-model:current-page="page"
      :page-size="pageSize"
      :total="total"
      layout="total, prev, pager, next"
      class="graph-pager"
    />
  </div>
</template>

<style scoped>
.graph-summary {
  display: flex;
  gap: 16px;
  align-items: center;
  margin-bottom: 12px;
  font-size: 13px;
}

.graph-summary .pending {
  color: var(--app-warning);
}

.graph-filters {
  display: flex;
  gap: 10px;
  margin-bottom: 12px;
}

.graph-empty {
  padding: 40px;
  color: var(--app-text-tertiary);
}

.graph-pager {
  justify-content: flex-end;
  margin-top: 12px;
}
</style>