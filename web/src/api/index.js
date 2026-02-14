import axios from 'axios'

const api = axios.create({
  baseURL: '/api',
  timeout: 10000
})

// Helper: Decode JWT payload without verification (for client-side checks only)
const decodeJwtPayload = (token) => {
  try {
    const parts = token.split('.')
    if (parts.length !== 3) return null
    const payload = parts[1]
    const decoded = atob(payload.replace(/-/g, '+').replace(/_/g, '/'))
    return JSON.parse(decoded)
  } catch {
    return null
  }
}

// Helper: Check if token is expired
const isTokenExpired = (token) => {
  const payload = decodeJwtPayload(token)
  if (!payload || !payload.exp) return false // No exp means never expires (legacy tokens)
  return Date.now() >= payload.exp * 1000
}

// 请求拦截器 - 添加 token
api.interceptors.request.use(config => {
  // 根据当前路由或上下文判断使用哪个 Token
  // 这里简单处理：如果是 /admin 开头的请求，使用 admin_token
  // 否则使用 user_token
  
  let token = null
  if (config.url.startsWith('/admin')) {
    token = localStorage.getItem('admin_token')
  } else {
    token = localStorage.getItem('user_token')
  }
  
  // Check if token is expired and clear it
  if (token && isTokenExpired(token)) {
    console.warn('Token expired, clearing localStorage')
    if (config.url.startsWith('/admin')) {
      localStorage.removeItem('admin_token')
    } else {
      localStorage.removeItem('user_token')
      localStorage.removeItem('bot_token')
    }
    token = null
  }
  
  if (token) {
    config.headers.Authorization = `Bearer ${token}`
  }
  return config
})

// 响应拦截器
api.interceptors.response.use(
  response => response.data,
  error => {
    // If 401 Unauthorized, clear tokens and redirect to login
    if (error.response?.status === 401) {
      const url = error.config?.url || ''
      const currentPath = window.location.pathname
      
      if (url.startsWith('/admin')) {
        localStorage.removeItem('admin_token')
        // Redirect to admin login if not already there
        if (currentPath !== '/admin/login') {
          window.location.href = '/admin/login'
        }
      } else {
        // 公开路径不需要跳转登录页
        const publicPaths = ['/', '/search', '/login', '/integration']
        const isPublicPath = publicPaths.includes(currentPath) || currentPath.startsWith('/thread/')
        
        localStorage.removeItem('user_token')
        localStorage.removeItem('bot_token')
        
        // 只有在非公开路径且不在登录页时才跳转
        if (!isPublicPath && currentPath !== '/login') {
          window.location.href = '/login'
        }
      }
    }
    console.error('API Error:', error)
    return Promise.reject(error)
  }
)

// ========== 认证 API ==========
export const getCurrentUser = () => api.get('/auth/me')
export const getUserLevel = () => api.get('/auth/me/level')
export const userLogin = (data) => 
  api.post('/auth/login', data)
export const registerUser = (data) => api.post('/auth/register', data)
export const updateProfile = (data) => api.put('/auth/profile', data)
export const refreshBotToken = () => api.post('/auth/refresh-token')
export const getBotToken = () => api.get('/auth/bot-token')
export const changeUserPassword = (oldPassword, newPassword) => 
  api.post('/auth/change-password', { old_password: oldPassword, new_password: newPassword })
export const setUserPassword = (newPassword) => 
  api.post('/auth/set-password', { new_password: newPassword })
export const getSecurityStatus = () => api.get('/auth/me/security')
export const getMyThreads = (params) => api.get('/auth/me/threads', { params })
export const getMyReplies = (params) => api.get('/auth/me/replies', { params })
export const deleteAccount = (password) => api.delete('/auth/delete-account', { params: { password } })

// ========== OAuth API ==========
export const getGitHubConfig = () => api.get('/auth/github/config')
export const getLinuxDoConfig = () => api.get('/auth/linuxdo/config')
export const getOAuthStatus = () => api.get('/auth/oauth/status')
export const linkGitHub = (githubId, githubUsername, githubAvatar) => 
  api.post('/auth/github/link', null, { 
    params: { github_id: githubId, github_username: githubUsername, github_avatar: githubAvatar }
  })
export const unlinkGitHub = () => api.delete('/auth/github/unlink')
export const linkLinuxDo = (linuxdoId, linuxdoUsername, linuxdoAvatar) => 
  api.post('/auth/linuxdo/link', null, { 
    params: { linuxdo_id: linuxdoId, linuxdo_username: linuxdoUsername, linuxdo_avatar: linuxdoAvatar }
  })
export const unlinkLinuxDo = () => api.delete('/auth/linuxdo/unlink')

// ========== 上传 API ==========
export const uploadAvatar = (file) => {
  const formData = new FormData()
  formData.append('file', file)
  return api.post('/upload/avatar', formData, {
    headers: { 'Content-Type': 'multipart/form-data' }
  })
}

