<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useRoute } from 'vue-router'

import { NAV_GROUPS } from '@/layouts/nav'

const STORAGE_KEY = 'study-agent-nav-open-groups'

const route = useRoute()
const activeNav = computed(() => route.meta.nav ?? route.name)
const activeGroupName = computed(
  () =>
    NAV_GROUPS.find((group) =>
      group.items.some((item) => item.name === activeNav.value),
    )?.name ?? null,
)

function readOpenGroups(): string[] | null {
  try {
    const raw = localStorage.getItem(STORAGE_KEY)
    if (!raw) return null
    const parsed: unknown = JSON.parse(raw)
    if (!Array.isArray(parsed)) return null
    return parsed.filter((item): item is string => typeof item === 'string')
  } catch {
    return null
  }
}

const stored = readOpenGroups()
const openGroups = ref<Set<string>>(
  new Set(stored ?? (activeGroupName.value ? [activeGroupName.value] : [])),
)

function isOpen(name: string): boolean {
  return openGroups.value.has(name)
}

function toggle(name: string): void {
  const next = new Set(openGroups.value)
  if (next.has(name)) {
    next.delete(name)
  } else {
    next.add(name)
  }
  openGroups.value = next
}

// 切到另一个分组时自动展开它；用户手动关闭当前组后不会被强行 reopen
watch(
  activeGroupName,
  (name) => {
    if (name && !openGroups.value.has(name)) {
      openGroups.value = new Set([...openGroups.value, name])
    }
  },
  { immediate: true },
)

watch(openGroups, (groups) => {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify([...groups]))
  } catch {
    // localStorage 不可用（隐私模式）时只影响记忆，不影响导航
  }
})
</script>

<template>
  <aside class="sidebar">
    <router-link class="brand" to="/notes">
      <span class="brand-name">知序</span>
      <span class="brand-sub">学习工作台</span>
    </router-link>

    <nav class="sidebar-nav" aria-label="主导航">
      <div v-for="group in NAV_GROUPS" :key="group.name" class="nav-group">
        <button
          type="button"
          class="nav-group-head"
          :class="{ 'has-active': activeGroupName === group.name }"
          :aria-expanded="isOpen(group.name)"
          :data-testid="`nav-group-${group.name}`"
          @click="toggle(group.name)"
        >
          <span>{{ group.title }}</span>
          <span
            class="chevron"
            :class="{ open: isOpen(group.name) }"
            aria-hidden="true"
          >
            ⌄
          </span>
        </button>
        <ul v-if="isOpen(group.name)" class="nav-list">
          <li v-for="item in group.items" :key="item.name">
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
      </div>
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
  padding: 0 12px 18px;
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

.sidebar-nav {
  flex: 1;
  min-height: 0;
  margin: 0 -4px;
  padding: 0 4px;
  overflow-y: auto;
}

.nav-group + .nav-group {
  margin-top: 4px;
}

.nav-group-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  width: 100%;
  padding: 8px 12px;
  color: var(--app-text-tertiary);
  font-size: 14px;
  font-weight: 600;
  letter-spacing: 0.02em;
  background: none;
  border: none;
  border-radius: var(--app-radius-sm);
  cursor: pointer;
  transition:
    background 120ms ease-out,
    color 120ms ease-out;
}

.nav-group-head:hover {
  color: var(--app-text);
  background: #f3f4f6;
}

.nav-group-head.has-active {
  color: var(--app-text);
  background: #dbe4ff;
}

.chevron {
  font-size: 13px;
  line-height: 1;
  transition: transform 160ms ease-out;
}

.chevron.open {
  transform: rotate(180deg);
}

.nav-list {
  display: grid;
  gap: 2px;
  margin: 2px 0 0;
  padding: 0;
  list-style: none;
}

.nav-link {
  display: flex;
  align-items: center;
  padding: 9px 12px 9px 20px;
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
  color: var(--app-text);
  font-weight: 500;
  background: var(--app-primary-soft);
  border-left-color: transparent;
}

.sidebar-foot {
  margin-top: auto;
  padding-top: 16px;
  border-top: 1px solid var(--app-border);
}
</style>