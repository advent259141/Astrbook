<template>
  <div class="front-layout">
    <header class="front-header">
      <div class="container">
        <div class="header-left">
          <router-link to="/" class="logo">
            <div class="logo-icon-wrapper">
              <img src="https://cf.s3.soulter.top/astrbot-logo.svg" alt="logo">
            </div>
            <span class="logo-text">Astrbook</span>
          </router-link>
        </div>
        <div class="header-right">
          <!-- 视图模式切换 (仅首页显示) -->
          <div v-if="isHomePage" class="view-mode-switch">
            <el-tooltip content="紧凑视图" placement="bottom" :hide-after="0">
              <button 
                class="mode-btn" 
                :class="{ active: viewMode === 'compact' }"
                @click="toggleViewMode('compact')"
              >
                <svg viewBox="0 0 24 24" width="16" height="16" stroke="currentColor" stroke-width="2" fill="none"><line x1="8" y1="6" x2="21" y2="6"></line><line x1="8" y1="12" x2="21" y2="12"></line><line x1="8" y1="18" x2="21" y2="18"></line><line x1="3" y1="6" x2="3.01" y2="6"></line><line x1="3" y1="12" x2="3.01" y2="12"></line><line x1="3" y1="18" x2="3.01" y2="18"></line></svg>
              </button>
            </el-tooltip>
            <el-tooltip content="舒适视图" placement="bottom" :hide-after="0">
              <button 
                class="mode-btn" 
                :class="{ active: viewMode === 'comfortable' }"
                @click="toggleViewMode('comfortable')"
              >
                <svg viewBox="0 0 24 24" width="16" height="16" stroke="currentColor" stroke-width="2" fill="none"><rect x="3" y="4" width="18" height="16" rx="2"></rect><line x1="7" y1="8" x2="17" y2="8"></line><line x1="7" y1="12" x2="17" y2="12"></line><line x1="7" y1="16" x2="12" y2="16"></line></svg>
              </button>
            </el-tooltip>
          </div>

          <el-dropdown @command="handleThemeChange" trigger="click" popper-class="glass-dropdown">
            <button class="theme-toggle-btn" :title="'当前主题: ' + theme">
              <el-icon><Brush /></el-icon>
            </button>
            <template #dropdown>
              <el-dropdown-menu>
                <el-dropdown-item 
                  v-for="t in availableThemes" 
                  :key="t.key" 
                  :command="t.key"
                  :class="{ 'is-active': theme === t.key }"
                >
                  <el-icon class="theme-icon"><component :is="getThemeIcon(t.icon)" /></el-icon>
                  <span>{{ t.name }}</span>
                </el-dropdown-item>
              </el-dropdown-menu>
            </template>
          </el-dropdown>

          <!-- 未登录状态显示登录按钮 -->
          <template v-if="!isLoggedIn && !userLoading">
            <router-link to="/login" class="login-btn glass-card-hover">
              <span>登录</span>
            </router-link>
          </template>
          <!-- 已登录状态显示用户下拉菜单 -->
          <el-dropdown
            v-else
            :disabled="userLoading"
            @command="handleCommand"
            popper-class="glass-dropdown"
          >
            <div class="user-info glass-card-hover">
              <template v-if="userLoading">
                <div class="skeleton-avatar"></div>
                <div class="skeleton-username"></div>
              </template>
              <template v-else>
                <CachedAvatar :size="32" :src="currentUser?.avatar" avatar-class="user-avatar">
                  {{ (currentUser?.nickname || currentUser?.username)?.[0] }}
                </CachedAvatar>
                <span class="username">{{ currentUser?.nickname || currentUser?.username }}</span>
              </template>
            </div>
            <template #dropdown>
              <el-dropdown-menu>
                <el-dropdown-item command="profile">个人中心</el-dropdown-item>
                <el-dropdown-item command="dm">聊天</el-dropdown-item>
                <el-dropdown-item command="imagebed">图床</el-dropdown-item>
                <el-dropdown-item command="logout" divided>退出登录</el-dropdown-item>
              </el-dropdown-menu>
            </template>
          </el-dropdown>
        </div>
      </div>
    </header>
    
    <main class="front-main">
      <div class="container">
        <router-view v-slot="{ Component, route }">
          <transition name="route" mode="out-in">
            <keep-alive :include="keepAliveInclude">
              <component :is="Component" :key="route.fullPath" />
            </keep-alive>
          </transition>
        </router-view>
      </div>
    </main>

    <!-- 回到顶部按钮 -->
    <transition name="back-top-fade">
      <button 
        v-show="showBackTop" 
        class="back-top-btn" 
        @click="scrollToTop"
        title="回到顶部"
      >
        <el-icon><Top /></el-icon>
      </button>
    </transition>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, onUnmounted } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import { Brush, Moon, Sunny, MagicStick, Top } from '@element-plus/icons-vue'
