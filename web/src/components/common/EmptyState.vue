<script setup lang="ts">
defineProps<{
  title: string
  description?: string
}>()
</script>

<template>
  <div class="empty-state">
    <div class="empty-mark" aria-hidden="true">·</div>
    <h2>{{ title }}</h2>
    <p v-if="description">{{ description }}</p>
    <div class="empty-actions">
      <slot name="actions" />
    </div>
  </div>
</template>

<style scoped>
.empty-state {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  padding: 72px 24px;
  background: var(--app-surface);
  border: 1px solid var(--app-border);
  border-radius: var(--app-radius-md);
  text-align: center;
}

.empty-mark {
  display: grid;
  width: 40px;
  height: 40px;
  margin-bottom: 16px;
  place-items: center;
  color: var(--app-primary);
  font-size: 28px;
  line-height: 1;
  background: var(--app-primary-soft);
  border-radius: 50%;
}

.empty-state h2 {
  margin: 0 0 8px;
  font-size: 16px;
  font-weight: 600;
}

.empty-state p {
  max-width: 460px;
  margin: 0;
  color: var(--app-text-secondary);
  font-size: 13px;
}

.empty-actions {
  margin-top: 20px;
}
</style>