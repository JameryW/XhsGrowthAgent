import { createRouter, createWebHistory } from 'vue-router'
import { useAuthStore } from '@/stores'

const router = createRouter({
  history: createWebHistory(),
  routes: [
    {
      path: '/',
      name: 'home',
      component: () => import('@/views/Home.vue'),
      meta: { transition: 'fade-slide', public: true },
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
      path: '/:pathMatch(.*)*',
      name: 'not-found',
      component: () => import('@/views/NotFound.vue'),
      meta: { transition: 'fade-slide', public: true },
    },
  ],
})

// Auth guard
router.beforeEach(async (to, _from, next) => {
  const authStore = useAuthStore()

  // Wait for auth initialization if needed
  if (!authStore.isInitialized) {
    await authStore.initialize()
  }

  const requiresAuth = to.meta.requiresAuth

  if (requiresAuth && !authStore.isAuthenticated) {
    // Redirect to login with return path
    next({ name: 'login', query: { redirect: to.fullPath } })
  } else if (to.name === 'login' && authStore.isAuthenticated) {
    // Already logged in - redirect to dashboard
    next({ name: 'dashboard' })
  } else {
    next()
  }
})

export default router