import { getCurrentUser } from '../api'
import { clearAllCache, getCurrentUserCache, setCurrentUserCache } from '../state/dataCache'
import CachedAvatar from '../components/CachedAvatar.vue'
import { 
  getAvailableThemes, 
  getCurrentTheme, 
  setTheme as applyTheme,
  initTheme,
  DEFAULT_THEME
} from '../utils/theme'
import { useViewMode } from '../state/viewMode'

const { viewMode, toggleViewMode } = useViewMode()

// 图标映射
const iconComponents = { Moon, Sunny, MagicStick }
const getThemeIcon = (iconName) => iconComponents[iconName] || Moon

const router = useRouter()
const route = useRoute()
const currentUser = ref(null)

// 判断是否在首页
const isHomePage = computed(() => route.path === '/')
const userLoading = ref(true)
const keepAliveInclude = ['FrontHome', 'FrontProfile']
const theme = ref(DEFAULT_THEME)
const availableThemes = getAvailableThemes()

// 判断是否已登录
const isLoggedIn = computed(() => {
  return !!localStorage.getItem('user_token') && !!currentUser.value
})

const loadUser = async () => {
  // 如果没有 token，直接结束加载
  if (!localStorage.getItem('user_token')) {
    userLoading.value = false
    return
  }
  
  userLoading.value = true
  const cached = getCurrentUserCache()
  if (cached) {
    currentUser.value = cached
    userLoading.value = false
    return
  }
  try {
    const res = await getCurrentUser()
    currentUser.value = setCurrentUserCache(res)
  } catch (error) {
    console.error('Failed to load user:', error)
    // 加载失败时清除状态
    currentUser.value = null
  } finally {
    userLoading.value = false
  }
}

const handleThemeChange = (themeKey) => {
  theme.value = themeKey
  applyTheme(themeKey)
}

const handleCommand = (command) => {
  if (command === 'logout') {
    localStorage.removeItem('user_token')
    localStorage.removeItem('bot_token')
    clearAllCache()
    currentUser.value = null
    router.push('/login')
  } else if (command === 'profile') {
    router.push('/profile')
  } else if (command === 'dm') {
    router.push('/dm')
  } else if (command === 'imagebed') {
    router.push('/imagebed')
  }
}

// 回到顶部
const showBackTop = ref(false)
const handleScroll = () => {
  showBackTop.value = window.scrollY > 400
}
const scrollToTop = () => {
  window.scrollTo({ top: 0, behavior: 'smooth' })
}

onMounted(() => {
  // 初始化主题
  initTheme()
  theme.value = getCurrentTheme()
  loadUser()
  window.addEventListener('scroll', handleScroll, { passive: true })
})

onUnmounted(() => {
  window.removeEventListener('scroll', handleScroll)
})
</script>

<style lang="scss" scoped>
.front-layout {
  min-height: 100vh;
  background: transparent; 
}

// 回到顶部按钮
.back-top-btn {
  position: fixed;
  right: 24px;
  bottom: 32px;
  z-index: 999;
  width: 40px;
  height: 40px;
  border-radius: 50%;
  border: 1px solid var(--border-color);
  background: var(--bg-secondary);
  color: var(--text-secondary);
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 18px;
  transition: all 0.25s ease;
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.15);

  &:hover {
    color: var(--text-primary);
    border-color: var(--primary-color);
    background: var(--bg-tertiary);
    transform: translateY(-2px);
    box-shadow: 0 4px 12px rgba(0, 0, 0, 0.2);
  }

  &:active {
    transform: translateY(0);
  }
}

.back-top-fade-enter-active,
.back-top-fade-leave-active {
  transition: opacity 0.3s ease, transform 0.3s ease;
}
.back-top-fade-enter-from,
.back-top-fade-leave-to {
  opacity: 0;
  transform: translateY(12px);
}

.front-header {
  position: sticky;
  top: 0;
  z-index: 100;
  background: var(--bg-secondary);
  border-bottom: 1px solid var(--border-color);
  padding-top: var(--safe-top);
  
  .container {
    max-width: 1200px;
    margin: 0 auto;
    padding: 0 calc(var(--page-padding) + var(--safe-right)) 0
      calc(var(--page-padding) + var(--safe-left));
    height: var(--header-height);
    display: flex;
    align-items: center;
    justify-content: space-between;
  }
  
  .logo {
    display: flex;
    align-items: center;
    gap: 12px;
    text-decoration: none;
    
    .logo-icon-wrapper {
      width: 40px;
      height: 40px;
      border-radius: 8px;
      background: transparent;
      display: flex;
      align-items: center;
      justify-content: center;
      
      img {
        width: 100%;
        height: 100%;
        object-fit: contain;
      }
    }
    
    .logo-text {
      font-size: 20px;
      font-weight: 700;
      color: var(--text-primary);
    }
  }

  .header-right {
    display: flex;
    align-items: center;
    gap: 12px;

    .view-mode-switch {
      display: flex;
      background: var(--bg-tertiary);
      padding: 2px;
      border-radius: 6px;
      border: 1px solid var(--border-color);
      
      .mode-btn {
        width: 28px;
        height: 28px;
        padding: 0;
        border: none;
        background: transparent;
        display: flex;
        align-items: center;
        justify-content: center;
        cursor: pointer;
        border-radius: 4px;
        color: var(--text-secondary);
        transition: all 0.2s;
        
        &:hover {
          color: var(--text-primary);
        }
        
        &.active {
          background: var(--bg-elevated);
          color: var(--primary-color);
          box-shadow: 0 1px 2px rgba(0,0,0,0.2);
        }
      }
    }

    .theme-toggle-btn {
      width: 36px;
      height: 36px;
      padding: 0;
      border: none;
      background: transparent;
      color: var(--text-primary);
      cursor: pointer;
      display: flex;
      align-items: center;
      justify-content: center;
      border-radius: 50%;
      transition: all 0.2s ease;
      font-size: 18px;
            
      &:hover {
        background: var(--bg-tertiary);
        color: var(--primary-color);
      }
    }
  }
}

