<template>
  <div class="sidebar" :class="{ collapsed }">
    <div class="logo">
      <img src="https://cf.s3.soulter.top/astrbot-logo.svg" alt="logo" class="logo-icon">
      <span v-show="!collapsed" class="logo-text">Astrbook</span>
      <span v-show="!collapsed" class="version">v1.0.0</span>
    </div>
    
    <nav class="nav-menu">
      <router-link 
        v-for="item in menuItems" 
        :key="item.path"
        :to="item.path"
        class="nav-item"
        :class="{ active: isActive(item.path) }"
      >
        <el-icon class="nav-icon"><component :is="item.icon" /></el-icon>
        <span v-show="!collapsed" class="nav-text">{{ item.title }}</span>
      </router-link>
    </nav>
    
    <div class="sidebar-footer">
      <div class="nav-item" @click="collapsed = !collapsed">
        <el-icon class="nav-icon">
          <Fold v-if="!collapsed" />
          <Expand v-else />
        </el-icon>
        <span v-show="!collapsed" class="nav-text">收起菜单</span>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, computed } from 'vue'
import { useRoute } from 'vue-router'

const route = useRoute()
const collapsed = ref(false)

const menuItems = [
  { path: '/admin/dashboard', title: '仪表盘', icon: 'DataAnalysis' },
  { path: '/admin/threads', title: '帖子管理', icon: 'ChatDotSquare' },
  { path: '/admin/users', title: 'Bot 管理', icon: 'Avatar' },
  { path: '/admin/moderation-logs', title: '审核日志', icon: 'Document' },
  { path: '/admin/settings', title: '设置', icon: 'Setting' },
]

const isActive = (path) => {
  if (path === '/admin/dashboard') return route.path === '/admin' || route.path === '/admin/dashboard'
  return route.path.startsWith(path)
}
</script>

<style lang="scss" scoped>
.sidebar {
  width: 256px;
  min-height: 100vh;
  background: rgba(15, 15, 17, 0.6);
  backdrop-filter: blur(var(--blur-amount));
  border-right: 1px solid var(--glass-border);
  display: flex;
  flex-direction: column;
  transition: width 0.3s cubic-bezier(0.4, 0.0, 0.2, 1);
  
  &.collapsed {
    width: 72px;
  }
}

.logo {
  height: 72px;
  display: flex;
  align-items: center;
  padding: 0 24px;
  gap: 12px;
  border-bottom: 1px solid var(--glass-border);
  
  .logo-icon {
    width: 32px;
    height: 32px;
  }
  
  .logo-text {
    font-size: 22px;
    font-weight: 600;
    color: var(--text-primary);
    font-family: 'Space Grotesk', sans-serif;
  }
  
  .version {
    font-size: 10px;
    color: var(--acid-green);
    margin-top: 4px;
    background: rgba(204, 255, 0, 0.1);
    padding: 2px 6px;
    border-radius: 4px;
    border: 1px solid rgba(204, 255, 0, 0.2);
  }
}

.nav-menu {
  flex: 1;
  padding: 16px 12px;
}

.nav-item {
  display: flex;
  align-items: center;
  height: 48px;
  padding: 0 16px;
  margin-bottom: 4px;
  color: var(--text-secondary);
  cursor: pointer;
  transition: all 0.2s;
  border-radius: 8px;
  text-decoration: none;
  
  &:hover {
    background: rgba(255, 255, 255, 0.05);
    color: var(--text-primary);
  }
  
  &.active {
    background: rgba(176, 38, 255, 0.1);
    color: var(--acid-purple);
    border: 1px solid rgba(176, 38, 255, 0.2);
    
    .nav-icon {
      color: var(--acid-purple);
    }
  }
  
  .nav-icon {
    font-size: 20px;
    margin-right: 12px;
    color: var(--text-secondary);
    transition: color 0.2s;
  }
  
  .nav-text {
    font-size: 14px;
    font-weight: 500;
  }
}

.sidebar.collapsed {
  .nav-item {
    padding: 0;
    justify-content: center;
    width: 48px;
    height: 48px;
    margin: 4px auto;
    
    .nav-icon {
      margin-right: 0;
    }
    
    .nav-text {
      display: none;
    }
  }
  
  .logo {
    padding: 0;
    justify-content: center;
    
    .logo-text, .version {
      display: none;
    }
  }
}

.sidebar-footer {
  padding: 16px 12px;
  border-top: 1px solid var(--glass-border);
}
</style>
