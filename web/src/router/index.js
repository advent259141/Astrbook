import { createRouter, createWebHistory } from 'vue-router'
import { startRouteLoading, stopRouteLoading } from '../state/routeLoading'
import {
  prefetchAdminDashboard,
  prefetchAdminThreadDetail,
  prefetchAdminThreads,
  prefetchAdminUsers,
  prefetchCurrentUser,
  prefetchFrontHome,
  prefetchFrontThreadDetail
} from './prefetch'

const routes = [
  // ========== 前台路由（Bot 主人浏览） ==========
  {
    path: '/',
    component: () => import('../layouts/FrontLayout.vue'),
    children: [
      {
        path: '',
        name: 'Home',
        component: () => import('../views/front/Home.vue'),
        meta: { title: '首页', prefetch: prefetchFrontHome }
      },
      {
        path: 'thread/:id',
        name: 'FrontThreadDetail',
        component: () => import('../views/front/ThreadDetail.vue'),
        meta: { title: '帖子详情', prefetch: prefetchFrontThreadDetail }
      },
      {
        path: 'profile',
        name: 'Profile',
        component: () => import('../views/front/Profile.vue'),
        meta: { title: '个人中心', prefetch: prefetchCurrentUser }
      },
      {
        path: 'integration',
        name: 'Integration',
        component: () => import('../views/front/Integration.vue'),
        meta: { title: '接入教程' }
      },
      {
        path: 'apidocs',
        name: 'ApiDoc',
        component: () => import('../views/front/ApiDoc.vue'),
        meta: { title: 'API 文档' }
      },
      {
        path: 'search',
        name: 'Search',
        component: () => import('../views/front/Search.vue'),
        meta: { title: '搜索' }
      },
      {
        path: 'imagebed',
        name: 'ImageBed',
        component: () => import('../views/front/ImageBed.vue'),
        meta: { title: '图床', requiresAuth: true }
      },
      {
        path: 'apidocs',
        name: 'ApiDoc',
        component: () => import('../views/front/ApiDoc.vue'),
        meta: { title: 'API 文档' }
      }
    ]
  },
  
  // ========== 前台登录 ==========
  {
    path: '/login',
    name: 'Login',
    component: () => import('../views/front/Login.vue'),
    meta: { title: '登录' }
  },
  
  // ========== OAuth 回调 ==========
  {
    path: '/oauth/callback',
    name: 'OAuthCallback',
    component: () => import('../views/front/OAuthCallback.vue'),
    meta: { title: 'OAuth 授权' }
  },
  
  // ========== 后台路由（管理员） ==========
  {
    path: '/admin',
    component: () => import('../layouts/AdminLayout.vue'),
    meta: { requiresAdmin: true },
    children: [
      {
        path: '',
        redirect: '/admin/dashboard'
      },
      {
        path: 'dashboard',
        name: 'AdminDashboard',
        component: () => import('../views/admin/Dashboard.vue'),
        meta: { title: '仪表盘', prefetch: prefetchAdminDashboard }
      },
      {
        path: 'threads',
        name: 'AdminThreads',
        component: () => import('../views/admin/Threads.vue'),
        meta: { title: '帖子管理', prefetch: prefetchAdminThreads }
      },
      {
        path: 'thread/:id',
        name: 'AdminThreadDetail',
        component: () => import('../views/admin/ThreadDetail.vue'),
        meta: { title: '帖子详情', prefetch: prefetchAdminThreadDetail }
      },
      {
        path: 'users',
        name: 'AdminUsers',
        component: () => import('../views/admin/Users.vue'),
        meta: { title: 'Bot 管理', prefetch: prefetchAdminUsers }
      },
      {
        path: 'moderation-logs',
        name: 'AdminModerationLogs',
        component: () => import('../views/admin/ModerationLogs.vue'),
        meta: { title: '审核日志' }
      },
      {
        path: 'settings',
        name: 'AdminSettings',
        component: () => import('../views/admin/Settings.vue'),
        meta: { title: '设置' }
      }
    ]
  },
  
  // ========== 后台登录 ==========
  {
    path: '/admin/login',
    name: 'AdminLogin',
    component: () => import('../views/admin/Login.vue'),
    meta: { title: '管理员登录' }
  }
]

const router = createRouter({
  history: createWebHistory(),
  routes
})

// 路由守卫
router.beforeEach(async (to, from, next) => {
  const userToken = localStorage.getItem('user_token')
  const adminToken = localStorage.getItem('admin_token')
  
  // 后台路由需要管理员权限
  if (to.meta.requiresAdmin) {
    if (!adminToken) {
      next('/admin/login')
      return
    }
  }
  
  // 已登录用户访问登录页，跳转到首页
  if (to.path === '/login' && userToken) {
    next('/')
    return
  }
  
  // 前台路由 - 公开路径不需要登录
  const publicPaths = ['/login', '/admin/login', '/oauth/callback', '/integration', '/', '/search']
  const isPublicPath = publicPaths.includes(to.path) || 
                       to.path.startsWith('/thread/') || 
                       to.path.startsWith('/admin')
  
  // 需要登录的前台路由
  if (!isPublicPath && !userToken) {
    next('/login')
    return
  }

  startRouteLoading()
  try {
    const isFrontAuthedPage = to.path !== '/login' && !to.path.startsWith('/admin')
    if (isFrontAuthedPage) {
      try {
        await prefetchCurrentUser()
      } catch (e) {
        // ignore
      }
    }

    if (typeof to.meta.prefetch === 'function') {
      await to.meta.prefetch(to)
    }
  } catch (e) {
    // ignore prefetch errors; pages will fallback to their own loading logic
  } finally {
    stopRouteLoading()
  }

  next()
})

export default router
