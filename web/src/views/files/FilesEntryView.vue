<script setup lang="ts">
import StudentOnlyView from '@/components/common/StudentOnlyView.vue'
import FileListView from './FileListView.vue'
</script>

<template>
  <StudentOnlyView feature="文件">
    <FileListView />
  </StudentOnlyView>
</template>
