<script setup lang="ts">
import { computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'

import { useAuthStore } from '@/stores/auth'

const route = useRoute()
const router = useRouter()
const auth = useAuthStore()

const title = computed(() => String(route.meta.title ?? ''))
const initials = computed(() => auth.user?.nickname.slice(0, 1) ?? '知')

function onCommand(command: string | number | object): void {
  if (command !== 'logout') return
  auth.clearSession()
  ElMessage.success('已退出登录')
  void router.replace('/login')
}
</script>

<template>
  <header class="topbar">
    <nav class="crumbs" aria-label="面包屑">
      <router-link to="/notes">首页</router-link>
      <span class="separator" aria-hidden="true">/</span>
      <span class="current">{{ title }}</span>
    </nav>

    <el-dropdown trigger="click" @command="onCommand">
      <button class="user-trigger" type="button">
        <span class="avatar" aria-hidden="true">{{ initials }}</span>
        <span class="user-text">
          <span class="user-name">{{ auth.user?.nickname }}</span>
          <span class="user-role">{{ auth.roleLabel }}</span>
        </span>
        <span class="caret" aria-hidden="true">⌄</span>
      </button>
      <template #dropdown>
        <el-dropdown-menu>
          <el-dropdown-item disabled>{{ auth.user?.username }}</el-dropdown-item>
          <el-dropdown-item command="logout" divided>退出登录</el-dropdown-item>
        </el-dropdown-menu>
      </template>
    </el-dropdown>
  </header>
</template>

<style scoped>
.topbar {
  position: sticky;
  top: 0;
  z-index: 10;
  display: flex;
  align-items: center;
  justify-content: space-between;
  height: var(--app-topbar-height);
  padding: 0 32px;
  background: rgba(247, 248, 250, 0.88);
  border-bottom: 1px solid var(--app-border);
  backdrop-filter: blur(8px);
}

.crumbs {
  display: flex;
  gap: 8px;
  align-items: center;
  color: var(--app-text-secondary);
  font-size: 13px;
}

.crumbs a:hover {
  color: var(--app-primary);
}

.separator {
  color: var(--app-text-tertiary);
}

.current {
  color: var(--app-text);
}

.user-trigger {
  display: flex;
  gap: 10px;
  align-items: center;
  padding: 4px 8px;
  background: none;
  border: none;
  border-radius: var(--app-radius-sm);
  cursor: pointer;
}

.user-trigger:hover {
  background: #eef0f3;
}

.avatar {
  display: grid;
  width: 30px;
  height: 30px;
  place-items: center;
  color: var(--app-primary);
  font-size: 13px;
  font-weight: 600;
  background: var(--app-primary-soft);
  border-radius: 50%;
}

.user-text {
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  line-height: 1.3;
}

.user-name {
  color: var(--app-text);
  font-size: 13px;
}

.user-role {
  color: var(--app-text-tertiary);
  font-size: 11px;
}

.caret {
  color: var(--app-text-tertiary);
  font-size: 12px;
}
</style>