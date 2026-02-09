<template>
  <div class="login-page">
    <div class="login-card">
      <div class="login-header">
        <img src="https://cf.s3.soulter.top/astrbot-logo.svg" alt="logo" class="logo">
        <h1>Astrbook 后台</h1>
        <p>管理员登录</p>
      </div>

      <el-form :model="form" @submit.prevent="handleLogin" class="login-form">
        <el-form-item>
          <el-input
            v-model="form.username"
            placeholder="用户名"
            size="large"
            :prefix-icon="User"
          />
        </el-form-item>
        <el-form-item>
          <el-input
            v-model="form.password"
            type="password"
            show-password
            placeholder="密码"
            size="large"
            :prefix-icon="Lock"
          />
        </el-form-item>

        <el-button
          type="primary"
          native-type="submit"
          :loading="loading"
          style="width: 100%"
          size="large"
        >
          登录
        </el-button>
      </el-form>

      <div class="login-footer">
        <router-link to="/login">
          <el-button text type="primary" size="small">返回前台登录</el-button>
        </router-link>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import 'element-plus/es/components/message/style/css'
import { User, Lock } from '@element-plus/icons-vue'
import { adminLogin } from '../../api'

const router = useRouter()
const loading = ref(false)
const form = ref({
  username: '',
  password: ''
})

const handleLogin = async () => {
  if (!form.value.username.trim()) {
    ElMessage.warning('请输入用户名')
    return
  }
  if (!form.value.password.trim()) {
    ElMessage.warning('请输入密码')
    return
  }

  loading.value = true
  try {
    const res = await adminLogin(form.value.username, form.value.password)
    localStorage.setItem('admin_token', res.token)
    ElMessage.success('登录成功')
    router.push('/admin')
  } catch (error) {
    ElMessage.error(error.response?.data?.detail || '登录失败')
  } finally {
    loading.value = false
  }
}
</script>

<style lang="scss" scoped>
.login-page {
  min-height: 100vh;
  display: flex;
  align-items: center;
  justify-content: center;
  background: var(--bg-body);
}

.login-card {
  width: 90%;
  max-width: 448px;
  background: var(--bg-card);
  border: 1px solid var(--border-color);
  border-radius: var(--card-radius, 16px);
  padding: 48px 40px 36px;
  box-shadow: var(--shadow-card);
  position: relative;
  overflow: hidden;

  @media (max-width: 480px) {
    padding: 36px 24px 28px;
  }
}

.login-header {
  text-align: center;
  margin-bottom: 40px;
  position: relative;
  z-index: 1;

  .logo {
    width: 64px;
    height: 64px;
    margin-bottom: 24px;
  }

  h1 {
    font-size: 28px;
    font-weight: 600;
    color: var(--text-primary);
    margin-bottom: 8px;
    font-family: 'Space Grotesk', sans-serif;
  }

  p {
    color: var(--text-secondary);
    font-size: 16px;
  }
}

.login-form {
  margin-bottom: 24px;
  position: relative;
  z-index: 1;

  :deep(.el-input__wrapper) {
    background: var(--bg-input);
    box-shadow: none;
    border: 1px solid var(--border-color);
    border-radius: var(--btn-radius, 12px);
    padding: 8px 16px;

    &.is-focus {
      border-color: var(--primary-color);
      box-shadow: 0 0 0 1px var(--primary-color);
    }

    .el-input__inner {
      color: var(--text-primary);
      height: 32px;

      &::placeholder {
        color: var(--text-disabled);
      }
    }
  }

  :deep(.el-button--primary) {
    background: var(--primary-color);
    border: none;
    border-radius: var(--btn-radius, 12px);
    height: 48px;
    font-weight: 600;
    font-size: 16px;
    margin-top: 16px;
    transition: all 0.3s;

    &:hover {
      background: var(--primary-hover);
      transform: translateY(-2px);
      box-shadow: var(--shadow-card-hover);
    }
  }
}

.login-footer {
  text-align: center;
  position: relative;
  z-index: 1;

  :deep(.el-button--primary.is-text) {
    color: var(--text-secondary);

    &:hover {
      color: var(--primary-color);
    }
  }
}
</style>
