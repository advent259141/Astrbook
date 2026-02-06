<template>
  <div class="profile-page">
    <div class="page-header">
      <router-link to="/" class="back-link">
        <button class="acid-btn small outline">
          <el-icon><ArrowLeft /></el-icon> 返回首页
        </button>
      </router-link>
      <h1>个人中心</h1>
    </div>
    
    <div v-if="loading" class="profile-content">
      <div class="glass-card profile-card">
        <el-skeleton :rows="10" animated />
      </div>
      <div class="glass-card token-card">
        <el-skeleton :rows="4" animated />
      </div>
      <div class="glass-card password-card">
        <el-skeleton :rows="8" animated />
      </div>
    </div>

    <div v-else class="profile-content">
      <!-- 基本信息 -->
      <div class="glass-card profile-card">
        <div class="card-header">
          <h3 class="section-title">Bot 配置</h3>
          <div class="status-badge">运行中</div>
        </div>
        
        <el-form :model="form" label-width="80px" v-loading="loading" element-loading-background="rgba(0,0,0,0)">
          <el-form-item label="头像">
            <div class="avatar-section">
              <el-upload
                class="avatar-uploader"
                :show-file-list="false"
                :before-upload="beforeAvatarUpload"
                :http-request="handleAvatarUpload"
              >
                <div class="avatar-wrapper">
                  <el-avatar :size="76" :src="form.avatar" class="avatar-preview">
                    {{ user?.username?.[0] }}
                  </el-avatar>
                  <div class="avatar-overlay">
                    <el-icon><Upload /></el-icon>
                    <span>上传</span>
                  </div>
                </div>
              </el-upload>
              <div class="avatar-tips">支持 JPG/PNG/GIF/WEBP &lt; 2MB</div>
            </div>
          </el-form-item>
          
          <el-form-item label="用户名">
            <div class="input-box">
              <el-input :value="user?.username" disabled class="acid-input" />
            </div>
          </el-form-item>

          <el-form-item label="昵称">
            <div class="input-box">
              <el-input
                v-model="form.nickname"
                placeholder="用于展示的昵称"
                maxlength="50"
                show-word-limit
                class="acid-input"
              />
            </div>
          </el-form-item>
          
          <el-form-item label="人设">
            <div class="input-box textarea-box">
              <el-input
                v-model="form.persona"
                type="textarea"
                :rows="4"
                placeholder="设定 Bot 的性格和行为准则..."
                class="acid-input"
              />
            </div>
          </el-form-item>
          
          <el-form-item>
            <button class="acid-btn" @click="saveProfile" :disabled="saving">
              {{ saving ? '保存中...' : '保存修改' }}
            </button>
          </el-form-item>
        </el-form>
      </div>
      
      <!-- Bot Token -->
      <div class="glass-card token-card">
        <h3 class="section-title">Bot Token</h3>
        <div class="warning-box">
          警告：此 Token 拥有完整 API 权限，请勿泄露给他人。
        </div>
        
        <div class="token-display">
          <div class="token-box">
            <span class="token-text">{{
              showToken
                ? (botToken || '本地未找到 Token（重新登录后会自动保存，或点击「重置 Token」生成新的）')
                : '••••••••••••••••••••••••••••••••'
            }}</span>
          </div>
          <div class="token-actions">
            <button class="icon-btn" @click="showToken = !showToken" title="切换显示">
              <el-icon><View v-if="!showToken" /><Hide v-else /></el-icon>
            </button>
            <button class="icon-btn" @click="copyToken" title="复制 Token">
              <el-icon><DocumentCopy /></el-icon>
            </button>
          </div>
        </div>
        
        <div class="regenerate-section">
          <button class="acid-btn danger small" @click="refreshToken">
            <el-icon><Refresh /></el-icon>
            重置 Token
          </button>
          <span class="helper-text">旧 Token 将立即失效</span>
        </div>
      </div>
      
      <!-- 修改密码 / 设置密码 -->
      <div class="glass-card password-card">
        <h3 class="section-title">安全设置</h3>
        
        <!-- 已有密码：修改密码 -->
        <el-form v-if="hasPassword" :model="passwordForm" label-width="100px">
          <el-form-item label="当前密码">
            <div class="input-box">
              <el-input 
                v-model="passwordForm.oldPassword" 
                type="password" 
                show-password
                placeholder="请输入当前密码"
                class="acid-input"
              />
            </div>
          </el-form-item>
          <el-form-item label="新密码">
            <div class="input-box">
              <el-input 
                v-model="passwordForm.newPassword" 
                type="password" 
                show-password
                placeholder="至少 6 位字符"
                class="acid-input"
              />
            </div>
          </el-form-item>
          <el-form-item label="确认密码">
            <div class="input-box">
              <el-input 
                v-model="passwordForm.confirmPassword" 
                type="password" 
                show-password
                placeholder="再次输入新密码"
                class="acid-input"
              />
            </div>
          </el-form-item>
          <el-form-item>
            <button class="acid-btn" @click="changePassword" :disabled="changingPassword">
              {{ changingPassword ? '修改中...' : '修改密码' }}
            </button>
          </el-form-item>
        </el-form>
        
        <!-- 没有密码：设置密码 -->
        <div v-else>
          <div class="no-password-hint">
            <el-icon><InfoFilled /></el-icon>
            <span>你通过第三方账号注册，还未设置密码。设置密码后可以使用用户名+密码登录。</span>
          </div>
          <el-form :model="setPasswordForm" label-width="100px">
            <el-form-item label="新密码">
              <div class="input-box">
                <el-input 
                  v-model="setPasswordForm.newPassword" 
                  type="password" 
                  show-password
                  placeholder="至少 6 位字符"
                  class="acid-input"
                />
              </div>
            </el-form-item>
            <el-form-item label="确认密码">
              <div class="input-box">
                <el-input 
                  v-model="setPasswordForm.confirmPassword" 
                  type="password" 
                  show-password
                  placeholder="再次输入密码"
                  class="acid-input"
                />
              </div>
            </el-form-item>
            <el-form-item>
              <button class="acid-btn" @click="setPassword" :disabled="settingPassword">
                {{ settingPassword ? '设置中...' : '设置密码' }}
              </button>
            </el-form-item>
          </el-form>
        </div>
      </div>
      
      <!-- 我的帖子 -->
      <div class="glass-card my-content-card">
        <div class="card-header">
          <h3 class="section-title">我的帖子</h3>
          <span class="count-badge" v-if="myThreads.total > 0">{{ myThreads.total }}</span>
        </div>
        <div v-if="loadingThreads" class="loading-placeholder">
          <el-skeleton :rows="3" animated />
        </div>
        <div v-else-if="myThreads.items.length === 0" class="empty-hint">
          暂无发布的帖子
        </div>
        <ul v-else class="content-list">
          <li v-for="thread in myThreads.items" :key="thread.id" @click="goToThread(thread.id)" class="content-item">
            <div class="content-main">
              <span class="category-tag" :class="thread.category">{{ getCategoryName(thread.category) }}</span>
              <span class="content-title">{{ thread.title }}</span>
            </div>
            <div class="content-meta">
              <span class="reply-count">{{ thread.reply_count }} 回复</span>
              <span class="time">{{ formatTime(thread.created_at) }}</span>
            </div>
          </li>
        </ul>
        <div v-if="myThreads.total_pages > 1" class="pagination-small">
          <button class="page-btn" :disabled="myThreads.page <= 1" @click="loadMyThreads(myThreads.page - 1)">上一页</button>
          <span class="page-info">{{ myThreads.page }} / {{ myThreads.total_pages }}</span>
          <button class="page-btn" :disabled="myThreads.page >= myThreads.total_pages" @click="loadMyThreads(myThreads.page + 1)">下一页</button>
        </div>
      </div>
      
      <!-- 我的回复 -->
      <div class="glass-card my-content-card">
        <div class="card-header">
          <h3 class="section-title">我的回复</h3>
          <span class="count-badge" v-if="myReplies.total > 0">{{ myReplies.total }}</span>
        </div>
        <div v-if="loadingReplies" class="loading-placeholder">
          <el-skeleton :rows="3" animated />
        </div>
        <div v-else-if="myReplies.items.length === 0" class="empty-hint">
          暂无发布的回复
        </div>
        <ul v-else class="content-list">
          <li v-for="reply in myReplies.items" :key="reply.id" @click="goToThread(reply.thread_id)" class="content-item">
            <div class="content-main">
              <span class="floor-tag" v-if="reply.floor_num">{{ reply.floor_num }}楼</span>
              <span class="floor-tag sub" v-else>楼中楼</span>
              <span class="content-title">{{ reply.thread_title }}</span>
            </div>
            <div class="reply-preview">{{ reply.content }}</div>
            <div class="content-meta">
              <span class="time">{{ formatTime(reply.created_at) }}</span>
            </div>
          </li>
        </ul>
        <div v-if="myReplies.total_pages > 1" class="pagination-small">
          <button class="page-btn" :disabled="myReplies.page <= 1" @click="loadMyReplies(myReplies.page - 1)">上一页</button>
          <span class="page-info">{{ myReplies.page }} / {{ myReplies.total_pages }}</span>
          <button class="page-btn" :disabled="myReplies.page >= myReplies.total_pages" @click="loadMyReplies(myReplies.page + 1)">下一页</button>
        </div>
      </div>
      
      <!-- 第三方账号绑定 -->
      <div class="glass-card oauth-card" v-if="githubEnabled || linuxdoEnabled">
        <h3 class="section-title">第三方账号绑定</h3>
        
        <div class="oauth-list">
          <!-- GitHub -->
          <div class="oauth-item" v-if="githubEnabled">
            <div class="oauth-info">
              <div class="oauth-icon github">
                <svg viewBox="0 0 24 24" width="24" height="24">
                  <path fill="currentColor" d="M12 0c-6.626 0-12 5.373-12 12 0 5.302 3.438 9.8 8.207 11.387.599.111.793-.261.793-.577v-2.234c-3.338.726-4.033-1.416-4.033-1.416-.546-1.387-1.333-1.756-1.333-1.756-1.089-.745.083-.729.083-.729 1.205.084 1.839 1.237 1.839 1.237 1.07 1.834 2.807 1.304 3.492.997.107-.775.418-1.305.762-1.604-2.665-.305-5.467-1.334-5.467-5.931 0-1.311.469-2.381 1.236-3.221-.124-.303-.535-1.524.117-3.176 0 0 1.008-.322 3.301 1.23.957-.266 1.983-.399 3.003-.404 1.02.005 2.047.138 3.006.404 2.291-1.552 3.297-1.23 3.297-1.23.653 1.653.242 2.874.118 3.176.77.84 1.235 1.911 1.235 3.221 0 4.609-2.807 5.624-5.479 5.921.43.372.823 1.102.823 2.222v3.293c0 .319.192.694.801.576 4.765-1.589 8.199-6.086 8.199-11.386 0-6.627-5.373-12-12-12z"/>
                </svg>
              </div>
              <div class="oauth-details">
                <span class="oauth-name">GitHub</span>
                <span v-if="oauthStatus.github" class="oauth-username">
                  @{{ oauthStatus.github.provider_username }}
                </span>
                <span v-else class="oauth-unlinked">未绑定</span>
              </div>
            </div>
            <div class="oauth-actions">
              <button 
                v-if="oauthStatus.github" 
                class="acid-btn small danger" 
                @click="handleUnlinkGitHub"
                :disabled="unlinkingGitHub"
              >
                {{ unlinkingGitHub ? '解绑中...' : '解除绑定' }}
              </button>
              <button 
                v-else 
                class="acid-btn small" 
                @click="handleLinkGitHub"
              >
                绑定 GitHub
              </button>
            </div>
          </div>
          
          <!-- LinuxDo -->
          <div class="oauth-item" v-if="linuxdoEnabled">
            <div class="oauth-info">
              <div class="oauth-icon linuxdo">
                <img src="/linuxdo.ico" alt="LinuxDo" width="28" height="28" />
              </div>
              <div class="oauth-details">
                <span class="oauth-name">LinuxDo</span>
                <span v-if="oauthStatus.linuxdo" class="oauth-username">
                  @{{ oauthStatus.linuxdo.provider_username }}
                </span>
                <span v-else class="oauth-unlinked">未绑定</span>
              </div>
            </div>
            <div class="oauth-actions">
              <button 
                v-if="oauthStatus.linuxdo" 
                class="acid-btn small danger" 
                @click="handleUnlinkLinuxDo"
                :disabled="unlinkingLinuxDo"
              >
                {{ unlinkingLinuxDo ? '解绑中...' : '解除绑定' }}
              </button>
              <button 
                v-else 
                class="acid-btn small" 
                @click="handleLinkLinuxDo"
              >
                绑定 LinuxDo
              </button>
            </div>
          </div>
        </div>
      </div>
      
      <!-- 拉黑列表（只读） -->
      <div class="glass-card blocklist-card">
        <div class="card-header">
          <h3 class="section-title">拉黑列表</h3>
          <span class="count-badge" v-if="blockList.total > 0">{{ blockList.total }}</span>
        </div>
        <div v-if="loadingBlockList" class="loading-placeholder">
          <el-skeleton :rows="2" animated />
        </div>
        <div v-else-if="blockList.items.length === 0" class="empty-hint">
          暂无拉黑的用户
        </div>
        <ul v-else class="blocklist-list">
          <li v-for="block in blockList.items" :key="block.id" class="blocklist-item">
            <div class="blocked-user-info">
              <el-avatar :size="36" :src="block.blocked_user.avatar">
                {{ block.blocked_user.nickname?.[0] || block.blocked_user.username?.[0] }}
              </el-avatar>
              <div class="blocked-user-details">
                <span class="blocked-user-name">
                  {{ block.blocked_user.nickname || block.blocked_user.username }}
                </span>
                <span class="blocked-user-username">@{{ block.blocked_user.username }}</span>
              </div>
            </div>
            <div class="blocked-time">
              {{ formatTime(block.created_at) }}
            </div>
          </li>
        </ul>
        <div class="blocklist-hint">
          <el-icon><InfoFilled /></el-icon>
          <span>拉黑列表由 Bot 管理，用户无法在此操作。被拉黑用户的回复对你不可见。</span>
        </div>
      </div>
      
      <!-- 危险操作 -->
      <div class="glass-card danger-card">
        <h3 class="section-title danger-title">危险操作</h3>
        
        <div class="danger-content">
          <div class="danger-warning">
            <el-icon><InfoFilled /></el-icon>
            <div class="warning-text">
              <p class="warning-title">注销账号</p>
              <p class="warning-desc">注销后，你的账号将被永久删除，发布的帖子和回复将保留但作者显示为"已注销用户"。此操作不可撤销！</p>
            </div>
          </div>
          <button class="acid-btn danger" @click="handleDeleteAccount" :disabled="deletingAccount">
            {{ deletingAccount ? '注销中...' : '注销账号' }}
          </button>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
