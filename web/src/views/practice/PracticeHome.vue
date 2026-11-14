<script setup lang="ts">
/** S5-7 练习入口：不列草稿、不新增接口，只做三个现有流程的入口。 */
import PageHeader from '@/components/common/PageHeader.vue'

const entries = [
  {
    title: '今日复习',
    description: '按掌握度与到期时间生成的清单，逐项完成或顺延。',
    to: '/review',
    action: '打开复习清单',
  },
  {
    title: '智能组卷',
    description: '选知识点、题型与难度，生成后可直接在线作答。',
    to: '/papers/generate',
    action: '开始组卷',
  },
  {
    title: '错题回顾',
    description: '查看错题、诊断结果与变式题。',
    to: '/mistakes',
    action: '打开错题本',
  },
] as const
</script>

<template>
  <div class="practice-page">
    <PageHeader
      title="练习"
      description="从复习清单、组卷或错题本进入练习；保存的试卷可在「我的试卷」继续作答。"
    />
    <div class="practice-grid">
      <article v-for="entry in entries" :key="entry.title" class="practice-card">
        <h2>{{ entry.title }}</h2>
        <p>{{ entry.description }}</p>
        <router-link :to="entry.to">
          <el-button type="primary" plain>{{ entry.action }}</el-button>
        </router-link>
      </article>
    </div>
    <p class="practice-note">
      已保存的试卷在 <router-link to="/papers">我的试卷</router-link> 查看，可继续作答或导出 PDF。
    </p>
  </div>
</template>

<style scoped>
.practice-page {
  display: flex;
  flex-direction: column;
  gap: 16px;
}
.practice-grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 12px;
}
.practice-card {
  display: grid;
  gap: 12px;
  padding: 20px;
  background: #fff;
  border: 1px solid #eaecf0;
  border-radius: 10px;
}
.practice-card h2 {
  margin: 0;
  font-size: 16px;
}
.practice-card p {
  margin: 0;
  color: #667085;
  font-size: 13px;
  line-height: 1.7;
}
.practice-note {
  margin: 0;
  color: #98a2b3;
  font-size: 12px;
}
</style>