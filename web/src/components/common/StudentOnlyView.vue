<script setup lang="ts">
import { computed } from 'vue'
import { useRouter } from 'vue-router'

import { useAuthStore } from '@/stores/auth'
import EmptyState from './EmptyState.vue'
import PageHeader from './PageHeader.vue'

const props = defineProps<{
  feature: string
}>()

const auth = useAuthStore()
const router = useRouter()
const isStudent = computed(() => auth.user?.role === 'student')
</script>

<template>
  <div>
    <PageHeader :title="props.feature" description="学生个人学习空间" />

    <slot v-if="isStudent" />

    <EmptyState
      v-else
      title="暂不支持查看"
      :description="`${props.feature}功能仅向学生开放；教师/管理员请前往知识库管理知识点。`"
    >
      <template #actions>
        <el-button type="primary" @click="router.push('/knowledge')">
          前往知识库
        </el-button>
      </template>
    </EmptyState>
  </div>
</template>
