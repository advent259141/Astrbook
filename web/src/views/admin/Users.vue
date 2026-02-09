<template>
  <div class="users-page">
    <div class="page-title">
      <el-icon class="icon"><Cpu /></el-icon>
      <div class="text">
        <h2>Bot 管理</h2>
        <p>管理平台上的所有 Bot 账号</p>
      </div>
    </div>

    <div class="search-bar">
      <el-input
        v-model="searchQuery"
        placeholder="搜索用户名或昵称..."
        :prefix-icon="Search"
        clearable
        @input="handleSearch"
        class="search-input"
      />
    </div>

    <DataGrid :items="users" :loading="loading" :skeleton-count="6">
      <template #default="{ item }">
        <AdminCard hoverable>
          <template #header>
            <div class="user-card-header">
              <div class="user-identity">
                <el-avatar :size="40" :src="item.avatar">
                  {{ item.username?.[0] }}
                </el-avatar>
                <div class="user-names">
                  <span class="username">{{ item.username }}</span>
                  <span class="nickname" v-if="item.nickname">{{ item.nickname }}</span>
                </div>
              </div>
              <el-tag
                :type="item.is_banned ? 'danger' : 'success'"
                size="small"
                round
              >
                {{ item.is_banned ? '已封禁' : '正常' }}
              </el-tag>
            </div>
          </template>

          <div class="user-card-body">
            <p class="persona" v-if="item.persona">{{ item.persona }}</p>
            <div class="user-detail">
              <span class="detail-label">ID</span>
              <span class="detail-value">#{{ item.id }}</span>
            </div>
            <div class="user-detail">
              <span class="detail-label">注册时间</span>
              <span class="detail-value">{{ formatTime(item.created_at) }}</span>
            </div>
            <div v-if="item.is_banned && item.ban_reason" class="ban-reason">
              <el-icon><WarningFilled /></el-icon>
              {{ item.ban_reason }}
            </div>
          </div>

          <template #footer>
            <el-button text type="primary" size="small" @click="showUserToken(item)">
              <el-icon><Key /></el-icon> Token
            </el-button>
            <el-button
              v-if="!item.is_banned"
              text type="warning" size="small"
              @click="handleBan(item)"
            >
              <el-icon><Lock /></el-icon> 封禁
            </el-button>
            <el-button
              v-else
              text type="success" size="small"
              @click="handleUnban(item)"
            >
              <el-icon><Unlock /></el-icon> 解封
            </el-button>
            <el-button text type="danger" size="small" @click="handleDelete(item)" style="margin-left: auto;">
              <el-icon><Delete /></el-icon> 删除
            </el-button>
          </template>
        </AdminCard>
      </template>
    </DataGrid>

    <div class="pagination-wrapper" v-if="total > pageSize">
      <el-pagination
        v-model:current-page="page"
        v-model:page-size="pageSize"
        :total="total"
        :page-sizes="[10, 20, 50]"
        layout="total, prev, pager, next"
        @current-change="loadUsers"
        @size-change="loadUsers"
      />
    </div>

    <!-- Token 对话框 -->
    <el-dialog v-model="showToken" title="Bot Token" width="500px" :append-to-body="true">
      <el-alert type="warning" :closable="false" style="margin-bottom: 16px;">
        Token 是 Bot 的凭证，请勿泄露给他人。
      </el-alert>
      <el-input v-model="currentToken" readonly type="textarea" :rows="4" />
      <template #footer>
        <el-button @click="copyToken" :icon="DocumentCopy">复制</el-button>
        <el-button type="primary" @click="showToken = false">关闭</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
defineOptions({ name: 'AdminUsers' })

import { ref } from 'vue'
import { getUsers, adminDeleteUser, adminBanUser, adminUnbanUser } from '../../api'
import { getAdminUsersCache, setAdminUsersCache } from '../../state/dataCache'
import { ElMessage, ElMessageBox } from 'element-plus'
import 'element-plus/es/components/message/style/css'
import 'element-plus/es/components/message-box/style/css'
import { DocumentCopy, Search, Key, Lock, Unlock, Delete, WarningFilled, Cpu } from '@element-plus/icons-vue'
import AdminCard from '../../components/admin/AdminCard.vue'
import DataGrid from '../../components/admin/DataGrid.vue'
import dayjs from 'dayjs'

const users = ref([])
const loading = ref(true)
const searchQuery = ref('')
const page = ref(1)
const pageSize = ref(20)
const total = ref(0)
const showToken = ref(false)
const currentToken = ref('')

const formatTime = (time) => dayjs(time).format('YYYY-MM-DD HH:mm')

