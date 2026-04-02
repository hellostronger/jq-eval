import { createRouter, createWebHistory } from 'vue-router'

const router = createRouter({
  history: createWebHistory(),
  routes: [
    {
      path: '/',
      redirect: '/dashboard',
    },
    {
      path: '/dashboard',
      name: 'Dashboard',
      component: () => import('@/views/Dashboard.vue'),
    },
    {
      path: '/models',
      name: 'Models',
      component: () => import('@/views/Models.vue'),
    },
    {
      path: '/rag-systems',
      name: 'RAGSystems',
      component: () => import('@/views/RAGSystems.vue'),
    },
    {
      path: '/datasets',
      name: 'Datasets',
      component: () => import('@/views/Datasets.vue'),
    },
    {
      path: '/datasets/:id',
      name: 'DatasetDetail',
      component: () => import('@/views/DatasetDetail.vue'),
    },
    {
      path: '/evaluations',
      name: 'Evaluations',
      component: () => import('@/views/Evaluations.vue'),
    },
    {
      path: '/evaluations/:id',
      name: 'EvaluationDetail',
      component: () => import('@/views/EvaluationDetail.vue'),
    },
    {
      path: '/metrics',
      name: 'Metrics',
      component: () => import('@/views/Metrics.vue'),
    },
    {
      path: '/data-sources',
      name: 'DataSources',
      component: () => import('@/views/DataSources.vue'),
    },
  ],
})

export default router