<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'

import { listSubjects } from '@/api/kp'
import PageHeader from '@/components/common/PageHeader.vue'
import type { SubjectOut } from '@/types/kp'
import PendingAlign from './PendingAlign.vue'
import Tree from './Tree.vue'

const subjects = ref<SubjectOut[]>([])
const selectedSubject = ref('')
const activeTab = ref<'tree' | 'pending'>('tree')
const loading = ref(false)
const error = ref('')

const selected = computed(
  () => subjects.value.find((subject) => subject.code === selectedSubject.value) ?? null,
)

async function loadSubjects(): Promise<void> {
  loading.value = true
  error.value = ''
  try {
    subjects.value = await listSubjects()
    if (!subjects.value.some((subject) => subject.code === selectedSubject.value)) {
      selectedSubject.value = subjects.value[0]?.code ?? ''
    }
  } catch {
    error.value = '学科加载失败，请重试'
  } finally {
    loading.value = false
  }
}

onMounted(loadSubjects)
</script>

<template>
  <div class="knowledge-page">
    <PageHeader
      title="知识库"
      description="浏览知识点树，处理笔记自动对齐产生的待确认候选。"
    />

    <div v-if="error" class="knowledge-error" role="alert">
      {{ error }}
      <el-button
        link
        type="primary"
        data-testid="retry-subjects"
        @click="loadSubjects"
      >
        重试
      </el-button>
    </div>

    <el-tabs v-model="activeTab" class="knowledge-tabs">
      <el-tab-pane label="知识点树" name="tree">
        <div class="subject-bar">
          <span class="subject-label">学科</span>
          <el-select
            v-model="selectedSubject"
            placeholder="选择学科"
            :loading="loading"
            style="width: 220px"
          >
            <el-option
              v-for="subject in subjects"
              :key="subject.code"
              :label="subject.name"
              :value="subject.code"
            />
          </el-select>
        </div>

        <Tree v-if="selected" :subject="selected.code" />
        <div v-else-if="!loading && !error" class="subject-empty">
          暂无学科数据
        </div>
      </el-tab-pane>

      <el-tab-pane label="待确认对齐" name="pending">
        <PendingAlign v-if="activeTab === 'pending'" />
      </el-tab-pane>
    </el-tabs>
  </div>
</template>

<style scoped>
.knowledge-page {
  min-width: 0;
}

.knowledge-error {
  display: flex;
  gap: 8px;
  align-items: center;
  padding: 10px 14px;
  margin-bottom: 14px;
  color: var(--app-danger);
  font-size: 13px;
  background: #fff5f5;
  border: 1px solid #ffc9c9;
  border-radius: var(--app-radius-sm);
}

.knowledge-tabs {
  margin-top: 8px;
}

.subject-bar {
  display: flex;
  gap: 10px;
  align-items: center;
  margin-bottom: 14px;
}

.subject-label {
  color: var(--app-text-secondary);
  font-size: 13px;
}

.subject-empty {
  padding: 48px;
  color: var(--app-text-tertiary);
  text-align: center;
}
</style>