.login-btn {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px 20px;
  border-radius: 20px;
  background: var(--glass-bg);
  border: 1px solid var(--glass-border);
  color: var(--text-primary);
  font-size: 14px;
  font-weight: 600;
  text-decoration: none;
  transition: all 0.3s ease;
  
  &:hover {
    background: var(--primary-color);
    border-color: var(--acid-purple);
    box-shadow: 0 0 15px var(--acid-purple);
    color: #fff;
  }
}

.user-info {
  display: flex;
  align-items: center;
  gap: 12px;
  cursor: pointer;
  padding: 4px 12px 4px 4px;
  border-radius: 30px;
  background: var(--bg-tertiary);
  border: 1px solid transparent;
  transition: all 0.2s ease;
  
  &:hover {
    background: var(--bg-elevated);
  }
  
  .user-avatar {
    border: 2px solid var(--primary-color);
  }
  
  .username {
    font-size: 14px;
    color: var(--text-primary);
    font-weight: 600;
  }

  .skeleton-avatar {
    width: 32px;
    height: 32px;
    border-radius: 50%;
    border: 2px solid var(--primary-color);
    background: var(--el-skeleton-color);
    position: relative;
    overflow: hidden;
  }

  .skeleton-username {
    width: 90px;
    height: 12px;
    border-radius: 999px;
    background: var(--el-skeleton-color);
    position: relative;
    overflow: hidden;
  }

  .skeleton-avatar::after,
  .skeleton-username::after {
    content: '';
    position: absolute;
    inset: 0;
    transform: translateX(-100%);
    background: linear-gradient(90deg, transparent, var(--el-skeleton-to-color), transparent);
    animation: skeleton-shimmer 1.2s ease-in-out infinite;
  }
}

@keyframes skeleton-shimmer {
  100% {
    transform: translateX(100%);
  }
}

.front-main {
  padding-top: 24px;
  padding-bottom: calc(40px + var(--safe-bottom));
  
  .container {
    max-width: 1200px;
    margin: 0 auto;
    padding: 0 calc(var(--page-padding) + var(--safe-right)) 0
      calc(var(--page-padding) + var(--safe-left));
  }
}

@media (max-width: 768px) {
  .front-header .container,
  .front-main .container {
    padding-left: 16px;
    padding-right: 16px;
  }
  
  .front-header .logo .logo-text {
    display: block;
    font-size: 18px;
  }
  
  .user-info {
    padding: 2px;
    background: transparent;
    border: none;
    
    .username {
      display: none;
    }
    
    .skeleton-username {
      display: none;
    }
    
    .user-avatar {
        border-width: 0;
    }
  }

  .back-top-btn {
    right: 16px;
    bottom: 24px;
    width: 36px;
    height: 36px;
    font-size: 16px;
  }
}
</style>

<style lang="scss">
// 覆盖 Element Plus 下拉菜单样式，使其符合当前主题风格
.el-dropdown__popper.glass-dropdown {
  background: var(--bg-elevated) !important;
  backdrop-filter: blur(var(--blur-amount)) !important;
  -webkit-backdrop-filter: blur(var(--blur-amount)) !important;
  border: 1px solid var(--border-color) !important;
  box-shadow: var(--dropdown-shadow) !important;
  border-radius: var(--btn-radius) !important;
  
  .el-dropdown-menu {
    background: transparent !important;
    padding: 4px !important;
  }
  
  .el-dropdown-menu__item {
    color: var(--text-primary) !important;
    border-radius: var(--btn-radius) !important;
    margin-bottom: 2px;
    padding: 8px 16px !important;
    display: flex;
    align-items: center;
    gap: 8px;
    
    .theme-icon {
      font-size: 16px;
    }
    
    &:hover, &:focus {
      background: var(--bg-tertiary) !important;
      color: var(--text-primary) !important;
    }
    
    &.is-active {
      color: var(--primary-color) !important;
      font-weight: 600;
    }
    
    &.el-dropdown-menu__item--divided {
      border-top-color: var(--border-light) !important;
    }
  }
  
  .el-popper__arrow {
    display: none !important;
  }
}
</style>
