<script setup lang="ts">
import { storeToRefs } from 'pinia'

import SideNav from '@/components/layout/SideNav.vue'
import TopBar from '@/components/layout/TopBar.vue'
import { useAuthStore } from '@/stores/auth'

const { roleLabel } = storeToRefs(useAuthStore())
</script>

<template>
  <div class="app-shell">
    <SideNav>
      <template #user>
        <div class="user-card">
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
  max-width: var(--app-content-max);
  padding: 32px;
  margin: 0 auto;
}

.user-card {
  padding: 0 12px;
}
</style>