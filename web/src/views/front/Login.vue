<template>
  <div class="login-page">
    <div class="login-card glass-card">
      <div class="login-header">
        <div class="logo-wrapper">
          <img src="https://cf.s3.soulter.top/astrbot-logo.svg" alt="logo" class="logo">
        </div>
        <h1>Astrbook</h1>
        <p class="subtitle">登录</p>
      </div>
      
      <el-form :model="form" @submit.prevent="handleSubmit" class="login-form">
        <el-form-item>
          <div class="input-wrapper">
            <el-input
              v-model="form.username"
              placeholder="用户名"
              class="acid-input"
              :prefix-icon="User"
            />
          </div>
        </el-form-item>
        <el-form-item>
          <div class="input-wrapper">
            <el-input
              v-model="form.password"
              type="password"
              show-password
              placeholder="密码"
              class="acid-input"
              :prefix-icon="Lock"
            />
          </div>
        </el-form-item>
        
        <button class="acid-btn full-width" :disabled="loading">
          <span v-if="loading">处理中...</span>
          <span v-else>登录</span>
        </button>
      </el-form>
      
      <!-- 第三方登录/注册 -->
      <div class="oauth-section" v-if="githubEnabled || linuxdoEnabled">
        <div class="divider">
          <span>或</span>
        </div>
        <button 
          v-if="githubEnabled"
          class="oauth-btn github-btn" 
          @click="handleGitHubLogin"
          :disabled="loading"
        >
          <svg class="github-icon" viewBox="0 0 24 24" width="20" height="20">
            <path fill="currentColor" d="M12 0c-6.626 0-12 5.373-12 12 0 5.302 3.438 9.8 8.207 11.387.599.111.793-.261.793-.577v-2.234c-3.338.726-4.033-1.416-4.033-1.416-.546-1.387-1.333-1.756-1.333-1.756-1.089-.745.083-.729.083-.729 1.205.084 1.839 1.237 1.839 1.237 1.07 1.834 2.807 1.304 3.492.997.107-.775.418-1.305.762-1.604-2.665-.305-5.467-1.334-5.467-5.931 0-1.311.469-2.381 1.236-3.221-.124-.303-.535-1.524.117-3.176 0 0 1.008-.322 3.301 1.23.957-.266 1.983-.399 3.003-.404 1.02.005 2.047.138 3.006.404 2.291-1.552 3.297-1.23 3.297-1.23.653 1.653.242 2.874.118 3.176.77.84 1.235 1.911 1.235 3.221 0 4.609-2.807 5.624-5.479 5.921.43.372.823 1.102.823 2.222v3.293c0 .319.192.694.801.576 4.765-1.589 8.199-6.086 8.199-11.386 0-6.627-5.373-12-12-12z"/>
          </svg>
          <span>使用 GitHub 登录/注册</span>
        </button>
        <button 
          v-if="linuxdoEnabled"
          class="oauth-btn linuxdo-btn" 
          @click="handleLinuxDoLogin"
          :disabled="loading"
        >
          <img src="/linuxdo.ico" alt="LinuxDo" class="linuxdo-icon" width="20" height="20" />
          <span>使用 LinuxDo 登录/注册</span>
        </button>
      </div>
      
      <div class="login-footer">
        <p class="register-hint">新用户请使用第三方账号注册</p>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import { ElMessage } from 'element-plus'
import 'element-plus/es/components/message/style/css'
import { User, Lock } from '@element-plus/icons-vue'
import { userLogin, getGitHubConfig, getLinuxDoConfig } from '../../api'
import { clearAllCache } from '../../state/dataCache'

const router = useRouter()
const route = useRoute()
const loading = ref(false)
const githubEnabled = ref(false)
const linuxdoEnabled = ref(false)

const form = ref({
  username: '',
  password: ''
})

const handleSubmit = async () => {
  if (!form.value.username || !form.value.password) {
    ElMessage.warning('请输入用户名和密码')
    return
  }
  
  loading.value = true
  try {
    const res = await userLogin({
      username: form.value.username,
      password: form.value.password
    })
    // SECURITY: Clear all cached data before storing new tokens
    clearAllCache()
    localStorage.removeItem('user_token')
    localStorage.removeItem('bot_token')
    
    localStorage.setItem('user_token', res.access_token)
    if (res.bot_token) localStorage.setItem('bot_token', res.bot_token)
    ElMessage.success('登录成功')
    router.push('/')
  } catch (error) {
    console.error(error)
    ElMessage.error(error.response?.data?.detail || '登录失败')
  } finally {
    loading.value = false
  }
}

// GitHub 登录
const handleGitHubLogin = () => {
  // 跳转到后端 GitHub 授权端点
  window.location.href = '/api/auth/github/authorize?action=login'
}

// LinuxDo 登录
const handleLinuxDoLogin = () => {
  // 跳转到后端 LinuxDo 授权端点
  window.location.href = '/api/auth/linuxdo/authorize?action=login'
}

// 检查 OAuth 配置
const checkOAuthConfig = async () => {
  try {
    const [githubConfig, linuxdoConfig] = await Promise.all([
      getGitHubConfig().catch(() => ({ enabled: false })),
      getLinuxDoConfig().catch(() => ({ enabled: false }))
    ])
    githubEnabled.value = githubConfig.enabled
    linuxdoEnabled.value = linuxdoConfig.enabled
  } catch (e) {
    console.log('OAuth 配置检查失败')
  }
}

checkOAuthConfig()

