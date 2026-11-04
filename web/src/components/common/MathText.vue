<script setup lang="ts">
/**
 * 把带 `$…$` 的题干渲染成公式（S4-1 审题页 / S4-2 错题列表共用）。
 *
 * 列表里不做 JS 截断，交给调用方的 CSS 折行 clamp：截断按字符切会把公式切一半，
 * KaTeX 渲染不了半条公式。
 */
import 'katex/dist/katex.min.css'

import { computed } from 'vue'

import { renderMathToHtml } from '@/utils/mathText'

const props = defineProps<{ text: string }>()

const html = computed(() => renderMathToHtml(props.text))
</script>

<template>
  <span class="math-text" v-html="html" />
</template>

<style scoped>
.math-text {
  word-break: break-word;
}
</style>