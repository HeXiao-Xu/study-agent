<script setup lang="ts">
/**
 * 占位页：Task 10 的路由（`/questions`）按计划指向 ReviewView。
 * 完整审题页（列表 / 编辑 / 合并 / 拆分）由 Task 11 交付并替换本文件；
 * 这里只保证 Task 10 提交时路由动态导入不悬空、`npm run build` 可过。
 */
import { useRouter } from 'vue-router'

import PageHeader from '@/components/common/PageHeader.vue'

const router = useRouter()
</script>

<template>
  <div class="review-view">
    <PageHeader title="题库" description="AI 切题后逐题核对：可直接用 / 需小改 / 需重录。" />
    <el-card shadow="never">
      <el-empty description="审题页将在 S4-1 后续任务上线，可先导入试卷。">
        <el-button type="primary" @click="router.push('/questions/import')">导入试卷</el-button>
      </el-empty>
    </el-card>
  </div>
</template>