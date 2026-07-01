import { createRouter, createWebHistory } from 'vue-router'
import { useAuthStore } from '@/stores/auth'
import { pinia } from '@/stores/pinia'

const router = createRouter({
  history: createWebHistory(),
  routes: [
    {
      path: '/',
      name: 'showcase',
      component: () => import('@/views/Showcase.vue'),
      meta: { transition: 'fade-slide', public: true },
    },
    {
      path: '/replay/:threadId',
      name: 'replay',
      component: () => import('@/views/WorkflowReplay.vue'),
      meta: { transition: 'fade-slide', public: true },
    },
    {
      path: '/start',
      name: 'home',
      component: () => import('@/views/Home.vue'),
      meta: { transition: 'fade-slide', requiresAuth: true },
    },
    {
      path: '/login',
      name: 'login',
      component: () => import('@/views/Login.vue'),
      meta: { transition: 'fade-slide', public: true },
    },
    {
      path: '/dashboard',
      name: 'dashboard',
      component: () => import('@/views/Dashboard.vue'),
      meta: { transition: 'fade-slide', requiresAuth: true },
    },
    {
      path: '/review',
      name: 'review',
      component: () => import('@/views/Review.vue'),
      meta: { transition: 'fade-slide', requiresAuth: true },
    },
    {
      path: '/analytics',
      name: 'analytics',
      component: () => import('@/views/Analytics.vue'),
      meta: { transition: 'fade-slide', requiresAuth: true },
    },
    {
      path: '/evaluation',
      name: 'evaluation',
      component: () => import('@/views/EvaluationView.vue'),
      meta: { transition: 'fade-slide', requiresAuth: true },
    },
    {
      path: '/history',
      name: 'history',
      component: () => import('@/views/History.vue'),
      meta: { transition: 'fade-slide', requiresAuth: true },
    },
    {
      path: '/settings',
      name: 'settings',
      component: () => import('@/views/Settings.vue'),
      meta: { transition: 'fade-slide', requiresAuth: true },
    },
    {
      path: '/tui',
      name: 'tui',
      component: () => import('@/views/AgentTUI.vue'),
      meta: { transition: 'fade-slide', public: true },
    },
    {
      path: '/:pathMatch(.*)*',
      name: 'not-found',
      component: () => import('@/views/NotFound.vue'),
      meta: { transition: 'fade-slide', public: true },
    },
  ],
})

// Auth guard — wait for initialization to avoid flash with stale tokens
router.beforeEach(async (to, _from, next) => {
  const authStore = useAuthStore(pinia)

  // Wait for auth initialization on first navigation
  if (!authStore.isInitialized) {
    await authStore.initialize()
  }

  const requiresAuth = to.meta.requiresAuth

  if (requiresAuth && !authStore.isAuthenticated) {
    next({ name: 'login', query: { redirect: to.fullPath } })
  } else if (to.name === 'login' && authStore.isAuthenticated) {
    next({ name: 'dashboard' })
  } else {
    next()
  }
})

export default router
