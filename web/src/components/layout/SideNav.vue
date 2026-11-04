<script setup lang="ts">
import { computed } from 'vue'
import { useRoute } from 'vue-router'

import { NAV_ITEMS } from '@/layouts/nav'

const route = useRoute()
const activeNav = computed(() => route.meta.nav ?? route.name)
</script>

<template>
  <aside class="sidebar">
    <router-link class="brand" to="/notes">
      <span class="brand-name">知序</span>
      <span class="brand-sub">学习工作台</span>
    </router-link>

    <nav aria-label="主导航">
      <ul class="nav-list">
        <li v-for="item in NAV_ITEMS" :key="item.name">
          <router-link
            class="nav-link"
            :class="{ active: activeNav === item.name }"
            :to="item.path"
            :aria-current="activeNav === item.name ? 'page' : undefined"
            data-testid="nav-link"
          >
            <span>{{ item.label }}</span>
          </router-link>
        </li>
      </ul>
    </nav>

    <div class="sidebar-foot">
      <slot name="user" />
    </div>
  </aside>
</template>

<style scoped>
.sidebar {
  position: sticky;
  top: 0;
  display: flex;
  flex-direction: column;
  width: var(--app-sidebar-width);
  height: 100vh;
  padding: 24px 16px 16px;
  background: var(--app-surface);
  border-right: 1px solid var(--app-border);
}

.brand {
  display: flex;
  flex-direction: column;
  gap: 2px;
  padding: 0 12px 24px;
}

.brand-name {
  font-size: 20px;
  font-weight: 600;
  letter-spacing: 0.12em;
}

.brand-sub {
  color: var(--app-text-tertiary);
  font-size: 11px;
  letter-spacing: 0.16em;
}

.nav-list {
  display: grid;
  gap: 4px;
  margin: 0;
  padding: 0;
  list-style: none;
}

.nav-link {
  display: flex;
  align-items: center;
  padding: 10px 12px;
  color: var(--app-text-secondary);
  font-size: 14px;
  border-left: 3px solid transparent;
  border-radius: var(--app-radius-sm);
  transition:
    background 120ms ease-out,
    color 120ms ease-out;
}

.nav-link:hover {
  color: var(--app-text);
  background: #f3f4f6;
}

.nav-link.active {
  color: var(--app-primary);
  font-weight: 500;
  background: var(--app-primary-soft);
  border-left-color: var(--app-primary);
}

.sidebar-foot {
  margin-top: auto;
  padding-top: 16px;
  border-top: 1px solid var(--app-border);
}
</style>