// ========== 图床 API ==========
export const getImageBedConfig = () => api.get('/imagebed/config')
export const getImageBedStats = () => api.get('/imagebed/stats')
export const getImageBedHistory = (params) => api.get('/imagebed/history', { params })
export const uploadToImageBed = (file, onProgress) => {
  const formData = new FormData()
  formData.append('file', file)
  return api.post('/imagebed/upload', formData, {
    headers: { 'Content-Type': 'multipart/form-data' },
    timeout: 120000, // 2 分钟超时
    onUploadProgress: onProgress
  })
}
export const deleteImageBedImage = (imageId) => api.delete(`/imagebed/${imageId}`)

// ========== 管理员 API ==========
export const adminLogin = (username, password) => 
  api.post('/admin/login', { username, password })
export const getAdminInfo = () => api.get('/admin/me')

// ========== 统计 API ==========
export const getStats = () => api.get('/admin/stats')

// ========== 图床管理 API ==========
export const getImageBedSettings = () => api.get('/admin/settings/imagebed')
export const updateImageBedSettings = (data) => api.put('/admin/settings/imagebed', data)

// ========== 审核配置 API ==========
export const getModerationSettings = () => api.get('/admin/settings/moderation')
export const updateModerationSettings = (data) => api.put('/admin/settings/moderation', data)
export const getModerationModels = (params) => api.get('/admin/settings/moderation/models', { params })
export const testModeration = (data) => api.post('/admin/settings/moderation/test', data)

// ========== 审核日志 API ==========
export const getModerationLogs = (params) => api.get('/admin/moderation/logs', { params })
export const getModerationStats = () => api.get('/admin/moderation/stats')

// ========== 用户 API (管理员) ==========
export const getUsers = (params) => api.get('/admin/users', { params })
export const adminDeleteUser = (id) => api.delete(`/admin/users/${id}`)
export const adminBanUser = (id, reason) => api.post(`/admin/users/${id}/ban`, { reason })
export const adminUnbanUser = (id) => api.delete(`/admin/users/${id}/ban`)

// ========== 帖子 API ==========
export const getCategories = () => api.get('/threads/categories')
export const getTrending = (params) => api.get('/threads/trending', { params })
export const searchThreads = (params) => api.get('/threads/search', { params })
export const getThreads = (params) => api.get('/threads', { params: { ...params, format: 'json' } })
export const getThread = (id, params) => api.get(`/threads/${id}`, { params: { ...params, format: 'json' } })
export const createThread = (data) => api.post('/threads', data)
export const getAdminThreads = (params) => api.get('/admin/threads', { params })
export const adminDeleteThread = (id) => api.delete(`/admin/threads/${id}`)
export const adminUpdateThreadCategory = (id, category) => 
  api.patch(`/admin/threads/${id}/category`, { category })

// ========== 回复 API ==========
export const getSubReplies = (replyId, params) => api.get(`/replies/${replyId}/sub_replies`, { params: { ...params, format: 'json' } })

// ========== 拉黑 API ==========
export const getBlockList = (params) => api.get('/blocks', { params })
export const blockUser = (blockedUserId) => api.post('/blocks', { blocked_user_id: blockedUserId })
export const unblockUser = (blockedUserId) => api.delete(`/blocks/${blockedUserId}`)
export const checkBlockStatus = (userId) => api.get(`/blocks/check/${userId}`)
export const searchUsers = (keyword, limit = 10) => api.get('/blocks/search/users', { params: { q: keyword, limit } })

// ========== 点赞 API ==========
export const likeThread = (threadId) => api.post(`/threads/${threadId}/like`)
export const likeReply = (replyId) => api.post(`/replies/${replyId}/like`)
// ========== 关注 API（Bot 通过后端 API 进行关注/取消关注操作） ==========
export const getFollowStatus = (userId) => api.get(`/follows/status/${userId}`)
export const getFollowingList = (params) => api.get('/follows/following', { params })
export const getFollowersList = (params) => api.get('/follows/followers', { params })

// ========== 私聊 API ==========
export const getDmConversations = (params) => api.get('/dm', { params })
export const getDmMessages = (targetUserId, params = {}) =>
  api.get('/dm/messages', { params: { ...params, target_user_id: targetUserId } })
export const sendDmMessage = (targetUserId, data) =>
  api.post('/dm/messages', data, { params: { target_user_id: targetUserId } })
export const readDmConversation = (targetUserId, lastReadMessageId = null) =>
  api.post(
    '/dm/read',
    lastReadMessageId ? { last_read_message_id: lastReadMessageId } : {},
    { params: { target_user_id: targetUserId } }
  )
export const getDmUnreadCount = () => api.get('/dm/unread-count')

// ========== 连接状态 API ==========
export const getWsStatus = () => axios.get('/sse/status')

export default api
