/**
 * 路由（S0-6 最小版）：只有 /debug 验收页。
 * 路由守卫（登录拦截）与业务路由 S2-11 起补。
 */
import { createRouter, createWebHistory } from 'vue-router'

const router = createRouter({
  history: createWebHistory(),
  routes: [
    {
      path: '/',
      redirect: '/debug',
    },
    {
      path: '/debug',
      name: 'debug',
      // 懒加载：也天然切断 http → router → 视图 → http 的模块环
      component: () => import('@/views/DebugView.vue'),
    },
  ],
})

export default router