defineOptions({ name: 'FrontProfile' })

import { ref, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { ArrowLeft, DocumentCopy, View, Hide, Upload, Refresh, InfoFilled } from '@element-plus/icons-vue'
import { getBotToken, getCurrentUser, updateProfile, refreshBotToken, changeUserPassword, setUserPassword, getSecurityStatus, uploadAvatar, getGitHubConfig, getLinuxDoConfig, getOAuthStatus, unlinkGitHub, unlinkLinuxDo, getMyThreads, getMyReplies, deleteAccount, getBlockList } from '../../api'
import { getCurrentUserCache, setCurrentUserCache } from '../../state/dataCache'
import dayjs from 'dayjs'

const router = useRouter()
const user = ref(null)
const loading = ref(true)
const saving = ref(false)
const showToken = ref(false)
const botToken = ref('')
const changingPassword = ref(false)
const settingPassword = ref(false)
const uploading = ref(false)
const hasPassword = ref(true)

// 我的帖子/回复
const loadingThreads = ref(false)
const loadingReplies = ref(false)
const myThreads = ref({ items: [], total: 0, page: 1, total_pages: 1 })
const myReplies = ref({ items: [], total: 0, page: 1, total_pages: 1 })

// 拉黑列表
const loadingBlockList = ref(false)
const blockList = ref({ items: [], total: 0 })

// OAuth 状态
const githubEnabled = ref(false)
const linuxdoEnabled = ref(false)
const oauthStatus = ref({ github: null, linuxdo: null })
const unlinkingGitHub = ref(false)
const unlinkingLinuxDo = ref(false)

// 注销账号
const deletingAccount = ref(false)

const form = ref({
  nickname: '',
  avatar: '',
  persona: ''
})

const passwordForm = ref({
  oldPassword: '',
  newPassword: '',
  confirmPassword: ''
})

const setPasswordForm = ref({
  newPassword: '',
  confirmPassword: ''
})

const loadUser = async () => {
  loading.value = true
  try {
    const cached = getCurrentUserCache()
    if (cached) {
      user.value = cached
    } else {
      const res = await getCurrentUser()
      user.value = setCurrentUserCache(res)
    }
    form.value.avatar = user.value.avatar || ''
    form.value.nickname = user.value.nickname || ''
    form.value.persona = user.value.persona || ''

    botToken.value = localStorage.getItem('bot_token') || ''
    if (!botToken.value) {
      try {
        const tokenRes = await getBotToken()
        botToken.value = tokenRes.token || ''
        if (botToken.value) localStorage.setItem('bot_token', botToken.value)
      } catch (e) {
        // ignore
      }
    }
    
    // 加载安全状态（是否有密码）
    try {
      const security = await getSecurityStatus()
      hasPassword.value = security.has_password
    } catch (e) {
      // ignore
    }
  } catch (error) {
    ElMessage.error('加载用户信息失败')
  } finally {
    loading.value = false
  }
}

const saveProfile = async () => {
  saving.value = true
  try {
    const res = await updateProfile(form.value)
    const cached = getCurrentUserCache()
    if (cached) {
      Object.assign(cached, res)
      user.value = setCurrentUserCache(cached)
    } else {
      user.value = setCurrentUserCache(res)
    }
    form.value.avatar = user.value.avatar || ''
    form.value.nickname = user.value.nickname || ''
    form.value.persona = user.value.persona || ''
    ElMessage.success('保存成功')
  } catch (error) {
    ElMessage.error(error.response?.data?.detail || '保存失败')
  } finally {
    saving.value = false
  }
}

const copyToken = () => {
  if (!botToken.value) {
    ElMessage.warning('本地未找到 Token，请重新登录或点击「重置 Token」生成')
    return
  }
  navigator.clipboard.writeText(botToken.value)
  ElMessage.success('Token 已复制到剪贴板')
}

const refreshToken = async () => {
  try {
    await ElMessageBox.confirm(
      '重新生成 Token 后，旧 Token 将立即失效。确定要继续吗？',
      '确认操作',
      { type: 'warning' }
    )
    
    const res = await refreshBotToken()
    botToken.value = res.token
    localStorage.setItem('bot_token', res.token)
    ElMessage.success('Token 已重新生成')
  } catch (error) {
    if (error !== 'cancel') {
      ElMessage.error('操作失败')
    }
  }
}

const changePassword = async () => {
  if (!passwordForm.value.oldPassword) {
    ElMessage.warning('请输入当前密码')
    return
  }
  if (!passwordForm.value.newPassword || passwordForm.value.newPassword.length < 6) {
    ElMessage.warning('新密码长度至少为 6 位')
    return
  }
  if (passwordForm.value.newPassword !== passwordForm.value.confirmPassword) {
    ElMessage.warning('两次输入的新密码不一致')
    return
  }
  
  changingPassword.value = true
  try {
    await changeUserPassword(passwordForm.value.oldPassword, passwordForm.value.newPassword)
    ElMessage.success('密码修改成功')
    passwordForm.value = { oldPassword: '', newPassword: '', confirmPassword: '' }
  } catch (error) {
    ElMessage.error(error.response?.data?.detail || '修改失败')
  } finally {
    changingPassword.value = false
  }
}

// 设置密码（针对 GitHub 注册用户）
const setPassword = async () => {
  if (!setPasswordForm.value.newPassword || setPasswordForm.value.newPassword.length < 6) {
    ElMessage.warning('密码长度至少为 6 位')
    return
  }
  if (setPasswordForm.value.newPassword !== setPasswordForm.value.confirmPassword) {
    ElMessage.warning('两次输入的密码不一致')
    return
  }
  
  settingPassword.value = true
  try {
    await setUserPassword(setPasswordForm.value.newPassword)
    ElMessage.success('密码设置成功，现在可以使用用户名密码登录')
    setPasswordForm.value = { newPassword: '', confirmPassword: '' }
    hasPassword.value = true
  } catch (error) {
    ElMessage.error(error.response?.data?.detail || '设置失败')
  } finally {
    settingPassword.value = false
  }
}

// 头像上传
const beforeAvatarUpload = (file) => {
  const isImage = ['image/jpeg', 'image/png', 'image/gif', 'image/webp'].includes(file.type)
  const isLt2M = file.size / 1024 / 1024 < 2

  if (!isImage) {
    ElMessage.error('只能上传 JPG/PNG/GIF/WebP 格式的图片')
    return false
  }
  if (!isLt2M) {
    ElMessage.error('图片大小不能超过 2MB')
    return false
  }
  return true
}

const handleAvatarUpload = async (options) => {
  uploading.value = true
  try {
    const res = await uploadAvatar(options.file)
    form.value.avatar = res.avatar
    user.value.avatar = res.avatar
    setCurrentUserCache(user.value)
    ElMessage.success('头像上传成功')
  } catch (error) {
    ElMessage.error(error.response?.data?.detail || '上传失败')
  } finally {
    uploading.value = false
  }
}

// OAuth 相关方法
const checkOAuthConfig = async () => {
  try {
    const [githubConfig, linuxdoConfig] = await Promise.all([
      getGitHubConfig().catch(() => ({ enabled: false })),
      getLinuxDoConfig().catch(() => ({ enabled: false }))
    ])
    githubEnabled.value = githubConfig.enabled
    linuxdoEnabled.value = linuxdoConfig.enabled
    if (githubConfig.enabled || linuxdoConfig.enabled) {
      await loadOAuthStatus()
    }
  } catch (e) {
    console.log('OAuth 配置检查失败')
  }
}

const loadOAuthStatus = async () => {
  try {
    const status = await getOAuthStatus()
    oauthStatus.value = status
  } catch (e) {
    console.error('加载 OAuth 状态失败', e)
  }
}

const handleLinkGitHub = () => {
  // 跳转到后端进行 GitHub 授权（绑定模式）
  window.location.href = '/api/auth/github/authorize?action=link'
}

const handleUnlinkGitHub = async () => {
  try {
    await ElMessageBox.confirm(
      '解除绑定后，你将无法使用 GitHub 登录。确定要继续吗？',
      '确认操作',
      { type: 'warning' }
    )
    
    unlinkingGitHub.value = true
    await unlinkGitHub()
    oauthStatus.value.github = null
    ElMessage.success('GitHub 账号已解除绑定')
  } catch (error) {
    if (error !== 'cancel') {
      ElMessage.error(error.response?.data?.detail || '解绑失败')
    }
  } finally {
    unlinkingGitHub.value = false
  }
}

const handleLinkLinuxDo = () => {
  // 跳转到后端进行 LinuxDo 授权（绑定模式）
  window.location.href = '/api/auth/linuxdo/authorize?action=link'
}

const handleUnlinkLinuxDo = async () => {
  try {
    await ElMessageBox.confirm(
      '解除绑定后，你将无法使用 LinuxDo 登录。确定要继续吗？',
      '确认操作',
      { type: 'warning' }
    )
    
    unlinkingLinuxDo.value = true
    await unlinkLinuxDo()
    oauthStatus.value.linuxdo = null
    ElMessage.success('LinuxDo 账号已解除绑定')
  } catch (error) {
    if (error !== 'cancel') {
      ElMessage.error(error.response?.data?.detail || '解绑失败')
    }
  } finally {
    unlinkingLinuxDo.value = false
  }
}

// 分类名称映射
const categoryNames = {
  chat: '闲聊',
  deals: '羊毛',
  misc: '杂谈',
  tech: '技术',
  help: '求助',
  intro: '介绍',
  acg: 'ACG'
}

const getCategoryName = (key) => categoryNames[key] || '闲聊'

const formatTime = (time) => {
  if (!time) return ''
  return dayjs(time).format('MM-DD HH:mm')
}

const goToThread = (threadId) => {
  router.push(`/thread/${threadId}`)
}

const loadMyThreads = async (page = 1) => {
  loadingThreads.value = true
  try {
    const res = await getMyThreads({ page, page_size: 5 })
    myThreads.value = res
  } catch (error) {
    console.error('加载帖子失败', error)
  } finally {
    loadingThreads.value = false
  }
}

const loadMyReplies = async (page = 1) => {
  loadingReplies.value = true
  try {
    const res = await getMyReplies({ page, page_size: 5 })
    myReplies.value = res
  } catch (error) {
    console.error('加载回复失败', error)
  } finally {
    loadingReplies.value = false
  }
}

// 加载拉黑列表
const loadBlockList = async () => {
  loadingBlockList.value = true
  try {
    const res = await getBlockList()
    blockList.value = res
  } catch (error) {
    console.error('加载拉黑列表失败', error)
  } finally {
    loadingBlockList.value = false
  }
}

// 注销账号
const handleDeleteAccount = async () => {
  try {
    let password = null
    
    // 如果用户设置了密码，需要输入密码确认
    if (hasPassword.value) {
      const { value } = await ElMessageBox.prompt(
        '此操作不可撤销！你的账号将被永久删除，发布的内容将保留但作者显示为"已注销用户"。请输入密码以确认：',
        '注销账号',
        {
          confirmButtonText: '确认注销',
          cancelButtonText: '取消',
          inputType: 'password',
          inputPlaceholder: '请输入密码',
          inputValidator: (value) => {
            if (!value) return '请输入密码'
            return true
          }
        }
      )
      password = value
    } else {
      await ElMessageBox.confirm(
        '此操作不可撤销！你的账号将被永久删除，发布的内容将保留但作者显示为"已注销用户"。确定要继续吗？',
        '注销账号',
        {
          confirmButtonText: '确认注销',
          cancelButtonText: '取消',
          type: 'warning'
        }
      )
    }
    
    deletingAccount.value = true
    await deleteAccount(password)
    
    // 清除本地存储
    localStorage.removeItem('user_token')
    localStorage.removeItem('bot_token')
    
    ElMessage.success('账号已成功注销')
    router.push('/login')
  } catch (error) {
    if (error !== 'cancel') {
      ElMessage.error(error.response?.data?.detail || '注销失败')
    }
  } finally {
    deletingAccount.value = false
  }
}

// 初始化加载
loadUser()
checkOAuthConfig()
loadMyThreads(1)
loadMyReplies(1)
loadBlockList()
</script>

<style lang="scss" scoped>
.profile-page {
  max-width: 900px;
  margin: 0 auto;
  padding-bottom: 40px;
}

.page-header {
  margin-bottom: 32px;
  display: flex;
  align-items: center;
  gap: 24px;
  
  h1 {
    font-size: 32px;
    font-weight: 700;
    color: var(--text-primary);
    text-shadow: 0 0 10px rgba(255,255,255,0.2);
    letter-spacing: 1px;
  }
  
  .back-link {
    text-decoration: none;
  }
}

.profile-content {
  display: flex;
  flex-direction: column;
  gap: 32px;
}

/* 玻璃卡片 */
.glass-card {
  background: var(--glass-bg);
  backdrop-filter: blur(var(--blur-amount));
  border: 1px solid var(--glass-border);
  border-radius: var(--card-radius);
  box-shadow: var(--card-shadow);
  padding: 32px;
  position: relative;
  overflow: hidden;
}

.card-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 24px;
  border-bottom: 1px solid rgba(255, 255, 255, 0.05);
  padding-bottom: 16px;
  
  .section-title {
    font-size: 18px;
    font-weight: 700;
    color: var(--text-primary);
    letter-spacing: 1px;
  }
  
  .status-badge {
    background: rgba(30, 238, 62, 0.1);
    color: #1eee3e;
    padding: 4px 12px;
    border-radius: 4px;
    font-size: 12px;
    font-weight: 700;
    border: 1px solid rgba(30, 238, 62, 0.3);
  }
}

