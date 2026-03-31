import { createRouter, createWebHistory } from 'vue-router'
import { useAuthStore } from '@/stores/auth'

const router = createRouter({
  history: createWebHistory(),
  routes: [
    {
      path: '/login',
      name: 'login',
      component: () => import('@/views/LoginView.vue'),
      meta: { public: true },
    },
    {
      path: '/projects',
      name: 'projects',
      component: () => import('@/views/ProjectsView.vue'),
      meta: { provider: true },
    },
    {
      path: '/projects/:id/setup',
      component: () => import('@/components/layout/SetupLayout.vue'),
      meta: { provider: true },
      children: [
        { path: 'datasource', name: 'setup-datasource', component: () => import('@/views/setup/DatasourceView.vue'), meta: { step: 1, provider: true } },
        { path: 'documents', name: 'setup-documents', component: () => import('@/views/setup/DocumentsView.vue'), meta: { step: 2, provider: true } },
        { path: 'ai', name: 'setup-ai', component: () => import('@/views/setup/AiConfigView.vue'), meta: { step: 3, provider: true } },
        { path: 'norms', name: 'setup-norms', component: () => import('@/views/setup/NormsView.vue'), meta: { step: 4, provider: true } },
        { path: 'delegations', name: 'setup-delegations', component: () => import('@/views/setup/DelegationsView.vue'), meta: { step: 5, provider: true } },
        { path: 'overview', name: 'setup-overview', component: () => import('@/views/setup/OverviewView.vue'), meta: { step: 6, provider: true } },
        { path: 'access', redirect: 'documents' },
      ],
    },
    {
      path: '/consumer/simulate',
      name: 'consumer-simulate',
      component: () => import('@/views/consumer/SimulateView.vue'),
    },
    {
      path: '/consumer/projects',
      name: 'consumer-projects',
      component: () => import('@/views/consumer/ConsumerProjectsView.vue'),
      meta: { consumer: true },
    },
    {
      path: '/consumer/projects/:id/chat',
      name: 'consumer-chat',
      component: () => import('@/views/consumer/ProjectChatView.vue'),
      meta: { consumer: true },
    },
    { path: '/', redirect: '/login' },
  ],
})

router.beforeEach(async (to) => {
  if (to.meta.public) return true
  const auth = useAuthStore()
  if (!auth.isAuthenticated) return '/login'

  // Ensure we have user info
  if (!auth.user) {
    const ok = await auth.checkSession()
    if (!ok) return '/login'
  }

  // Consumer trying to access provider pages → redirect
  if (to.meta.provider && auth.isConsumer) {
    return '/consumer/projects'
  }

  // Provider trying to access consumer pages → redirect to simulate
  if (to.meta.consumer && !auth.isConsumer) {
    return '/consumer/simulate'
  }

  return true
})

export default router
