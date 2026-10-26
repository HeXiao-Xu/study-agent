<script setup lang="ts">
import { computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'

import EmptyState from '@/components/common/EmptyState.vue'
import PageHeader from '@/components/common/PageHeader.vue'

const route = useRoute()
const router = useRouter()

const title = computed(() => String(route.meta.title ?? '功能'))
const description = computed(() => String(route.meta.description ?? ''))
const task = computed(() => String(route.meta.task ?? '后续任务'))
</script>

<template>
  <div>
    <PageHeader :title="title" :description="description" />
    <EmptyState
      title="功能建设中"
      :description="`计划在 ${task} 交付。当前只完成应用骨架，避免用假数据让你误判进度。`"
    >
      <el-button type="primary" @click="router.push('/notes')">返回笔记</el-button>
    </EmptyState>
  </div>
</template>