.section-title {
  font-size: 18px;
  font-weight: 700;
  color: var(--text-primary);
  margin-bottom: 24px;
  letter-spacing: 1px;
}

/* 头像部分 */
.avatar-section {
  display: flex;
  align-items: center; /* 垂直居中 */
  gap: 24px;
}

.avatar-tips {
  color: var(--text-secondary);
  font-size: 12px;
  font-family: monospace;
  padding: 10px 12px;
  border-radius: 12px;
  background: rgba(0, 0, 0, 0.25);
  border: 1px solid rgba(255, 255, 255, 0.08);
}

.avatar-wrapper {
  position: relative;
  width: 80px;
  height: 80px;
  border-radius: 50%;
  border: 2px solid var(--acid-green);
  /* padding: 2px;  去除 padding，让头像贴合边框 */
  cursor: pointer;
  overflow: hidden; /* 确保内容不溢出圆形 */
  box-shadow: 0 0 10px rgba(204, 255, 0, 0.2); /* 增加一点发光 */
  
  .avatar-preview {
    width: 100%;
    height: 100%;
    background: #000;
    display: block; /* 消除图片底部的空隙 */
  }
  
  .avatar-overlay {
    position: absolute;
    inset: 0;
    /* border-radius: 50%;  因为父容器已经 overflow: hidden，这里不需要了 */
    background: rgba(0, 0, 0, 0.7);
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    color: var(--acid-green);
    font-size: 10px;
    font-weight: 700;
    opacity: 0;
    transition: opacity 0.3s;
    
    .el-icon {
      font-size: 20px;
      margin-bottom: 4px;
    }
  }
  
  &:hover .avatar-overlay {
    opacity: 1;
  }
}

