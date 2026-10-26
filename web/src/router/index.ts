/**
 * 路由与守卫（S2-11）：登录页公开，其余业务路由需登录；403/404 公开。
 */
import { createRouter, createWebHistory } from 'vue-router'

import MainLayout from '@/layouts/MainLayout.vue'
import { resolveAccess } from '@/router/guard'
import { useAuthStore } from '@/stores/auth'

const router = createRouter({
  history: createWebHistory(),
  routes: [
    {
      path: '/login',
      name: 'login',
      component: () => import('@/views/LoginView.vue'),
      meta: { public: true, title: '登录' },
    },
    {
      path: '/',
      component: MainLayout,
      redirect: '/notes',
      children: [
        {
          path: 'notes',
          name: 'notes',
          component: () => import('@/views/notes/NoteListView.vue'),
          meta: { title: '笔记', nav: 'notes', roles: ['student'] },
        },
        {
          path: 'notes/new',
          name: 'note-new',
          component: () => import('@/views/notes/NoteEditView.vue'),
          meta: { title: '新建笔记', nav: 'notes', roles: ['student'] },
        },
        {
          path: 'notes/:id(\\d+)/edit',
          name: 'note-edit',
          component: () => import('@/views/notes/NoteEditView.vue'),
          meta: { title: '编辑笔记', nav: 'notes', roles: ['student'] },
        },
        {
          path: 'files',
          name: 'files',
          component: () => import('@/views/ComingSoonView.vue'),
          meta: {
            title: '文件',
            task: 'S2-13',
            description: '上传 PDF / Word / 图片，解析成可检索的笔记与切片。',
          },
        },
        {
          path: 'knowledge',
          name: 'knowledge',
          component: () => import('@/views/ComingSoonView.vue'),
          meta: {
            title: '知识库',
            task: 'S2-14',
            description: '浏览知识点树，处理待确认的笔记对齐。',
          },
        },
        {
          path: 'qa',
          name: 'qa',
          component: () => import('@/views/ComingSoonView.vue'),
          meta: {
            title: '智能问答',
            task: 'S3-1',
            description: '基于个人知识库回答问题，并给出可点击的原文引用。',
          },
        },
        {
          path: 'mistakes',
          name: 'mistakes',
          component: () => import('@/views/ComingSoonView.vue'),
          meta: {
            title: '错题本',
            task: 'S4-3',
            description: '按知识点归集错题，定位薄弱环节。',
          },
        },
        {
          path: 'plan',
          name: 'plan',
          component: () => import('@/views/ComingSoonView.vue'),
          meta: {
            title: '复习计划',
            task: 'S4-4',
            description: '按掌握度生成每日复习任务。',
          },
        },
        {
          path: 'debug',
          name: 'debug',
          component: () => import('@/views/DebugView.vue'),
          meta: { title: '诊断' },
        },
      ],
    },
    {
      path: '/403',
      name: 'forbidden',
      component: () => import('@/views/ForbiddenView.vue'),
      meta: { public: true, title: '无权限' },
    },
    {
      path: '/:pathMatch(.*)*',
      name: 'not-found',
      component: () => import('@/views/NotFoundView.vue'),
      meta: { public: true, title: '页面不存在' },
    },
  ],
})

router.beforeEach(async (to) => {
  const auth = useAuthStore()

  if (to.meta.public) {
    if (to.name === 'login' && auth.token) return { path: '/notes' }
    return true
  }

  if (!auth.token) {
    return { path: '/login', query: { redirect: to.fullPath } }
  }

  if (!auth.user) {
    auth.loading = true
    try {
      await auth.fetchMe()
    } catch {
      auth.clearSession()
      return { path: '/login', query: { redirect: to.fullPath } }
    } finally {
      auth.loading = false
    }
  }

  const decision = resolveAccess({
    isPublic: false,
    hasToken: true,
    user: auth.user,
    roles: to.meta.roles,
    redirectPath: to.fullPath,
  })

  if (decision.type === 'forbidden') return { path: '/403' }
  if (decision.type === 'login') {
    return { path: '/login', query: { redirect: decision.redirect } }
  }
  return true
})

router.afterEach((to) => {
  document.title = to.meta.title ? `知序 · ${to.meta.title}` : '知序'
})

export default router