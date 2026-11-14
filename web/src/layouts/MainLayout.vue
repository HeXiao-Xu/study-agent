<script setup lang="ts">
import { computed } from 'vue'
import { storeToRefs } from 'pinia'
import { useRoute } from 'vue-router'

import StudentOnlyView from '@/components/common/StudentOnlyView.vue'
import SideNav from '@/components/layout/SideNav.vue'
import TopBar from '@/components/layout/TopBar.vue'
import { useAuthStore } from '@/stores/auth'
import type { UserRole } from '@/types/auth'
import { NAV_ITEMS } from './nav'

const auth = useAuthStore()
const { roleLabel, user } = storeToRefs(auth)
const route = useRoute()

const featureLabel = computed(
  () =>
    NAV_ITEMS.find((item) => item.name === route.meta.nav)?.label ??
    String(route.meta.title ?? '该功能'),
)

/** 角色不符时由布局兜底，避免把教师踢到独立 403 页、丢失左侧导航。 */
const roleBlocked = computed(() => {
  const roles = route.meta.roles as UserRole[] | undefined
  if (!roles?.length) return false
  const role = user.value?.role
  return !role || !roles.includes(role)
})
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
        <StudentOnlyView v-if="roleBlocked" :feature="featureLabel" />
        <router-view v-else v-slot="{ Component }">
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