.avatar-input-wrapper {
  flex: 1;
  display: flex;
  flex-direction: column;
  gap: 8px;
  width: 100%; /* 确保占满剩余空间 */
}

/* 输入框容器 */
.input-box {
  background: rgba(0, 0, 0, 0.3);
  border-radius: 8px;
  padding: 4px;
  border: 1px solid transparent;
  transition: all 0.3s;
  width: 100%; /* 强制占满父容器 */
  
  &:focus-within {
    border-color: var(--acid-purple);
    box-shadow: 0 0 15px rgba(176, 38, 255, 0.1);
  }
  
  &.textarea-box {
    padding: 0;
    
    :deep(.el-textarea__inner) {
      background: transparent !important;
      box-shadow: none !important;
      color: #fff;
      font-family: monospace;
      padding: 16px; /* 增加内边距 */
      min-height: 160px !important; /* 再次增加高度 */
      height: 160px !important; /* 强制高度 */
      line-height: 1.6;
      width: 100%; /* 强制宽度 */
      resize: vertical; /* 允许垂直拉伸 */
      
      &::placeholder {
        color: var(--text-disabled);
      }
      
      &:focus {
        box-shadow: none !important;
      }
    }
  }
}

/* Token 显示 */
.warning-box {
  background: rgba(255, 171, 0, 0.1);
  color: #ffab00;
  padding: 12px;
  border-radius: 8px;
  font-size: 12px;
  font-family: monospace;
  margin-bottom: 16px;
  border: 1px solid rgba(255, 171, 0, 0.2);
}

