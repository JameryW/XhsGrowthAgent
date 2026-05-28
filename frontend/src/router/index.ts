import { createRouter, createWebHistory } from 'vue-router'

const router = createRouter({
  history: createWebHistory(),
  routes: [
    {
      path: '/',
      name: 'home',
      component: () => import('@/views/Home.vue'),
      meta: { transition: 'fade-slide' },
    },
    {
      path: '/dashboard',
      name: 'dashboard',
      component: () => import('@/views/Dashboard.vue'),
      meta: { transition: 'fade-slide' },
    },
    {
      path: '/review',
      name: 'review',
      component: () => import('@/views/Review.vue'),
      meta: { transition: 'fade-slide' },
    },
    {
      path: '/analytics',
      name: 'analytics',
      component: () => import('@/views/Analytics.vue'),
      meta: { transition: 'fade-slide' },
    },
    {
      path: '/:pathMatch(.*)*',
      name: 'not-found',
      component: () => import('@/views/NotFound.vue'),
      meta: { transition: 'fade-slide' },
    },
  ],
})

export default router