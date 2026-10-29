<script setup lang="ts">
import StudentOnlyView from '@/components/common/StudentOnlyView.vue'
import NoteListView from './NoteListView.vue'
</script>

<template>
  <StudentOnlyView feature="笔记">
    <NoteListView />
  </StudentOnlyView>
</template>