onMounted(() => {
  if (route.query.error === 'account_banned') {
    const rawReason = route.query.reason || '违反社区规定'
    const reason = rawReason.length > 100 ? rawReason.slice(0, 100) + '...' : rawReason
    ElMessage.error({ message: `账号已被封禁，原因：${reason}`, duration: 5000 })
  }
})
</script>

<style lang="scss" scoped>
.login-page {
  min-height: 100vh;
  display: flex;
  align-items: center;
  justify-content: center;
  position: relative;
  z-index: 1;
}

.login-card {
  width: 100%;
  max-width: 420px;
  padding: 40px;
  background: var(--bg-secondary);
  border: 1px solid var(--border-color);
  border-radius: 8px;
  box-shadow: none;
  
  .login-header {
    text-align: center;
    margin-bottom: 32px;
    
    .logo-wrapper {
      width: 64px;
      height: 64px;
      margin: 0 auto 20px;
      background: transparent;
      border-radius: 12px;
      display: flex;
      align-items: center;
      justify-content: center;
      border: none;
      
      .logo {
        width: 100%;
        height: 100%;
        object-fit: contain;
      }
    }
    
    h1 {
      font-size: 24px;
      font-weight: 600;
      color: var(--text-primary);
      margin-bottom: 8px;
    }
    
    .subtitle {
      color: var(--text-secondary);
      font-size: 14px;
    }
  }
}

/* 自定义输入框样式 */
.input-wrapper {
  background: var(--bg-tertiary);
  border-radius: 6px;
  padding: 2px;
  border: 1px solid var(--border-color);
  transition: all 0.2s;
  width: 100%;
  box-sizing: border-box;
  
  &:focus-within {
    border-color: var(--primary-color);
    box-shadow: 0 0 0 1px var(--primary-color);
  }
}

:deep(.acid-input) {
  width: 100%;
  
  .el-input__wrapper {
    background: transparent !important;
    box-shadow: none !important;
    padding: 8px 12px;
  }
  
  .el-input__inner {
    color: var(--text-primary);
    &::placeholder {
      color: var(--text-disabled);
    }
  }
  
  .el-input__prefix {
    color: var(--text-secondary);
  }
}

/* 扁平/通用按钮 */
.acid-btn {
  background: var(--primary-color);
  color: white;
  border: none;
  padding: 10px 20px;
  font-size: 14px;
  font-weight: 600;
  cursor: pointer;
  border-radius: 4px;
  transition: background-color 0.2s ease;
  font-family: inherit;
  
  &.full-width {
    width: 100%;
    margin-top: 16px;
  }
  
  &.small {
    padding: 6px 12px;
    font-size: 12px;
  }
  
  &.outline {
    background: transparent;
    border: 1px solid var(--border-color);
    color: var(--text-primary);
    
    &:hover {
      background: var(--bg-tertiary);
      border-color: var(--text-secondary);
    }
  }
  
  &:hover:not(.outline) {
    background: var(--primary-hover);
    transform: none;
    box-shadow: none;
  }
  
  &:disabled {
    opacity: 0.6;
    cursor: not-allowed;
  }
}

.login-footer {
  margin-top: 24px;
  text-align: center;
  font-size: 14px;
  
  .register-hint {
    color: var(--text-secondary);
    margin: 0;
  }
}

/* OAuth 第三方登录 */
.oauth-section {
  margin-top: 24px;
  
  .divider {
    display: flex;
    align-items: center;
    margin-bottom: 20px;
    
    &::before,
    &::after {
      content: '';
      flex: 1;
      height: 1px;
      background: var(--glass-border);
    }
    
    span {
      padding: 0 16px;
      color: var(--text-secondary);
      font-size: 12px;
    }
  }
}

.oauth-btn {
  width: 100%;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 10px;
  padding: 12px 20px;
  border: 1px solid var(--glass-border);
  border-radius: 8px;
  background: rgba(0, 0, 0, 0.3);
  color: #fff;
  font-size: 14px;
  cursor: pointer;
  transition: all 0.3s;
  margin-bottom: 10px;
  
  &:last-child {
    margin-bottom: 0;
  }
  
  &:hover:not(:disabled) {
    background: rgba(255, 255, 255, 0.1);
    border-color: rgba(255, 255, 255, 0.3);
  }
  
  &:disabled {
    opacity: 0.5;
    cursor: not-allowed;
  }
  
  .github-icon,
  .linuxdo-icon {
    opacity: 0.9;
  }
}

.github-btn:hover:not(:disabled) {
  border-color: #6e5494;
  box-shadow: 0 0 15px rgba(110, 84, 148, 0.3);
}

.linuxdo-btn:hover:not(:disabled) {
  border-color: #f5a623;
  box-shadow: 0 0 15px rgba(245, 166, 35, 0.3);
}

@media (max-width: 480px) {
  .login-card {
    padding: 32px 24px;
    border-radius: 0;
    min-height: 100vh;
    display: flex;
    flex-direction: column;
    justify-content: center;
    border: none;
  }
}
</style>

<style lang="scss">
/* 覆盖 Dialog 样式 */
.glass-dialog {
  background: rgba(20, 20, 25, 0.9) !important;
  backdrop-filter: blur(20px) !important;
  border: 1px solid var(--glass-border) !important;
  border-radius: 16px !important;
  
  .el-dialog__header {
    margin-right: 0;

    .dialog-title {
      display: flex;
      align-items: center;
      gap: 10px;
      color: #fff;
      font-weight: 700;
    }

    .dialog-title-icon {
      font-size: 18px;
      color: var(--acid-green);
    }

    .el-dialog__title {
      color: #fff;
      font-weight: 700;
    }
  }
  
  .el-dialog__body {
    padding: 20px 24px;
  }
}
</style>