.token-display {
  display: flex;
  gap: 12px;
  margin-bottom: 24px;
  align-items: flex-start; /* 对齐顶部，适应高度变化 */
  
  .token-box {
    flex: 1;
    background: #000;
    padding: 12px 16px;
    border-radius: 8px;
    border: 1px solid var(--glass-border);
    font-family: monospace;
    color: var(--acid-blue);
    display: flex;
    align-items: center;
    min-height: 42px; /* 保证最小高度 */
    word-break: break-all; /* 强制换行 */
    white-space: pre-wrap; /* 保留空白并允许换行 */
    line-height: 1.4;
  }
  
  .token-actions {
    display: flex;
    gap: 8px; /* 按钮间距 */
    flex-shrink: 0; /* 防止按钮被压缩 */
  }
  
  .icon-btn {
    width: 42px;
    height: 42px; /* 固定高度 */
    background: var(--glass-bg);
    border: 1px solid var(--glass-border);
    color: var(--text-primary);
    border-radius: 8px;
    cursor: pointer;
    transition: all 0.2s;
    display: flex;
    align-items: center;
    justify-content: center;
    
    &:hover {
      background: var(--glass-highlight);
      border-color: var(--acid-purple);
    }
  }
}

.regenerate-section {
  display: flex;
  align-items: center;
  gap: 16px;
}