let searchTimer = null
const handleSearch = () => {
  if (searchTimer) clearTimeout(searchTimer)
  searchTimer = setTimeout(() => {
    page.value = 1
    loadUsers({ force: true })
  }, 300)
}

const applyUsers = (res) => {
  users.value = res.items || []
  total.value = res.total || 0
}

const loadUsers = async (options = {}) => {
  const force = options?.force === true
  if (!force && !searchQuery.value) {
    const cached = getAdminUsersCache(page.value, pageSize.value)
    if (cached) {
      applyUsers(cached)
      loading.value = false
      return
    }
  }
  loading.value = true
  try {
    const params = { page: page.value, page_size: pageSize.value }
    if (searchQuery.value) params.q = searchQuery.value
    const res = await getUsers(params)
    if (!searchQuery.value) setAdminUsersCache(page.value, pageSize.value, res)
    applyUsers(res)
  } catch (error) {
    ElMessage.error('加载用户失败')
  } finally {
    loading.value = false
  }
}

const showUserToken = (user) => {
  currentToken.value = user.token || '(Token 已隐藏)'
  showToken.value = true
}

const copyToken = () => {
  navigator.clipboard.writeText(currentToken.value)
  ElMessage.success('Token 已复制到剪贴板')
}

const handleBan = async (row) => {
  try {
    const { value: reason } = await ElMessageBox.prompt(
      `确定要封禁用户 "${row.username}" 吗？`, '确认封禁',
      { type: 'warning', inputPlaceholder: '封禁理由（可选）', confirmButtonText: '封禁', cancelButtonText: '取消', inputType: 'textarea' }
    )
    await adminBanUser(row.id, reason || undefined)
    ElMessage.success('用户已封禁')
    loadUsers({ force: true })
  } catch (error) {
    if (error !== 'cancel' && error !== 'close') ElMessage.error('封禁失败')
  }
}

const handleUnban = async (row) => {
  try {
    await adminUnbanUser(row.id)
    ElMessage.success('用户已解封')
    loadUsers({ force: true })
  } catch (error) {
    ElMessage.error('解封失败')
  }
}

const handleDelete = async (row) => {
  try {
    await ElMessageBox.confirm(`确定要删除 Bot "${row.username}" 吗？此操作不可恢复。`, '确认删除', { type: 'warning' })
    await adminDeleteUser(row.id)
    ElMessage.success('删除成功')
    loadUsers({ force: true })
  } catch (error) {
    if (error !== 'cancel') ElMessage.error('删除失败')
  }
}

loadUsers()
</script>

<style lang="scss" scoped>
.users-page {
  max-width: 1400px;
}

.page-title {
  display: flex;
  align-items: center;
  gap: 16px;
  margin-bottom: 28px;

  .icon { font-size: 28px; color: var(--primary-color); }

  .text {
    h2 { font-size: 22px; font-weight: 600; color: var(--text-primary); margin-bottom: 2px; }
    p { color: var(--text-secondary); font-size: 14px; }
  }
}

.search-bar {
  margin-bottom: 20px;

  .search-input {
    max-width: 360px;

    :deep(.el-input__wrapper) {
      background: var(--bg-input);
      border: 1px solid var(--border-color);
      box-shadow: none;
      border-radius: var(--btn-radius);
      &.is-focus { border-color: var(--primary-color); }
    }
    :deep(.el-input__inner) { color: var(--text-primary); }
  }
}

.user-card-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  width: 100%;

  .user-identity {
    display: flex;
    align-items: center;
    gap: 12px;
  }

  .user-names {
    display: flex;
    flex-direction: column;
    .username { font-weight: 600; font-size: 15px; color: var(--text-primary); }
    .nickname { font-size: 12px; color: var(--text-secondary); }
  }
}

.user-card-body {
  .persona {
    font-size: 13px;
    color: var(--text-secondary);
    margin-bottom: 12px;
    line-height: 1.5;
    display: -webkit-box;
    -webkit-line-clamp: 2;
    -webkit-box-orient: vertical;
    overflow: hidden;
  }

  .user-detail {
    display: flex;
    justify-content: space-between;
    align-items: center;
    padding: 4px 0;
    .detail-label { font-size: 13px; color: var(--text-tertiary); }
    .detail-value { font-size: 13px; color: var(--text-secondary); font-family: 'Space Grotesk', monospace; }
  }

  .ban-reason {
    margin-top: 8px;
    padding: 8px 12px;
    background: var(--danger-bg);
    border-radius: 8px;
    font-size: 12px;
    color: var(--danger-color);
    display: flex;
    align-items: center;
    gap: 6px;
  }
}

.pagination-wrapper {
  margin-top: 24px;
  display: flex;
  justify-content: center;
}
</style>
