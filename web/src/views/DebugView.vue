<script setup lang="ts">
/**
 * S0-6 验收页：调后端 GET /health，验证「跨域 + axios 封装 + 统一响应壳」整条链路。
 */
import { onMounted, ref } from 'vue'
import http, { type ApiEnvelope } from '@/api/http'

interface HealthData {
  status: string
  app: string
  version: string
  env: string
}

const loading = ref(true)
const failed = ref(false)
const result = ref<ApiEnvelope<HealthData> | null>(null)
const errorText = ref('')

async function load(): Promise<void> {
  loading.value = true
  failed.value = false
  try {
    const resp = await http.get<ApiEnvelope<HealthData>>('/health')
    result.value = resp.data
  } catch (err) {
    failed.value = true
    errorText.value = err instanceof Error ? err.message : String(err)
  } finally {
    loading.value = false
  }
}

onMounted(() => {
  void load()
})
</script>

<template>
  <main class="debug-page">
    <el-card>
      <template #header>
        <div class="card-header">
          <span>后端健康检查（GET /health）</span>
          <el-button :loading="loading" @click="load">刷新</el-button>
        </div>
      </template>

      <el-skeleton v-if="loading" :rows="3" animated />

      <el-alert
        v-else-if="failed"
        type="error"
        :title="`请求失败：${errorText}`"
        :closable="false"
        show-icon
      />

      <el-descriptions v-else-if="result" :column="1" border>
        <el-descriptions-item label="status">
          <el-tag :type="result.data.status === 'ok' ? 'success' : 'danger'">
            {{ result.data.status }}
          </el-tag>
        </el-descriptions-item>
        <el-descriptions-item label="app">{{ result.data.app }}</el-descriptions-item>
        <el-descriptions-item label="version">{{ result.data.version }}</el-descriptions-item>
        <el-descriptions-item label="env">{{ result.data.env }}</el-descriptions-item>
        <el-descriptions-item label="code">{{ result.code }}</el-descriptions-item>
        <el-descriptions-item label="trace_id">{{ result.trace_id }}</el-descriptions-item>
      </el-descriptions>
    </el-card>
  </main>
</template>

<style scoped>
.debug-page {
  max-width: 720px;
  margin: 40px auto;
  padding: 0 16px;
}

.card-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
}
</style>