/* 酸性按钮 */
.acid-btn {
  background: var(--acid-green);
  color: #000;
  border: none;
  padding: 10px 24px;
  font-size: 14px;
  font-weight: 700;
  cursor: pointer;
  display: inline-flex;
  align-items: center;
  gap: 8px;
  clip-path: polygon(10px 0, 100% 0, 100% calc(100% - 10px), calc(100% - 10px) 100%, 0 100%, 0 10px);
  transition: all 0.2s ease;
  text-transform: uppercase;
  letter-spacing: 1px;
  font-family: 'Space Grotesk', sans-serif;
  
  &:hover {
    transform: translate(-2px, -2px);
    box-shadow: 4px 4px 0 var(--acid-purple);
  }
  
  &.outline {
    background: transparent;
    border: 1px solid var(--acid-green);
    color: var(--acid-green);
    
    &:hover {
      background: rgba(204, 255, 0, 0.1);
    }
  }
  
  &.small {
    padding: 8px 16px;
    font-size: 12px;
    clip-path: none;
    border-radius: 4px;
  }
  
  &.danger {
    background: transparent;
    border: 1px solid #ff4d4f;
    color: #ff4d4f;
    
    &:hover {
      background: rgba(255, 77, 79, 0.1);
      box-shadow: 0 0 10px rgba(255, 77, 79, 0.3);
    }
  }
  
  &:disabled {
    opacity: 0.6;
    cursor: not-allowed;
  }
}

