<script setup lang="ts">
import { useRouter } from 'vue-router'

defineProps<{
  code: string
  title: string
  description: string
}>()

const router = useRouter()
</script>

<template>
  <div class="status-page">
    <p class="status-code" aria-hidden="true">{{ code }}</p>
    <h1>{{ title }}</h1>
    <p>{{ description }}</p>
    <el-button type="primary" @click="router.replace('/notes')">返回首页</el-button>
  </div>
</template>

<style scoped>
.status-page {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  min-height: 100vh;
  padding: 24px;
  text-align: center;
}

.status-code {
  margin: 0;
  color: var(--app-primary);
  font-size: 48px;
  font-weight: 600;
  line-height: 1;
  font-variant-numeric: tabular-nums;
}

.status-page h1 {
  margin: 20px 0 8px;
  font-size: 20px;
}

.status-page p {
  margin: 0 0 24px;
  color: var(--app-text-secondary);
  font-size: 13px;
}
</style>