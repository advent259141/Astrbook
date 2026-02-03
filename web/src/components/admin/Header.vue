<template>
  <header class="header">
    <div class="header-left">
      <el-breadcrumb separator="/">
        <el-breadcrumb-item :to="{ path: '/admin' }">后台</el-breadcrumb-item>
        <el-breadcrumb-item v-if="currentRoute.meta.title">
          {{ currentRoute.meta.title }}
        </el-breadcrumb-item>
      </el-breadcrumb>
    </div>
    
    <div class="header-right">
      <el-dropdown @command="handleCommand">
        <el-avatar :size="36" class="avatar">
          <el-icon><User /></el-icon>
        </el-avatar>
        <template #dropdown>
          <el-dropdown-menu>
            <el-dropdown-item command="logout">退出登录</el-dropdown-item>
          </el-dropdown-menu>
        </template>
      </el-dropdown>
    </div>
  </header>
</template>

<script setup>
import { computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { clearAllCache } from '../../state/dataCache'

const route = useRoute()
const router = useRouter()
const currentRoute = computed(() => route)

const handleCommand = (command) => {
  if (command === 'logout') {
    localStorage.removeItem('admin_token')
    clearAllCache()
    router.push('/admin/login')
  }
}
</script>

<style lang="scss" scoped>
.header {
  height: 72px;
  background: rgba(15, 15, 17, 0.6);
  backdrop-filter: blur(var(--blur-amount));
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0 32px;
  border-bottom: 1px solid var(--glass-border);
}

.header-left {
  display: flex;
  align-items: center;
}

.header-right {
  display: flex;
  align-items: center;
  gap: 16px;
  
  .avatar {
    cursor: pointer;
    background: var(--acid-purple);
    font-size: 14px;
    font-weight: 600;
    border: 2px solid rgba(255, 255, 255, 0.1);
    transition: all 0.2s;
    
    &:hover {
      transform: scale(1.05);
      border-color: var(--acid-purple);
      box-shadow: 0 0 10px rgba(176, 38, 255, 0.3);
    }
  }
}

// 面包屑样式优化
:deep(.el-breadcrumb) {
  font-size: 14px;
  
  .el-breadcrumb__inner {
    color: var(--text-secondary);
    font-weight: 400;
    
    &.is-link:hover {
      color: var(--acid-purple);
    }
  }
  
  .el-breadcrumb__item:last-child .el-breadcrumb__inner {
    color: var(--text-primary);
    font-weight: 500;
  }
  
  .el-breadcrumb__separator {
    color: var(--text-disabled);
  }
}
</style>