/* 覆盖 Element Plus 样式 */
:deep(.el-form-item__label) {
  color: var(--text-secondary);
  font-family: monospace;
  font-size: 12px;
}

:deep(.acid-input) {
  .el-input__wrapper {
    background: transparent !important;
    box-shadow: none !important;
    padding: 4px 8px;
  }
  
  .el-input__inner {
    color: #fff;
    font-family: monospace;
    &::placeholder {
      color: var(--text-disabled);
    }
  }

  .el-input__count {
    background: rgba(0, 0, 0, 0.25);
    border: 1px solid rgba(255, 255, 255, 0.12);
    border-radius: 10px;
    padding: 0 8px;
    height: 20px;
    line-height: 18px;
    color: var(--text-tertiary);
    font-family: monospace;
    font-size: 12px;
  }

  .el-input__count-inner {
    background: transparent;
    color: inherit;
  }
}

/* 我的帖子/回复卡片 */
.my-content-card {
  .card-header {
    display: flex;
    align-items: center;
    gap: 12px;
    margin-bottom: 16px;
    padding-bottom: 12px;
    border-bottom: 1px solid rgba(255, 255, 255, 0.05);
  }
  
  .count-badge {
    background: rgba(30, 238, 62, 0.15);
    color: var(--acid-green);
    padding: 2px 10px;
    border-radius: 12px;
    font-size: 12px;
    font-weight: 600;
  }
  
  .loading-placeholder {
    padding: 20px 0;
  }
  
  .empty-hint {
    color: var(--text-disabled);
    text-align: center;
    padding: 30px 0;
    font-size: 14px;
  }
  
  .content-list {
    list-style: none;
    padding: 0;
    margin: 0;
  }
  
  .content-item {
    padding: 12px 0;
    border-bottom: 1px solid rgba(255, 255, 255, 0.03);
    cursor: pointer;
    transition: all 0.2s;
    
    &:hover {
      background: rgba(255, 255, 255, 0.02);
      margin: 0 -16px;
      padding: 12px 16px;
    }
    
    &:last-child {
      border-bottom: none;
    }
  }
  
  .content-main {
    display: flex;
    align-items: center;
    gap: 8px;
    margin-bottom: 6px;
  }
  
  .category-tag {
    font-size: 11px;
    padding: 2px 6px;
    border-radius: 4px;
    background: rgba(255, 255, 255, 0.1);
    color: var(--text-secondary);
    
    &.tech { background: rgba(30, 238, 62, 0.15); color: var(--acid-green); }
    &.help { background: rgba(255, 100, 100, 0.15); color: #ff6464; }
    &.deals { background: rgba(255, 200, 50, 0.15); color: #ffc832; }
    &.acg { background: rgba(200, 100, 255, 0.15); color: #c864ff; }
  }
  
  .floor-tag {
    font-size: 11px;
    padding: 2px 6px;
    border-radius: 4px;
    background: rgba(30, 238, 62, 0.15);
    color: var(--acid-green);
    
    &.sub {
      background: rgba(255, 255, 255, 0.1);
      color: var(--text-secondary);
    }
  }
  
  .content-title {
    color: var(--text-primary);
    font-size: 14px;
    flex: 1;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  
  .reply-preview {
    font-size: 13px;
    color: var(--text-secondary);
    margin-bottom: 6px;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  
  .content-meta {
    display: flex;
    gap: 12px;
    font-size: 12px;
    color: var(--text-disabled);
  }
  
  .pagination-small {
    display: flex;
    align-items: center;
    justify-content: center;
    gap: 12px;
    margin-top: 16px;
    padding-top: 12px;
    border-top: 1px solid rgba(255, 255, 255, 0.05);
    
    .page-btn {
      background: rgba(255, 255, 255, 0.05);
      border: 1px solid rgba(255, 255, 255, 0.1);
      color: var(--text-secondary);
      padding: 4px 12px;
      border-radius: 4px;
      font-size: 12px;
      cursor: pointer;
      transition: all 0.2s;
      
      &:hover:not(:disabled) {
        background: rgba(30, 238, 62, 0.1);
        border-color: var(--acid-green);
        color: var(--acid-green);
      }
      
      &:disabled {
        opacity: 0.4;
        cursor: not-allowed;
      }
    }
    
    .page-info {
      font-size: 12px;
      color: var(--text-disabled);
    }
  }
}

/* OAuth 绑定卡片 */
.oauth-card {
  .oauth-list {
    display: flex;
    flex-direction: column;
    gap: 16px;
  }
  
  .oauth-item {
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding: 16px;
    background: rgba(0, 0, 0, 0.2);
    border-radius: 8px;
    border: 1px solid var(--glass-border);
  }
  
  .oauth-info {
    display: flex;
    align-items: center;
    gap: 16px;
  }
  
  .oauth-icon {
    width: 48px;
    height: 48px;
    border-radius: 12px;
    display: flex;
    align-items: center;
    justify-content: center;
    
    &.github {
      background: linear-gradient(135deg, #333 0%, #1a1a1a 100%);
      color: #fff;
    }
    
    &.linuxdo {
      background: linear-gradient(135deg, #f5a623 0%, #d4880f 100%);
      color: #fff;
    }
  }
  
  .oauth-details {
    display: flex;
    flex-direction: column;
    gap: 4px;
  }
  
  .oauth-name {
    color: #fff;
    font-weight: 500;
    font-size: 14px;
  }
  
  .oauth-username {
    color: var(--acid-green);
    font-family: monospace;
    font-size: 12px;
  }
  
  .oauth-unlinked {
    color: var(--text-secondary);
    font-size: 12px;
  }
}

/* 拉黑列表卡片 */
.blocklist-card {
  .blocklist-list {
    list-style: none;
    padding: 0;
    margin: 0;
  }
  
  .blocklist-item {
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding: 12px 0;
    border-bottom: 1px solid rgba(255, 255, 255, 0.03);
    
    &:last-child {
      border-bottom: none;
    }
  }
  
  .blocked-user-info {
    display: flex;
    align-items: center;
    gap: 12px;
  }
  
  .blocked-user-details {
    display: flex;
    flex-direction: column;
    gap: 2px;
  }
  
  .blocked-user-name {
    color: var(--text-primary);
    font-size: 14px;
    font-weight: 500;
  }
  
  .blocked-user-username {
    color: var(--text-disabled);
    font-size: 12px;
    font-family: monospace;
  }
  
  .blocked-time {
    color: var(--text-disabled);
    font-size: 12px;
  }
  
  .blocklist-hint {
    display: flex;
    align-items: flex-start;
    gap: 8px;
    padding: 12px;
    background: rgba(255, 255, 255, 0.03);
    border-radius: 6px;
    margin-top: 16px;
    
    .el-icon {
      color: var(--text-disabled);
      font-size: 14px;
      flex-shrink: 0;
      margin-top: 2px;
    }
    
    span {
      color: var(--text-disabled);
      font-size: 12px;
      line-height: 1.5;
    }
  }
}

/* 危险操作卡片 */
.danger-card {
  .danger-title {
    color: #ff4d4f;
  }
  
  .danger-content {
    display: flex;
    flex-direction: column;
    gap: 20px;
  }
  
  .danger-warning {
    display: flex;
    align-items: flex-start;
    gap: 12px;
    padding: 16px;
    background: rgba(255, 77, 79, 0.1);
    border: 1px solid rgba(255, 77, 79, 0.3);
    border-radius: 8px;
    
    .el-icon {
      color: #ff4d4f;
      font-size: 20px;
      flex-shrink: 0;
      margin-top: 2px;
    }
    
    .warning-text {
      flex: 1;
    }
    
    .warning-title {
      color: #ff4d4f;
      font-weight: 600;
      font-size: 14px;
      margin: 0 0 8px 0;
    }
    
    .warning-desc {
      color: var(--text-secondary);
      font-size: 13px;
      line-height: 1.6;
      margin: 0;
    }
  }
}

/* 无密码提示 */
.no-password-hint {
  display: flex;
  align-items: flex-start;
  gap: 10px;
  padding: 16px;
  background: rgba(204, 255, 0, 0.1);
  border: 1px solid rgba(204, 255, 0, 0.3);
  border-radius: 8px;
  margin-bottom: 24px;
  
  .el-icon {
    color: var(--acid-green);
    font-size: 18px;
    flex-shrink: 0;
    margin-top: 2px;
  }
  
  span {
    color: var(--text-secondary);
    font-size: 13px;
    line-height: 1.5;
  }
}

@media (max-width: 768px) {
  .page-header {
    flex-direction: column;
    align-items: flex-start;
    gap: 16px;
    
    h1 {
      font-size: 28px;
    }
  }
  
  .glass-card {
    padding: 20px;
  }
  
  .avatar-section {
    flex-direction: column;
    align-items: center;
    gap: 16px;
    
    .avatar-tips {
      text-align: center;
    }
  }

  .token-display {
    flex-direction: column;
    align-items: stretch;
    
    .token-box {
      margin-bottom: 8px;
    }
    
    .token-actions {
      justify-content: flex-end;
    }
  }
  
  .oauth-item {
    flex-direction: column;
    align-items: flex-start;
    gap: 16px;
    
    .oauth-actions {
      width: 100%;
      
      button {
        width: 100%;
      }
    }
  }
  
  /* Form responsiveness */
  ::v-deep(.el-form-item) {
    display: flex;
    flex-direction: column;
    align-items: stretch;
    
    .el-form-item__label {
      text-align: left;
      justify-content: flex-start;
      margin-bottom: 4px;
      width: auto !important;
    }
    
    .el-form-item__content {
      margin-left: 0 !important;
    }
  }
}
</style>
