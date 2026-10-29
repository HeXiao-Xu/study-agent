<script setup lang="ts">
import { storeToRefs } from 'pinia'

import SideNav from '@/components/layout/SideNav.vue'
import TopBar from '@/components/layout/TopBar.vue'
import { useAuthStore } from '@/stores/auth'

const auth = useAuthStore()
const { roleLabel, user } = storeToRefs(auth)
</script>

<template>
  <div class="app-shell">
    <SideNav>
      <template #user>
        <div class="user-card">
          <span class="user-name">{{ user?.nickname }}</span>
          <el-tag size="small" effect="plain">{{ roleLabel }}</el-tag>
        </div>
      </template>
    </SideNav>

    <div class="app-main">
      <TopBar />
      <main class="app-content">
        <router-view v-slot="{ Component }">
          <transition name="page" mode="out-in">
            <component :is="Component" />
          </transition>
        </router-view>
      </main>
    </div>
  </div>
</template>

<style scoped>
.app-shell {
  display: flex;
  min-height: 100vh;
  background: var(--app-bg);
}

.app-main {
  flex: 1;
  min-width: 0;
}

.app-content {
  width: 100%;
  padding: 24px;
  margin: 0;
}

.user-card {
  display: flex;
  gap: 8px;
  align-items: center;
  justify-content: space-between;
  padding: 0 12px;
}

.user-name {
  overflow: hidden;
  color: var(--app-text);
  font-size: 13px;
  text-overflow: ellipsis;
  white-space: nowrap;
}
</style>